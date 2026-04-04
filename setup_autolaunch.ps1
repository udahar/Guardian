# Guardian Auto-Launch Setup
# Registers Guardian as a scheduled task that starts at login
# Also registers weekly Docker VHD compaction (runs as admin, kills Docker, compacts, restarts)
#
# Run this once as Administrator:
#   Right-click setup_autolaunch.ps1 -> Run as Administrator

param(
    [switch]$Remove   # Pass -Remove to uninstall all Guardian tasks
)

$ErrorActionPreference = "Stop"
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$GuardianDir = $ScriptDir
$RepoRoot = Split-Path -Parent $GuardianDir
$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
$DaemonCmd = Join-Path $GuardianDir "guardian_daemon.cmd"
$CleanupCmd = Join-Path $GuardianDir "safe_cleanup.cmd"
$CompactBat  = "C:\Users\Richard\compact_docker.bat"

if (-not $PythonPath) {
    Write-Host "ERROR: python not found in PATH" -ForegroundColor Red
    exit 1
}

# ── Task names ──────────────────────────────────────────────────────────────
$TaskDaemon  = "Guardian - System Health Daemon"
$TaskDocker  = "Guardian - Docker Weekly Compact"
$TaskPrune   = "Guardian - Docker Daily Prune"
$TaskCleanup = "Guardian - Safe Cleanup Pass"

if ($Remove) {
    Write-Host "Removing Guardian scheduled tasks..." -ForegroundColor Yellow
    foreach ($t in @($TaskDaemon, $TaskDocker, $TaskPrune, $TaskCleanup)) {
        if (Get-ScheduledTask -TaskName $t -ErrorAction SilentlyContinue) {
            Unregister-ScheduledTask -TaskName $t -Confirm:$false
            Write-Host "  Removed: $t" -ForegroundColor Green
        }
    }
    Write-Host "Done." -ForegroundColor Green
    exit 0
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Guardian Auto-Launch Setup            " -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# ── 1. Guardian daemon — starts at user login ────────────────────────────────
Write-Host "[1/4] Registering Guardian daemon (start at login)..." -ForegroundColor Yellow

$DaemonAction = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$DaemonCmd`""

$DaemonTrigger = New-ScheduledTaskTrigger -AtLogon

$DaemonSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Hours 0) `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 5) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskDaemon `
    -Action $DaemonAction `
    -Trigger $DaemonTrigger `
    -Settings $DaemonSettings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "  OK: $TaskDaemon" -ForegroundColor Green

# ── 2. Docker daily prune — 3 AM every day ──────────────────────────────────
Write-Host "[2/4] Registering Docker daily prune (3 AM)..." -ForegroundColor Yellow

$PruneAction = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "-c `"from Guardian.modules.docker.docker_guardian import DockerGuardian; r = DockerGuardian(cache_prune_threshold_gb=1.0).prune(); print('Freed:', round(r.space_freed_gb,2), 'GB')`"" `
    -WorkingDirectory $RepoRoot

$PruneTrigger = New-ScheduledTaskTrigger -Daily -At "03:00"

$PruneSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 10) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskPrune `
    -Action $PruneAction `
    -Trigger $PruneTrigger `
    -Settings $PruneSettings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "  OK: $TaskPrune" -ForegroundColor Green

# ── 3. Safe cleanup pass — daily 2:30 AM ────────────────────────────────────
Write-Host "[3/4] Registering safe cleanup pass (2:30 AM)..." -ForegroundColor Yellow

$CleanupAction = New-ScheduledTaskAction `
    -Execute "cmd.exe" `
    -Argument "/c `"$CleanupCmd`""

$CleanupTrigger = New-ScheduledTaskTrigger -Daily -At "02:30"

$CleanupSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 20) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskCleanup `
    -Action $CleanupAction `
    -Trigger $CleanupTrigger `
    -Settings $CleanupSettings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "  OK: $TaskCleanup" -ForegroundColor Green

# ── 4. Docker weekly VHD compact — Sunday 4 AM ──────────────────────────────
Write-Host "[4/4] Registering Docker weekly VHD compact (Sunday 4 AM)..." -ForegroundColor Yellow

# The compact script:
# 1. Kill Docker Desktop
# 2. Wait for VHD to be released
# 3. Run diskpart compact
# 4. Restart Docker Desktop
$CompactScript = @'
Write-Host "Guardian: Weekly Docker VHD compact starting..."
# Kill Docker
Get-Process -Name "Docker Desktop","com.docker.backend","docker-sandbox","com.docker.build","dockerd" -ErrorAction SilentlyContinue | Stop-Process -Force
Start-Sleep -Seconds 10
# Shutdown WSL so VHD handles are released
wsl --shutdown
Start-Sleep -Seconds 5
# Run diskpart compact
$diskpartScript = @"
select vdisk file="C:\Users\Richard\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"@
$tmpScript = "$env:TEMP\guardian_compact.txt"
$diskpartScript | Set-Content -Path $tmpScript -Encoding ASCII
diskpart /s $tmpScript
$diskpartExit = $LASTEXITCODE
Remove-Item $tmpScript -ErrorAction SilentlyContinue
if ($diskpartExit -ne 0) {
    Write-Host "Guardian: diskpart compact failed."
    exit $diskpartExit
}
# Restart Docker Desktop
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
Write-Host "Guardian: VHD compact done. Waiting for Docker daemon..."
$deadline = (Get-Date).AddMinutes(2)
do {
    Start-Sleep -Seconds 4
    docker info --format "{{.ServerVersion}}" *> $null
    if ($LASTEXITCODE -eq 0) {
        Write-Host "Guardian: Docker daemon is ready."
        exit 0
    }
} while ((Get-Date) -lt $deadline)
Write-Host "Guardian: Docker Desktop started but daemon did not become ready within timeout."
exit 1
'@

$CompactScriptPath = "$GuardianDir\_compact_task.ps1"
$CompactScript | Set-Content -Path $CompactScriptPath -Encoding UTF8

$CompactAction = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NonInteractive -NoProfile -ExecutionPolicy Bypass -File `"$CompactScriptPath`""

$CompactTrigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "04:00"

$CompactSettings = New-ScheduledTaskSettingsSet `
    -ExecutionTimeLimit (New-TimeSpan -Minutes 30) `
    -MultipleInstances IgnoreNew

Register-ScheduledTask `
    -TaskName $TaskDocker `
    -Action $CompactAction `
    -Trigger $CompactTrigger `
    -Settings $CompactSettings `
    -RunLevel Highest `
    -Force | Out-Null

Write-Host "  OK: $TaskDocker" -ForegroundColor Green

Write-Host ""
Write-Host "========================================" -ForegroundColor Green
Write-Host "  All tasks registered successfully!    " -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Green
Write-Host ""
Write-Host "Tasks registered:" -ForegroundColor Cyan
Write-Host "  - Guardian daemon: starts at login, restarts on failure" -ForegroundColor White
Write-Host "  - Safe cleanup pass: daily, clears temp and package caches" -ForegroundColor White
Write-Host "  - Docker prune: daily, clears build cache" -ForegroundColor White
Write-Host "  - Docker weekly compact: Sunday 4 AM, reclaims VHD bloat" -ForegroundColor White
Write-Host ""
Write-Host "To remove all tasks: .\setup_autolaunch.ps1 -Remove" -ForegroundColor Gray
Write-Host ""

# Show registered tasks
Get-ScheduledTask | Where-Object { $_.TaskName -like "Guardian*" } |
    Select-Object TaskName, State |
    Format-Table -AutoSize
