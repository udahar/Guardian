@echo off
setlocal
set "REPO_ROOT=C:\Users\Richard\clawd"
set "PYTHON_EXE=C:\Users\Richard\AppData\Local\Python\pythoncore-3.14-64\python.exe"
set "PYTHONPATH=%REPO_ROOT%;%PYTHONPATH%"
cd /d "%REPO_ROOT%"
"%PYTHON_EXE%" -m Guardian.modules.performance.safe_cleanup_pass %*
