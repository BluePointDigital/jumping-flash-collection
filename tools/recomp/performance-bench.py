"""Live desktop diagnostics. Input recipes are synthetic, not hardware acceptance."""
import argparse
import json
import math
from pathlib import Path
import socket
import struct
import time


class Client:
    def __init__(self, port):
        self.port = port
        self.id = 0

    def query(self, command, **arguments):
        self.id += 1
        # The runtime's TCP protocol accepts one command per connection.
        # Retry only connection establishment: no mutating request has been sent.
        for attempt in range(2):
            try:
                connection = socket.create_connection(("127.0.0.1", self.port), timeout=2)
                break
            except OSError:
                if attempt:
                    raise
                time.sleep(.05)
        with connection:
            connection.settimeout(30)
            connection.sendall((json.dumps(dict(cmd=command, id=self.id, **arguments)) + "\n").encode())
            stream = connection.makefile("rb")
            while True:
                line = stream.readline()
                if not line:
                    raise RuntimeError("debug connection closed")
                reply = json.loads(line)
                if reply.get("id") != self.id:
                    continue
                if not reply.get("ok"):
                    raise RuntimeError(reply)
                return reply

    def wait_ready(self):
        deadline = time.monotonic() + 30
        while True:
            try:
                self.query("frame")
                return
            except OSError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(.2)


def summarize(values):
    ordered = sorted(values)
    if not ordered:
        raise RuntimeError("no frame timing samples")
    return dict(count=len(values), mean_ms=sum(values) / len(values),
                p50_ms=ordered[math.ceil(.50 * len(values)) - 1],
                p95_ms=ordered[math.ceil(.95 * len(values)) - 1],
                p99_ms=ordered[math.ceil(.99 * len(values)) - 1],
                max_ms=ordered[-1], stalls_over_100_ms=sum(v > 100 for v in values))


def player_position(client):
    # Fixed actor identity is signature-guarded by jf2_desktop_status.
    data = client.query("read_ram", addr="80136DEC", len=12)["hex"]
    return list(struct.unpack("<iii", bytes.fromhex(data)))


def load(client, slot):
    start = time.monotonic()
    generation = client.query("savestate_status")["generation"]
    client.query("savestate", op="load", slot=slot)
    deadline = time.monotonic() + 40
    while time.monotonic() < deadline:
        status = client.query("savestate_status")
        if status["generation"] > generation and not status["pending"]:
            if not status["last_ok"]:
                raise RuntimeError(status)
            time.sleep(3)  # Exclude restore, delayed GL-query results and audio refill.
            return dict(slot=slot, seconds_including_settle=time.monotonic()-start,
                        generation=status["generation"])
        time.sleep(.1)
    raise RuntimeError("restore did not complete; close any paused menu")


def route(client, scenario, seconds):
    recipes = {
        "street": [(60, 0xFFEF), (15, 0xFFFF), (60, 0xFFBF), (15, 0xFFFF)],
        "combat": [(35, 0x7BFF), (15, 0xFFFF), (35, 0x77FF), (15, 0xFFFF)],
        "jumps": [(4, 0xBFFF), (15, 0xFFFF), (4, 0xBFFF),
                  (15, 0xFFFF), (4, 0xBFFF), (158, 0xFFFF)],
        "movement": [(15, 0xFFEF), (15, 0xFFFF), (15, 0xFFBF), (15, 0xFFFF)],
        "booster": [(40, 0xFFEF), (15, 0xFFFF), (40, 0xFFBF), (15, 0xFFFF)],
    }
    client.query("input_route_clear")
    if scenario not in recipes:
        return
    recipe = recipes[scenario]
    repeats = math.ceil((seconds + 2) * 50 / sum(step[0] for step in recipe))
    for _ in range(repeats):
        for frames, buttons in recipe:
            client.query("input_route_append", frames=frames, buttons=buttons,
                         boost=int(scenario == "booster" and buttons != 0xFFFF))
    client.query("input_route_start")


def measure(client, scenario, seconds):
    if client.query("jf2_desktop_status")["desktop"]["menu"]:
        raise RuntimeError("menu is open; measurement would count paused time")
    try:
        route(client, scenario, seconds)
        before = dict(audio=client.query("audio_stats"), compilation=client.query("autocompile_status"),
                      desktop=client.query("jf2_desktop_status"), position=player_position(client))
        recent = client.query("frame_perf_samples", after="0")["samples"]
        after = recent[-1][0] if recent else 0
        frame0 = client.query("frame")["frame"]
        start = time.monotonic()
        samples, polls, gaps = [], [], 0
        next_report = start + 20
        while time.monotonic() - start < seconds:
            time.sleep(min(1, max(0, seconds - (time.monotonic() - start))))
            result = client.query("frame_perf_samples", after=str(after))["samples"]
            for seq, frame, milliseconds, *phases in result:
                if seq > after + 1:
                    gaps += seq - after - 1
                after = seq
                if not math.isfinite(milliseconds) or milliseconds <= 0:
                    raise RuntimeError("invalid frame time")
                samples.append([seq, frame, milliseconds, *phases])
            status = client.query("jf2_desktop_status")["desktop"]
            if status["menu"] or not status["supported"]:
                raise RuntimeError("gameplay paused or left the supported overlay")
            now = time.monotonic()
            frame = client.query("frame")["frame"]
            polls.append(dict(seconds=now - start, frame=frame))
            if len(polls) % 5 == 0:
                polls[-1]["compilation"] = client.query("autocompile_status")
                polls[-1]["position"] = player_position(client)
            if now >= next_report:
                print(json.dumps(dict(scenario=scenario, elapsed=round(now-start),
                                      hz=round((frame-frame0)/(now-start), 2))), flush=True)
                next_report += 20
        elapsed = time.monotonic() - start
        if gaps:
            raise RuntimeError(f"lost {gaps} timing samples; repeat this measurement")
        frame1 = client.query("frame")["frame"]
        after_stats = dict(audio=client.query("audio_stats"), compilation=client.query("autocompile_status"),
                           desktop=client.query("jf2_desktop_status"), position=player_position(client))
        return dict(scenario=scenario, seconds=elapsed, guest_hz=(frame1-frame0)/elapsed,
                    frame_times=summarize([row[2] for row in samples]), missing_samples=gaps,
                    audio_underrun_samples=after_stats["audio"]["out"]["underruns"]-before["audio"]["out"]["underruns"],
                    before=before, after=after_stats, samples=samples, polls=polls)
    finally:
        client.query("input_route_clear")
        client.query("clear_input")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--port", type=int, default=4392)
    parser.add_argument("--slot", type=int, required=True)
    parser.add_argument("--scenario", choices=["street", "rooftop", "combat", "jumps", "movement", "booster"], required=True)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if not 0 <= args.slot <= 9 or not 1 <= args.seconds <= 600 or not 1 <= args.repeats <= 10:
        parser.error("slot 0..9, seconds 1..600 and repeats 1..10 required")
    client = Client(args.port)
    client.wait_ready()
    runs = []
    for index in range(args.repeats):
        transition = load(client, args.slot)
        run = measure(client, args.scenario, args.seconds)
        run["restore"] = transition
        runs.append(run)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(runs=runs), indent=2), encoding="utf-8")
        print(json.dumps({k: run[k] for k in ["scenario", "guest_hz", "frame_times", "missing_samples", "audio_underrun_samples"]}), flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
