# Guardian Scheduled Tasks Installer
# Run as Administrator once to install daily auto-cleanup and VHD compact tasks

$guardianDir = "C:\Users\Richard\clawd\Guardian"
$python = "python"

# Task 1: Daily safe cleanup (2 AM)
$action1 = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-m Guardian.modules.performance.safe_cleanup_pass" `
    -WorkingDirectory "C:\Users\Richard\clawd"
$trigger1 = New-ScheduledTaskTrigger -Daily -At "02:00"
$settings1 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable
Register-ScheduledTask `
    -TaskName "Guardian-DailyCleanup" `
    -TaskPath "\Guardian\" `
    -Action $action1 `
    -Trigger $trigger1 `
    -Settings $settings1 `
    -RunLevel Highest `
    -Force
Write-Host "Registered: Guardian-DailyCleanup (daily 2 AM)"

# Task 2: Weekly WSL VHD compact (Sunday 3 AM) — requires admin
$wslCompactScript = @"
wsl --shutdown
Start-Sleep -Seconds 5
# Ubuntu VHD
`$vhd = (Get-ItemProperty 'HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Lxss\*' | Where-Object DistributionName -eq 'Ubuntu').BasePath + '\ext4.vhdx'
if (Test-Path `$vhd) {
    `$script = "select vdisk file=`"`$vhd`"`nattach vdisk readonly`ncompact vdisk`ndetach vdisk`nexit"
    `$script | diskpart
    Write-Host "Compacted: `$vhd"
}
# Docker data VHD
`$dockerVhd = `"C:\Users\Richard\AppData\Local\Docker\wsl\disk\docker_data.vhdx`"
if (Test-Path `$dockerVhd) {
    `$script2 = "select vdisk file=`"`$dockerVhd`"`nattach vdisk readonly`ncompact vdisk`ndetach vdisk`nexit"
    `$script2 | diskpart
    Write-Host "Compacted Docker VHD"
}
"@
$wslCompactPath = "$guardianDir\_compact_vhds.ps1"
$wslCompactScript | Out-File -FilePath $wslCompactPath -Encoding UTF8

$action2 = New-ScheduledTaskAction `
    -Execute "powershell.exe" `
    -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$wslCompactPath`""
$trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00"
$settings2 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable
Register-ScheduledTask `
    -TaskName "Guardian-WeeklyVHDCompact" `
    -TaskPath "\Guardian\" `
    -Action $action2 `
    -Trigger $trigger2 `
    -Settings $settings2 `
    -RunLevel Highest `
    -Force
Write-Host "Registered: Guardian-WeeklyVHDCompact (Sunday 3 AM)"

# Task 3: Disk alert check every 30 minutes
$action3 = New-ScheduledTaskAction `
    -Execute $python `
    -Argument "-c `"import psutil; d=psutil.disk_usage('C:'); exit(1 if d.percent>85 else 0)`"" `
    -WorkingDirectory "C:\Users\Richard\clawd"
$trigger3 = New-ScheduledTaskTrigger -RepetitionInterval (New-TimeSpan -Minutes 30) -Once -At (Get-Date)
Register-ScheduledTask `
    -TaskName "Guardian-DiskAlertCheck" `
    -TaskPath "\Guardian\" `
    -Action $action3 `
    -Trigger $trigger3 `
    -Settings (New-ScheduledTaskSettingsSet -StartWhenAvailable) `
    -Force
Write-Host "Registered: Guardian-DiskAlertCheck (every 30 min)"

Write-Host ""
Write-Host "All Guardian scheduled tasks installed."
Write-Host "Run: Get-ScheduledTask -TaskPath '\Guardian\' to verify"
