param([string]$Name = 'perf-only-cold')
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$experiment = Join-Path $root '.jf2-workbench/recomp/JumpingFlash2Recomp'
if ($Name -notmatch '^perf-only-[a-z0-9-]+$') { throw 'Use a perf-only- name containing lowercase letters, digits and hyphens.' }
$destination = Join-Path $experiment "evidence/$Name"
if ((Test-Path -LiteralPath $destination) -and (Get-ChildItem -LiteralPath $destination -Force | Select-Object -First 1)) {
    throw "Use a new empty directory. Existing evidence was preserved: $destination"
}
$build = Join-Path $experiment 'build-desktop'
New-Item -ItemType Directory -Path $destination, "$destination/build", "$destination/disc", "$destination/seeds" -Force | Out-Null
Copy-Item -LiteralPath "$experiment/game.toml" -Destination $destination
Copy-Item -LiteralPath "$experiment/disc/SCES_001.11" -Destination "$destination/disc"
Copy-Item -LiteralPath "$experiment/seeds/ghidra_funcs.txt" -Destination "$destination/seeds"
Copy-Item -LiteralPath "$experiment/saves" -Destination "$destination/saves" -Recurse
Copy-Item -LiteralPath "$build/JumpingFlash2_Recompiled.exe" -Destination "$destination/build"
Copy-Item -LiteralPath "$build/overlay_toolchain" -Destination "$destination/build/overlay_toolchain" -Recurse
foreach ($name in @('settings.toml', 'keybinds.ini', 'keybinds-classic.ini', 'keybinds-modern.ini')) {
    Copy-Item -LiteralPath (Join-Path $build $name) -Destination "$destination/build"
}
# Only relocate writable storage. Disc and supplied BIOS remain read-only sources.
$settingsPath = "$destination/build/settings.toml"
$settings = Get-Content -LiteralPath $settingsPath -Raw
$savePath = "$destination/saves".Replace('\', '/')
$settings = [regex]::Replace($settings, '(?m)^dir\s*=.*$', "dir = `"$savePath`"")
$settings = [regex]::Replace($settings, '(?m)^card1\s*=.*$', "card1 = `"$savePath/card1.mcd`"")
$settings = [regex]::Replace($settings, '(?m)^card2\s*=.*$', "card2 = `"$savePath/card2.mcd`"")
[IO.File]::WriteAllText($settingsPath, $settings, [Text.UTF8Encoding]::new($false))
Write-Output "Isolated project: $destination"
Write-Output 'Its executable directory has no overlay cache. Original saves and settings are unchanged.'
