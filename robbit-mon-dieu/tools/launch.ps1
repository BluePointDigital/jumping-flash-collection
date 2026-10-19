param([switch]$Check, [switch]$Hidden, [switch]$NoLauncher, [switch]$SoftwareRecovery)
$ErrorActionPreference = 'Stop'
$root = Split-Path $PSScriptRoot -Parent
$work = Join-Path $root '.workbench'
$build = Join-Path $work 'build'
$exe = Join-Path $build 'Robbit_Mon_Dieu_Recompiled.exe'
$bios = Join-Path $work 'psxrecomp/bios/SCPH5500.BIN'
$config = Join-Path $work 'game.toml'
foreach ($path in @($exe,$bios,$config,(Join-Path $build 'overlay_toolchain/python/python.exe'),(Join-Path $work 'disc/english/Robbit mon Dieu (English).bin'))) {
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { throw "Missing Robbit file: $path" }
}
if ((Get-FileHash $bios -Algorithm SHA256).Hash -ne '9C0421858E217805F4ABE18698AFEA8D5AA36FF0727EB8484944E00EB5E7EADB') { throw 'Japanese BIOS identity changed.' }
if ($Check) { Write-Output 'Robbit native launch files and Japanese BIOS verified.'; return }
$running = Get-Process -Name Robbit_Mon_Dieu_Recompiled -ErrorAction SilentlyContinue | Where-Object { $_.Path -eq $exe }
if ($running) { Write-Output "Already running (PID $($running[0].Id))."; return }
& (Join-Path $PSScriptRoot 'configure-overlay-compiler.ps1') -BuildDirectory $build -CompilerPath (Join-Path (Split-Path $root -Parent) '.jf2-workbench/recomp/toolchain/bin/clang.exe') | Out-Null
$runtimeArgs = @('--game',('"'+$config+'"'),'--bios',('"'+$bios+'"'),'--debug-port','4393')
if ($NoLauncher -or $SoftwareRecovery) { $runtimeArgs += '--no-launcher' }
if ($SoftwareRecovery) { $runtimeArgs += @('--renderer','software') }
if ($Hidden) { $runtimeArgs += '--hidden-window' }
$logs = Join-Path $build 'logs'
New-Item -ItemType Directory -Force -Path $logs | Out-Null
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$process = Start-Process -FilePath $exe -ArgumentList $runtimeArgs -WorkingDirectory $work -WindowStyle Hidden -PassThru -RedirectStandardOutput (Join-Path $logs "$stamp.stdout.log") -RedirectStandardError (Join-Path $logs "$stamp.stderr.log")
Write-Output "Robbit Mon Dieu started (PID $($process.Id)); diagnostics: localhost:4393."
