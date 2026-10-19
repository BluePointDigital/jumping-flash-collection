param([Parameter(Mandatory=$true)][string]$FixtureDirectory)
$ErrorActionPreference = 'Stop'
$fixture = Join-Path $FixtureDirectory ('overlay compiler ' + [Guid]::NewGuid())
$toolchain = Join-Path $fixture 'overlay_toolchain'
New-Item -ItemType Directory -Path $toolchain -Force | Out-Null
$compiler = Join-Path $fixture 'clang.exe'
$custom = Join-Path $fixture 'custom compiler.exe'
$compilerFile = Join-Path $toolchain 'compiler.txt'
[IO.File]::WriteAllText($compiler, 'fixture')
[IO.File]::WriteAllText($custom, 'fixture')
function Configure([string]$path) {
    & (Join-Path $PSScriptRoot 'configure-overlay-compiler.ps1') -BuildDirectory $fixture -CompilerPath $path
}
function Require([bool]$condition, [string]$message) {
    if (-not $condition) { throw $message }
}
Require ((Configure $compiler) -eq $compiler) 'Local compiler was not discovered'
$bytes = [IO.File]::ReadAllBytes($compilerFile)
Require (-not ($bytes.Length -ge 3 -and $bytes[0] -eq 239 -and $bytes[1] -eq 187 -and $bytes[2] -eq 191)) 'Compiler path has a BOM'
[IO.File]::WriteAllText($compilerFile, $custom)
Require ((Configure $compiler) -eq $custom) 'Custom compiler was overwritten'
[IO.File]::WriteAllText($compilerFile, (Join-Path $fixture 'missing.exe'))
Require ((Configure $compiler) -eq $compiler) 'Stale compiler path was not repaired'
[IO.File]::WriteAllText($compilerFile, '')
Require ((Configure $compiler) -eq $compiler) 'Empty compiler file was not repaired'
[IO.File]::WriteAllText($compilerFile, '')
Require ($null -eq (Configure (Join-Path $fixture 'missing.exe'))) 'Missing compiler did not retain fallback behavior'
Write-Output 'Overlay compiler discovery checks passed.'
