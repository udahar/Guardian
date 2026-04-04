@echo off
setlocal
set "REPO_ROOT=C:\Users\Richard\clawd"
set "PYTHON_EXE=C:\Users\Richard\AppData\Local\Python\pythoncore-3.14-64\python.exe"
set "PYTHONPATH=%REPO_ROOT%;%PYTHONPATH%"
cd /d "%REPO_ROOT%"
"%PYTHON_EXE%" -c "from Guardian.modules.docker.docker_guardian import DockerGuardian; r = DockerGuardian(cache_prune_threshold_gb=1.0).prune(); print('Freed:', round(r.space_freed_gb,2), 'GB')"
