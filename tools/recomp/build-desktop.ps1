param([switch]$Check, [switch]$NoTests)
$ErrorActionPreference = 'Stop'
$root = Split-Path (Split-Path $PSScriptRoot -Parent) -Parent
$exp = Join-Path $root '.jf2-workbench/recomp/JumpingFlash2Recomp'
$fw = Join-Path $exp 'psxrecomp'
$ui = Join-Path $exp 'recomp-ui'
$tc = Join-Path $root '.jf2-workbench/recomp/toolchain'
$pins = Get-Content (Join-Path $PSScriptRoot 'pins.json') -Raw | ConvertFrom-Json
function Run-Git([string]$repo, [string[]]$arguments) {
    & git -C $repo @arguments
    if ($LASTEXITCODE -ne 0) { throw "Git failed in ${repo}: $arguments" }
}
function Check-Pin([string]$repo, [string]$pin) {
    $actual = & git -C $repo rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $actual -ne $pin) { throw "Expected $repo at $pin; found $actual. No checkout was reset." }
}
function Apply-Support([string]$repo, [string]$name) {
    $patch = Join-Path $PSScriptRoot $name
    $previousPreference = $ErrorActionPreference
    $ErrorActionPreference = 'Continue'
    & git -C $repo apply --reverse --check $patch 2>$null
    $alreadyApplied = $LASTEXITCODE -eq 0
    $ErrorActionPreference = $previousPreference
    if ($alreadyApplied) { return }
    & git -C $repo apply --check $patch
    if ($LASTEXITCODE -ne 0) { throw "Cannot apply $name over existing changes. No files were reset." }
    Run-Git $repo @('apply', $patch)
}
foreach ($required in @('game.toml','generated/SCES_001.11_dispatch.c','build-recompiler/psxrecomp-bios.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path $exp $required))) { throw "Missing $required; first prepare the private experiment using docs/RECOMPILATION-EXPERIMENT.md." }
}
Check-Pin $exp $pins.scaffold
Check-Pin $fw $pins.framework
$bios = Join-Path $fw 'bios/EUR-PSX-SCPH5552.bin'
if ((Get-FileHash -LiteralPath $bios -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pins.bios_sha256) { throw 'Supplied PAL BIOS identity does not match the pinned profile.' }
if ($Check) {
    Check-Pin $ui $pins.recomp_ui
    Write-Output 'Desktop source pins and supplied BIOS identity verified.'
    return
}
$desktopExe = Join-Path $exp 'build-desktop/JumpingFlash2_Recompiled.exe'
$running = Get-Process -Name 'JumpingFlash2_Recompiled' -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $desktopExe }
if ($running) { throw 'Close the desktop game and launcher before rebuilding. The running build was left untouched.' }
if (-not (Test-Path -LiteralPath $ui)) {
    & git clone https://github.com/RetroPortingToolKit/recomp-ui.git $ui
    if ($LASTEXITCODE -ne 0) { throw 'recomp-ui clone failed' }
    Run-Git $ui @('checkout', '--detach', $pins.recomp_ui)
}
Check-Pin $ui $pins.recomp_ui
Apply-Support $fw 'framework-desktop.patch'
Apply-Support $ui 'recomp-ui-desktop.patch'
Apply-Support $exp 'project-desktop.patch'
$support = Join-Path $exp 'desktop'
New-Item -ItemType Directory -Path $support -Force | Out-Null
Copy-Item -LiteralPath (Join-Path $PSScriptRoot 'jf2_desktop.h'), (Join-Path $PSScriptRoot 'jf2_desktop_core.h') -Destination $support
# BIOS C is private. Regenerate it from the patched, identity-checked profile.
$dispatch = Join-Path $fw 'generated/SCPH5552_dispatch.c'
if (-not ((Get-Content -LiteralPath $dispatch -Raw) -match '0x00001C20u,\s*/\* deliver_event_ret')) {
    Push-Location $fw
    try { & (Join-Path $exp 'build-recompiler/psxrecomp-bios.exe') --config bios/SCPH5552.toml
        if ($LASTEXITCODE -ne 0) { throw 'PAL BIOS generation failed' }
    } finally { Pop-Location }
}
$originalPath = $env:PATH
$originalPsxToolchain = $env:PSXRECOMP_TOOLCHAIN_DIR
$originalRetToolchain = $env:RETCOMM_TOOLCHAIN_DIR
try {
    $env:PATH = "$tc/bin;C:/Program Files/Git/bin;$originalPath"
    $env:PSXRECOMP_TOOLCHAIN_DIR = $tc
    $env:RETCOMM_TOOLCHAIN_DIR = $tc
    $build = Join-Path $exp 'build-desktop'
    & cmake -S "$fw/recompiler" -B "$exp/build-recompiler" -G Ninja -DCMAKE_BUILD_TYPE=Release "-DCMAKE_C_COMPILER=$tc/bin/clang.exe" "-DCMAKE_CXX_COMPILER=$tc/bin/clang++.exe" -DPSXRECOMP_STATIC_CLI=ON
    if ($LASTEXITCODE -ne 0) { throw 'Recompiler configure failed' }
    & cmake --build "$exp/build-recompiler" --target psxrecomp-game psxrecomp-bios -j8
    if ($LASTEXITCODE -ne 0) { throw 'Recompiler build failed' }
    Push-Location $exp
    try { & "$exp/build-recompiler/psxrecomp-game.exe" --config game.toml --project-root $exp
        if ($LASTEXITCODE -ne 0) { throw 'Private game source generation failed' }
    } finally { Pop-Location }
    & cmake -S $exp -B $build -G Ninja -DCMAKE_BUILD_TYPE=Release -DCMAKE_C_COMPILER=clang -DCMAKE_CXX_COMPILER=clang++ -DPSX_DEBUG_TOOLS=ON -DPSX_ENABLE_VULKAN=OFF -DPSX_REWIND=OFF -DPSXRECOMP_REQUIRE_GAME_C=ON '-DPSXRECOMP_BIOS_STEMS=OpenBIOS;SCPH5552' -DPSX_SHELLWIN_INTERP=ON
    if ($LASTEXITCODE -ne 0) { throw 'Desktop configure failed' }
    & cmake --build $build --target psx-runtime -j8
    if ($LASTEXITCODE -ne 0) { throw 'Desktop build failed' }
    # Refresh the compiler and hash together so old generated overlays cannot be reused.
    & {
        & python (Join-Path $fw 'tools/release_stage.py') stage-toolchain --stage $build --recomp-dir (Join-Path $exp 'build-recompiler') --recomp-tools (Join-Path $fw 'tools') --recomp-include (Join-Path $fw 'runtime/include') --dl-cache (Join-Path $exp '.cache/overlay-toolchain') --platform win
        if ($LASTEXITCODE -ne 0) { throw 'Overlay toolchain staging failed' }
    }
    & (Join-Path $PSScriptRoot 'configure-overlay-compiler.ps1') `
        -BuildDirectory $build -CompilerPath (Join-Path $tc 'bin/clang.exe') | Out-Null
    if (-not $NoTests) {
        & python (Join-Path $PSScriptRoot 'test_cache_paths.py') "$fw/runtime/src/overlay_loader.c" "$tc/bin/clang.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Cache path regression failed' }
        & python (Join-Path $PSScriptRoot 'test_perf_samples.py') "$fw/runtime/src/gpu_gl_renderer.c" "$tc/bin/clang.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Frame sample regression failed' }
        & python (Join-Path $PSScriptRoot 'test_performance_bench.py')
        if ($LASTEXITCODE -ne 0) { throw 'Performance measurement regression failed' }
        & python (Join-Path $PSScriptRoot 'test_diagnostic_route.py') "$fw/runtime/src/debug_server.c" (Join-Path $PSScriptRoot 'jf2_desktop.h') "$tc/bin/clang++.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Diagnostic route regression failed' }
        & python (Join-Path $PSScriptRoot 'test_audio_refill.py') "$fw/runtime/src/main.cpp" "$tc/bin/clang.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Audio refill regression failed' }
        & python (Join-Path $PSScriptRoot 'test_diagnostic_capture.py') "$fw/runtime/src/debug_server.c" "$tc/bin/clang.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Diagnostic capture defaults test failed' }
        & (Join-Path $PSScriptRoot 'test_overlay_compiler.ps1') -FixtureDirectory (Join-Path $build 'test-fixtures')
        & clang -std=c11 -DJF2_DESKTOP=1 (Join-Path $PSScriptRoot 'test_empty_compilation.c') "$fw/runtime/src/autocompile.c" "-I$fw/runtime/include" -o (Join-Path $build 'test-empty-compilation.exe')
        if ($LASTEXITCODE -ne 0) { throw 'Empty compilation test build failed' }
        & (Join-Path $build 'test-empty-compilation.exe')
        if ($LASTEXITCODE -ne 0) { throw 'Empty compilation tests failed' }
        & (Join-Path $build 'test-empty-compilation.exe') failure
        if ($LASTEXITCODE -ne 0) { throw 'Failed compilation rescan test failed' }
        & python (Join-Path $PSScriptRoot 'test_codegen_syscall.py') "$exp/build-recompiler/psxrecomp-game.exe"
        if ($LASTEXITCODE -ne 0) { throw 'Syscall code-generation regression failed' }
        & clang -std=c11 -DJF2_DESKTOP=1 (Join-Path $PSScriptRoot 'test_frame_pacing.c') "-I$fw/runtime/src" "-I$fw/runtime/include" -o (Join-Path $build 'test-frame-pacing.exe')
        if ($LASTEXITCODE -ne 0) { throw 'Frame pacing test build failed' }
        & (Join-Path $build 'test-frame-pacing.exe')
        if ($LASTEXITCODE -ne 0) { throw 'Frame pacing tests failed' }
        & clang++ -std=c++17 (Join-Path $PSScriptRoot 'test_desktop_core.cpp') -o (Join-Path $build 'test-desktop-core.exe')
        if ($LASTEXITCODE -ne 0) { throw 'Mouse-look test build failed' }
        & (Join-Path $build 'test-desktop-core.exe')
        if ($LASTEXITCODE -ne 0) { throw 'Mouse-look tests failed' }
        & clang -std=c11 -DJF2_DESKTOP=1 (Join-Path $PSScriptRoot 'test_menu.c') "$ui/src/common/recomp_runtime_ui.c" "-I$ui/src" -o (Join-Path $build 'test-menu.exe')
        if ($LASTEXITCODE -ne 0) { throw 'Menu test build failed' }
        & (Join-Path $build 'test-menu.exe')
        if ($LASTEXITCODE -ne 0) { throw 'Menu callback tests failed' }
        & clang++ -std=c++17 -DFMT_HEADER_ONLY (Join-Path $PSScriptRoot 'test_persistence.cpp') "$fw/recompiler/src/config_loader.cpp" "$fw/recompiler/src/ps1_exe_parser.cpp" "-I$fw/recompiler/src" "-I$fw/recompiler/include" "-I$fw/runtime/include" "-I$fw/recompiler/lib/fmt/include" "-I$fw/recompiler/lib/toml11" -o (Join-Path $build 'test-persistence.exe')
        if ($LASTEXITCODE -ne 0) { throw 'Persistence test build failed' }
        & (Join-Path $build 'test-persistence.exe') (Join-Path $build 'test-fixtures')
        if ($LASTEXITCODE -ne 0) { throw 'Persistence tests failed' }
    }
} finally {
    $env:PATH = $originalPath
    $env:PSXRECOMP_TOOLCHAIN_DIR = $originalPsxToolchain
    $env:RETCOMM_TOOLCHAIN_DIR = $originalRetToolchain
}
Write-Output 'Desktop build and requested checks completed. Run launch-recomp.cmd.'
