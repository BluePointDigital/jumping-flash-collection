param([switch]$Check)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$work = Join-Path $root '.workbench'
$framework = Join-Path $work 'psxrecomp'
$ui = Join-Path $work 'recomp-ui'
$build = Join-Path $work 'build'
$tc = Join-Path (Split-Path $root -Parent) '.jf2-workbench/recomp/toolchain'
$pins = Get-Content (Join-Path $PSScriptRoot 'pins.json') -Raw | ConvertFrom-Json
function Run([string]$Program, [string[]]$Arguments) {
    & $Program @Arguments
    if ($LASTEXITCODE -ne 0) { throw "$Program failed: $Arguments" }
}
foreach ($pair in @(@($framework,$pins.framework),@($ui,$pins.recomp_ui))) {
    $actual = & git -C $pair[0] rev-parse HEAD
    if ($LASTEXITCODE -ne 0 -or $actual -ne $pair[1]) { throw "Source pin changed: $($pair[0]). No files were reset." }
}
$bios = Join-Path $framework 'bios/SCPH5500.BIN'
if ((Get-FileHash $bios -Algorithm SHA256).Hash.ToLowerInvariant() -ne $pins.bios_sha256) { throw 'Japanese BIOS identity changed.' }
if ($Check) { Write-Output 'Robbit source pins and Japanese BIOS verified.'; return }
$exe = Join-Path $build 'Robbit_Mon_Dieu_Recompiled.exe'
if (Get-Process -Name Robbit_Mon_Dieu_Recompiled -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }) {
    throw 'Close the Robbit game before rebuilding. Jumping Flash 2 can remain open.'
}
foreach ($pair in @(@($framework,'framework.patch'),@($ui,'ui.patch'))) {
    $patch = Join-Path $PSScriptRoot $pair[1]
    & git -C $pair[0] apply --reverse --check $patch 2>$null
    if ($LASTEXITCODE -ne 0) {
        Run git @('-C',$pair[0],'apply','--check',$patch)
        Run git @('-C',$pair[0],'apply',$patch)
    }
}
Copy-Item (Join-Path $PSScriptRoot 'CMakeLists.txt') $work
New-Item -ItemType Directory -Force -Path (Join-Path $work 'desktop') | Out-Null
Copy-Item (Join-Path $PSScriptRoot 'robbit_input.h'),(Join-Path $PSScriptRoot 'robbit_input_core.h'),(Join-Path $PSScriptRoot 'robbit_desktop.h') (Join-Path $work 'desktop')
if (-not (Test-Path (Join-Path $work 'game.toml'))) { Copy-Item (Join-Path $PSScriptRoot 'game.toml') $work }
$oldPath = $env:PATH
$oldToolchain = $env:PSXRECOMP_TOOLCHAIN_DIR
try {
    $env:PATH = "$tc/bin;$oldPath"
    $env:PSXRECOMP_TOOLCHAIN_DIR = $tc
    Run cmake @('-S',"$framework/recompiler",'-B',"$work/build-emitters",'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',"-DCMAKE_C_COMPILER=$tc/bin/clang.exe","-DCMAKE_CXX_COMPILER=$tc/bin/clang++.exe",'-DPSXRECOMP_STATIC_CLI=ON','-DPSXRECOMP_ENABLE_CHD=OFF','-DBUILD_TESTING=OFF')
    Run cmake @('--build',"$work/build-emitters",'--target','psxrecomp-game','psxrecomp-bios','-j8')
    Push-Location $work
    try { Run "$work/build-emitters/psxrecomp-game.exe" @('--config','game.toml') } finally { Pop-Location }
    Push-Location $framework
    try { Run "$work/build-emitters/psxrecomp-bios.exe" @('--config','bios/SCPH5500.toml') } finally { Pop-Location }
    Run cmake @('-S',$work,'-B',$build,'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',"-DCMAKE_C_COMPILER=$tc/bin/clang.exe","-DCMAKE_CXX_COMPILER=$tc/bin/clang++.exe",'-DPSX_DEBUG_TOOLS=ON','-DPSX_ENABLE_VULKAN=OFF','-DPSX_REWIND=OFF','-DPSXRECOMP_REQUIRE_GAME_C=ON','-DPSXRECOMP_BIOS_STEMS=OpenBIOS;SCPH5500','-DPSX_SHELLWIN_INTERP=ON')
    Run cmake @('--build',$build,'--target','psx-runtime','-j8')
    Run python @("$framework/tools/release_stage.py",'stage-toolchain','--stage',$build,'--recomp-dir',"$work/build-emitters",'--recomp-tools',"$framework/tools",'--recomp-include',"$framework/runtime/include",'--dl-cache',"$work/.cache/overlay-toolchain",'--platform','win')
    & (Join-Path $PSScriptRoot 'configure-overlay-compiler.ps1') -BuildDirectory $build -CompilerPath "$tc/bin/clang.exe"
    & (Join-Path $PSScriptRoot 'test.ps1')
} finally {
    $env:PATH = $oldPath
    $env:PSXRECOMP_TOOLCHAIN_DIR = $oldToolchain
}
Write-Output 'Robbit native build and focused checks completed.'
