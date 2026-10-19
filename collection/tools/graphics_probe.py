"""Bounded hidden-window GPU probe; it cannot qualify visible output or campaigns."""
from pathlib import Path
import argparse
import json
import os
import shutil
import subprocess
import time
import tomllib
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent))
from diagnostics import Client
from cache_identity import seed_cache


def probe(root,identity,data,port,seconds,executable=None,resolution=1080,allow_empty_cache=False):
    game=next(g for g in tomllib.loads((root/'catalog.toml').read_text())['games'] if g['id']==identity)
    if data.exists():raise ValueError('Use a new private probe directory')
    data.mkdir(parents=True)
    cache_seed=seed_cache(root,game,data,allow_empty_cache)
    (data/'settings.toml').write_text('''[video]
renderer = "opengl"
internal_resolution = RESOLUTION
aspect_ratio = "4:3"
window_width = 1280
fullscreen = 0
render_thread = true
present_thread = false
frame_generation = true
frame_generation_method = "redraw"
frame_interpolation = false
dynamic_resolution = false
geometry_correction = false
perspective_texturing = false
vsync = "on"
[desktop]
control_style = "modern"
audio_volume = 0
muted = true
native_menu = true
[controller]
p1_device = "keyboard"
p1_mode = "digital"
[launcher]
skip_launcher = true
'''.replace('RESOLUTION',str(resolution)))
    environment=os.environ.copy();environment['PSX_FRAME_GEN']='1';environment['PSX_FRAME_GEN_METHOD']='redraw'
    for key in ('PSX_LOAD_SLOT','PSX_OVERLAY_UNIT_DEFER','PSX_FRAME_GEN_FORCE','PSX_HOST_REFRESH_HZ','PSX_HOST_REFRESH_MAX_HZ'):
        environment.pop(key,None)
    command=[str(executable or root/game['executable']),'--game',str(root/game['config']),'--bios',str(root/game['bios']),
        '--disc',str(root/game['disc']),'--no-launcher','--hidden-window','--collection-mode',
        '--user-data-dir',str(data),'--debug-port',str(port)]
    report=dict(schema=1,game=identity,resolution_lines=resolution,cache_seed=cache_seed,method='Hidden real OpenGL context, redraw smoothing. Boot/menu/attract sampling; no visible-FPS, audio or campaign qualification.',samples=[])
    client=Client(port);started=time.monotonic()
    with (data/'graphics.log').open('wb') as log:
        process=subprocess.Popen(command,cwd=data,env=environment,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            while True:
                if process.poll() is not None:raise RuntimeError(f'GPU probe exited during startup ({process.returncode})')
                try:client.query('frame');break
                except OSError:
                    if time.monotonic()-started>60:raise RuntimeError('GPU diagnostic server did not start')
                    time.sleep(.25)
            deadline=time.monotonic()+seconds;pulses=0;last_pulse=-1000
            while time.monotonic()<deadline:
                frame=client.query('frame')['frame'];gpu=client.query('gpu_state')
                if frame>=1500 and frame-last_pulse>=300 and pulses<4:
                    client.query('press',buttons=0xfff7 if pulses==0 else 0xbfff,frames=15)
                    pulses+=1;last_pulse=frame
                sample=dict(wall_seconds=time.monotonic()-started,frame=frame,
                    recent_3d_frame=gpu['ws']['last_3d_frame'],disabled=gpu['disabled'],
                    gpu=gpu,
                    redraw=client.query('frame_gen'),render_thread=client.query('render_thread'))
                report['samples'].append(sample)
                (data/'graphics-receipt.json').write_text(json.dumps(report,indent=2))
                if len(report['samples'])%5==0:
                    redraw=sample['redraw']
                    print(json.dumps(dict(seconds=round(sample['wall_seconds']),frame=frame,
                        generated=redraw['generated'],swaps=redraw['swaps'],
                        rejected=redraw['rejected'],reason=redraw['noplan_why'] or redraw['reject_why'])),flush=True)
                time.sleep(3)
        finally:
            if process.poll() is None:
                try:client.query('clear_input');client.query('quit')
                except (OSError,RuntimeError):pass
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
            report['exit_code']=process.returncode
            (data/'graphics-receipt.json').write_text(json.dumps(report,indent=2))
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True);parser.add_argument('--game',choices=('jf1','jf2','robbit'),required=True)
    parser.add_argument('--data',type=Path,required=True);parser.add_argument('--port',type=int,default=4394);parser.add_argument('--seconds',type=float,default=120)
    parser.add_argument('--resolution',type=int,choices=(720,1080),default=1080)
    parser.add_argument('--allow-empty-cache',action='store_true',help='Explicit cold-cache experiment; never label it warm')
    parser.add_argument('--executable',type=Path,help='Private rebuilt runtime for an A/B probe');args=parser.parse_args()
    probe(args.root.resolve(),args.game,args.data.resolve(),args.port,args.seconds,args.executable.resolve() if args.executable else None,args.resolution,args.allow_empty_cache)
