"""Exercise one process-local SDL controller; physical hardware is a separate gate."""
import argparse
import json
from pathlib import Path
import time
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from diagnostics import Client


def probe(port, button, output):
    client=Client(port);report=dict(schema=1,method='Process-local virtual SDL gamepad, no physical/Deck qualification',samples=[])
    try:
        client.query('collection_input',enable=1,buttons=0)
        time.sleep(.4)
        report['neutral']=dict(host=client.query('collection_input'),guest=client.query('pad_status'))
        client.query('collection_input',enable=1,buttons=1 << button)
        for _ in range(4):
            time.sleep(.2)
            report['samples'].append(dict(host=client.query('collection_input'),guest=client.query('pad_status')))
        client.query('collection_input',enable=1,buttons=0)
        time.sleep(.3)
        report['released']=dict(host=client.query('collection_input'),guest=client.query('pad_status'))
    finally:
        client.query('collection_input',enable=0)
        output.parent.mkdir(parents=True,exist_ok=True)
        output.write_text(json.dumps(report,indent=2))
    print(json.dumps(dict(neutral=report['neutral']['host']['pad_word'],
        pressed=[sample['host']['pad_word'] for sample in report['samples']],
        guest=[sample['guest']['slot0']['buttons'] for sample in report['samples']],
        released=report['released']['host']['pad_word']),indent=2))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,required=True)
    parser.add_argument('--button',type=int,choices=range(21),default=6);parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    probe(args.port,args.button,args.output)
