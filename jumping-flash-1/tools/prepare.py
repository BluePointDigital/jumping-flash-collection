"""Prepare the owner-supplied USA disc and BIOS in an isolated native workbench."""
from pathlib import Path
import dataclasses
import hashlib
import json
import runpy
import shutil
import zipfile
import re

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parent
WORK = ROOT / '.workbench'
FRAMEWORK_PIN = '67a21b739598d8e6f372ddd5e252c8622971869c'
BIOS_SHA = '71af94d1e47a68c11e8fdb9f8368040601514a42a5a399cda48c7d3bff1e99d3'

def prepare():
    WORK.mkdir(parents=True, exist_ok=True)
    original = REPO / 'references/Jumping Flash! (USA)/Jumping Flash! (USA)/Jumping Flash! (USA).cue'
    base = REPO / 'robbit-mon-dieu/.workbench'
    framework = WORK / 'psxrecomp'
    if not framework.exists():
        shutil.copytree(base / 'psxrecomp', framework,
                        ignore=shutil.ignore_patterns('.git', '.cache', 'build', 'build-*', '__pycache__'))
    ui = WORK / 'recomp-ui'
    if not ui.exists():
        shutil.copytree(base / 'recomp-ui', ui,
                        ignore=shutil.ignore_patterns('.git', '.cache', 'build', 'build-*', '__pycache__'))
    # JF1's fade waits inside a nested guest call for its VBlank callback.
    # The shared Exact runtime fix already covers JF2/Robbit; opt JF1 into it.
    loader=framework/'runtime/src/overlay_loader.c'
    text=loader.read_text(encoding='utf-8')
    text=text.replace("#if defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP)\n    // JF2's nested World 1 frame wait",
        "#if defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP) || defined(JF1_DESKTOP)\n    // These titles' nested frame waits")
    loader.write_text(text,encoding='utf-8')
    main=framework/'runtime/src/main.cpp';text=main.read_text(encoding='utf-8')
    text=re.sub(r'defined\(JF2_DESKTOP\) \|\| defined\(ROBBIT_DESKTOP\)(?: \|\| defined\(JF1_DESKTOP\))*',
        'defined(JF2_DESKTOP) || defined(ROBBIT_DESKTOP) || defined(JF1_DESKTOP)',text)
    main.write_text(text,encoding='utf-8')
    probe = runpy.run_path(str(framework / 'tools/new_project_layout/probe_disc.py'))
    identity = probe['probe'](original)
    if identity.serial != 'SCUS-94103':
        raise ValueError(f'Wrong Jumping Flash disc: {identity.serial}')
    disc = WORK / 'disc/original'
    disc.mkdir(parents=True, exist_ok=True)
    for name in [identity.bin_name, identity.cue_name]:
        source, output = original.parent / name, disc / name
        if output.exists():
            with source.open('rb') as a, output.open('rb') as b:
                if hashlib.file_digest(a, 'sha256').digest() != hashlib.file_digest(b, 'sha256').digest():
                    raise ValueError(f'Preserving conflicting disc: {output}')
        else:
            shutil.copy2(source, output)
    bios = None
    with zipfile.ZipFile(REPO / 'references/PS1_BIOS.zip') as archive:
        for item in archive.infolist():
            if item.file_size == 524288:
                data = archive.read(item)
                if hashlib.sha256(data).hexdigest() == BIOS_SHA:
                    bios = data
                    break
    if bios is None:
        raise ValueError('The supplied BIOS archive has no matching USA SCPH-1001 v2.2 BIOS')
    (framework / 'bios/SCPH1001.BIN').write_bytes(bios)
    # Reuse the bounded ISO reader, supplying only this project's destinations.
    iso = runpy.run_path(str(REPO / 'robbit-mon-dieu/tools/prepare.py'))
    iso['inventory'].__globals__['WORK'] = WORK
    (WORK / 'evidence').mkdir(exist_ok=True)
    iso['inventory']('original')
    shutil.copy2(WORK / 'disc-files/original' / identity.boot_exe, WORK / 'disc' / identity.boot_exe)
    seeds = WORK / 'seeds'
    seeds.mkdir(exist_ok=True)
    (seeds / 'ghidra_funcs.txt').write_text(probe['render_seeds_file']([int(x,16) for x in identity.seed_addrs], boot_exe=identity.boot_exe,
        entry=int(identity.entry_pc,16), load=int(identity.load_address,16), text=int(identity.text_size,16)), encoding='utf-8')
    config = probe['render_game_toml'](identity, disc_rel='disc/original/'+identity.cue_name, out_dir='disc', players=1)
    config = config.replace('overlay_cache = true', 'overlay_cache = true\nbios_hle = true\nbios_hle_keep_intro = false')
    config = config.replace('aspect_ratio = "4:3"', 'aspect_ratio = "4:3"\nwindow_width = 1280\ninternal_resolution = 720\ndynamic_resolution = false\nrender_thread = true')
    (WORK / 'game.toml').write_text(config, encoding='utf-8')
    (ROOT / 'tools/game.toml').write_text(config, encoding='utf-8')
    receipt = {k:v for k,v in dataclasses.asdict(identity).items() if not isinstance(v,bytes)}
    receipt.pop('seed_addrs')
    receipt.update(framework_pin=FRAMEWORK_PIN, bios_sha256=BIOS_SHA)
    with (disc / identity.bin_name).open('rb') as stream:
        receipt['disc_sha256'] = hashlib.file_digest(stream, 'sha256').hexdigest()
    (WORK / 'evidence/identity.json').write_text(json.dumps(receipt, indent=2), encoding='utf-8')
    print(json.dumps(receipt, indent=2))

if __name__ == '__main__':
    prepare()
