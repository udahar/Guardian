#!/usr/bin/env python3
"""
System Diagnostics - Windows Health Analysis Tool
PromptOS Module

Comprehensive system health analysis for diagnosing boot issues,
performance problems, and hardware degradation.

Features:
- Windows Event Log analysis (Application, System, Security)
- Blue Screen/crash dump analysis
- Disk health checking (SMART)
- CPU/RAM/SSD monitoring
- Temperature monitoring
- Application crash tracking
- Boot performance analysis
- Maintenance recommendations
- HTML/JSON report generation
"""

import os
import subprocess
import json
import re
import logging
from dataclasses import dataclass, field, asdict
from typing import Optional, Callable
from datetime import datetime, timedelta
from enum import Enum
from pathlib import Path
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


class Severity(Enum):
    CRITICAL = "critical"
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"
    INFO = "info"


class IssueCategory(Enum):
    BOOT = "boot"
    CRASH = "crash"
    DISK = "disk"
    MEMORY = "memory"
    CPU = "cpu"
    HARDWARE = "hardware"
    DRIVER = "driver"
    APPLICATION = "application"
    SECURITY = "security"
    PERFORMANCE = "performance"


@dataclass
class DiagnosticIssue:
    category: IssueCategory
    severity: Severity
    title: str
    description: str
    source: str
    timestamp: Optional[datetime] = None
    recommendations: list = field(default_factory=list)
    raw_data: Optional[dict] = None


@dataclass
class DiskHealth:
    drive: str
    model: str
    health_status: str
    temperature: Optional[float] = None
    read_error_rate: Optional[int] = None
    reallocated_sectors: Optional[int] = None
    pending_sectors: Optional[int] = None
    power_on_hours: Optional[int] = None
    smart_data: dict = field(default_factory=dict)


@dataclass
class CrashInfo:
    timestamp: datetime
    crash_type: str
    process_name: str
    exception_code: Optional[str] = None
    dump_file: Optional[str] = None
    stack_trace: Optional[str] = None


@dataclass
class BootPerformance:
    total_time_ms: int
    firmware_time_ms: int
    bootloader_time_ms: int
    kernel_time_ms: int
    user_login_time_ms: int
    errors: list = field(default_factory=list)


@dataclass
class SystemDiagnostics:
    timestamp: datetime
    os_version: str
    uptime_days: float
    cpu_info: str
    ram_total_gb: float
    disk_info: list
    issues: list = field(default_factory=list)
    boot_performance: Optional[BootPerformance] = None
    disk_health: list = field(default_factory=list)
    recent_crashes: list = field(default_factory=list)
    event_log_summary: dict = field(default_factory=dict)
    performance_metrics: dict = field(default_factory=dict)
    recommendations: list = field(default_factory=list)


class DiagnosticsEngine:
    def __init__(self):
        self.logger = self._setup_logging()
        self._wmi = None
        if WMI_AVAILABLE:
            try:
                self._wmi = wmi.WMI()
            except Exception as e:
                self.logger.warning(f"WMI not available: {e}")

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("Diagnostics")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_powershell(self, command: str, timeout: int = 60) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def _run_command(self, cmd: list, timeout: int = 30) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def get_os_info(self) -> tuple[str, float]:
        try:
            version = subprocess.run(
                ["powershell", "-NoProfile", "cmd", "ver"],
                capture_output=True,
                text=True,
                timeout=10,
            ).stdout.strip()

            boot_time = psutil.boot_time()
            uptime = (datetime.now().timestamp() - boot_time) / 86400
            return version.replace("Microsoft Windows [Version ", "").replace(
                "]", ""
            ), uptime
        except Exception as e:
            return "Unknown", 0

    def get_cpu_info(self) -> str:
        try:
            if self._wmi:
                for cpu in self._wmi.Win32_Processor():
                    return f"{cpu.Name.strip()} ({cpu.NumberOfCores} cores, {cpu.NumberOfLogicalProcessors} threads)"
            return "Unknown"
        except Exception:
            return "Unknown"

    def get_ram_info(self) -> float:
        try:
            return psutil.virtual_memory().total / (1024**3)
        except Exception:
            return 0

    def get_disk_info(self) -> list:
        disks = []
        try:
            for part in psutil.disk_partitions():
                if part.fstype:
                    try:
                        usage = psutil.disk_usage(part.mountpoint)
                        disks.append(
                            {
                                "drive": part.device,
                                "mountpoint": part.mountpoint,
                                "fstype": part.fstype,
                                "total_gb": round(usage.total / (1024**3), 2),
                                "used_gb": round(usage.used / (1024**3), 2),
                                "free_gb": round(usage.free / (1024**3), 2),
                                "percent": usage.percent,
                            }
                        )
                    except PermissionError:
                        pass
        except Exception as e:
            self.logger.warning(f"Error getting disk info: {e}")
        return disks

    def get_event_logs(self, days: int = 7) -> dict:
        self.logger.info(f"Reading Event Logs for last {days} days...")
        logs = {
            "application": [],
            "system": [],
            "security": [],
            "errors": [],
            "warnings": [],
        }

        for log_name in ["Application", "System", "Security"]:
            try:
                success, output = self._run_powershell(
                    f'Get-WinEvent -LogName "{log_name}" -MaxEvents 100 '
                    f'-FilterXPath "*[System[TimeCreated[@SystemTime > \\"{(datetime.now() - timedelta(days=days)).isoformat()}Z\\"]]]" '
                    f"-ErrorAction SilentlyContinue | Select-Object TimeCreated,LevelDisplayName,ProviderName,Message | ConvertTo-Json",
                    timeout=60,
                )

                if success and output.strip():
                    try:
                        events = json.loads(output)
                        if isinstance(events, dict):
                            events = [events]

                        for event in events:
                            level = event.get("LevelDisplayName", "Information").lower()
                            entry = {
                                "time": event.get("TimeCreated"),
                                "level": level,
                                "source": event.get("ProviderName"),
                                "message": (event.get("Message", "") or "")[:200],
                            }
                            logs[log_name.lower()].append(entry)

                            if level in ["error", "critical"]:
                                logs["errors"].append(entry)
                            elif level == "warning":
                                logs["warnings"].append(entry)
                    except json.JSONDecodeError:
                        pass
            except Exception as e:
                self.logger.warning(f"Error reading {log_name} log: {e}")

        return logs

    def check_crash_dumps(self, days: int = 30) -> list:
        self.logger.info("Analyzing crash dumps...")
        crashes = []

        dump_paths = [
            r"C:\Windows\Minidump",
            r"C:\Windows\memdump",
        ]

        for dump_path in dump_paths:
            if os.path.exists(dump_path):
                try:
                    for f in os.listdir(dump_path):
                        if f.endswith(".dmp"):
                            fpath = os.path.join(dump_path, f)
                            mtime = datetime.fromtimestamp(os.path.getmtime(fpath))
                            if (datetime.now() - mtime).days <= days:
                                size_mb = os.path.getsize(fpath) / (1024 * 1024)
                                crashes.append(
                                    {
                                        "file": f,
                                        "path": fpath,
                                        "size_mb": round(size_mb, 2),
                                        "timestamp": mtime.isoformat(),
                                        "type": "minidump"
                                        if "minidump" in dump_path.lower()
                                        else "memdump",
                                    }
                                )
                except Exception as e:
                    self.logger.warning(f"Error reading dump path {dump_path}: {e}")

        return crashes

    def check_disk_health(self) -> list:
        self.logger.info("Checking disk SMART data...")
        disks = []

        if self._wmi:
            try:
                for disk in self._wmi.Win32_DiskDrive():
                    health = DiskHealth(
                        drive=disk.DeviceID,
                        model=disk.Model,
                        health_status=disk.Status or "Unknown",
                    )

                    try:
                        for partition in disk.associators(
                            "Win32_DiskDriveToDiskPartition"
                        ):
                            for logical in partition.associators(
                                "Win32_LogicalDiskToPartition"
                            ):
                                health.drive = logical.DeviceID
                    except Exception:
                        pass

                    disks.append(health)
            except Exception as e:
                self.logger.warning(f"WMI disk health error: {e}")

        success, output = self._run_command(
            ["wmic", "diskdrive", "get", "model,status", "/format:csv"]
        )
        if success:
            for line in output.strip().split("\n")[1:]:
                if line.strip():
                    parts = line.split(",")
                    if len(parts) >= 2:
                        existing = next((d for d in disks if parts[1] in d.model), None)
                        if existing:
                            existing.health_status = parts[0] or existing.health_status

        return disks

    def get_boot_performance(self) -> Optional[BootPerformance]:
        self.logger.info("Analyzing boot performance...")

        try:
            success, output = self._run_powershell(
                'Get-WinEvent -LogName "Microsoft-Windows-Diagnostics-Performance/Operational" '
                "-MaxEvents 50 -ErrorAction SilentlyContinue | "
                'Where-Object { $_.ProviderName -eq "Microsoft-Windows-Diagnostics-Performance" } | '
                "Select-Object TimeCreated,Id,Message | ConvertTo-Json",
                timeout=30,
            )

            if success and output.strip():
                errors = []
                total = firmware = bootloader = kernel = login = 0

                try:
                    events = json.loads(output)
                    if isinstance(events, dict):
                        events = [events]

                    for event in events:
                        msg = event.get("Message", "")
                        if "Total" in msg and "Boot" in msg:
                            match = re.search(r"(\d+)\s*ms", msg)
                            if match:
                                total = int(match.group(1))
                        elif "Firmware" in msg:
                            match = re.search(r"(\d+)\s*ms", msg)
                            if match:
                                firmware = int(match.group(1))
                        elif "Boot" in msg and "Launcher" in msg:
                            match = re.search(r"(\d+)\s*ms", msg)
                            if match:
                                bootloader = int(match.group(1))
                        elif "Windows" in msg and "Startup" in msg:
                            match = re.search(r"(\d+)\s*ms", msg)
                            if match:
                                kernel = int(match.group(1))
                        elif "User" in msg and "Profile" in msg:
                            match = re.search(r"(\d+)\s*ms", msg)
                            if match:
                                login = int(match.group(1))

                        if event.get("Id") in [101, 103, 105, 107, 109, 110, 111, 112]:
                            errors.append(msg[:150])
                except (json.JSONDecodeError, KeyError):
                    pass

                if total > 0:
                    return BootPerformance(
                        total_time_ms=total,
                        firmware_time_ms=firmware,
                        bootloader_time_ms=bootloader,
                        kernel_time_ms=kernel,
                        user_login_time_ms=login,
                        errors=errors,
                    )
        except Exception as e:
            self.logger.warning(f"Boot performance analysis error: {e}")

        return None

    def get_performance_metrics(self) -> dict:
        self.logger.info("Gathering performance metrics...")
        metrics = {}

        try:
            metrics["cpu"] = {
                "percent": psutil.cpu_percent(interval=2),
                "count": psutil.cpu_count(),
                "freq": psutil.cpu_freq()._asdict() if psutil.cpu_freq() else None,
            }

            vm = psutil.virtual_memory()
            metrics["memory"] = {
                "total_gb": round(vm.total / (1024**3), 2),
                "available_gb": round(vm.available / (1024**3), 2),
                "percent": vm.percent,
                "used_gb": round(vm.used / (1024**3), 2),
            }

            sm = psutil.disk_io_counters()
            if sm:
                metrics["disk_io"] = {
                    "read_mb": round(sm.read_bytes / (1024**2), 2),
                    "write_mb": round(sm.write_bytes / (1024**2), 2),
                    "read_count": sm.read_count,
                    "write_count": sm.write_count,
                }

            net = psutil.net_io_counters()
            if net:
                metrics["network"] = {
                    "sent_mb": round(net.bytes_sent / (1024**2), 2),
                    "recv_mb": round(net.bytes_recv / (1024**2), 2),
                }

            temps = psutil.sensors_temperatures()
            if temps:
                metrics["temperatures"] = temps

            metrics["processes"] = len(psutil.pids())

            top_cpu = []
            for proc in sorted(
                psutil.process_iter(["name", "cpu_percent", "memory_percent"]),
                key=lambda x: x.info.get("cpu_percent", 0),
                reverse=True,
            )[:5]:
                try:
                    top_cpu.append(
                        {
                            "name": proc.info["name"],
                            "cpu": proc.info["cpu_percent"],
                            "mem": proc.info["memory_percent"],
                        }
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
            metrics["top_processes"] = top_cpu

        except Exception as e:
            self.logger.warning(f"Performance metrics error: {e}")

        return metrics

    def analyze_issues(
        self,
        logs: dict,
        crashes: list,
        disk_health: list,
        boot: Optional[BootPerformance],
        perf: dict,
    ) -> list:
        issues = []

        for error in logs.get("errors", [])[:20]:
            msg = error.get("message", "").lower()

            if "boot" in msg or "startup" in msg:
                issues.append(
                    DiagnosticIssue(
                        category=IssueCategory.BOOT,
                        severity=Severity.HIGH,
                        title="Boot Issue Detected",
                        description=error.get("message", ""),
                        source=error.get("source", "Unknown"),
                        timestamp=datetime.fromisoformat(
                            error["time"].replace("Z", "+00:00")
                        )
                        if error.get("time")
                        else None,
                        recommendations=[
                            "Run 'systemreset' to repair Windows",
                            "Check disk for errors",
                            "Review driver updates",
                        ],
                    )
                )

            if "driver" in msg or "device" in msg:
                issues.append(
                    DiagnosticIssue(
                        category=IssueCategory.DRIVER,
                        severity=Severity.MEDIUM,
                        title="Driver Issue Detected",
                        description=error.get("message", ""),
                        source=error.get("source", "Unknown"),
                        timestamp=datetime.fromisoformat(
                            error["time"].replace("Z", "+00:00")
                        )
                        if error.get("time")
                        else None,
                        recommendations=[
                            "Update device drivers",
                            "Check Device Manager for yellow triangles",
                        ],
                    )
                )

            if any(x in msg for x in ["disk", "storage", "i/o"]):
                issues.append(
                    DiagnosticIssue(
                        category=IssueCategory.DISK,
                        severity=Severity.HIGH,
                        title="Disk Issue Detected",
                        description=error.get("message", ""),
                        source=error.get("source", "Unknown"),
                        timestamp=datetime.fromisoformat(
                            error["time"].replace("Z", "+00:00")
                        )
                        if error.get("time")
                        else None,
                        recommendations=[
                            "Run disk check: chkdsk C: /f",
                            "Backup important data",
                            "Check SMART data",
                        ],
                    )
                )

            if any(x in msg for x in ["memory", "pool", "nonpaged"]):
                issues.append(
                    DiagnosticIssue(
                        category=IssueCategory.MEMORY,
                        severity=Severity.HIGH,
                        title="Memory Issue Detected",
                        description=error.get("message", ""),
                        source=error.get("source", "Unknown"),
                        timestamp=datetime.fromisoformat(
                            error["time"].replace("Z", "+00:00")
                        )
                        if error.get("time")
                        else None,
                        recommendations=[
                            "Run Windows Memory Diagnostic",
                            "Check for memory leaks",
                            "Update BIOS",
                        ],
                    )
                )

        for crash in crashes:
            issues.append(
                DiagnosticIssue(
                    category=IssueCategory.CRASH,
                    severity=Severity.HIGH,
                    title=f"Crash Dump Found: {crash.get('file', 'Unknown')}",
                    description=f"Crash dump file: {crash.get('path', '')} ({crash.get('size_mb', 0)}MB)",
                    source="System",
                    timestamp=datetime.fromisoformat(crash["timestamp"])
                    if crash.get("timestamp")
                    else None,
                    recommendations=[
                        "Analyze dump with WinDbg",
                        "Check for recent driver updates",
                        "Review event logs around crash time",
                    ],
                )
            )

        for disk in disk_health:
            if disk.health_status.lower() not in ["ok", "healthy", "good"]:
                issues.append(
                    DiagnosticIssue(
                        category=IssueCategory.DISK,
                        severity=Severity.CRITICAL,
                        title=f"Disk Health Warning: {disk.model}",
                        description=f"Disk status: {disk.health_status}",
                        source="SMART",
                        recommendations=[
                            "Backup all important data immediately",
                            "Run disk diagnostics",
                            "Consider replacing disk",
                        ],
                    )
                )

        if boot and boot.total_time_ms > 60000:
            issues.append(
                DiagnosticIssue(
                    category=IssueCategory.BOOT,
                    severity=Severity.MEDIUM,
                    title="Slow Boot Performance",
                    description=f"Total boot time: {boot.total_time_ms / 1000:.1f}s (target: <30s)",
                    source="Boot Performance",
                    recommendations=[
                        "Disable startup programs",
                        "Run disk defragmenter",
                        "Update drivers",
                        "Consider SSD upgrade",
                    ],
                )
            )

        if perf.get("memory", {}).get("percent", 0) > 90:
            issues.append(
                DiagnosticIssue(
                    category=IssueCategory.MEMORY,
                    severity=Severity.MEDIUM,
                    title="High Memory Usage",
                    description=f"Memory usage: {perf['memory']['percent']}%",
                    source="Performance Monitor",
                    recommendations=[
                        "Close unused applications",
                        "Check for memory leaks",
                        "Consider adding more RAM",
                    ],
                )
            )

        return issues

    def generate_recommendations(
        self, issues: list, disk_health: list, uptime_days: float, perf: dict
    ) -> list:
        recommendations = []

        critical_count = sum(1 for i in issues if i.severity == Severity.CRITICAL)
        high_count = sum(1 for i in issues if i.severity == Severity.HIGH)

        if critical_count > 0:
            recommendations.append(
                {
                    "priority": "CRITICAL",
                    "action": "Data Backup Recommended",
                    "details": f"{critical_count} critical issues found. Backup important data immediately.",
                }
            )

        if high_count > 2:
            recommendations.append(
                {
                    "priority": "HIGH",
                    "action": "Run System File Checker",
                    "details": "Multiple issues detected. Run: sfc /scannow in admin cmd",
                }
            )

        if uptime_days > 365:
            recommendations.append(
                {
                    "priority": "MEDIUM",
                    "action": "Consider Restart",
                    "details": f"System has been running for {uptime_days:.0f} days. Consider restarting for memory cleanup.",
                }
            )

        for disk in disk_health:
            if disk.health_status.lower() not in ["ok", "healthy", "good"]:
                recommendations.append(
                    {
                        "priority": "CRITICAL",
                        "action": "Replace Hard Drive",
                        "details": f"Disk {disk.model} shows health issues. Replace immediately.",
                    }
                )

        if perf.get("disk_io", {}).get("read_count", 0) > 10000000:
            recommendations.append(
                {
                    "priority": "MEDIUM",
                    "action": "High Disk I/O",
                    "details": "Excessive disk operations. Consider running defragmenter or upgrading to SSD.",
                }
            )

        recommendations.extend(
            [
                {
                    "priority": "MEDIUM",
                    "action": "Run Disk Cleanup",
                    "details": "Use Windows Disk Cleanup to remove temporary files and system cache.",
                },
                {
                    "priority": "LOW",
                    "action": "Windows Update",
                    "details": "Check for Windows updates to patch security vulnerabilities.",
                },
                {
                    "priority": "LOW",
                    "action": "Driver Updates",
                    "details": "Update all device drivers to latest versions.",
                },
            ]
        )

        return recommendations

    def run_full_diagnostics(self, days: int = 7) -> SystemDiagnostics:
        self.logger.info("Starting full system diagnostics...")

        os_version, uptime_days = self.get_os_info()
        cpu_info = self.get_cpu_info()
        ram_total = self.get_ram_info()
        disk_info = self.get_disk_info()

        logs = self.get_event_logs(days)
        crashes = self.check_crash_dumps(days)
        disk_health_raw = self.check_disk_health()
        boot_perf = self.get_boot_performance()
        perf = self.get_performance_metrics()

        issues = self.analyze_issues(logs, crashes, disk_health_raw, boot_perf, perf)
        recommendations = self.generate_recommendations(
            issues, disk_health_raw, uptime_days, perf
        )

        return SystemDiagnostics(
            timestamp=datetime.now(),
            os_version=os_version,
            uptime_days=uptime_days,
            cpu_info=cpu_info,
            ram_total_gb=ram_total,
            disk_info=disk_info,
            issues=[asdict(i) for i in issues],
            boot_performance=asdict(boot_perf) if boot_perf else None,
            disk_health=[asdict(d) for d in disk_health_raw],
            recent_crashes=crashes,
            event_log_summary={
                "total_errors": len(logs.get("errors", [])),
                "total_warnings": len(logs.get("warnings", [])),
                "app_events": len(logs.get("application", [])),
                "sys_events": len(logs.get("system", [])),
            },
            performance_metrics=perf,
            recommendations=recommendations,
        )

    def export_report(
        self, diagnostics: SystemDiagnostics, output_path: str, format: str = "json"
    ):
        if format == "json":
            with open(output_path, "w") as f:
                json.dump(asdict(diagnostics), f, indent=2, default=str)
        elif format == "html":
            html = self._generate_html_report(diagnostics)
            with open(output_path, "w") as f:
                f.write(html)

        self.logger.info(f"Report exported to {output_path}")

    def _generate_html_report(self, diagnostics: SystemDiagnostics) -> str:
        html = f"""
<!DOCTYPE html>
<html>
<head>
    <title>System Diagnostics Report</title>
    <style>
        body {{ font-family: Arial, sans-serif; margin: 20px; }}
        h1 {{ color: #2c3e50; }}
        h2 {{ color: #34495e; border-bottom: 2px solid #3498db; }}
        .severity-critical {{ color: #c0392b; font-weight: bold; }}
        .severity-high {{ color: #e67e22; font-weight: bold; }}
        .severity-medium {{ color: #f39c12; }}
        .severity-low {{ color: #27ae60; }}
        .issue {{ background: #f8f9fa; padding: 10px; margin: 5px 0; border-left: 4px solid #3498db; }}
        .metric {{ display: inline-block; margin: 10px; padding: 15px; background: #ecf0f1; border-radius: 5px; }}
        .recommendation {{ background: #e8f6f3; padding: 10px; margin: 5px 0; border-left: 4px solid #27ae60; }}
    </style>
</head>
<body>
    <h1>System Diagnostics Report</h1>
    <p>Generated: {diagnostics.timestamp}</p>
    
    <h2>System Overview</h2>
    <div class="metric">OS: {diagnostics.os_version}</div>
    <div class="metric">Uptime: {diagnostics.uptime_days:.1f} days</div>
    <div class="metric">RAM: {diagnostics.ram_total_gb:.1f} GB</div>
    <div class="metric">CPU: {diagnostics.cpu_info}</div>
    
    <h2>Issues Found ({len(diagnostics.issues)})</h2>
"""
        for issue in diagnostics.issues:
            severity_class = f"severity-{issue['severity']}"
            html += f"""
    <div class="issue">
        <span class="{severity_class}">{issue["severity"].upper()}</span> - 
        <strong>{issue["title"]}</strong><br>
        {issue["description"]}<br>
        <em>Source: {issue["source"]}</em>
    </div>
"""

        html += f"""
    <h2>Recommendations</h2>
"""
        for rec in diagnostics.recommendations:
            priority_class = f"severity-{rec['priority'].lower()}"
            html += f"""
    <div class="recommendation">
        <span class="{priority_class}">{rec["priority"]}</span> - 
        <strong>{rec["action"]}</strong><br>
        {rec["details"]}
    </div>
"""

        html += f"""
    <h2>Performance</h2>
    <div class="metric">CPU: {diagnostics.performance_metrics.get("cpu", {}).get("percent", 0)}%</div>
    <div class="metric">Memory: {diagnostics.performance_metrics.get("memory", {}).get("percent", 0)}%</div>
    <div class="metric">Processes: {diagnostics.performance_metrics.get("processes", 0)}</div>
    
    <h2>Event Log Summary</h2>
    <div class="metric">Errors: {diagnostics.event_log_summary.get("total_errors", 0)}</div>
    <div class="metric">Warnings: {diagnostics.event_log_summary.get("total_warnings", 0)}</div>
</body>
</html>
"""
        return html


def run_diagnostics(
    days: int = 7, output: Optional[str] = None, format: str = "json"
) -> SystemDiagnostics:
    engine = DiagnosticsEngine()
    results = engine.run_full_diagnostics(days)

    if output:
        engine.export_report(results, output, format)

    return results


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="System Diagnostics")
    parser.add_argument("--days", type=int, default=7, help="Days to analyze")
    parser.add_argument("--output", type=str, help="Output file path")
    parser.add_argument("--format", choices=["json", "html"], default="json")
    parser.add_argument("--print", action="store_true", help="Print results to console")

    args = parser.parse_args()

    results = run_diagnostics(args.days, args.output, args.format)

    if args.print or not args.output:
        print(f"\n=== System Diagnostics Report ===")
        print(f"OS: {results.os_version}")
        print(f"Uptime: {results.uptime_days:.1f} days")
        print(f"Issues Found: {len(results.issues)}")
        print(f"Errors: {results.event_log_summary.get('total_errors', 0)}")
        print(f"Warnings: {results.event_log_summary.get('total_warnings', 0)}")

        if results.performance_metrics:
            perf = results.performance_metrics
            print(f"\n=== Performance ===")
            print(f"CPU: {perf.get('cpu', {}).get('percent', 0)}%")
            print(f"Memory: {perf.get('memory', {}).get('percent', 0)}%")
            print(f"Processes: {perf.get('processes', 0)}")

        print(f"\n=== Recommendations ===")
        for rec in results.recommendations[:5]:
            print(f"[{rec['priority']}] {rec['action']}: {rec['details']}")
