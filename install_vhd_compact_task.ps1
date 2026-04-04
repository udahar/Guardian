
# Install Guardian VHD Compact as a weekly scheduled task (runs as SYSTEM)
$taskName = "GuardianVHDCompact"
$guardianPath = "C:\Users\Richard\clawd"
$pythonExe = "C:\Users\Richard\AppData\Local\Python\pythoncore-3.14-64\python.exe"
$action = New-ScheduledTaskAction `
    -Execute $pythonExe `
    -Argument "-m Guardian.modules.wsl.vhd_compact --auto" `
    -WorkingDirectory $guardianPath

# Every Sunday at 3am (when you're not working)
$trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00"

$settings = New-ScheduledTaskSettingsSet `
    -StartWhenAvailable `
    -ExecutionTimeLimit (New-TimeSpan -Hours 1)

$principal = New-ScheduledTaskPrincipal -UserId "SYSTEM" -RunLevel Highest

Register-ScheduledTask `
    -TaskName $taskName `
    -Action $action `
    -Trigger $trigger `
    -Settings $settings `
    -Principal $principal `
    -Force

Write-Host "Scheduled task '$taskName' installed. Runs every Sunday at 3am as SYSTEM."
