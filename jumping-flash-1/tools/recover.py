"""Recover each verified USA executable into this game's private workbench."""
from pathlib import Path
import argparse
import hashlib
import json
import runpy
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
WORK=ROOT/'.workbench'
sys.path.insert(0,str(REPO/'tools'))
decode=runpy.run_path(str(REPO/'tools/extract-jf2-assets.py'))['decompress_lz1']
probe=runpy.run_path(str(WORK/'psxrecomp/tools/new_project_layout/probe_disc.py'))

def recover(generate=False):
    inventory=json.loads((WORK/'evidence/inventory-original.json').read_text())
    executables=[item for item in inventory if item['psx_exe']]
    if len(executables)!=16:raise ValueError('The verified USA executable inventory changed')
    results=[]
    for item in executables:
        raw=(WORK/'disc-files/original'/item['path']).read_bytes()
        if hashlib.sha256(raw).hexdigest()!=item['sha256']:raise ValueError('Executable identity changed')
        entry,gp,load,size=struct.unpack_from('<IIII',raw,16)
        if not 0<size<=2*1024*1024:raise ValueError('Invalid executable size')
        compressed=len(raw)!=2048+size
        body=decode(raw[2048:]) if compressed else raw[2048:]
        if len(body)!=size:raise ValueError(f'Decoded size mismatch: {item["path"]}')
        image=WORK/'decoded/original'/item['path'];image.parent.mkdir(parents=True,exist_ok=True)
        image.write_bytes(raw[:2048]+body)
        analysis=WORK/'analysis/original'/item['path'];analysis.mkdir(parents=True,exist_ok=True)
        analyzer=REPO/'robbit-mon-dieu/.workbench/build-recompiler/psxrecomp-analyze.exe'
        subprocess.run([str(analyzer),str(image),'--out',str(analysis),'--no-refs',
            '--emit-tsv',str(analysis/'functions.tsv'),'--disasm',str(analysis/'disassembly.txt'),
            '--emit-ghidra',str(analysis/'import-ghidra.py'),'--quiet'],check=True,stdout=subprocess.DEVNULL)
        native=WORK/'recovered-c/original'/item['path']
        if generate:
            native.mkdir(parents=True,exist_ok=True)
            seeds=probe['scan_jal_seeds'](image.read_bytes())
            (native/'seeds.txt').write_text('\n'.join(f'0x{x:08X}' for x in seeds)+'\n')
            config=dict(game=dict(name='Jumping Flash!',id='SCUS-94103',players=1,
                exe=image.as_posix(),load_address=f'0x{load:08X}',entry_pc=f'0x{entry:08X}',
                text_size=f'0x{size:08X}',stack_base='0x801FFFF0'),
                recompiler=dict(seeds=(native/'seeds.txt').as_posix(),out_dir=native.as_posix(),
                    bios_config=(WORK/'psxrecomp/bios/SCPH1001.toml').as_posix(),strict=True))
            config_path=native/'game.toml'
            config_path.write_text('\n'.join('['+section+']\n'+'\n'.join(f'{key} = {json.dumps(value)}' for key,value in values.items()) for section,values in config.items()))
            with (native/'generation.log').open('w',encoding='utf-8') as log:
                subprocess.run([str(REPO/'robbit-mon-dieu/.workbench/build-emitters/psxrecomp-game.exe'),'--config',str(config_path)],check=True,cwd=WORK,stdout=log,stderr=subprocess.STDOUT)
        stats=json.loads((analysis/'analysis.json').read_text())['stats']
        results.append(dict(path=item['path'],source_sha256=item['sha256'],lz1=compressed,
            decoded_sha256=hashlib.sha256(image.read_bytes()).hexdigest(),load=f'0x{load:08X}',
            entry=f'0x{entry:08X}',bytes=size,stats=stats,native_c_generated=generate))
        (WORK/'evidence/recovery.json').write_text(json.dumps(results,indent=2)+'\n')
        print(f'{len(results)}/16 {item["path"]}: {stats["total_functions"]} candidate functions',flush=True)
    return results

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--generate',action='store_true')
    recover(parser.parse_args().generate)
