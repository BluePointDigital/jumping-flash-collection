"""Check a resumed controller remains blocked until its held axis is released."""
from pathlib import Path
import json
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]/'collection/tools'))
from diagnostics import Client
client=Client(4391);report={}
time.sleep(.3)
report['resume_held']=client.query('collection_input')
report['frame_after_resume']=client.query('frame')
client.query('collection_input',enable=1,buttons=0,lx=0);time.sleep(.2)
report['neutral']=client.query('collection_input')
client.query('collection_input',enable=1,buttons=0,lx=32767);time.sleep(.25)
report['fresh']=client.query('collection_input')
client.query('collection_input',enable=1,buttons=0,lx=0);time.sleep(.2)
report['released']=client.query('collection_input')
report['passed']=report['resume_held']['jf1']['movement']==[0.,0.] and report['fresh']['jf1']['movement'][0]>.9 and report['released']['jf1']['movement']==[0.,0.]
output=Path(__file__).resolve().parents[1]/'.workbench/evidence/controller-resume-release.json'
output.write_text(json.dumps(report,indent=2));print(json.dumps(report,indent=2))
raise SystemExit(0 if report['passed'] else 1)
