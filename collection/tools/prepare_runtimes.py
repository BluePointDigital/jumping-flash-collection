"""Build collection adapters from private source snapshots; preserve standalone builds."""
from pathlib import Path
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
from runtime_adapter import adapt
from patch_compiler import patch,patch_runtime
from patch_performance import patch as patch_performance
from patch_static import patch as patch_static
from patch_aot_audit import patch as patch_aot_audit
from patch_emitter import patch as patch_emitter
from patch_trace_storage import patch_trace_storage
from patch_host_messages import patch as patch_host_messages

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
TOOLCHAIN=REPO/'.jf2-workbench/recomp/toolchain'
PROJECTS={
    'jf1':(REPO/'jumping-flash-1/.workbench','OpenBIOS;SCPH1001'),
    'jf2':(REPO/'.jf2-workbench/recomp/JumpingFlash2Recomp','OpenBIOS;SCPH5552'),
    'robbit':(REPO/'robbit-mon-dieu/.workbench','OpenBIOS;SCPH5500'),
}

def run(args,log,env):
    result=subprocess.run([str(a) for a in args],stdout=log,stderr=subprocess.STDOUT,env=env)
    if result.returncode:raise RuntimeError(f'Build failed ({result.returncode}); inspect {log.name}')

def _native_target(game,native_root=None):
    if game not in PROJECTS:raise ValueError(f'unknown game: {game}')
    base=Path(native_root) if native_root is not None else ROOT/'.workbench/native'
    target=(base/game).resolve()
    for original,_bios in PROJECTS.values():
        source_root=Path(original).resolve()
        target_key=os.path.normcase(str(target))
        source_key=os.path.normcase(str(source_root))
        try:
            common=os.path.commonpath((target_key,source_key))
        except ValueError:
            continue
        if common==target_key or common==source_key:
            raise ValueError(f'native target overlaps standalone source: {target} <-> {source_root}')
    return target


def prepare(game,source_only=False,jf1_family_source=False,native_root=None):
    if native_root is not None and not source_only:
        raise ValueError('--native-root requires --source-only; emitter builds remain tied to the default native workspace')
    source,bios=PROJECTS[game]
    if jf1_family_source and game!='jf1':raise ValueError('--jf1-family-source is JF1-only')
    target=_native_target(game,native_root)
    family_root=target/'psxrecomp/runtime/jf1_family'
    family_main=target/'psxrecomp/runtime/src/main.cpp'
    family_marked=family_main.is_file() and 'JF1_F4354_FAMILY_MAIN_V2' in family_main.read_text(encoding='utf-8')
    if jf1_family_source and not source_only:raise ValueError('--jf1-family-source is source-only; run palette preparation after AOT')
    if jf1_family_source and (family_root.exists() or family_marked):raise ValueError('JF1 family opt-in requires a fresh private target')
    if not jf1_family_source and (family_root.exists() or family_marked):raise ValueError('existing JF1 family target cannot be reset by the default prepare path; use a fresh private target')
    target.mkdir(parents=True,exist_ok=True)
    ignore=shutil.ignore_patterns('.git','.cache','build','build-*','__pycache__')
    for directory in ['psxrecomp','recomp-ui','generated']:
        destination=target/directory
        if not destination.exists():shutil.copytree(source/directory,destination,ignore=ignore)
    if (source/'desktop').exists():shutil.copytree(source/'desktop',target/'desktop',dirs_exist_ok=True)
    if game=='robbit':
        # Keep the standalone snapshot intact while the collection uses the
        # maintained adapter and its exact per-request control profiles.
        shutil.copy2(REPO/'robbit-mon-dieu/tools/robbit_desktop.h',target/'desktop/robbit_desktop.h')
    if game=='jf2':
        shutil.copy2(REPO/'tools/recomp/jf2_desktop.h',target/'desktop/jf2_desktop.h')
    shutil.copy2(source/'CMakeLists.txt',target/'CMakeLists.txt')
    # The small boot executable guards the linked native code. Disc data stays in its existing owner folder.
    import tomllib
    config=tomllib.loads((source/'game.toml').read_text(encoding='utf-8'))
    boot=Path(config['game']['exe'])
    original=source/boot
    if not original.exists() and game=='jf2':original=REPO/'.jf2-workbench/recomp/disc'/boot.name
    if not original.exists():raise FileNotFoundError(original)
    local_boot=Path('disc')/boot.name
    (target/local_boot).parent.mkdir(parents=True,exist_ok=True);shutil.copy2(original,target/local_boot)
    config_text=(source/'game.toml').read_text(encoding='utf-8')
    config_text=re.sub(r'(?m)^exe\s*=\s*"[^"]+"\s*$', 'exe = '+json.dumps(local_boot.as_posix()),config_text,count=1)
    if game=='robbit':
        from robbit_profiles import hook_config
        config_text=hook_config(config_text)
    if game=='jf2':
        from jf2_profiles import hook_config
        config_text=hook_config(config_text)
    (target/'game.toml').write_text(config_text,encoding='utf-8')
    cmake=(target/'CMakeLists.txt').read_text(encoding='utf-8')
    # Source-only callers configure later, so retain the title's BIOS defaults.
    cmake='set(PSXRECOMP_BIOS_STEMS "'+bios+'" CACHE STRING "Recompiled BIOS backends")\n'+cmake
    cmake+='\ntarget_include_directories(psx-runtime PRIVATE "'+(ROOT/'runtime').as_posix()+'")\n'
    cmake+='target_compile_definitions(psx-runtime PRIVATE COLLECTION_RUNTIME=1)\n'
    cmake+='target_sources(psx-runtime PRIVATE "'+(ROOT/'runtime/collection_metrics.c').as_posix()+'")\n'
    cmake+='target_sources(psx-runtime PRIVATE "'+(ROOT/'runtime/collection_static.c').as_posix()+'")\n'
    if game=='jf1':cmake+='target_compile_definitions(psx-runtime PRIVATE JF1_DESKTOP=1)\n'
    (target/'CMakeLists.txt').write_text(cmake,encoding='utf-8')
    main=target/'psxrecomp/runtime/src/main.cpp'
    if game=='jf1':
        text=main.read_text(encoding='utf-8')
        text=re.sub(r'defined\(JF2_DESKTOP\) \|\| defined\(ROBBIT_DESKTOP\)(?: \|\| defined\(JF1_DESKTOP\))*',
            'defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP) || defined(JF1_DESKTOP)',text)
        main.write_text(text,encoding='utf-8')
    patch_trace_storage(target/'psxrecomp',game)
    adapt(target/'psxrecomp')
    patch(target/'psxrecomp/tools/compile_overlays.py')
    patch_runtime(target/'psxrecomp')
    patch_performance(target/'psxrecomp')
    patch_static(target/'psxrecomp')
    patch_aot_audit(target/'psxrecomp')
    patch_emitter(target/'psxrecomp')
    patch_host_messages(target,game)
    if jf1_family_source:
        from family_promotion import prepare_family_sources
        prepare_family_sources(target/'psxrecomp',ROOT/'runtime',target/'CMakeLists.txt')
    limits_header=ROOT/'runtime/collection_overlay_limits.h'
    limits_text=limits_header.read_text()
    capacity=int(re.search(r'#define COLLECTION_OVERLAY_CANDIDATE_CAP (\d+)',limits_text)[1])
    schema=int(re.search(r'#define COLLECTION_OVERLAY_LIMITS_SCHEMA (\d+)',limits_text)[1])
    api=(target/'psxrecomp/runtime/include/overlay_api.h').read_text()
    abi=int(re.search(r'#define PSX_OVERLAY_ABI_VERSION (\d+)',api)[1])
    limits=dict(schema=schema,profile='collection-v1',candidate_capacity=capacity,abi_version=abi,
        source_sha256=hashlib.sha256(limits_header.read_bytes()).hexdigest())
    (target/'psxrecomp/runtime/include/collection_overlay_limits.json').write_text(json.dumps(limits,indent=2)+'\n')
    if source_only:
        print(f'Collection native sources prepared without compilation: {game} -> {target}',flush=True)
        return target
    env=dict(os.environ,PATH=str(TOOLCHAIN/'bin')+os.pathsep+os.environ['PATH'],PSXRECOMP_TOOLCHAIN_DIR=str(TOOLCHAIN))
    build=target/'build'
    logs=ROOT/'.workbench/evidence';logs.mkdir(parents=True,exist_ok=True)
    cmake_exe=TOOLCHAIN/'bin/cmake.exe'
    with (logs/f'build-{game}.log').open('w',encoding='utf-8') as log:
        run([cmake_exe,'-S',target,'-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
             '-DCMAKE_C_COMPILER='+str(TOOLCHAIN/'bin/clang.exe'),'-DCMAKE_CXX_COMPILER='+str(TOOLCHAIN/'bin/clang++.exe'),
             '-DPSX_DEBUG_TOOLS=ON','-DPSX_ENABLE_VULKAN=OFF','-DPSX_REWIND=OFF','-DPSXRECOMP_REQUIRE_GAME_C=ON',
             '-DPSXRECOMP_BIOS_STEMS='+bios,'-DPSX_SHELLWIN_INTERP=ON'],log,env)
        run([cmake_exe,'--build',build,'--target','psx-runtime','-j8'],log,env)
    print(f'Collection native adapter built: {game} -> {build}',flush=True)

def build_emitters():
    framework=ROOT/'.workbench/native/jf1/psxrecomp'
    if not framework.exists():raise ValueError('Prepare JF1 before the shared compiler')
    env=dict(os.environ,PATH=str(TOOLCHAIN/'bin')+os.pathsep+os.environ['PATH'])
    cmake=TOOLCHAIN/'bin/cmake.exe';build=ROOT/'.workbench/emitters'
    with (ROOT/'.workbench/evidence/build-emitters.log').open('w',encoding='utf-8') as log:
        run([cmake,'-S',framework/'recompiler','-B',build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',
            '-DCMAKE_C_COMPILER='+str(TOOLCHAIN/'bin/clang.exe'),'-DCMAKE_CXX_COMPILER='+str(TOOLCHAIN/'bin/clang++.exe'),
            '-DPSXRECOMP_STATIC_CLI=ON','-DPSXRECOMP_ENABLE_CHD=OFF','-DBUILD_TESTING=OFF'],log,env)
        run([cmake,'--build',build,'--target','psxrecomp-game','psxrecomp-bios','psxrecomp-analyze','-j8'],log,env)
    hashes={game:(ROOT/'.workbench/native'/game/'psxrecomp/runtime/include/overlay_codegen_hash.h').read_text() for game in PROJECTS}
    if len(set(hashes.values()))!=1:raise ValueError('Per-game emitters differ; separate toolchain profiles are required')
    (ROOT/'.workbench/evidence/compiler-abi.json').write_text(json.dumps(dict(schema=1,game_codegen_headers=hashes,
        compiler_codegen_hash=subprocess.check_output([str(build/'psxrecomp-game.exe'),'--codegen-hash'],text=True).strip()),indent=2))

def main(argv=None):
    parser=argparse.ArgumentParser();parser.add_argument('--game',choices=list(PROJECTS),action='append')
    parser.add_argument('--source-only',action='store_true',help='Stage private source/config adapters without native or emitter compilation')
    parser.add_argument('--native-root',type=Path,help='write per-game targets below this root; requires --source-only')
    parser.add_argument('--jf1-family-source',action='store_true',help='opt into the exact-guarded JF1 family source bundle; palette connection remains post-AOT')
    args=parser.parse_args(argv)
    if args.native_root is not None and not args.source_only:
        parser.error('--native-root requires --source-only; emitter builds remain tied to the default native workspace')
    selected=args.game or list(PROJECTS)
    if args.jf1_family_source and selected!=['jf1']:parser.error('--jf1-family-source requires exactly --game jf1')
    for game in selected:prepare(game,args.source_only,args.jf1_family_source,args.native_root)
    if not args.source_only:build_emitters()
    return 0


if __name__=='__main__':
    raise SystemExit(main())
