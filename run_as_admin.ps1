#Requires -RunAsAdministrator
# Guardian: One-time admin cleanup + scheduled task installer
# Right-click → Run as Administrator

$ErrorActionPreference = "Continue"
$freed = 0

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Guardian Admin Cleanup" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan

# ── Adobe dead installations ──────────────────────────────────────────────
function Remove-Dir($path, $label) {
    if (Test-Path $path) {
        $size = (Get-ChildItem $path -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
        Remove-Item $path -Recurse -Force -ErrorAction SilentlyContinue
        if (-not (Test-Path $path)) {
            $gb = [math]::Round($size / 1GB, 2)
            Write-Host "  DELETED $label ($gb GB)" -ForegroundColor Green
            return $size
        } else {
            Write-Host "  PARTIAL $label (some files locked)" -ForegroundColor Yellow
            return 0
        }
    } else {
        Write-Host "  SKIP    $label (already gone)"
        return 0
    }
}

Write-Host ""
Write-Host "Adobe cleanup:" -ForegroundColor Yellow
$freed += Remove-Dir "C:\Program Files\Adobe\Adobe Photoshop 2025" "Photoshop 2025"
$freed += Remove-Dir "C:\Program Files\Adobe\Adobe Character Animator 2025" "Character Animator 2025"

# Clean orphaned registry entries
$regPaths = @(
    "HKLM:\SOFTWARE\Microsoft\Windows\CurrentVersion\Uninstall",
    "HKLM:\SOFTWARE\WOW6432Node\Microsoft\Windows\CurrentVersion\Uninstall"
)
foreach ($base in $regPaths) {
    Get-ChildItem $base -ErrorAction SilentlyContinue | ForEach-Object {
        $props = Get-ItemProperty $_.PSPath -ErrorAction SilentlyContinue
        if ($props.DisplayName -match "Photoshop 2025|Character Animator 2025") {
            Remove-Item $_.PSPath -Force -ErrorAction SilentlyContinue
            Write-Host "  Cleaned registry: $($props.DisplayName)" -ForegroundColor Green
        }
    }
}

# ── WSL VHD compact ───────────────────────────────────────────────────────
Write-Host ""
Write-Host "WSL + Docker VHD compact:" -ForegroundColor Yellow

# Find Ubuntu VHD via registry
$ubuntuVhd = $null
try {
    $lxss = Get-ChildItem "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Lxss" -ErrorAction Stop
    foreach ($key in $lxss) {
        $props = Get-ItemProperty $key.PSPath -ErrorAction SilentlyContinue
        if ($props.DistributionName -eq "Ubuntu") {
            $ubuntuVhd = Join-Path $props.BasePath "ext4.vhdx"
            break
        }
    }
} catch {}

Write-Host "  Shutting down WSL..."
wsl --shutdown
Start-Sleep -Seconds 5

if ($ubuntuVhd -and (Test-Path $ubuntuVhd)) {
    $sizeBefore = (Get-Item $ubuntuVhd).Length
    Write-Host "  Enabling sparse mode for Ubuntu..."
    wsl --manage Ubuntu --set-sparse true 2>$null
    Write-Host "  Compacting Ubuntu VHD ($([math]::Round($sizeBefore/1GB,1)) GB)..."
    $dpScript = "select vdisk file=`"$ubuntuVhd`"`r`nattach vdisk readonly`r`ncompact vdisk`r`ndetach vdisk`r`nexit"
    $tmpFile = "$env:TEMP\guardian_wsl_compact.txt"
    $dpScript | Set-Content $tmpFile -Encoding ASCII
    diskpart /s $tmpFile | Out-Null
    Remove-Item $tmpFile -ErrorAction SilentlyContinue
    $sizeAfter = (Get-Item $ubuntuVhd -ErrorAction SilentlyContinue).Length
    if ($sizeAfter) {
        $savedGB = [math]::Round(($sizeBefore - $sizeAfter) / 1GB, 2)
        Write-Host "  Ubuntu VHD: $([math]::Round($sizeBefore/1GB,1))GB -> $([math]::Round($sizeAfter/1GB,1))GB (saved $savedGB GB)" -ForegroundColor Green
        $freed += ($sizeBefore - $sizeAfter)
    }
} else {
    Write-Host "  Ubuntu VHD not found — skipping" -ForegroundColor Yellow
}

# Docker VHD compact
$dockerVhd = "C:\Users\Richard\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
if (Test-Path $dockerVhd) {
    $sizeBefore = (Get-Item $dockerVhd).Length
    Write-Host "  Compacting Docker VHD ($([math]::Round($sizeBefore/1GB,1)) GB)..."
    $dpScript = "select vdisk file=`"$dockerVhd`"`r`nattach vdisk readonly`r`ncompact vdisk`r`ndetach vdisk`r`nexit"
    $tmpFile = "$env:TEMP\guardian_docker_compact.txt"
    $dpScript | Set-Content $tmpFile -Encoding ASCII
    diskpart /s $tmpFile | Out-Null
    Remove-Item $tmpFile -ErrorAction SilentlyContinue
    $sizeAfter = (Get-Item $dockerVhd -ErrorAction SilentlyContinue).Length
    if ($sizeAfter) {
        $savedGB = [math]::Round(($sizeBefore - $sizeAfter) / 1GB, 2)
        Write-Host "  Docker VHD: $([math]::Round($sizeBefore/1GB,1))GB -> $([math]::Round($sizeAfter/1GB,1))GB (saved $savedGB GB)" -ForegroundColor Green
        $freed += ($sizeBefore - $sizeAfter)
    }
}

# ── Install Guardian scheduled tasks ─────────────────────────────────────
Write-Host ""
Write-Host "Installing Guardian scheduled tasks:" -ForegroundColor Yellow
$guardianDir = "C:\Users\Richard\clawd\Guardian"
$python = "python"
$clawd = "C:\Users\Richard\clawd"

# Task 1: Daily safe cleanup at 2 AM
$action = New-ScheduledTaskAction -Execute $python -Argument "-m Guardian.modules.performance.safe_cleanup_pass" -WorkingDirectory $clawd
$trigger = New-ScheduledTaskTrigger -Daily -At "02:00"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 1) -StartWhenAvailable -RunOnlyIfIdle $false
Register-ScheduledTask -TaskName "Guardian-DailyCleanup" -TaskPath "\Guardian\" -Action $action -Trigger $trigger -Settings $settings -RunLevel Highest -Force | Out-Null
Write-Host "  Registered: Guardian-DailyCleanup (daily 2AM)" -ForegroundColor Green

# Task 2: Weekly VHD compact Sunday 3 AM (this script, minus task registration)
$compactScript = "$guardianDir\_compact_vhds_full.ps1"
@'
#Requires -RunAsAdministrator
# Guardian: Weekly WSL + Docker VHD compact
wsl --shutdown
Start-Sleep -Seconds 5

# Ubuntu
try {
    $lxss = Get-ChildItem "HKCU:\SOFTWARE\Microsoft\Windows\CurrentVersion\Lxss"
    foreach ($key in $lxss) {
        $props = Get-ItemProperty $key.PSPath -ErrorAction SilentlyContinue
        if ($props.DistributionName -eq "Ubuntu") {
            $vhd = Join-Path $props.BasePath "ext4.vhdx"
            if (Test-Path $vhd) {
                $dp = "select vdisk file=`"$vhd`"`r`nattach vdisk readonly`r`ncompact vdisk`r`ndetach vdisk`r`nexit"
                $tmp = "$env:TEMP\guardian_compact_wsl.txt"
                $dp | Set-Content $tmp -Encoding ASCII
                diskpart /s $tmp | Out-Null
                Remove-Item $tmp -ErrorAction SilentlyContinue
                Write-EventLog -LogName Application -Source "Guardian" -EventId 1001 -Message "WSL VHD compacted: $vhd" -ErrorAction SilentlyContinue
            }
        }
    }
} catch {}

# Docker
$dockerVhd = "C:\Users\Richard\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
if (Test-Path $dockerVhd) {
    $dp = "select vdisk file=`"$dockerVhd`"`r`nattach vdisk readonly`r`ncompact vdisk`r`ndetach vdisk`r`nexit"
    $tmp = "$env:TEMP\guardian_compact_docker.txt"
    $dp | Set-Content $tmp -Encoding ASCII
    diskpart /s $tmp | Out-Null
    Remove-Item $tmp -ErrorAction SilentlyContinue
}
Write-Host "Guardian VHD compact complete."
'@ | Set-Content $compactScript -Encoding UTF8

$action2 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$compactScript`""
$trigger2 = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At "03:00"
$settings2 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Hours 2) -StartWhenAvailable -RunOnlyIfIdle $false
Register-ScheduledTask -TaskName "Guardian-WeeklyVHDCompact" -TaskPath "\Guardian\" -Action $action2 -Trigger $trigger2 -Settings $settings2 -RunLevel Highest -Force | Out-Null
Write-Host "  Registered: Guardian-WeeklyVHDCompact (Sunday 3AM)" -ForegroundColor Green

# Task 3: vm_bundles auto-prune at 2:15 AM (runs after daily cleanup)
$vmScript = "$guardianDir\_prune_vm_bundles.ps1"
@'
# Guardian: Auto-prune Claude vm_bundles when Claude Desktop not running
$claudeDesktop = Get-Process "claude" -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*WindowsApps*" }
if ($claudeDesktop) {
    Write-Host "Claude Desktop running — skipping vm_bundles prune"
    exit 0
}
$vmBundles = "$env:APPDATA\Claude\vm_bundles"
if (Test-Path $vmBundles) {
    $size = (Get-ChildItem $vmBundles -Recurse -File -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum
    Remove-Item $vmBundles -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "vm_bundles pruned: $([math]::Round($size/1GB,2))GB freed"
} else {
    Write-Host "vm_bundles not found"
}
'@ | Set-Content $vmScript -Encoding UTF8

$action3 = New-ScheduledTaskAction -Execute "powershell.exe" -Argument "-NoProfile -ExecutionPolicy Bypass -File `"$vmScript`""
$trigger3 = New-ScheduledTaskTrigger -Daily -At "02:15"
$settings3 = New-ScheduledTaskSettingsSet -ExecutionTimeLimit (New-TimeSpan -Minutes 10) -StartWhenAvailable
Register-ScheduledTask -TaskName "Guardian-VMBundlesPrune" -TaskPath "\Guardian\" -Action $action3 -Trigger $trigger3 -Settings $settings3 -RunLevel Highest -Force | Out-Null
Write-Host "  Registered: Guardian-VMBundlesPrune (daily 2:15AM, only when Claude Desktop closed)" -ForegroundColor Green

# ── Summary ───────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  Total freed: $([math]::Round($freed/1GB, 2)) GB" -ForegroundColor Cyan
$after = (Get-PSDrive C).Free
Write-Host "  C: free now: $([math]::Round($after/1GB, 2)) GB" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "Guardian scheduled tasks installed. Run Get-ScheduledTask -TaskPath '\Guardian\' to verify." -ForegroundColor Green
Write-Host "Restart FieldBench/Docker when ready: FieldBench\_start.ps1" -ForegroundColor Yellow
