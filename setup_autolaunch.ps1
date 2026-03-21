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
$PythonPath = (Get-Command python -ErrorAction SilentlyContinue).Source
$CompactBat  = "C:\Users\Richard\compact_docker.bat"

if (-not $PythonPath) {
    Write-Host "ERROR: python not found in PATH" -ForegroundColor Red
    exit 1
}

# ── Task names ──────────────────────────────────────────────────────────────
$TaskDaemon  = "Guardian - System Health Daemon"
$TaskDocker  = "Guardian - Docker Weekly Compact"
$TaskPrune   = "Guardian - Docker Daily Prune"

if ($Remove) {
    Write-Host "Removing Guardian scheduled tasks..." -ForegroundColor Yellow
    foreach ($t in @($TaskDaemon, $TaskDocker, $TaskPrune)) {
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
Write-Host "[1/3] Registering Guardian daemon (start at login)..." -ForegroundColor Yellow

$DaemonAction = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "-m Guardian.proactive_guardian" `
    -WorkingDirectory $GuardianDir

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
Write-Host "[2/3] Registering Docker daily prune (3 AM)..." -ForegroundColor Yellow

$PruneAction = New-ScheduledTaskAction `
    -Execute $PythonPath `
    -Argument "-c `"from Guardian.docker_guardian import DockerGuardian; r = DockerGuardian(cache_prune_threshold_gb=1.0).prune(); print('Freed:', round(r.space_freed_gb,2), 'GB')`"" `
    -WorkingDirectory $GuardianDir

$PruneTrigger = New-ScheduledTaskTrigger -AtLogon

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

# ── 3. Docker weekly VHD compact — Sunday 4 AM ──────────────────────────────
Write-Host "[3/3] Registering Docker weekly VHD compact (Sunday 4 AM)..." -ForegroundColor Yellow

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
Remove-Item $tmpScript -ErrorAction SilentlyContinue
# Restart Docker Desktop
Start-Process "C:\Program Files\Docker\Docker\Docker Desktop.exe"
Write-Host "Guardian: VHD compact done. Docker restarting."
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
Write-Host "  - Docker prune: at login, clears build cache" -ForegroundColor White
Write-Host "  - Docker weekly compact: Sunday 4 AM, reclaims VHD bloat" -ForegroundColor White
Write-Host ""
Write-Host "To remove all tasks: .\setup_autolaunch.ps1 -Remove" -ForegroundColor Gray
Write-Host ""

# Show registered tasks
Get-ScheduledTask | Where-Object { $_.TaskName -like "Guardian*" } |
    Select-Object TaskName, State |
    Format-Table -AutoSize
