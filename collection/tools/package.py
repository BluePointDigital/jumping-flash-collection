"""Stage a relocatable private collection; originals and existing saves stay intact."""
from pathlib import Path
import argparse
import hashlib
import json
import shutil
import tomllib
import re
import datetime
from import_game import game_from_catalog,import_disc,import_bios,import_card,sha
from patch_compiler import patch
from aot_package import verify_aot,verified_abi_markers
from cache_identity import namespace

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
SOURCES={
    'jf1': REPO/'jumping-flash-1/.workbench',
    'jf2': REPO/'.jf2-workbench/recomp/JumpingFlash2Recomp',
    'robbit': REPO/'robbit-mon-dieu/.workbench',
}

def copy(source,target):
    if not source.is_file():raise FileNotFoundError(source)
    if target.is_file() and source.stat().st_size==target.stat().st_size and sha(source)==sha(target):return
    target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(source,target)

def stage(output,local_import=False,migrate=False,seed_package=None):
    output=output.resolve();output.mkdir(parents=True,exist_ok=True)
    if seed_package:
        from verify_package import check
        seed_package=seed_package.resolve()
        if seed_package==output or seed_package in output.parents:raise ValueError('Seed and output packages must be separate')
        check(seed_package,True)
    copy(ROOT/'.workbench/build/JumpingFlashCollection.exe',output/'JumpingFlashCollection.exe')
    copy(ROOT/'catalog.toml',output/'catalog.toml')
    shutil.copytree(ROOT/'assets/artwork',output/'assets/artwork',dirs_exist_ok=True)
    for filename in ['import_game.py','diagnostics.py','headless_smoke.py','input_probe.py','graphics_probe.py','cache_identity.py','aot_package.py','aot_release_inventory.py','performance_probe.py','static_gate.py','strict_input_probe.py']:
        copy(ROOT/'tools'/filename,output/'tools'/filename)
    copy(REPO/'robbit-mon-dieu/tools/diagnostics.py',output/'tools/runtime_diagnostics.py')
    shared=REPO/'robbit-mon-dieu/.workbench'
    copy(REPO/'robbit-mon-dieu/tools/prepare.py',output/'tools/bps.py')
    copy(shared/'psxrecomp/tools/psx_chd.py',output/'tools/psx_chd.py')
    copy(shared/'build-recompiler/libchdr.dll',output/'tools/libchdr.dll')
    patches=list((shared/'translation').rglob('*.bps'))
    if len(patches)!=1:raise ValueError('Expected one verified English patch')
    copy(patches[0],output/'tools/Robbit-English-v0.4.bps')
    for source,name in [('LatoLatin-Regular.ttf','body.ttf'),('LatoLatin-Bold.ttf','heading.ttf')]:
        copy(shared/'recomp-ui/assets/common/fonts'/source,output/'assets/fonts'/name)
    notices=output/'notices';notices.mkdir(exist_ok=True)
    (notices/'menu-bitmap-font.txt').write_text('Collection menu bitmap glyphs: public-domain font8x8_basic, reused from the pinned PSXRecomp host OSD.\nSource: https://github.com/d7samurai/font8x8\nAtlas rasterization and proportional layout: collection/src/menu_style.h.\n',encoding='utf-8')
    for directory,prefix in [(shared/'recomp-ui','recomp-ui'),(shared/'psxrecomp','psxrecomp')]:
        for license in directory.glob('LICENSE*'):copy(license,notices/(prefix+'-'+license.name))
    for file in (shared/'recomp-ui/assets/common/fonts').glob('*LICENSE*'):copy(file,notices/file.name)
    for file in (shared/'recomp-ui/assets/common/fonts').glob('*OFL*'):copy(file,notices/file.name)
    copy(shared/'recomp-ui/assets/common/fonts/NOTICE.md',notices/'fonts-NOTICE.md')
    toolchain=output/'toolchain'
    if not toolchain.exists():shutil.copytree(REPO/'jumping-flash-1/.workbench/build/overlay_toolchain',toolchain)
    patch(toolchain/'compile_overlays.py')
    include=ROOT/'.workbench/native/jf1/psxrecomp/runtime/include'
    for file in include.rglob('*'):
        if file.is_file():copy(file,toolchain/'include'/file.relative_to(include))
    for name in ['psxrecomp-game.exe','psxrecomp-bios.exe']:copy(ROOT/'.workbench/emitters'/name,toolchain/name)
    # Clang needs its own executable, resource headers, CRT and MinGW import libraries.
    clang=toolchain/'clang';source_compiler=REPO/'.jf2-workbench/recomp/toolchain'
    for directory in ['include','lib','x86_64-w64-mingw32']:
        if not (clang/directory).exists():shutil.copytree(source_compiler/directory,clang/directory)
    for file in (source_compiler/'bin').glob('*.dll'):copy(file,clang/'bin'/file.name)
    for name in ['clang.exe','clang-22.exe','ld.lld.exe','llvm-ar.exe']:
        copy(source_compiler/'bin'/name,clang/'bin'/name)
    for file in (source_compiler/'bin').glob('*.cfg'):copy(file,clang/'bin'/file.name)
    (toolchain/'compiler.txt').write_text('clang/bin/clang.exe\n',encoding='utf-8')
    catalog=tomllib.loads((ROOT/'catalog.toml').read_text(encoding='utf-8'))
    receipt={'schema':1,'release':'test-preview-0.3.0','qualification_complete':False,'games':{}}
    for game in catalog['games']:
        identity=game['id'];source=SOURCES[identity]
        derivative=ROOT/'.workbench/native'/identity
        build=derivative/'build';exe=Path(game['executable']).name
        copy(build/exe,output/game['executable'])
        runtime=output/'runtime'/identity
        for dll in build.glob('*.dll'):copy(dll,runtime/dll.name)
        if (build/'mods').exists():shutil.copytree(build/'mods',runtime/'mods',dirs_exist_ok=True)
        config=tomllib.loads((derivative/'game.toml').read_text(encoding='utf-8'))
        boot=Path(config['game']['exe']);copy(derivative/boot,runtime/boot)
        # CLI selects mounted data; retain relative boot/config paths for native code guards.
        text=(derivative/'game.toml').read_text(encoding='utf-8')
        text=re.sub(r'(?m)^disc\s*=\s*".*"\s*$', 'disc = '+json.dumps('../../'+game['disc']),text,count=1)
        (runtime/'game.toml').write_text(text,encoding='utf-8')
        legacy=output/'runtime/disc'/boot.name
        if identity=='jf2' and legacy.is_file() and sha(legacy)==sha(runtime/boot):
            legacy.unlink()
            if not any(legacy.parent.iterdir()):legacy.parent.rmdir()
        data=output/'data/games'/identity;data.mkdir(parents=True,exist_ok=True)
        audit_root=ROOT/'.workbench/aot'/identity
        if identity=='jf1' and not (audit_root/'AOT_CACHE_AUDIT.json').exists():audit_root=REPO/'jumping-flash-1/.workbench/aot'
        audit_path=audit_root/'AOT_CACHE_AUDIT.json'
        if audit_path.exists():
            audit=json.loads(audit_path.read_text())
            if not audit['all_pairs_valid'] or not audit['all_guards_match_known_input_bytes']:
                raise ValueError(f'{identity}: AOT provenance audit is incomplete')
            relative=Path(audit['game_id'])/'gcc/win-x64'/audit['cache_tag']
            aot=audit_root/'cache'/relative
            for pair in audit['pairs']:
                from aot_package import artifact_path
                native=artifact_path(aot,pair['dll']);manifest=native.with_suffix('.ranges')
                if sha(native)!=pair['dll_sha256'] or sha(manifest)!=pair['manifest_sha256']:raise ValueError(f'{identity}: audited cache pair changed')
                target=artifact_path(data/'cache'/relative,pair['dll'])
                copy(native,target);copy(manifest,target.with_suffix('.ranges'))
                if pair.get('resident_sha256'):copy(native.with_suffix('.resident'),target.with_suffix('.resident'))
            copy(audit_path,data/'cache/AOT_CACHE_AUDIT.json')
            if (audit_root/'provenance.json').exists():copy(audit_root/'provenance.json',data/'cache/AOT_PROVENANCE.json')
        aot_receipt=verify_aot(output,game)
        supplemental=[]
        if seed_package:
            old_game=game_from_catalog(seed_package,identity)
            relative=namespace(output,game)
            if (old_game['serial']==game['serial'] and old_game['disc_sha256']==game['disc_sha256'] and
                namespace(seed_package,old_game)==relative):
                old_cache=seed_package/'data/games'/identity/'cache'/relative
                for dll in sorted(old_cache.rglob('*.dll')):
                    manifest=dll.with_suffix('.ranges')
                    if not manifest.is_file():continue
                    destination=data/'cache'/relative/dll.relative_to(old_cache)
                    if destination.exists():continue # Audited output wins over supplemental runtime captures.
                    copied=[]
                    for part in (dll,manifest,dll.with_suffix('.resident')):
                        if part.is_file():
                            target=destination.with_suffix(part.suffix);copy(part,target)
                            copied.append(dict(path=target.relative_to(data/'cache').as_posix(),sha256=sha(target)))
                    supplemental.append(dict(dll=destination.name,files=copied))
                (data/'cache/COMPATIBLE_SEED.json').write_text(json.dumps(dict(schema=1,
                    source_package_manifest_sha256=sha(seed_package/'package-manifest.json'),
                    cache_tag=relative.name,static_aot_qualification=False,
                    policy='Exact compatible namespace; retain live-byte/ABI guards; audited artifacts take precedence',
                    pairs=supplemental),indent=2))
        preferences=data/'settings.toml'
        if not preferences.exists():
            # Preview defaults stay on qualified paths; graphics gates enable the enhanced preset later.
            preferences.write_text('[desktop]\ncontrol_style = "modern"\nmouse_sensitivity = 100\ninvert_y = false\n'
                '[video]\nrenderer = "opengl"\naspect_ratio = "4:3"\ninternal_resolution = 1080\ndynamic_resolution = false\nrender_thread = true\n'
                'frame_generation = false\nframe_interpolation = false\ngeometry_correction = false\nperspective_texturing = false\n'
                '[controller]\np1_device = "keyboard"\np1_mode = "digital"\n'
                '[launcher]\nskip_launcher = true\n',encoding='utf-8')
        if local_import:
            original=source/('disc/original' if identity in ('jf1','robbit') else '../disc')
            if identity=='jf2':original=REPO/'.jf2-workbench/recomp/disc'
            bins=list(original.glob('*.bin'))
            if len(bins)!=1:raise ValueError(f'Expected one prepared disc for {identity}')
            import_disc(output,game,bins[0])
            bios_path=source/'psxrecomp/bios'/Path(game['bios']).name
            import_bios(output,game,bios_path)
        if migrate:
            ledger=data/'save-migration.json'
            migration=json.loads(ledger.read_text(encoding='utf-8')) if ledger.exists() else {}
            cards=migration.get('cards',{})
            for index in [1,2]:
                old=source/'saves'/f'card{index}.mcd';new=data/'saves'/old.name
                if old.exists() and not new.exists():
                    expected=sha(old)
                    import_card(output,game,old,index)
                    if sha(old)!=expected or sha(new)!=expected:raise ValueError('Memory card migration mismatch')
                    cards[old.name]=dict(bytes=new.stat().st_size,source_sha256=expected,
                        destination_sha256=sha(new),original_preserved=True)
            ledger.write_text(json.dumps(dict(schema=2,originals_preserved=True,
                runtime_states_migrated=False,cards=cards),indent=2),encoding='utf-8')
        gallery=data/'gallery';gallery.mkdir(exist_ok=True)
        for image in (source/'evidence').glob('gallery-*.png'):copy(image,gallery/image.name)
        if identity=='jf1' and (source/'evidence/first-gameplay.png').exists():copy(source/'evidence/first-gameplay.png',gallery/'01-first-level.png')
        aot_receipt['verified_abi_markers']=verified_abi_markers(output,data/'cache'/relative,audit,data/'cache/AOT_PROVENANCE.json')
        receipt['games'][identity]={'executable_sha256':sha(runtime/exe),'aot':aot_receipt,'supplemental_seed_pairs':len(supplemental),'qualified_widescreen':game['widescreen_qualified'],
                                  'qualified_smooth_60':game['smooth_60_qualified'],'qualified_modern_gamepad':game['modern_gamepad_qualified']}
        receipt['games'][identity]['runtime_limits']=json.loads((ROOT/'.workbench/native'/identity/'psxrecomp/runtime/include/collection_overlay_limits.json').read_text())
    (output/'package-receipt.json').write_text(json.dumps(receipt,indent=2),encoding='utf-8')
    copy(ROOT/'RELEASE-GATES.md',output/'RELEASE-GATES.md')
    copy(ROOT/'README.md',output/'README.md')
    copy(ROOT/'STEAM-DECK-TEST.md',output/'STEAM-DECK-TEST.md')
    if (ROOT/'.workbench/evidence/build-receipt.json').exists():
        copy(ROOT/'.workbench/evidence/build-receipt.json',output/'build-receipt.json')
    shutil.copytree(ROOT/'compatibility',output/'compatibility',dirs_exist_ok=True)
    copy(ROOT/'tools/verify_package.py',output/'tools/verify_package.py')
    manifest=dict(schema=1,release='test-preview-0.3.0',created_utc=datetime.datetime.now(datetime.timezone.utc).isoformat(),
        compiler_codegen_hash=json.loads((ROOT/'.workbench/evidence/compiler-abi.json').read_text())['compiler_codegen_hash'],files={})
    for file in sorted(output.rglob('*')):
        if not file.is_file():continue
        relative=file.relative_to(output)
        if relative.parts[0]=='data' or file.name=='package-manifest.json' or '__pycache__' in relative.parts:continue
        manifest['files'][relative.as_posix()]=dict(bytes=file.stat().st_size,sha256=sha(file))
    (output/'package-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Collection package staged: {output}')

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--output',type=Path,default=ROOT/'dist');parser.add_argument('--local-import',action='store_true');parser.add_argument('--migrate-saves',action='store_true');parser.add_argument('--seed-package',type=Path);args=parser.parse_args()
    stage(args.output,args.local_import,args.migrate_saves,args.seed_package)
