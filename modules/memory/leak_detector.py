#!/usr/bin/env python3
"""
Leak Detector - Memory & Resource Leak Detection
PromptOS Module

Detects memory and resource leaks in running processes:
- Tracks process memory over time
- Detects abnormal memory growth
- Monitors I/O patterns for SSD wear
- Flags processes using excessive resources
- Monitors Ollama instances specifically

Features:
- Process memory baseline tracking
- Growth rate analysis
- Suspicious process detection
- Ollama instance monitoring
- Resource leak alerts
"""

import time
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime
from collections import defaultdict


try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


@dataclass
class ProcessSnapshot:
    pid: int
    name: str
    cpu_percent: float
    memory_mb: float
    memory_percent: float
    io_read_mb: float
    io_write_mb: float
    threads: int
    timestamp: datetime


@dataclass
class LeakDetection:
    process_name: str
    pid: int
    leak_type: str  # "memory", "io", "cpu"
    severity: str  # "low", "medium", "high", "critical"
    description: str
    current_value: float
    baseline_value: float
    growth_rate: float
    recommendation: str


@dataclass
class OllamaStatus:
    instances: int
    total_memory_mb: float
    processes: List[Dict]
    recommendations: List[str]


class LeakDetector:
    def __init__(self):
        self.logger = self._setup_logging()
        self._process_history: Dict[int, List[ProcessSnapshot]] = defaultdict(list)
        self._baseline_memory: Dict[int, float] = {}
        self._history_duration = 300  # 5 minutes of history
        self._sample_interval = 30  # Sample every 30 seconds

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("LeakDetector")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def take_process_snapshot(self) -> List[ProcessSnapshot]:
        """Take snapshot of all processes."""
        if not PSUTIL_AVAILABLE:
            return []

        snapshots = []

        try:
            for proc in psutil.process_iter(
                [
                    "pid",
                    "name",
                    "cpu_percent",
                    "memory_info",
                    "memory_percent",
                    "num_threads",
                    "io_counters",
                ]
            ):
                try:
                    pinfo = proc.info
                    mem_info = pinfo["memory_info"]
                    io = pinfo["io_counters"]

                    snapshot = ProcessSnapshot(
                        pid=pinfo["pid"],
                        name=pinfo["name"],
                        cpu_percent=pinfo["cpu_percent"] or 0,
                        memory_mb=mem_info.rss / (1024 * 1024),
                        memory_percent=pinfo["memory_percent"] or 0,
                        io_read_mb=(io.read_bytes / (1024 * 1024)) if io else 0,
                        io_write_mb=(io.write_bytes / (1024 * 1024)) if io else 0,
                        threads=pinfo["num_threads"],
                        timestamp=datetime.now(),
                    )
                    snapshots.append(snapshot)

                    # Store in history
                    self._process_history[pinfo["pid"]].append(snapshot)

                    # Initialize baseline if not exists
                    if pinfo["pid"] not in self._baseline_memory:
                        self._baseline_memory[pinfo["pid"]] = snapshot.memory_mb

                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        except Exception as e:
            self.logger.error(f"Error taking snapshot: {e}")

        # Clean old history
        self._cleanup_history()

        return snapshots

    def _cleanup_history(self):
        """Remove old snapshots from history."""
        cutoff = datetime.now().timestamp() - self._history_duration
        for pid in list(self._process_history.keys()):
            self._process_history[pid] = [
                s
                for s in self._process_history[pid]
                if s.timestamp.timestamp() > cutoff
            ]
            if not self._process_history[pid]:
                del self._process_history[pid]

    def detect_memory_leaks(self, min_memory_mb: float = 500) -> List[LeakDetection]:
        """Detect processes with memory leaks."""
        leaks = []

        for pid, history in self._process_history.items():
            if len(history) < 3:
                continue

            # Get baseline and current
            baseline = self._baseline_memory.get(pid, history[0].memory_mb)
            current = history[-1].memory_mb
            first = history[0].memory_mb

            # Calculate growth
            growth_mb = current - first
            growth_percent = (growth_mb / baseline * 100) if baseline > 0 else 0

            # Skip small processes
            if current < min_memory_mb:
                continue

            process_name = history[-1].name

            # Determine severity
            severity = "low"
            if growth_percent > 100 or growth_mb > 2000:
                severity = "critical"
            elif growth_percent > 50 or growth_mb > 1000:
                severity = "high"
            elif growth_percent > 25 or growth_mb > 500:
                severity = "medium"

            # Only flag if significant growth
            if growth_percent > 20 and growth_mb > 200:
                recommendation = self._get_memory_recommendation(process_name, severity)

                leaks.append(
                    LeakDetection(
                        process_name=process_name,
                        pid=pid,
                        leak_type="memory",
                        severity=severity,
                        description=f"Memory grew from {first:.0f}MB to {current:.0f}MB ({growth_percent:.1f}% increase)",
                        current_value=current,
                        baseline_value=baseline,
                        growth_rate=growth_mb / (len(history) * 30),  # MB per sample
                        recommendation=recommendation,
                    )
                )

        return sorted(leaks, key=lambda x: x.growth_rate, reverse=True)

    def detect_io_leaks(self, min_write_mb: float = 1000) -> List[LeakDetection]:
        """Detect processes with excessive I/O (potential SSD wear)."""
        leaks = []

        for pid, history in self._process_history.items():
            if len(history) < 3:
                continue

            total_write = 0
            total_read = 0
            for i in range(1, len(history)):
                delta_write = history[i].io_write_mb - history[i - 1].io_write_mb
                delta_read = history[i].io_read_mb - history[i - 1].io_read_mb
                total_write += max(0, delta_write)
                total_read += max(0, delta_read)

            if total_write < min_write_mb:
                continue

            process_name = history[-1].name

            severity = "low"
            if total_write > 10000:
                severity = "critical"
            elif total_write > 5000:
                severity = "high"
            elif total_write > 2000:
                severity = "medium"

            leaks.append(
                LeakDetection(
                    process_name=process_name,
                    pid=pid,
                    leak_type="io",
                    severity=severity,
                    description=f"Wrote {total_write:.0f}MB, Read {total_read:.0f}MB in {len(history) * 30}s",
                    current_value=total_write,
                    baseline_value=0,
                    growth_rate=total_write / (len(history) * 30),
                    recommendation=f"Consider limiting {process_name} I/O or moving to RAM disk",
                )
            )

        return sorted(leaks, key=lambda x: x.current_value, reverse=True)

    def detect_ollama_instances(self) -> OllamaStatus:
        """Detect and analyze Ollama instances in Windows and WSL."""
        if not PSUTIL_AVAILABLE:
            return OllamaStatus(0, 0, [], [])

        ollama_procs = []
        total_memory = 0

        # Check Windows processes
        for proc in psutil.process_iter(["name", "pid", "memory_info"]):
            try:
                if "ollama" in proc.name().lower():
                    mem_mb = proc.memory_info().rss / (1024 * 1024)
                    total_memory += mem_mb
                    ollama_procs.append(
                        {
                            "source": "windows",
                            "pid": proc.pid,
                            "name": proc.name(),
                            "memory_mb": mem_mb,
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        # Check WSL for Ollama (via wslmanager)
        try:
            from Guardian.wsl_manager import WSLManager

            wsl_manager = WSLManager()
            wsl_ollama = wsl_manager.get_ollama_in_wsl()
            for o in wsl_ollama:
                # Try to get memory for WSL process
                total_memory += 2048  # Estimate 2GB per WSL Ollama
                o["source"] = "wsl"
                o["memory_mb"] = 2048
                ollama_procs.append(o)
        except Exception:
            pass

        recommendations = []

        if len(ollama_procs) > 2:
            recommendations.append(
                f"Running {len(ollama_procs)} Ollama instances - consider reducing to 2"
            )
        elif len(ollama_procs) == 0:
            recommendations.append("No Ollama instances detected")

        if total_memory > 8000:
            recommendations.append(
                f"Ollama using {total_memory:.0f}MB - ensure OLLAMA_KEEP_ALIVE is set"
            )

        return OllamaStatus(
            instances=len(ollama_procs),
            total_memory_mb=total_memory,
            processes=ollama_procs,
            recommendations=recommendations,
        )

    def detect_high_cpu_processes(self, threshold: float = 50.0) -> List[Dict]:
        """Detect processes with high CPU usage."""
        high_cpu = []

        for proc in psutil.process_iter(
            ["name", "pid", "cpu_percent", "memory_percent"]
        ):
            try:
                cpu = proc.cpu_percent()
                if cpu > threshold:
                    high_cpu.append(
                        {
                            "name": proc.info["name"],
                            "pid": proc.info["pid"],
                            "cpu": cpu,
                            "memory_percent": proc.info["memory_percent"] or 0,
                        }
                    )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        return sorted(high_cpu, key=lambda x: x["cpu"], reverse=True)[:10]

    def _get_memory_recommendation(self, process_name: str, severity: str) -> str:
        """Get recommendation based on process name."""
        name_lower = process_name.lower()

        if "ollama" in name_lower:
            return "Set OLLAMA_KEEP_ALIVE=5m to free memory when idle"
        elif "chrome" in name_lower or "edge" in name_lower:
            return "Close unused tabs or restart browser"
        elif "code" in name_lower or "cursor" in name_lower:
            return "Restart IDE or disable extensions"
        elif "vmmem" in name_lower:
            return "Run WSL memory reclaim: echo 3 > /proc/sys/vm/drop_caches"
        elif severity in ["critical", "high"]:
            return f"CRITICAL: {process_name} may be leaking - consider terminating"
        else:
            return f"Monitor {process_name} - may need restart"

    def get_full_report(self) -> dict:
        """Get comprehensive leak detection report."""
        self.take_process_snapshot()

        memory_leaks = self.detect_memory_leaks()
        io_leaks = self.detect_io_leaks()
        ollama = self.detect_ollama_instances()
        high_cpu = self.detect_high_cpu_processes()

        return {
            "timestamp": datetime.now().isoformat(),
            "memory_leaks": [
                {
                    "name": l.process_name,
                    "pid": l.pid,
                    "severity": l.severity,
                    "description": l.description,
                    "growth_rate_mb_per_min": round(l.growth_rate * 2, 1),
                    "recommendation": l.recommendation,
                }
                for l in memory_leaks[:10]
            ],
            "io_leaks": [
                {
                    "name": l.process_name,
                    "severity": l.severity,
                    "total_write_mb": round(l.current_value, 1),
                    "recommendation": l.recommendation,
                }
                for l in io_leaks[:10]
            ],
            "ollama": {
                "instances": ollama.instances,
                "total_memory_mb": round(ollama.total_memory_mb, 1),
                "recommendations": ollama.recommendations,
            },
            "high_cpu": high_cpu[:10],
            "summary": {
                "total_memory_leaks": len(memory_leaks),
                "total_io_leaks": len(io_leaks),
                "critical_count": sum(
                    1 for l in memory_leaks if l.severity == "critical"
                ),
                "high_count": sum(
                    1 for l in memory_leaks if l.severity in ["critical", "high"]
                ),
            },
        }


def detect_leaks() -> dict:
    """Quick leak detection."""
    detector = LeakDetector()
    return detector.get_full_report()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Leak Detector")
    parser.add_argument("--report", action="store_true", help="Full leak report")

    args = parser.parse_args()

    detector = LeakDetector()

    if args.report:
        import json

        print(json.dumps(detector.get_full_report(), indent=2, default=str))
    else:
        # Quick check
        snapshot = detector.take_process_snapshot()
        print(f"Tracked {len(snapshot)} processes")

        ollama = detector.detect_ollama_instances()
        print(
            f"Ollama instances: {ollama.instances}, Memory: {ollama.total_memory_mb:.0f}MB"
        )
