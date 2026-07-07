@echo off
setlocal
cd /d "%~dp0"

set "PORT=8000"
set "PYTHON_EXE=E:\anaconda\envs\jijin-backtest\python.exe"
if not exist "%PYTHON_EXE%" set "PYTHON_EXE=python"

echo Stopping old fund web server...
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0scripts\stop_webapp.ps1" %PORT% >nul 2>nul

echo Starting fund web server at http://127.0.0.1:%PORT%/
"%PYTHON_EXE%" -m fund_backtest.webapp --port %PORT% --open

echo.
echo Fund web server stopped. Press any key to close this window.
pause >nul
endlocal
