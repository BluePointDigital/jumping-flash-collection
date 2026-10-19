"""Decode this disc's PS-X executables and recover annotated code per overlay."""
import argparse
import hashlib
import json
from pathlib import Path
import runpy
import struct
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / '.workbench'
# Exact's LZ1 is shared with JF2; only the decoder is reused, with local outputs.
sys.path.insert(0, str(ROOT.parent / 'tools'))
decode = runpy.run_path(str(ROOT.parent / 'tools/extract-jf2-assets.py'))['decompress_lz1']
probe = runpy.run_path(str(WORK / 'psxrecomp/tools/new_project_layout/probe_disc.py'))


def recover(generate=False):
    inventory = json.loads((WORK / 'evidence/inventory-english.json').read_text())
    results = []
    for item in inventory:
        if not item['psx_exe']:
            continue
        raw = (WORK / 'disc-files/english' / item['path']).read_bytes()
        expected = struct.unpack_from('<I', raw, 28)[0]
        if not 0 < expected <= 2*1024*1024:
            raise ValueError(f'Invalid image size: {item["path"]}')
        compressed = len(raw) != 2048+expected
        body = decode(raw[2048:]) if compressed else raw[2048:]
        if len(body) != expected:
            raise ValueError(f'Decoded/header size mismatch: {item["path"]}')
        image = WORK / 'decoded/english' / item['path']
        image.parent.mkdir(parents=True, exist_ok=True)
        image.write_bytes(raw[:2048]+body)
        output = WORK / 'analysis/english' / item['path']
        output.mkdir(parents=True, exist_ok=True)
        analyzer = WORK / 'build-recompiler/psxrecomp-analyze.exe'
        subprocess.run([str(analyzer), str(image), '--out', str(output), '--no-refs',
                        '--emit-tsv', str(output/'functions.tsv'), '--disasm', str(output/'disassembly.txt'),
                        '--emit-ghidra', str(output/'import-ghidra.py'), '--quiet'], check=True,
                       stdout=subprocess.DEVNULL)
        entry, gp, load, size = struct.unpack_from('<IIII', raw, 16)
        native = WORK / 'recovered-c/english' / item['path']
        if generate:
            native.mkdir(parents=True, exist_ok=True)
            seeds = probe['scan_jal_seeds'](image.read_bytes())
            (native/'seeds.txt').write_text('\n'.join(f'0x{x:08X}' for x in seeds)+'\n')
            config = dict(game=dict(name='Robbit Mon Dieu', id='SCPS-10103', players=1,
                                   exe=image.as_posix(), load_address=f'0x{load:08X}',
                                   entry_pc=f'0x{entry:08X}', text_size=f'0x{size:08X}', stack_base='0x801FFFF0'),
                          recompiler=dict(seeds=(native/'seeds.txt').as_posix(), out_dir=native.as_posix(),
                                          bios_config=(WORK/'psxrecomp/bios/SCPH5500.toml').as_posix(), strict=True))
            config_text = '\n'.join('['+key+']\n'+'\n'.join(
                f'{k} = {json.dumps(v)}' for k,v in values.items()) for key,values in config.items())
            config_path = native/'game.toml'
            config_path.write_text(config_text)
            with (native/'generation.log').open('w', encoding='utf-8') as log:
                subprocess.run([str(WORK/'build-emitters/psxrecomp-game.exe'), '--config', str(config_path)],
                               check=True, stdout=log, stderr=subprocess.STDOUT, cwd=WORK)
        stats = json.loads((output/'analysis.json').read_text())['stats']
        results.append(dict(path=item['path'], source_sha256=item['sha256'], lz1=compressed,
                            decoded_sha256=hashlib.sha256(raw[:2048]+body).hexdigest(),
                            load=f'0x{load:08X}', entry=f'0x{entry:08X}', bytes=len(body),
                            stats=stats, native_c_generated=generate))
        (WORK/'evidence/recovery.json').write_text(json.dumps(results, indent=2)+'\n')
        print(f'{len(results)}/81 {item["path"]}: {stats["total_functions"]} candidate functions', flush=True)
    if len(results) != 81:
        raise ValueError('Robbit executable inventory changed')
    return results


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--generate', action='store_true')
    recover(parser.parse_args().generate)
