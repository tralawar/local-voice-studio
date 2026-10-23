@echo off
cd /d "%~dp0"
if exist ".venv\Scripts\python.exe" (
  ".venv\Scripts\python.exe" standalone.py --open
) else (
  python standalone.py --open
)
if errorlevel 1 pause
