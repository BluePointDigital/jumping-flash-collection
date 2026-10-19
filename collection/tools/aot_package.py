"""Fail closed when audited AOT artifacts do not match the installed runtime."""
from pathlib import Path
import json
import re
import subprocess
from import_game import sha
from cache_identity import namespace,compiler_module


def artifact_path(cache,name):
    if not isinstance(name,str) or not re.fullmatch(r'(?:seg-(?:kuseg|kseg1)/)?[0-9A-Fa-f]{8}_[0-9A-Fa-f]{8}\.dll',name):
        raise ValueError('Unsafe AOT artifact path')
    path=Path(cache)/name
    if Path(cache).resolve() not in path.resolve().parents:raise ValueError('AOT artifact escapes cache')
    return path


def verify_runtime_limits(root):
    root=Path(root);path=root/'toolchain/include/collection_overlay_limits.json'
    if not path.exists():return None
    limits=json.loads(path.read_text())
    compiler=compiler_module(root/'toolchain')
    capacity=compiler.overlay_candidate_cap(str(root/'toolchain/include'))
    if capacity!=limits.get('candidate_capacity'):raise ValueError('Collection loader/publisher capacity mismatch')
    return limits


def verify_runtime_executable(root,executable):
    """Reject a mixed loader/publisher budget before importing a test cache."""
    limits=verify_runtime_limits(root)
    if limits is None:return None
    executable=Path(executable).resolve()
    if b'--collection-runtime-info' not in executable.read_bytes():
        raise ValueError('Runtime lacks --collection-runtime-info; use a matching collection build')
    try:
        result=subprocess.run([str(executable),'--collection-runtime-info'],cwd=Path(root),
            capture_output=True,text=True,timeout=60,
            creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0),check=True)
        info=json.loads(result.stdout)
    except (OSError,subprocess.SubprocessError,ValueError) as error:
        raise ValueError(f'Cannot verify runtime resource contract: {executable.name}: {error}') from error
    expected={'overlay_limits_schema':limits['schema'],'overlay_limits_profile':limits['profile'],
        'overlay_candidate_capacity':limits['candidate_capacity']}
    if (not isinstance(info,dict) or any(info.get(key)!=value for key,value in expected.items()) or
        type(info.get('overlay_capacity_tables_bytes')) is not int or info['overlay_capacity_tables_bytes']<=0):
        raise ValueError('Runtime executable and publisher resource contract differ; rebuild them together or select a matching test root')
    return info


def _audited_pair_capacity_inventory(cache,compiler,pairs):
    """Count already-audited pairs without invoking compiler recovery paths."""
    required=('parse_runtime_shard_manifest','cache_dir_segment',
        '_normalized_runtime_manifest_identity','_candidate_group_identity',
        '_runtime_manifest_range_link_count')
    if any(not hasattr(compiler,name) for name in required):
        raise ValueError('Cannot inventory the installed loader/publisher capacity')
    cache=Path(cache).resolve();seen_paths=set();seen_groups=set()
    candidate_groups=raw_rows=range_links=0
    for pair in pairs:
        dll=artifact_path(cache,pair.get('dll'))
        manifest_path=dll.with_suffix('.ranges')
        if cache not in manifest_path.resolve().parents:
            raise ValueError('Audited AOT manifest escapes cache')
        key=str(dll.resolve())
        if key in seen_paths:raise ValueError('Duplicate audited AOT pair path')
        seen_paths.add(key)
        try:
            def fingerprint(path):
                stat=path.stat()
                return (stat.st_dev,stat.st_ino,stat.st_size,stat.st_mtime_ns,
                    getattr(stat,'st_ctime_ns',None))
            before=(fingerprint(dll),fingerprint(manifest_path))
            dll_hash_before=sha(dll);manifest_hash_before=sha(manifest_path)
            manifest=manifest_path.read_text(encoding='ascii')
            dll_hash_after=sha(dll);manifest_hash_after=sha(manifest_path)
            after=(fingerprint(dll),fingerprint(manifest_path))
        except (OSError,UnicodeError) as error:
            raise ValueError(f'Audited AOT pair changed or is unreadable: {pair.get("dll")}') from error
        if (before!=after or dll_hash_before!=pair.get('dll_sha256') or
            dll_hash_after!=pair.get('dll_sha256') or
            manifest_hash_before!=pair.get('manifest_sha256') or
            manifest_hash_after!=pair.get('manifest_sha256')):
            raise ValueError(f'Audited AOT pair changed during capacity verification: {pair.get("dll")}')
        pair_id,funcs=compiler.parse_runtime_shard_manifest(
            manifest,require_pair=False,
            expected_segment=compiler.cache_dir_segment(str(dll.parent)))
        if not funcs:
            raise ValueError(f'Audited AOT manifest is not runtime-admissible: {pair.get("dll")}')
        identity=compiler._normalized_runtime_manifest_identity(
            manifest,pair_id,funcs)
        group=compiler._candidate_group_identity(str(dll.parent),identity)
        if group is None or group not in seen_groups:
            candidate_groups+=len(funcs)
        if group is not None:seen_groups.add(group)
        raw_rows+=len(funcs)
        range_links+=compiler._runtime_manifest_range_link_count(funcs)
    return candidate_groups,raw_rows,range_links,len(seen_paths)


def verify_candidate_capacity(root,cache,limits,manifest_rows,audit_pairs=None):
    """Count the loader's shared manifest groups, retaining physical limits."""
    cap=limits['candidate_capacity'] if limits else 32768
    if not limits:
        if manifest_rows<=cap:return None
        raise ValueError('Audited cache exceeds the installed loader/publisher capacity')
    if not audit_pairs:
        raise ValueError('Audited AOT pair inventory is missing for capacity verification')
    compiler=compiler_module(Path(root)/'toolchain')
    total,raw,links,files=_audited_pair_capacity_inventory(cache,compiler,audit_pairs)
    if (raw!=manifest_rows or total>cap or raw>2*cap or
        links>2*cap*8 or files>compiler.RUNTIME_CACHE_FILE_CAP):
        raise ValueError('Audited cache exceeds or differs from the installed loader/publisher capacity inventory')
    return dict(candidate_groups=total,raw_manifest_rows=raw,range_links=links,files=files)


def verified_abi_markers(root,cache,audit,provenance):
    """Reuse audited ABI checks only for complete, byte-identical directories."""
    if (type(audit.get('flavor')) is not int or audit['flavor']!=0 or
        audit.get('all_pairs_valid') is not True or audit.get('all_guards_match_known_input_bytes') is not True):return []
    provenance=Path(provenance);toolchain=Path(root)/'toolchain';api=toolchain/'include/overlay_api.h'
    if (not provenance.is_file() or sha(provenance)!=audit.get('guidance_provenance_sha256') or not api.is_file()):return []
    identity=json.loads(provenance.read_text(encoding='utf-8'))
    if identity.get('preparation_tools',{}).get('overlay_api_sha256')!=sha(api):return []
    compiler=compiler_module(toolchain)
    abi=compiler.overlay_abi_tag(str(toolchain/'include'),0)
    groups={};cache=Path(cache)
    for pair in audit['pairs']:
        dll=artifact_path(cache,pair['dll'])
        groups.setdefault(dll.parent,[]).append((dll,pair))
    markers=[]
    for directory,pairs in groups.items():
        # Supplemental or interrupted publications have not passed this audit.
        actual={p.name.casefold() for p in directory.iterdir() if p.is_file() and p.suffix.lower()=='.dll'}
        if actual!={p.name.casefold() for p,_ in pairs}:continue
        valid=True
        for dll,pair in pairs:
            files=[(dll,pair['dll_sha256']),(dll.with_suffix('.ranges'),pair['manifest_sha256'])]
            if pair.get('resident_sha256'):files.append((dll.with_suffix('.resident'),pair['resident_sha256']))
            elif dll.with_suffix('.resident').exists():valid=False;break
            if any(not p.is_file() or sha(p)!=expected for p,expected in files):valid=False;break
        if not valid:continue
        # The runtime still checks overlay_abi before registering a used DLL.
        marker=directory/f'.abi_{abi:08x}.ok'
        marker.write_bytes(b'');markers.append(marker.relative_to(cache).as_posix())
    return markers


def verify_aot(root,game,preparation=None):
    root=Path(root)
    base=Path(preparation) if preparation else root/'data/games'/game['id']/'cache'
    audit_path=base/'AOT_CACHE_AUDIT.json'
    if not audit_path.is_file():raise ValueError(f'{game["id"]}: audited AOT cache missing; prepare this game before release')
    audit=json.loads(audit_path.read_text())
    disc_recipes=audit.get('disc_recipe_count',audit.get('recipe_count'))
    bios_recipes=audit.get('bios_recipe_count',0)
    game_recipes=audit.get('game_installed_recipe_count',0)
    bios_rows=[row for row in audit.get('image_coverage',[]) if row.get('producer')=='bios_resident_manifest']
    game_rows=[row for row in audit.get('image_coverage',[]) if row.get('producer')=='verified_game_installed_code']
    limits=verify_runtime_limits(root)
    relative=namespace(root,game)
    if (audit.get('game_id')!=game['serial'] or audit.get('cache_tag')!=relative.name or
        audit.get('all_pairs_valid') is not True or audit.get('all_guards_match_known_input_bytes') is not True or
        not audit.get('pairs') or audit.get('published_pairs')!=len(audit['pairs']) or
        disc_recipes!={'jf1':16,'jf2':28,'robbit':81}.get(game['id']) or
        not isinstance(bios_recipes,int) or bios_recipes<0 or bios_recipes!=len(bios_rows) or
        not isinstance(game_recipes,int) or game_recipes<0 or game_recipes!=len(game_rows) or
        audit.get('recipe_count')!=disc_recipes+bios_recipes+game_recipes or
        audit.get('recipe_count')!=len(audit.get('image_coverage',[]))):
        raise ValueError(f'{game["id"]}: AOT audit identity or provenance is incomplete')
    if any(row.get('bios_sha256')!=game.get('bios_sha256') or not row.get('bios_sha256') for row in bios_rows):
        raise ValueError('AOT resident recipe does not match the imported BIOS')
    if audit.get('guidance_provenance_sha256'):
        provenance=base/('provenance.json' if preparation else 'AOT_PROVENANCE.json')
        if not provenance.is_file() or sha(provenance)!=audit['guidance_provenance_sha256']:
            raise ValueError('Audited preparation provenance missing or changed')
        if preparation or game_recipes:
            identity=json.loads(provenance.read_text(encoding='utf-8'))
            if identity.get('game')!=game['id'] or identity.get('disc_sha256')!=game['disc_sha256']:
                raise ValueError('Audited preparation input disc differs from this installation')
            if bios_recipes and (len(identity.get('bios_installed',[]))!=bios_recipes or
                any(item.get('bios_sha256')!=game['bios_sha256'] for item in identity['bios_installed'])):
                raise ValueError('Audited preparation BIOS constructor provenance is incomplete')
            source_hashes={item.get('source_sha256') for item in identity.get('inputs',[])}
            constructed=identity.get('game_installed',[])
            if (len(constructed)!=game_recipes or any(not item.get('source_executable_sha256') or
                item['source_executable_sha256'] not in source_hashes for item in constructed) or
                any(row.get('source_executable_sha256') not in source_hashes for row in game_rows)):
                raise ValueError('Installed game code source is absent from the verified disc inventory')
            if any(item.get('source_executable_sha256') and item['source_executable_sha256'] not in source_hashes
                   for item in identity.get('bios_installed',[])):
                raise ValueError('SDK resident code source is absent from the verified disc inventory')
    elif preparation:raise ValueError('External preparation requires audited provenance')
    cache=base/('cache' if preparation else '')/relative
    for pair in audit['pairs']:
        name=pair['dll']
        dll=artifact_path(cache,name);manifest=dll.with_suffix('.ranges')
        if (not dll.is_file() or not manifest.is_file() or sha(dll)!=pair['dll_sha256'] or
            sha(manifest)!=pair['manifest_sha256']):raise ValueError(f'{game["id"]}: audited AOT pair missing or changed: {name}')
        if pair.get('resident_sha256'):
            marker=dll.with_suffix('.resident')
            if not marker.is_file() or sha(marker)!=pair['resident_sha256']:raise ValueError('AOT resident metadata changed')
            if bios_recipes and json.loads(marker.read_text(encoding='utf-8')).get('bios_sha256')!=game['bios_sha256']:
                raise ValueError('AOT resident marker names a different BIOS')
    capacity=verify_candidate_capacity(root,cache,limits,audit['manifest_rows'],audit['pairs'])
    return dict(cache_tag=audit['cache_tag'],recipes=audit['recipe_count'],pairs=len(audit['pairs']),
        guarded_manifest_entries=audit['manifest_rows'],audit_sha256=sha(audit_path),
        capacity_inventory=capacity,semantic_qualification=False)


def seed_preparation(root,game,data,preparation):
    """Copy only independently audited pairs into a new probe's private cache."""
    import shutil
    preparation=Path(preparation)
    receipt=verify_aot(root,game,preparation)
    proof=Path(data)/'static-preparation';proof.mkdir(parents=True,exist_ok=False)
    for name in ('AOT_CACHE_AUDIT.json','provenance.json'):shutil.copy2(preparation/name,proof/name)
    relative=namespace(root,game);destination=Path(data)/'cache'/relative
    destination.mkdir(parents=True,exist_ok=True)
    audit=json.loads((preparation/'AOT_CACHE_AUDIT.json').read_text(encoding='utf-8'))
    for pair in audit['pairs']:
        dll=artifact_path(preparation/'cache'/relative,pair['dll'])
        target=artifact_path(destination,pair['dll']);target.parent.mkdir(parents=True,exist_ok=True)
        for source in (dll,dll.with_suffix('.ranges')):
            shutil.copy2(source,target.with_suffix(source.suffix))
        resident=dll.with_suffix('.resident')
        if pair.get('resident_sha256'):shutil.copy2(resident,target.with_suffix('.resident'))
        elif target.with_suffix('.resident').exists():target.with_suffix('.resident').unlink()
    markers=verified_abi_markers(root,destination,audit,preparation/'provenance.json')
    receipt.update(source=str(preparation.resolve()),namespace=relative.as_posix(),retained_proof=str(proof.resolve()),
        verified_abi_markers=markers)
    return receipt
