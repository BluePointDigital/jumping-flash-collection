"""Build and audit native caches from hash-verified decoded USA executable images."""
from pathlib import Path
import argparse
import base64
import hashlib
import json
import os
import runpy
import struct
import subprocess
import sys

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent
WORK=ROOT/'.workbench'

def build():
    framework=REPO/'collection/.workbench/native/jf1/psxrecomp'
    sys.path.insert(0,str(REPO/'collection/tools'))
    from patch_compiler import patch
    patch(framework/'tools/compile_overlays.py')
    recovery=json.loads((WORK/'evidence/recovery.json').read_text())
    if len(recovery)!=16:raise ValueError('Recovery of every USA executable is required')
    probe=runpy.run_path(str(framework/'tools/new_project_layout/probe_disc.py'))
    records=[]
    for item in recovery:
        original=(WORK/'disc-files/original'/item['path']).read_bytes()
        decoded=(WORK/'decoded/original'/item['path']).read_bytes()
        if hashlib.sha256(original).hexdigest()!=item['source_sha256'] or hashlib.sha256(decoded).hexdigest()!=item['decoded_sha256']:
            raise ValueError(f'Original/decoded image changed: {item["path"]}')
        entry,_,load,size=struct.unpack_from('<IIII',decoded,16)
        if len(decoded)!=2048+size:raise ValueError('Executable layout changed')
        seeds=sorted(set(probe['scan_jal_seeds'](decoded))|{entry})
        records.append(dict(schema='psxrecomp overlay capture v3',producer='verified_psx_exe_lz1',
            producer_name=item['path'],load_addr=f'0x{load:08X}',size=size,
            bytes_b64=base64.b64encode(decoded[2048:]).decode(),executed_pcs=[],
            dispatch_entry_pcs=[f'0x{entry:08X}'],function_entry_pcs=[f'0x{x:08X}' for x in seeds],
            seeds=[f'0x{x:08X}' for x in seeds],
            producer_ranges=[dict(start=f'0x{load:08X}',end=f'0x{load+size:08X}')]))
    output=WORK/'aot';output.mkdir(exist_ok=True)
    captures=output/'original-records.json';captures.write_text(json.dumps(records))
    jobs=[]
    for index,(item,record) in enumerate(zip(recovery,records)):
        source=output/f'record-{index:03d}.json';source.write_text(json.dumps([record]))
        jobs.append(dict(name=item['path'],input=str(source),known_ranges=[
            [int(item['load'],16),int(item['load'],16)+item['bytes']]],
            required_entries=[] if item['path']=='SCUS_941.03' else [int(item['entry'],16)]))
    inventory=output/'inventory.json';inventory.write_text(json.dumps(dict(jobs=jobs),indent=2))
    compiler=REPO/'collection/dist/toolchain/clang/bin/clang.exe'
    recompiler=REPO/'collection/dist/toolchain/psxrecomp-game.exe'
    config=WORK/'game.toml';cache=output/'cache'
    env=dict(os.environ);env.pop('PSX_OVERLAY_CAPTURES',None);env.pop('PSX_OVERLAY_CACHE_DIR',None)
    command=[sys.executable,str(framework/'tools/compile_overlays.py'),'--captures',str(captures),
        '--game-toml',str(config),'--recompiler',str(recompiler),'--runtime-include',str(framework/'runtime/include'),
        '--project-root',str(WORK),'--out-dir',str(cache),'--gcc',str(compiler),'--jobs','2']
    with (output/'compile.log').open('w',encoding='utf-8') as log:
        result=subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env=env)
    if result.returncode:raise RuntimeError(f'AOT compilation failed; inspect {output/"compile.log"}')
    subprocess.run([sys.executable,str(framework/'tools/audit_aot_cache.py'),
        '--framework-root',str(framework),'--recompiler',str(recompiler),'--game-toml',str(config),
        '--inventory',str(inventory),'--cache-root',str(cache),'--output',str(output/'AOT_CACHE_AUDIT.json')],check=True,env=env)
    (output/'provenance.json').write_text(json.dumps(dict(schema=1,
        inputs=recovery,transform='PS-X EXE header load/text bounds and Exact LZ1, decoded sizes and hashes verified',
        original_records_sha256=hashlib.sha256(captures.read_bytes()).hexdigest(),
        semantic_qualification=False),indent=2))
    print(f'Audited JF1 AOT cache: {cache}')

if __name__=='__main__':build()
