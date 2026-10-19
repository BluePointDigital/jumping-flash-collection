# Alpha 1 — October 18, 2026

**Suggested tag:** `v0.1.0-alpha.1` · **GitHub classification:** pre-release.

This first alpha brings the three Jumping Flash adventures together in one Windows collection. The private playable alpha is undergoing owner testing; **this public release is a source preview, not a ready-to-play binary package**. It contains no discs, BIOS, compiled game runtimes, generated game/BIOS source, memory cards, or translation patch.

## Included in the private alpha

- A unified collection launcher for Jumping Flash!, Jumping Flash! 2, and Robbit Mon Dieu.
- Title-specific illustrated selections and PS1-inspired menus/fonts.
- Modern keyboard/mouse and gamepad control hooks, with configurable input settings.
- Isolated per-game settings and saves, normal game Load/Continue flows, and a native Return to Collection action.
- Robbit's English fan translation by **washingtonxan**, retaining Japanese voices. [Original translation patch and credits](https://romhackplaza.org/translations/robbit-mon-dieu-english-translation-playstation/). The collection does not claim authorship of the translation.
- Original 4:3 defaults; Experimental widescreen remains off and deferred.
- JF2's rendering thread is enabled in its packaged configuration. Frame generation and its separate presentation thread remain disabled.

## Checks completed

All three packaged games completed short Windows Load/gameplay/movement/native-exit routes with zero lifetime interpreter/runtime-compiler attempts and zero added audio underruns during the approximately 20-second samples. Copied normal cards remained unchanged in that batch. JF1/JF2 loaded Data 2 into Stage 1; Robbit loaded a one-request-cleared card into School B.

A subsequent bounded Robbit route cleared all ten School B rings, displayed an Excellent result, saved normally, and restored two cleared requests in a fresh process. This is not whole-campaign acceptance.

JF1 and JF2 completed fresh source rebuilds. Robbit retains its already accepted native controller-fix build; its redundant full clean replay was deferred.

## Steam Deck: first owner report

On an original LCD 64 GB Steam Deck using **Proton Experimental**, the owner reports JF2 running and playable, with graphical glitches and slowdowns. Menu voiceover is very choppy, then generally smooths out after a little gameplay. Windows feels better overall in the owner's comparison. These are subjective observations; no matched frame-time measurements or controlled comparison between Proton versions has been completed. Proton version may be a factor, but the cause has not been established.

This report does not certify all three games. The exact Proton Experimental build, settings, measured FPS, sleep/resume, endings, and broader device coverage remain open.

## Known limitations

- Sustained smooth 60 FPS rendering is not qualified. JF2's short alpha sample recorded about 33.59 internal swaps/second at 50.04 guest counters/second; those are not physical display FPS.
- Graphical glitches, slowdowns, and very choppy menu voiceover have been reported on Deck with Proton Experimental in JF2. Voiceover generally settles after a little gameplay; this is not proof of an audio fix.
- Intermittent JF2 audio starvation/hitches remain unresolved despite healthy short samples.
- Full campaigns, bosses/endings, wider cleared-stage persistence, physical modern controls, and the complete shipped launcher recovery/UI matrix remain open.
- No native Linux or Android release is available.
- Public user-side generation of the complete private alpha is not yet packaged. The development scripts retain private-workbench assumptions; see docs/BUILDING.md.

## Public contents

Integration sources, source-preparation tools, bounded metadata/profiles, tests, documentation, notices, fan menu artwork, and a small set of actual Windows test screenshots. No private runtime ZIP is attached. Please do not upload discs, BIOS files, RAM dumps, generated game sources, memory cards, or private diagnostic captures in issues.

See [performance methodology](docs/PERFORMANCE.md), [known issues](docs/KNOWN-ISSUES.md), and [input revisions](docs/INPUTS.md).
