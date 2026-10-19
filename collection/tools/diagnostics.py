"""Diagnostic collection across the three isolated local runtimes."""
from pathlib import Path
import argparse
import json
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
try:
    from runtime_diagnostics import Client,measure
except ModuleNotFoundError:
    import importlib.util
    spec=importlib.util.spec_from_file_location('robbit_diagnostic_core',Path(__file__).resolve().parents[2]/'robbit-mon-dieu/tools/diagnostics.py')
    core=importlib.util.module_from_spec(spec);spec.loader.exec_module(core)
    Client,measure=core.Client,core.measure

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--port',type=int,required=True);parser.add_argument('command');parser.add_argument('--args',default='{}');parser.add_argument('--seconds',type=float,default=60);parser.add_argument('--output',type=Path)
    args=parser.parse_args();client=Client(args.port)
    try:result=measure(client,args.seconds) if args.command=='measure' else client.query(args.command,**json.loads(args.args))
    except RuntimeError as error:
        if args.command!='quit' or str(error)!='Runtime closed the diagnostic connection':raise
        result=dict(exit_requested=True,diagnostic_socket_closed=True)
    if args.output:
        args.output.parent.mkdir(parents=True,exist_ok=True);args.output.write_text(json.dumps(result,indent=2),encoding='utf-8')
    print(json.dumps(result,indent=2))

if __name__=='__main__':main()
