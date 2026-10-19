# Build status: source preview

**Looking for player instructions?** See [Setup](SETUP.md) for Windows and the private alpha, or [Steam Deck setup](STEAM-DECK.md). This page is for developers; compiling the front end alone does not provide the games.

This snapshot preserves collection integration sources, adapters, metadata and development tools. It does not yet reproduce the full private October 18 alpha from a clean checkout. Do not treat the private source-replay builds as proof of a public, self-contained configure/generate/build workflow.

## Collection front end

The SDL3/OpenGL/Dear ImGui front end is described by collection/CMakeLists.txt. It requires Windows, a C++17 compiler, CMake 3.24+, an SDL3 package exposing SDL3::SDL3-static, recomp-ui for Dear ImGui and stb_image, and PSXRecomp for toml11. Supply COLLECTION_UI_ROOT, COLLECTION_FRAMEWORK_ROOT and SDL3_DIR explicitly when configuring. The defaults point at the historical local development layout.

Historical upstream pins are recorded in tools/recomp/pins.json; see UPSTREAM.json for URLs. They identify a framework baseline, not every later patched source in a native alpha executable. Source preparation applies additional integration transforms.

The front end alone does not contain gameplay. Missing runtime executables are reported as not installed. Place a runtime catalog beside the executable or pass --root to a prepared collection directory. Optional art paths resolve relative to that root.

## Full games: remaining public-build work

- Obtain supported discs and matching BIOS files privately; validate identities against the catalog.
- Acquire the pinned framework/UI/toolchain and apply reviewed integration changes.
- Replace private-workbench references and captured/replay-only inputs with generation from the user's original files.
- Generate boot, BIOS and verified overlay C locally; do not commit or publish those generated payloads.
- Connect the latest static coverage, controller and diagnostic changes to a clean build pipeline.
- Build and package all three runtimes, then verify ordinary gameplay, saves and returns on the resulting package.

Several included scripts expect references/, .workbench/, .jf2-workbench/, a previously prepared package, or generated files. The source-only publication deliberately excludes those inputs. The palette instruction-word catalog and translated JF1 family source payloads are also excluded pending conversion into original-input regeneration recipes. Tests for excluded developer inputs may require those inputs and are not advertised as passing in this public snapshot.

No dependency downloads, native game compilation, or public clean-checkout gameplay test were performed as part of publication staging. The Windows alpha test notes describe the separate private build.

## Local syntax and package check

Run python tools/verify_public_snapshot.py from this repository. It checks the source-publication boundary, links, text formats and manifest hashes; it does not certify licensing or game compatibility. Python 3.11+ is required for the TOML checks.
