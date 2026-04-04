@echo off
setlocal
set "REPO_ROOT=C:\Users\Richard\clawd"
set "PYTHON_EXE=C:\Users\Richard\AppData\Local\Python\pythoncore-3.14-64\python.exe"
set "GUARDIAN_API_PORT=4011"
set "PYTHONPATH=%REPO_ROOT%;%PYTHONPATH%"
set "GUARDIAN_SUPERVISOR_STATE_FILE=%REPO_ROOT%\Guardian\logs\supervisor_state.json"
cd /d "%REPO_ROOT%"
"%PYTHON_EXE%" -m Guardian.supervisor %*
