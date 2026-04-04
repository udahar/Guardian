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
