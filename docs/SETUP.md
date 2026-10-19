# Setup: start here

## 1. Check your package

| Package | What it provides |
|---|---|
| GitHub **Source code** ZIP, a clone, or `JumpingFlash-Collection-Source-Preview-20261018.zip` | Integration sources for review/development. **No playable game or collection executable.** See [build status](BUILDING.md). |
| Separately supplied **private playable alpha** | Prepared collection with `JumpingFlashCollection.exe` at its top level. Follow the steps below. |

**There is currently no public playable download.** Adding discs/BIOS to the public source ZIP does not complete its missing game-generation/build pipeline. You do not need to compile anything to run an already prepared private alpha.

## 2. Extract the complete playable package

Extract the ZIP before running it. Keep the complete folder together:

```text
JumpingFlash-Collection/          ← example name; yours may differ
  JumpingFlashCollection.exe     ← run/add this executable
  catalog.toml
  assets/
  data/
  runtime/
  toolchain/
  tools/
  notices/
  ...                           ← keep other supplied files too
```

Choose a writable folder with room for extraction and generated caches. Moving only the EXE leaves its artwork, tools and games behind. The individual game executables are inside `runtime/`; start with the collection EXE above.

## 3. Windows

1. Extract the complete playable ZIP into a writable folder, such as a folder under your user account's `Games` directory.
2. Open that folder and double-click **`JumpingFlashCollection.exe`**.
3. On the illustrated selection screen, select a game, open it, then choose **Play**.
4. Play opens the game's original title screen. Choose its **New Game**, **Continue**, or **Load** option. Runtime states are not automatically restored.
5. Use the selected game's **Game settings** for control style, sensitivity and bindings. **F1** or the top-right **Settings** button opens collection-wide options. Keep experimental widescreen off.
6. Save through the game's normal memory-card menu. To switch games, press **F8**, select **Return to Collection** with Up/Down or W/S, then confirm with Enter.

### If a game asks for files

Open its **Prepare files** page, then choose **Import disc image** and **Import BIOS**. Supply your own [supported game revision and matching BIOS](INPUTS.md). Imports verify identities and copy inputs, preserving originals. **Copy memory card 1/2** optionally copies existing progress; back up your original card first.

**Native build not installed** means the prepared runtime EXE is missing. Disc import cannot replace it. You need the complete prepared playable package; the public source preview does not contain those executables.

Robbit's English translation is by **washingtonxan**. Obtain the patch from the [original translation release](https://romhackplaza.org/translations/robbit-mon-dieu-english-translation-playstation/); it is not bundled in the public repository. See [input details](INPUTS.md).

## 4. Steam Deck

Use the [step-by-step Steam Deck guide](STEAM-DECK.md) for the exact shortcut, paths, compatibility and controller settings.

**Starting configuration: numbered Stable Proton, with `--deck`.** The owner reports slightly better JF2 performance than Experimental and now uses Stable by default. Performance is still imperfect; this is early feedback, not a certification.

## Launcher controls

These bindings apply to collection screens; original game menus can differ.

| Action | Keyboard | Gamepad / Deck |
|---|---|---|
| Select a game | Left/Right or A/D | Left stick/D-pad; LB/RB also switch games |
| Move between rows | Up/Down or W/S | Left stick/D-pad |
| Confirm/open | Enter or Space | A |
| Back | Escape or Backspace | B |
| Collection settings | F1 | Menu/Start |
| Credits | F2 | View/Back |

Back from the collection's home screen exits the launcher. During gameplay, **F8** or **View/Back** opens the collection return menu; Menu/Start also opens it during active gameplay. Select **Return to Collection** with Up/Down or the D-pad, then confirm with Enter/A. At original title screens, Menu/Start retains its original game meaning. Save normally before returning.

## Keep your progress

Per-game data is under `data/games/jf1/`, `data/games/jf2/`, and `data/games/robbit/`. Collection preferences are in `data/collection.toml` after first launch. Close games, then back up the **whole `data/` folder** before updating, moving or changing Proton versions. Preserve existing data before replacing it with anything from a fresh package.

Cloud saves are not provided. Use normal memory-card saves; experimental runtime states are not the migration path.

## Common problems

| Symptom | Check |
|---|---|
| No collection EXE | You probably downloaded the public source preview, which is not playable. |
| Missing catalog, artwork or runtime | Extract the entire ZIP and keep its folder structure. |
| Wrong disc/BIOS identity | Use the exact revision in [INPUTS.md](INPUTS.md); renaming incompatible files does not make them compatible. |
| Deck shortcut closes immediately | Check Target, Start In, Stable Proton and the complete extracted folder; see [Deck troubleshooting](STEAM-DECK.md#troubleshooting). |
| Input seems held or ignored after a transition | Release buttons, triggers and sticks, then press again; fresh input is required. |
| Choppy audio/slowdown | See [Deck observations](STEAM-DECK.md#what-to-expect) and [known issues](KNOWN-ISSUES.md). Setup does not fix all performance issues. |

[Report reproducible issues](https://github.com/BluePointDigital/jumping-flash-collection/issues/new/choose) with build, game/scene, hardware and settings, including exact Proton version. Screenshots are welcome; do not attach discs, BIOS files, memory cards or RAM dumps.
