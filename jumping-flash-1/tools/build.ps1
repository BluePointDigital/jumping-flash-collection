param([switch]$Prepare)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$repo = Split-Path $root -Parent
$work = Join-Path $root '.workbench'
$framework = Join-Path $work 'psxrecomp'
$tc = Join-Path $repo '.jf2-workbench/recomp/toolchain'
$emitters = Join-Path $repo 'robbit-mon-dieu/.workbench/build-emitters'
function Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed ($LASTEXITCODE)" }
}
if ($Prepare) { Run python @((Join-Path $PSScriptRoot 'prepare.py')) }
if (Get-Process -Name JumpingFlash1_Recompiled -ErrorAction SilentlyContinue) { throw 'Close Jumping Flash! before rebuilding.' }
Copy-Item (Join-Path $PSScriptRoot 'CMakeLists.txt') $work
$previousPath = $env:PATH
$previousToolchain = $env:PSXRECOMP_TOOLCHAIN_DIR
try {
    $env:PATH = "$tc/bin;$previousPath"
    $env:PSXRECOMP_TOOLCHAIN_DIR = $tc
    Push-Location $work
    try { Run "$emitters/psxrecomp-game.exe" @('--config','game.toml') } finally { Pop-Location }
    Push-Location $framework
    try { Run "$emitters/psxrecomp-bios.exe" @('--config','bios/SCPH1001.toml') } finally { Pop-Location }
    Run cmake @('-S',$work,'-B',"$work/build",'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',"-DCMAKE_C_COMPILER=$tc/bin/clang.exe","-DCMAKE_CXX_COMPILER=$tc/bin/clang++.exe",'-DPSX_DEBUG_TOOLS=ON','-DPSX_ENABLE_VULKAN=OFF','-DPSX_REWIND=OFF','-DPSXRECOMP_REQUIRE_GAME_C=ON','-DPSXRECOMP_BIOS_STEMS=OpenBIOS;SCPH1001','-DPSX_SHELLWIN_INTERP=ON')
    Run cmake @('--build',"$work/build",'--target','psx-runtime','-j8')
    Run python @("$framework/tools/release_stage.py",'stage-toolchain','--stage',"$work/build",'--recomp-dir',$emitters,'--recomp-tools',"$framework/tools",'--recomp-include',"$framework/runtime/include",'--dl-cache',"$work/.cache/overlay-toolchain",'--platform','win')
    & "$repo/robbit-mon-dieu/tools/configure-overlay-compiler.ps1" -BuildDirectory "$work/build" -CompilerPath "$tc/bin/clang.exe"
} finally {
    $env:PATH = $previousPath
    $env:PSXRECOMP_TOOLCHAIN_DIR = $previousToolchain
}
