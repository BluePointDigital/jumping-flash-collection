param([switch]$Check, [switch]$NoLauncher)
$ErrorActionPreference = 'Stop'
$work = Join-Path (Split-Path $PSScriptRoot -Parent) '.workbench'
$exe = Join-Path $work 'build/JumpingFlash1_Recompiled.exe'
foreach ($file in @($exe,"$work/game.toml","$work/psxrecomp/bios/SCPH1001.BIN")) {
    if (-not (Test-Path -LiteralPath $file)) { throw "Missing: $file" }
}
if ($Check) { Write-Output 'Jumping Flash! native launch files verified.'; return }
if (Get-Process -Name JumpingFlash1_Recompiled -ErrorAction SilentlyContinue) { return }
New-Item -ItemType Directory -Force -Path "$work/build/logs" | Out-Null
$runtimeArgs = @('--game',('"'+"$work/game.toml"+'"'),'--bios',('"'+"$work/psxrecomp/bios/SCPH1001.BIN"+'"'),'--debug-port','4391')
if ($NoLauncher) { $runtimeArgs += '--no-launcher' }
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss-fff'
$process = Start-Process -FilePath $exe -WorkingDirectory $work -ArgumentList $runtimeArgs -WindowStyle Hidden -PassThru -RedirectStandardOutput "$work/build/logs/$stamp.stdout.log" -RedirectStandardError "$work/build/logs/$stamp.stderr.log"
Write-Output "Jumping Flash! started (PID $($process.Id)); diagnostics: localhost:4391."
