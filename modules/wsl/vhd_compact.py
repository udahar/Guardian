#!/usr/bin/env python3
"""
VHD Compact - Windows VHDX Compaction for Docker and WSL
Guardian Module

The real fix for "deleted files but disk is still full":
- fstrim/drop_caches only frees space inside Linux
- VHD files on Windows DON'T shrink until diskpart compact is run
- This module handles that automatically

Targets:
- Docker: AppData/Local/Docker/wsl/disk/docker_data.vhdx (can be 20+ GB)
- WSL Ubuntu: AppData/Local/Packages/Canonical*/LocalState/ext4.vhdx

Requires: Admin rights (runs via scheduled task as SYSTEM) or elevated PS shell.
"""

import os
import subprocess
import logging
import time
import glob
import tempfile
import winreg
import ctypes
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime
from pathlib import Path


@dataclass
class VHDInfo:
    path: str
    label: str
    size_gb: float
    exists: bool


@dataclass
class CompactResult:
    label: str
    path: str
    size_before_gb: float
    size_after_gb: float
    freed_gb: float
    success: bool
    error: str = ""


class VHDCompactor:
    """
    Compact VHDX files to reclaim space after Docker/WSL deletes.

    This solves the "I deleted 20GB inside Docker/WSL but Windows
    didn't gain any space back" problem.
    """

    DOCKER_VHD = r"AppData\Local\Docker\wsl\disk\docker_data.vhdx"
    WSL_VHD_PATTERN = r"AppData\Local\Packages\CanonicalGroupLimited.*\LocalState\ext4.vhdx"

    def _find_registry_wsl_vhds(self) -> List[VHDInfo]:
        """
        Find WSL distros registered under the modern HKCU\...\Lxss registry key.

        Newer/imported distros live under AppData\Local\wsl\{guid}\ext4.vhdx rather
        than the older Microsoft Store Packages\Canonical...\LocalState layout.
        """
        vhds: List[VHDInfo] = []
        root = r"Software\Microsoft\Windows\CurrentVersion\Lxss"

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, root) as key:
                subkey_count, _, _ = winreg.QueryInfoKey(key)
                for i in range(subkey_count):
                    subkey_name = winreg.EnumKey(key, i)
                    with winreg.OpenKey(key, subkey_name) as subkey:
                        try:
                            distro = winreg.QueryValueEx(subkey, "DistributionName")[0]
                            base_path = winreg.QueryValueEx(subkey, "BasePath")[0]
                        except FileNotFoundError:
                            continue

                        if distro == "docker-desktop":
                            continue

                        vhd_path = Path(base_path) / "ext4.vhdx"
                        if vhd_path.exists():
                            vhds.append(VHDInfo(
                                path=str(vhd_path),
                                label=f"WSL-{distro}",
                                size_gb=vhd_path.stat().st_size / 1e9,
                                exists=True,
                            ))
        except OSError:
            pass

        return vhds

    def __init__(self, username: str = None):
        self.username = username or os.environ.get("USERNAME", "Richard")
        self.user_home = Path(f"C:\\Users\\{self.username}")
        self.logger = self._setup_logging()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("VHDCompactor")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            logger.addHandler(handler)
        return logger

    def is_admin(self) -> bool:
        try:
            return bool(ctypes.windll.shell32.IsUserAnAdmin())
        except Exception:
            return False

    def find_vhds(self) -> List[VHDInfo]:
        """Find all VHDX files that can be compacted."""
        vhds = []

        # Docker VHD
        docker_path = self.user_home / self.DOCKER_VHD
        vhds.append(VHDInfo(
            path=str(docker_path),
            label="Docker",
            size_gb=docker_path.stat().st_size / 1e9 if docker_path.exists() else 0,
            exists=docker_path.exists(),
        ))

        # WSL Ubuntu VHD(s)
        wsl_pattern = str(self.user_home / self.WSL_VHD_PATTERN)
        for match in glob.glob(wsl_pattern):
            p = Path(match)
            distro = p.parts[-3].replace("CanonicalGroupLimited.", "").split("Ubuntu")[0] or "Ubuntu"
            vhds.append(VHDInfo(
                path=match,
                label=f"WSL-{distro}",
                size_gb=p.stat().st_size / 1e9 if p.exists() else 0,
                exists=p.exists(),
            ))

        # Modern/imported WSL distros use registry metadata instead.
        seen_paths = {v.path for v in vhds}
        for vhd in self._find_registry_wsl_vhds():
            if vhd.path not in seen_paths:
                vhds.append(vhd)

        return [v for v in vhds if v.exists]

    def get_wasted_space_estimate(self) -> float:
        """
        Estimate how much space is wasted in VHDs.
        VHD size - actual WSL/Docker used = waste (roughly).
        """
        total_vhd_gb = sum(v.size_gb for v in self.find_vhds())
        # Rough heuristic: VHDs are typically 30-60% wasted after heavy use
        return total_vhd_gb

    def _build_diskpart_script(self, vhd_path: str) -> str:
        """Build a diskpart script to compact a single VHD."""
        return (
            f'select vdisk file="{vhd_path}"\n'
            f'attach vdisk readonly\n'
            f'compact vdisk\n'
            f'detach vdisk\n'
            f'exit\n'
        )

    def compact_vhd(self, vhd: VHDInfo) -> CompactResult:
        """Compact a single VHDX file using diskpart."""
        result = CompactResult(
            label=vhd.label,
            path=vhd.path,
            size_before_gb=vhd.size_gb,
            size_after_gb=vhd.size_gb,
            freed_gb=0,
            success=False,
        )

        if not vhd.exists:
            result.error = "VHD not found"
            return result

        self.logger.info(f"Compacting {vhd.label} ({vhd.size_gb:.1f}GB): {vhd.path}")

        # Write diskpart script to temp file
        script = self._build_diskpart_script(vhd.path)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(script)
            script_path = f.name

        try:
            proc = subprocess.run(
                ["diskpart", "/s", script_path],
                capture_output=True,
                text=True,
                timeout=300,
            )

            if "successfully compacted" in proc.stdout.lower() or proc.returncode == 0:
                # Measure after
                p = Path(vhd.path)
                if p.exists():
                    result.size_after_gb = p.stat().st_size / 1e9
                result.freed_gb = result.size_before_gb - result.size_after_gb
                result.success = True
                self.logger.info(
                    f"{vhd.label} compact done: freed {result.freed_gb:.1f}GB "
                    f"({result.size_before_gb:.1f}GB → {result.size_after_gb:.1f}GB)"
                )
            else:
                result.error = proc.stdout + proc.stderr
                self.logger.error(f"diskpart failed for {vhd.label}: {result.error[:200]}")

        except subprocess.TimeoutExpired:
            result.error = "diskpart timed out after 5 minutes"
            self.logger.error(f"Compact timed out for {vhd.label}")
        except PermissionError:
            result.error = "Access denied - diskpart requires admin rights"
            self.logger.error(f"Admin required to compact {vhd.label}")
        except Exception as e:
            result.error = str(e)
            self.logger.error(f"Compact failed for {vhd.label}: {e}")
        finally:
            try:
                os.unlink(script_path)
            except Exception:
                pass

        return result

    def shutdown_wsl_and_docker(self) -> bool:
        """Shut down WSL and Docker so VHDs can be compacted."""
        self.logger.info("Shutting down WSL and Docker for VHD compaction...")

        for proc_name in ["Docker Desktop", "com.docker.backend", "dockerd"]:
            subprocess.run(
                ["powershell", "-NoProfile", "-Command",
                 f"Stop-Process -Name '{proc_name}' -Force -ErrorAction SilentlyContinue"],
                capture_output=True, timeout=10,
            )

        time.sleep(3)

        try:
            subprocess.run(["wsl", "--shutdown"], capture_output=True, timeout=30)
            self.logger.info("WSL shut down")
        except Exception as e:
            self.logger.warning(f"wsl --shutdown: {e}")

        # Common Windows-side holders of WSL VHD handles.
        for image_name in ["Code.exe", "Cursor.exe", "WindowsTerminal.exe", "explorer.exe"]:
            try:
                subprocess.run(
                    ["taskkill", "/f", "/im", image_name],
                    capture_output=True,
                    text=True,
                    timeout=15,
                )
            except Exception as e:
                self.logger.warning(f"taskkill {image_name}: {e}")

        time.sleep(3)
        return True

    def _docker_info(self) -> tuple[bool, str, str]:
        try:
            proc = subprocess.run(
                ["docker", "info", "--format", "{{.ServerVersion}}"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return proc.returncode == 0, proc.stdout.strip(), proc.stderr.strip()
        except Exception as e:
            return False, "", str(e)

    def restart_docker_desktop(self, wait_seconds: int = 90) -> Dict[str, object]:
        docker_exe = Path(r"C:\Program Files\Docker\Docker\Docker Desktop.exe")
        if not docker_exe.exists():
            return {"started": False, "ready": False, "error": "Docker Desktop.exe not found"}

        try:
            subprocess.Popen([str(docker_exe)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except Exception as e:
            self.logger.warning(f"start Docker Desktop: {e}")
            return {"started": False, "ready": False, "error": str(e)}

        deadline = time.time() + max(10, int(wait_seconds))
        last_error = "docker not ready"
        while time.time() < deadline:
            ok, out, err = self._docker_info()
            if ok and out:
                self.logger.info("Docker Desktop restarted and daemon is responding")
                return {"started": True, "ready": True, "error": None}
            last_error = err or last_error
            time.sleep(3)

        self.logger.warning(f"Docker Desktop started but daemon did not become ready: {last_error}")
        return {"started": True, "ready": False, "error": last_error}

    def trigger_compact_task(self, task_name: str = "Guardian - Docker Weekly Compact") -> Dict[str, object]:
        try:
            proc = subprocess.run(
                ["schtasks", "/Run", "/TN", task_name],
                capture_output=True,
                text=True,
                timeout=20,
            )
            success = proc.returncode == 0
            output = (proc.stdout or proc.stderr or "").strip()
            if success:
                self.logger.info(f"Triggered scheduled task: {task_name}")
            else:
                self.logger.error(f"Failed to trigger scheduled task {task_name}: {output[:200]}")
            return {"success": success, "task_name": task_name, "details": output}
        except Exception as e:
            self.logger.error(f"Could not trigger scheduled task {task_name}: {e}")
            return {"success": False, "task_name": task_name, "details": str(e)}

    def restart_shell_processes(self) -> None:
        """Restart minimal Windows shell processes stopped for compaction."""
        try:
            subprocess.run(["cmd", "/c", "start", "explorer.exe"], capture_output=True, timeout=15)
            self.logger.info("Explorer restarted")
        except Exception as e:
            self.logger.warning(f"start explorer.exe: {e}")

    def compact_all(self, shutdown_first: bool = True) -> Dict:
        """
        Compact all found VHDs. Main entry point.

        NOTE: This requires admin rights and shuts down WSL/Docker briefly.
        """
        vhds = self.find_vhds()

        if not vhds:
            return {"status": "no_vhds_found", "results": [], "total_freed_gb": 0}

        self.logger.info(f"Found {len(vhds)} VHD(s) to compact")
        for v in vhds:
            self.logger.info(f"  {v.label}: {v.size_gb:.1f}GB — {v.path}")

        if shutdown_first:
            self.shutdown_wsl_and_docker()

        results = []
        total_freed = 0.0

        for vhd in vhds:
            r = self.compact_vhd(vhd)
            results.append(r)
            total_freed += r.freed_gb

        self.restart_shell_processes()
        docker_restart = self.restart_docker_desktop()

        return {
            "status": "complete",
            "timestamp": datetime.now().isoformat(),
            "vhds_compacted": len([r for r in results if r.success]),
            "total_freed_gb": round(total_freed, 2),
            "docker_restart": docker_restart,
            "results": [
                {
                    "label": r.label,
                    "freed_gb": round(r.freed_gb, 2),
                    "before_gb": round(r.size_before_gb, 2),
                    "after_gb": round(r.size_after_gb, 2),
                    "success": r.success,
                    "error": r.error,
                }
                for r in results
            ],
        }

    def generate_scheduled_task_ps1(self, output_path: str = None) -> str:
        """
        Generate a PowerShell script to install a weekly scheduled task
        that runs VHD compact as SYSTEM (has admin rights automatically).
        Saves Richard from ever having to run this manually again.
        """
        script = r"""
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
"""
        if output_path:
            with open(output_path, 'w') as f:
                f.write(script)
            self.logger.info(f"Scheduled task script saved to {output_path}")

        return script


def check_vhd_bloat() -> Dict:
    """Quick check: how much space could we recover from VHD compact?"""
    c = VHDCompactor()
    vhds = c.find_vhds()
    return {
        "vhds": [{"label": v.label, "size_gb": round(v.size_gb, 1), "path": v.path} for v in vhds],
        "total_gb": round(sum(v.size_gb for v in vhds), 1),
    }


if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="VHD Compactor - reclaim space from Docker/WSL VHDs")
    parser.add_argument("--check", action="store_true", help="Show VHD sizes without compacting")
    parser.add_argument("--auto", action="store_true", help="Compact all VHDs (requires admin)")
    parser.add_argument("--install-task", action="store_true", help="Install weekly scheduled task")
    args = parser.parse_args()

    compactor = VHDCompactor()

    if args.check:
        print(json.dumps(check_vhd_bloat(), indent=2))
    elif args.install_task:
        ps1_path = r"C:\Users\Richard\clawd\Guardian\install_vhd_compact_task.ps1"
        compactor.generate_scheduled_task_ps1(ps1_path)
        print(f"Run as Admin: powershell -ExecutionPolicy Bypass -File {ps1_path}")
    elif args.auto:
        result = compactor.compact_all()
        print(json.dumps(result, indent=2))
    else:
        parser.print_help()
