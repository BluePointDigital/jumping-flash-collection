# Focused regression checks without rebuilding the game or touching save files.
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$work = Join-Path $root '.workbench'
$framework = Join-Path $work 'psxrecomp'
$tc = Join-Path (Split-Path $root -Parent) '.jf2-workbench/recomp/toolchain/bin'
function Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed (exit $LASTEXITCODE): $Arguments" }
}
& (Join-Path $PSScriptRoot 'build.ps1') -Check
& (Join-Path $PSScriptRoot 'launch.ps1') -Check
Run python @("$PSScriptRoot/test_prepare.py")
Run python @("$PSScriptRoot/test_diagnostics.py")
Run python @("$PSScriptRoot/test_audio_refill.py","$framework/runtime/src/main.cpp","$tc/clang.exe")
Run python @("$PSScriptRoot/test_codegen_syscall.py","$work/build-emitters/psxrecomp-game.exe")
Run "$tc/clang++.exe" @('-std=c++17','-static',"$PSScriptRoot/test_input.cpp",'-o',"$work/test-input.exe")
Run "$work/test-input.exe" @()
Run "$tc/clang.exe" @('-std=c11','-DROBBIT_DESKTOP=1',"$PSScriptRoot/test_frame_pacing.c","-I$framework/runtime/src","-I$framework/runtime/include",'-o',"$work/test-pacing.exe")
Run "$work/test-pacing.exe" @()
Write-Output 'PASS: Robbit launch checks and all focused regressions.'
