#!/usr/bin/env python3
"""
ThermalWatchdog - Laptop State & Thermal Monitoring
PromptOS Module

Monitors laptop state and thermal conditions:
- Laptop lid open/closed detection
- CPU/GPU temperature monitoring
- Automatic power throttling when in bag/car
- Battery and power state monitoring

Output: PostgreSQL logging
"""

import subprocess
import logging
from dataclasses import dataclass
from typing import Optional, Dict
from datetime import datetime
from enum import Enum


class LaptopState(Enum):
    OPEN = "open"
    CLOSED = "closed"
    UNKNOWN = "unknown"


class ThermalState(Enum):
    COOL = "cool"
    NORMAL = "normal"
    WARM = "warm"
    HOT = "hot"
    CRITICAL = "critical"


@dataclass
class ThermalReport:
    laptop_state: LaptopState
    cpu_temp_c: float
    gpu_temp_c: Optional[float]
    thermal_state: ThermalState
    power_plan: str
    is_battery: bool
    battery_percent: int
    should_throttle: bool


class ThermalWatchdog:
    def __init__(
        self,
        temp_warning: float = 75.0,
        temp_critical: float = 85.0,
        throttle_temp: float = 80.0,
    ):
        self.temp_warning = temp_warning
        self.temp_critical = temp_critical
        self.throttle_temp = throttle_temp
        self.logger = self._setup_logging()
        self._throttle_active = False

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("ThermalWatchdog")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_ps(self, command: str) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-Command", command],
                capture_output=True,
                text=True,
                timeout=10,
            )
            return result.returncode == 0, result.stdout
        except Exception:
            return False, ""

    def get_laptop_state(self) -> LaptopState:
        """Detect if laptop lid is open or closed."""
        # Method 1: Check power state changes
        success, output = self._run_ps(
            "(Get-CimInstance -ClassName Win32_SystemEnclosure | Select-Object -ExpandProperty ChassisTypes)"
        )

        if success and output.strip():
            # 10 = Desktop, 8 = Portable, 9 = Laptop
            chassis = output.strip()
            if "8" in chassis or "9" in chassis:
                # It's a laptop, check lid state via power
                success, output = self._run_ps(
                    "(Get-CimInstance -ClassName Win32_PowerMeter).IsActive"
                )
                # If power meter not active, likely closed
                if not success or "True" not in output:
                    return LaptopState.CLOSED

        # Method 2: Check if display is on
        success, output = self._run_ps(
            "(Get-CimInstance -Namespace root/wmi -ClassName WmiMonitorID).Active"
        )
        if success:
            if "True" in output:
                return LaptopState.OPEN
            else:
                return LaptopState.CLOSED

        return LaptopState.UNKNOWN

    def get_cpu_temp(self) -> Optional[float]:
        """Get CPU temperature."""
        # Try WMI
        success, output = self._run_ps(
            "Get-WmiObject MSAcpi_ThermalZoneTemperature -Namespace root/wmi | "
            "Select-Object -First 1 -ExpandProperty CurrentTemperature"
        )

        if success and output.strip():
            try:
                temp_k = float(output.strip())
                return (temp_k - 2732) / 10
            except:
                pass

        # Try OpenHardwareMonitor
        success, output = self._run_ps(
            "Get-WmiObject -Namespace root/OpenHardwareMonitor -Class Sensor | "
            "Where-Object {$_.SensorType -eq 'Temperature'} | "
            "Select-Object -First 1 -ExpandProperty Value"
        )

        if success and output.strip():
            try:
                return float(output.strip())
            except:
                pass

        return None

    def get_gpu_temp(self) -> Optional[float]:
        """Get GPU temperature."""
        # Try NVIDIA
        success, output = self._run_ps(
            "nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits"
        )
        if success and output.strip():
            try:
                return float(output.strip())
            except:
                pass

        # Try AMD
        success, output = self._run_ps(
            "Get-WmiObject -Namespace root/WMI -Class AMDGPUEventLog | "
            "Select-Object -First 1 -ExpandProperty Temperature"
        )

        return None

    def get_power_state(self) -> Dict:
        """Get power state info."""
        success, output = self._run_ps(
            "Get-CimInstance -ClassName Win32_Battery | "
            "Select-Object BatteryStatus, EstimatedChargeRemaining | ConvertTo-Json"
        )

        if success and output.strip():
            try:
                import json

                data = json.loads(output)
                return {
                    "on_battery": data.get("BatteryStatus") == 1,
                    "percent": data.get("EstimatedChargeRemaining", 100),
                    "charging": data.get("BatteryStatus") == 2,
                }
            except:
                pass

        return {"on_battery": False, "percent": 100, "charging": False}

    def get_power_plan(self) -> str:
        """Get current power plan."""
        success, output = self._run_ps(
            "(Get-WmiObject -Class Win32_PowerPlan -Namespace root/cimv2/power | "
            "Where-Object {$_.IsActive -eq $true}).InstanceID"
        )

        if success and output.strip():
            guid = output.strip().lower()
            if "8c5e7fda" in guid:
                return "High Performance"
            elif "381b4222" in guid:
                return "Balanced"
            elif "a1841308" in guid:
                return "Power Saver"

        return "Unknown"

    def set_power_plan(self, plan: str) -> bool:
        """Set power plan."""
        plans = {
            "power_saver": "a1841308-3541-4fab-bc81-f71556f20b4a",
            "balanced": "381b4222-f694-41f0-9685-ff5bb260df2e",
            "high_performance": "8c5e7fda-e8bf-4a96-9a85-a6e23a8c635c",
        }

        guid = plans.get(plan.lower().replace(" ", "_"))
        if not guid:
            return False

        success, _ = self._run_ps(f"powercfg /setactive {guid}")
        if success:
            self.logger.info(f"Power plan changed to {plan}")
        return success

    def determine_thermal_state(
        self, cpu_temp: float, gpu_temp: Optional[float]
    ) -> ThermalState:
        """Determine thermal state."""
        max_temp = max(cpu_temp, gpu_temp or 0)

        if max_temp < 50:
            return ThermalState.COOL
        elif max_temp < 65:
            return ThermalState.NORMAL
        elif max_temp < self.temp_warning:
            return ThermalState.WARM
        elif max_temp < self.temp_critical:
            return ThermalState.HOT
        else:
            return ThermalState.CRITICAL

    def should_throttle(
        self, state: LaptopState, thermal: ThermalState, is_battery: bool
    ) -> bool:
        """Determine if throttling should be active."""
        # Throttle if closed (in bag) and any warmth
        if state == LaptopState.CLOSED and thermal in [
            ThermalState.WARM,
            ThermalState.HOT,
            ThermalState.CRITICAL,
        ]:
            return True

        # Throttle if critical temp
        if thermal == ThermalState.CRITICAL:
            return True

        # Throttle if hot and on battery
        if thermal == ThermalState.HOT and is_battery:
            return True

        return False

    def execute_throttle(self) -> Dict:
        """Execute throttling measures."""
        self.logger.warning("Activating thermal throttle!")

        actions = []

        # Set power saver
        if self.set_power_plan("power_saver"):
            actions.append("power_plan:power_saver")

        # Reduce WSL memory
        try:
            subprocess.run(["wsl", "--shutdown"], capture_output=True, timeout=30)
            actions.append("wsl_shutdown")
        except:
            pass

        self._throttle_active = True

        return {
            "success": True,
            "actions": actions,
            "timestamp": datetime.now().isoformat(),
        }

    def release_throttle(self) -> Dict:
        """Release throttling."""
        self.logger.info("Releasing thermal throttle")

        actions = []

        if self.set_power_plan("balanced"):
            actions.append("power_plan:balanced")

        self._throttle_active = False

        return {
            "success": True,
            "actions": actions,
            "timestamp": datetime.now().isoformat(),
        }

    def get_report(self) -> ThermalReport:
        """Generate thermal report."""
        laptop_state = self.get_laptop_state()
        cpu_temp = self.get_cpu_temp() or 0
        gpu_temp = self.get_gpu_temp()
        thermal_state = self.determine_thermal_state(cpu_temp, gpu_temp)
        power_plan = self.get_power_plan()
        power = self.get_power_state()

        should_throttle = self.should_throttle(
            laptop_state, thermal_state, power["on_battery"]
        )

        # Auto-throttle if needed
        if should_throttle and not self._throttle_active:
            self.execute_throttle()
        elif not should_throttle and self._throttle_active:
            self.release_throttle()

        return ThermalReport(
            laptop_state=laptop_state,
            cpu_temp_c=cpu_temp,
            gpu_temp_c=gpu_temp,
            thermal_state=thermal_state,
            power_plan=power_plan,
            is_battery=power["on_battery"],
            battery_percent=power["percent"],
            should_throttle=should_throttle,
        )


def run_thermal_check() -> Dict:
    """Quick thermal check."""
    watchdog = ThermalWatchdog()
    report = watchdog.get_report()

    return {
        "timestamp": datetime.now().isoformat(),
        "laptop_state": report.laptop_state.value,
        "cpu_temp_c": report.cpu_temp_c,
        "gpu_temp_c": report.gpu_temp_c,
        "thermal_state": report.thermal_state.value,
        "power_plan": report.power_plan,
        "on_battery": report.is_battery,
        "battery_percent": report.battery_percent,
        "should_throttle": report.should_throttle,
    }


if __name__ == "__main__":
    import argparse
    import json

    parser = argparse.ArgumentParser(description="Thermal Watchdog")
    parser.add_argument("--report", action="store_true", help="Full report")
    parser.add_argument("--throttle", action="store_true", force="Activate throttle")

    args = parser.parse_args()

    if args.report:
        print(json.dumps(run_thermal_check(), indent=2))
    else:
        print(json.dumps(run_thermal_check(), indent=2))
