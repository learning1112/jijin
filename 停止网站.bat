@echo off
setlocal
cd /d "%~dp0"

set "PORT=8000"

echo Stopping fund web server...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_webapp.ps1" %PORT%

echo Done. Press any key to exit.
if /I "%~1"=="--no-pause" goto done
pause >nul
:done
endlocal
