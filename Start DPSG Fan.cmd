@echo off
rem Starts the DPS G fan tray app without a console window.
rem On first run, creates a .venv next to this file and installs requirements.txt into it.
cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
    echo Creating virtual environment...
    python -m venv .venv || goto :fail
    ".venv\Scripts\python.exe" -m pip install -r requirements.txt || goto :fail
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0dpsg_tray.pyw" %*
exit /b 0

:fail
echo.
echo Setup failed. Is Python 3 installed and on PATH?
pause
exit /b 1
