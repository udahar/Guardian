# Guardian Launcher - PowerShell Script
# Automated system health monitoring and maintenance

param(
    [Parameter(Position=0)]
    [ValidateSet("ai", "monitor", "diagnose", "cleanup", "optimize", "shrink", "docker", "docker-prune", "services", "ollama", "diskreport", "caches", "logs", "history", "trends", "patterns", "memory", "daemon", "help")]
    [string]$Mode = "menu",
    
    [Parameter(Position=1)]
    [string]$Distro = "Ubuntu",
    
    [switch]$Background
)

$ErrorActionPreference = "Continue"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$RepoRoot = Split-Path -Parent $ScriptDir
Set-Location $ScriptDir

if ([string]::IsNullOrWhiteSpace($env:PYTHONPATH)) {
    $env:PYTHONPATH = $RepoRoot
} elseif (-not ($env:PYTHONPATH -split ';' | Where-Object { $_ -eq $RepoRoot })) {
    $env:PYTHONPATH = "$RepoRoot;$env:PYTHONPATH"
}

function Write-Banner {
    Write-Host ""
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host "       Guardian System Health          " -ForegroundColor Cyan
    Write-Host "========================================" -ForegroundColor Cyan
    Write-Host ""
}

function Show-Menu {
    Write-Banner
    Write-Host "  [1] Start AI Guardian (Recommended)" -ForegroundColor Green
    Write-Host "  [2] Continuous Monitor" -ForegroundColor Yellow
    Write-Host "  [3] Run Diagnostics" -ForegroundColor Yellow
    Write-Host "  [4] Quick Cleanup" -ForegroundColor Yellow
    Write-Host "  [5] WSL Optimize" -ForegroundColor Yellow
    Write-Host "  [6] WSL Shrink Disk" -ForegroundColor Red
    Write-Host "  [7] Docker Disk Status" -ForegroundColor Yellow
    Write-Host "  [8] Docker Prune (free cache)" -ForegroundColor Yellow
    Write-Host "  [A] Service Health Check" -ForegroundColor Cyan
    Write-Host "  [B] Ollama Status" -ForegroundColor Cyan
    Write-Host "  [C] Disk Report" -ForegroundColor Cyan
    Write-Host "  [E] Stale Cache Scan" -ForegroundColor Cyan
    Write-Host "  [F] Log Watch (last 24h)" -ForegroundColor Cyan
    Write-Host "  [G] Decision History" -ForegroundColor White
    Write-Host "  [H] Show Trends" -ForegroundColor White
    Write-Host "  [I] Pattern Analysis" -ForegroundColor White
    Write-Host "  [J] Memory Pressure Report" -ForegroundColor White
    Write-Host "  [D] Run as Daemon (Background)" -ForegroundColor Gray
    Write-Host "  [Q] Quit" -ForegroundColor Red
    Write-Host ""
    
    $choice = Read-Host "Select option"
    return $choice
}

switch ($Mode) {
    "help" {
        Write-Banner
        Write-Host "Guardian Command Line Usage:" -ForegroundColor Cyan
        Write-Host ""
        Write-Host "  .\guardian.ps1 ai           - Make AI decision" -ForegroundColor White
        Write-Host "  .\guardian.ps1 monitor      - Continuous monitoring" -ForegroundColor White
        Write-Host "  .\guardian.ps1 diagnose    - Run diagnostics" -ForegroundColor White
        Write-Host "  .\guardian.ps1 cleanup      - Quick cleanup" -ForegroundColor White
        Write-Host "  .\guardian.ps1 optimize    - Optimize WSL" -ForegroundColor White
        Write-Host "  .\guardian.ps1 shrink       - Shrink WSL disk" -ForegroundColor White
        Write-Host "  .\guardian.ps1 docker       - Docker disk status" -ForegroundColor White
        Write-Host "  .\guardian.ps1 docker-prune - Prune Docker cache" -ForegroundColor White
        Write-Host "  .\guardian.ps1 memory      - Analyze RAM, commit, and paging pressure" -ForegroundColor White
        Write-Host "  .\guardian.ps1 history      - Show decision history" -ForegroundColor White
        Write-Host "  .\guardian.ps1 trends      - Show trends" -ForegroundColor White
        Write-Host "  .\guardian.ps1 patterns    - Pattern analysis" -ForegroundColor White
        Write-Host "  .\guardian.ps1 daemon      - Run in background" -ForegroundColor White
        Write-Host ""
    }
    
    "ai" {
        Write-Host "Starting AI Guardian..." -ForegroundColor Cyan
        python -m Guardian.modules.services.ai_guardian --decision
    }
    
    "monitor" {
        Write-Host "Starting Guardian Monitor..." -ForegroundColor Cyan
        Write-Host "Press Ctrl+C to stop" -ForegroundColor Gray
        python -m Guardian.modules.windows.windows_guardian
    }
    
    "diagnose" {
        Write-Host "Running System Diagnostics..." -ForegroundColor Cyan
        python -m Guardian.modules.diagnostics.diagnostics
    }
    
    "cleanup" {
        Write-Host "Running Cleanup..." -ForegroundColor Cyan
        python -c "from Guardian import cleanup_all; import json; print(json.dumps(cleanup_all(), indent=2))"
    }
    
    "optimize" {
        Write-Host "Optimizing WSL ($Distro)..." -ForegroundColor Cyan
        python -c "from Guardian import optimize_wsl; import json; print(json.dumps(optimize_wsl('$Distro'), indent=2))"
    }
    
    "shrink" {
        Write-Host "Shrinking WSL Disk ($Distro)..." -ForegroundColor Yellow
        Write-Host "This will temporarily stop WSL..." -ForegroundColor Red
        python -c "from Guardian import shrink_wsl_disk; import json; print(json.dumps(shrink_wsl_disk('$Distro'), indent=2))"
    }

    "docker" {
        Write-Host "Docker Disk Status..." -ForegroundColor Cyan
        python -c "from Guardian.modules.docker.docker_guardian import DockerGuardian; import json; print(json.dumps(DockerGuardian().get_disk_state().__dict__, indent=2, default=str))"
    }

    "docker-prune" {
        Write-Host "Pruning Docker disk (build cache + dangling images + stopped containers)..." -ForegroundColor Yellow
        python -c "from Guardian.modules.docker.docker_guardian import DockerGuardian; import json; r = DockerGuardian().prune(aggressive=False); print(json.dumps({'success': r.success, 'actions': r.actions, 'freed_gb': round(r.space_freed_gb,2), 'errors': r.errors}, indent=2))"
    }

    "services" {
        Write-Host "Service Health Check..." -ForegroundColor Cyan
        python -m Guardian.modules.services.service_health
    }

    "ollama" {
        Write-Host "Ollama Status..." -ForegroundColor Cyan
        python -m Guardian.modules.services.ollama_monitor
    }

    "diskreport" {
        Write-Host "Running disk report (may take ~30s)..." -ForegroundColor Cyan
        python -m Guardian.modules.disk.disk_report
    }

    "caches" {
        Write-Host "Scanning stale caches..." -ForegroundColor Cyan
        python -m Guardian.modules.performance.stale_cache_cleaner
    }

    "logs" {
        Write-Host "Reading logs (last 24h)..." -ForegroundColor Cyan
        python -m Guardian.modules.monitor.log_watcher 24
    }

    "memory" {
        Write-Host "Analyzing memory pressure..." -ForegroundColor Cyan
        python -m Guardian.modules.memory.memory_pressure
    }

    "history" {
        Write-Host "Decision History:" -ForegroundColor Cyan
        python -m Guardian.modules.database.db_manager --history
    }
    
    "trends" {
        Write-Host "Trends (30 days):" -ForegroundColor Cyan
        python -m Guardian.modules.database.db_manager --trends
    }
    
    "patterns" {
        Write-Host "Pattern Analysis:" -ForegroundColor Cyan
        python -m Guardian.modules.database.db_manager --patterns
    }
    
    "daemon" {
        Write-Host "Starting Guardian as background service..." -ForegroundColor Cyan
        Start-Process -FilePath "$ScriptDir\guardian_daemon.cmd" -WindowStyle Hidden
        Write-Host "Guardian started in background" -ForegroundColor Green
    }
    
    "menu" {
        while ($true) {
            $choice = Show-Menu
            
            switch ($choice) {
                "1" { python -m Guardian.modules.services.ai_guardian --decision }
                "2" { python -m Guardian.modules.windows.windows_guardian }
                "3" { python -m Guardian.modules.diagnostics.diagnostics }
                "4" { python -c "from Guardian import cleanup_all; import json; print(json.dumps(cleanup_all(), indent=2))" }
                "5" { python -c "from Guardian import optimize_wsl; import json; print(json.dumps(optimize_wsl('$Distro'), indent=2))" }
                "6" { python -c "from Guardian import shrink_wsl_disk; import json; print(json.dumps(shrink_wsl_disk('$Distro'), indent=2))" }
                "7" { python -c "from Guardian.modules.docker.docker_guardian import DockerGuardian; import json; print(json.dumps(DockerGuardian().get_disk_state().__dict__, indent=2, default=str))" }
                "8" { python -c "from Guardian.modules.docker.docker_guardian import DockerGuardian; import json; r = DockerGuardian().prune(); print(json.dumps({'success': r.success, 'actions': r.actions, 'freed_gb': round(r.space_freed_gb,2), 'errors': r.errors}, indent=2))" }
                "9" { python -m Guardian.modules.database.db_manager --history }
                "A" { python -m Guardian.modules.services.service_health }
                "B" { python -m Guardian.modules.services.ollama_monitor }
                "C" { Write-Host 'Running disk report...'; python -m Guardian.modules.disk.disk_report }
                "E" { python -m Guardian.modules.performance.stale_cache_cleaner }
                "F" { python -m Guardian.modules.monitor.log_watcher 24 }
                "J" { python -m Guardian.modules.memory.memory_pressure }
                "G" { python -m Guardian.modules.database.db_manager --trends }
                "H" { python -m Guardian.modules.database.db_manager --patterns }
                "D" { 
                    Start-Process -FilePath "$ScriptDir\guardian_daemon.cmd" -WindowStyle Hidden
                    Write-Host "Guardian started in background" -ForegroundColor Green
                }
                { $_ -in @("Q", "q") } { 
                    Write-Host "Goodbye!" -ForegroundColor Cyan
                    break 
                }
                default { Write-Host "Invalid option" -ForegroundColor Red }
            }
            
            if ($choice -notin @("2")) {
                Write-Host ""
                Read-Host "Press Enter to continue"
            }
        }
    }
}

if ($Background) {
    Start-Process -FilePath "$ScriptDir\guardian_daemon.cmd" -WindowStyle Hidden
}
