"""Identify the live executable before interpreting title-specific RAM or traces."""
from pathlib import Path
import argparse
import json
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'collection/tools'))
from diagnostics import Client

ROOT = Path(__file__).resolve().parents[1]


def identify(port):
    client = Client(port)
    ram = bytes.fromhex(client.query('read_ram', addr='80000000', len=2097152)['hex'])
    home = ROOT/'.workbench/evidence/live-recovery'
    home.mkdir(parents=True,exist_ok=True)
    (home/'ram.bin').write_bytes(ram)
    pointers={}
    for target in (0x800b9978,0x800ba3a4,0x800b973c,0x800ba624):
        needle=struct.pack('<I',target);found=[];offset=0
        while (offset:=ram.find(needle,offset))>=0:
            if offset%4==0:found.append(f'{0x80000000+offset:08X}')
            offset+=4
        pointers[f'{target:08X}']=found
    print(json.dumps(dict(callback_references=pointers),indent=2))
    matches = []
    for record in json.loads((ROOT/'.workbench/evidence/recovery.json').read_text()):
        source = ROOT/'.workbench/decoded/original'/record['path']
        if not source.is_file():
            continue
        image = source.read_bytes()
        load, size = struct.unpack_from('<II',image,0x18)
        code = image[2048:2048+size]
        live = ram[load&0x1fffff:(load&0x1fffff)+size]
        # Compare aligned instruction-sized words; mutable data may differ.
        equal = sum(code[i:i+4] == live[i:i+4] for i in range(0,min(len(code),len(live)),4))
        matches.append(dict(path=record['path'],load=f'{load:08X}',bytes=size,
                            matching_words=equal,match_fraction=equal/(size/4),
                            decoded_sha256=record['decoded_sha256']))
    matches.sort(key=lambda item:item['match_fraction'],reverse=True)
    frame=client.query('frame')['frame'];gpu=client.query('gpu_state')
    report = dict(schema=1,frame=frame,matches=matches,recent_3d_frame=gpu['ws']['last_3d_frame'],
                  recent_3d=not gpu['disabled'] and 0<=frame-gpu['ws']['last_3d_frame']<=8,
                  purpose='Candidate identity; require live word fingerprints before applying any enhancement.')
    (home/'identity.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(matches[:4],indent=2))
    actors=[]
    for index in range(128):
        address=0x80114af8+index*0x13c; offset=address&0x1fffff
        words=struct.unpack_from('<79I',ram,offset)
        callbacks=[words[field//4] for field in (0x24,0x34,0x44)]
        if not any(0x800b0000 <= callback < 0x80100000 for callback in callbacks):continue
        actors.append(dict(address=f'{address:08X}',index=index,
            callbacks=[f'{value:08X}' for value in callbacks],
            position=struct.unpack_from('<3i',ram,offset+0x68),
            yaw=struct.unpack_from('<i',ram,offset+0x8c)[0],
            pitch=struct.unpack_from('<i',ram,offset+0x90)[0],active=ram[offset+0x5a]))
    (home/'actors.json').write_text(json.dumps(actors,indent=2))
    print(json.dumps(dict(candidate_actors=actors[:12],count=len(actors)),indent=2))


if __name__ == '__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=4391);args=parser.parse_args()
    identify(args.port)
