# Performance evidence

## Windows alpha short samples

Source: the October 18 three-title alpha runtime review. Host: Windows desktop; internal rendering setting 720 lines; 4:3; actual fullscreen output 2880 x 1620. These are approximately 20-second samples from single runs after normal Load/Continue and brief movement. They are not a full benchmark suite. Hardware model, driver version, and physical-display frame capture were not attached to this summarized evidence.

| Title | Guest counter/s | Internal swaps/s | Generated swaps/s | Added audio underrun frames |
|---|---:|---:|---:|---:|
| JF1 | 60.1605 | 60.1605 | 0 | 0 |
| JF2, PAL | 50.0424 | 33.5942 | 0 | 0 |
| Robbit | 60.1672 | 60.1174 | 0 | 0 |

All three routes observed zero process-lifetime interpreter, oracle, and runtime-compiler attempts. No runtime state was restored. These observations cover only the exercised routes. Audio listening was not performed; zero counter increases do not establish audible perfection or resolve other failed runs.

## Reading the counters

- Guest cadence is console timing, not unique world updates or monitor refresh.
- Swap counts are completed internal calls, not verified physical display frames.
- JF2 intentionally skips some unchanged images. Focused intervals observed unchanged-image skips without stale presents, queue stalls, or added underruns. That does not prove smooth interpolation or remove every hitch.
- NTSC and PAL guest timing must remain unchanged when presentation improves.

## Private JF2 optimization experiment

A narrowly scoped cycle-charge fast-prefix change was compared in both parent/candidate run orders in World 1. Mean emulation-thread CPU milliseconds per guest frame were 10.9849 (parent) versus 10.5221 (candidate), about 4.21% lower. Mean process CPU milliseconds per guest frame were 19.7049 versus 18.8641, about 4.27% lower.

The individual observed reductions varied considerably between the two orders. This is descriptive evidence from two short pairs, not an established general speedup. The option remains scoped and disabled by default; it is not a demonstrated Deck improvement or proof that the intermittent audio issue is fixed. The selected alpha does not silently include this private candidate.

## Steam Deck feedback

On an original LCD 64 GB Steam Deck, the owner reports JF2 **feels slightly better with Stable Proton than Experimental**, while still imperfect. Stable is now the owner's default and the [setup guide](STEAM-DECK.md) starting point. The earlier Experimental run had graphical glitches, slowdowns, and very choppy menu voiceover that generally smoothed out during gameplay. The Stable follow-up does not establish that those issues are fixed. Windows feels better overall to the owner. Exact Proton versions and matched scene/settings measurements were not supplied. No measured Deck FPS or percentile frame times are available; do not reuse Windows figures as Deck benchmarks or present the subjective improvement as a measured speedup.

## Next acceptance work

Matched scenes/settings and movement routes; physical frame-time capture; cold versus warmed behavior; audio listening and counters; CPU/memory data; full gameplay families; physical controller/focus/reconnect; and Deck sleep/resume/save/restart. Preserve negative results alongside improvements.
