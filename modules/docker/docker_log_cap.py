#!/usr/bin/env python3
"""
Docker Log Cap - Enforce container log size limits and enforce daemon.json config
Guardian Module

Docker container logs grow unbounded by default inside the VHD.
This module:
1. Checks/sets daemon.json log rotation (max-size, max-file)
2. Scans current container log files for size
3. Alerts when any single container log is bloated
4. Can truncate oversized logs (with flag)

The daemon.json change requires Docker restart to take effect for NEW containers.
Existing containers are not affected until restarted.
"""

import json
import subprocess
import logging
import os
from dataclasses import dataclass, field
from typing import List, Optional, Dict
from datetime import datetime
from pathlib import Path


logger = logging.getLogger("DockerLogCap")

DAEMON_JSON_PATH = Path(os.environ.get("PROGRAMDATA", r"C:\ProgramData")) / "Docker" / "config" / "daemon.json"

DESIRED_LOG_CONFIG = {
    "log-driver": "json-file",
    "log-opts": {
        "max-size": "50m",
        "max-file": "3",
    }
}

# Container log files live here inside WSL2 docker-desktop
# We access them via Docker API, not filesystem
CONTAINER_LOG_WARN_MB = 200


@dataclass
class ContainerLogInfo:
    container_id: str
    name: str
    log_size_mb: float
    status: str


@dataclass
class LogCapReport:
    timestamp: datetime
    daemon_json_ok: bool = False
    daemon_json_path: str = ""
    daemon_json_changed: bool = False
    container_logs: List[ContainerLogInfo] = field(default_factory=list)
    oversized: List[ContainerLogInfo] = field(default_factory=list)
    alerts: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)


def _run(cmd: list, timeout: int = 15) -> tuple[bool, str, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
    except FileNotFoundError:
        return False, "", "docker not found"
    except Exception as e:
        return False, "", str(e)


def _is_docker_running() -> bool:
    ok, _, _ = _run(["docker", "info"], timeout=5)
    return ok


def check_daemon_json(auto_fix: bool = False) -> tuple[bool, bool]:
    """
    Returns (is_ok, was_changed).
    auto_fix=True writes the config if missing or incomplete.
    """
    current = {}
    if DAEMON_JSON_PATH.exists():
        try:
            with open(DAEMON_JSON_PATH) as f:
                current = json.load(f)
        except Exception as e:
            logger.error(f"daemon.json parse error: {e}")
            return False, False

    # Check if log config is already set correctly
    existing_driver = current.get("log-driver", "")
    existing_opts   = current.get("log-opts", {})
    max_size_ok = existing_opts.get("max-size", "") == DESIRED_LOG_CONFIG["log-opts"]["max-size"]
    max_file_ok = existing_opts.get("max-file", "") == DESIRED_LOG_CONFIG["log-opts"]["max-file"]

    if existing_driver == "json-file" and max_size_ok and max_file_ok:
        return True, False

    if not auto_fix:
        return False, False

    # Merge our desired config in
    current["log-driver"] = "json-file"
    current.setdefault("log-opts", {})
    current["log-opts"]["max-size"] = DESIRED_LOG_CONFIG["log-opts"]["max-size"]
    current["log-opts"]["max-file"]  = DESIRED_LOG_CONFIG["log-opts"]["max-file"]

    try:
        DAEMON_JSON_PATH.parent.mkdir(parents=True, exist_ok=True)
        with open(DAEMON_JSON_PATH, "w") as f:
            json.dump(current, f, indent=2)
        logger.info(
            f"Updated daemon.json at {DAEMON_JSON_PATH} with log rotation config. "
            "Restart Docker Desktop for it to take effect on new containers."
        )
        return True, True
    except PermissionError:
        logger.warning(
            f"Cannot write daemon.json (need admin). "
            f"Add manually: {json.dumps(DESIRED_LOG_CONFIG, indent=2)}"
        )
        return False, False
    except Exception as e:
        logger.error(f"Failed to write daemon.json: {e}")
        return False, False


def get_container_log_sizes() -> List[ContainerLogInfo]:
    """Get log sizes by inspecting each container via docker inspect."""
    if not _is_docker_running():
        return []

    ok, out, err = _run(
        ["docker", "ps", "-a", "--format", "{{.ID}}|{{.Names}}|{{.Status}}"],
        timeout=15
    )
    if not ok or not out:
        return []

    results = []
    for line in out.splitlines():
        parts = line.split("|")
        if len(parts) < 3:
            continue
        cid, name, status = parts[0], parts[1], parts[2]

        # Get log file path via docker inspect
        ok2, inspect_out, _ = _run(
            ["docker", "inspect", "--format", "{{.LogPath}}", cid],
            timeout=5
        )
        if not ok2 or not inspect_out:
            continue

        log_path = inspect_out.strip()
        if not log_path:
            continue

        # Log path is inside WSL2 — get size via WSL
        try:
            r = subprocess.run(
                ["wsl", "-d", "docker-desktop", "--", "stat", "-c", "%s", log_path],
                capture_output=True, text=True, timeout=8
            )
            size_bytes = int(r.stdout.strip()) if r.stdout.strip().isdigit() else 0
            size_mb = size_bytes / (1024**2)
        except Exception:
            size_mb = 0.0

        results.append(ContainerLogInfo(
            container_id=cid[:12],
            name=name,
            log_size_mb=round(size_mb, 1),
            status=status,
        ))

    return results


def check(auto_fix_daemon: bool = True) -> LogCapReport:
    report = LogCapReport(
        timestamp=datetime.now(),
        daemon_json_path=str(DAEMON_JSON_PATH),
    )

    # Check/fix daemon.json
    ok, changed = check_daemon_json(auto_fix=auto_fix_daemon)
    report.daemon_json_ok = ok
    report.daemon_json_changed = changed

    if not ok and not changed:
        report.alerts.append(
            f"Docker log rotation NOT configured in daemon.json. "
            f"Container logs will grow unbounded. "
            f"Add to {DAEMON_JSON_PATH}: {json.dumps(DESIRED_LOG_CONFIG)}"
        )

    if changed:
        report.alerts.append(
            "daemon.json updated with log rotation config. "
            "Restart Docker Desktop for new containers to pick it up."
        )

    # Scan container log sizes
    if _is_docker_running():
        report.container_logs = get_container_log_sizes()
        for cl in report.container_logs:
            if cl.log_size_mb >= CONTAINER_LOG_WARN_MB:
                report.oversized.append(cl)
                report.alerts.append(
                    f"Container '{cl.name}' log is {cl.log_size_mb:.0f}MB — "
                    f"run: docker restart {cl.name}"
                )

    return report


def get_summary() -> Dict:
    report = check()
    return {
        "daemon_json_ok": report.daemon_json_ok,
        "daemon_json_changed": report.daemon_json_changed,
        "containers_checked": len(report.container_logs),
        "oversized_logs": [
            {"name": c.name, "size_mb": c.log_size_mb}
            for c in report.oversized
        ],
        "alerts": report.alerts,
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    report = check(auto_fix_daemon=True)

    print(f"\nDocker Log Cap  —  {report.timestamp.strftime('%H:%M:%S')}")
    print(f"  daemon.json: {'OK' if report.daemon_json_ok else 'MISSING/INCOMPLETE'}")
    if report.daemon_json_changed:
        print("  daemon.json UPDATED — restart Docker to apply")
    print(f"  Containers checked: {len(report.container_logs)}")
    for cl in report.container_logs:
        flag = "  <<< OVERSIZED" if cl.log_size_mb >= CONTAINER_LOG_WARN_MB else ""
        print(f"    {cl.name:<35} {cl.log_size_mb:>8.1f}MB{flag}")
    if report.alerts:
        print()
        for a in report.alerts:
            print(f"  ALERT: {a}")
