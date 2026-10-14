@echo off
setlocal
cd /d "%~dp0"
where py >nul 2>nul
if %errorlevel%==0 (
  py -3 scripts\run_local.py
) else (
  python scripts\run_local.py
)
if errorlevel 1 (
  echo Please install Python 3.11 or newer and retry. See LOCAL_START.md.
)
pause
