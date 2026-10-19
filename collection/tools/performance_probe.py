"""Bounded Windows GL diagnostic run using context-free collection metrics.

Internal swap completion times are not physical presentation or campaign proof.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import time
import tomllib
import sys
TOOL_DIR=Path(__file__).resolve().parent
if (TOOL_DIR/'diagnostics.py').is_file():
    sys.path.insert(0,str(TOOL_DIR))
else:
    SOURCE_ROOT=next((p for p in TOOL_DIR.parents if (p/'collection/catalog.toml').is_file()),None)
    if SOURCE_ROOT is None:raise ImportError('Missing adjacent diagnostic tools; copy the complete tools folder')
    sys.path.append(str(SOURCE_ROOT/'collection/tools'))
from diagnostics import Client
from cache_identity import seed_cache
from aot_package import verify_runtime_executable

VIRTUAL_INPUT_BUTTON_INDEX = 0
VIRTUAL_INPUT_EXPECTED_WORD = 0xBFFF


def process_cpu_seconds(handle):
    import ctypes
    from ctypes import wintypes
    api=ctypes.WinDLL('kernel32',use_last_error=True).GetProcessTimes
    api.argtypes=[wintypes.HANDLE]+[ctypes.POINTER(wintypes.FILETIME)]*4
    api.restype=wintypes.BOOL
    times=[wintypes.FILETIME() for _ in range(4)]
    if not api(int(handle),*(ctypes.byref(value) for value in times)):
        return None
    return sum((value.dwHighDateTime<<32)|value.dwLowDateTime for value in times[2:])/1e7


def summarize(samples):
    if len(samples)<2:return {'unavailable':'fewer than two snapshots'}
    end=samples[-1]
    start=next((s for s in samples if s['seconds']>=end['seconds']-20),samples[0])
    dt=end['seconds']-start['seconds']
    if dt<=0:return {'unavailable':'zero observation interval'}
    window=[s for s in samples if s['seconds']>start['seconds']]
    rows=[row for s in window for row in s['metrics']['samples']]
    intervals=[(b[1]-a[1])/1e6 for a,b in zip(rows,rows[1:]) if b[0]==a[0]+1]
    def pct(p):
        import math
        return sorted(intervals)[max(0,math.ceil(len(intervals)*p)-1)] if intervals else None
    cpu_start=start.get('process_cpu_seconds');cpu_end=end.get('process_cpu_seconds')
    return dict(window_seconds=dt,guest_hz=(end['frame']-start['frame'])/dt,
        process_cpu_ms_per_wall_second=(cpu_end-cpu_start)*1000/dt if cpu_start is not None and cpu_end is not None else None,
        swap_calls_per_second=(end['metrics']['swap_calls']-start['metrics']['swap_calls'])/dt if end['metrics'].get('metrics_enabled',True) else None,
        generated_swap_calls_per_second=(end['metrics']['generated_swap_calls']-start['metrics']['generated_swap_calls'])/dt if end['metrics'].get('metrics_enabled',True) else None,
        swap_completion_interval_p50_ms=pct(.5),swap_completion_interval_p95_ms=pct(.95),
        swap_completion_interval_p99_ms=pct(.99),swap_completion_interval_max_ms=max(intervals) if intervals else None,
        collected_swap_samples=len(rows),missing_between_rows=sum(max(0,b[0]-a[0]-1) for a,b in zip(rows,rows[1:])),
        producer_sample_drops=end['metrics']['sample_drops']-start['metrics']['sample_drops'],
        audio_underrun_sample_frames=end['audio']['out']['underruns']-start['audio']['out']['underruns'],
        audio_overflow_sample_frames=end['audio']['out']['overflow_drops']-start['audio']['out']['overflow_drops'],
        physical_present_fps=None,world_update_hz=None)


def assess_virtual_input(report):
    """Require the probe's injected A mask on host and guest, then a clean release."""
    expected_word = VIRTUAL_INPUT_EXPECTED_WORD
    def word(value):
        try:
            return int(value, 0) & 0xFFFF if isinstance(value, str) else int(value) & 0xFFFF
        except (TypeError, ValueError):
            return None

    neutral = report.get('neutral') or {}
    released = report.get('released') or {}
    neutral_host = neutral.get('host') or {}
    neutral_guest = neutral.get('guest') or {}
    released_host = released.get('host') or {}
    released_guest = released.get('guest') or {}
    neutral_guest_pad = (neutral_guest.get('slot0') or {}).get('buttons')
    released_guest_pad = (released_guest.get('slot0') or {}).get('buttons')
    device_registered = (
        int(neutral_host.get('controllers') or 0) > 0
        and bool(neutral_host.get('virtual_probe'))
        and bool((neutral_guest.get('slot0') or {}).get('connected'))
    )
    neutral_seen = word(neutral_host.get('pad_word')) == 0xFFFF and word(neutral_guest_pad) == 0xFFFF
    released_seen = word(released_host.get('pad_word')) == 0xFFFF and word(released_guest_pad) == 0xFFFF
    samples = report.get('samples') if isinstance(report.get('samples'), list) else []
    host_pressed = any(word((sample.get('host') or {}).get('pad_word')) == expected_word for sample in samples)
    guest_pressed = any(word(((sample.get('guest') or {}).get('slot0') or {}).get('buttons')) == expected_word for sample in samples)
    paired_press = any(
        word((sample.get('host') or {}).get('pad_word')) == expected_word
        and word(((sample.get('guest') or {}).get('slot0') or {}).get('buttons')) == expected_word
        for sample in samples
    )
    reasons = []
    if not device_registered:
        reasons.append('virtual controller was not registered in both host and guest')
    if not neutral_seen:
        reasons.append('neutral baseline was not observed by both host and guest')
    if not host_pressed:
        reasons.append(f'host never reported the injected 0x{expected_word:04X} button mask')
    if not guest_pressed:
        reasons.append(f'guest never reported the injected 0x{expected_word:04X} button mask')
    elif not paired_press:
        reasons.append('host and guest press samples did not coincide')
    if not released_seen:
        reasons.append('host and guest did not both return to neutral after release')
    return dict(
        device_registered=device_registered,
        expected_button_mask=f'0x{expected_word:04X}',
        neutral_seen=neutral_seen,
        host_button_observed=host_pressed,
        guest_button_observed=guest_pressed,
        paired_press_observed=paired_press,
        released=released_seen,
        functional_check_passed=not reasons,
        input_focus_samples=[(sample.get('host') or {}).get('input_focus') for sample in samples],
        release_guard_blocked_samples=[(sample.get('host') or {}).get('release_gate_a_blocked') for sample in samples],
        failure_reasons=reasons,
    )


def require_virtual_input_acceptance(game, observation):
    if game in ('jf1', 'jf2') and not observation.get('functional_check_passed'):
        details='; '.join(observation.get('failure_reasons') or ['input acceptance was not established'])
        focus=observation.get('input_focus_samples')
        guard=observation.get('release_guard_blocked_samples')
        raise RuntimeError(
            'Virtual SDL input functional check failed: '+details+
            f'. Runtime input_focus samples={focus}, neutral-release guard blocked samples={guard}. '
            'Keep input acceptance unqualified; focus the game window, confirm a fresh neutral release, and rerun.')


def prepare_robbit_meadow(client,start,result,data):
    """Original-menu route, no state load or game-memory writes.

    Native image guards and live flags identify the scene independently of the
    host player-hook freshness flag (the old build has an interpreted-hook gap).
    """
    deadline=time.monotonic()+180
    def wait_frame(target):
        while client.query('frame')['frame']<target:
            if time.monotonic()>deadline:raise TimeoutError('Robbit native menu route timed out')
            time.sleep(.25)
    def press(buttons,frames=10,settle=120):
        frame=client.query('frame')['frame']
        client.query('press',buttons=buttons,frames=frames)
        result['inputs'].append(dict(seconds=time.monotonic()-start,frame=frame,buttons=buttons,frames=frames,phase='native Meadow route'))
        wait_frame(frame+frames+settle)
    wait_frame(2600)
    press(0xfff7,settle=200) # Skip any remaining publisher/movie intro.
    wait_frame(3600)
    press(0xfff7,settle=200) # The native title now accepts Start.
    press(0xdfff,settle=400) # New Game -> supervisor letter.
    press(0xdfff,settle=200) # Finish letter entrance / supervisor popup.
    press(0xdfff,settle=200) # Dismiss letter -> original world map.
    press(0xffdf,frames=20,settle=30)
    press(0xffbf,frames=25,settle=30) # Initial map cursor -> Meadow HELP marker.
    client.query('screenshot_file',path=str(data/'route-map.png'))
    map_entry=[int(word,16) for word in client.query('mem_words',addr='800ba904',count=4)['words']]
    if map_entry!=[0x3c028011,0x24429ce0,0x3c038012,0x2463ea58]:
        raise RuntimeError('Expected verified English world-map entry; reject attract-mode timing, inspect route-map.png')
    for _ in range(4):press(0xdfff,settle=120) # View Request, letter, accept.
    while True:
        status=client.query('robbit_desktop_status')
        flags=int(client.query('mem_words',addr='800d101c',count=1)['words'][0],16)
        modes=client.query('mem_words',addr='800d0f58',count=2)['words']
        if status['supported'] and flags&0x00300018==0x00100000 and int(modes[0],16)>>16==1 and int(modes[1],16)==0:break
        if time.monotonic()>deadline:raise TimeoutError('Meadow did not become playable; inspect route-map.png and log')
        press(0xdfff,settle=180) # Intro dialogue / objectives; stop at live gameplay.
    client.query('clear_input')
    wait_frame(client.query('frame')['frame']+120)
    client.query('screenshot_file',path=str(data/'route-ready.png'))
    result['route_ready_seconds']=time.monotonic()-start



def static_package_runtime_contract(root,game,executable):
    """Verify a packaged static host without importing a compiler/cache identity."""
    from import_game import sha
    manifest=json.loads((root/'package-manifest.json').read_text(encoding='utf-8'))
    if manifest.get('schema')!=1 or not str(manifest.get('release','')).startswith('static-'):
        raise ValueError('Compiler-free probing requires a static package manifest')
    selected=(root/game['executable']).resolve()
    if executable!=selected or not selected.is_relative_to(root):
        raise ValueError('Select the catalog executable inside the static package')
    row=manifest.get('files',{}).get(selected.relative_to(root).as_posix(),{})
    digest=sha(selected)
    if row.get('sha256')!=digest or row.get('bytes')!=selected.stat().st_size:
        raise ValueError('Static executable does not match the package manifest')
    result=subprocess.run([str(selected),'--collection-runtime-info'],cwd=root,
        capture_output=True,text=True,timeout=60,check=True,
        creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
    info=json.loads(result.stdout)
    expected={'overlay_limits_schema':1,'overlay_limits_profile':'collection-v1',
        'overlay_candidate_capacity':262144,'overlay_capacity_tables_bytes':184549376}
    if not isinstance(info,dict) or any(type(info.get(k)) is not type(v) or info[k]!=v for k,v in expected.items()):
        raise ValueError('Unsupported static runtime resource contract')
    config=tomllib.loads((root/game['config']).read_text(encoding='utf-8'))
    if config.get('runtime',{}).get('overlay_cache') is not False:
        raise ValueError('Static package must disable the overlay DLL cache')
    return info,digest

def probe(args):
    # Reject an invalid strict Robbit input recipe before creating the data root,
    # seeding caches, or copying settings/saves.
    if args.game=='robbit' and args.functional_checks and (not args.visible or not args.gameplay_route or args.static_audit!='strict'):
        raise ValueError('Robbit functional input acceptance requires --visible, --gameplay-route, and --static-audit strict')
    runtime_env={}
    for item in getattr(args,'runtime_env',[]):
        name,separator,value=item.partition('=')
        if not separator or not name.startswith('PSX_') or not name.isidentifier() or '\x00' in value:
            raise ValueError('--runtime-env requires PSX_NAME=VALUE')
        runtime_env[name]=value
    compiler_free=getattr(args,'compiler_free_static',False)
    if compiler_free and (not args.compiler_off or args.static_audit!='strict' or args.aot_only or args.aot_preparation or args.legacy_telemetry):
        raise ValueError('--compiler-free-static requires --compiler-off --static-audit strict and no AOT/legacy options')
    preparation_start=time.monotonic()
    root=args.root.resolve();data=args.data.resolve()
    if data.exists() or root==data or root in data.parents:raise ValueError('Choose a new private data directory outside the package')
    if not 5<=args.seconds<=600:raise ValueError('seconds must be 5..600')
    with socket.socket() as port:port.bind(('127.0.0.1',args.port))
    game=next(g for g in tomllib.loads((root/'catalog.toml').read_text())['games'] if g['id']==args.game)
    if args.aot_only and not args.aot_preparation:raise ValueError('--aot-only requires an independently audited --aot-preparation')
    executable=args.executable.resolve() if args.executable else root/game['executable']
    selected_digest=None
    if compiler_free:runtime_contract,selected_digest=static_package_runtime_contract(root,game,executable)
    else:runtime_contract=verify_runtime_executable(root,executable)
    data.mkdir(parents=True)
    if compiler_free:seed=dict(namespace=None,seed_dlls=0,state='compiler-free-static-no-cache-seeding')
    elif args.aot_only:
        from cache_identity import namespace
        seed=dict(namespace=namespace(root,game).as_posix(),seed_dlls=0,state='audited-preparation-only')
    else:seed=seed_cache(root,game,data,args.allow_empty_cache)
    if args.aot_preparation:
        from aot_package import seed_preparation
        seed['audited_supplement']=seed_preparation(root,game,data,args.aot_preparation.resolve())
    source=root/'data/games'/args.game
    for name in ('settings.toml','keybinds.ini','input.ini'):
        if (source/name).is_file():shutil.copy2(source/name,data/name)
    if (source/'saves').is_dir():shutil.copytree(source/'saves',data/'saves')
    env={k:v for k,v in os.environ.items() if not k.startswith('PSX_')}
    env.update(runtime_env)
    env.update(PSX_FRAME_REPORT_MS='5000',PSX_RUNTIME_PERF_DIAG='1',PSX_RUNTIME_PERF_DIAG_MS='5000')
    if args.diagnostics:env.update(PSX_COLLECTION_DIAGNOSTICS='1',PSX_LAUNCHER_BOOT_TIMING='1')
    if args.compiler_off:env['PSX_OVERLAY_AUTOCOMPILE_OFF']='1'
    if args.metrics_off:env['PSX_COLLECTION_METRICS']='0'
    if args.host_profile:env['PSX_HOST_SAMPLER']='1'
    if args.static_audit!='off':
        env.update(PSX_STATIC_AUDIT=args.static_audit,PSX_STATIC_AUDIT_REPORT=str(data/'static-coverage.json'))
    if args.loader_log:env['PSX_STATIC_LOADER_LOG']='1'
    if getattr(args,'framegen_trace',False):env['PSX_FRAME_GEN_TRACE']='1'
    if getattr(args,'force_framegen',False):env['PSX_FRAME_GEN_FORCE']='1'
    # Collapse catalog ../ components before the Windows host checks file paths.
    visible=getattr(args,'visible',False)
    command=[str(executable),'--game',str((root/game['config']).resolve()),'--disc',str((root/game['disc']).resolve()),
        '--bios',str((root/game['bios']).resolve()),'--no-launcher',*([] if visible else ['--hidden-window']),'--collection-mode','--deck-profile',
        '--user-data-dir',str(data),'--debug-port',str(args.port)]
    result=dict(schema=1,game=args.game,command=command,executable_sha256=selected_digest or hashlib.sha256(executable.read_bytes()).hexdigest(),
        compiler_free_static=compiler_free,
        probe_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),runtime_contract=runtime_contract,
        input_route=('fresh native title/map -> Meadow request' if args.game=='robbit' else 'ready-relative menu confirm until guarded gameplay or eight pulses') if args.gameplay_route else 'legacy four pulses' if args.start_pulses else 'none',
        environment={k:v for k,v in env.items() if k.startswith('PSX_')},cache_seed=seed,
        window_visible=visible,
        method=('Visible' if visible else 'Hidden')+' Windows OpenGL discovery; internal swap-call telemetry and process CPU time, not physical FPS or campaign qualification',
        preparation_seconds=time.monotonic()-preparation_start,samples=[],inputs=[],errors=[])
    def save():
        (data/'performance-receipt.json').write_text(json.dumps(result,indent=2)+'\n')
    client=Client(args.port);process=None;start=time.monotonic();sequence=0;pulse=0
    with (data/'performance.log').open('wb') as log:
        process=subprocess.Popen(command,cwd=data,env=env,stdout=log,stderr=subprocess.STDOUT,creationflags=subprocess.CREATE_NO_WINDOW)
        result['pid']=process.pid
        try:
            while True:
                if process.poll() is not None:raise RuntimeError(f'Runtime exited during boot: {process.returncode}')
                try:client.query('frame' if args.legacy_telemetry else 'collection_perf');break
                except OSError:
                    if time.monotonic()-start>args.boot_timeout:raise TimeoutError('Diagnostic server unavailable')
                    time.sleep(.25)
            result['ready_seconds']=time.monotonic()-start
            if args.gameplay_route and args.game=='robbit':prepare_robbit_meadow(client,start,result,data)
            deadline=time.monotonic()+args.seconds
            while time.monotonic()<deadline:
                if process.poll() is not None:raise RuntimeError('Runtime exited during probe')
                t=time.monotonic()
                if args.legacy_telemetry:
                    old=client.query('frame_gen')
                    metrics=dict(swap_calls=old['swaps'],generated_swap_calls=old['generated'],samples=[],sample_drops=0,
                        semantics='Legacy internal swap counter; no swap interval samples')
                else:metrics=client.query('collection_perf',after=sequence)
                sample=dict(seconds=t-start,query_roundtrip_ms=(time.monotonic()-t)*1000,metrics=metrics,
                    frame=client.query('frame')['frame'],audio=client.query('audio_stats'),process_cpu_seconds=process_cpu_seconds(process._handle))
                if args.gameplay_route:sample['input_state']=client.query('collection_input')
                if args.static_audit!='off':sample['static_coverage']=client.query('collection_static')
                if metrics['samples']:sequence=metrics['samples'][-1][0]
                if len(result['samples'])%5==0:
                    sample['compiler']=client.query('autocompile_status')
                    sample['loader']=client.query('overlay_loader_status')
                    if args.static_audit=='observe':sample['capture_flush']=client.query('overlay_capture_dump')
                    print(json.dumps(dict(game=args.game,seconds=round(sample['seconds']),guest_frame=sample['frame'],swaps=metrics['swap_calls'])),flush=True)
                input_time=sample['seconds']-result['ready_seconds'] if args.gameplay_route else sample['seconds']
                needs_confirm=not sample.get('input_state',{}).get('gameplay',False)
                if (args.start_pulses or (args.gameplay_route and args.game!='robbit')) and pulse<(8 if args.gameplay_route else 4) and input_time>=30+15*pulse and (needs_confirm or not args.gameplay_route):
                    buttons=0xfff7 if pulse==0 or args.game=='jf1' else 0xdfff if args.game=='robbit' and args.gameplay_route else 0xbfff
                    client.query('press',buttons=buttons,frames=8)
                    result['inputs'].append(dict(seconds=sample['seconds'],buttons=buttons));pulse+=1
                result['samples'].append(sample);save()
                time.sleep(min(2,max(0,deadline-time.monotonic())))
            # Keep fallback evidence even when an early boot scene has no display.
            if args.static_audit!='off':
                result['static_coverage']=client.query('collection_static')
                result['dirty_coverage']=client.query('dirty_ram_stats')
                if args.static_audit=='observe':
                    busiest=sorted(result['dirty_coverage'].get('per_pc',[]),key=lambda row:row['insns'],reverse=True)[:8]
                    result['fallback_candidates']={row['pc']:{'loaded':client.query('overlay_candidates',pc=f'{int(row["pc"],16)|0x80000000:08x}'),
                        'indexed':client.query('overlay_candidates',pc=f'{int(row["pc"],16)|0x80000000:08x}',lazy=1)} for row in busiest}
                first=result['static_coverage'].get('first_interpreter')
                if first and int(first['pc'],16)<0x10000:
                    address=int(first['pc'],16)&~15
                    result['kernel_snapshot']=dict(address=f'0x{address:08X}',frame=client.query('frame')['frame'],
                        words=client.query('mem_words',addr=f'{address:08x}',count=32)['words'],
                        byte_authority='Runtime observation only; not independently audited BIOS/SDK provenance')
            # Single deliberate GL synchronization after the measurement interval.
            result['final_gpu']=client.query('gpu_state')
            client.query('screenshot_file',path=str(data/'final.png'))
            if args.host_profile:result['host_profile']=client.query('host_profile',frames=1200,top=400)
            if not args.legacy_telemetry:
                result['final_input']=client.query('collection_input')
                result['capture_statistics']={name:client.query(name) for name in ('display_ring_stats','present_image_ring_stats')}
            if args.functional_checks:
                if args.legacy_telemetry:raise ValueError('Functional checks require the new runtime')
                result['disabled_diagnostics']={}
                for endpoint in ('phase_profile','frame_perf','frame_perf_samples','cyc_watch','cyc_watch_dump','dirty_insn_log','dirty_block_log','dirty_flow_log'):
                    try:result['disabled_diagnostics'][endpoint]=client.query(endpoint)
                    except RuntimeError as error:result['disabled_diagnostics'][endpoint]=dict(error=str(error))
                if args.game=='robbit':
                    from strict_input_probe import probe_controls
                    result['virtual_input_observation']=probe_controls(args.port,data/'virtual-input.json')
                else:
                    from input_probe import probe as input_probe
                    input_probe(args.port,VIRTUAL_INPUT_BUTTON_INDEX,data/'virtual-input.json')
                    observed=json.loads((data/'virtual-input.json').read_text())
                    observation=assess_virtual_input(observed)
                    observation.update(
                        physical_controls_qualified=False,
                        limitation='This process-local virtual SDL check does not qualify physical controls or Deck input.')
                    result['virtual_input_observation']=observation
                    require_virtual_input_acceptance(args.game, observation)
                if args.game=='robbit' and result['final_input']['gameplay']:
                    from strict_input_probe import guard_robbit_meadow_profile, sample_robbit_meadow_position
                    before_sample=sample_robbit_meadow_position(client)
                    profile_pin=before_sample['profile_pin']
                    check=dict(method='Native diagnostic pad overrides after timing; exact EVENT/00/M01.PEX Meadow only; not physical/SDL input acceptance',
                        profile_pin={'control_profile':profile_pin[0],'profile_changes':profile_pin[1]},
                        before=before_sample['words'],steps=[])
                    result['native_action_check']=check
                    try:
                        for buttons,frames in ((0xffef,60),(0xbfef,24),(0x7fff,8),(0xffff,60)):
                            guard_robbit_meadow_profile(client,profile_pin)
                            frame=client.query('frame')['frame']
                            client.query('press',buttons=buttons,frames=frames)
                            until=time.monotonic()+10
                            while client.query('frame')['frame']<frame+frames+4:
                                if time.monotonic()>until:raise TimeoutError('Native action check stopped advancing')
                                time.sleep(.05)
                            guard_robbit_meadow_profile(client,profile_pin)
                            check['steps'].append(dict(buttons=buttons,frames=frames))
                    finally:
                        if process.poll() is None:client.query('clear_input')
                    after_sample=sample_robbit_meadow_position(client,profile_pin)
                    check['after']=after_sample['words']
                    check['position_changed']=check['before'][:3]!=check['after'][:3]
                    client.query('screenshot_file',path=str(data/'native-actions.png'))
                    if not check['position_changed']:raise RuntimeError('Native forward/jump actions did not change player position')
        except Exception as error:
            result['errors'].append(repr(error))
            if process.poll() is None:
                try:client.query('screenshot_file',path=str(data/'failure.png'))
                except (OSError,RuntimeError):pass
        finally:
            if process.poll() is None:
                try:client.query('clear_input');client.query('quit')
                except (OSError,RuntimeError):pass
                try:process.wait(timeout=15)
                except subprocess.TimeoutExpired:process.terminate();process.wait(timeout=10)
            result['exit_code']=process.returncode;result['elapsed_seconds']=time.monotonic()-start
            audit=data/'static-coverage.json'
            if audit.exists():result['static_coverage_report']=json.loads(audit.read_text(encoding='utf-8'))
            elif args.static_audit!='off':result['errors'].append('Static-audit report missing')
            result['summary']=summarize(result['samples']);save()
            if args.static_audit!='off':
                from static_gate import assess
                result['static_gate']=assess(result);save()
    print(json.dumps({k:v for k,v in result.items() if k not in ('samples','command','final_gpu')},indent=2))
    return (process.returncode==0 and not result['errors'] and
        (args.static_audit!='strict' or result['static_gate']['native_only_observed'] is True))


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--root',type=Path,required=True)
    parser.add_argument('--game',choices=('jf1','jf2','robbit'),required=True)
    parser.add_argument('--data',type=Path,required=True);parser.add_argument('--port',type=int,default=4472)
    parser.add_argument('--seconds',type=int,default=95);parser.add_argument('--executable',type=Path)
    parser.add_argument('--boot-timeout',type=int,default=180,help='Separate cold startup timeout; startup is excluded from settled-window statistics')
    parser.add_argument('--diagnostics',action='store_true');parser.add_argument('--compiler-off',action='store_true')
    parser.add_argument('--metrics-off',action='store_true',help='Observer control; swap metrics are unavailable, not zero FPS')
    parser.add_argument('--legacy-telemetry',action='store_true',help='Compare an old runtime without collection_perf; no swap interval distribution')
    parser.add_argument('--allow-empty-cache',action='store_true');parser.add_argument('--start-pulses',action='store_true')
    parser.add_argument('--compiler-free-static',action='store_true',help='Verify the static package manifest/runtime and seed no DLLs; requires compiler-off and strict static audit')
    parser.add_argument('--aot-preparation',type=Path,help='Additional independently audited preparation; copied only into the new private probe cache')
    parser.add_argument('--aot-only',action='store_true',help='With --aot-preparation, exclude all older shipped/supplemental cache pairs')
    parser.add_argument('--gameplay-route',action='store_true',help='Confirm original menus until guarded gameplay or eight pulses, relative to readiness; inspect final scene before classifying')
    parser.add_argument('--functional-checks',action='store_true',help='After timing/screenshot, exercise diagnostic errors and a process-local virtual gamepad')
    parser.add_argument('--visible',action='store_true',help='Show the game window for focus-dependent SDL input checks; default hidden')
    parser.add_argument('--runtime-env',action='append',default=[],metavar='PSX_NAME=VALUE',help='Explicit runtime experiment override, recorded in the receipt; enabled dedicated safety/observer flags take precedence')
    parser.add_argument('--host-profile',action='store_true',help='Intrusive emulation-thread IP sampling; use as discovery, not performance acceptance')
    parser.add_argument('--static-audit',choices=('off','observe','strict'),default='off',help='Intrusive whole-process fallback observer; strict exits 86 before interpretation or a compiler request')
    parser.add_argument('--loader-log',action='store_true',help='Intrusive diagnostic: retain native loader admission/rejection messages; default silent')
    parser.add_argument('--framegen-trace',action='store_true',help='Intrusive diagnostic: enable bounded renderer event tracing in compatible experimental hosts; default off')
    parser.add_argument('--force-framegen',action='store_true',help='Diagnostic only: force generation planning to exercise render guards; timings do not qualify ordinary performance')
    raise SystemExit(0 if probe(parser.parse_args()) else 1)
