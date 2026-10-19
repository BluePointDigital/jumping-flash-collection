@echo off
if not exist "%~dp0dist\JumpingFlashCollection.exe" (
  echo Build and stage the collection first. See README.md.
  pause
  exit /b 1
)
start "" "%~dp0dist\JumpingFlashCollection.exe"
