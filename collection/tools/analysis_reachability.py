"""Recover native roots behind verified jumps and split function preludes."""
from collections import deque
import hashlib
import struct


def control_transfer(word):
    op=word>>26
    return op in (1,2,3,4,5,6,7,20,21,22,23) or (op==0 and word&63 in (8,9)) or (op in (16,17,18,19) and word>>21&31==8)


def terminal_jump_roots(analysis,edges,load,body,additional_roots=()):
    if (analysis.get('schema')!='psxrecomp static analysis v1' or
        edges.get('schema')!='psxrecomp call edges v1' or analysis.get('static_only') is not True or
        analysis.get('load_address')!=load or analysis.get('image_size')!=len(body)):
        raise ValueError('Terminal-jump analysis does not match the verified image')
    functions={}
    for item in analysis['functions']:
        lo,hi=item['addr'],item['end']
        if lo%4 or hi%4 or not load<=lo<hi<=load+len(body) or item['size']!=hi-lo:
            raise ValueError('Analyzer function extent outside the verified image')
        if not item['partial'] and not item['is_data']:functions[lo]=item
    graph={address:set() for address in functions}
    for edge in edges['edges']:
        if edge['from'] in functions and edge['to'] in functions:
            graph[edge['from']].add(edge['to'])
    additions=[];fallthroughs=[]
    for address,item in functions.items():
        hi=item['end']
        if not item['ends_jr_ra'] and hi in functions and item['size']>=8:
            words=struct.unpack(f'<{item["size"]//4}I',body[address-load:hi-load])
            safe=not any(control_transfer(word) for word in words[-2:])
            for i,word in enumerate(words):
                op=word>>26;rs=word>>21&31;rt=word>>16&31
                if op==0 and word&63 in (12,13):safe=False;break
                if not control_transfer(word):continue
                # A split prelude can continue after an ordinary call or an
                # unknown conditional branch. No unconditional jump/return,
                # constant-taken branch or control transfer in its slot.
                ordinary=(op==3 or op in (4,5) and rs!=rt or op in (6,7) and rs!=0)
                if not ordinary or i+1==len(words) or control_transfer(words[i+1]):safe=False;break
            if safe:
                graph[address].add(hi)
                fallthroughs.append(dict(source=hex(address),target=hex(hi),
                    prefix_sha256=hashlib.sha256(body[address-load:hi-load]).hexdigest()))
        if item['size']<8:continue
        pc=item['end']-8
        word,slot=struct.unpack_from('<2I',body,pc-load)
        if word>>26!=2:continue
        # A control transfer in a delay slot has no ordinary static edge proof.
        if control_transfer(slot):continue
        target=((pc+4)&0xf0000000)|((word&0x03ffffff)<<2)
        if target not in functions or target==address:continue
        if target not in graph[address]:
            graph[address].add(target)
            additions.append(dict(source=hex(address),pc=hex(pc),target=hex(target),instruction=hex(word),delay_slot=hex(slot)))
    originally_reachable={address for address,item in functions.items() if item['reachable']}
    additional_roots=set(additional_roots)
    if any(pc not in functions or not functions[pc]['ends_jr_ra'] for pc in additional_roots):
        raise ValueError('Additional static graph root is not a complete known returning function')
    reachable=originally_reachable|additional_roots;queue=deque(sorted(reachable))
    while queue:
        for target in graph[queue.popleft()]:
            if target not in reachable:reachable.add(target);queue.append(target)
    # This is the analyzer's existing High criterion, with the repaired graph.
    # Neither prologues nor execution bits are invented for interiors or data.
    recovered=sorted(address for address in reachable-originally_reachable if functions[address]['ends_jr_ra'])
    return recovered,dict(policy='Existing static call/address-taken graph plus exact terminal J and bounded fallthrough-prelude edges to known function entries; retain nonpartial/nondata jr-ra requirement',
        terminal_edges=additions,fallthrough_edges=fallthroughs,additional_roots=[hex(pc) for pc in sorted(additional_roots)],
        recovered_roots=[hex(pc) for pc in recovered],runtime_evidence_used=False)
