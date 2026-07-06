@echo off
cd /d "%~dp0"

where conda >nul 2>nul
if %errorlevel%==0 (
  conda run -n jijin-backtest python -m fund_backtest.webapp --open
) else (
  python -m fund_backtest.webapp --open
)

pause
