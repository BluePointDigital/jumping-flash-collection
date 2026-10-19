# Steam Deck: early owner testing

On an original LCD 64 GB Steam Deck using **Proton Experimental**, the owner reports JF2 running and playable, with graphical glitches and slowdowns. Menu voiceover is very choppy, then generally smooths out after a little gameplay. Windows feels better overall in the owner's comparison. These are subjective observations; no matched frame-time measurements or controlled comparison between Proton versions has been completed. Proton version may be a factor, but the cause has not been established.

Other titles, exact Proton Experimental build/settings, measured FPS, gyro, sleep/resume, and full campaigns have not been established by that report.

For an existing private owner-test build, extract the whole portable folder, add JumpingFlashCollection.exe as a non-Steam game, select a suitable Proton version, and use the --deck argument. Keep runtime, assets, toolchain and data together. Retain original 4:3 and disabled experimental widescreen. The Deck profile requests 720-line internal rendering and 1280x800 output; verify actual values on the device rather than treating the profile name as proof.

Those instructions do not turn this public source preview into a playable package. The proprietary inputs and translated runtimes are not included here.

When reporting a Deck issue, include the title/region, exact scene and steps, Proton version, SteamOS version, LCD/OLED model, SSD/microSD, power and refresh/FPS limits, rendering settings and whether the game was cold or warmed. Distinguish slow game speed, uneven camera motion, missing geometry and audio breakup. Screenshots or short clips are welcome; do not attach game/BIOS files, cards or RAM dumps.
