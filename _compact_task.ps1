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
