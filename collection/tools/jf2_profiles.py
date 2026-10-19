"""Recover guarded PAL control layouts; this does not enable runtime writes."""
import argparse
import json
from pathlib import Path
import struct

from robbit_profiles import (call_target, digest, fnv64,merge_hook_sites,
                             normalized, require, source_functions)

REFERENCE = 'JF2_W1/MAIN.PEX'
ROLES = dict(update=0x800e1528, camera=0x800e7f1c, pitch=0x800e2b4c,
             movement=0x800e2550, restore=0x800e2b90)
FIELDS=('actor','pad','movement_mode','base_speed','look_mode','camera_pointer')


def address_pair(words, high, low):
    a,b=words[high],words[low]
    require(low==high+1 and a>>26==15 and a>>16&31==b>>21&31 and
            b>>26 in (9,0x23,0x2b), 'JF2 address-pair register/opcode roles changed')
    immediate=b&0xffff
    value=((a&0xffff)<<16)+(immediate-0x10000 if immediate&0x8000 else immediate)
    require(0x80000000<=value<0x80200000,'JF2 field outside RAM')
    return value


def derive(name, body, functions, reference):
    index = {}
    for address, words in functions.items():
        index.setdefault(normalized(words), []).append(address)
    addresses = {}
    for role, address in ROLES.items():
        hits = index.get(normalized(reference[address]), [])
        require(len(hits) == 1, f'{name}: ambiguous/missing {role}')
        addresses[role] = hits[0]
    words = {role:functions[address] for role,address in addresses.items()}
    # The adapter writes actor fields, so reject any changed actor-relative access.
    for role, actor_register in (('update',17), ('pitch',4), ('movement',16), ('restore',18)):
        for original, candidate in zip(reference[ROLES[role]], words[role]):
            if 0x20 <= original >> 26 <= 0x2e and original >> 21 & 31 == actor_register:
                require(original == candidate, f'{name}: {role} actor field changed')
    for role, instructions in words.items():
        for original, candidate in zip(reference[ROLES[role]], instructions):
            if original >> 26 == 15 and not 0x8000 <= original & 0xffff < 0x8020:
                require(original == candidate, f'{name}: {role} constant changed')
    update, movement, restore = words['update'], words['movement'], words['restore']
    fields = dict(actor=address_pair(update,2,3), pad=address_pair(update,92,93),
        movement_mode=address_pair(update,97,98), base_speed=address_pair(movement,3,4),
        look_mode=address_pair(movement,36,37), camera_pointer=address_pair(words['camera'],0,1))
    require(fields['pad'] == address_pair(update,219,220) == address_pair(movement,41,42)
            == address_pair(restore,18,19) == address_pair(restore,32,33), f'{name}: pad roles disagree')
    require(fields['movement_mode'] == address_pair(update,205,206) == address_pair(movement,14,15)
            == address_pair(restore,13,14), f'{name}: movement mode roles disagree')
    require(fields['look_mode'] == fields['movement_mode']+4 and fields['pad'] == fields['look_mode']+4,
            f'{name}: command fields no longer adjacent')
    require(all(value % 4 == 0 for value in fields.values()) and fields['actor']+0x100 < 0x80200000,
            f'{name}: field alignment/extent changed')
    require(call_target(update,402) == addresses['camera'], f'{name}: update camera call changed')
    require(update[405:408] == (0x8e240088,0x8e25008c,0x00042023) and
            words['pitch'][0] == 0x8c82008c and movement[(0x800e28f4-ROLES['movement'])//4] == 0xae0200ac,
            f'{name}: orientation/velocity roles changed')
    guards = {}
    for role, instructions in words.items():
        data=struct.pack(f'<{len(instructions)}I',*instructions)
        guards[role]=dict(address=hex(addresses[role]),words=len(instructions),sha256=digest(data),
            fnv64=f'{fnv64(data):016x}',first=f'{instructions[0]:08x}',last=f'{instructions[-1]:08x}')
    return dict(image=name,source_body_sha256=digest(body),sites={k:hex(v) for k,v in addresses.items()},
        fields={k:hex(v) for k,v in fields.items()},camera_return=hex(addresses['update']+404*4),guards=guards)


def recover(preparation):
    preparation=Path(preparation)
    provenance_bytes=(preparation/'provenance.json').read_bytes()
    provenance=json.loads(provenance_bytes)
    require(provenance.get('game') == 'jf2', 'Expected JF2 preparation')
    records_bytes=(preparation/'records.json').read_bytes()
    require(digest(records_bytes) == provenance['records_sha256'], 'Prepared records changed')
    require(provenance['disc_sha256']=='f09ee5cefcdcb5dc8015c41faf5409a20b12180d556721b124ac3c8478ca2d8b',
            'Unsupported JF2 PAL source disc')
    records={r['producer_name']:r for r in json.loads(records_bytes)}
    inputs={r['path']:r for r in provenance['inputs']}
    names=sorted(name for name in inputs if name.startswith(('JF2_W','JF2_E','JF2_B')) and name.endswith('/MAIN.PEX'))
    require(len(names)==24 and REFERENCE in names,'Expected 24 PAL gameplay images')
    decoded={}
    for name in names:
        analysis=(preparation/'analysis'/name/'analysis.json').read_bytes()
        image=(preparation/'analysis'/name/'verified-image.exe').read_bytes()
        authority=inputs[name]['analysis']
        require(digest(analysis)==authority['analysis_json_sha256'] and digest(image)==authority['image_sha256'],
                f'{name}: prepared source changed')
        body,functions=source_functions(records[name],json.loads(analysis))
        require(image[2048:]==body,f'{name}: record/EXE disagree')
        decoded[name]=(body,functions)
    reference=decoded[REFERENCE][1]
    return dict(schema=1,game='jf2',serial='SCES-00111',source_disc_sha256=provenance['disc_sha256'],
        provenance_sha256=digest(provenance_bytes),recovery_tool_sha256=digest(Path(__file__).read_bytes()),
        profiles=[derive(name,*decoded[name],reference) for name in names],
        runtime_installed=False,runtime_qualification_complete=False)


def hook_config(text,document=None):
    if document is None:document=json.loads((Path(__file__).resolve().parents[1]/'runtime/jf2_profiles.json').read_text())
    return merge_hook_sites(text,'SCES-00111',
        (int(p['sites'][key],16) for p in document['profiles'] for key in ROLES))


def validate_guards(profile,load,body):
    require(set(profile['guards'])==set(ROLES),'JF2 requires all five control routine guards')
    for role,guard in profile['guards'].items():
        address=int(guard['address'],16);offset=address-load;size=guard['words']*4
        require(address==int(profile['sites'][role],16) and offset%4==0 and size>0 and offset>=0 and
                offset+size<=len(body) and digest(body[offset:offset+size])==guard['sha256'],
                'JF2 control guard outside or different from source')


def render_headers(document):
    lines=['#pragma once','#include <cstdint>',
        '// Generated from verified PAL images by tools/jf2_profiles.py.',
        'struct Jf2Guard {uint32_t address,words,first,last;uint64_t hash;};',
        'struct Jf2Profile {const char* image;uint32_t '+','.join(ROLES)+',camera_return;',
        '    uint32_t '+','.join(FIELDS)+';Jf2Guard guards[5];};',
        'static constexpr Jf2Profile jf2_profiles[]={']
    for profile in document['profiles']:
        values=[int(profile['sites'][key],16) for key in ROLES]+[int(profile['camera_return'],16)]
        values.extend(int(profile['fields'][key],16) for key in FIELDS)
        lines.append('    {"'+profile['image']+'",'+','.join(f'0x{x:08x}u' for x in values)+', {')
        for key in ROLES:
            g=profile['guards'][key]
            lines.append(f'        {{{g["address"]}u,{g["words"]},0x{g["first"]}u,0x{g["last"]}u,0x{g["fnv64"]}ull}},')
        lines.append('    }},')
    lines.extend(['};','#include "jf2_control_sites.h"'])
    sites=['#pragma once','#include <stdint.h>',
        '// Prefilters only; complete code guards authorize all input writes.']
    for name,keys in (('control',ROLES),('update',('update',))):
        addresses={int(p['sites'][key],16)&0x1fffffff for p in document['profiles'] for key in keys}
        if name=='control':addresses.add(0xf3a44) # Existing separately guarded native title menu.
        sites.append(f'static inline int jf2_{name}_site(uint32_t pc){{pc&=0x1fffffffu;switch(pc){{')
        sites.extend(f'case 0x{x:x}u:' for x in sorted(addresses))
        sites.append('return 1;default:return 0;}}')
    return '\n'.join(lines)+'\n','\n'.join(sites)+'\n'


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args()
    document=recover(args.preparation)
    args.output.write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    header,sites=render_headers(document)
    args.output.with_suffix('.h').write_text(header,encoding='utf-8')
    args.output.with_name('jf2_control_sites.h').write_text(sites,encoding='utf-8')
    print(f"Recovered {len(document['profiles'])} guarded PAL layouts; runtime integration pending")


if __name__=='__main__':main()
