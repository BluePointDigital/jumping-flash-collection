# Contributing

## Start with a bounded task

1. Read [build status](docs/BUILDING.md), [known issues](docs/KNOWN-ISSUES.md), and the [latest JF2 compatibility update](docs/COMPATIBILITY-ALPHA.md). The public tree is a source preview; supplying discs and BIOS alone does not currently yield the complete playable collection.
2. Open an issue describing the specific gap you want to work on so efforts can be coordinated. If you maintain another port, comparisons of formats, behavior and tooling are welcome too.
3. Fork the repository and work in a branch. Preserve the existing title/revision guards, normal saves, and simulation timing.
4. Submit a pull request describing the problem, the change, prerequisites, and one relevant check with its actual result. Identify checks you could not run. Excluded development inputs mean some tests cannot run from a clean public checkout yet.
5. Include recipes and tooling that operate on the user's local inputs. Keep discs, BIOS, translated/generated game code, game binaries and private data out of commits and attachments. Preserve component notices and translation attribution.

## Highest-priority work

- Replace private replay/generated-source dependencies with generation from verified user-supplied discs and BIOS.
- Make dependency setup, per-game generation, compilation and packaging reproducible without this machine's private workbench.
- Connect the maintained JF2 compatibility main delta and headers to that pipeline against a verified baseline.
- Check resulting packages for normal gameplay/save/return behavior, then broaden graphics, performance and physical Windows/Deck controller testing.

The immediate public-build gap is tracked in [BUILDING.md](docs/BUILDING.md). Watch the repository for updates; there is no public playable download to test yet.

## Reports and validation

Useful reports identify the game, exact revision, scene, reproducible steps, expected/actual behavior and package/source version. Include OS, CPU/GPU/driver, rendering settings and whether the run was cold or warmed. Deck reports should include Proton/SteamOS, device model, power/refresh caps, storage, and controller/Steam Input configuration.

Screenshots and short clips help. Review logs before sharing. Do not attach discs, BIOS files, extracted game data, generated game source/binaries, memory cards, RAM dumps, credentials or personal information.

Keep changes scoped. Explain why a change helps, preserve original simulation timing and per-title guards, and include a relevant short check. Do not infer gameplay correctness from compilation alone or FPS from guest/swap counters. Record failed tests as well as successful ones. Physical hardware and broad campaign results must be labeled with their actual scope.

AI-assisted contributions should be disclosed and reviewed by a person who understands the change. Respect upstream policies when contributing to other projects; our contribution policy does not override theirs.
