"""Five repeated World 1 scenarios, or ten minutes of mixed scripted gameplay."""
import argparse
import importlib.util
import json
from pathlib import Path

spec = importlib.util.spec_from_file_location("bench", Path(__file__).with_name("performance-bench.py"))
bench = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bench)
parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument("--port", type=int, default=4392)
parser.add_argument("--street-slot", type=int, default=7)
parser.add_argument("--roof-slot", type=int, default=9)
parser.add_argument("--mixed", action="store_true")
parser.add_argument("--output", type=Path, required=True)
args = parser.parse_args()
if not all(0 <= slot <= 9 for slot in (args.street_slot, args.roof_slot)):
    parser.error("slots must be 0..9; use copied saves")
client = bench.Client(args.port)
client.wait_ready()
scenarios = ["street", "rooftop", "combat", "jumps", "booster"]
sequence = scenarios * 2 if args.mixed else [s for s in scenarios for _ in range(3)]
runs = []
for scenario in sequence:
    transition = bench.load(client, args.roof_slot if scenario == "rooftop" else args.street_slot)
    run = bench.measure(client, scenario, 60)
    run["restore"] = transition
    runs.append(run)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(dict(synthetic_inputs=True, runs=runs), indent=2), encoding="utf-8")
    print(json.dumps({k: run[k] for k in ("scenario", "guest_hz", "frame_times",
                                         "audio_underrun_samples", "missing_samples")}), flush=True)
