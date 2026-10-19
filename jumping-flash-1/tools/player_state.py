"""Read player state only after exact live routine fingerprints match an overlay."""
from pathlib import Path
import argparse
import json
import struct
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'collection/tools'))
from diagnostics import Client

ROOT=Path(__file__).resolve().parents[1]
def state(client):
    ram=bytes.fromhex(client.query('read_ram',addr='80000000',len=2097152)['hex'])
    profiles=json.loads((ROOT/'.workbench/evidence/controls-layouts.json').read_text())['profiles']
    found=[]
    for profile in profiles:
        good=True
        for guard in profile['guards'].values():
            address=int(guard['address'],16)&0x1fffff
            expected=struct.pack('<'+'I'*len(guard['words']),*(int(w,16) for w in guard['words']))
            if ram[address:address+len(expected)]!=expected:good=False;break
        if not good:continue
        fields={k:struct.unpack_from('<I',ram,int(address,16)&0x1fffff)[0]
                for k,address in profile['fields'].items() if k!='player'}
        player=int(profile['fields']['player'],16)&0x1fffff
        values={f'{offset:02X}':struct.unpack_from('<i',ram,player+offset)[0]
                for offset in (0x68,0x6c,0x70,0x74,0x78,0x7c,0x8c,0x90,0x98,0x9c,0xa4,0xac,0xb0)}
        found.append(dict(image=profile['image'],player=profile['fields']['player'],fields=fields,values=values,
            state=struct.unpack_from('<H',ram,player+0x18)[0],health=struct.unpack_from('<H',ram,player+0x5c)[0]))
    frame=client.query('frame')['frame'];gpu=client.query('gpu_state')
    return dict(frame=frame,recent_3d=not gpu['disabled'] and 0<=frame-gpu['ws']['last_3d_frame']<=8,profiles=found)

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=4391);parser.add_argument('--output',type=Path);args=parser.parse_args()
    result=state(Client(args.port))
    if args.output:args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2))
    print(json.dumps(result,indent=2))
