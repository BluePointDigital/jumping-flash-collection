# Steam Deck setup and testing notes

**You need the separately supplied private playable alpha.** The public GitHub source preview has no collection EXE or playable runtimes. See [Setup: check your package](SETUP.md#1-check-your-package) first if unsure.

## Add the collection to Steam

1. Open **Steam > Power > Switch to Desktop** on Deck.
2. Copy and extract the **whole playable package** into a writable folder. For example: `/home/deck/Games/JumpingFlash-Collection/`. Your actual location/name can differ. Do not run inside the ZIP or copy only the EXE; keep `runtime`, `assets`, `toolchain`, `tools`, `data` and the remaining supplied files together.
3. Open Steam in Desktop Mode. Choose **Games > Add a Non-Steam Game to My Library**, then **Browse** to the extracted **`JumpingFlashCollection.exe`** and add it. If the file is hidden by the file-type filter, choose the option that shows all files.
4. Find that shortcut in your Steam Library and open **Properties**. You can rename it **Jumping Flash! Collector's Edition**.
5. Under **Shortcut**, check these fields. Replace the example paths with your actual extracted location; quote paths containing spaces:

   | Field | Example value |
   |---|---|
   | Target | `"/home/deck/Games/JumpingFlash-Collection/JumpingFlashCollection.exe"` |
   | Start In | `"/home/deck/Games/JumpingFlash-Collection"` |
   | Launch Options | `--deck` |

   Target is the **EXE**, Start In is its **containing folder**, and Launch Options contains **only `--deck`** for this starting configuration.

6. Open **Compatibility**, enable **Force the use of a specific Steam Play compatibility tool**, then select the **numbered Stable Proton release**. It usually appears as `Proton` followed by a version number; the entry may not literally say “Proton Stable.” Leave **Proton Experimental** unselected for this starting configuration. Let Steam download the selected tool if needed.
7. Open the shortcut's **Controller Layout** and start with a standard **Gamepad** template. This passes integrated controls through as a controller. A keyboard-only layout may prevent normal gamepad detection. Trackpad/gyro mouse additions can be tried later; they are not fully qualified.
8. Use **Return to Gaming Mode**. Find the shortcut under **Library > Non-Steam**, then press **Play**.

Steam menu paths follow Valve's [Desktop Mode FAQ](https://help.steampowered.com/en/faqs/view/671A-4453-E8D2-323C), [non-Steam shortcut guide](https://help.steampowered.com/en/faqs/view/4B8B-9697-2338-40EC), and [Proton compatibility guide](https://help.steampowered.com/en/faqs/view/7DD4-C618-182E-0E49). Labels may vary with Steam updates.

## First launch

1. The illustrated three-game screen should appear. Move with the D-pad/left stick, press **A** to open a game, then choose **Play**. **B** goes back; **LB/RB** switch games.
2. Choose New Game/Continue/Load in the original game's title menu. Play does not automatically restore a runtime state. If files are requested, see [Prepare files](SETUP.md#if-a-game-asks-for-files).
3. Keep original **4:3** and **experimental widescreen off**. `--deck` selects the Deck profile, requesting 720-line internal rendering and 1280×800 fullscreen output. Those are configuration targets, not measured display qualification. Side bars in 4:3 are expected.
4. Use the selected game's **Game settings** for control style, sensitivity and deadzone. Modern controls are intended to use left-stick movement, right-stick aim, A jump, RT fire and LT secondary; broader physical testing remains open.
5. Release buttons, triggers and sticks after transitions, then press again. Held inputs are deliberately cleared.
6. Save in the original game's memory-card menu. Open the collection return menu with **View/Back** (Deck's left small menu button), or Menu/Start during active gameplay. Select **Return to Collection** with the D-pad and confirm with **A**. B from the launcher's home screen exits the collection.

When moving the folder, update both Target and Start In. Close games and back up the complete `data/` folder before replacing a build or changing Proton versions. Keep your normal saves.

## What to expect

On an **original Steam Deck LCD 64 GB**, the owner reports JF2 running and playable. **Stable Proton feels slightly better than Experimental**, but performance remains imperfect. Stable is now the owner's default and the starting configuration documented here.

The earlier Experimental test had graphical glitches, slowdowns, and very choppy menu voiceover that generally smoothed out after a little gameplay. The Stable follow-up does not establish that those individual issues are fixed. Windows feels better overall to the owner.

These are subjective observations, not a matched benchmark or a Steam Deck Verified rating. Exact Stable/Experimental versions, measured FPS/frame times, SteamOS/settings, storage location, other titles, gyro, sleep/resume and full campaigns remain unreported or unqualified. Do not reuse [Windows benchmark figures](PERFORMANCE.md) as Deck measurements.

## Troubleshooting

| Problem | Check |
|---|---|
| No collection EXE | The public source ZIP is not playable. See [Setup](SETUP.md). |
| Steam immediately returns to Play | Check Target/Start In, the selected Stable Proton tool, and the complete extracted package. |
| Native build not installed | The prepared runtime EXE is missing; importing a disc cannot supply it. |
| Disc/BIOS requested | Use the selected game's Prepare files page and your [supported local inputs](INPUTS.md). |
| Controller missing | Check the Gamepad layout, release all controls, and retry. Compare launcher and in-game behavior separately. |
| Choppy audio or slowdown | Keep 4:3 and Stable as the starting point. Note menu versus gameplay and cold versus warmed behavior. Performance/audio work remains open. |

To compare Proton versions, save normally, close the game/launcher, back up `data/`, change only the compatibility tool and repeat the same scene/settings. Record exact version names. There is no need to switch back to Experimental to follow this guide.

## Reporting issues

Include build, title/region, scene/steps, full Proton dropdown version, SteamOS, LCD/OLED model, SSD/microSD location, power and refresh/FPS limits, rendering settings, controller layout and cold/warmed status. Distinguish slow gameplay, uneven camera motion, missing geometry and audio breakup. Screenshots/clips are welcome; do not attach discs, BIOS files, memory cards or RAM dumps.
