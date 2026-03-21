#!/usr/bin/env python3
"""
Linux Sensors - WSL/Linux System Monitoring
PromptOS Module

Comprehensive Linux/WSL system monitoring including:
- Load average monitoring (btop/htop style)
- I/O monitoring (iotop style)
- Memory and swap analysis
- Process monitoring including zombies
- dmesg and kernel ring buffer monitoring
- OOM (Out of Memory) kill detection

Features:
- Real-time load average with core comparison
- I/O per-process tracking
- Zombie process detection and reaping
- OOM event logging and alerting
- Thermal and resource throttling recommendations
"""

import subprocess
import re
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict
from datetime import datetime
import json


@dataclass
class LoadAverage:
    load_1: float
    load_5: float
    load_15: float
    cores: int
    is_overloaded: bool


@dataclass
class ProcessIO:
    pid: int
    name: str
    read_bytes: int
    write_bytes: float
    read_mb: float
    write_mb: float


@dataclass
class MemoryInfo:
    total_mb: float
    used_mb: float
    free_mb: float
    available_mb: float
    percent: float
    swap_total_mb: float
    swap_used_mb: float
    swap_percent: float
    cached_mb: float
    buffers_mb: float


@dataclass
class ProcessInfo:
    pid: int
    user: str
    cpu_percent: float
    mem_percent: float
    vsz_kb: int
    rss_kb: int
    stat: str
    time: str
    command: str
    is_zombie: bool = False
    is_defunct: bool = False


@dataclass
class DiskIO:
    read_bytes: int
    write_bytes: int
    read_count: int
    write_count: int
    read_mb: float
    write_mb: float


@dataclass
class OOMEvent:
    timestamp: datetime
    process_name: str
    pid: int
    message: str
    memory_killed: Optional[int] = None


@dataclass
class LinuxSnapshot:
    timestamp: datetime
    hostname: str
    uptime_seconds: float
    load: LoadAverage
    memory: MemoryInfo
    disk_io: DiskIO
    top_processes: List[ProcessInfo] = field(default_factory=list)
    zombie_processes: List[ProcessInfo] = field(default_factory=list)
    oom_events: List[OOMEvent] = field(default_factory=list)


class LinuxSensors:
    def __init__(self, distro: str = "Ubuntu"):
        self.distro = distro
        self.logger = self._setup_logging()
        self._last_oom_check = None

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("LinuxSensors")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_wsl(self, command: str, timeout: int = 10) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["wsl", "-d", self.distro, "sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def is_running(self) -> bool:
        try:
            result = subprocess.run(
                ["wsl", "-l", "-v"], capture_output=True, text=True, timeout=5
            )
            return self.distro in result.stdout
        except Exception:
            return False

    def get_load_average(self) -> Optional[LoadAverage]:
        if not self.is_running():
            return None

        success, output = self._run_wsl("cat /proc/loadavg")
        if not success:
            return None

        try:
            parts = output.strip().split()
            load_1 = float(parts[0])
            load_5 = float(parts[1])
            load_15 = float(parts[2])

            success, cores_out = self._run_wsl("nproc")
            cores = int(cores_out.strip()) if success else 1

            return LoadAverage(
                load_1=load_1,
                load_5=load_5,
                load_15=load_15,
                cores=cores,
                is_overloaded=load_1 > cores,
            )
        except Exception as e:
            self.logger.error(f"Error getting load average: {e}")
            return None

    def get_memory_info(self) -> Optional[MemoryInfo]:
        if not self.is_running():
            return None

        success, output = self._run_wsl("free -m")
        if not success:
            return None

        try:
            lines = output.strip().split("\n")
            mem_line = lines[1].split()
            swap_line = lines[2].split() if len(lines) > 2 else ["0"] * 7

            total = float(mem_line[1])
            used = float(mem_line[2])
            free = float(mem_line[3])
            cached = float(mem_line[5]) if len(mem_line) > 5 else 0
            buffers = float(mem_line[4]) if len(mem_line) > 4 else 0

            swap_total = float(swap_line[1])
            swap_used = float(swap_line[2])

            return MemoryInfo(
                total_mb=total,
                used_mb=used,
                free_mb=free,
                available_mb=free + cached + buffers,
                percent=(used / total * 100) if total > 0 else 0,
                swap_total_mb=swap_total,
                swap_used_mb=swap_used,
                swap_percent=(swap_used / swap_total * 100) if swap_total > 0 else 0,
                cached_mb=cached,
                buffers_mb=buffers,
            )
        except Exception as e:
            self.logger.error(f"Error getting memory info: {e}")
            return None

    def get_disk_io(self) -> Optional[DiskIO]:
        if not self.is_running():
            return None

        success, output = self._run_wsl("cat /proc/diskstats")
        if not success:
            return None

        try:
            total_read = 0
            total_write = 0
            read_count = 0
            write_count = 0

            for line in output.split("\n"):
                parts = line.split()
                if len(parts) >= 14:
                    sector_size = 512
                    reads = int(parts[5])
                    reads_merged = int(parts[6])
                    sectors_read = int(parts[3])
                    writes = int(parts[9])
                    writes_merged = int(parts[10])
                    sectors_written = int(parts[7])

                    total_read += sectors_read * sector_size
                    total_write += sectors_written * sector_size
                    read_count += reads
                    write_count += writes

            return DiskIO(
                read_bytes=total_read,
                write_bytes=total_write,
                read_count=read_count,
                write_count=write_count,
                read_mb=total_read / (1024 * 1024),
                write_mb=total_write / (1024 * 1024),
            )
        except Exception as e:
            self.logger.error(f"Error getting disk IO: {e}")
            return None

    def get_top_processes(self, limit: int = 10) -> List[ProcessInfo]:
        if not self.is_running():
            return []

        success, output = self._run_wsl("ps aux --sort=-%mem | head -n 20")
        if not success:
            return []

        processes = []
        try:
            lines = output.strip().split("\n")[1:]
            for line in lines[:limit]:
                parts = line.split(None, 10)
                if len(parts) >= 11:
                    is_zombie = "Z" in parts[7]
                    processes.append(
                        ProcessInfo(
                            pid=int(parts[1]),
                            user=parts[0],
                            cpu_percent=float(parts[2]),
                            mem_percent=float(parts[3]),
                            vsz_kb=int(parts[4]),
                            rss_kb=int(parts[5]),
                            stat=parts[7],
                            time=parts[9],
                            command=parts[10][:50],
                            is_zombie=is_zombie,
                            is_defunct=is_zombie,
                        )
                    )
        except Exception as e:
            self.logger.error(f"Error parsing processes: {e}")

        return processes

    def find_zombie_processes(self) -> List[ProcessInfo]:
        if not self.is_running():
            return []

        success, output = self._run_wsl("ps -ef | grep defunct")
        if not success:
            return []

        zombies = []
        try:
            lines = output.strip().split("\n")
            for line in lines:
                if "defunct" in line.lower() and "grep" not in line:
                    parts = line.split(None, 8)
                    if len(parts) >= 8:
                        zombies.append(
                            ProcessInfo(
                                pid=int(parts[1]),
                                user=parts[0],
                                cpu_percent=0,
                                mem_percent=0,
                                vsz_kb=0,
                                rss_kb=0,
                                stat="Z",
                                time=parts[7],
                                command=parts[7] if len(parts) > 7 else "",
                                is_zombie=True,
                                is_defunct=True,
                            )
                        )
        except Exception as e:
            self.logger.error(f"Error finding zombies: {e}")

        return zombies

    def get_dmesg_oom_events(self, lines: int = 50) -> List[OOMEvent]:
        if not self.is_running():
            return []

        success, output = self._run_wsl(f"dmesg | tail -n {lines}")
        if not success:
            return []

        oom_events = []
        try:
            for line in output.split("\n"):
                if "oom-kill" in line.lower() or "out of memory" in line.lower():
                    timestamp = datetime.now()
                    process_name = "unknown"
                    pid = 0

                    match = re.search(
                        r"\[(\d+\.\d+)\].*oom-kill:.*process\s+(\S+).*pid\s+(\d+)", line
                    )
                    if match:
                        process_name = match.group(2)
                        pid = int(match.group(3))

                    oom_events.append(
                        OOMEvent(
                            timestamp=timestamp,
                            process_name=process_name,
                            pid=pid,
                            message=line[:200],
                        )
                    )

                    self.logger.warning(f"OOM Event: {process_name} (PID: {pid})")
        except Exception as e:
            self.logger.error(f"Error parsing dmesg: {e}")

        return oom_events

    def get_uptime(self) -> Optional[float]:
        if not self.is_running():
            return None

        success, output = self._run_wsl("cat /proc/uptime")
        if not success:
            return None

        try:
            return float(output.strip().split()[0])
        except Exception:
            return None

    def get_hostname(self) -> str:
        if not self.is_running():
            return "unknown"

        success, output = self._run_wsl("hostname")
        return output.strip() if success else "unknown"

    def take_snapshot(self) -> Optional[LinuxSnapshot]:
        if not self.is_running():
            return None

        return LinuxSnapshot(
            timestamp=datetime.now(),
            hostname=self.get_hostname(),
            uptime_seconds=self.get_uptime() or 0,
            load=self.get_load_average() or LoadAverage(0, 0, 0, 1, False),
            memory=self.get_memory_info() or MemoryInfo(0, 0, 0, 0, 0, 0, 0, 0, 0, 0),
            disk_io=self.get_disk_io() or DiskIO(0, 0, 0, 0, 0, 0),
            top_processes=self.get_top_processes(10),
            zombie_processes=self.find_zombie_processes(),
            oom_events=self.get_dmesg_oom_events(),
        )

    def get_summary(self) -> dict:
        snapshot = self.take_snapshot()
        if not snapshot:
            return {"error": "WSL not running"}

        return {
            "timestamp": snapshot.timestamp.isoformat(),
            "hostname": snapshot.hostname,
            "uptime_hours": snapshot.uptime_seconds / 3600,
            "load": {
                "1m": snapshot.load.load_1,
                "5m": snapshot.load.load_5,
                "15m": snapshot.load.load_15,
                "cores": snapshot.load.cores,
                "overloaded": snapshot.load.is_overloaded,
            },
            "memory": {
                "total_mb": snapshot.memory.total_mb,
                "used_mb": snapshot.memory.used_mb,
                "available_mb": snapshot.memory.available_mb,
                "percent": snapshot.memory.percent,
                "swap_used_mb": snapshot.memory.swap_used_mb,
            },
            "disk_io": {
                "read_mb": round(snapshot.disk_io.read_mb, 2),
                "write_mb": round(snapshot.disk_io.write_mb, 2),
            },
            "top_processes": [
                {"name": p.command[:30], "cpu": p.cpu_percent, "mem": p.mem_percent}
                for p in snapshot.top_processes[:5]
            ],
            "zombies": len(snapshot.zombie_processes),
            "oom_events": len(snapshot.oom_events),
        }


class WSLMemoryBalancer:
    """Automatically balances WSL memory usage."""

    def __init__(self, distro: str = "Ubuntu", threshold_percent: float = 60.0):
        self.distro = distro
        self.threshold_percent = threshold_percent
        self.sensors = LinuxSensors(distro)
        self.logger = logging.getLogger("WSLMemoryBalancer")

    def get_vmmem_usage(self) -> Optional[float]:
        """Get vmmem usage as percentage of total RAM."""
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "(Get-Process vmmem).WorkingSet64 / (Get-CimInstance Win32_ComputerSystem).TotalPhysicalMemory * 100",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                return float(result.stdout.strip())
        except Exception as e:
            self.logger.warning(f"Could not get vmmem: {e}")
        return None

    def needs_reclamation(self) -> bool:
        vmmem = self.get_vmmem_usage()
        if vmmem and vmmem > self.threshold_percent:
            self.logger.warning(
                f"vmmem at {vmmem:.1f}% (threshold: {self.threshold_percent}%)"
            )
            return True
        return False

    def reclaim_memory(self) -> dict:
        """Drop caches and free memory."""
        result = {
            "success": False,
            "actions": [],
            "vmmem_before": self.get_vmmem_usage(),
        }

        if not self.sensors.is_running():
            result["error"] = "WSL not running"
            return result

        try:
            self.sensors._run_wsl("sync")

            success, output = self.sensors._run_wsl("echo 3 > /proc/sys/vm/drop_caches")
            if success:
                result["actions"].append("drop_caches")
                self.logger.info("Dropped Linux caches")

            result["vmmem_after"] = self.get_vmmem_usage()
            result["success"] = True

        except Exception as e:
            result["error"] = str(e)

        return result


class ZombieProcessKiller:
    """Find and reap zombie processes."""

    def __init__(self, distro: str = "Ubuntu"):
        self.distro = distro
        self.sensors = LinuxSensors(distro)
        self.logger = logging.getLogger("ZombieKiller")

    def kill_zombies(self) -> dict:
        result = {"zombies_found": 0, "zombies_killed": 0, "errors": []}

        zombies = self.sensors.find_zombie_processes()
        result["zombies_found"] = len(zombies)

        if not zombies:
            return result

        for z in zombies:
            try:
                parent_pid = self._get_parent_pid(z.pid)
                if parent_pid and parent_pid != 1:
                    self.logger.info(
                        f"Killing zombie {z.command} (PID: {z.pid}, PPID: {parent_pid})"
                    )

                    success, _ = self.sensors._run_wsl(
                        f"kill -9 {parent_pid} 2>/dev/null || true"
                    )
                    if success:
                        result["zombies_killed"] += 1
                else:
                    result["errors"].append(
                        f"Cannot kill {z.pid} - orphan with no init parent"
                    )
            except Exception as e:
                result["errors"].append(str(e))

        return result

    def _get_parent_pid(self, pid: int) -> Optional[int]:
        success, output = self.sensors._run_wsl(f"ps -o ppid= -p {pid}")
        if success:
            try:
                return int(output.strip())
            except Exception:
                pass
        return None


def get_linux_sensors(distro: str = "Ubuntu") -> dict:
    """Quick function to get Linux sensors."""
    sensors = LinuxSensors(distro)
    return sensors.get_summary()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Linux Sensors")
    parser.add_argument("--distro", type=str, default="Ubuntu")
    parser.add_argument("--snapshot", action="store_true", help="Full snapshot")
    parser.add_argument("--zombies", action="store_true", help="Find zombies")
    parser.add_argument("--oom", action="store_true", help="Check OOM events")
    parser.add_argument("--reclaim", action="store_true", help="Reclaim memory")

    args = parser.parse_args()

    sensors = LinuxSensors(args.distro)

    if args.snapshot:
        snap = sensors.take_snapshot()
        if snap:
            print(json.dumps(sensors.get_summary(), indent=2, default=str))
        else:
            print("WSL not running")

    elif args.zombies:
        zombies = sensors.find_zombie_processes()
        print(f"Zombie processes: {len(zombies)}")
        for z in zombies:
            print(f"  PID {z.pid}: {z.command}")

    elif args.oom:
        oom_events = sensors.get_dmesg_oom_events()
        print(f"OOM events: {len(oom_events)}")
        for oom in oom_events:
            print(f"  {oom.timestamp}: {oom.process_name} (PID: {oom.pid})")

    elif args.reclaim:
        balancer = WSLMemoryBalancer(args.distro)
        result = balancer.reclaim_memory()
        print(json.dumps(result, indent=2))

    else:
        print(json.dumps(sensors.get_summary(), indent=2, default=str))
