@echo off
REM Guardian Launcher - Windows Batch Script
REM Automated system health monitoring and maintenance

setlocal enabledelayedexpansion

set "SCRIPT_DIR=%~dp0"
set "PYTHON=python"
set "MODE=%1"

REM Check if Python is available
where python >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found in PATH
    echo Please install Python and add to PATH
    pause
    exit /b 1
)

REM Change to script directory
cd /d "%SCRIPT_DIR%"

REM Check for virtual environment
if exist "venv\Scripts\activate.bat" (
    call venv\Scripts\activate.bat
)

REM Parse arguments
if "%MODE%"=="" goto :menu
if "%MODE%"=="help" goto :help
if "%MODE%"=="monitor" goto :monitor
if "%MODE%"=="ai" goto :ai
if "%MODE%"=="diagnose" goto :diagnose
if "%MODE%"=="cleanup" goto :cleanup
if "%MODE%"=="shrink" goto :shrink
if "%MODE%"=="optimize" goto :optimize
if "%MODE%"=="daemon" goto :daemon

:menu
echo ========================================
echo        Guardian System Health
echo ========================================
echo.
echo  [1] Start AI Guardian (Recommended)
echo  [2] Continuous Monitor
echo  [3] Run Diagnostics
echo  [4] Quick Cleanup
echo  [5] WSL Optimize
echo  [6] WSL Shrink Disk
echo  [7] Decision History
echo  [8] Show Trends
echo  [Q] Quit
echo.
set /p choice="Select option: "

if "%choice%"=="1" goto :ai
if "%choice%"=="2" goto :monitor
if "%choice%"=="3" goto :diagnose
if "%choice%"=="4" goto :cleanup
if "%choice%"=="5" goto :optimize
if "%choice%"=="6" goto :shrink
if "%choice%"=="7" goto :history
if "%choice%"=="8" goto :trends
goto :menu

:ai
echo.
echo Starting AI Guardian...
echo.
python -m Guardian.ai_guardian --decision
echo.
pause
goto :menu

:monitor
echo.
echo Starting Guardian Monitor...
echo Press Ctrl+C to stop
echo.
python -m Guardian.windows_guardian
goto :end

:diagnose
echo.
echo Running System Diagnostics...
echo.
python -m Guardian.diagnostics --print
echo.
pause
goto :menu

:cleanup
echo.
echo Running Cleanup...
echo.
python -c "from Guardian import cleanup_all; import json; print(json.dumps(cleanup_all(), indent=2))"
echo.
pause
goto :menu

:optimize
echo.
echo Optimizing WSL...
echo.
python -c "from Guardian import optimize_wsl; import json; print(json.dumps(optimize_wsl(), indent=2))"
echo.
pause
goto :menu

:shrink
echo.
echo Shrinking WSL Disk...
echo This will temporarily stop WSL...
echo.
python -c "from Guardian import shrink_wsl_disk; import json; print(json.dumps(shrink_wsl_disk(), indent=2))"
echo.
pause
goto :menu

:history
echo.
python -c "from Guardian.db_manager import create_db; db = create_db(); hist = db.get_decision_history(7); [print(f\"{h.get('timestamp','')[:19]} - {h.get('decision')} ({h.get('confidence')})\") for h in hist[:15]]"
echo.
pause
goto :menu

:trends
echo.
python -c "from Guardian.db_manager import create_db; db = create_db(); trends = db.get_trends(30); import json; print(json.dumps(trends, indent=2))"
echo.
pause
goto :menu

:daemon
echo.
echo Starting Guardian as background service...
echo.
start /b python -m Guardian.windows_guardian
echo Guardian started in background
timeout /t 2 /nobreak >nul
goto :menu

:help
echo.
echo Guardian Command Line Usage:
echo.
echo   guardian.bat ai          - Make AI decision
echo   guardian.bat monitor     - Continuous monitoring
echo   guardian.bat diagnose   - Run diagnostics
echo   guardian.bat cleanup    - Quick cleanup
echo   guardian.bat optimize   - Optimize WSL
echo   guardian.bat shrink     - Shrink WSL disk
echo   guardian.bat history    - Show decision history
echo   guardian.bat trends     - Show trends
echo.
pause

:end
