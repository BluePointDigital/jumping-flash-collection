"""Observe a native cold/warm boot without injecting input or counting it as gameplay."""
import argparse
import importlib.util
import json
from pathlib import Path
import time

spec = importlib.util.spec_from_file_location("bench", Path(__file__).with_name("performance-bench.py"))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, required=True)
parser.add_argument("--seconds", type=int, default=60)
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if not 1 <= args.seconds <= 600:
    parser.error("seconds must be 1..600")
client = bench.Client(args.port)
client.wait_ready()
start = time.monotonic()
cursor, missing, samples, polls = 0, 0, [], []
recent = client.query("frame_perf_samples", after="0")["samples"]
if recent:
    cursor = recent[-1][0]
while time.monotonic()-start < args.seconds:
    time.sleep(1)
    for row in client.query("frame_perf_samples", after=str(cursor))["samples"]:
        if row[0] > cursor+1:
            missing += row[0]-cursor-1
        cursor = row[0]
        samples.append(row)
    polls.append(dict(seconds=time.monotonic()-start, sequence=cursor,
                      frame=client.query("frame")["frame"],
                      desktop=client.query("jf2_desktop_status")["desktop"],
                      compilation=client.query("autocompile_status"),
                      audio=client.query("audio_stats"),
                      save=client.query("savestate_status")))
    # Avoid rewriting the growing log every frame or second.
    if len(polls) % 10 == 0 or time.monotonic()-start >= args.seconds:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(json.dumps(dict(kind="native-boot-transition",
                                              excluded_from_gameplay_average=True,
                                              completed=time.monotonic()-start >= args.seconds,
                                              seconds=time.monotonic()-start,
                                              missing_samples=missing,
                                              samples=samples, polls=polls), indent=2), encoding="utf-8")
print(json.dumps(dict(seconds=time.monotonic()-start, samples=len(samples),
                      missing_samples=missing,
                      times=bench.summarize([row[2] for row in samples]) if samples else {})), flush=True)
