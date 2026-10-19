# JF2 compatibility update — October 18, 2026

This source preview now includes the maintained changes used by the newer **private compatibility alpha**. No game executable, imported input, generated game source, or private runtime archive is included. The public setup/build pipeline is still incomplete.

## What changed

- JF2 uses its original title/options screen. Its extra startup home, title Mods entry, runtime mod overlay, and plugin activation are disconnected.
- JF2 disables geometry/perspective/PGXP corrections, post-AA, extra supersampling, altered FOV, boost, frame generation, and interpolation. Old saved preferences and matching environment overrides cannot silently turn those effects back on.
- Modern mouse/WASD and controller hooks remain, with shared controls/audio/display preferences. Use the collection's Game settings and Settings screens.
- Developer messages are off during JF2 gameplay. The small shared pause/Return to Collection menu is explicitly visible, including when gameplay messages are disabled.
- The launcher, its artwork, JF1, and Robbit binaries are inherited unchanged from the earlier private alpha.

## Included source changes

- [JF2 main integration delta](../tools/recomp/jf2-compatibility-main.patch)
- [JF2 desktop adapter](../tools/recomp/jf2_desktop.h)
- [Shared pause/return integration](../collection/runtime/collection_runtime.h)

The main delta is against the matching alpha-derived `runtime/src/main.cpp`; it is not a self-contained recipe for patching a fresh upstream checkout. Source preparation must reproduce that baseline before applying it. See [remaining public-build work](BUILDING.md#full-games-remaining-public-build-work).

## Bounded Windows evidence

The private rebuild checked all 1,211 dependencies for the rebuilt main translation unit and preserved the ordered link inputs. A short Windows route deliberately requested the removed effects through both saved preferences and environment overrides; actual renderer getters still reported those effects off, 4:3 and original FOV.

The original five-entry title menu, New Game flow and first stage ran. Process-local SDL virtual input changed right-stick yaw and produced 27 left-stick strafe updates. Pause stopped guest frames, resume advanced them, and native Return to Collection exited zero. Both copied cards stayed unchanged. Normal Load/Save was not repeated in this batch. Physical controller acceptance was not performed.

| Approximately 10-second warmed sample | Result |
|---|---:|
| Guest counter/second, PAL cadence | 50.11 |
| Completed internal swap calls/second | 33.04 |
| Generated swap calls | 0 |
| Added audio underrun frames | 0 |
| Added audio overflow drops | 0 |
| Process-lifetime interpreter/oracle/compiler attempts | 0 |

These internal counters are not physical display FPS, unique moving frames, a measured speedup, or sustained 60 FPS qualification. [Machine-readable evidence summary](benchmarks/jf2-compatibility-20261018.json).

## Still open

Owner-reported see-through/missing building surfaces and moving ground-texture flicker have **not been proven fixed**. Full campaigns, broader graphics, sustained output cadence, physical mouse/controller behavior, and normal save/reload regression work remain open.

The owner's Stable-versus-Experimental Proton observations and the earlier three-game benchmark table refer to the **earlier alpha**. This newer compatibility build has bounded Windows checks only; no new Deck result is claimed. Widescreen remains deferred.
