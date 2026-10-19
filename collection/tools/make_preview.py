"""Freeze a private owner-test folder and CRC-checked ZIP without stale caches."""
from pathlib import Path
import argparse
import datetime
import json
import re
import shutil
import zipfile
from import_game import sha
from verify_package import check

ROOT=Path(__file__).resolve().parents[1]
NAME='JumpingFlash-Collectors-Edition-Preview-0.3.0'

def make(source,destination,archive):
    source=source.resolve();destination=destination.resolve();archive=archive.resolve()
    if destination.exists() or archive.exists() or source==destination or source in destination.parents:
        raise ValueError('Choose new output paths outside the source package; existing previews are preserved')
    check(source,True,True,True)
    header=(source/'toolchain/include/overlay_api.h').read_text()
    version=int(re.search(r'#define PSX_OVERLAY_CODEGEN_VER (\d+)',header)[1])
    codegen=json.loads((source/'package-manifest.json').read_text())['compiler_codegen_hash']
    cache_prefix=f'cg{version}_{codegen}_'
    audit=json.loads((source/'data/games/jf1/cache/AOT_CACHE_AUDIT.json').read_text())
    if not audit['cache_tag'].startswith(cache_prefix) or not audit['all_pairs_valid'] or not audit['all_guards_match_known_input_bytes']:
        raise ValueError('JF1 needs an audited AOT cache matching this runtime ABI before freezing an owner preview')
    def include(path):
        rel=path.relative_to(source)
        if '__pycache__' in rel.parts or path.is_symlink():return False
        if rel.parts[0]=='data':
            if any(p in ('states','savestates','logs') for p in rel.parts):return False
            if 'overlay_captures.json.d' in rel.parts or path.name.startswith('psx_freeze_'):return False
            if path.name=='psx_last_run_report.json':return False
            if path.suffix in ('.log','.tmp','.pair-lock','.c') or path.name=='overlay_captures.json':return False
            variants=[p for p in rel.parts if re.match(r'cg\d+_',p)]
            if variants and any(not p.startswith(cache_prefix) for p in variants):return False
        return path.is_file()
    files=[p for p in sorted(source.rglob('*')) if include(p)]
    total=sum(p.stat().st_size for p in files)
    destination.parent.mkdir(parents=True,exist_ok=True);archive.parent.mkdir(parents=True,exist_ok=True)
    if shutil.disk_usage(destination.parent).free<total*2+1024**3:raise ValueError('Insufficient space for folder, ZIP and working margin')
    for path in files:
        target=destination/path.relative_to(source);target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(path,target)
    check(destination,True,True,True)
    frozen=[p for p in sorted(destination.rglob('*')) if p.is_file()]
    temporary=archive.with_suffix('.zip.partial')
    if temporary.exists():raise ValueError('An interrupted archive already exists; preserve it before retrying')
    started=datetime.datetime.now(datetime.timezone.utc)
    print(f'Freezing {len(frozen)} files, {total/1024**3:.2f} GiB; active cache ABI {cache_prefix}',flush=True)
    with zipfile.ZipFile(temporary,'w',compression=zipfile.ZIP_DEFLATED,compresslevel=5,allowZip64=True) as output:
        for path in frozen:output.write(path,destination.name+'/'+path.relative_to(destination).as_posix())
    with zipfile.ZipFile(temporary) as output:
        bad=output.testzip()
        if bad:raise ValueError(f'Archive CRC verification failed: {bad}')
        if len(output.infolist())!=len(frozen):raise ValueError('Archive file count changed')
    temporary.rename(archive)
    receipt=dict(schema=1,release=json.loads((source/'package-manifest.json').read_text())['release'],private_owner_test=True,qualification_complete=False,
        created_utc=started.isoformat(),source=str(source),folder=str(destination),archive=str(archive),
        archive_sha256=sha(archive),archive_bytes=archive.stat().st_size,installed_bytes=total,
        file_count=len(frozen),archive_crc_verified=True,game_hashes_verified=True,
        active_cache_prefix=cache_prefix,experimental_runtime_states_copied=False,
        hardware_proton_qualified=False)
    archive.with_suffix('.json').write_text(json.dumps(receipt,indent=2))
    archive.with_suffix('.sha256').write_text(receipt['archive_sha256']+'  '+archive.name+'\n')
    print(json.dumps(receipt,indent=2),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source',type=Path,default=ROOT/'dist')
    parser.add_argument('--folder',type=Path,default=ROOT/'releases'/NAME)
    parser.add_argument('--archive',type=Path,default=ROOT/'releases'/(NAME+'.zip'));args=parser.parse_args()
    make(args.source,args.folder,args.archive)
