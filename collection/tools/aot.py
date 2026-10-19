"""Build byte-audited native caches from verified discs, with optional dispatch guidance."""
from pathlib import Path
import argparse
import base64
import csv
import hashlib
import json
import mmap
import os
import re
import runpy
import struct
import subprocess
import sys
import tomllib
import zlib

ROOT=Path(__file__).resolve().parents[1]
REPO=ROOT.parent


def preserve_compile_log(output):
    output=Path(output);source=output/'compile.log'
    if not source.is_file():return None
    content=source.read_bytes()
    archive=output/'previous-compilations'/f'compile-{hashlib.sha256(content).hexdigest()}.log'
    if not archive.resolve().is_relative_to(output.resolve()):raise ValueError('Compile log archive escapes preparation')
    archive.parent.mkdir(exist_ok=True)
    if archive.exists():
        if archive.read_bytes()!=content:raise ValueError('Compile log archive changed')
    else:
        with archive.open('xb') as target:target.write(content)
    return archive


def guarded_title_seeds(game,load,body,image=None):
    """Per-image roots authorized by exact, verified control-routine layouts."""
    if game!='robbit':return []
    from robbit_profiles import profile_roots
    return profile_roots(image,load,body)


def analysis_function_roots(table,load,size,allow_empty=False):
    """Select only the analyzer's verified/high function extents, never data."""
    roots=[]
    for row in csv.DictReader(table.splitlines(),delimiter='\t'):
        if row['confidence'] not in ('verified','high'):continue
        address=int(row['addr'],16);extent=int(row['size'])
        if address%4 or extent<4 or extent%4 or not load<=address<address+extent<=load+size:
            raise ValueError('Analyzer function extent outside verified image')
        roots.append(address)
    if not roots and not allow_empty:raise ValueError('No verified/high functions in analyzed image')
    return sorted(set(roots))


def observed_dispatch_entries(records,load,body):
    """Match runtime dispatch evidence to static bytes; do not invent functions.

    Sixteen matching instruction bytes bind each observed PC to this verified
    image. The compiler still classifies interior entries and the final audit
    checks every emitted code range, not just these matching prefixes.
    The capture's executed_pcs bitmap records interpreter attempts before
    decode; it is not an architectural retired-instruction counter.
    """
    physical=load&0x1fffffff;entries=set()
    for record in records:
        captured=base64.b64decode(record['bytes_b64'],validate=True)
        start=int(record['load_addr'],16)&0x1fffffff
        if len(captured)!=record['size']:raise ValueError('Runtime evidence size mismatch')
        attempted={int(raw,16)&0x1fffffff for raw in record.get('executed_pcs',[])}
        for raw in record.get('dispatch_entry_pcs',[]):
            pc=int(raw,16)&0x1fffffff
            if pc not in attempted:continue
            a,b=pc-start,pc-physical
            if pc%4 or a<0 or b<0 or a+16>len(captured) or b+16>len(body):continue
            if captured[a:a+16]==body[b:b+16]:entries.add((load&0xe0000000)|pc)
    return sorted(entries)


def runtime_guidance(receipt_path,game):
    """Retain earlier overlay identities, not only the last resident image."""
    from import_game import sha
    receipt_path=Path(receipt_path);receipt=json.loads(receipt_path.read_text(encoding='utf-8'))
    if receipt.get('game')!=game or receipt.get('errors') or receipt.get('exit_code')!=0 or not receipt.get('final_input',{}).get('gameplay'):
        raise ValueError('Runtime evidence must be a clean reviewed gameplay run of this title')
    captures=receipt_path.parent/'overlay_captures.json'
    files=[captures,*sorted(captures.with_name(captures.name+'.d').glob('*.json'))]
    records=[];identities=[]
    for path in files:
        data=json.loads(path.read_text(encoding='utf-8'))
        if not isinstance(data,list):raise ValueError('Expected an overlay capture array')
        records.extend(data)
        identities.append(dict(path=path.relative_to(receipt_path.parent).as_posix(),sha256=sha(path)))
    return records,dict(receipt_sha256=sha(receipt_path),captures_sha256=sha(captures),
        capture_files=identities,runtime_sha256=receipt['executable_sha256'],source=str(receipt_path.resolve()))


def verified_repair_entries(requested,only_images,records):
    """Isolate observed dispatches stranded in a partly obsolete CPS bundle."""
    requested=sorted(set(requested))
    if not requested:return []
    if len(only_images)!=1:raise ValueError('Entry repair requires exactly one verified --only-image')
    image=next(record for record in records if record['producer_name']==only_images[0])
    observed={int(pc,16) for pc in image['executed_pcs']}
    if any(pc%4 or pc not in observed for pc in requested):
        raise ValueError('Entry repair requires byte-matched runtime dispatch evidence in the selected image')
    return requested


def isolate_repair_record(record,pc,cache):
    """Use a matching function guard to exclude unrelated CPS snapshot owners."""
    body=base64.b64decode(record['bytes_b64'],validate=True);load=int(record['load_addr'],16)
    choices=[]
    for path in Path(cache).rglob('*.ranges'):
        current=None;rows=[]
        for line in path.read_text(encoding='utf-8').splitlines():
            fields=line.split()
            if fields and fields[0]=='F':
                current=[int(fields[1],16),int(fields[2],16),[]];rows.append(current)
            elif fields and fields[0]=='R' and current is not None:
                current[2].append((int(fields[1],16),int(fields[2],16)))
        for entry,crc,ranges in rows:
            if entry!=pc or not ranges:continue
            if any(start%4 or size<=0 or size%4 or not load<=start<start+size<=load+len(body) for start,size in ranges):continue
            if not any(start<=pc<start+size for start,size in ranges):continue
            actual=0
            for start,size in ranges:actual=zlib.crc32(body[start-load:start-load+size],actual)
            if actual!=crc:continue
            lo=min(start for start,_ in ranges);hi=max(start+size for start,size in ranges)
            choices.append((hi-lo,lo,hi,path))
    if not choices:raise ValueError('Entry repair has no native guard matching the verified source image')
    size,lo,hi,path=min(choices,key=lambda item:(item[0],item[1],str(item[3])))
    isolated=dict(record,producer_name=record['producer_name']+f':repair-{pc:08X}',
        load_addr=f'0x{lo:08X}',size=size,bytes_b64=base64.b64encode(body[lo-load:hi-load]).decode(),
        executed_pcs=[f'0x{pc:08X}'],dispatch_entry_pcs=[f'0x{pc:08X}'],
        static_dispatch_entry_pcs=[],function_entry_pcs=[],seeds=[],
        producer_ranges=[dict(start=f'0x{lo:08X}',end=f'0x{hi:08X}')])
    isolated.pop('dispatch_entry_segments',None)
    for key in ('static_alias_ranges','static_jump_table_proofs','static_call_continuation_pcs','static_exception_continuation_pcs','source_uncached_callback_entries'):
        isolated.pop(key,None)
    return isolated,dict(entry=hex(pc),range=[hex(lo),hex(hi)],
        guard_manifest=str(path.resolve()),guard_manifest_sha256=hashlib.sha256(path.read_bytes()).hexdigest(),
        bytes_authority='Verified selected disc image; existing manifest supplies extent only')


def executable_images(disc):
    """Walk bounded ISO extents; return only PS-X EXE files, retaining their paths."""
    result=[]
    with Path(disc).open('rb') as stream,mmap.mmap(stream.fileno(),0,access=mmap.ACCESS_READ) as image:
        def read(lba,size):
            if lba<0 or size<0 or (lba+(size+2047)//2048)*2352>len(image):
                raise ValueError('ISO extent outside verified disc')
            return b''.join(image[i*2352+24:i*2352+2072] for i in range(lba,lba+(size+2047)//2048))[:size]
        seen=set()
        def walk(lba,size,prefix=''):
            if (lba,size) in seen:raise ValueError('ISO directory cycle')
            seen.add((lba,size))
            data=read(lba,size);offset=0
            while offset<len(data):
                count=data[offset]
                if not count:offset=(offset//2048+1)*2048;continue
                if count<34 or offset+count>len(data):raise ValueError('Malformed ISO directory')
                row=data[offset:offset+count];offset+=count
                rawname=row[33:33+row[32]]
                if rawname in (b'\0',b'\1'):continue
                name=rawname.decode('ascii').split(';')[0]
                if not name or name in ('.','..') or any(c in name for c in '/\\:'):
                    raise ValueError('Unsafe ISO filename')
                extent,length=struct.unpack_from('<I',row,2)[0],struct.unpack_from('<I',row,10)[0]
                relative=prefix+name
                if row[25]&2:walk(extent,length,relative+'/')
                elif read(extent,min(length,8))==b'PS-X EXE':
                    result.append((relative,read(extent,length)))
        pvd=read(16,2048)
        if pvd[1:6]!=b'CD001':raise ValueError('Expected ISO9660 volume')
        walk(struct.unpack_from('<I',pvd,158)[0],struct.unpack_from('<I',pvd,166)[0])
    return sorted(result)


def decode_executable(raw,decode):
    if len(raw)<2048 or raw[:8]!=b'PS-X EXE':raise ValueError('Expected PS-X executable')
    entry,_,load,size=struct.unpack_from('<IIII',raw,16)
    physical=load&0x1fffffff
    if size<=0 or size>0x200000 or physical+size>0x200000:
        raise ValueError('Executable image outside guest RAM')
    body=raw[2048:] if len(raw)==2048+size else decode(raw[2048:])
    if len(body)!=size:raise ValueError('Decoded executable/header length mismatch')
    if not physical<= (entry&0x1fffffff)<physical+size:raise ValueError('Entry outside executable image')
    return entry,load,body


def build(game,package,prepare_only=False,audit_only=False,speculative_attempts=32,runtime_evidence=None,output=None,only_images=(),bios_installed=False,incremental=False,repair_entries=()):
    from import_game import sha,raw_disc,game_from_catalog
    config=game_from_catalog(package,game)
    disc=raw_disc(package/config['disc'],package/(Path(config['disc']).parent),package)
    if sha(disc)!=config['disc_sha256']:raise ValueError('AOT input disc hash mismatch')
    runtime_records=[];runtime_provenance=None
    if runtime_evidence:
        if game not in ('jf1','jf2','robbit'):raise ValueError('Unknown title for dispatch guidance')
        sources=runtime_evidence if isinstance(runtime_evidence,(list,tuple)) else [runtime_evidence]
        provenances=[]
        for source in sources:
            records,identity=runtime_guidance(source,game)
            runtime_records.extend(records);provenances.append(identity)
        runtime_provenance=provenances[0] if len(provenances)==1 else provenances
    framework=ROOT/'.workbench/native'/game/'psxrecomp'
    sys.path.insert(0,str(REPO/'tools'))
    decode=runpy.run_path(str(REPO/'tools/extract-jf2-assets.py'))['decompress_lz1']
    probe=runpy.run_path(str(framework/'tools/new_project_layout/probe_disc.py')) if game=='jf1' else None
    images=executable_images(disc)
    if not images:raise ValueError('No executable recipes on verified disc')
    if game=='jf1' and len(images)!=16:raise ValueError('JF1 executable inventory changed')
    if game=='jf2' and len(images)!=28:raise ValueError('JF2 executable inventory changed')
    if game=='robbit' and len(images)!=81:raise ValueError('Robbit executable inventory changed')
    output=Path(output).resolve() if output else ROOT/'.workbench/aot'/game
    if output==package or package in output.parents:raise ValueError('Preparation output must stay outside the input package')
    output.mkdir(parents=True,exist_ok=True)
    records=[];jobs=[];inputs=[];game_records=[];game_evidence=[];initialized_inputs={};initialized_guidance=[]
    boot=Path(tomllib.loads((ROOT/'.workbench/native'/game/'game.toml').read_text())['game']['exe']).name
    boot_raw=None
    for index,(name,raw) in enumerate(images):
        if name==boot:boot_raw=raw
        entry,load,body=decode_executable(raw,decode)
        from game_installed_aot import installed_game_records
        constructed,proofs=installed_game_records(game,name,hashlib.sha256(raw).hexdigest(),load,body)
        game_records.extend(constructed);game_evidence.extend(proofs)
        from entry_layouts import nominations
        layout_entries=nominations(game,config['disc_sha256'],name,load,body)
        decoded=raw[:2048]+body
        # JF2/Robbit images mix code and large data sections. A raw JAL-shaped
        # word is not function-entry evidence; let the compiler follow verified roots.
        guarded_roots=guarded_title_seeds(game,load,body,name)
        analyzed_roots=[];analysis_receipt=None;observed=[];static_entries=[];static_aliases=[];static_proofs=[];continuations=[];exceptions=[];link_branches=[];uncached_entries=[]
        if game in ('jf1','jf2','robbit'):
            # Analyze verified image bytes for function-pointer targets. The
            # authored Robbit roots retain their separate fingerprint gate.
            analyzer=ROOT/'.workbench/emitters/psxrecomp-analyze.exe'
            analysis=output/'analysis'/name;analysis.mkdir(parents=True,exist_ok=True)
            image_path=analysis/'verified-image.exe';image_path.write_bytes(decoded)
            table_path=analysis/'functions.tsv'
            subprocess.run([str(analyzer),str(image_path),'--out',str(analysis),'--no-refs',
                '--emit-tsv',str(table_path),'--quiet'],check=True,stdout=subprocess.DEVNULL)
            analyzed_roots=analysis_function_roots(table_path.read_text(),load,len(body),allow_empty=True)
            from analysis_reachability import terminal_jump_roots
            analysis_data=json.loads((analysis/'analysis.json').read_text(encoding='utf-8'))
            from static_dispatches import nullable_function_tables,static_dispatches,source_referenced_callbacks,uncached_callbacks
            method_roots,_=nullable_function_tables(analysis_data,load,body)
            callback_roots,callback_proofs=source_referenced_callbacks(framework,analysis_data,load,body)
            uncached_entries,uncached_proofs=uncached_callbacks(analysis_data,load,body)
            recovered,reachability=terminal_jump_roots(analysis_data,
                json.loads((analysis/'edges.json').read_text(encoding='utf-8')),load,body,[*method_roots,*callback_roots])
            analyzed_roots=sorted(set(analyzed_roots)|set(recovered))
            static=static_dispatches(framework,analysis_data,json.loads((analysis/'indirect.json').read_text(encoding='utf-8')),
                load,body,sorted({entry,*guarded_roots,*analyzed_roots}))
            analyzed_roots=sorted(set(analyzed_roots)|set(static['function_roots']))
            static_entries=static['entries'];static_aliases=static['aliases']
            static_proofs=static['jump_table_proofs'];continuations=static['call_continuations']
            exceptions=static['syscall_returns']
            link_branches=static['link_branches']
            analysis_receipt=dict(analyzer_sha256=sha(analyzer),image_sha256=sha(image_path),
                function_table_sha256=sha(table_path),analysis_json_sha256=sha(analysis/'analysis.json'),
                edge_table_sha256=sha(analysis/'edges.json'),indirect_json_sha256=sha(analysis/'indirect.json'),
                extractor_sha256=sha(framework/'tools/aot_overlay_spike/extract_generic.py'),
                confidence=['verified','high'],roots=len(analyzed_roots),terminal_jump_reachability=reachability,
                nullable_function_tables=static['function_table_proofs'],
                source_referenced_callbacks=callback_proofs,
                source_uncached_callbacks=uncached_proofs,
                masked_return_tables=static['masked_return_tables'],
                local_control_proofs=static['local_control_proofs'],
                additional_root_policy='Complete functions with source-verified callable boundaries in dense null-padded method tables, plus source-referenced callbacks accepted by the shared bounded verifier',
                static_dispatch_entries=[hex(pc) for pc in static_entries],guarded_jump_tables=len(static_proofs),
                syscall_returns=[dict(syscall_pc=hex(item['syscall_pc']),return_pc=hex(item['return_pc'])) for item in exceptions],
                link_branches=[{key:hex(value) for key,value in item.items()} for item in link_branches])
            observed=observed_dispatch_entries(runtime_records,load,body)
        seeds=sorted(set(probe['scan_jal_seeds'](decoded))|{entry,*analyzed_roots}) if probe else sorted({entry,*guarded_roots,*analyzed_roots})
        record=dict(schema='psxrecomp overlay capture v3',producer='verified_psx_exe_lz1',producer_name=name,
            load_addr=f'0x{load:08X}',size=len(body),bytes_b64=base64.b64encode(body).decode(),
            executed_pcs=[f'0x{pc:08X}' for pc in observed],
            dispatch_entry_pcs=[f'0x{pc:08X}' for pc in sorted({entry,*observed,*layout_entries,*static_entries})],
            static_dispatch_entry_pcs=[f'0x{pc:08X}' for pc in sorted({entry,*static_entries})],
            function_entry_pcs=[f'0x{x:08X}' for x in seeds],seeds=[f'0x{x:08X}' for x in seeds],
            producer_ranges=[dict(start=f'0x{load:08X}',end=f'0x{load+len(body):08X}')])
        record['static_alias_ranges']=[dict(entry=hex(pc),start=hex(lo),end=hex(hi)) for pc,lo,hi in static_aliases]
        record['static_jump_table_proofs']=[dict(host_entry=hex(p['host_entry']),jr_pc=hex(p['jr_pc']),
            table_base=hex(p['table_base']),count=p['count'],targets=[hex(pc) for pc in p['targets']]) for p in static_proofs]
        record['static_call_continuation_pcs']=[hex(pc) for pc in continuations]
        record['static_exception_continuation_pcs']=[hex(item['return_pc']) for item in exceptions]
        record['source_uncached_callback_entries']=[hex(pc) for pc in uncached_entries]
        if layout_entries:
            # Export hints remain ordinary dispatch candidates, with no invented
            # execution evidence, prologues or static cross-variant authority.
            record['dispatch_entry_segments']={label:[f'0x{pc:08X}' for pc in sorted({entry,*observed,*layout_entries,*static_entries}) if pc&0xe0000000==segment]
                for label,segment in [('kuseg',0),('kseg0',0x80000000),('kseg1',0xa0000000)]}
        # Independent byte inventory stays purely disc-derived. Runtime metadata
        # is compiler guidance, never the authority for native code bytes.
        static_record=dict(record,executed_pcs=[],dispatch_entry_pcs=list(record['static_dispatch_entry_pcs']))
        if 'dispatch_entry_segments' in static_record:
            static_entries_set=set(record['static_dispatch_entry_pcs'])
            static_record['dispatch_entry_segments']={label:[pc for pc in entries if pc in static_entries_set]
                for label,entries in record['dispatch_entry_segments'].items()}
        if game in ('jf1','jf2'):
            from game_installed_aot import initialized_image_record,initialized_compile_record
            initialized,proof=initialized_image_record(game,static_record,hashlib.sha256(raw).hexdigest())
            if initialized is not None:
                game_records.append(initialized);game_evidence.append(proof)
                if observed:
                    compiled,guidance=initialized_compile_record(initialized,record)
                    initialized_inputs[initialized['producer_name']]=compiled;initialized_guidance.append(guidance)
        path=output/f'record-{index:03d}.json';path.write_text(json.dumps([static_record]))
        jobs.append(dict(name=name,input=str(path),sha256=hashlib.sha256(body).hexdigest(),
            known_ranges=[[load,load+len(body)]],required_entries=[] if name==boot else sorted({entry,*guarded_roots})))
        records.append(record)
        inputs.append(dict(path=name,source_sha256=hashlib.sha256(raw).hexdigest(),
            decoded_sha256=hashlib.sha256(decoded).hexdigest(),load=hex(load),entry=hex(entry),bytes=len(body),
            authored_function_roots=[hex(root) for root in guarded_roots],analysis=analysis_receipt,
            observed_dispatch_entries=[hex(pc) for pc in observed],layout_nominations=[hex(pc) for pc in layout_entries]))
    for index,record in enumerate(game_records):
        path=output/f'record-installed-{index:03d}.json';path.write_text(json.dumps([record]),encoding='utf-8')
        load=int(record['load_addr'],16);code=base64.b64decode(record['bytes_b64'])
        jobs.append(dict(name=record['producer_name'],input=str(path),sha256=hashlib.sha256(code).hexdigest(),
            known_ranges=[[load,load+len(code)]],required_entries=[int(pc,16) for pc in record.get('required_entry_pcs',
                [pc for entries in record['dispatch_entry_segments'].values() for pc in entries])]))
        records.append(initialized_inputs.get(record['producer_name'],record))
    bios_evidence=[]
    if bios_installed:
        from bios_aot import installed_records
        bios_records,bios_evidence=installed_records(package/config['bios'],config['bios_sha256'])
        from sdk_aot import installed_sdk_records
        sdk_records,sdk_evidence=installed_sdk_records(game,boot_raw,package/config['bios'],config['bios_sha256'])
        bios_records.extend(sdk_records);bios_evidence.extend(sdk_evidence)
        for index,record in enumerate(bios_records):
            path=output/f'record-bios-{index:03d}.json';path.write_text(json.dumps([record]),encoding='utf-8')
            load=int(record['load_addr'],16);code=base64.b64decode(record['bytes_b64'])
            jobs.append(dict(name=record['producer_name'],input=str(path),sha256=hashlib.sha256(code).hexdigest(),
                known_ranges=[[load,load+len(code)]],required_entries=[int(pc,16) for entries in record['dispatch_entry_segments'].values() for pc in entries]))
            records.append(record)
    captures=output/'records.json';captures.write_text(json.dumps(records))
    compile_captures=captures
    if only_images:
        if set(only_images)-{r['producer_name'] for r in records}:raise ValueError('Requested image is not a verified executable')
        compile_captures=output/'compile-records.json'
        compile_captures.write_text(json.dumps([r for r in records if r['producer_name'] in only_images]))
    repairs=verified_repair_entries(repair_entries,only_images,records)
    repair_proofs=[]
    if repairs:
        image=next(record for record in records if record['producer_name']==only_images[0])
        isolated=[]
        for pc in repairs:
            record,proof=isolate_repair_record(image,pc,output/'cache')
            isolated.append(record);repair_proofs.append(proof)
        compile_captures=output/'compile-records.json'
        compile_captures.write_text(json.dumps(isolated),encoding='utf-8')
    from static_dispatches import compile_segment_records
    selected=json.loads(compile_captures.read_text(encoding='utf-8'))
    segment_records=compile_segment_records(selected)
    if len(segment_records)!=len(selected):
        compile_captures=output/'compile-segment-records.json'
        compile_captures.write_text(json.dumps(segment_records),encoding='utf-8')
    inventory=output/'inventory.json';inventory.write_text(json.dumps(dict(jobs=jobs),indent=2))
    from source_slices import source_slice_plans,compile_source_slices
    slices=source_slice_plans(game,records,framework,only_images,repairs)
    provenance=dict(schema=1,game=game,disc_sha256=config['disc_sha256'],inputs=inputs,
        records_sha256=sha(captures),translation_patch_sha256=config.get('translation_patch_sha256'),bios_installed=bios_evidence,game_installed=game_evidence,initialized_dispatch_guidance=initialized_guidance,
        transform='Verified MODE2/2352 disc -> bounded ISO file -> exact LZ1 decode and PS-X EXE header bounds',
        seed_policy=('Existing JF1 recipe seeds; fresh verified/high static extents; optional byte-matched executed dispatch evidence retains ordinary runtime/interior classification' if game=='jf1' else 'Verified PS-X EXE entry; fingerprint-authorized function roots; fresh verified/high static extents; optional byte-matched executed dispatch evidence retains ordinary runtime/interior classification; no raw data JAL guesses'),
        preparation_tools=dict(compiler_script_sha256=sha(framework/'tools/compile_overlays.py'),
            recipe_source_sha256={name:sha(ROOT/'tools'/name) for name in ('aot.py','bios_aot.py','sdk_aot.py','game_installed_aot.py','source_slices.py','robbit_profiles.py','jf2_profiles.py','analysis_reachability.py','static_dispatches.py','entry_layouts.py','patch_aot_audit.py','batch_static_guards.py')},
            entry_layout_sha256=sha(ROOT/'runtime/jf1_entry_layouts.json') if game=='jf1' else None,
            installed_image_layout_sha256=sha(ROOT/f'runtime/{game}_initialized_images.json') if game in ('jf1','jf2') else None,
            control_profile_layout_sha256=sha(ROOT/f'runtime/{game}_profiles.json') if game in ('jf2','robbit') else None,
            emitter_sha256=sha(ROOT/'.workbench/emitters/psxrecomp-game.exe'),
            host_compiler_sha256=sha(REPO/'.jf2-workbench/recomp/toolchain/bin/clang.exe'),
            overlay_api_sha256=sha(framework/'runtime/include/overlay_api.h')),
        runtime_evidence=runtime_provenance,compile_image_filter=list(only_images),isolated_entry_repairs=repair_proofs,
        source_slice_plans=slices,source_slice_results=[],
        primary_policy='retain-valid-primary-and-repair-fragments' if incremental else 'refresh-same-image',
        compile_records_sha256=sha(compile_captures),semantic_qualification=False)
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2))
    print(f'{game}: prepared {len(records)} verified executable recipes',flush=True)
    if prepare_only:return
    recompiler=ROOT/'.workbench/emitters/psxrecomp-game.exe'
    compiler=REPO/'.jf2-workbench/recomp/toolchain/bin/clang.exe'
    env={k:v for k,v in os.environ.items() if not k.startswith('PSX_')}
    if speculative_attempts<0:raise ValueError('speculative_attempts must be nonnegative')
    env['PSX_STATIC_FRAGMENT_ATTEMPTS']=str(speculative_attempts)
    config_path=ROOT/'.workbench/native'/game/'game.toml'
    command=[sys.executable,str(framework/'tools/compile_overlays.py'),'--captures',str(compile_captures),
        '--game-toml',str(config_path),'--recompiler',str(recompiler),'--runtime-include',str(framework/'runtime/include'),
        '--project-root',str(ROOT/'.workbench/native'/game),'--out-dir',str(output/'cache'),
        '--gcc',str(compiler),'--jobs','2']
    if not incremental:command.append('--force')
    for pc in repairs:command.extend(['--force-interior',hex(pc)])
    # Offline preparation owns this output: replace older same-image bundles
    # with the richer recipe. The normal concurrent runtime publisher keeps its
    # first-valid-pair protection; exact dispatch repair alone misses new roots.
    if not audit_only:
        preserve_compile_log(output)
        with (output/'compile.log').open('w',encoding='utf-8') as log:
            subprocess.run(command,stdout=log,stderr=subprocess.STDOUT,env=env,check=True)
    provenance['source_slice_results']=compile_source_slices(slices,records,framework,recompiler,
        compiler,output,env,audit_only=audit_only)
    (output/'provenance.json').write_text(json.dumps(provenance,indent=2))
    subprocess.run([sys.executable,str(framework/'tools/audit_aot_cache.py'),'--framework-root',str(framework),
        '--recompiler',str(recompiler),'--game-toml',str(config_path),'--inventory',str(inventory),
        '--cache-root',str(output/'cache'),'--output',str(output/'AOT_CACHE_AUDIT.json')],check=True,env=env)
    audit_path=output/'AOT_CACHE_AUDIT.json';audit=json.loads(audit_path.read_text())
    audit['preparation_kind']=('verified-disc-with-source-call-and-branch-closure' if slices else
        'verified-disc-with-runtime-dispatch-guidance' if runtime_provenance else 'verified-disc-static')
    audit['guidance_provenance_sha256']=sha(output/'provenance.json')
    audit_path.write_text(json.dumps(audit,indent=2)+'\n')
    print(f'{game}: audited native cache at {output}',flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--game',choices=('jf1','jf2','robbit'),required=True)
    parser.add_argument('--package',type=Path,default=ROOT/'releases/JumpingFlash-Collectors-Edition-Preview-0.2.1')
    parser.add_argument('--speculative-attempts',type=int,default=32,help='Unexecuted static recovery budget; 0 explicitly requests exhaustive preparation')
    parser.add_argument('--runtime-evidence',type=Path,action='append',help='Clean reviewed gameplay receipt for this title; repeat to preserve earlier discovery; exact static-byte matching retains interior classification')
    parser.add_argument('--output',type=Path,help='Separate preparation directory; preserve earlier audited caches')
    parser.add_argument('--only-image',action='append',default=[],help='Refresh this verified image only, e.g. SELECT.PEX; repeat for multiple images. The final audit still checks the entire cache and all recipes')
    parser.add_argument('--bios-installed',action='store_true',help='Also prepare BIOS-installed code from independently verified ROM copy constructors')
    parser.add_argument('--incremental',action='store_true',help='Retain valid primary bundles while repairing uncovered entry fragments; the final full byte audit remains mandatory')
    parser.add_argument('--repair-entry',type=lambda value:int(value,0),action='append',default=[],help='Isolate an actual byte-matched observed dispatch even if a partly obsolete bundle already contains it; requires one --only-image and --runtime-evidence')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--prepare-only',action='store_true');mode.add_argument('--audit-only',action='store_true');args=parser.parse_args()
    build(args.game,args.package.resolve(),args.prepare_only,args.audit_only,args.speculative_attempts,args.runtime_evidence,args.output,args.only_image,args.bios_installed,args.incremental,args.repair_entry)
