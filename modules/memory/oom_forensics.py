#!/usr/bin/env python3
"""
OOM Forensics & Process Leak Detector
PromptOS Module

Tracks OOM kills and file descriptor leaks:
- Scans WSL syslog for OOM events
- Tracks process file descriptors
- Detects handle leaks
- Logs to PostgreSQL
"""

import subprocess
import logging
from dataclasses import dataclass
from typing import List, Dict, Optional
from datetime import datetime, timedelta


class OOMForensics:
    """Monitor OOM kills in WSL."""

    def __init__(self, distro: str = "Ubuntu"):
        self.distro = distro
        self.logger = self._setup_logging()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("OOMForensics")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_wsl(self, cmd: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["wsl", "-d", self.distro, "sh", "-c", cmd],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def scan_oom_events(self, hours: int = 24) -> List[Dict]:
        """Scan for OOM kill events."""
        events = []

        # Check dmesg for OOM
        success, output = self._run_wsl(f"dmesg | grep -i 'oom|kill|memory' | tail -50")

        if success and output.strip():
            for line in output.strip().split("\n"):
                if "oom" in line.lower() or "kill" in line.lower():
                    events.append(
                        {
                            "source": "dmesg",
                            "message": line[:200],
                            "timestamp": datetime.now().isoformat(),
                        }
                    )

        # Check syslog
        success, output = self._run_wsl(
            f"journalctl -k --since '{hours} hours ago' | grep -i oom | tail -20"
        )

        if success and output.strip():
            for line in output.strip().split("\n"):
                events.append(
                    {
                        "source": "journalctl",
                        "message": line[:200],
                        "timestamp": datetime.now().isoformat(),
                    }
                )

        return events

    def get_memory_pressure(self) -> Dict:
        """Check current memory pressure."""
        success, output = self._run_wsl(
            "cat /proc/meminfo | grep -E 'MemFree|MemAvailable|Cached|Buffers'"
        )

        if not success:
            return {"error": "Unable to read meminfo"}

        data = {}
        for line in output.strip().split("\n"):
            parts = line.split(":")
            if len(parts) == 2:
                key = parts[0].strip()
                val = int(parts[1].strip().split()[0])
                data[key] = val  # in KB

        mem_available = data.get("MemAvailable", data.get("MemFree", 0))
        mem_total = data.get("MemTotal", 1)

        return {
            "mem_available_kb": mem_available,
            "mem_total_kb": mem_total,
            "pressure_percent": ((mem_total - mem_available) / mem_total) * 100,
            "oom_risk": mem_available < (mem_total * 0.1),  # Less than 10% available
        }


class ProcessLeakDetector:
    """Track file descriptor and handle leaks."""

    def __init__(self, distro: str = "Ubuntu"):
        self.distro = distro
        self.logger = self._setup_logging()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("LeakDetector")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_wsl(self, cmd: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["wsl", "-d", self.distro, "sh", "-c", cmd],
                capture_output=True,
                text=True,
                timeout=30,
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def get_fd_usage(self, limit: int = 20) -> List[Dict]:
        """Get processes with most open file descriptors."""
        success, output = self._run_wsl(
            f"lsof +D / 2>/dev/null | awk '{{print $2}}' | sort | uniq -c | sort -rn | head -{limit}"
        )

        if not success:
            return []

        results = []
        for line in output.strip().split("\n")[:limit]:
            parts = line.strip().split()
            if len(parts) >= 2:
                try:
                    results.append({"fd_count": int(parts[0]), "pid": parts[1]})
                except:
                    pass

        # Get process names
        for r in results[:10]:
            pid = r["pid"]
            success, output = self._run_wsl(f"ps -p {pid} -o comm=")
            if success:
                r["process"] = output.strip()

        return results

    def check_fd_leaks(self, threshold: int = 1000) -> List[Dict]:
        """Find processes with suspicious FD counts."""
        fd_usage = self.get_fd_usage(50)

        leaks = []
        for proc in fd_usage:
            if proc.get("fd_count", 0) > threshold:
                leaks.append(
                    {
                        "pid": proc.get("pid"),
                        "process": proc.get("process", "unknown"),
                        "fd_count": proc.get("fd_count"),
                        "severity": "high"
                        if proc.get("fd_count", 0) > 5000
                        else "medium",
                    }
                )

        return leaks


def run_oom_forensics() -> Dict:
    """Quick OOM check."""
    forensics = OOMForensics()
    return {
        "oom_events": forensics.scan_oom_events(24),
        "memory_pressure": forensics.get_memory_pressure(),
    }


def run_fd_check() -> Dict:
    """Quick FD leak check."""
    detector = ProcessLeakDetector()
    return {
        "fd_leaks": detector.check_fd_leaks(),
        "top_fd_usage": detector.get_fd_usage(10),
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="OOM & Leak Detection")
    parser.add_argument("--oom", action="store_true", help="Check OOM")
    parser.add_argument("--fd", action="store_true", help="Check FD leaks")

    args = parser.parse_args()

    if args.oom:
        print(json.dumps(run_oom_forensics(), indent=2, default=str))
    elif args.fd:
        print(json.dumps(run_fd_check(), indent=2, default=str))
    else:
        print(
            json.dumps(
                {"oom": run_oom_forensics(), "leaks": run_fd_check()},
                indent=2,
                default=str,
            )
        )
