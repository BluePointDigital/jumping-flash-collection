"""Portable native boot/overlay smoke check. Not graphical or campaign acceptance."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import time
import tomllib
from diagnostics import Client


def snapshot(client):
    gpu = client.query('gpu_state')
    return dict(frame=client.query('frame')['frame'], display_disabled=gpu['disabled'],
                last_3d_frame=gpu['ws']['last_3d_frame'],
                compilation=client.query('autocompile_status'))


def smoke(root, identity, data, port, seconds, isolated_tools=False, deck_profile=False):
    catalog = tomllib.loads((root/'catalog.toml').read_text(encoding='utf-8'))
    game = next(g for g in catalog['games'] if g['id'] == identity)
    data.mkdir(parents=True, exist_ok=True)
    environment = os.environ.copy()
    environment.pop('PSX_OVERLAY_UNIT_DEFER', None)
    environment.pop('PSX_LOAD_SLOT', None)
    if isolated_tools:
        system_root = next(value for key, value in environment.items() if key.lower() == 'systemroot')
        for key in list(environment):
            if key.lower() in ('path', 'pythonpath', 'pythonhome', 'psxrecomp_toolchain_dir', 'psx_overlay_compiler'):
                environment.pop(key)
        environment['PATH'] = str(Path(system_root)/'System32')
    command = [str(root/game['executable']), '--game', str(root/game['config']),
               '--bios', str(root/game['bios']), '--disc', str(root/game['disc']),
               '--no-launcher', '--headless', '--collection-mode',
               '--user-data-dir', str(data), '--debug-port', str(port)]
    if deck_profile:
        command.append('--deck-profile')
    report = dict(schema=1, game=identity, package=str(root),
                  method='Headless software-renderer smoke; no frame, audio, controller or campaign qualification.',
                  overlay_unit_defer_environment_override=False, samples=[])
    report['developer_tools_removed_from_path'] = isolated_tools
    report['deck_profile_requested'] = deck_profile
    client = Client(port)
    started = time.monotonic()
    with (data/'smoke.log').open('wb') as log:
        process = subprocess.Popen(command, cwd=data, env=environment, stdout=log,
                                   stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
        try:
            deadline = started + 60
            while True:
                if process.poll() is not None:
                    raise RuntimeError(f'Native runtime exited during boot: {process.returncode}')
                try:
                    report['boot'] = snapshot(client)
                    break
                except (OSError, TimeoutError):
                    if time.monotonic() >= deadline:
                        raise RuntimeError('Native diagnostic server did not become ready')
                    time.sleep(.25)
            report['server_ready_seconds'] = time.monotonic() - started
            deadline = time.monotonic() + seconds
            pulse = 0
            last_pulse_frame = -1000
            while time.monotonic() < deadline:
                # Original Start/confirm, released between guest-frame pulses.
                # This only exercises boot/menu/load handling; it cannot complete a campaign.
                current_frame = client.query('frame')['frame']
                if pulse < 4 and current_frame >= 1800 and current_frame-last_pulse_frame >= 600:
                    client.query('press', buttons=0xFFF7 if pulse == 0 else 0xBFFF, frames=8)
                    pulse += 1
                    last_pulse_frame = current_frame
                time.sleep(2)
                report['samples'].append(snapshot(client))
            report['alive'] = process.poll() is None
            report['guest_frames_advanced'] = report['samples'][-1]['frame'] - report['boot']['frame']
            report['result'] = 'boot-smoke-passed' if report['alive'] and report['guest_frames_advanced'] > 100 else 'failed'
            client.query('screenshot_file', path=str(data/'smoke.png'))
        finally:
            if process.poll() is None:
                try:
                    client.query('clear_input')
                    client.query('quit')
                except (OSError, RuntimeError):
                    pass  # Quit closes this socket before acknowledging.
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.terminate()
                    process.wait(timeout=10)
            report['exit_code'] = process.returncode
            report['elapsed_seconds'] = time.monotonic() - started
            (data/'smoke-receipt.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    return report


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--game', choices=['jf1', 'jf2', 'robbit'], required=True)
    parser.add_argument('--data', type=Path, required=True)
    parser.add_argument('--port', type=int, default=4394)
    parser.add_argument('--seconds', type=float, default=30)
    parser.add_argument('--isolated-tools', action='store_true')
    parser.add_argument('--deck-profile', action='store_true')
    args = parser.parse_args()
    result = smoke(args.root.resolve(), args.game, args.data.resolve(), args.port, args.seconds, args.isolated_tools, args.deck_profile)
    print(json.dumps({key: value for key, value in result.items() if key not in ('boot', 'samples')}, indent=2))
    raise SystemExit(0 if result['result'] == 'boot-smoke-passed' else 1)
