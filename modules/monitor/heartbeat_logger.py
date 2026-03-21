#!/usr/bin/env python3
"""
Heartbeat Logger - Structured JSON Logging
PromptOS Module

Structured JSON logging system for Guardian with:
- Timestamped heartbeat reports
- Structured log entries (AI-readable)
- Log rotation and retention
- Multi-source aggregation (Windows, WSL, Network)

Features:
- JSON Lines format for easy parsing
- Log levels: DEBUG, INFO, WARNING, ERROR, CRITICAL
- Automatic file rotation
- Heartbeat summarization
"""

import json
import os
import logging
import time
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime, timedelta
from enum import Enum
import threading


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class HeartbeatReport:
    timestamp: str
    source: str
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    wsl_running: bool
    wsl_memory_mb: Optional[float]
    network_healthy: bool
    active_distros: List[str] = field(default_factory=list)
    issues: List[str] = field(default_factory=list)
    actions_taken: List[str] = field(default_factory=list)


@dataclass
class LogEntry:
    timestamp: str
    level: str
    source: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)


class HeartbeatLogger:
    def __init__(self, log_dir: str = "logs", heartbeat_interval: int = 60):
        self.log_dir = log_dir
        self.heartbeat_interval = heartbeat_interval
        self.logger = self._setup_logger()
        self._ensure_log_dir()
        self._last_heartbeat = None
        self._lock = threading.Lock()

        self.heartbeat_file = os.path.join(log_dir, "heartbeat.jsonl")
        self.events_file = os.path.join(log_dir, "events.jsonl")

    def _setup_logger(self) -> logging.Logger:
        logger = logging.getLogger("Heartbeat")
        logger.setLevel(logging.INFO)
        return logger

    def _ensure_log_dir(self):
        os.makedirs(self.log_dir, exist_ok=True)

    def log_event(self, level: LogLevel, source: str, message: str, data: Dict = None):
        """Log a structured event."""
        entry = LogEntry(
            timestamp=datetime.now().isoformat(),
            level=level.value,
            source=source,
            message=message,
            data=data or {},
        )

        with self._lock:
            try:
                with open(self.events_file, "a") as f:
                    f.write(json.dumps(asdict(entry)) + "\n")
            except Exception as e:
                self.logger.error(f"Failed to log event: {e}")

        getattr(self.logger, level.value.lower())(f"[{source}] {message}")

    def log_info(self, source: str, message: str, data: Dict = None):
        self.log_event(LogLevel.INFO, source, message, data)

    def log_warning(self, source: str, message: str, data: Dict = None):
        self.log_event(LogLevel.WARNING, source, message, data)

    def log_error(self, source: str, message: str, data: Dict = None):
        self.log_event(LogLevel.ERROR, source, message, data)

    def log_critical(self, source: str, message: str, data: Dict = None):
        self.log_event(LogLevel.CRITICAL, source, message, data)

    def heartbeat(
        self,
        cpu: float,
        ram: float,
        disk: float,
        wsl_running: bool,
        wsl_memory: Optional[float],
        network_healthy: bool,
        active_distros: List[str] = None,
        issues: List[str] = None,
        actions: List[str] = None,
    ):
        """Log a heartbeat report."""
        report = HeartbeatReport(
            timestamp=datetime.now().isoformat(),
            source="guardian",
            cpu_percent=cpu,
            ram_percent=ram,
            disk_percent=disk,
            wsl_running=wsl_running,
            wsl_memory_mb=wsl_memory,
            network_healthy=network_healthy,
            active_distros=active_distros or [],
            issues=issues or [],
            actions_taken=actions or [],
        )

        with self._lock:
            try:
                with open(self.heartbeat_file, "a") as f:
                    f.write(json.dumps(asdict(report)) + "\n")
                self._last_heartbeat = report
            except Exception as e:
                self.logger.error(f"Failed to log heartbeat: {e}")

        return report

    def get_recent_heartbeats(self, minutes: int = 60) -> List[HeartbeatReport]:
        """Get heartbeats from the last N minutes."""
        heartbeats = []
        cutoff = datetime.now() - timedelta(minutes=minutes)

        if not os.path.exists(self.heartbeat_file):
            return heartbeats

        with self._lock:
            try:
                with open(self.heartbeat_file, "r") as f:
                    for line in f:
                        try:
                            data = json.loads(line)
                            ts = datetime.fromisoformat(data["timestamp"])
                            if ts > cutoff:
                                heartbeats.append(HeartbeatReport(**data))
                        except (json.JSONDecodeError, KeyError):
                            pass
            except Exception as e:
                self.logger.error(f"Failed to read heartbeats: {e}")

        return heartbeats

    def get_statistics(self, minutes: int = 60) -> Dict[str, Any]:
        """Get statistics from recent heartbeats."""
        heartbeats = self.get_recent_heartbeats(minutes)

        if not heartbeats:
            return {"error": "No data"}

        cpu_values = [h.cpu_percent for h in heartbeats]
        ram_values = [h.ram_percent for h in heartbeats]
        disk_values = [h.disk_percent for h in heartbeats]

        all_issues = []
        all_actions = []
        for h in heartbeats:
            all_issues.extend(h.issues)
            all_actions.extend(h.actions_taken)

        return {
            "period_minutes": minutes,
            "heartbeats": len(heartbeats),
            "cpu": {
                "avg": sum(cpu_values) / len(cpu_values),
                "max": max(cpu_values),
                "min": min(cpu_values),
            },
            "ram": {
                "avg": sum(ram_values) / len(ram_values),
                "max": max(ram_values),
                "min": min(ram_values),
            },
            "disk": {
                "avg": sum(disk_values) / len(disk_values),
                "max": max(disk_values),
                "min": min(disk_values),
            },
            "issues_count": len(all_issues),
            "actions_count": len(all_actions),
            "unique_issues": list(set(all_issues)),
            "unique_actions": list(set(all_actions)),
        }

    def read_logs(self, lines: int = 100, log_type: str = "events") -> List[Dict]:
        """Read recent log entries."""
        log_file = self.events_file if log_type == "events" else self.heartbeat_file

        if not os.path.exists(log_file):
            return []

        entries = []
        with self._lock:
            try:
                with open(log_file, "r") as f:
                    all_lines = f.readlines()
                    for line in all_lines[-lines:]:
                        try:
                            entries.append(json.loads(line))
                        except json.JSONDecodeError:
                            pass
            except Exception as e:
                self.logger.error(f"Failed to read logs: {e}")

        return entries

    def rotate_logs(self, max_size_mb: int = 10, max_files: int = 5):
        """Rotate log files if they exceed max size."""
        for log_file in [self.heartbeat_file, self.events_file]:
            if os.path.exists(log_file):
                size_mb = os.path.getsize(log_file) / (1024 * 1024)
                if size_mb > max_size_mb:
                    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
                    base, ext = os.path.splitext(log_file)
                    new_file = f"{base}_{timestamp}{ext}"

                    with self._lock:
                        os.rename(log_file, new_file)

                    self.logger.info(f"Rotated log to {new_file}")

        self._cleanup_old_logs(max_files)

    def _cleanup_old_logs(self, max_files: int):
        """Remove old rotated log files."""
        for log_file in [self.heartbeat_file, self.events_file]:
            base, ext = os.path.splitext(log_file)
            dir_name = os.path.dirname(log_file)

            if not dir_name:
                continue

            try:
                old_logs = sorted(
                    [
                        f
                        for f in os.listdir(dir_name)
                        if f.startswith(os.path.basename(base))
                        and f != os.path.basename(log_file)
                    ],
                    reverse=True,
                )

                for old_log in old_logs[max_files:]:
                    old_path = os.path.join(dir_name, old_log)
                    try:
                        os.remove(old_path)
                        self.logger.info(f"Removed old log: {old_log}")
                    except Exception:
                        pass
            except Exception:
                pass


def create_logger(
    log_dir: str = "logs", heartbeat_interval: int = 60
) -> HeartbeatLogger:
    """Create a heartbeat logger."""
    return HeartbeatLogger(log_dir, heartbeat_interval)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Heartbeat Logger")
    parser.add_argument("--log-dir", type=str, default="logs")
    parser.add_argument("--heartbeat", action="store_true", help="Send heartbeat")
    parser.add_argument("--stats", action="store_true", help="Get statistics")
    parser.add_argument("--read", type=int, help="Read N lines from logs")

    args = parser.parse_args()

    logger = HeartbeatLogger(args.log_dir)

    if args.heartbeat:
        report = logger.heartbeat(
            cpu=45.0,
            ram=72.0,
            disk=85.0,
            wsl_running=True,
            wsl_memory=2048.0,
            network_healthy=True,
            active_distros=["Ubuntu"],
            issues=[],
            actions=["memory_reclaim"],
        )
        print(f"Heartbeat logged: {report.timestamp}")

    elif args.stats:
        stats = logger.get_statistics(args.stats if hasattr(args, "stats") else 60)
        print(json.dumps(stats, indent=2))

    elif args.read:
        logs = logger.read_logs(args.read)
        for entry in logs:
            print(json.dumps(entry))

    else:
        print("Heartbeat Logger")
        print("Usage: python heartbeat_logger.py --heartbeat")
