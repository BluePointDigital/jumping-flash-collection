# Known issues and open qualification

1. JF2 has owner-reported graphical glitches and slowdowns on an LCD 64 GB Steam Deck using Proton Experimental. Menu voiceover is very choppy and generally smooths out after a little gameplay. Windows feels better overall to the owner. A Proton-version cause is unconfirmed; no controlled comparison has been completed.
2. Smooth 60 FPS across all titles is a target, not a release claim. JF2 presentation cadence and interpolation need further work.
3. Intermittent JF2 audio starvation/hitches remain unresolved. A healthy short sample is not proof of a fix.
4. Campaigns/endings and all transition paths have not been qualified. Unvisited paths may expose missing native bindings or incorrect behavior.
5. Save/restart checks cover bounded routes. Robbit's observed School B progress round-trip is not a complete-game persistence guarantee.
6. Physical mouse/twin-stick behavior, controller reconnect, Steam Input trackpad/gyro, and the entire shipped launcher UI matrix need broader testing. Many automated routes used finite guest-pad or virtual-device input.
7. Experimental widescreen is off by default and deferred; it can show missing scenery and other artifacts. It does not block the initial release.
8. Android and native Linux packages are not available. Windows under Proton is the current Deck direction.
9. This source preview is not a complete clean-checkout game build recipe. Private generated-source and source-replay inputs have not all been replaced by user-side regeneration tooling.
