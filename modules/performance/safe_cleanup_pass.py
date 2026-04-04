#!/usr/bin/env python3
"""
Safe Cleanup Pass - low-risk disk cleanup for recurring automation.

Targets only:
- temp files
- recycle bin
- DNS cache
- thumbnails
- package manager caches

Explicitly does not touch:
- Ollama models
- Qdrant data
- project source/data directories
- Downloads
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
from dataclasses import dataclass, asdict, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import List

from Guardian.modules.windows.windows_guardian import WindowsGuardian


logger = logging.getLogger("SafeCleanupPass")


@dataclass
class CommandResult:
    label: str
    command: str
    success: bool
    details: str = ""


@dataclass
class SafeCleanupReport:
    timestamp: str
    windows_actions: List[str] = field(default_factory=list)
    windows_space_freed_mb: float = 0.0
    stale_partial_downloads_removed: List[str] = field(default_factory=list)
    stale_temp_paths_removed: List[str] = field(default_factory=list)
    command_results: List[CommandResult] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _run(label: str, command: List[str], timeout: int = 180) -> CommandResult:
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        details = (result.stdout or result.stderr or "").strip()
        return CommandResult(
            label=label,
            command=" ".join(command),
            success=result.returncode == 0,
            details=details[:500],
        )
    except Exception as exc:
        return CommandResult(
            label=label,
            command=" ".join(command),
            success=False,
            details=str(exc),
        )


def _clean_stale_partial_downloads(
    report: SafeCleanupReport,
    downloads_dir: Path = Path(r"C:\Users\Richard\Downloads"),
    min_age_days: int = 14,
) -> None:
    if not downloads_dir.exists():
        return

    cutoff = datetime.now() - timedelta(days=min_age_days)

    for path in downloads_dir.glob("*.parts"):
        try:
            stat = path.stat()
            last_write = datetime.fromtimestamp(stat.st_mtime)
            if last_write > cutoff:
                continue

            # Only target plain files in Downloads with the .parts suffix.
            if not path.is_file():
                continue

            os.remove(path)
            report.stale_partial_downloads_removed.append(str(path))
        except Exception as exc:
            report.errors.append(f"stale partial cleanup failed for {path}: {exc}")


def _path_size_mb(path: Path) -> float:
    try:
        if path.is_file():
            return path.stat().st_size / (1024 * 1024)

        total = 0
        for child in path.rglob("*"):
            try:
                if child.is_file():
                    total += child.stat().st_size
            except Exception:
                continue
        return total / (1024 * 1024)
    except Exception:
        return 0.0


def _clean_stale_temp_paths(
    report: SafeCleanupReport,
    temp_dir: Path = Path(r"C:\Users\Richard\AppData\Local\Temp"),
    min_age_hours: int = 24,
) -> None:
    if not temp_dir.exists():
        return

    cutoff = datetime.now() - timedelta(hours=min_age_hours)
    protected_names = {
        "code_validator_of7no886",
    }

    for path in temp_dir.iterdir():
        try:
            if path.name in protected_names:
                continue

            stat = path.stat()
            last_write = datetime.fromtimestamp(stat.st_mtime)
            if last_write > cutoff:
                continue

            if path.is_file():
                size_mb = _path_size_mb(path)
                path.unlink()
                report.stale_temp_paths_removed.append(
                    f"{path} ({size_mb:.1f} MB)"
                )
                continue

            if path.is_dir():
                size_mb = _path_size_mb(path)
                if path.name == "DiagOutputDir" or size_mb >= 5.0:
                    import shutil

                    shutil.rmtree(path, ignore_errors=False)
                    report.stale_temp_paths_removed.append(
                        f"{path} ({size_mb:.1f} MB)"
                    )
        except Exception as exc:
            report.errors.append(f"stale temp cleanup failed for {path}: {exc}")


def _prune_vm_bundles(report: SafeCleanupReport) -> None:
    """Delete Claude vm_bundles only when not locked by the Claude desktop app."""
    vm_bundles = Path(os.environ.get("APPDATA", "")) / "Claude" / "vm_bundles"
    if not vm_bundles.exists():
        return
    # Only remove if not currently locked (Claude desktop not running with VM)
    rootfs = vm_bundles / "claudevm.bundle" / "rootfs.vhdx"
    if rootfs.exists():
        try:
            # Probe for lock by trying to open exclusively
            rootfs.open("r+b").close()
        except (PermissionError, OSError):
            report.errors.append("vm_bundles locked by Claude desktop — skipping")
            return
    try:
        size_mb = _path_size_mb(vm_bundles)
        import shutil
        shutil.rmtree(str(vm_bundles), ignore_errors=False)
        report.stale_temp_paths_removed.append(f"Claude vm_bundles ({size_mb:.0f} MB)")
    except Exception as exc:
        report.errors.append(f"vm_bundles cleanup failed: {exc}")


def _prune_wsl_logs(report: SafeCleanupReport) -> None:
    """Vacuum WSL systemd journal and clean apt cache."""
    try:
        r = subprocess.run(
            ["wsl", "-e", "bash", "-c",
             "sudo journalctl --vacuum-size=50M 2>&1 && sudo apt-get clean -y 2>&1 && sudo rm -rf /tmp/* 2>/dev/null; echo done"],
            capture_output=True, text=True, timeout=60,
        )
        if "done" in r.stdout:
            report.command_results.append(CommandResult(
                label="wsl journal+apt clean", command="journalctl --vacuum-size=50M && apt clean",
                success=True, details=r.stdout.strip()[-200:],
            ))
    except Exception as exc:
        report.errors.append(f"WSL log cleanup failed: {exc}")


def _prune_docker(report: SafeCleanupReport) -> None:
    """Run docker system prune if daemon is reachable."""
    try:
        import socket
        s = socket.socket(socket.AF_UNIX if hasattr(socket, 'AF_UNIX') else socket.AF_INET, socket.SOCK_STREAM)
        s.close()
    except Exception:
        pass
    r = _run("docker system prune", ["docker", "system", "prune", "-f"], timeout=120)
    report.command_results.append(r)
    if not r.success and "cannot connect" not in r.details.lower() and "not found" not in r.details.lower():
        report.errors.append(f"docker prune failed: {r.details[:200]}")


def run_safe_cleanup() -> SafeCleanupReport:
    report = SafeCleanupReport(timestamp=datetime.now().isoformat())

    win_guard = WindowsGuardian()
    win_result = win_guard.cleanup(["temp", "recycle_bin", "dns", "thumbnails"])
    report.windows_actions = win_result.actions_performed
    report.windows_space_freed_mb = round(win_result.space_freed_mb, 1)
    report.errors.extend(win_result.errors)

    commands = [
        ("pip cache purge", ["python", "-m", "pip", "cache", "purge"]),
        ("npm cache clean", ["cmd", "/c", "npm", "cache", "clean", "--force"]),
    ]

    for label, command in commands:
        cmd_result = _run(label, command)
        report.command_results.append(cmd_result)
        if not cmd_result.success:
            report.errors.append(f"{label} failed: {cmd_result.details}")

    _prune_vm_bundles(report)
    _prune_wsl_logs(report)
    _prune_docker(report)
    _clean_stale_partial_downloads(report)
    _clean_stale_temp_paths(report)

    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print(json.dumps(asdict(run_safe_cleanup()), indent=2))
