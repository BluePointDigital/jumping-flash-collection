"""Recover exact, per-request Robbit control layouts from verified AOT inputs."""
import argparse
import base64
import hashlib
import json
from pathlib import Path
import struct
import re
import tomllib

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = 'EVENT/00/M01.PEX'
TEMPLATES = dict(update=0x800a2778, pitch=0x800a24b4, vector=0x80099c0c,
    physical=0x8008a428, flags=0x800adac0, rotation=0x800a42ac,
    move1=0x800a3bf8, move2=0x800a675c, modes=0x800a1ef0)
FIELDS = ('player', 'live_flags', 'mode', 'lock1', 'lock2')
SITES = ('update', 'pitch', 'vector', 'rotation_return', 'move1_return', 'move2_return')


def require(condition, message):
    if not condition:
        raise ValueError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def normalized(words):
    """Nomination only; complete guards and operand-role checks authorize a layout."""
    result = []
    for word in words:
        op = word >> 26
        if op in (2, 3):
            word &= 0xfc000000
        elif op == 15 or 0x20 <= op <= 0x2e or (op == 9 and word >> 21 & 31 != 29 and word >> 16 & 31 != 29):
            word &= 0xffff0000
        result.append(word)
    return tuple(result)


def address_pair(words, high, low):
    a, b = words[high], words[low]
    require(a >> 26 == 15 and (a >> 16 & 31) == (b >> 21 & 31) and
            b >> 26 in (9, 0x21, 0x23, 0x29), 'Control address pair changed opcode/register roles')
    # The only nonadjacent pairs used here cross a store or a LUI to another register.
    reg = a >> 16 & 31
    for middle in words[high + 1:low]:
        op = middle >> 26
        require((op in (0x28, 0x29, 0x2b)) or (op == 15 and middle >> 16 & 31 != reg),
                'Control address pair crosses an unverified register write')
    immediate = b & 0xffff
    if immediate & 0x8000:
        immediate -= 0x10000
    value = ((a & 0xffff) << 16) + immediate
    require(0x80000000 <= value < 0x80200000, 'Control field outside guest RAM')
    return value


def call_target(words, index):
    require(words[index] >> 26 == 3, 'Expected control-routine direct JAL')
    return 0x80000000 | ((words[index] & 0x3ffffff) << 2)


def fnv64(data):
    value = 14695981039346656037
    for byte in data:
        value = ((value ^ byte) * 1099511628211) & 0xffffffffffffffff
    return value


def source_functions(record, analysis):
    body = base64.b64decode(record['bytes_b64'], validate=True)
    load = int(record['load_addr'], 16)
    require(len(body) == record['size'] and load % 4 == 0 and len(body) % 4 == 0 and
            0x80000000 <= load < load + len(body) <= 0x80200000, 'Invalid Robbit source bounds')
    require(analysis.get('schema') == 'psxrecomp static analysis v1' and analysis.get('static_only') is True and
            analysis['load_address'] == load and analysis['image_size'] == len(body), 'Analysis/source mismatch')
    functions = {}
    for function in analysis['functions']:
        if function['is_data'] or function['partial']:
            continue
        lo, hi = function['addr'], function['end']
        require(lo % 4 == hi % 4 == 0 and load <= lo < hi <= load + len(body), 'Control function outside source')
        functions[lo] = struct.unpack_from(f'<{(hi-lo)//4}I', body, lo-load)
    return body, functions


def derive_profile(name, body, functions, reference):
    index = {}
    for address, words in functions.items():
        index.setdefault(normalized(words), []).append(address)
    matched = {}
    for role, address in TEMPLATES.items():
        hits = index.get(normalized(reference[address]), [])
        require(len(hits) == 1, f'{name}: {role} has {len(hits)} structural candidates')
        matched[role] = hits[0]
    words = {role:functions[address] for role, address in matched.items()}
    for role in ('update', 'pitch', 'rotation'):
        for a, b in zip(reference[TEMPLATES[role]], words[role]):
            if 0x20 <= a >> 26 <= 0x2e and (a >> 21 & 31) == 17:
                require(a == b, f'{name}: player-register field offset changed in {role}')
    for role, instructions in words.items():
        for a, b in zip(reference[TEMPLATES[role]], instructions):
            if a >> 26 == 15 and not 0x8000 <= a & 0xffff < 0x8020:
                require(a == b, f'{name}: non-address LUI changed in {role}')
        if role == 'vector':
            for a, b in zip(reference[TEMPLATES[role]], instructions):
                if 0x20 <= a >> 26 <= 0x2e and (a >> 21 & 31) in (6, 7):
                    require(a == b, f'{name}: walking vector output layout changed')
    player = address_pair(words['update'], 1, 3)
    require(player == address_pair(words['pitch'], 1, 3), f'{name}: player pointer disagrees')
    flags = address_pair(words['flags'], 0, 1)
    mode = address_pair(words['pitch'], 12, 13)
    mode_store = address_pair(words['modes'], 26, 27)
    lock1, lock2 = address_pair(words['modes'], 28, 29), address_pair(words['modes'], 30, 32)
    require(mode == mode_store and lock1 == mode + 2 and lock2 == mode + 4, f'{name}: mode/lock layout disagrees')
    require(player % 4 == flags % 4 == mode % 2 == 0 and player + 0x100 < 0x80200000,
            f'{name}: invalid player/flag alignment or extent')
    require(call_target(words['pitch'], 5) == matched['flags'], f'{name}: pitch flag getter changed')
    first, second = (0x800a3f5c-TEMPLATES['move1'])//4, (0x800a6844-TEMPLATES['move2'])//4
    require(call_target(words['move1'], first) == matched['vector'] and
            call_target(words['move2'], second) == matched['vector'], f'{name}: walking callees disagree')
    require(words['move1'][first-3] == 0x26060028 and words['move1'][first+1] == 0x26070020 and
            words['move2'][second-5] == 0x24e60028 and words['move2'][second+1] == 0x24e70020,
            f'{name}: walking output argument offsets changed')
    require(words['rotation'][0x168//4] >> 26 == 3 and words['rotation'][0x170//4] == 0x8e220048 and
            words['rotation'][(0x800a4554-TEMPLATES['rotation'])//4] == 0xae220010,
            f'{name}: physical-pointer/pitch transfer changed')
    sites = dict(update=matched['update'], pitch=matched['pitch'], vector=matched['vector'],
        rotation_return=matched['rotation']+0x170, move1_return=matched['move1']+first*4+8,
        move2_return=matched['move2']+second*4+8)
    guards = {}
    for role, instructions in words.items():
        data = struct.pack(f'<{len(instructions)}I', *instructions)
        guards[role] = dict(address=hex(matched[role]), words=len(instructions), sha256=digest(data),
            fnv64=f'{fnv64(data):016x}', first=f'{instructions[0]:08x}', last=f'{instructions[-1]:08x}')
    return dict(image=name, source_body_sha256=digest(body), functions={k:hex(v) for k,v in matched.items()},
        fields={k:hex(v) for k,v in dict(player=player, live_flags=flags, mode=mode, lock1=lock1, lock2=lock2).items()},
        sites={k:hex(v) for k,v in sites.items()}, guards=guards)


def recover(preparation, original_disc=None):
    preparation = Path(preparation)
    provenance = json.loads((preparation/'provenance.json').read_text())
    require(provenance.get('game') == 'robbit' and provenance['disc_sha256'] ==
            '90981ce0353dfb8b335629504e3f2bb58acd82ddb1bc19db934cc7abdfbad282', 'Unsupported Robbit source disc')
    records_bytes = (preparation/'records.json').read_bytes()
    require(digest(records_bytes) == provenance['records_sha256'], 'Robbit records changed after preparation')
    records = {r['producer_name']:r for r in json.loads(records_bytes)}
    inputs = {r['path']:r for r in provenance['inputs']}
    requests = sorted(name for name in inputs if name.startswith('EVENT/') and
                      name.split('/')[-1].startswith('M') and name.endswith('.PEX'))
    require(len(requests) == 48 and REFERENCE in requests, 'Robbit request inventory changed')
    decoded = {}
    for name in requests:
        analysis_path = preparation/'analysis'/name/'analysis.json'
        record = records[name];authority = inputs[name]['analysis']
        image = preparation/'analysis'/name/'verified-image.exe'
        require(digest(analysis_path.read_bytes()) == authority['analysis_json_sha256'] and
                digest(image.read_bytes()) == authority['image_sha256'], f'{name}: analysis identity changed')
        body, functions = source_functions(record, json.loads(analysis_path.read_text()))
        require(image.read_bytes()[2048:] == body, f'{name}: verified analyzer input/record bytes disagree')
        decoded[name] = (body, functions)
    reference = decoded[REFERENCE][1]
    profiles = [derive_profile(name, *decoded[name], reference) for name in requests]
    if original_disc is not None:
        from aot import executable_images,decode_executable
        import runpy
        import sys
        sys.path.insert(0,str(ROOT.parent/'tools'))
        with Path(original_disc).open('rb') as stream:
            original_sha=hashlib.file_digest(stream,'sha256').hexdigest()
        require(original_sha == '45c8ff8dbda8c7e55fd327cf2282f0259ca141ece8441f34c5a54319d0741963',
                'Unsupported original Japanese disc')
        original=dict(executable_images(original_disc))
        decode=runpy.run_path(str(ROOT.parent/'tools/extract-jf2-assets.py'))['decompress_lz1']
        for profile in profiles:
            entry,load,body=decode_executable(original[profile['image']],decode)
            validate_guards(profile,load,body)
            profile['original_body_sha256']=digest(body)
    return dict(schema=1, game='robbit', serial='SCPS-10103', source_disc_sha256=provenance['disc_sha256'],
                original_disc_sha256=original_sha if original_disc is not None else None,
                profiles=profiles, provenance_sha256=digest((preparation/'provenance.json').read_bytes()),
                recovery_tool_sha256=digest(Path(__file__).read_bytes()), runtime_qualification_complete=False)


def render_headers(document):
    profiles = document['profiles']
    lines = ['#pragma once', '#include <cstdint>',
        '// Exact instruction-derived request profiles; generated by tools/robbit_profiles.py.',
        'struct RobbitGuard {uint32_t address,words,first,last;uint64_t hash;};',
        'struct RobbitProfile {const char* image;uint32_t '+','.join(SITES)+';',
        '    uint32_t '+','.join(FIELDS)+';RobbitGuard guards[9];};',
        'static constexpr RobbitProfile robbit_profiles[]={']
    sites = set()
    for profile in profiles:
        values = [int(profile['sites'][key],16) for key in SITES]
        sites.update(values[:4])
        lines.append('    {"'+profile['image']+'",'+','.join(f'0x{x:08x}u' for x in values)+',')
        lines.append('     '+','.join(f'0x{int(profile["fields"][key],16):08x}u' for key in FIELDS)+',{')
        for key in TEMPLATES:
            guard = profile['guards'][key]
            lines.append(f'        {{0x{int(guard["address"],16):08x}u,{guard["words"]},0x{guard["first"]}u,0x{guard["last"]}u,0x{guard["fnv64"]}ull}},')
        lines.append('    }},')
    lines.append('};')
    lines.append('#include "robbit_control_sites.h"')
    site_lines = ['#pragma once', '#include <stdint.h>',
        '// A prefilter only; complete per-image instruction guards authorize changes.',
        'static inline int robbit_control_site(uint32_t pc){pc&=0x1fffffffu;switch(pc){']
    site_lines.extend(f'case 0x{x&0x1fffffff:x}u:' for x in sorted(sites))
    site_lines.append('return 1;default:return 0;}}')
    updates=sorted({int(p['sites']['update'],16)&0x1fffffff for p in profiles})
    site_lines.append('static inline int robbit_update_site(uint32_t pc){pc&=0x1fffffffu;switch(pc){')
    site_lines.extend(f'case 0x{x:x}u:' for x in updates)
    site_lines.append('return 1;default:return 0;}}')
    return '\n'.join(lines)+'\n', '\n'.join(site_lines)+'\n'


def validate_guards(profile,load,body):
    require(len(profile['guards']) == 9,'Robbit profile requires all nine routine guards')
    for guard in profile['guards'].values():
        offset = int(guard['address'],16)-load; size = guard['words']*4
        require(offset % 4 == 0 and size > 0 and offset >= 0 and offset+size <= len(body) and digest(body[offset:offset+size]) == guard['sha256'],
                'Robbit control guard outside or different from request source')


def profile_roots(image, load, body, document=None):
    if document is None:
        document = json.loads((ROOT/'runtime/robbit_profiles.json').read_text())
    profile = next((p for p in document['profiles'] if p['image'] == image), None)
    if profile is None:
        return []
    require(digest(body) in (profile['source_body_sha256'],profile.get('original_body_sha256')),
            'Robbit profile requires exact verified request bytes')
    validate_guards(profile,load,body)
    return [int(profile['sites'][key],16) for key in ('update','pitch','vector')]


def hook_config(text, document=None):
    if document is None:
        document = json.loads((ROOT/'runtime/robbit_profiles.json').read_text())
    return merge_hook_sites(text,'SCPS-10103',
        (int(p['sites'][key],16) for p in document['profiles'] for key in SITES[:4]))


def merge_hook_sites(text, serial, required):
    parsed = tomllib.loads(text)
    require(parsed['game']['id'] == serial, 'Hook config belongs to another title')
    sites = set(int(raw,0) for raw in parsed.get('recompiler',{}).get('mod_instruction_sites',[]))
    sites.update(required)
    require(all(pc % 4 == 0 and 0x80000000 <= pc < 0x80200000 for pc in sites), 'Invalid Robbit hook site')
    entry = 'mod_instruction_sites = ['+', '.join(f'"0x{pc:08X}"' for pc in sorted(sites))+']'
    require(text.count('[recompiler]') == 1, 'Robbit recompiler table missing/ambiguous')
    begin = text.index('[recompiler]')+len('[recompiler]')
    following = re.search(r'(?m)^\s*\[',text[begin:])
    end = begin+following.start() if following else len(text)
    block = text[begin:end]
    if 'mod_instruction_sites' in parsed['recompiler']:
        block, count = re.subn(r'(?ms)^mod_instruction_sites\s*=\s*\[.*?\]',entry,block)
        require(count == 1, 'Robbit hook list changed syntax')
    else:
        block = '\n'+entry+block
    result = text[:begin]+block+text[end:]
    require(set(int(x,0) for x in tomllib.loads(result)['recompiler']['mod_instruction_sites']) == sites,
            'Robbit hook configuration failed round trip')
    return result


if __name__ == '__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--preparation',type=Path,required=True)
    parser.add_argument('--output',type=Path,required=True,help='Descriptor output; profiles.h and control_sites.h accompany it')
    parser.add_argument('--original-disc',type=Path,help='Also verify all profile guards against the pinned original Japanese disc')
    args=parser.parse_args();document=recover(args.preparation,args.original_disc)
    args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(document,indent=2)+'\n',encoding='utf-8')
    header,sites=render_headers(document)
    args.output.with_suffix('.h').write_text(header,encoding='utf-8')
    args.output.with_name('robbit_control_sites.h').write_text(sites,encoding='utf-8')
    print(f'Recovered {len(document["profiles"])} exact per-request control profiles')
