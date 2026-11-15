@echo off
rem Starts the Apparatus World Tile GUI, creating the virtual environment on first run.
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
    echo Creating virtual environment...
    py -3 -m venv .venv || python -m venv .venv || goto :error
    ".venv\Scripts\python.exe" -m pip install --upgrade pip || goto :error
    ".venv\Scripts\python.exe" -m pip install -e ".[gui]" || goto :error
)
".venv\Scripts\python.exe" -m awt gui %*
exit /b %errorlevel%

:error
echo Setup failed. Install Python 3.11 or newer and try again.
pause
exit /b 1
