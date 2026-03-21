#!/usr/bin/env python3
"""
ReclamationEngine - WSL Memory & Disk Auto-Reclamation
PromptOS Module

Automatically monitors and bridges the memory gap between Windows and WSL:
- Monitors vmmemWSL (Windows) vs free -m (Linux)
- Triggers drop_caches when memory gap > threshold
- Runs fstrim after large deletions/builds
- Tracks VHDX size vs actual Linux disk usage

Output: PostgreSQL logging via db_manager
"""

import subprocess
import time
import logging
from dataclasses import dataclass
from typing import Optional, Dict, Any
from datetime import datetime


@dataclass
class ReclaimResult:
    action: str
    success: bool
    memory_freed_mb: float
    disk_freed_mb: float
    vmmem_before_mb: float
    vmmem_after_mb: float
    linux_used_before_mb: float
    linux_used_after_mb: float


class ReclamationEngine:
    def __init__(
        self,
        distro: str = "Ubuntu",
        memory_gap_threshold_mb: float = 1536,  # 1.5GB
        idle_duration_seconds: float = 180,
        min_cpu_for_reclaim: float = 80.0,
    ):
        self.distro = distro
        self.memory_gap_threshold = memory_gap_threshold_mb
        self.idle_duration = idle_duration_seconds
        self.min_cpu_for_reclaim = min_cpu_for_reclaim
        self.logger = self._setup_logging()
        self._last_reclaim_time = 0
        self._gap_start_time = None

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("ReclamationEngine")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_wsl(self, command: str, timeout: int = 30) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["wsl", "-d", self.distro, "sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            self.logger.error(f"WSL command failed: {e}")
            return False, str(e)

    def get_vmmem_usage(self) -> Optional[float]:
        """Get vmmemWSL memory in MB from Windows side."""
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-Process vmmem -ErrorAction SilentlyContinue).WorkingSet64 / 1MB",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception as e:
            self.logger.debug(f"vmmem check failed: {e}")
        return None

    def get_linux_memory(self) -> Optional[Dict[str, float]]:
        """Get Linux memory usage in MB."""
        success, output = self._run_wsl("free -b")
        if not success:
            return None

        try:
            for line in output.split("\n"):
                if line.startswith("Mem:"):
                    parts = line.split()
                    return {
                        "total": float(parts[1]) / (1024**2),
                        "used": float(parts[2]) / (1024**2),
                        "free": float(parts[3]) / (1024**2),
                        "available": float(parts[6]) / (1024**2)
                        if len(parts) > 6
                        else float(parts[3]) / (1024**2),
                    }
        except Exception as e:
            self.logger.error(f"Linux memory parse failed: {e}")
        return None

    def get_cpu_usage(self) -> float:
        """Get current CPU usage."""
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-Counter '\\Processor(_Total)\\% Processor Time').CounterSamples.CookedValue",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                return float(result.stdout.strip())
        except Exception:
            pass
        return 0

    def get_vhdx_size(self) -> Optional[Dict[str, float]]:
        """Get VHDX virtual size vs actual usage."""
        import os
        import glob

        user = os.environ.get("USERNAME", "Unknown")
        base = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Packages",
            f"CanonicalGroupLimited.{self.distro}*",
            "LocalState",
            "ext4.vhdx",
        )

        matches = glob.glob(base)
        if not matches:
            return None

        vhdx_path = matches[0]
        virtual_size = os.path.getsize(vhdx_path) / (1024**2)  # MB

        # Get actual disk usage inside WSL
        success, output = self._run_wsl("df -B1 / | tail -1 | awk '{print $3}'")
        actual_size = 0
        if success and output.strip():
            actual_size = float(output.strip()) / (1024**2)  # MB

        return {
            "virtual_mb": virtual_size,
            "actual_mb": actual_size,
            "overhead_mb": virtual_size - actual_size,
        }

    def check_memory_gap(self) -> Dict[str, Any]:
        """Check memory gap between Windows and WSL."""
        vmmem = self.get_vmmem_usage()
        linux = self.get_linux_memory()

        if vmmem is None or linux is None:
            return {"error": "Unable to read memory stats"}

        gap_mb = vmmem - linux["used"]

        return {
            "vmmem_mb": vmmem,
            "linux_used_mb": linux["used"],
            "linux_available_mb": linux["available"],
            "gap_mb": gap_mb,
            "threshold_mb": self.memory_gap_threshold,
            "needs_reclaim": gap_mb > self.memory_gap_threshold,
            "cpu_percent": self.get_cpu_usage(),
        }

    def trigger_ram_reclaim(self) -> ReclaimResult:
        """Execute RAM reclamation (drop_caches)."""
        vmmem_before = self.get_vmmem_usage()
        linux_before = self.get_linux_memory()

        result = ReclaimResult(
            action="RAM_FLUSH",
            success=False,
            memory_freed_mb=0,
            disk_freed_mb=0,
            vmmem_before_mb=vmmem_before or 0,
            vmmem_after_mb=0,
            linux_used_before_mb=linux_before["used"] if linux_before else 0,
            linux_used_after_mb=0,
        )

        # Check CPU before reclaiming
        if result.cpu_percent > self.min_cpu_for_reclaim:
            self.logger.warning(f"CPU at {result.cpu_percent}%, skipping reclaim")
            return result

        self.logger.info("Executing drop_caches...")

        # Sync first
        self._run_wsl("sync")

        # Drop caches
        success, _ = self._run_wsl("echo 3 > /proc/sys/vm/drop_caches")

        if success:
            time.sleep(2)
            vmmem_after = self.get_vmmem_usage()
            linux_after = self.get_linux_memory()

            result.success = True
            result.vmmem_after_mb = vmmem_after or 0
            result.linux_used_after_mb = linux_after["used"] if linux_after else 0
            result.memory_freed_mb = result.vmmem_before_mb - result.vmmem_after_mb

            self._last_reclaim_time = time.time()
            self.logger.info(
                f"RAM reclaim complete: {result.memory_freed_mb:.0f}MB freed"
            )

        return result

    def trigger_disk_trim(self) -> ReclaimResult:
        """Execute fstrim to reclaim disk space."""
        vhdx_before = self.get_vhdx_size()

        result = ReclaimResult(
            action="DISK_TRIM",
            success=False,
            memory_freed_mb=0,
            disk_freed_mb=0,
            vmmem_before_mb=0,
            vmmem_after_mb=0,
            linux_used_before_mb=0,
            linux_used_after_mb=0,
        )

        if vhdx_before:
            result.vmmem_before_mb = vhdx_before["overhead_mb"]

        self.logger.info("Executing fstrim...")

        # First enable sparse if not already
        subprocess.run(
            ["wsl", "--manage", self.distro, "--set-sparse", "true"],
            capture_output=True,
            timeout=30,
        )

        # Run fstrim
        success, output = self._run_wsl("fstrim -v /")

        if success:
            vhdx_after = self.get_vhdx_size()

            result.success = True
            if vhdx_after:
                result.disk_freed_mb = (
                    vhdx_before["overhead_mb"] - vhdx_after["overhead_mb"]
                    if vhdx_before
                    else 0
                )

            self.logger.info(
                f"Disk trim complete: {result.disk_freed_mb:.0f}MB reclaimed"
            )

        return result

    def auto_reclaim(self) -> Dict[str, Any]:
        """Main auto-reclaim logic with gap tracking."""
        gap_info = self.check_memory_gap()

        if "error" in gap_info:
            return {"status": "error", "message": gap_info["error"]}

        actions_taken = []

        # Track gap duration
        if gap_info["needs_reclaim"]:
            if self._gap_start_time is None:
                self._gap_start_time = time.time()
            else:
                gap_duration = time.time() - self._gap_start_time
                gap_info["gap_duration_sec"] = gap_duration
        else:
            self._gap_start_time = None

        # Check thresholds and reclaim
        if (
            gap_info["needs_reclaim"]
            and gap_info.get("gap_duration_sec", 0) > self.idle_duration
            and gap_info["cpu_percent"] < self.min_cpu_for_reclaim
        ):
            result = self.trigger_ram_reclaim()
            actions_taken.append(
                {
                    "action": result.action,
                    "success": result.success,
                    "freed_mb": result.memory_freed_mb,
                }
            )

        # Check disk bloat
        vhdx = self.get_vhdx_size()
        if vhdx and vhdx["overhead_mb"] > 512:  # 512MB overhead
            result = self.trigger_disk_trim()
            actions_taken.append(
                {
                    "action": result.action,
                    "success": result.success,
                    "freed_mb": result.disk_freed_mb,
                }
            )

        return {
            "timestamp": datetime.now().isoformat(),
            "memory_gap": gap_info,
            "vhdx": vhdx,
            "actions": actions_taken,
            "should_reclaim": gap_info["needs_reclaim"]
            and gap_info.get("gap_duration_sec", 0) > self.idle_duration,
        }


def run_reclamation() -> Dict:
    """Quick reclamation check."""
    engine = ReclamationEngine()
    return engine.auto_reclaim()


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Reclamation Engine")
    parser.add_argument("--check", action="store_true", help="Check memory gap")
    parser.add_argument("--reclaim", action="store_true", help="Trigger reclaim")
    parser.add_argument("--trim", action="store_true", help="Trigger disk trim")

    args = parser.parse_args()

    engine = ReclamationEngine()

    if args.check:
        print(json.dumps(engine.check_memory_gap(), indent=2))
    elif args.reclaim:
        result = engine.trigger_ram_reclaim()
        print(
            json.dumps(
                {
                    "action": result.action,
                    "success": result.success,
                    "freed_mb": result.memory_freed_mb,
                },
                indent=2,
            )
        )
    elif args.trim:
        result = engine.trigger_disk_trim()
        print(
            json.dumps(
                {
                    "action": result.action,
                    "success": result.success,
                    "freed_mb": result.disk_freed_mb,
                },
                indent=2,
            )
        )
    else:
        print(json.dumps(engine.auto_reclaim(), indent=2, default=str))
