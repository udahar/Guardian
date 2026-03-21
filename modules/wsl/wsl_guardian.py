#!/usr/bin/env python3
"""
WSL Guardian - WSL Health Monitor and Maintenance
PromptOS Module

Monitors WSL resource usage and performs automatic maintenance
when thresholds are exceeded.

Features:
- RAM monitoring and cache clearing
- Disk monitoring and filesystem trimming
- Configurable thresholds
- Logging and reporting
"""

import subprocess
import time
import logging
import os
from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime
from enum import Enum


class LogLevel(Enum):
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"


@dataclass
class WSLConfig:
    ram_threshold: int = 85
    disk_threshold: int = 90
    wsl_distro: str = "Ubuntu"
    check_interval: int = 300
    auto_heal: bool = True
    log_level: str = "INFO"


@dataclass
class SystemMetrics:
    timestamp: datetime
    windows_ram_percent: float
    windows_disk_percent: float
    wsl_ram_mb: Optional[float] = None
    wsl_disk_gb: Optional[float] = None


@dataclass
class HealResult:
    success: bool = False
    actions_performed: list = field(default_factory=list)
    errors: list = field(default_factory=list)


class WSLGuardian:
    def __init__(self, config: Optional[WSLConfig] = None):
        self.config = config or WSLConfig()
        self.logger = self._setup_logging()
        self._callbacks: list[Callable] = []

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("WSLGuardian")
        logger.setLevel(getattr(logging, self.config.log_level))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def add_callback(self, callback: Callable[[SystemMetrics, bool], None]):
        self._callbacks.append(callback)

    def get_windows_metrics(self) -> SystemMetrics:
        import psutil

        return SystemMetrics(
            timestamp=datetime.now(),
            windows_ram_percent=psutil.virtual_memory().percent,
            windows_disk_percent=psutil.disk_usage("C:").percent,
        )

    def get_wsl_metrics(self) -> Optional[dict]:
        try:
            result = subprocess.run(
                [
                    "wsl",
                    "-d",
                    self.config.wsl_distro,
                    "-u",
                    "root",
                    "sh",
                    "-c",
                    "free -m | grep Mem | awk '{print $3,$2}'",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                used, total = result.stdout.strip().split()
                ram_percent = (float(used) / float(total)) * 100

                result = subprocess.run(
                    [
                        "wsl",
                        "-d",
                        self.config.wsl_distro,
                        "-u",
                        "root",
                        "df",
                        "-BG",
                        "/",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=10,
                )
                if result.returncode == 0:
                    lines = result.stdout.strip().split("\n")
                    if len(lines) > 1:
                        parts = lines[1].split()
                        disk_used = float(parts[2].replace("G", ""))
                        return {"ram_percent": ram_percent, "disk_gb": disk_used}
        except Exception as e:
            self.logger.warning(f"Could not get WSL metrics: {e}")
        return None

    def heal_wsl(self) -> HealResult:
        result = HealResult(actions_performed=[], errors=[])

        try:
            self.logger.info(f"Starting WSL healing for {self.config.wsl_distro}...")

            # 1. Clear Linux Cache (RAM Fix)
            try:
                subprocess.run(
                    [
                        "wsl",
                        "-d",
                        self.config.wsl_distro,
                        "-u",
                        "root",
                        "sh",
                        "-c",
                        "echo 3 > /proc/sys/vm/drop_caches",
                    ],
                    check=True,
                    timeout=30,
                )
                result.actions_performed.append("RAM cache cleared")
                self.logger.info("RAM cache cleared")
            except Exception as e:
                result.errors.append(f"Failed to clear RAM cache: {e}")
                self.logger.error(f"Failed to clear RAM cache: {e}")

            # 2. Trim Filesystem (Disk Fix)
            try:
                subprocess.run(
                    [
                        "wsl",
                        "-d",
                        self.config.wsl_distro,
                        "-u",
                        "root",
                        "fstrim",
                        "-v",
                        "/",
                    ],
                    check=True,
                    timeout=60,
                )
                result.actions_performed.append("Filesystem trimmed")
                self.logger.info("Filesystem trimmed")
            except Exception as e:
                result.errors.append(f"Failed to trim filesystem: {e}")
                self.logger.error(f"Failed to trim filesystem: {e}")

            # 3. Clear WSL log cache (optional)
            try:
                subprocess.run(
                    [
                        "wsl",
                        "-d",
                        self.config.wsl_distro,
                        "-u",
                        "root",
                        "sh",
                        "-c",
                        "journalctl --vacuum-time=3d",
                    ],
                    check=True,
                    timeout=30,
                )
                result.actions_performed.append("System logs cleaned (3 days)")
                self.logger.info("System logs cleaned")
            except Exception as e:
                result.errors.append(f"Failed to clean logs: {e}")

            result.success = len(result.errors) == 0

        except Exception as e:
            result.errors.append(f"Healing failed: {e}")
            self.logger.error(f"WSL healing failed: {e}")

        return result

    def check_and_heal(self) -> tuple[SystemMetrics, bool]:
        metrics = self.get_windows_metrics()

        self.logger.info(
            f"Status - Win RAM: {metrics.windows_ram_percent}% | "
            f"Win Disk: {metrics.windows_disk_percent}%"
        )

        needs_healing = (
            metrics.windows_ram_percent > self.config.ram_threshold
            or metrics.windows_disk_percent > self.config.disk_threshold
        )

        if needs_healing and self.config.auto_heal:
            heal_result = self.heal_wsl()
            for callback in self._callbacks:
                callback(metrics, heal_result.success)

        return metrics, needs_healing

    def run_once(self) -> tuple[SystemMetrics, bool]:
        return self.check_and_heal()

    def monitor(self, duration: Optional[int] = None):
        start_time = time.time()

        while True:
            self.check_and_heal()

            if duration and (time.time() - start_time) >= duration:
                break

            time.sleep(self.config.check_interval)


def get_default_config() -> WSLConfig:
    return WSLConfig()


def create_guardian(config: Optional[WSLConfig] = None) -> WSLGuardian:
    return WSLGuardian(config)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="WSL Guardian")
    parser.add_argument(
        "--once", action="store_true", help="Run once instead of continuous"
    )
    parser.add_argument("--ram-threshold", type=int, default=85)
    parser.add_argument("--disk-threshold", type=int, default=90)
    parser.add_argument("--distro", type=str, default="Ubuntu")

    args = parser.parse_args()

    config = WSLConfig(
        ram_threshold=args.ram_threshold,
        disk_threshold=args.disk_threshold,
        wsl_distro=args.distro,
    )

    guardian = WSLGuardian(config)

    if args.once:
        metrics, needs_healing = guardian.run_once()
        print(
            f"RAM: {metrics.windows_ram_percent}%, Disk: {metrics.windows_disk_percent}%"
        )
    else:
        print("WSL Guardian Active. Monitoring...")
        guardian.monitor()
