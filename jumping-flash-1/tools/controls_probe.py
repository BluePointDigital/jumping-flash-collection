"""Bounded live controls check in a manually entered, flat first-stage spawn."""
from pathlib import Path
import argparse
import json
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'collection/tools'))
from diagnostics import Client
from player_state import state

def probe(port,output):
    client=Client(port);report=dict(schema=1,method='Windows live manual stage, process-local SDL gamepad; physical/Deck acceptance excluded',samples={})
    def sample(name):
        player=state(client);host=client.query('collection_input')
        if len(player['profiles'])!=1 or player['profiles'][0]['fields']['demo_mode']!=0:raise RuntimeError('A verified manual JF1 stage is required')
        report['samples'][name]=dict(player=player,host=host)
        return player['profiles'][0]['values']
    def axes(**values):client.query('collection_input',enable=1,buttons=0,**values)
    def move(name,**values):
        axes();time.sleep(.18);before=sample(name+'-before');axes(**values);time.sleep(.3);after=sample(name+'-held')
        axes();time.sleep(.18);sample(name+'-released');return before,after
    try:
        axes();time.sleep(.4);sample('initial')
        checks={}
        for name,axis,value,field,sign in [('strafe-right','lx',32767,'68',1),('strafe-left','lx',-32767,'68',-1),
                                         ('forward','ly',-32767,'70',1),('back','ly',32767,'70',-1)]:
            before,after=move(name,**{axis:value})
            checks[name]=sign*(after[field]-before[field])>0 and after['8C']==before['8C']
        before,after=move('aim-right',rx=16384)
        checks['yaw-aim']=after['8C']!=before['8C'] and after['68']==before['68'] and after['70']==before['70']
        before,after=move('aim-down',ry=16384)
        checks['pitch-aim']=after['90']>before['90']
        before=sample('neutral-before');time.sleep(.3);after=sample('neutral-after')
        checks['neutral-stops']=after['68']==before['68'] and after['70']==before['70']
        checks['pitch-persists']=after['90']==before['90']
        checks['native-movement-command-hook-ran']=all(s['host']['jf1']['move_updates']>0 for name,s in report['samples'].items() if name.endswith('-held'))
        report['checks']=checks;report['passed']=all(checks.values())
    finally:
        client.query('collection_input',enable=0)
        output.parent.mkdir(parents=True,exist_ok=True);output.write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(passed=report['passed'],checks=report['checks']),indent=2))
    return report['passed']

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,default=4391);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    raise SystemExit(0 if probe(args.port,args.output) else 1)
