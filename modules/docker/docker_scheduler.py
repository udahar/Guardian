#!/usr/bin/env python3
"""
Docker Scheduled Cleanup Manager
Sets up automatic Docker cleanup on a schedule
"""

import sys
import os
import platform
from pathlib import Path
from typing import Dict, Any, List
import json
import logging
from datetime import datetime, time
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Guardian.modules.docker import DockerGuardian


class DockerScheduledCleanup:
    """Manages scheduled Docker cleanup tasks."""

    def __init__(self):
        self.logger = logging.getLogger("DockerScheduledCleanup")
        self.platform = platform.system()

    def setup_weekly_cleanup(self) -> Dict[str, Any]:
        """Set up weekly Docker cleanup task."""
        result = {"success": False, "changes": [], "errors": []}

        if self.platform == "Windows":
            result = self._setup_windows_task()
        elif self.platform == "Darwin":
            result = self._setup_macos_launchd()
        else:
            result = self._setup_linux_cron()

        return result

    def _setup_windows_task(self) -> Dict[str, Any]:
        """Set up Windows Scheduled Task for weekly cleanup."""
        result = {"success": False, "changes": [], "errors": []}

        # PowerShell script to create scheduled task
        script = r"""
$TaskName = "GuardianDockerCleanup"
$TaskPath = "\Guardian\"

# Create task if not exists
$task = Get-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -ErrorAction SilentlyContinue

if ($null -eq $task) {
    $action = New-ScheduledTaskAction -Execute 'powershell.exe' -Argument @'
        -NoProfile -WindowStyle Hidden -Command "
        $dockerPath = 'C:\Users\Richard\clawd\Guardian'
        Set-Location $dockerPath
        python.exe -m Guardian.modules.docker.docker_guardian
    "@
    
    $trigger = New-ScheduledTaskTrigger -Weekly -DaysOfWeek Sunday -At 02:00AM
    
    $settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -StartWhenAvailable
    
    Register-ScheduledTask -TaskName $TaskName -TaskPath $TaskPath -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
    
    Write-Output "Created Windows Scheduled Task: $TaskName"
} else {
    Write-Output "Windows Scheduled Task already exists: $TaskName"
}
"""

        try:
            result_obj = subprocess.run(
                ["powershell", "-Command", script],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if result_obj.returncode == 0:
                result["success"] = True
                result["changes"].append(
                    "Windows Scheduled Task created (Sunday 2:00 AM)"
                )
                if result_obj.stdout:
                    result["changes"].append(result_obj.stdout.strip())
            else:
                result["errors"].append(
                    f"Failed to create task: {result_obj.stderr[:200]}"
                )

        except Exception as e:
            result["errors"].append(f"PowerShell error: {str(e)}")

        return result

    def _setup_macos_launchd(self) -> Dict[str, Any]:
        """Set up macOS launchd for weekly cleanup."""
        result = {"success": False, "changes": [], "errors": []}

        plist_content = """<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.guardian.docker.cleanup</string>
    <key>ProgramArguments</key>
    <array>
        <string>/usr/bin/python3</string>
        <string>-m</string>
        <string>Guardian.modules.docker.docker_guardian</string>
    </array>
    <key>StartCalendarInterval</key>
    <dict>
        <key>Weekday</key>
        <integer>0</integer>
        <key>Hour</key>
        <integer>2</integer>
        <key>Minute</key>
        <integer>0</integer>
    </dict>
    <key>StandardOutPath</key>
    <string>/var/log/guardian-docker-cleanup.log</string>
    <key>StandardErrorPath</key>
    <string>/var/log/guardian-docker-cleanup.log</string>
    <key>RunAtLoad</key>
    <false/>
    <key>KeepAlive</key>
    <false/>
</dict>
</plist>"""

        try:
            plist_path = Path.home() / "Library" / "LaunchAgents" / "com.guardian.docker.cleanup.plist"
            plist_path.parent.mkdir(parents=True, exist_ok=True)

            with open(plist_path, "w") as f:
                f.write(plist_content)

            result["success"] = True
            result["changes"].append(f"Created launchd plist: {plist_path}")
            result["changes"].append("launchctl load ~/Library/LaunchAgents/com.guardian.docker.cleanup.plist")

        except Exception as e:
            result["errors"].append(f"Error creating launchd plist: {str(e)}")

        return result

    def _setup_linux_cron(self) -> Dict[str, Any]:
        """Set up Linux cron job for weekly cleanup."""
        result = {"success": False, "changes": [], "errors": []}

        # Create cron entry
        cron_command = '0 2 * * 0 cd /path/to/Guardian && /usr/bin/python3 -m Guardian.modules.docker.docker_guardian >> /var/log/guardian-docker-cleanup.log 2>&1'

        try:
            # Check if cron already exists
            result_obj = subprocess.run(
                ["crontab", "-l"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            existing_crontab = result_obj.stdout if result_obj.returncode == 0 else ""

            if "guardian.docker.cleanup" not in existing_crontab:
                # Add new cron job
                new_crontab = existing_crontab + f"\n# Guardian Docker cleanup - Sunday 2:00 AM\n{cron_command}\n"

                result_obj = subprocess.run(
                    ["crontab", "-"],
                    input=new_crontab,
                    capture_output=True,
                    text=True,
                    timeout=10,
                )

                if result_obj.returncode == 0:
                    result["success"] = True
                    result["changes"].append("Cron job created (Sunday 2:00 AM)")
                else:
                    result["errors"].append(f"Failed to set cron: {result_obj.stderr[:100]}")
            else:
                result["success"] = True
                result["changes"].append("Cron job already exists")

        except Exception as e:
            result["errors"].append(f"Error setting up cron: {str(e)}")

        return result

    def cleanup_now(self, aggressive: bool = False) -> Dict[str, Any]:
        """Run cleanup immediately."""
        docker = DockerGuardian()
        cleanup_result = docker.prune(aggressive=aggressive)

        return {
            "timestamp": datetime.now().isoformat(),
            "success": cleanup_result.success,
            "actions": cleanup_result.actions,
            "space_freed_gb": cleanup_result.space_freed_gb,
            "errors": cleanup_result.errors,
        }

    def get_cleanup_schedule(self) -> Dict[str, Any]:
        """Get scheduled cleanup information."""
        return {
            "platform": self.platform,
            "schedule": "Weekly - Sunday 2:00 AM",
            "next_cleanup_day": "Sunday",
            "next_cleanup_time": "02:00 (UTC)",
            "aggressive_mode": False,
            "note": "Set up with setup_weekly_cleanup()",
        }


def main():
    logging.basicConfig(level=logging.INFO)

    scheduler = DockerScheduledCleanup()

    print("Docker Scheduled Cleanup Manager")
    print(f"Platform: {scheduler.platform}")
    print()

    # Setup schedule
    print("Setting up weekly cleanup schedule...")
    result = scheduler.setup_weekly_cleanup()
    print(f"Success: {result['success']}")
    if result["changes"]:
        for change in result["changes"]:
            print(f"  ✓ {change}")
    if result["errors"]:
        for error in result["errors"]:
            print(f"  ✗ {error}")

    print()

    # Show schedule
    print("Current schedule:")
    schedule = scheduler.get_cleanup_schedule()
    for key, value in schedule.items():
        print(f"  {key}: {value}")

    print()

    # Cleanup now
    print("Running cleanup now...")
    cleanup_result = scheduler.cleanup_now(aggressive=False)
    print(json.dumps(cleanup_result, indent=2))


if __name__ == "__main__":
    main()
