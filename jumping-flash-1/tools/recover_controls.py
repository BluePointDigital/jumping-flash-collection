"""Match common player routines across verified USA overlays; emit exact guards."""
from pathlib import Path
import hashlib
import json
import re
import struct

ROOT=Path(__file__).resolve().parents[1]
TEMPLATES={'player':0x800dbbe4,'update':0x800dc4c4,'movement':0x800dd158,
           'pitch':0x800dd534,'pitch_integrate':0x800dd750,
           'yaw':0x800dd794,'vector':0x800dcee0,
           'pad_service':0x800f2e50,'pad_capture':0x800f32bc,'gate':0x800dbc98}

def functions(image):
    text=(ROOT/'.workbench/analysis/original'/image/'disassembly.txt').read_text()
    result={}
    for block in text.split('/* ------------------------------------------------------------ */'):
        header=re.search(r'/\* func_([0-9A-F]{8})',block)
        if header:
            instructions=re.findall(r'^    ([0-9A-F]{8})  ([0-9A-F]{8}) ',block,re.M)
            result[int(header[1],16)]=[(int(a,16),int(w,16)) for a,w in instructions]
    return result

def normalized(instructions):
    result=[]
    for _,word in instructions:
        op=word>>26
        if op in (2,3):word &= 0xfc000000
        elif op==15 or 0x20<=op<=0x2e:word &= 0xffff0000
        elif op==9:
            immediate=struct.unpack('<h',struct.pack('<H',word&0xffff))[0]
            if abs(immediate)>1000:word &= 0xffff0000
        result.append(word)
    return result

def address_pair(instructions,index):
    high=instructions[index][1]&0xffff
    low=struct.unpack('<h',struct.pack('<H',instructions[index+1][1]&0xffff))[0]
    return (high<<16)+low

def field_address(base,actual,expected):
    for index in range(len(base)-1):
        if base[index][1]>>26==15 and address_pair(base,index)==expected:
            return address_pair(actual,index)
    raise ValueError(f'Global address {expected:08X} absent from template')

def generate():
    base=functions('JM1/MAIN.PEX');profiles=[]
    for record in json.loads((ROOT/'.workbench/evidence/recovery.json').read_text()):
        if not record['path'].startswith('JM'):continue
        image=record['path'];source=ROOT/'.workbench/decoded/original'/image
        if hashlib.sha256(source.read_bytes()).hexdigest()!=record['decoded_sha256']:raise ValueError('Decoded image changed')
        candidates=functions(image);matched={}
        for key,address in TEMPLATES.items():
            pattern=normalized(base[address])
            hits=[a for a,ins in candidates.items() if normalized(ins)==pattern]
            # The player getter has several look-alike constant accessors. The
            # movement caller identifies the player's exact getter separately.
            if key=='player':continue
            if len(hits)!=1:raise ValueError(f'{image}: {key} has {len(hits)} structural matches')
            matched[key]=hits[0]
        update=candidates[matched['update']]
        player=address_pair(update,5)
        getters=[a for a,ins in candidates.items() if len(ins)==4 and
                 ins[0][1]>>26==15 and ins[1][1]>>26==9 and
                 ins[2][1]==0x03e00008 and address_pair(ins,0)==player]
        if len(getters)!=1:raise ValueError(f'{image}: player accessor not unique')
        matched['player']=getters[0]
        movement=candidates[matched['movement']]
        pitch=candidates[matched['pitch']]
        def field(key,address):return field_address(base[TEMPLATES[key]],candidates[matched[key]],address)
        fields={'player':player,'demo_mode':field('pad_service',0x80102fec),
                'pad_held':field('pad_capture',0x8010301c),
                'move_flags':field('movement',0x80102c2c),
                'pitch_target':field('pitch',0x80102744),
                'control_live':field('gate',0x80102c84),
                'original_pause':field('update',0x80102c8c)}
        # Follow guarded native control-gate calls to their one-field getters.
        gate=candidates[matched['gate']]
        def callee(ins,index):
            word=ins[index][1]
            if word>>26!=3:raise ValueError('Expected guarded JAL')
            return 0x80000000|((word&0x3ffffff)<<2)
        for name,index in [('control_block',7),('finish',11),('finish2',19)]:
            address=callee(gate,index);matched[name]=address
            fields[name]=address_pair(candidates[address],0)
        movie_gate=callee(gate,15);matched['movie_gate']=movie_gate
        for name,index in [('movie',3),('movie_ready',7)]:
            address=callee(candidates[movie_gate],index);matched[name]=address
            fields[name]=address_pair(candidates[address],0)
        # Exact instruction-derived addresses are checked against the known
        # common routine offsets rather than accepted on a structural guess.
        if image=='JM1/MAIN.PEX':
            assert player==0x801380b8
            assert fields['demo_mode']==0x80102fec and fields['pad_held']==0x8010301c
        profiles.append(dict(image=image,decoded_sha256=record['decoded_sha256'],
            functions={k:f'{v:08X}' for k,v in matched.items()},
            fields={k:f'{v:08X}' for k,v in fields.items()},
            guards={k:dict(address=f'{matched[k]:08X}',words=[f'{w:08X}' for _,w in candidates[matched[k]]])
                    for k in ('update','movement','pitch','pitch_integrate','yaw','vector','player','gate',
                              'control_block','finish','finish2','movie_gate','movie','movie_ready','pad_service','pad_capture')}))
    output=ROOT/'.workbench/evidence/controls-layouts.json';output.write_text(json.dumps(dict(schema=1,
        purpose='Structurally matched, exact fingerprint-guarded candidates; live controls still require validation.',profiles=profiles),indent=2))
    print(json.dumps([dict(image=p['image'],functions=p['functions'],fields=p['fields']) for p in profiles],indent=2))
    return profiles

if __name__=='__main__':generate()
