"""Verify configured control callbacks in real emitted C; never compile a DLL."""
import argparse
import base64
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import struct
import subprocess
import sys
import tomllib
from robbit_profiles import ROOT,validate_guards,require


def check(preparation,output,game='robbit',config_override=None,compiler_override=None):
    preparation,output=Path(preparation).resolve(),Path(output).resolve()
    require(game in ('robbit','jf2'),'Unsupported control-profile title')
    native=ROOT/'.workbench/native'/game;framework=native/'psxrecomp'
    config=Path(config_override) if config_override else native/'game.toml'
    compiler=Path(compiler_override) if compiler_override else framework/'tools/compile_overlays.py'
    emitter=ROOT/'.workbench/emitters/psxrecomp-game.exe'
    document=json.loads((ROOT/f'runtime/{game}_profiles.json').read_text())
    if game=='jf2':
        from jf2_profiles import validate_guards as validate,ROLES
        keys=tuple(ROLES)
    else:
        validate=validate_guards;keys=('update','pitch','vector','rotation_return')
    records={r['producer_name']:r for r in json.loads((preparation/'records.json').read_text())}
    configured={int(pc,0) for pc in tomllib.loads(config.read_text())['recompiler'].get('mod_instruction_sites',[])}
    required={int(p['sites'][key],16) for p in document['profiles'] for key in keys}
    require(required<=configured,'Prepare the Robbit profile hook configuration before checking emission')
    require(not output.exists() and not output.is_relative_to(preparation),'Choose a new emission directory outside the preparation')
    sys.path.insert(0,str(framework/'tools'))
    spec=importlib.util.spec_from_file_location('profile_emission_compiler',compiler)
    co=importlib.util.module_from_spec(spec);sys.modules[spec.name]=co;spec.loader.exec_module(co)
    include=framework/'runtime/include';co.load_dispatch_preamble(str(include))
    co.verify_recompiler_matches_tag(str(emitter),co.codegen_hash(str(include)))
    output.mkdir(parents=True);results=[]
    env={k:v for k,v in os.environ.items() if not k.startswith('PSX_')}
    for profile in document['profiles']:
        name=profile['image'];record=records[name];body=base64.b64decode(record['bytes_b64'],validate=True)
        load=int(record['load_addr'],16);validate(profile,load,body)
        require(hashlib.sha256(body).hexdigest() in (profile['source_body_sha256'],profile.get('original_body_sha256')),
                f'{name}: source image changed')
        spans=[(int(g['address'],16),int(g['address'],16)+g['words']*4) for g in profile['guards'].values()]
        lo=min(a for a,b in spans);hi=max(b for a,b in spans)
        sites={key:int(profile['sites'][key],16) for key in keys}
        directory=output/Path(name).with_suffix('');directory.mkdir(parents=True)
        image=directory/'input.psx';image.write_bytes(co.make_psxexe(lo,min(sites.values()),body[lo-load:hi-load],guard_bytes=0))
        seeds=directory/'seeds.txt'
        seeds.write_text(''.join(f'producer_range 0x{a:08X} 0x{b:08X}\n' for a,b in spans)+
                         ''.join(f'dispatch_root 0x{pc:08X}\n' for pc in sites.values()))
        command=[str(emitter),str(image),'--seeds',str(seeds),'--out-dir',str(directory/'generated'),
                 '--overlay','--ws-config',str(config),'--project-root',str(native)]
        result=subprocess.run(command,capture_output=True,text=True,env=env)
        (directory/'emission.log').write_text(result.stdout+'\n'+result.stderr,encoding='utf-8')
        require(result.returncode==0,f'{name}: emitter failed; inspect {directory}/emission.log')
        sources=list((directory/'generated').glob('*_full.c'))
        require(len(sources)==1,f'{name}: expected exactly one emitted C translation unit')
        source=sources[0].read_text(encoding='cp1252')
        patched=co.patch_generated_c(source,lo,hi-lo)
        (directory/'patched.c').write_text(patched,encoding='utf-8')
        for role,pc in sites.items():
            instruction=struct.unpack_from('<I',body,pc-load)[0]
            pattern=rf'psx_mod_instruction\(cpu,\s*0x{pc:08X}u,\s*0x{instruction:08X}u\);'
            require(re.search(pattern,source,re.I),f'{name}: missing configured {role} callback')
            require(not re.search(rf'if\(psx_mod_function_entry\(cpu,0x{pc:08X}u\)\)return;',patched,re.I),
                    f'{name}: duplicate manual callback at {role}')
        results.append(dict(image=name,all_configured_callbacks_present=True,no_duplicate_manual_callbacks=True,
            generated_c_sha256=hashlib.sha256(source.encode('cp1252')).hexdigest(),
            patched_c_sha256=hashlib.sha256(patched.encode()).hexdigest()))
    receipt=dict(schema=1,game=game,config_hash=f'{co.overlay_config_hash(str(emitter),str(config)):08x}',results=results,
        profiles_checked=len(results),callbacks_checked=len(keys)*len(results),native_compilation_performed=False,
        compiler_sha256=hashlib.sha256(compiler.read_bytes()).hexdigest(),config_sha256=hashlib.sha256(config.read_bytes()).hexdigest(),
        gameplay_qualified=False,tool_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest())
    (output/'receipt.json').write_text(json.dumps(receipt,indent=2)+'\n')
    print(f'PASS: {len(results)} profiles / {len(keys)*len(results)} configured callbacks; no native compilation performed')
    return receipt


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation',type=Path,required=True);parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--game',choices=('robbit','jf2'),default='robbit')
    parser.add_argument('--config',type=Path);parser.add_argument('--compiler',type=Path)
    args=parser.parse_args();check(args.preparation,args.output,args.game,args.config,args.compiler)
