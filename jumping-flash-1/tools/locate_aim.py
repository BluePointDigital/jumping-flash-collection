"""Compare neutral/right/neutral/left controller samples to find aim fields."""
from pathlib import Path
import argparse
import array
import json
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'collection/tools'))
from diagnostics import Client


def locate(port, output):
    client=Client(port);snapshots=[];states=[]
    frame=client.query('frame')['frame'];gpu=client.query('gpu_state')
    if gpu['disabled'] or frame-gpu['ws']['last_3d_frame']>8:
        raise RuntimeError('No recent 3D gameplay frame; do not interpret title/stage-picker RAM as player aim')
    def snapshot(name):
        frame=client.query('frame')['frame']
        raw=bytes.fromhex(client.query('read_ram',addr='80050000',len=0x130000)['hex'])
        (output/(name+'.bin')).write_bytes(raw);snapshots.append(raw)
        states.append(dict(name=name,frame=frame,pad=client.query('collection_input')['pad_word']))
    output.mkdir(parents=True,exist_ok=True)
    try:
        client.query('collection_input',enable=1,buttons=0);time.sleep(.5)
        snapshot('neutral1');time.sleep(.6);snapshot('neutral2')
        client.query('collection_input',enable=1,buttons=1 << 14);time.sleep(.7);snapshot('right')
        client.query('collection_input',enable=1,buttons=0);time.sleep(.4);snapshot('neutral3')
        client.query('collection_input',enable=1,buttons=1 << 13);time.sleep(.7);snapshot('left')
        client.query('collection_input',enable=1,buttons=0);time.sleep(.4);snapshot('neutral4')
    finally:
        client.query('collection_input',enable=0)
    halfwords=[]
    for raw in snapshots:
        values=array.array('H');values.frombytes(raw);halfwords.append(values)
    candidates=[]
    for index, values in enumerate(zip(*halfwords)):
        a,b,c,d,e,f=values
        if a==b and c==d and e==f and b!=c and d!=e:
            candidates.append(dict(address=f'{0x80050000+index*2:08X}',values=values))
    report=dict(schema=1,method='Causal digital turn input; candidate fields need instruction and camera validation.',states=states,candidates=candidates)
    (output/'aim-candidates.json').write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(states=states,candidate_count=len(candidates),candidates=candidates[:12]),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=4391);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    locate(args.port,args.output.resolve())
