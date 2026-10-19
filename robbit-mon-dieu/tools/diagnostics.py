"""Local Robbit receipts; gameplay input is opt-in and always released."""
import argparse
import json
import math
from pathlib import Path
import socket
import time


class Client:
    def __init__(self, port=4393):
        self.port, self.sequence = port, 0

    def query(self, command, **arguments):
        self.sequence += 1
        with socket.create_connection(('127.0.0.1', self.port), timeout=5) as connection:
            connection.settimeout(30)
            connection.sendall((json.dumps(dict(cmd=command, id=self.sequence, **arguments))+'\n').encode())
            stream = connection.makefile('rb')
            pending = b''
            while True:
                line = stream.readline()
                if not line:
                    raise RuntimeError('Runtime closed the diagnostic connection')
                pending += line
                if len(pending) > 8*1024*1024:
                    raise RuntimeError('Diagnostic response exceeded 8 MiB')
                # Some runtime handlers send one JSON object over several lines.
                try:
                    result = json.loads(pending)
                except json.JSONDecodeError:
                    continue
                pending = b''
                if result.get('id') != self.sequence:
                    continue
                if not result.get('ok'):
                    raise RuntimeError(result)
                return result


GAMEPLAY_ROUTE = [(0xBFFF,8),(0x7FEF,30),(0x7BFF,30),(0xFFDF,15),(0xFFFF,1),(0xFFBF,30)]


def measure(client, seconds, exercise=False):
    recent = client.query('frame_perf_samples', after='0')['samples']
    sequence = recent[-1][0] if recent else 0
    before = dict(frame=client.query('frame'), audio=client.query('audio_stats'),
                  compilation=client.query('autocompile_status'), pad=client.query('pad_status'))
    start, samples, missing, route_index = time.monotonic(), [], 0, 0
    try:
        while time.monotonic()-start < seconds:
            if exercise:
                buttons, frames = GAMEPLAY_ROUTE[route_index % len(GAMEPLAY_ROUTE)]
                client.query('press', buttons=buttons, frames=frames)
                route_index += 1
            time.sleep(min(1, max(0, seconds-(time.monotonic()-start))))
            for row in client.query('frame_perf_samples', after=str(sequence))['samples']:
                missing += max(0, row[0]-sequence-1)
                sequence = row[0]
                if not math.isfinite(row[2]) or row[2] <= 0:
                    raise ValueError('Invalid timing sample')
                samples.append(row)
    finally:
        if exercise:
            client.query('clear_input')
    after = dict(frame=client.query('frame'), audio=client.query('audio_stats'),
                 compilation=client.query('autocompile_status'), pad=client.query('pad_status'))
    elapsed = time.monotonic()-start
    if missing or not samples:
        raise ValueError(f'Incomplete timing collection: {missing} missing, {len(samples)} present')
    ordered = sorted(row[2] for row in samples)
    return dict(seconds=elapsed, guest_hz=(after['frame']['frame']-before['frame']['frame'])/elapsed,
                sample_count=len(samples), missing_samples=missing,
                mean_ms=sum(ordered)/len(ordered), p99_ms=ordered[math.ceil(.99*len(ordered))-1],
                max_ms=ordered[-1], stalls_over_100_ms=sum(value > 100 for value in ordered),
                audio_underrun_samples=after['audio']['out']['underruns']-before['audio']['out']['underruns'],
                audio_overflow_drops=after['audio']['out'].get('overflow_drops',0)-before['audio']['out'].get('overflow_drops',0),
                before=before, after=after, samples=samples,
                route=GAMEPLAY_ROUTE if exercise else [],
                method=('Synthetic finite controller pulses: jump, move/fire, strafe/fire, turn, neutral, back; released in finally'
                        if exercise else 'Passive observation; no synthetic controller inputs during this interval'))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('command', nargs='?', default='status')
    parser.add_argument('--args', default='{}', help='JSON arguments for a diagnostic command')
    parser.add_argument('--seconds', type=int, default=60)
    parser.add_argument('--output', type=Path)
    parser.add_argument('--exercise', action='store_true', help='During measure, apply bounded gameplay pulses; can move or kill the player')
    args = parser.parse_args()
    if not 1 <= args.seconds <= 600:
        parser.error('seconds must be 1..600')
    if args.exercise and args.command != 'measure':
        parser.error('--exercise requires measure')
    client = Client()
    if args.command == 'measure':
        result = measure(client, args.seconds, exercise=args.exercise)
    elif args.command == 'status':
        result = {name:client.query(name) for name in
                  ['frame','pad_status','savestate_status','autocompile_status','audio_stats','display_ring_stats']}
    else:
        result = client.query(args.command, **json.loads(args.args))
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(result, indent=2)+'\n', encoding='utf-8')
    print(json.dumps({k:v for k,v in result.items() if k not in ('before','after','samples')}, indent=2))
