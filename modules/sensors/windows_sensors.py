#!/usr/bin/env python3
"""
Windows Sensors - Windows Host Hardware Monitoring
PromptOS Module

Comprehensive Windows hardware monitoring including:
- CPU temperature monitoring (WMI/OpenHardwareMonitor)
- Power state and battery monitoring
- Process monitoring with spike detection
- Thermal throttling recommendations
- Power plan management

Features:
- Real-time CPU temperature
- Battery state and charging status
- Power profile detection
- Process anomaly detection
- High-temperature alerts and auto-throttling
"""

import subprocess
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime
import json
import os


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


@dataclass
class CPUTemperature:
    current_celsius: float
    critical_celsius: float
    thermal_throttling: bool
    source: str


@dataclass
class PowerState:
    is_on_battery: bool
    battery_percent: int
    power_plan: str
    charging: bool
    time_remaining_minutes: Optional[int]


@dataclass
class ProcessSpike:
    name: str
    pid: int
    cpu_percent: float
    memory_mb: float
    is_system_process: bool
    should_deprioritize: bool


@dataclass
class WindowsSensorsSnapshot:
    timestamp: datetime
    cpu_temp: Optional[CPUTemperature]
    power: Optional[PowerState]
    cpu_percent: float
    memory_percent: float
    disk_percent: float
    processes: int
    top_cpu_processes: List[Dict] = field(default_factory=list)
    top_memory_processes: List[Dict] = field(default_factory=list)
    spikes: List[ProcessSpike] = field(default_factory=list)


class WindowsSensors:
    def __init__(self):
        self.logger = self._setup_logging()
        self._wmi = None
        if WMI_AVAILABLE:
            try:
                self._wmi = wmi.WMI()
            except Exception as e:
                self.logger.warning(f"WMI not available: {e}")

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("WindowsSensors")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_powershell(self, command: str, timeout: int = 30) -> tuple[bool, str]:
        try:
            kwargs = {
                "capture_output": True,
                "text": True,
                "timeout": timeout,
            }
            if os.name == "nt":
                kwargs["creationflags"] = getattr(subprocess, "CREATE_NO_WINDOW", 0)
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                **kwargs,
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def get_cpu_temperature(self) -> Optional[CPUTemperature]:
        """Get CPU temperature via WMI or OpenHardwareMonitor."""
        temp_c = None
        critical = 90.0
        source = "unknown"

        if self._wmi:
            try:
                for t in self._wmi.Win32_TemperatureProbe():
                    if t.CurrentReading:
                        temp_c = (float(t.CurrentReading) - 2732) / 10
                        if t.CriticalTripPoint:
                            critical = (float(t.CriticalTripPoint) - 2732) / 10
                        source = "WMI"
                        break
            except Exception as e:
                self.logger.debug(f"WMI temp failed: {e}")

        if temp_c is None:
            success, output = self._run_powershell(
                'Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace "root/wmi" | '
                "Select-Object -First 1 -ExpandProperty CurrentTemperature"
            )
            if success and output.strip():
                try:
                    temp_k = float(output.strip())
                    temp_c = (temp_k - 2732) / 10
                    source = "WMI-thermal"
                except Exception:
                    pass

        if temp_c is None and PSUTIL_AVAILABLE:
            try:
                temps = psutil.sensors_temperatures()
                for name, entries in temps.items():
                    for entry in entries:
                        if entry.current:
                            temp_c = entry.current
                            critical = entry.critical or 90.0
                            source = f"psutil-{name}"
                            break
                    if temp_c:
                        break
            except Exception as e:
                self.logger.debug(f"psutil temps failed: {e}")

        if temp_c is None:
            return None

        return CPUTemperature(
            current_celsius=round(temp_c, 1),
            critical_celsius=critical,
            thermal_throttling=temp_c > critical,
            source=source,
        )

    def get_power_state(self) -> Optional[PowerState]:
        """Get battery and power state."""
        if not PSUTIL_AVAILABLE:
            return None

        try:
            battery = psutil.sensors_battery()

            is_battery = battery.percent < 100 or battery.power_plugged == False
            charging = battery.power_plugged == True if battery else False

            power_plan = "Unknown"
            success, output = self._run_powershell(
                "(Get-WmiObject -Class Win32_PowerPlan -Namespace root/cimv2/power | "
                'Where-Object { $_.IsActive -eq $true }).InstanceID -replace ".*\\{", "" -replace "\\}", ""'
            )
            if success and output.strip():
                plan_id = output.strip().lower()
                if "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c" in plan_id:
                    power_plan = "High Performance"
                elif "381b4222-f694-41f0-9685-ff5bb260df2e" in plan_id:
                    power_plan = "Balanced"
                elif "a1841308-3541-4fab-bc81-f71556f20b4a" in plan_id:
                    power_plan = "Power Saver"

            time_remaining = None
            if battery and battery.secsleft and battery.secsleft < 2**31:
                time_remaining = int(battery.secsleft / 60)

            return PowerState(
                is_on_battery=is_battery,
                battery_percent=int(battery.percent) if battery else 100,
                power_plan=power_plan,
                charging=charging,
                time_remaining_minutes=time_remaining,
            )
        except Exception as e:
            self.logger.error(f"Error getting power state: {e}")
            return None

    def get_top_processes(self, limit: int = 10) -> tuple[List[Dict], List[Dict]]:
        """Get top CPU and memory processes."""
        if not PSUTIL_AVAILABLE:
            return [], []

        cpu_procs = []
        mem_procs = []

        try:
            all_procs = list(
                psutil.process_iter(
                    ["name", "cpu_percent", "memory_percent", "memory_info"]
                )
            )

            sorted_cpu = sorted(
                all_procs, key=lambda x: x.info.get("cpu_percent", 0), reverse=True
            )
            sorted_mem = sorted(
                all_procs, key=lambda x: x.info.get("memory_percent", 0), reverse=True
            )

            for proc in sorted_cpu[:limit]:
                try:
                    mem_mb = proc.memory_info().rss / (1024 * 1024)
                    cpu_procs.append(
                        {
                            "name": proc.name(),
                            "pid": proc.pid,
                            "cpu": round(proc.cpu_percent(), 1),
                            "mem_percent": round(proc.memory_percent(), 1),
                            "mem_mb": round(mem_mb, 1),
                        }
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

            for proc in sorted_mem[:limit]:
                try:
                    mem_mb = proc.memory_info().rss / (1024 * 1024)
                    mem_procs.append(
                        {
                            "name": proc.name(),
                            "pid": proc.pid,
                            "cpu": round(proc.cpu_percent(), 1),
                            "mem_percent": round(proc.memory_percent(), 1),
                            "mem_mb": round(mem_mb, 1),
                        }
                    )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass

        except Exception as e:
            self.logger.error(f"Error getting processes: {e}")

        return cpu_procs, mem_procs

    def detect_process_spikes(
        self, cpu_threshold: float = 30.0, memory_threshold_mb: float = 500.0
    ) -> List[ProcessSpike]:
        """Detect processes that are spiking."""
        spikes = []

        problematic_procs = [
            "SearchIndexer.exe",
            "MsMpEng.exe",
            "RuntimeBroker.exe",
            "SearchHost.exe",
            "sihost.exe",
        ]

        if not PSUTIL_AVAILABLE:
            return spikes

        try:
            for proc in psutil.process_iter(["name", "cpu_percent", "memory_info"]):
                try:
                    cpu = proc.cpu_percent()
                    mem_mb = proc.memory_info().rss / (1024 * 1024)
                    name = proc.name()

                    if cpu > cpu_threshold or mem_mb > memory_threshold_mb:
                        is_system = name in problematic_procs

                        spikes.append(
                            ProcessSpike(
                                name=name,
                                pid=proc.pid,
                                cpu_percent=round(cpu, 1),
                                memory_mb=round(mem_mb, 1),
                                is_system_process=is_system,
                                should_deprioritize=is_system and cpu > 10,
                            )
                        )
                except (psutil.NoSuchProcess, psutil.AccessDenied):
                    pass
        except Exception as e:
            self.logger.error(f"Error detecting spikes: {e}")

        return sorted(spikes, key=lambda x: x.cpu_percent, reverse=True)[:10]

    def take_snapshot(self) -> WindowsSensorsSnapshot:
        cpu_temp = self.get_cpu_temperature()
        power = self.get_power_state()
        cpu_procs, mem_procs = self.get_top_processes()
        spikes = self.detect_process_spikes()

        cpu = psutil.cpu_percent(interval=0.5) if PSUTIL_AVAILABLE else 0
        memory = psutil.virtual_memory().percent if PSUTIL_AVAILABLE else 0
        disk = psutil.disk_usage("C:").percent if PSUTIL_AVAILABLE else 0
        process_count = len(psutil.pids()) if PSUTIL_AVAILABLE else 0

        return WindowsSensorsSnapshot(
            timestamp=datetime.now(),
            cpu_temp=cpu_temp,
            power=power,
            cpu_percent=cpu,
            memory_percent=memory,
            disk_percent=disk,
            processes=process_count,
            top_cpu_processes=cpu_procs,
            top_memory_processes=mem_procs,
            spikes=spikes,
        )

    def get_summary(self) -> dict:
        snapshot = self.take_snapshot()

        result = {
            "timestamp": snapshot.timestamp.isoformat(),
            "cpu_percent": snapshot.cpu_percent,
            "memory_percent": snapshot.memory_percent,
            "disk_percent": snapshot.disk_percent,
            "processes": snapshot.processes,
        }

        if snapshot.cpu_temp:
            result["cpu_temp"] = {
                "celsius": snapshot.cpu_temp.current_celsius,
                "critical": snapshot.cpu_temp.critical_celsius,
                "throttling": snapshot.cpu_temp.thermal_throttling,
                "source": snapshot.cpu_temp.source,
            }

        if snapshot.power:
            result["power"] = {
                "on_battery": snapshot.power.is_on_battery,
                "battery_percent": snapshot.power.battery_percent,
                "power_plan": snapshot.power.power_plan,
                "charging": snapshot.power.charging,
                "time_remaining_min": snapshot.power.time_remaining_minutes,
            }

        result["top_cpu"] = snapshot.top_cpu_processes[:5]
        result["spikes"] = [
            {
                "name": s.name,
                "cpu": s.cpu_percent,
                "mem_mb": s.memory_mb,
                "system": s.is_system_process,
            }
            for s in snapshot.spikes[:5]
        ]

        return result

    def apply_thermal_throttle(self) -> dict:
        """Apply thermal throttling measures."""
        result = {"actions": [], "success": False}

        if not PSUTIL_AVAILABLE:
            result["error"] = "psutil not available"
            return result

        cpu_temp = self.get_cpu_temperature()
        if not cpu_temp or cpu_temp.current_celsius < 85:
            result["message"] = "Temperature OK, no action needed"
            result["success"] = True
            return result

        try:
            success, _ = self._run_powershell("powercfg /change standby-timeout-ac 5")
            if success:
                result["actions"].append("set_standby_5min")

            success, _ = self._run_powershell(
                "powercfg /setactive 381b4222-f694-41f0-9685-ff5bb260df2e"
            )
            if success:
                result["actions"].append("set_balanced_power")

            result["success"] = True
            self.logger.info(f"Applied thermal throttle: {result['actions']}")

        except Exception as e:
            result["error"] = str(e)

        return result


class ProcessGhostBuster:
    """Track and manage problematic processes."""

    def __init__(self):
        self.logger = logging.getLogger("ProcessGhost")
        self.tracked = {}

    def deprioritize_process(self, name: str) -> bool:
        """Lower priority of a process."""
        try:
            for proc in psutil.process_iter(["name", "pid"]):
                if proc.name().lower() == name.lower():
                    proc.nice(psutil.IDLE_PRIORITY_CLASS)
                    self.logger.info(f"Deprioritized {name} (PID: {proc.pid})")
                    return True
        except Exception as e:
            self.logger.error(f"Failed to deprioritize {name}: {e}")
        return False

    def suspend_process(self, name: str) -> bool:
        """Suspend a process."""
        try:
            for proc in psutil.process_iter(["name", "pid"]):
                if proc.name().lower() == name.lower():
                    proc.suspend()
                    self.logger.info(f"Suspended {name} (PID: {proc.pid})")
                    return True
        except Exception as e:
            self.logger.error(f"Failed to suspend {name}: {e}")
        return False


def get_windows_sensors() -> dict:
    """Quick function to get Windows sensors."""
    sensors = WindowsSensors()
    return sensors.get_summary()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Windows Sensors")
    parser.add_argument("--snapshot", action="store_true", help="Full snapshot")
    parser.add_argument("--temp", action="store_true", help="Get CPU temp")
    parser.add_argument("--power", action="store_true", help="Get power state")
    parser.add_argument("--spikes", action="store_true", help="Detect spikes")
    parser.add_argument(
        "--throttle", action="store_true", help="Apply thermal throttle"
    )

    args = parser.parse_args()

    sensors = WindowsSensors()

    if args.snapshot or (not any([args.temp, args.power, args.spikes, args.throttle])):
        print(json.dumps(sensors.get_summary(), indent=2, default=str))

    elif args.temp:
        temp = sensors.get_cpu_temperature()
        if temp:
            print(
                f"CPU Temperature: {temp.current_celsius}°C (Critical: {temp.critical_celsius}°C)"
            )
            print(f"Throttling: {temp.thermal_throttling}")
            print(f"Source: {temp.source}")
        else:
            print("Could not get temperature")

    elif args.power:
        power = sensors.get_power_state()
        if power:
            print(f"Battery: {power.battery_percent}%")
            print(f"On Battery: {power.is_on_battery}")
            print(f"Charging: {power.charging}")
            print(f"Power Plan: {power.power_plan}")
            if power.time_remaining_minutes:
                print(f"Time Remaining: {power.time_remaining_minutes} min")
        else:
            print("Could not get power state")

    elif args.spikes:
        spikes = sensors.detect_process_spikes()
        print(f"Process Spikes: {len(spikes)}")
        for s in spikes[:10]:
            print(
                f"  {s.name}: CPU {s.cpu_percent}%, MEM {s.memory_mb:.1f}MB"
                + (" [SYSTEM]" if s.is_system_process else "")
            )

    elif args.throttle:
        result = sensors.apply_thermal_throttle()
        print(json.dumps(result, indent=2))
