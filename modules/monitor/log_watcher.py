#!/usr/bin/env python3
"""
Log Watcher - Read Windows + WSL + application logs for anomalies
Guardian Module

Watches and parses logs from every layer of the stack:

Windows:
  - Event Log: System (crashes, disk errors, driver failures, BSODs)
  - Event Log: Application (service crashes, .NET errors)
  - Event Log: Security (failed logins, account lockouts)
  - WER (Windows Error Reporting) crash reports
  - PowerShell operational log
  - Task Scheduler history

WSL:
  - /var/log/syslog (OOM kills, kernel panics, disk errors)
  - /var/log/kern.log
  - dmesg (hardware errors, USB resets, disk I/O errors)
  - journalctl (service failures)

Docker:
  - Docker Desktop event log
  - Per-container tail (errors/exceptions)

Application:
  - FieldBench logs (Prime/FieldBench/logs/)
  - Benchmark logs
  - Alfred logs

Emits structured findings with severity so proactive_guardian can alert.
"""

import subprocess
import re
import logging
import os
from dataclasses import dataclass, field
from typing import List, Dict, Optional, Pattern
from datetime import datetime, timedelta
from pathlib import Path
import json


logger = logging.getLogger("LogWatcher")

USER_HOME  = Path(os.environ.get("USERPROFILE", r"C:\Users\Richard"))
CLAWD      = Path(r"C:\Users\Richard\clawd")
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", USER_HOME / "AppData" / "Local"))


@dataclass
class LogEvent:
    source: str         # "windows_system", "wsl_syslog", "fieldbench", etc.
    severity: str       # "critical", "error", "warning", "info"
    message: str
    timestamp: Optional[str] = None
    raw: str = ""


@dataclass
class LogReport:
    timestamp: datetime
    events: List[LogEvent] = field(default_factory=list)
    critical_count: int = 0
    error_count: int = 0
    warning_count: int = 0
    sources_checked: List[str] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)  # watcher errors


# ── Severity keyword patterns ─────────────────────────────────────────────────

CRITICAL_PATTERNS = [
    r"BSOD|blue.?screen|STOP.*0x",
    r"kernel.panic",
    r"oom.kill|out.of.memory",
    r"disk.failure|SMART.*error|I/O.error|bad.sector",
    r"CRITICAL|FATAL",
    r"unexpected.shutdown|system.crash",
    r"hardware.error|NMI|machine.check",
    r"ntfs.*corrupt|filesystem.*corrupt|chkdsk",
]

ERROR_PATTERNS = [
    r"\bERROR\b|\bException\b|\bTraceback\b",
    r"failed.to.start|service.*failed|crash",
    r"connection.refused|ECONNREFUSED",
    r"database.*error|postgres.*error",
    r"permission.denied|access.denied",
    r"out.of.*space|no.space.left",
    r"timeout|timed.out",
    r"certificate.*expired|TLS.*error",
]

WARNING_PATTERNS = [
    r"\bWARN\b|\bWARNING\b",
    r"high.memory|memory.pressure",
    r"slow.query|long.running",
    r"retry|reconnect",
    r"deprecated",
]

_critical_re = re.compile("|".join(CRITICAL_PATTERNS), re.IGNORECASE)
_error_re    = re.compile("|".join(ERROR_PATTERNS),    re.IGNORECASE)
_warning_re  = re.compile("|".join(WARNING_PATTERNS),  re.IGNORECASE)


def _classify(text: str) -> str:
    if _critical_re.search(text):
        return "critical"
    if _error_re.search(text):
        return "error"
    if _warning_re.search(text):
        return "warning"
    return "info"


def _run_ps(cmd: str, timeout: int = 20) -> str:
    try:
        kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            **kwargs,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _run_wsl(cmd: str, timeout: int = 15) -> str:
    try:
        kwargs = {
            "capture_output": True,
            "text": True,
            "timeout": timeout,
        }
        if os.name == "nt":
            kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        r = subprocess.run(
            ["wsl", "-e", "bash", "-c", cmd],
            **kwargs,
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _tail_file(path: Path, lines: int = 200) -> str:
    try:
        if not path.exists():
            return ""
        with open(path, "r", errors="replace") as f:
            all_lines = f.readlines()
        return "".join(all_lines[-lines:])
    except Exception:
        return ""


# ── Windows Event Log ────────────────────────────────────────────────────────

def read_windows_event_log(log: str, hours: int = 24,
                            level: int = 2, max_events: int = 50) -> List[LogEvent]:
    """
    level: 1=Critical, 2=Error, 3=Warning
    Returns structured events.
    """
    events = []
    since = (datetime.now() - timedelta(hours=hours)).strftime("%Y-%m-%d %H:%M:%S")

    cmd = (
        f"Get-WinEvent -LogName '{log}' -MaxEvents {max_events} "
        f"-FilterHashtable @{{LogName='{log}'; Level=1,2,3; "
        f"StartTime='{since}'}} -ErrorAction SilentlyContinue "
        f"| Select-Object TimeCreated,LevelDisplayName,Message "
        f"| ConvertTo-Json -Compress -Depth 2"
    )
    out = _run_ps(cmd, timeout=30)
    if not out:
        return events

    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        for item in data:
            msg = str(item.get("Message", ""))[:300]
            ts  = str(item.get("TimeCreated", ""))[:19]
            lvl = str(item.get("LevelDisplayName", "")).lower()
            if "critical" in lvl:
                sev = "critical"
            elif "error" in lvl:
                sev = "error"
            else:
                sev = "warning"
            events.append(LogEvent(
                source=f"windows_{log.lower().replace(' ', '_')}",
                severity=sev,
                message=msg.replace("\n", " ").replace("\r", ""),
                timestamp=ts,
                raw=msg,
            ))
    except Exception as e:
        logger.debug(f"Event log parse error ({log}): {e}")

    return events


# ── WSL logs ─────────────────────────────────────────────────────────────────

def read_wsl_syslog(lines: int = 300) -> List[LogEvent]:
    events = []

    # Try journalctl first (systemd distros), fall back to /var/log/syslog
    out = _run_wsl(
        "journalctl -n 300 -p warning --no-pager --output short-iso 2>/dev/null "
        "|| tail -n 300 /var/log/syslog 2>/dev/null "
        "|| tail -n 300 /var/log/messages 2>/dev/null",
        timeout=20
    )
    if not out:
        return events

    for line in out.splitlines():
        if not line.strip():
            continue
        sev = _classify(line)
        if sev in ("critical", "error", "warning"):
            events.append(LogEvent(
                source="wsl_syslog",
                severity=sev,
                message=line[:250],
                raw=line,
            ))

    return events


def read_wsl_dmesg(lines: int = 100) -> List[LogEvent]:
    events = []
    out = _run_wsl(
        "dmesg --level=err,crit,emerg 2>/dev/null | tail -n 100",
        timeout=10
    )
    for line in (out or "").splitlines():
        if not line.strip():
            continue
        sev = _classify(line)
        events.append(LogEvent(
            source="wsl_dmesg",
            severity=sev if sev != "info" else "error",
            message=line[:250],
            raw=line,
        ))
    return events


def read_wsl_docker_logs() -> List[LogEvent]:
    """Check running container logs for recent errors."""
    events = []
    try:
        r = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}"],
            capture_output=True, text=True, timeout=5,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
        )
        if r.returncode != 0:
            return events

        containers = [c.strip() for c in r.stdout.strip().splitlines() if c.strip()]
        for name in containers[:8]:  # cap to avoid slowness
            r2 = subprocess.run(
                ["docker", "logs", "--tail", "50", "--since", "1h", name],
                capture_output=True, text=True, timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0,
            )
            log_text = (r2.stdout + r2.stderr)
            for line in log_text.splitlines():
                sev = _classify(line)
                if sev in ("critical", "error"):
                    events.append(LogEvent(
                        source=f"docker/{name}",
                        severity=sev,
                        message=line[:200],
                        raw=line,
                    ))
    except Exception:
        pass
    return events


# ── Application logs ──────────────────────────────────────────────────────────

def read_app_log(path: Path, source_name: str, lines: int = 200) -> List[LogEvent]:
    events = []
    content = _tail_file(path, lines)
    for line in content.splitlines():
        sev = _classify(line)
        if sev in ("critical", "error", "warning"):
            events.append(LogEvent(
                source=source_name,
                severity=sev,
                message=line.strip()[:250],
                raw=line,
            ))
    return events


def read_app_logs() -> List[LogEvent]:
    events = []

    log_paths = [
        (CLAWD / "Prime" / "FieldBench" / "logs" / "app.log",    "fieldbench"),
        (CLAWD / "Prime" / "FieldBench" / "logs" / "error.log",  "fieldbench_error"),
        (CLAWD / "Benchmark" / "logs" / "app.log",               "benchmark"),
        (CLAWD / "Prime" / "Alfred.py" / "logs" / "alfred.log",  "alfred_py"),
        (CLAWD / "Prime" / "Alfred.js" / "logs" / "server.log",  "alfred_js"),
        (USER_HOME / "clawd" / "services" / "logs" / "vendor.log", "vendor_proxy"),
    ]

    for path, name in log_paths:
        if path.exists():
            events.extend(read_app_log(path, name))

    return events


# ── WER crash reports ─────────────────────────────────────────────────────────

def read_wer_crashes(max_age_days: int = 7) -> List[LogEvent]:
    events = []
    wer_dir = LOCAL_APPDATA / "Microsoft" / "Windows" / "WER" / "ReportArchive"
    if not wer_dir.exists():
        return events

    cutoff = datetime.now() - timedelta(days=max_age_days)
    for report_dir in sorted(wer_dir.iterdir(), reverse=True)[:20]:
        if not report_dir.is_dir():
            continue
        try:
            mtime = datetime.fromtimestamp(report_dir.stat().st_mtime)
            if mtime < cutoff:
                continue
            # Read the report.wer file
            for wer_file in report_dir.glob("*.wer"):
                content = _tail_file(wer_file, 20)
                if content:
                    # Extract crash info
                    app_name = ""
                    for line in content.splitlines():
                        if line.startswith("AppName="):
                            app_name = line.split("=", 1)[1]
                    msg = f"WER crash: {app_name or report_dir.name} at {mtime.strftime('%Y-%m-%d %H:%M')}"
                    events.append(LogEvent(
                        source="wer_crashes",
                        severity="error",
                        message=msg,
                        timestamp=mtime.isoformat()[:19],
                    ))
                break
        except Exception:
            continue

    return events


# ── Task Scheduler failures ───────────────────────────────────────────────────

def read_task_scheduler_failures() -> List[LogEvent]:
    events = []
    cmd = (
        "Get-WinEvent -LogName 'Microsoft-Windows-TaskScheduler/Operational' "
        "-MaxEvents 50 "
        "-FilterHashtable @{LogName='Microsoft-Windows-TaskScheduler/Operational'; Level=2,3} "
        "-ErrorAction SilentlyContinue "
        "| Select-Object TimeCreated,Message "
        "| ConvertTo-Json -Compress -Depth 2"
    )
    out = _run_ps(cmd, timeout=20)
    if not out:
        return events
    try:
        data = json.loads(out)
        if isinstance(data, dict):
            data = [data]
        for item in data[:10]:
            msg = str(item.get("Message", ""))[:200].replace("\n", " ")
            ts  = str(item.get("TimeCreated", ""))[:19]
            events.append(LogEvent(
                source="task_scheduler",
                severity="warning",
                message=msg,
                timestamp=ts,
            ))
    except Exception:
        pass
    return events


# ── Main scan ────────────────────────────────────────────────────────────────

def scan(hours: int = 24, include_docker_logs: bool = True,
         include_app_logs: bool = True) -> LogReport:
    report = LogReport(timestamp=datetime.now())

    def _collect(source: str, fn, *args, **kwargs):
        report.sources_checked.append(source)
        try:
            evts = fn(*args, **kwargs)
            report.events.extend(evts)
        except Exception as e:
            report.errors.append(f"{source}: {e}")

    _collect("windows_system",     read_windows_event_log, "System",      hours=hours)
    _collect("windows_application", read_windows_event_log, "Application", hours=hours)
    _collect("windows_security",    read_windows_event_log, "Security",    hours=hours, level=4)
    _collect("wsl_syslog",          read_wsl_syslog)
    _collect("wsl_dmesg",           read_wsl_dmesg)
    _collect("wer_crashes",         read_wer_crashes)
    _collect("task_scheduler",      read_task_scheduler_failures)

    if include_docker_logs:
        _collect("docker_containers", read_wsl_docker_logs)

    if include_app_logs:
        _collect("app_logs",  read_app_logs)

    # Deduplicate near-identical messages
    seen: set = set()
    unique_events = []
    for e in report.events:
        key = (e.source, e.message[:80])
        if key not in seen:
            seen.add(key)
            unique_events.append(e)
    report.events = unique_events

    # Counts
    report.critical_count = sum(1 for e in report.events if e.severity == "critical")
    report.error_count    = sum(1 for e in report.events if e.severity == "error")
    report.warning_count  = sum(1 for e in report.events if e.severity == "warning")

    return report


def get_summary(hours: int = 1) -> Dict:
    """Quick summary for proactive_guardian heartbeat (short window, fast)."""
    report = scan(hours=hours, include_docker_logs=False, include_app_logs=True)
    return {
        "critical": report.critical_count,
        "errors":   report.error_count,
        "warnings": report.warning_count,
        "top_critical": [
            {"source": e.source, "message": e.message[:120]}
            for e in report.events if e.severity == "critical"
        ][:5],
        "sources_checked": report.sources_checked,
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    hours = int(sys.argv[1]) if len(sys.argv) > 1 else 24
    report = scan(hours=hours)

    print(f"\nLog Watch  —  last {hours}h  —  {report.timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"  Sources: {', '.join(report.sources_checked)}")
    print(f"  Critical: {report.critical_count}  Errors: {report.error_count}  "
          f"Warnings: {report.warning_count}")

    if report.critical_count > 0:
        print("\n  CRITICAL:")
        for e in report.events:
            if e.severity == "critical":
                ts = f"[{e.timestamp}] " if e.timestamp else ""
                print(f"    [{e.source}] {ts}{e.message[:150]}")

    if report.error_count > 0:
        print(f"\n  ERRORS (top 10):")
        for e in [x for x in report.events if x.severity == "error"][:10]:
            ts = f"[{e.timestamp}] " if e.timestamp else ""
            print(f"    [{e.source}] {ts}{e.message[:150]}")

    if report.errors:
        print(f"\n  Watcher errors: {report.errors}")
