param([switch]$Runtimes)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$repo = Split-Path $root -Parent
$tc = Join-Path $repo '.jf2-workbench/recomp/toolchain'
function Run([string]$Program,[string[]]$Arguments) { & $Program @Arguments; if ($LASTEXITCODE -ne 0) { throw "$Program failed ($LASTEXITCODE)" } }
$previousPath = $env:PATH
try {
    $env:PATH = "$tc/bin;$previousPath"
    Run "$tc/bin/cmake.exe" @('-S',$root,'-B',"$root/.workbench/build",'-G','Ninja','-DCMAKE_BUILD_TYPE=Release',"-DCMAKE_C_COMPILER=$tc/bin/clang.exe","-DCMAKE_CXX_COMPILER=$tc/bin/clang++.exe","-DSDL3_DIR=$tc/deps/lib/cmake/SDL3")
    Run "$tc/bin/cmake.exe" @('--build',"$root/.workbench/build",'-j8')
    Run "$root/.workbench/build/collection-model-test.exe" @("$root/catalog.toml")
    Run "$root/.workbench/build/collection-frame-history-test.exe" @()
    Run "$root/.workbench/build/collection-jf1-controls-test.exe" @()
    Run "$root/.workbench/build/collection-metrics-test.exe" @()
    Run "$root/.workbench/build/collection-metrics-test.exe" @('--disabled')
    Run python @("$root/tools/check_static_audit.py","$root/.workbench/build/collection-static-audit-test.exe")
    if ($Runtimes) { Run python @("$root/tools/prepare_runtimes.py") }
} finally { $env:PATH = $previousPath }
