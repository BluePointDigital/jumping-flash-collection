"""Carry verified static jump tables and call returns into native entry discovery."""
from functools import lru_cache
from pathlib import Path
import hashlib
from bisect import bisect_right
import runpy
import struct
from analysis_reachability import control_transfer


def local_control_entries(analysis,load,body):
    """Nominate source jump labels, retaining their analyzed host boundaries."""
    if (analysis.get('schema')!='psxrecomp static analysis v1' or analysis.get('static_only') is not True or
        analysis.get('load_address')!=load or analysis.get('image_size')!=len(body) or len(body)%4):
        raise ValueError('Local control analysis does not match verified image')
    functions=sorted((f for f in analysis['functions'] if not f['partial'] and not f['is_data']),key=lambda f:f['addr'])
    for f in functions:
        if f['addr']%4 or f['end']%4 or not load<=f['addr']<f['end']<=load+len(body):
            raise ValueError('Local control host outside image')
    starts=[f['addr'] for f in functions];entries=set();aliases=set();proofs=[]
    def owner(target):
        i=bisect_right(starts,target)-1
        return functions[i] if i>=0 and target<functions[i]['end'] else None
    def ordinary(word):return not control_transfer(word) and not (word>>26==0 and word&63 in (12,13))
    def nominate(target,host,proof):
        entries.add(target);aliases.add((target,host['addr'],host['end']))
        proofs.append(dict(proof,entry=hex(target),host_entry=hex(host['addr']),host_end=hex(host['end']),
            host_sha256=hashlib.sha256(body[host['addr']-load:host['end']-load]).hexdigest()))
    for host in functions:
        lo,hi=host['addr'],host['end'];words=struct.unpack(f'<{(hi-lo)//4}I',body[lo-load:hi-load])
        for i,word in enumerate(words[:-1]):
            pc=lo+4*i
            if i and control_transfer(words[i-1]):continue
            if i+6<len(words):
                upper,lower,base_upper,base_lower,subtract,store=words[i:i+6]
                value_reg=upper>>16&31;base_reg=base_upper>>16&31;object_reg=store>>21&31
                if (upper>>26==15 and upper>>21&31==0 and value_reg and
                    lower>>26==9 and lower>>21&31==value_reg and lower>>16&31==value_reg and
                    base_upper>>26==15 and base_upper>>21&31==0 and base_reg and base_reg!=value_reg and
                    base_lower>>26==9 and base_lower>>21&31==base_reg and base_lower>>16&31==base_reg and
                    subtract==(value_reg<<21|base_reg<<16|value_reg<<11|0x23) and
                    store>>26==41 and store>>16&31==value_reg and store&0xffff==2 and
                    16<=object_reg<=23 and object_reg not in (value_reg,base_reg)):
                    low=lower&0xffff;low=low-0x10000 if low&0x8000 else low
                    target=(((upper&0xffff)<<16)+low)&0xffffffff
                    low=base_lower&0xffff;low=low-0x10000 if low&0x8000 else low
                    base=(((base_upper&0xffff)<<16)+low)&0xffffffff
                    if target==pc+24 and lo<=base<hi and base%4==0 and -32768<=target-base<=32767:
                        # The engine stores a relative PC for resuming at the
                        # next instruction, not an ordinary function pointer.
                        nominate(target,host,dict(kind='stored_local_resume_pc',binding_pc=hex(pc),
                            base=hex(base),relative_offset=target-base,object_register=object_reg,
                            binding_sha256=hashlib.sha256(body[pc-load:pc-load+24]).hexdigest()))
            if i+10<len(words):
                bound,compare,reject,scale,upper,lower,add,deref,load_slot,jump,jump_slot=words[i:i+11]
                limit_reg=bound>>16&31;index_reg=compare>>16&31;condition=compare>>11&31
                scaled=scale>>11&31;base_reg=upper>>16&31;address=add>>11&31;destination=deref>>16&31
                if (bound>>26==13 and bound>>21&31==0 and limit_reg and bound&0xffff<4096 and
                    index_reg and index_reg!=limit_reg and condition and condition!=index_reg and
                    compare==(limit_reg<<21|index_reg<<16|condition<<11|0x2b) and
                    reject>>26==5 and reject>>21&31==condition and reject>>16&31==0 and
                    scaled and scale==(index_reg<<16|scaled<<11|2<<6) and
                    upper>>26==15 and upper>>21&31==0 and base_reg and base_reg!=scaled and
                    lower>>26==9 and lower>>21&31==base_reg and lower>>16&31==base_reg and
                    address and add in (base_reg<<21|scaled<<16|address<<11|0x21,
                                        scaled<<21|base_reg<<16|address<<11|0x21) and
                    destination not in (0,31) and deref==(0x8c000000|address<<21|destination<<16) and
                    not load_slot and jump==(destination<<21|8) and not jump_slot):
                    low=lower&0xffff;low=low-0x10000 if low&0x8000 else low
                    base=(((upper&0xffff)<<16)+low)&0xffffffff;count=(bound&0xffff)+1
                    offset=reject&0xffff;offset=offset-0x10000 if offset&0x8000 else offset
                    default=(pc+12+4*offset)&0xffffffff
                    if (lo<=default<hi and not pc<=default<pc+44 and base%4==0 and
                        load<=base<base+4*count<=load+len(body) and (base+4*count<=lo or base>=hi)):
                        data=body[base-load:base-load+4*count];values=struct.unpack(f'<{count}I',data)
                        if all(pc+44<=target<hi and target%4==0 and
                               not control_transfer(words[(target-lo)//4-1]) for target in values):
                            for target in sorted(set(values)):
                                nominate(target,host,dict(kind='inclusive_bound_jump_table',binding_pc=hex(pc),
                                    jump_pc=hex(pc+36),table_base=hex(base),count=count,default_pc=hex(default),
                                    targets=[hex(value) for value in values],
                                    table_sha256=hashlib.sha256(data).hexdigest(),
                                    binding_sha256=hashlib.sha256(body[pc-load:pc-load+44]).hexdigest()))
            # Also recognize a branch-delay move followed by SLL. The original
            # 11-word form above remains unchanged (SLL itself is the delay slot).
            # This 12-word form admits one exact ADDU rd,rs,$zero or NOP slot;
            # the move must not overwrite the index consumed by the following SLL.
            if i+11<len(words):
                bound2,compare2,reject2,delay2,scale2,upper2,lower2,add2,deref2,load_slot2,jump2,jump_slot2=words[i:i+12]
                limit2=bound2>>16&31;index2=compare2>>16&31;condition2=compare2>>11&31
                scaled2=scale2>>11&31;base_reg2=upper2>>16&31;address2=add2>>11&31
                delay_rd2=delay2>>11&31;delay_rs2=delay2>>21&31
                delay_ok2=(delay2==0 or
                    (delay2==(delay_rs2<<21|delay_rd2<<11|0x21) and delay_rd2!=index2))
                destination2=deref2>>16&31
                if (bound2>>26==13 and bound2>>21&31==0 and limit2 and bound2&0xffff<4096 and
                    index2 and index2!=limit2 and condition2 and condition2!=index2 and
                    compare2==(limit2<<21|index2<<16|condition2<<11|0x2b) and
                    reject2>>26==5 and reject2>>21&31==condition2 and reject2>>16&31==0 and
                    delay_ok2 and scaled2 and scale2==(index2<<16|scaled2<<11|2<<6) and
                    upper2>>26==15 and upper2>>21&31==0 and base_reg2 and base_reg2!=scaled2 and
                    lower2>>26==9 and lower2>>21&31==base_reg2 and lower2>>16&31==base_reg2 and
                    address2 and add2 in (base_reg2<<21|scaled2<<16|address2<<11|0x21,
                                          scaled2<<21|base_reg2<<16|address2<<11|0x21) and
                    destination2 not in (0,31) and deref2==(0x8c000000|address2<<21|destination2<<16) and
                    not load_slot2 and jump2==(destination2<<21|8) and not jump_slot2):
                    low2=lower2&0xffff;low2=low2-0x10000 if low2&0x8000 else low2
                    base2=(((upper2&0xffff)<<16)+low2)&0xffffffff;count2=(bound2&0xffff)+1
                    offset2=reject2&0xffff;offset2=offset2-0x10000 if offset2&0x8000 else offset2
                    default2=(pc+12+4*offset2)&0xffffffff
                    if (lo<=pc and pc+48<=hi and lo<=default2<hi and not pc<=default2<pc+48 and
                        base2%4==0 and load<=base2<base2+4*count2<=load+len(body) and
                        (base2+4*count2<=lo or base2>=hi)):
                        data2=body[base2-load:base2-load+4*count2];values2=struct.unpack(f'<{count2}I',data2)
                        if all(pc+48<=target<hi and target%4==0 and
                               not control_transfer(words[(target-lo)//4-1]) for target in values2):
                            for target in sorted(set(values2)):
                                nominate(target,host,dict(kind='inclusive_bound_jump_table_delay_move',
                                    binding_pc=hex(pc),branch_pc=hex(pc+8),branch_delay_pc=hex(pc+12),
                                    branch_delay_word=hex(delay2),jump_pc=hex(pc+40),table_base=hex(base2),
                                    count=count2,default_pc=hex(default2),targets=[hex(value) for value in values2],
                                    table_sha256=hashlib.sha256(data2).hexdigest(),
                                    binding_sha256=hashlib.sha256(body[pc-load:pc-load+48]).hexdigest()))
            jump_kind=None
            if word>>26==2:
                target=((pc+4)&0xf0000000)|((word&0x03ffffff)<<2);jump_kind='direct_j_to_known_code'
            elif ((word>>26 in (4,5) and not (word>>26==5 and word>>21&31==word>>16&31)) or
                  (word>>26 in (6,7) and word>>16&31==0 and not (word>>26==7 and word>>21&31==0)) or
                  (word>>26==1 and word>>16&31 in (0,1) and not (word>>16&31==0 and word>>21&31==0))):
                offset=word&0xffff;offset=offset-0x10000 if offset&0x8000 else offset
                target=(pc+4+4*offset)&0xffffffff;jump_kind='direct_branch_to_known_code'
            if jump_kind and ordinary(words[i+1]):
                other=owner(target)
                if other is not None and other['addr']!=lo:
                    nominate(target,other,dict(kind=jump_kind,jump_pc=hex(pc),instruction=hex(word),delay_slot=hex(words[i+1])))
            # This nominates possible local JR labels, not a claim that every
            # path preserves the literal. No function root or execution bit is added.
            base_reg=word>>16&31
            if word>>26!=15 or word>>21&31 or not base_reg:continue
            for lower_index in range(i+1,min(i+4,len(words))):
                gap=words[i+1:lower_index]
                if any(w and w>>26!=43 for w in gap):break # Only SW/NOP scheduling leaves the base register untouched.
                lower=words[lower_index];reg=lower>>16&31
                if lower>>26 not in (9,13) or lower>>21&31!=base_reg or not 16<=reg<=23:continue
                low=lower&0xffff
                if lower>>26==9 and low&0x8000:low-=0x10000
                target=((((word&0xffff)<<16)+low) if lower>>26==9 else ((word&0xffff)<<16)|low)&0xffffffff
                if not lo<=target<hi or target%4:continue
                jumps=[lo+4*j for j in range(lower_index+1,len(words)-1) if words[j]==(reg<<21|8) and ordinary(words[j+1])]
                if jumps:nominate(target,host,dict(kind='local_literal_and_matching_jr',literal_pc=hex(pc),lower_pc=hex(lo+4*lower_index),register=reg,jump_pcs=[hex(j) for j in jumps],
                    literal_sha256=hashlib.sha256(body[pc-load:lo+4*lower_index+4-load]).hexdigest()))
    return entries,aliases,proofs


def masked_return_tables(analysis,load,body):
    """Prove bounded computed jumps into an exact JR-RA/NOP stub array."""
    if (analysis.get('schema')!='psxrecomp static analysis v1' or analysis.get('static_only') is not True or
        analysis.get('load_address')!=load or analysis.get('image_size')!=len(body)):
        raise ValueError('Return-table analysis does not match verified image')
    targets=set();aliases=set();proofs=[]
    for host in analysis['functions']:
        if host['partial'] or host['is_data']:continue
        pc,hi=host['addr'],host['end']
        if pc%4 or hi%4 or not load<=pc<hi<=load+len(body):raise ValueError('Return-table producer outside image')
        if hi-pc<28:continue
        words=struct.unpack_from('<7I',body,pc-load);upper,lower,sub,maskword,add,jump,slot=words
        if (upper&0xffff0000!=0x3c020000 or lower&0xffff0000!=0x24420000 or
            sub!=0x00821823 or maskword&0xffff0000!=0x30630000 or add!=0x00431021 or
            jump!=0x00400008 or slot):continue
        low=lower&0xffff;low=low-0x10000 if low&0x8000 else low
        base=(((upper&0xffff)<<16)+low)&0xffffffff;mask=maskword&0xffff
        size=mask+8
        if base!=pc+28 or mask&7 or size<8 or size>4096 or size&(size-1) or base+size>load+len(body):continue
        table=body[base-load:base-load+size]
        if table!=struct.pack('<2I',0x03e00008,0)*(size//8):continue
        entries=list(range(base,base+size,8));targets.update(entries)
        if base<hi:aliases.add((base,pc,hi))
        proofs.append(dict(host_entry=hex(pc),jump_pc=hex(pc+20),base=hex(base),mask=hex(mask),
            entries=len(entries),producer_sha256=hashlib.sha256(body[pc-load:base-load+size]).hexdigest(),
            policy='Exact subtract/mask/add/JR producer; every aligned possible target is a source JR-RA/NOP stub'))
    return targets,aliases,proofs


def uncached_callbacks(analysis,load,body):
    """Exact LUI/ADDIU/LUI/OR/JAL registration of an uncached callback."""
    if (analysis.get('schema')!='psxrecomp static analysis v1' or analysis.get('static_only') is not True or analysis.get('load_address')!=load or
        analysis.get('image_size')!=len(body) or len(body)%4):
        raise ValueError('Uncached callback analysis does not match verified image')
    functions={f['addr']:f for f in analysis['functions'] if not f['partial'] and not f['is_data'] and f.get('ends_jr_ra')}
    entries=set();proofs=[]
    for owner in functions.values():
        lo,hi=owner['addr'],owner['end']
        if not load<=lo<hi<=load+len(body) or lo%4 or hi%4:raise ValueError('Callback producer outside image')
        for pc in range(lo,hi-23,4):
            a,b,c,d,call,slot=struct.unpack_from('<6I',body,pc-load)
            reg=a>>16&31;alias=c>>16&31
            if (a>>26!=15 or a>>21&31 or not reg or b>>26!=9 or b>>21&31!=reg or b>>16&31!=reg or
                c>>26!=15 or c>>21&31 or c&0xffff!=0xa000 or alias!=4 or alias==reg or
                d>>26 or d&63!=37 or d>>6&31 or d>>11&31!=alias or
                {d>>21&31,d>>16&31}!={reg,alias} or call>>26!=3 or
                not (slot==0 or slot>>26 in (9,13) and slot>>21&31==0 and slot>>16&31 in (5,6,7))):continue
            low=b&0xffff;low=low-0x10000 if low&0x8000 else low
            target=(((a&0xffff)<<16)+low)&0xffffffff
            function=functions.get(target)
            if function is None or target&0xe0000000!=0x80000000:continue
            entry=target|0xa0000000;entries.add(entry)
            proofs.append(dict(registration_pc=hex(pc),target=hex(target),uncached_entry=hex(entry),
                host_entry=hex(lo),target_end=hex(function['end']),
                registration_sha256=hashlib.sha256(body[pc-load:pc-load+24]).hexdigest(),
                target_sha256=hashlib.sha256(body[target-load:function['end']-load]).hexdigest()))
    return sorted(entries),proofs


def compile_segment_records(records):
    """Compile proven uncached callbacks without duplicating all cached roots."""
    import copy
    result=[]
    for record in records:
        result.append(record)
        entries=record.get('source_uncached_callback_entries',[])
        if not entries:continue
        load=int(record['load_addr'],16);size=record['size']
        if any(int(pc,16)&0xe0000000!=0xa0000000 or int(pc,16)%4 or
               not (load&0x1fffffff)<=(int(pc,16)&0x1fffffff)<(load&0x1fffffff)+size for pc in entries):
            raise ValueError('Source callback alias outside verified image')
        view=copy.deepcopy(record)
        for key in ('dispatch_entry_segments','static_alias_ranges','static_jump_table_proofs',
                    'static_call_continuation_pcs','static_exception_continuation_pcs','source_uncached_callback_entries'):
            view.pop(key,None)
        view.update(load_addr=f'0x{(load&0x1fffffff)|0xa0000000:08X}',executed_pcs=[],
            dispatch_entry_pcs=list(entries),static_dispatch_entry_pcs=list(entries),function_entry_pcs=list(entries),seeds=list(entries),
            producer_ranges=[dict(start=f'0x{(load&0x1fffffff)|0xa0000000:08X}',end=f'0x{((load&0x1fffffff)+size)|0xa0000000:08X}')])
        result.append(view)
    return result


def source_referenced_callbacks(framework,analysis,load,body):
    """Recover source-referenced callables using the existing bounded verifier."""
    if (analysis.get('schema')!='psxrecomp static analysis v1' or analysis.get('static_only') is not True or
        analysis.get('load_address')!=load or analysis.get('image_size')!=len(body) or len(body)%4):
        raise ValueError('Callback analysis does not match the verified image')
    occupied=bytearray(len(body)//4);eligible={}
    for item in analysis['functions']:
        lo,hi=item['addr'],item['end']
        if lo%4 or hi%4 or not load<=lo<hi<=load+len(body):raise ValueError('Callback outside verified image')
        if item['is_data']:continue
        occupied[(lo-load)//4:(hi-load)//4]=b'\1'*((hi-lo)//4)
        if not item['partial'] and item.get('ends_jr_ra') is True:eligible[lo]=item
    pointers={}
    for index,word in enumerate(struct.unpack(f'<{len(body)//4}I',body)):
        if word in eligible and not occupied[index]:pointers.setdefault(word,[]).append(load+4*index)
    extractor=_extractor(str(Path(framework).resolve()));roots=[];proofs=[]
    for pc,slots in sorted(pointers.items()):
        if (not extractor['_callable_boundary'](body,pc-load) or
            not extractor['co'].plausible_callable_target(body,load,len(body),pc,eligible[pc]['end'],
                instruction_budget=min(4097,(eligible[pc]['end']-pc)//4+1))):continue
        item=eligible[pc];roots.append(pc)
        proofs.append(dict(entry=hex(pc),end=hex(item['end']),pointer_slots=[hex(slot) for slot in slots],
            body_sha256=hashlib.sha256(body[pc-load:item['end']-load]).hexdigest()))
    return roots,proofs


def nullable_function_tables(analysis,load,body):
    """Extend dense, independently bounded method tables across null slots."""
    if (analysis.get('schema')!='psxrecomp static analysis v1' or analysis.get('static_only') is not True or
        analysis.get('load_address')!=load or analysis.get('image_size')!=len(body) or len(body)%4):
        raise ValueError('Function-table analysis does not match the verified image')
    words=struct.unpack(f'<{len(body)//4}I',body)
    functions={};occupied=bytearray(len(words))
    for item in analysis['functions']:
        lo,hi=item['addr'],item['end']
        if lo%4 or hi%4 or not load<=lo<hi<=load+len(body):raise ValueError('Method-table function outside image')
        if item['is_data']:continue
        occupied[(lo-load)//4:(hi-load)//4]=b'\1'*((hi-lo)//4)
        if not item['partial'] and item.get('ends_jr_ra') and hi-lo>=8:
            last=words[(hi-load)//4-2];slot=words[(hi-load)//4-1]
            if last==0x03e00008 and not control_transfer(slot):functions[lo]=item
    eligible={}
    for pc,item in functions.items():
        index=(pc-load)//4;first=words[index]
        framed=(first>>26 in (8,9) and (first>>16)&0x3ff==0x3bd and first&0x8000)
        previous=(index>=2 and words[index-2]==0x03e00008 and not control_transfer(words[index-1]))
        if framed or previous:eligible[pc]=item
    roots=set();proofs=[];i=0
    while i<len(words):
        if occupied[i] or words[i] not in eligible:i+=1;continue
        start=i
        while i<len(words) and not occupied[i] and words[i] in eligible:i+=1
        if len(set(words[start:i]))<3:continue
        end=i;nulls=0
        while i<len(words) and not occupied[i]:
            if words[i] in eligible:nulls=0;end=i+1
            elif words[i]==0:
                nulls+=1
                if nulls>2:break
            else:break
            i+=1
        entries=[dict(slot=hex(load+4*n),target=hex(words[n])) for n in range(start,end) if words[n] in eligible]
        roots.update(int(entry['target'],16) for entry in entries)
        proofs.append(dict(table_base=hex(load+4*start),table_end=hex(load+4*end),entries=entries,
            table_sha256=hashlib.sha256(body[4*start:4*end]).hexdigest(),max_consecutive_nulls=2))
    return sorted(roots),proofs


def guarded_jump_tables(analysis,indirect,load,body):
    if (analysis.get('schema')!='psxrecomp static analysis v1' or analysis.get('static_only') is not True or
        indirect.get('schema')!='psxrecomp indirect sites v1' or
        analysis.get('load_address')!=load or analysis.get('image_size')!=len(body)):
        raise ValueError('Jump-table analysis does not match the verified image')
    functions={item['addr']:item for item in analysis['functions'] if not item['partial'] and not item['is_data']}
    targets=set();aliases=set();proofs=[]
    for site in indirect['sites']:
        if site['classification']!='jump_table:guarded':continue
        host=functions.get(site['func'])
        if host is None:continue
        lo,hi=host['addr'],host['end'];pc=site['pc'];base=site['table_base'];count=site['table_count']
        if (not load<=lo<hi<=load+len(body) or pc%4 or not lo<=pc<hi or
            not isinstance(count,int) or not 1<=count<=4096 or base%4 or
            not load<=base<base+4*count<=load+len(body) or len(site['targets'])!=count):
            raise ValueError('Guarded jump table outside the verified producer')
        word=struct.unpack_from('<I',body,pc-load)[0]
        if site['kind']!='jr' or word&0xfc1fffff!=8 or (word>>21)&31!=site['reg'] or site['reg']==31:
            raise ValueError('Guarded jump-table transfer no longer matches its source instruction')
        data=body[base-load:base-load+4*count]
        values=struct.unpack(f'<{count}I',data)
        if list(values)!=site['targets']:raise ValueError('Guarded jump-table values changed')
        if any(target%4 or not lo<=target<hi for target in values):
            # Cross-function tables need their own ownership proof; retain the
            # existing fallback rather than inventing a callable boundary.
            continue
        targets.update(values)
        aliases.update((target,lo,hi) for target in values if target!=lo)
        proofs.append(dict(host_entry=lo,jr_pc=pc,table_base=base,count=count,targets=list(values),
            table_bytes_sha256=hashlib.sha256(data).hexdigest()))
    return targets,aliases,proofs


def syscall_returns(analysis,load,body,roots):
    if (analysis.get('static_only') is not True or analysis.get('load_address')!=load or
        analysis.get('image_size')!=len(body)):
        raise ValueError('Syscall analysis does not match the verified image')
    roots=set(roots);proofs=[]
    for item in analysis['functions']:
        lo,hi=item['addr'],item['end']
        if lo not in roots or item['partial'] or item['is_data']:continue
        if lo%4 or hi%4 or not load<=lo<hi<=load+len(body):raise ValueError('Syscall host outside the verified image')
        for pc in range(lo,hi-4,4):
            word=struct.unpack_from('<I',body,pc-load)[0]
            if word&0xfc00003f!=0x0c:continue
            if pc>lo and control_transfer(struct.unpack_from('<I',body,pc-load-4)[0]):continue
            proofs.append(dict(host_entry=lo,host_end=hi,syscall_pc=pc,return_pc=pc+4,instruction=word))
    return proofs


def link_branch_dispatches(analysis,load,body,roots):
    """REGIMM branch-and-link calls can enter frameless embedded SDK code."""
    if (analysis.get('static_only') is not True or analysis.get('load_address')!=load or
        analysis.get('image_size')!=len(body)):
        raise ValueError('Link-branch analysis does not match the verified image')
    functions=[item for item in analysis['functions'] if not item['partial'] and not item['is_data']]
    roots=set(roots);entries=set();aliases=set();proofs=[]
    for item in functions:
        lo,hi=item['addr'],item['end']
        if lo not in roots:continue
        if lo%4 or hi%4 or not load<=lo<hi<=load+len(body):raise ValueError('Link-branch host outside the verified image')
        for pc in range(lo,hi-4,4):
            word,slot=struct.unpack_from('<2I',body,pc-load)
            if word>>26!=1 or (word>>16)&31 not in (16,17) or control_transfer(slot):continue
            if pc>lo and control_transfer(struct.unpack_from('<I',body,pc-load-4)[0]):continue
            displacement=word&0xffff
            if displacement&0x8000:displacement-=0x10000
            target=(pc+4+4*displacement)&0xffffffff
            owner=next((f for f in functions if f['addr']<=target<f['end']),None)
            if owner is None or not load<=target<load+len(body):continue
            entries.add(target);aliases.add((target,owner['addr'],owner['end']))
            if pc+8<hi:entries.add(pc+8);aliases.add((pc+8,lo,hi))
            proofs.append(dict(host_entry=lo,branch_pc=pc,target=target,return_pc=pc+8,instruction=word,delay_slot=slot))
    return entries,aliases,proofs


@lru_cache(maxsize=3)
def _extractor(framework):
    return runpy.run_path(str(Path(framework)/'tools/aot_overlay_spike/extract_generic.py'))


def static_dispatches(framework,analysis,indirect,load,body,roots):
    table_roots,table_proofs=nullable_function_tables(analysis,load,body)
    roots=sorted(set(roots)|set(table_roots))
    extracted=_extractor(str(Path(framework).resolve()))['reachable_static_dispatches'](body,load,roots)
    targets,aliases,proofs=guarded_jump_tables(analysis,indirect,load,body)
    exceptions=syscall_returns(analysis,load,body,roots)
    targets.update(item['return_pc'] for item in exceptions)
    aliases.update((item['return_pc'],item['host_entry'],item['host_end']) for item in exceptions)
    link_entries,link_aliases,link_proofs=link_branch_dispatches(analysis,load,body,roots)
    targets.update(link_entries);aliases.update(link_aliases)
    return_entries,return_aliases,return_proofs=masked_return_tables(analysis,load,body)
    targets.update(return_entries);aliases.update(return_aliases)
    local_entries,local_aliases,local_proofs=local_control_entries(analysis,load,body)
    targets.update(local_entries);aliases.update(local_aliases)
    entries=sorted(targets|set(extracted['dispatch_pcs']))
    return dict(entries=entries,aliases=sorted(aliases),
        function_roots=table_roots,function_table_proofs=table_proofs,
        jump_table_proofs=[*extracted['jump_table_proofs'],*proofs],
        call_continuations=extracted['call_continuation_pcs'],syscall_returns=exceptions,link_branches=link_proofs,
        masked_return_tables=return_proofs,local_control_proofs=local_proofs)
