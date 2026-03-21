#!/usr/bin/env python3
"""
Windows Guardian - Windows Health Monitor and Maintenance
PromptOS Module

Monitors Windows system resources and performs automatic maintenance
when thresholds are exceeded. Can also trigger WSL healing.

Features:
- CPU, RAM, Disk monitoring
- Temperature monitoring (via WMI/OpenHardwareMonitor)
- Automatic cleanup: temp files, recycle bin, browser caches
- Windows Update cleanup
- DNS cache clearing
- Integration with WSL Guardian
- Comprehensive logging
"""

import subprocess
import time
import os
import shutil
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime
from enum import Enum
import threading


try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


try:
    import wmi

    WMI_AVAILABLE = True
except ImportError:
    WMI_AVAILABLE = False


class CleanupTarget(Enum):
    TEMP_FILES = "temp"
    RECYCLE_BIN = "recycle_bin"
    DNS_CACHE = "dns"
    BROWSER_CACHE = "browser"
    WINDOWS_UPDATE = "windows_update"
    PREFETCH = "prefetch"
    THUMBNAILS = "thumbnails"
    ALL = "all"


@dataclass
class WindowsConfig:
    ram_threshold: int = 85
    disk_threshold: int = 90
    cpu_threshold: int = 90
    temp_threshold: int = 80
    check_interval: int = 300
    auto_heal: bool = True
    cleanup_targets: list[str] = field(
        default_factory=lambda: [
            CleanupTarget.TEMP_FILES.value,
            CleanupTarget.RECYCLE_BIN.value,
            CleanupTarget.DNS_CACHE.value,
            CleanupTarget.PREFETCH.value,
        ]
    )
    trigger_wsl_heal: bool = True
    log_level: str = "INFO"


@dataclass
class WindowsMetrics:
    timestamp: datetime
    cpu_percent: float
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    disk_percent: float
    disk_free_gb: float
    disk_total_gb: float
    temperature: Optional[float] = None
    processes: int = 0
    top_processes: list = field(default_factory=list)


@dataclass
class CleanupResult:
    success: bool = False
    actions_performed: list = field(default_factory=list)
    space_freed_mb: float = 0
    errors: list = field(default_factory=list)


class WindowsGuardian:
    def __init__(self, config: Optional[WindowsConfig] = None):
        self.config = config or WindowsConfig()
        self.logger = self._setup_logging()
        self._callbacks: list[Callable] = []
        self._wmi = None
        if WMI_AVAILABLE:
            try:
                self._wmi = wmi.WMI()
            except Exception as e:
                self.logger.warning(f"WMI not available: {e}")

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("WindowsGuardian")
        logger.setLevel(getattr(logging, self.config.log_level))

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def add_callback(self, callback: Callable[[WindowsMetrics, bool], None]):
        self._callbacks.append(callback)

    def get_system_metrics(self) -> WindowsMetrics:
        if not PSUTIL_AVAILABLE:
            raise ImportError("psutil is required for Windows Guardian")

        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory()
        disk = psutil.disk_usage("C:")

        top_procs = []
        for proc in sorted(
            psutil.process_iter(["name", "cpu_percent", "memory_percent"]),
            key=lambda x: x.info.get("cpu_percent", 0),
            reverse=True,
        )[:5]:
            try:
                top_procs.append(
                    {
                        "name": proc.info["name"],
                        "cpu": proc.info["cpu_percent"],
                        "mem": proc.info["memory_percent"],
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        temp = None
        if self._wmi:
            try:
                for temp in self._wmi.Win32_TemperatureProbe():
                    if temp.CurrentReading:
                        temp = (float(temp.CurrentReading) - 2732) / 10
                        break
            except Exception:
                pass

        return WindowsMetrics(
            timestamp=datetime.now(),
            cpu_percent=cpu,
            ram_percent=ram.percent,
            ram_used_gb=ram.used / (1024**3),
            ram_total_gb=ram.total / (1024**3),
            disk_percent=disk.percent,
            disk_free_gb=disk.free / (1024**3),
            disk_total_gb=disk.total / (1024**3),
            temperature=temp,
            processes=len(psutil.pids()),
            top_processes=top_procs,
        )

    def _run_powershell(self, command: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=60,
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def _get_folder_size(self, path: str) -> float:
        total = 0
        try:
            for dirpath, dirnames, filenames in os.walk(path):
                for f in filenames:
                    fp = os.path.join(dirpath, f)
                    try:
                        total += os.path.getsize(fp)
                    except (OSError, FileNotFoundError):
                        pass
        except Exception:
            pass
        return total / (1024 * 1024)

    def cleanup(self, targets: Optional[list[str]] = None) -> CleanupResult:
        if targets is None:
            targets = self.config.cleanup_targets

        result = CleanupResult(actions_performed=[], errors=[])

        self.logger.info(f"Starting Windows cleanup: {targets}")

        if CleanupTarget.TEMP_FILES.value in targets:
            self._cleanup_temp_files(result)

        if CleanupTarget.RECYCLE_BIN.value in targets:
            self._cleanup_recycle_bin(result)

        if CleanupTarget.DNS_CACHE.value in targets:
            self._cleanup_dns(result)

        if CleanupTarget.PREFETCH.value in targets:
            self._cleanup_prefetch(result)

        if CleanupTarget.THUMBNAILS.value in targets:
            self._cleanup_thumbnails(result)

        if CleanupTarget.BROWSER_CACHE.value in targets:
            self._cleanup_browser_cache(result)

        if CleanupTarget.WINDOWS_UPDATE.value in targets:
            self._cleanup_windows_update(result)

        result.success = len(result.errors) == 0
        return result

    def _cleanup_temp_files(self, result: CleanupResult):
        temp_paths = [
            os.environ.get("TEMP", ""),
            os.environ.get("TMP", ""),
            r"C:\Windows\Temp",
        ]

        for temp_path in temp_paths:
            if temp_path and os.path.exists(temp_path):
                try:
                    size = self._get_folder_size(temp_path)
                    count = 0
                    for item in os.listdir(temp_path):
                        item_path = os.path.join(temp_path, item)
                        try:
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path, ignore_errors=True)
                            count += 1
                        except Exception:
                            pass
                    result.actions_performed.append(
                        f"Cleaned {temp_path}: {count} items, {size:.1f}MB"
                    )
                    result.space_freed_mb += size
                    self.logger.info(
                        f"Cleaned {temp_path}: {count} items, {size:.1f}MB"
                    )
                except Exception as e:
                    result.errors.append(f"Failed to clean {temp_path}: {e}")

    def _cleanup_recycle_bin(self, result: CleanupResult):
        try:
            success, output = self._run_powershell(
                "Clear-RecycleBin -Force -ErrorAction SilentlyContinue"
            )
            result.actions_performed.append("Recycle Bin emptied")
            self.logger.info("Recycle Bin emptied")
        except Exception as e:
            result.errors.append(f"Failed to empty Recycle Bin: {e}")

    def _cleanup_dns(self, result: CleanupResult):
        try:
            subprocess.run(["ipconfig", "/flushdns"], check=True, timeout=10)
            result.actions_performed.append("DNS cache flushed")
            self.logger.info("DNS cache flushed")
        except Exception as e:
            result.errors.append(f"Failed to flush DNS: {e}")

    def _cleanup_prefetch(self, result: CleanupResult):
        prefetch_path = r"C:\Windows\Prefetch"
        if os.path.exists(prefetch_path):
            try:
                size = self._get_folder_size(prefetch_path)
                count = 0
                for item in os.listdir(prefetch_path):
                    try:
                        os.remove(os.path.join(prefetch_path, item))
                        count += 1
                    except Exception:
                        pass
                result.actions_performed.append(
                    f"Cleaned Prefetch: {count} files, {size:.1f}MB"
                )
                result.space_freed_mb += size
                self.logger.info(f"Cleaned Prefetch: {count} files, {size:.1f}MB")
            except Exception as e:
                result.errors.append(f"Failed to clean Prefetch: {e}")

    def _cleanup_thumbnails(self, result: CleanupResult):
        thumb_path = os.path.join(
            os.environ.get("LOCALAPPDATA", ""), "Microsoft", "Windows", "Explorer"
        )
        if os.path.exists(thumb_path):
            try:
                size = self._get_folder_size(thumb_path)
                count = 0
                for item in os.listdir(thumb_path):
                    if item.startswith("thumbcache") or item.startswith("iconcache"):
                        try:
                            os.remove(os.path.join(thumb_path, item))
                            count += 1
                        except Exception:
                            pass
                result.actions_performed.append(
                    f"Cleaned Thumbnails: {count} files, {size:.1f}MB"
                )
                result.space_freed_mb += size
                self.logger.info(f"Cleaned Thumbnails: {count} files, {size:.1f}MB")
            except Exception as e:
                result.errors.append(f"Failed to clean Thumbnails: {e}")

    def _cleanup_browser_cache(self, result: CleanupResult):
        local_appdata = os.environ.get("LOCALAPPDATA", "")

        browsers = {
            "Chrome": os.path.join(
                local_appdata, "Google", "Chrome", "User Data", "Default", "Cache"
            ),
            "Edge": os.path.join(
                local_appdata, "Microsoft", "Edge", "User Data", "Default", "Cache"
            ),
            "Firefox": os.path.join(local_appdata, "Mozilla", "Firefox", "Profiles"),
        }

        for browser, cache_path in browsers.items():
            if os.path.exists(cache_path):
                try:
                    size = self._get_folder_size(cache_path)
                    if browser == "Firefox":
                        for profile in os.listdir(cache_path):
                            profile_path = os.path.join(cache_path, profile, "cache2")
                            if os.path.exists(profile_path):
                                shutil.rmtree(profile_path, ignore_errors=True)
                    else:
                        shutil.rmtree(cache_path, ignore_errors=True)
                    result.actions_performed.append(
                        f"Cleaned {browser} cache: {size:.1f}MB"
                    )
                    result.space_freed_mb += size
                    self.logger.info(f"Cleaned {browser} cache: {size:.1f}MB")
                except Exception as e:
                    result.errors.append(f"Failed to clean {browser} cache: {e}")

    def _cleanup_windows_update(self, result: CleanupResult):
        try:
            success, output = self._run_powershell(
                'Get-ChildItem "C:\\Windows\\SoftwareDistribution\\Download" -Recurse | '
                "Remove-Item -Force -Recurse -ErrorAction SilentlyContinue"
            )
            result.actions_performed.append("Windows Update cache cleaned")
            self.logger.info("Windows Update cache cleaned")
        except Exception as e:
            result.errors.append(f"Failed to clean Windows Update: {e}")

    def check_and_heal(
        self, wsl_guardian=None
    ) -> tuple[WindowsMetrics, bool, Optional[CleanupResult]]:
        metrics = self.get_system_metrics()

        self.logger.info(
            f"Status - CPU: {metrics.cpu_percent}% | RAM: {metrics.ram_percent}% | "
            f"Disk: {metrics.disk_percent}% | Procs: {metrics.processes}"
        )

        if metrics.top_processes:
            top = ", ".join(
                [f"{p['name']}({p['cpu']}%)" for p in metrics.top_processes[:3]]
            )
            self.logger.debug(f"Top processes: {top}")

        needs_healing = (
            metrics.ram_percent > self.config.ram_threshold
            or metrics.disk_percent > self.config.disk_threshold
            or metrics.cpu_percent > self.config.cpu_threshold
        )

        cleanup_result = None
        if needs_healing and self.config.auto_heal:
            cleanup_result = self.cleanup()

            if self.config.trigger_wsl_heal and wsl_guardian:
                try:
                    wsl_guardian.heal_wsl()
                    self.logger.info("WSL healing triggered from Windows Guardian")
                except Exception as e:
                    self.logger.error(f"Failed to trigger WSL healing: {e}")

            for callback in self._callbacks:
                callback(metrics, cleanup_result.success)

        return metrics, needs_healing, cleanup_result

    def run_once(
        self, wsl_guardian=None
    ) -> tuple[WindowsMetrics, bool, Optional[CleanupResult]]:
        return self.check_and_heal(wsl_guardian)

    def monitor(self, duration: Optional[int] = None, wsl_guardian=None):
        start_time = time.time()

        while True:
            self.check_and_heal(wsl_guardian)

            if duration and (time.time() - start_time) >= duration:
                break

            time.sleep(self.config.check_interval)


def get_default_config() -> WindowsConfig:
    return WindowsConfig()


def create_guardian(config: Optional[WindowsConfig] = None) -> WindowsGuardian:
    return WindowsGuardian(config)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Windows Guardian")
    parser.add_argument(
        "--once", action="store_true", help="Run once instead of continuous"
    )
    parser.add_argument("--ram-threshold", type=int, default=85)
    parser.add_argument("--disk-threshold", type=int, default=90)
    parser.add_argument("--cpu-threshold", type=int, default=90)
    parser.add_argument(
        "--no-wsl", action="store_true", help="Don't trigger WSL healing"
    )
    parser.add_argument(
        "--cleanup",
        nargs="+",
        choices=["temp", "recycle_bin", "dns", "browser", "prefetch", "all"],
        help="Run specific cleanup actions",
    )

    args = parser.parse_args()

    config = WindowsConfig(
        ram_threshold=args.ram_threshold,
        disk_threshold=args.disk_threshold,
        cpu_threshold=args.cpu_threshold,
        trigger_wsl_heal=not args.no_wsl,
    )

    guardian = WindowsGuardian(config)

    if args.cleanup:
        targets = (
            args.cleanup
            if "all" not in args.cleanup
            else [c.value for c in CleanupTarget]
        )
        result = guardian.cleanup(targets)
        print(f"Cleanup complete: {result.actions_performed}")
        print(f"Space freed: {result.space_freed_mb:.1f}MB")
    elif args.once:
        metrics, needs_healing, cleanup = guardian.run_once()
        print(
            f"CPU: {metrics.cpu_percent}%, RAM: {metrics.ram_percent}%, Disk: {metrics.disk_percent}%"
        )
        if needs_healing:
            print("Cleanup triggered!")
    else:
        print("Windows Guardian Active. Monitoring...")
        guardian.monitor()
