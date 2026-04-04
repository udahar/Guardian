#!/usr/bin/env python3
"""
Runaway Process Detector - Guardian Module

Detects AI model servers and other processes eating excessive RAM
on Admiral (Richard's laptop). Specifically built for the real pattern:
- Alfred.model serve_base.py eating 6+ GB
- ollama.exe holding loaded models in RAM
- Multiple claude.exe / codex.exe instances stacking up

Actions:
- Alert via Telegram when a process exceeds RAM threshold
- Optionally kill the process if it exceeds the hard limit
- Never kill FieldBench, Benchmark, or OllamaBot (those are legit)
"""

import logging
import time
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime

try:
    import psutil
    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


# Processes that are NEVER killed even if over threshold
PROTECTED_PROCESSES = {
    "node.exe",          # FieldBench, Alfred.js, OllamaBot
    "postgres.exe",      # PostgreSQL
    "docker.exe",
    "dockerd.exe",
    "wslhost.exe",
    "vmmemWSL",
}

# Known AI model servers that can balloon unexpectedly
AI_MODEL_SERVERS = {
    "serve_base.py",     # Alfred.model inference server
    "ollama.exe",        # Ollama (keep eye on, don't kill)
    "llama-server.exe",  # llama.cpp server
    "python.exe",        # catches serve_base.py via cmdline check
}


@dataclass
class RunawayProcess:
    pid: int
    name: str
    cmdline: str
    ram_gb: float
    ram_percent: float
    is_ai_server: bool
    is_protected: bool
    created_at: Optional[float] = None


@dataclass
class DetectionResult:
    timestamp: str
    total_ram_gb: float
    total_ram_percent: float
    runaway_processes: List[RunawayProcess] = field(default_factory=list)
    alerts_fired: List[str] = field(default_factory=list)
    killed: List[str] = field(default_factory=list)


class RunawayDetector:
    """
    Watches for processes exceeding RAM limits and alerts/acts.
    """

    def __init__(
        self,
        warn_gb: float = 2.0,     # Alert when process uses > 2 GB
        kill_gb: float = 8.0,     # Kill (non-protected) when > 8 GB
        auto_kill: bool = False,   # False = alert only, True = kill
        alert_callback=None,       # fn(process, ram_gb) for Telegram etc.
    ):
        self.warn_gb = warn_gb
        self.kill_gb = kill_gb
        self.auto_kill = auto_kill
        self.alert_callback = alert_callback
        self.logger = self._setup_logging()
        self._alerted_pids: Dict[int, float] = {}  # pid -> last alert time
        self._alert_cooldown = 300  # 5 min between same-process alerts

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("RunawayDetector")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            handler.setFormatter(logging.Formatter("%(asctime)s - %(levelname)s - %(message)s"))
            logger.addHandler(handler)
        return logger

    def _is_ai_server(self, name: str, cmdline: str) -> bool:
        name_lower = name.lower()
        cmd_lower = cmdline.lower()
        return (
            any(s in name_lower for s in ["serve_base", "llama-server"])
            or "serve_base.py" in cmd_lower
            or ("python" in name_lower and any(
                kw in cmd_lower for kw in ["serve_base", "model_server", "inference"]
            ))
        )

    def _is_protected(self, name: str) -> bool:
        return name.lower() in {p.lower() for p in PROTECTED_PROCESSES}

    def _get_cmdline(self, proc) -> str:
        try:
            return " ".join(proc.cmdline())
        except (psutil.AccessDenied, psutil.NoSuchProcess):
            return proc.name()

    def _should_alert(self, pid: int) -> bool:
        now = time.time()
        last = self._alerted_pids.get(pid, 0)
        if now - last > self._alert_cooldown:
            self._alerted_pids[pid] = now
            return True
        return False

    def scan(self) -> DetectionResult:
        """Scan all processes for RAM overuse."""
        if not PSUTIL_AVAILABLE:
            return DetectionResult(
                timestamp=datetime.now().isoformat(),
                total_ram_gb=0,
                total_ram_percent=0,
            )

        ram = psutil.virtual_memory()
        result = DetectionResult(
            timestamp=datetime.now().isoformat(),
            total_ram_gb=round(ram.used / 1e9, 2),
            total_ram_percent=ram.percent,
        )

        try:
            procs = list(psutil.process_iter(['name', 'pid', 'memory_info', 'create_time']))
        except Exception as e:
            self.logger.error(f"Process scan failed: {e}")
            return result

        for proc in procs:
            try:
                info = proc.info
                mem = info.get('memory_info')
                if not mem:
                    continue

                ram_gb = mem.rss / 1e9
                if ram_gb < self.warn_gb:
                    continue

                name = info.get('name', 'unknown')
                cmdline = self._get_cmdline(proc)
                ram_pct = (mem.rss / psutil.virtual_memory().total) * 100

                rp = RunawayProcess(
                    pid=info['pid'],
                    name=name,
                    cmdline=cmdline[:120],
                    ram_gb=round(ram_gb, 2),
                    ram_percent=round(ram_pct, 1),
                    is_ai_server=self._is_ai_server(name, cmdline),
                    is_protected=self._is_protected(name),
                    created_at=info.get('create_time'),
                )

                result.runaway_processes.append(rp)

                # Alert
                if self._should_alert(rp.pid):
                    msg = (
                        f"RUNAWAY: {rp.name} (PID {rp.pid}) using {rp.ram_gb:.1f}GB RAM "
                        f"({'AI server' if rp.is_ai_server else 'process'})"
                    )
                    self.logger.warning(msg)
                    result.alerts_fired.append(msg)

                    if self.alert_callback:
                        try:
                            self.alert_callback(rp, rp.ram_gb)
                        except Exception as e:
                            self.logger.error(f"Alert callback failed: {e}")

                # Kill if over hard limit and not protected
                if (
                    self.auto_kill
                    and ram_gb > self.kill_gb
                    and not rp.is_protected
                ):
                    try:
                        proc.kill()
                        msg = f"KILLED {rp.name} (PID {rp.pid}) — was using {rp.ram_gb:.1f}GB"
                        self.logger.warning(msg)
                        result.killed.append(msg)
                    except Exception as e:
                        self.logger.error(f"Failed to kill PID {rp.pid}: {e}")

            except (psutil.NoSuchProcess, psutil.AccessDenied):
                continue

        return result

    def get_summary(self) -> Dict:
        """Quick summary for health reports."""
        result = self.scan()
        return {
            "total_ram_gb": result.total_ram_gb,
            "total_ram_percent": result.total_ram_percent,
            "runaway_count": len(result.runaway_processes),
            "runaways": [
                {
                    "name": p.name,
                    "pid": p.pid,
                    "ram_gb": p.ram_gb,
                    "is_ai": p.is_ai_server,
                    "protected": p.is_protected,
                    "cmd": p.cmdline[:80],
                }
                for p in result.runaway_processes
            ],
            "alerts": result.alerts_fired,
            "killed": result.killed,
        }


def scan_once(warn_gb: float = 2.0) -> Dict:
    """Quick one-shot scan."""
    return RunawayDetector(warn_gb=warn_gb).get_summary()


if __name__ == "__main__":
    import argparse, json

    parser = argparse.ArgumentParser(description="Runaway Process Detector")
    parser.add_argument("--warn-gb", type=float, default=2.0, help="Warn threshold in GB (default 2.0)")
    parser.add_argument("--kill-gb", type=float, default=8.0, help="Kill threshold in GB (default 8.0)")
    parser.add_argument("--auto-kill", action="store_true", help="Actually kill runaway processes")
    args = parser.parse_args()

    detector = RunawayDetector(warn_gb=args.warn_gb, kill_gb=args.kill_gb, auto_kill=args.auto_kill)
    result = detector.get_summary()
    print(json.dumps(result, indent=2))
