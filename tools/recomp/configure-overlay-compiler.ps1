param([Parameter(Mandatory=$true)][string]$BuildDirectory,
      [Parameter(Mandatory=$true)][string]$CompilerPath)

$ErrorActionPreference = 'Stop'
$toolchainDirectory = Join-Path $BuildDirectory 'overlay_toolchain'
if (-not (Test-Path -LiteralPath $toolchainDirectory -PathType Container)) { return }
$compilerFile = Join-Path $toolchainDirectory 'compiler.txt'
# Preserve an existing working compiler, including a user's custom toolchain.
if (Test-Path -LiteralPath $compilerFile -PathType Leaf) {
    $configuredCompiler = Get-Content -LiteralPath $compilerFile -TotalCount 1
    if ($configuredCompiler) { $configuredCompiler = $configuredCompiler.Trim() }
    if ($configuredCompiler -and (Test-Path -LiteralPath $configuredCompiler -PathType Leaf)) {
        return $configuredCompiler
    }
}
if (-not (Test-Path -LiteralPath $CompilerPath -PathType Leaf)) { return }
$resolvedCompiler = (Resolve-Path -LiteralPath $CompilerPath).Path
# The runtime reads the first line as a path; a UTF-8 BOM would hide the file.
[System.IO.File]::WriteAllText($compilerFile, $resolvedCompiler + [Environment]::NewLine,
    (New-Object System.Text.UTF8Encoding($false)))
return $resolvedCompiler
