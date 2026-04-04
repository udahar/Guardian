#!/usr/bin/env python3
"""
Guardian package.

Keep top-level imports lazy so the package can bootstrap quickly for runtime
entrypoints such as the supervisor, API server, and monitor daemon.
"""

from __future__ import annotations

from datetime import datetime
import importlib
import time
from typing import Any


_EXPORTS = {
    "WSLGuardian": ("Guardian.modules.wsl", "WSLGuardian"),
    "WSLConfig": ("Guardian.modules.wsl", "WSLConfig"),
    "get_wsl_config": ("Guardian.modules.wsl", "get_default_config"),
    "create_wsl_guardian": ("Guardian.modules.wsl", "create_guardian"),
    "WindowsGuardian": ("Guardian.modules.windows", "WindowsGuardian"),
    "WindowsConfig": ("Guardian.modules.windows", "WindowsConfig"),
    "CleanupTarget": ("Guardian.modules.windows", "CleanupTarget"),
    "get_windows_config": ("Guardian.modules.windows", "get_default_config"),
    "create_windows_guardian": ("Guardian.modules.windows", "create_guardian"),
    "DiagnosticsEngine": ("Guardian.modules.diagnostics", "DiagnosticsEngine"),
    "SystemDiagnostics": ("Guardian.modules.diagnostics", "SystemDiagnostics"),
    "DiagnosticIssue": ("Guardian.modules.diagnostics", "DiagnosticIssue"),
    "DiskHealth": ("Guardian.modules.diagnostics", "DiskHealth"),
    "CrashInfo": ("Guardian.modules.diagnostics", "CrashInfo"),
    "BootPerformance": ("Guardian.modules.diagnostics", "BootPerformance"),
    "IssueCategory": ("Guardian.modules.diagnostics", "IssueCategory"),
    "Severity": ("Guardian.modules.diagnostics", "Severity"),
    "run_diagnostics": ("Guardian.modules.diagnostics", "run_diagnostics"),
    "AIGuardianBrain": ("Guardian.modules.services", "AIGuardianBrain"),
    "GuardianAI": ("Guardian.modules.services", "GuardianAI"),
    "quick_ai_decision": ("Guardian.modules.services", "quick_ai_decision"),
    "DecisionType": ("Guardian.modules.services", "DecisionType"),
    "Confidence": ("Guardian.modules.services", "Confidence"),
    "WSLManager": ("Guardian.modules.wsl", "WSLManager"),
    "shrink_wsl_disk": ("Guardian.modules.wsl", "shrink_wsl_disk"),
    "optimize_wsl": ("Guardian.modules.wsl", "optimize_wsl"),
    "GuardianDB": ("Guardian.modules.database", "GuardianDB"),
    "InMemoryDB": ("Guardian.modules.database", "InMemoryDB"),
    "create_db": ("Guardian.modules.database", "create_db"),
    "LinuxSensors": ("Guardian.modules.sensors", "LinuxSensors"),
    "WSLMemoryBalancer": ("Guardian.modules.sensors", "WSLMemoryBalancer"),
    "ZombieProcessKiller": ("Guardian.modules.sensors", "ZombieProcessKiller"),
    "get_linux_sensors": ("Guardian.modules.sensors", "get_linux_sensors"),
    "WindowsSensors": ("Guardian.modules.sensors", "WindowsSensors"),
    "ProcessGhostBuster": ("Guardian.modules.sensors", "ProcessGhostBuster"),
    "get_windows_sensors": ("Guardian.modules.sensors", "get_windows_sensors"),
    "NetworkMonitor": ("Guardian.modules.network", "NetworkMonitor"),
    "get_network_status": ("Guardian.modules.network", "get_network_status"),
    "HeartbeatLogger": ("Guardian.modules.monitor", "HeartbeatLogger"),
    "create_logger": ("Guardian.modules.monitor", "create_logger"),
    "ProactiveGuardian": ("Guardian.modules.monitor", "ProactiveGuardian"),
    "GuardianConfig": ("Guardian.modules.monitor", "GuardianConfig"),
    "create_guardian": ("Guardian.modules.monitor", "create_guardian"),
    "PortScanner": ("Guardian.modules.network", "PortScanner"),
    "get_port_scan": ("Guardian.modules.network", "get_port_scan"),
    "LeakDetector": ("Guardian.modules.memory", "LeakDetector"),
    "detect_leaks": ("Guardian.modules.memory", "detect_leaks"),
    "TelegramAlerts": ("Guardian.modules.alerts", "TelegramAlerts"),
    "TelegramConfig": ("Guardian.modules.alerts", "TelegramConfig"),
    "create_telegram_alerts": ("Guardian.modules.alerts", "create_telegram_alerts"),
    "AlertLevel": ("Guardian.modules.alerts", "AlertLevel"),
    "PerformanceAdvisor": ("Guardian.modules.performance", "PerformanceAdvisor"),
    "get_performance_suggestions": ("Guardian.modules.performance", "get_performance_suggestions"),
    "SuggestionCategory": ("Guardian.modules.performance", "SuggestionCategory"),
    "ImpactLevel": ("Guardian.modules.performance", "ImpactLevel"),
    "get_wsl_summary": ("Guardian.modules.wsl", "get_wsl_summary"),
    "SecurityMonitor": ("Guardian.modules.security", "SecurityMonitor"),
    "get_security_report": ("Guardian.modules.security", "get_security_report"),
    "SecurityLevel": ("Guardian.modules.security", "SecurityLevel"),
    "DockerGuardian": ("Guardian.modules.docker", "DockerGuardian"),
    "create_docker_guardian": ("Guardian.modules.docker", "create_docker_guardian"),
    "ServiceHealthMonitor": ("Guardian.modules.services", "ServiceHealthMonitor"),
    "ServiceDef": ("Guardian.modules.services", "ServiceDef"),
    "get_service_monitor": ("Guardian.modules.services", "get_monitor"),
    "scan_ollama": ("Guardian.modules.services", "scan"),
    "OllamaReport": ("Guardian.modules.services", "OllamaReport"),
    "check_docker_logs": ("Guardian.modules.docker", "check"),
    "scan_disk": ("Guardian.modules.disk", "scan"),
    "print_disk_report": ("Guardian.modules.disk", "print_report"),
    "scan_caches": ("Guardian.modules.performance", "scan"),
    "clean_caches": ("Guardian.modules.performance", "clean"),
    "scan_logs": ("Guardian.modules.monitor", "scan"),
    "get_log_summary": ("Guardian.modules.monitor", "get_summary"),
}


def __getattr__(name: str) -> Any:
    target = _EXPORTS.get(name)
    if target is None:
        raise AttributeError(f"module 'Guardian' has no attribute '{name}'")
    module_name, attr_name = target
    module = importlib.import_module(module_name)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


class Guardian:
    """
    Unified Guardian that monitors both Windows and WSL.
    """

    def __init__(self, wsl_config=None, windows_config=None):
        self.wsl_config = wsl_config or __getattr__("WSLConfig")()
        self.windows_config = windows_config or __getattr__("WindowsConfig")()
        self.wsl_guardian = __getattr__("WSLGuardian")(self.wsl_config)
        self.windows_guardian = __getattr__("WindowsGuardian")(self.windows_config)
        self._running = False

    def start(self, duration: int = None):
        print("Guardian: Starting unified monitoring...")
        print(
            f"  Windows - RAM: {self.windows_config.ram_threshold}%, Disk: {self.windows_config.disk_threshold}%"
        )
        print(
            f"  WSL - RAM: {self.wsl_config.ram_threshold}%, Disk: {self.wsl_config.disk_threshold}%"
        )
        self._running = True
        start_time = time.time()
        while self._running:
            _, needs_healing, cleanup = self.windows_guardian.run_once(self.wsl_guardian)
            if needs_healing:
                print(f"Guardian: Windows cleanup triggered ({cleanup.space_freed_mb:.1f}MB freed)")
            if duration and (time.time() - start_time) >= duration:
                break
            interval = min(self.wsl_config.check_interval, self.windows_config.check_interval)
            time.sleep(interval)

    def stop(self):
        self._running = False
        print("Guardian: Stopped")


def quick_health_check() -> dict:
    import psutil

    return {
        "cpu_percent": psutil.cpu_percent(interval=1),
        "ram_percent": psutil.virtual_memory().percent,
        "disk_percent": psutil.disk_usage("C:").percent,
        "processes": len(psutil.pids()),
        "uptime_hours": (datetime.now().timestamp() - psutil.boot_time()) / 3600,
    }


def cleanup_all():
    win_guard = __getattr__("WindowsGuardian")()
    wsl_guard = __getattr__("WSLGuardian")()
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


__all__ = ["Guardian", "quick_health_check", "cleanup_all", *_EXPORTS.keys()]
