"""Verify the portable executable/tool bundle, independently of its location."""
from pathlib import Path
import argparse
import json
import hashlib
import ntpath
import os
import sys
import tomllib
sys.path.insert(0,str(Path(__file__).resolve().parent))
from import_game import sha,verify
from cache_identity import namespace

WINDOWS_MAX_PATH_CHARS = 260

def validate_windows_path_budget(root, relative_paths, *, windows=None):
    """Reject paths the Windows runtime cannot reliably discover."""
    if windows is None:
        windows = os.name == 'nt'
    if not windows:
        return
    for name in relative_paths:
        absolute = ntpath.normpath(ntpath.join(os.fspath(root), os.fspath(name)))
        if len(absolute) >= WINDOWS_MAX_PATH_CHARS:
            raise ValueError(
                f'Windows package path is {len(absolute)} characters (limit is '
                f'{WINDOWS_MAX_PATH_CHARS - 1}): {absolute}; move the package to '
                'a shorter folder so every bundled path is below 260 characters')

def check(root,with_games=False,require_aot=False,runtime_contract=False,require_audited_native_cache=False):
    if require_audited_native_cache and not require_aot:
        raise ValueError('The native-cache inventory gate requires the ordinary AOT audit')
    root=root.resolve();manifest=json.loads((root/'package-manifest.json').read_text())
    if manifest.get('schema')!=1:raise ValueError('Unsupported package manifest')
    validate_windows_path_budget(root, manifest['files'])
    checked=0
    for name,record in manifest['files'].items():
        relative=Path(name)
        if relative.is_absolute() or relative.drive or '..' in relative.parts:raise ValueError('Unsafe manifest path')
        path=root/relative
        if not path.is_file() or path.stat().st_size!=record['bytes'] or sha(path)!=record['sha256']:
            raise ValueError(f'Package file missing or changed: {name}')
        checked+=1
    catalog=tomllib.loads((root/'catalog.toml').read_text(encoding='utf-8'))
    from aot_package import verify_runtime_limits,verify_runtime_executable
    limits=verify_runtime_limits(root)
    if limits:
        build=json.loads((root/'build-receipt.json').read_text())
        package=json.loads((root/'package-receipt.json').read_text())
        if build.get('sources',{}).get('collection/runtime/collection_overlay_limits.h')!=limits.get('source_sha256'):
            raise ValueError('Collection resource profile source receipt mismatch')
        for game in catalog['games']:
            if build.get('runtime_limits',{}).get(game['id'])!=limits or package['games'][game['id']].get('runtime_limits')!=limits:
                raise ValueError('Per-game loader/publisher resource contract mismatch')
        if runtime_contract:
            if os.name!='nt':raise ValueError('Run native contract checks with Windows Python, including under Proton')
            for game in catalog['games']:
                executable=root/game['executable']
                info=verify_runtime_executable(root,executable)
                print(f'PASS: {game["id"]} native resource contract, {info["overlay_candidate_capacity"]} slots, {info["overlay_capacity_tables_bytes"]} table bytes')
    for game in catalog['games']:
        config_path=root/game['config'];config=tomllib.loads(config_path.read_text(encoding='utf-8'))
        boot=(config_path.parent/config['game']['exe']).resolve()
        if not boot.is_relative_to(config_path.parent) or not boot.is_file():raise ValueError(f'{game["id"]}: boot executable escaped its game folder')
        disc=Path(config['game']['disc'])
        if disc.is_absolute() or not (config_path.parent/disc).resolve().is_relative_to(root):raise ValueError('Non-portable configured disc path')
        if with_games:verify(root,game)
        if require_aot:
            from aot_package import verify_aot
            audit_raw=None
            if require_audited_native_cache:
                audit_raw=(root/'data/games'/game['id']/'cache/AOT_CACHE_AUDIT.json').read_bytes()
            audit=verify_aot(root,game)
            if require_audited_native_cache:
                from aot_release_inventory import verify_release_cache_inventory
                if hashlib.sha256(audit_raw).hexdigest()!=audit['audit_sha256']:
                    raise ValueError(f'{game["id"]}: AOT audit changed while verifying its cache inventory')
                audit_document=json.loads(audit_raw)
                inventory=verify_release_cache_inventory(
                    root/'data/games'/game['id']/'cache',
                    namespace(root,game),
                    audit_document['pairs'])
                print(f'PASS: {game["id"]} audited cache inventory, {inventory["audited_dlls"]} DLLs and {inventory["audited_sidecars"]} sidecars')
            print(f'PASS: {game["id"]} {audit["pairs"]} audited AOT pairs, {audit["recipes"]} recipes')
    print(f'PASS: {checked} portable package files, per-game boot isolation and relative disc paths')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,default=Path(__file__).resolve().parents[1]);parser.add_argument('--games',action='store_true');parser.add_argument('--aot',action='store_true');parser.add_argument('--runtime-contract',action='store_true');parser.add_argument('--require-audited-native-cache',action='store_true',help='Strictly inventory active-namespace DLLs for a complete release; does not establish semantic or campaign qualification');args=parser.parse_args()
    try:check(args.root,args.games,args.aot,args.runtime_contract,args.require_audited_native_cache)
    except Exception as error:print(f'Package verification failed: {error}',file=sys.stderr);raise SystemExit(1)
