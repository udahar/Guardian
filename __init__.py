#!/usr/bin/env python3
"""
Guardian - Unified System Health Monitor
PromptOS Module

A comprehensive system health monitoring and maintenance package
that combines Windows and WSL monitoring with diagnostics.

Usage:
    from Guardian import Guardian, run_diagnostics

    # Quick health check
    results = run_diagnostics(days=7)

    # Start unified monitoring
    guardian = Guardian()
    guardian.start()

    # Individual modules
    from Guardian import WSLGuardian, WindowsGuardian, DiagnosticsEngine
"""

from Guardian.modules.wsl import (
    WSLGuardian,
    WSLConfig,
    get_default_config as get_wsl_config,
    create_guardian as create_wsl_guardian,
)

from Guardian.modules.windows import (
    WindowsGuardian,
    WindowsConfig,
    CleanupTarget,
    get_default_config as get_windows_config,
    create_guardian as create_windows_guardian,
)

from Guardian.modules.diagnostics import (
    DiagnosticsEngine,
    SystemDiagnostics,
    DiagnosticIssue,
    DiskHealth,
    CrashInfo,
    BootPerformance,
    IssueCategory,
    Severity,
    run_diagnostics,
)

from Guardian.modules.services import (
    AIGuardianBrain,
    GuardianAI,
    quick_ai_decision,
    DecisionType,
    Confidence,
)

from Guardian.modules.wsl import (
    WSLManager,
    shrink_wsl_disk,
    optimize_wsl,
)

from Guardian.modules.database import (
    GuardianDB,
    InMemoryDB,
    create_db,
)

from Guardian.modules.sensors import (
    LinuxSensors,
    WSLMemoryBalancer,
    ZombieProcessKiller,
    get_linux_sensors,
)

from Guardian.modules.sensors import (
    WindowsSensors,
    ProcessGhostBuster,
    get_windows_sensors,
)

from Guardian.modules.network import (
    NetworkMonitor,
    get_network_status,
)

from Guardian.modules.monitor import (
    HeartbeatLogger,
    create_logger,
)

from Guardian.modules.monitor import (
    ProactiveGuardian,
    GuardianConfig,
    create_guardian,
)

from Guardian.modules.network import (
    PortScanner,
    get_port_scan,
)

from Guardian.modules.memory import (
    LeakDetector,
    detect_leaks,
)

from Guardian.modules.alerts import (
    TelegramAlerts,
    TelegramConfig,
    create_telegram_alerts,
    AlertLevel,
)

from Guardian.modules.performance import (
    PerformanceAdvisor,
    get_performance_suggestions,
    SuggestionCategory,
    ImpactLevel,
)

from Guardian.modules.wsl import (
    WSLManager,
    get_wsl_summary,
)

from Guardian.modules.security import (
    SecurityMonitor,
    get_security_report,
    SecurityLevel,
)

from Guardian.modules.docker import DockerGuardian, create_docker_guardian
from Guardian.modules.services import ServiceHealthMonitor, ServiceDef, get_monitor as get_service_monitor
from Guardian.modules.services import scan as scan_ollama, OllamaReport
from Guardian.modules.docker import check as check_docker_logs
from Guardian.modules.disk import scan as scan_disk, print_report as print_disk_report
from Guardian.modules.performance import scan as scan_caches, clean as clean_caches
from Guardian.modules.monitor import scan as scan_logs, get_summary as get_log_summary


class Guardian:
    """
    Unified Guardian that monitors both Windows and WSL.

    Monitors system resources and performs automatic maintenance
    when thresholds are exceeded on either platform.
    """

    def __init__(
        self, wsl_config: WSLConfig = None, windows_config: WindowsConfig = None
    ):
        self.wsl_config = wsl_config or WSLConfig()
        self.windows_config = windows_config or WindowsConfig()

        self.wsl_guardian = WSLGuardian(self.wsl_config)
        self.windows_guardian = WindowsGuardian(self.windows_config)

        self._running = False

    def start(self, duration: int = None):
        """
        Start unified monitoring.

        Args:
            duration: Optional duration in seconds. If None, runs indefinitely.
        """
        print("Guardian: Starting unified monitoring...")
        print(
            f"  Windows - RAM: {self.windows_config.ram_threshold}%, Disk: {self.windows_config.disk_threshold}%"
        )
        print(
            f"  WSL - RAM: {self.wsl_config.ram_threshold}%, Disk: {self.wsl_config.disk_threshold}%"
        )

        self._running = True
        start_time = __import__("time").time()

        while self._running:
            # Check Windows
            metrics, needs_healing, cleanup = self.windows_guardian.run_once(
                self.wsl_guardian
            )

            if needs_healing:
                print(
                    f"Guardian: Windows cleanup triggered ({cleanup.space_freed_mb:.1f}MB freed)"
                )

            # Check duration
            if duration and (time.time() - start_time) >= duration:
                break

            # Sleep
            interval = min(
                self.wsl_config.check_interval, self.windows_config.check_interval
            )
            time.sleep(interval)

    def stop(self):
        """Stop monitoring."""
        self._running = False
        print("Guardian: Stopped")


def quick_health_check() -> dict:
    """Run a quick health check and return summary."""
    import psutil

    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("C:").percent,
        "processes": len(psutil.pids()),
        "uptime_hours": (datetime.now().timestamp() - psutil.boot_time()) / 3600,
    }


def cleanup_all():
    """Run cleanup on both Windows and WSL."""
    win_guard = WindowsGuardian()
    wsl_guard = WSLGuardian()

    win_result = win_guard.cleanup()
    wsl_result = wsl_guard.heal_wsl()

    return {
        "windows": {
            "success": win_result.success,
            "actions": win_result.actions_performed,
            "space_freed_mb": win_result.space_freed_mb,
            "errors": win_result.errors,
        },
        "wsl": {
            "success": wsl_result.success,
            "actions": wsl_result.actions_performed,
            "errors": wsl_result.errors,
        },
    }


import time
from datetime import datetime


__all__ = [
    "Guardian",
    "WSLGuardian",
    "WindowsGuardian",
    "DiagnosticsEngine",
    "WSLConfig",
    "WindowsConfig",
    "CleanupTarget",
    "SystemDiagnostics",
    "DiagnosticIssue",
    "DiskHealth",
    "CrashInfo",
    "BootPerformance",
    "IssueCategory",
    "Severity",
    "run_diagnostics",
    "quick_health_check",
    "cleanup_all",
    "get_wsl_config",
    "get_windows_config",
    "create_wsl_guardian",
    "create_windows_guardian",
]
