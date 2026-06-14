@echo off
rem One-click launcher for Windows. Double-click this file, or run:  run.bat [args]
rem First run creates a local virtual environment and installs dependencies.
cd /d "%~dp0"

where python >nul 2>nul || goto :nopython

if not exist ".venv\Scripts\python.exe" call :setup
call ".venv\Scripts\activate.bat"

python main.py %*
echo.
pause
goto :eof

:setup
echo Setting up (first run only)...
python -m venv .venv
call ".venv\Scripts\activate.bat"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
goto :eof

:nopython
echo Python was not found on your PATH.
echo Install Python 3 from https://www.python.org/downloads/ and tick
echo "Add python.exe to PATH" during setup, then run this again.
echo.
pause
goto :eof
