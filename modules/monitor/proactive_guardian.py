#!/usr/bin/env python3
"""
Proactive Guardian - AI-Powered Auto-Healing System
PromptOS Module

The ultimate proactive system guardian that:
- Monitors all sensors (Windows, WSL, Network)
- Uses AI (Ollama) to make intelligent decisions
- Automatically triggers healing actions
- Logs everything with heartbeat reports
- Learns patterns from past decisions

Auto-Healing Triggers:
- RAM > 60%: WSL memory reclaim
- RAM > 80%: Windows cleanup + WSL reclaim
- RAM > 90%: Aggressive cleanup
- Disk > 85%: WSL trim
- Disk > 90%: WSL shrink + Windows cleanup
- Load average > cores: Throttle processes
- Temperature > 85°C: Thermal throttle
- Temperature > 90°C: Aggressive throttle
- OOM events: Log and alert
- Zombie processes: Reap
- Network down: Log and retry
"""

import time
import logging
import threading
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
import json


@dataclass
class GuardianConfig:
    # Memory thresholds
    wsl_memory_threshold: float = 60.0
    windows_memory_warning: float = 70.0
    windows_memory_critical: float = 85.0

    # Disk thresholds
    disk_warning: float = 80.0
    disk_critical: float = 90.0

    # CPU thresholds
    load_threshold_ratio: float = 1.0  # load / cores
    cpu_critical: float = 95.0

    # Temperature thresholds
    temp_warning: float = 80.0
    temp_critical: float = 90.0

    # Intervals
    check_interval: int = 60  # seconds
    heartbeat_interval: int = 60  # seconds

    # Features
    auto_heal: bool = True
    use_ai: bool = True
    log_heartbeats: bool = True

    # WSL
    wsl_distro: str = "Ubuntu"


class ProactiveGuardian:
    """
    The main proactive guardian that monitors everything and auto-heals.
    """

    def __init__(self, config: GuardianConfig = None):
        self.config = config or GuardianConfig()
        self.logger = self._setup_logging()

        self._running = False
        self._health_history: List[Dict] = []

        self._init_modules()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("ProactiveGuardian")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def _init_modules(self):
        """Initialize all sensor modules."""
        self.logger.info("Initializing Guardian modules...")

        try:
            from Guardian.linux_sensors import (
                LinuxSensors,
                WSLMemoryBalancer,
                ZombieProcessKiller,
            )

            self.linux_sensors = LinuxSensors(self.config.wsl_distro)
            self.wsl_balancer = WSLMemoryBalancer(
                self.config.wsl_distro, self.config.wsl_memory_threshold
            )
            self.zombie_killer = ZombieProcessKiller(self.config.wsl_distro)
        except Exception as e:
            self.logger.warning(f"Linux sensors unavailable: {e}")
            self.linux_sensors = None
            self.wsl_balancer = None
            self.zombie_killer = None

        try:
            from Guardian.windows_sensors import WindowsSensors

            self.windows_sensors = WindowsSensors()
        except Exception as e:
            self.logger.warning(f"Windows sensors unavailable: {e}")
            self.windows_sensors = None

        try:
            from Guardian.network_monitor import NetworkMonitor

            self.network_monitor = NetworkMonitor()
        except Exception as e:
            self.logger.warning(f"Network monitor unavailable: {e}")
            self.network_monitor = None

        try:
            from Guardian.ai_guardian import AIGuardianBrain

            self.ai_brain = AIGuardianBrain()
        except Exception as e:
            self.logger.warning(f"AI brain unavailable: {e}")
            self.ai_brain = None

        try:
            from Guardian.heartbeat_logger import HeartbeatLogger

            self.heartbeat_logger = HeartbeatLogger()
        except Exception as e:
            self.logger.warning(f"Heartbeat logger unavailable: {e}")
            self.heartbeat_logger = None

        try:
            from Guardian.wsl_utils import WSLManager

            self.wsl_manager = WSLManager(self.config.wsl_distro)
        except Exception as e:
            self.logger.warning(f"WSL manager unavailable: {e}")
            self.wsl_manager = None

        try:
            from Guardian.docker_guardian import DockerGuardian

            self.docker_guardian = DockerGuardian(
                cache_prune_threshold_gb=getattr(self.config, "docker_cache_prune_threshold_gb", 3.0),
                vhd_bloat_alert_gb=getattr(self.config, "docker_vhd_bloat_alert_gb", 4.0),
                images_warn_gb=getattr(self.config, "docker_images_warn_gb", 10.0),
                auto_prune=getattr(self.config, "docker_auto_prune", True),
            )
        except Exception as e:
            self.logger.warning(f"Docker guardian unavailable: {e}")
            self.docker_guardian = None

        try:
            from Guardian.service_health import ServiceHealthMonitor
            self.service_health = ServiceHealthMonitor()
        except Exception as e:
            self.logger.warning(f"Service health monitor unavailable: {e}")
            self.service_health = None

        try:
            from Guardian.ollama_monitor import scan as ollama_scan
            self._ollama_scan = ollama_scan
        except Exception as e:
            self.logger.warning(f"Ollama monitor unavailable: {e}")
            self._ollama_scan = None

        try:
            from Guardian.docker_log_cap import check as docker_log_check
            self._docker_log_check = docker_log_check
        except Exception as e:
            self.logger.warning(f"Docker log cap unavailable: {e}")
            self._docker_log_check = None

        try:
            from Guardian.log_watcher import get_summary as log_summary
            self._log_summary = log_summary
        except Exception as e:
            self.logger.warning(f"Log watcher unavailable: {e}")
            self._log_summary = None

        # Run disk report + cache scan once at startup (background-safe)
        self._startup_complete = False

        self.logger.info("Guardian modules initialized")

    def collect_health_data(self) -> Dict[str, Any]:
        """Collect all health data from all sensors."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "windows": {},
            "wsl": {},
            "network": {},
            "docker": {},
            "services": {},
            "ollama": {},
            "logs": {},
            "issues": [],
            "alerts": [],
        }

        if self.windows_sensors:
            try:
                win_summary = self.windows_sensors.get_summary()
                data["windows"] = win_summary

                if win_summary.get("cpu_temp", {}).get("throttling"):
                    data["alerts"].append(
                        f"CPU thermal throttling: {win_summary['cpu_temp']['celsius']}°C"
                    )

                if win_summary.get("cpu_percent", 0) > self.config.cpu_critical:
                    data["issues"].append(
                        f"High CPU usage: {win_summary['cpu_percent']}%"
                    )

                if (
                    win_summary.get("memory_percent", 0)
                    > self.config.windows_memory_critical
                ):
                    data["issues"].append(
                        f"High memory usage: {win_summary['memory_percent']}%"
                    )

                for spike in win_summary.get("spikes", []):
                    if spike.get("system"):
                        data["alerts"].append(
                            f"System process spike: {spike['name']} ({spike['cpu']}%)"
                        )

            except Exception as e:
                self.logger.error(f"Windows sensors error: {e}")

        if self.linux_sensors and self.linux_sensors.is_running():
            try:
                wsl_summary = self.linux_sensors.get_summary()
                data["wsl"] = wsl_summary

                if wsl_summary.get("load", {}).get("overloaded"):
                    data["issues"].append(
                        f"WSL load overloaded: {wsl_summary['load']['1m']}"
                    )

                if wsl_summary.get("zombies", 0) > 0:
                    data["alerts"].append(f"Zombie processes: {wsl_summary['zombies']}")

                if wsl_summary.get("oom_events", 0) > 0:
                    data["issues"].append(
                        f"OOM events detected: {wsl_summary['oom_events']}"
                    )

            except Exception as e:
                self.logger.error(f"WSL sensors error: {e}")

        if self.network_monitor:
            try:
                net_summary = self.network_monitor.get_summary()
                data["network"] = net_summary

                if not net_summary.get("internet_reachable"):
                    data["alerts"].append("Internet unreachable")

            except Exception as e:
                self.logger.error(f"Network monitor error: {e}")

        if self.docker_guardian:
            try:
                docker_result = self.docker_guardian.check_and_heal()
                data["docker"] = docker_result.get("state", {})
                for alert in docker_result.get("alerts", []):
                    data["alerts"].append(alert)
                for action in docker_result.get("actions", []):
                    data["issues"].append(f"docker_auto: {action}")
            except Exception as e:
                self.logger.error(f"Docker guardian error: {e}")

        if self.service_health:
            try:
                svc_summary = self.service_health.get_summary()
                data["services"] = svc_summary
                for svc in svc_summary.get("down_services", []):
                    data["alerts"].append(
                        f"Service DOWN: {svc['name']} (:{svc['port']}) — {svc.get('error', '')}"
                    )
            except Exception as e:
                self.logger.error(f"Service health error: {e}")

        if self._ollama_scan:
            try:
                ollama_report = self._ollama_scan()
                data["ollama"] = {
                    "process_count": ollama_report.process_count,
                    "total_vram_gb": ollama_report.total_vram_gb,
                    "duplicate_loaded": ollama_report.duplicate_loaded,
                }
                for alert in ollama_report.alerts:
                    data["alerts"].append(alert)
            except Exception as e:
                self.logger.error(f"Ollama monitor error: {e}")

        if self._docker_log_check:
            try:
                log_cap = self._docker_log_check(auto_fix_daemon=True)
                for alert in log_cap.alerts:
                    data["alerts"].append(alert)
            except Exception as e:
                self.logger.error(f"Docker log cap error: {e}")

        if self._log_summary:
            try:
                log_data = self._log_summary(hours=1)
                data["logs"] = log_data
                for evt in log_data.get("top_critical", []):
                    data["alerts"].append(
                        f"CRITICAL LOG [{evt['source']}]: {evt['message'][:120]}"
                    )
                if log_data.get("critical", 0) > 0:
                    data["issues"].append(
                        f"{log_data['critical']} critical log events in last hour"
                    )
            except Exception as e:
                self.logger.error(f"Log watcher error: {e}")

        return data

    def auto_heal(self, health_data: Dict) -> List[str]:
        """Execute auto-healing based on health data."""
        actions = []

        issues = health_data.get("issues", [])
        alerts = health_data.get("alerts", [])

        win_mem = health_data.get("windows", {}).get("memory_percent", 0)
        wsl_load = health_data.get("wsl", {}).get("load", {}).get("1m", 0)
        wsl_cores = health_data.get("wsl", {}).get("load", {}).get("cores", 1)
        wsl_zombies = health_data.get("wsl", {}).get("zombies", 0)
        disk = health_data.get("windows", {}).get("disk_percent", 0)
        temp = health_data.get("windows", {}).get("cpu_temp", {}).get("celsius", 0)

        if self.config.use_ai and self.ai_brain:
            try:
                decision = self.ai_brain.make_decision()
                if decision.decision.value != "monitor":
                    self.logger.info(
                        f"AI Decision: {decision.decision.value} - {decision.reasoning}"
                    )
                    actions.append(f"ai_decision:{decision.decision.value}")
            except Exception as e:
                self.logger.warning(f"AI decision failed: {e}")

        if disk > self.config.disk_critical:
            self.logger.warning(f"Critical disk usage: {disk}%")
            if self.wsl_manager:
                try:
                    # Use wsl_utils directly
                    from Guardian.wsl_utils import shrink_wsl_disk

                    result = shrink_wsl_disk(self.config.wsl_distro)
                    if result.get("success"):
                        actions.append(
                            f"wsl_shrink:{result.get('space_saved_gb', 0):.1f}GB"
                        )
                    else:
                        actions.append(
                            f"wsl_shrink_failed:{result.get('error', 'unknown')}"
                        )
                except Exception as e:
                    self.logger.error(f"WSL shrink failed: {e}")
                    actions.append(f"wsl_shrink_error:{str(e)[:50]}")

        if win_mem > self.config.windows_memory_critical or wsl_load > wsl_cores:
            self.logger.warning(f"Memory pressure: Win {win_mem}%, WSL load {wsl_load}")

            if self.wsl_balancer:
                try:
                    result = self.wsl_balancer.reclaim_memory()
                    if result.get("success"):
                        actions.append("wsl_memory_reclaim")
                except Exception as e:
                    self.logger.error(f"WSL memory reclaim failed: {e}")

            if self.zombie_killer and wsl_zombies > 0:
                try:
                    result = self.zombie_killer.kill_zombies()
                    if result.get("zombies_killed", 0) > 0:
                        actions.append(f"zombie_kill:{result['zombies_killed']}")
                except Exception as e:
                    self.logger.error(f"Zombie kill failed: {e}")

        if temp > self.config.temp_critical:
            self.logger.warning(f"Critical temperature: {temp}°C")
            if self.windows_sensors:
                try:
                    result = self.windows_sensors.apply_thermal_throttle()
                    actions.append("thermal_throttle")
                except Exception as e:
                    self.logger.error(f"Thermal throttle failed: {e}")

        if "OOM events detected" in issues:
            self.logger.critical("OOM event detected!")
            actions.append("oom_detected")

        if not health_data.get("network", {}).get("internet_reachable", True):
            self.logger.warning("Network unreachable")
            actions.append("network_down")

        return actions

    def run_cycle(self) -> Dict[str, Any]:
        """Run one monitoring cycle."""
        self.logger.info("Running monitoring cycle...")

        health_data = self.collect_health_data()

        actions = []
        if self.config.auto_heal:
            actions = self.auto_heal(health_data)

        if self.config.log_heartbeats and self.heartbeat_logger:
            try:
                self.heartbeat_logger.heartbeat(
                    cpu=health_data.get("windows", {}).get("cpu_percent", 0),
                    ram=health_data.get("windows", {}).get("memory_percent", 0),
                    disk=health_data.get("windows", {}).get("disk_percent", 0),
                    wsl_running=bool(health_data.get("wsl", {}).get("hostname")),
                    wsl_memory=health_data.get("wsl", {})
                    .get("memory", {})
                    .get("used_mb"),
                    network_healthy=health_data.get("network", {}).get(
                        "internet_reachable", True
                    ),
                    active_distros=[self.config.wsl_distro]
                    if health_data.get("wsl", {}).get("hostname")
                    else [],
                    issues=health_data.get("issues", []),
                    actions=actions,
                )
            except Exception as e:
                self.logger.error(f"Heartbeat failed: {e}")

        return {"health": health_data, "actions": actions}

    def start(self, duration: Optional[int] = None):
        """Start the proactive guardian."""
        self._running = True
        start_time = time.time()

        print("=" * 50)
        print("  PROACTIVE GUARDIAN STARTED")
        print("=" * 50)
        print(f"Auto-heal: {self.config.auto_heal}")
        print(f"AI Brain: {self.config.use_ai}")
        print(f"Check interval: {self.config.check_interval}s")
        print(f"WSL Distro: {self.config.wsl_distro}")
        print("=" * 50)

        # Run startup scans (disk report + cache sweep) in background thread
        if not self._startup_complete:
            threading.Thread(target=self._run_startup_scans, daemon=True).start()

        while self._running:
            try:
                result = self.run_cycle()

                issues = result["health"].get("issues", [])
                actions = result["actions"]

                if issues:
                    print(f"\n[!] Issues: {', '.join(issues)}")

                if actions:
                    print(f"[+] Actions: {', '.join(actions)}")

                if duration and (time.time() - start_time) >= duration:
                    break

                time.sleep(self.config.check_interval)

            except KeyboardInterrupt:
                print("\nStopping Guardian...")
                break
            except Exception as e:
                self.logger.error(f"Monitoring cycle error: {e}")
                time.sleep(self.config.check_interval)

        self._running = False
        print("Guardian stopped.")

    def _run_startup_scans(self):
        """Run slow one-off scans at startup and log findings."""
        self.logger.info("Running startup scans (disk report + cache sweep)...")
        try:
            from Guardian.disk_report import scan as disk_scan, print_report
            report = disk_scan()
            print_report(report)
            if report.reclaimable_gb >= 2.0:
                self.logger.warning(
                    f"Startup disk scan: {report.reclaimable_gb:.1f}GB reclaimable. "
                    f"Top hog: {report.top_10[0].label if report.top_10 else 'n/a'}"
                )
        except Exception as e:
            self.logger.error(f"Startup disk scan error: {e}")

        try:
            from Guardian.stale_cache_cleaner import scan as cache_scan
            cache_report = cache_scan()
            if cache_report.total_gb >= 1.0:
                self.logger.warning(
                    f"Startup cache scan: {cache_report.total_gb:.1f}GB in stale caches. "
                    f"Top: {cache_report.entries[0].label if cache_report.entries else 'n/a'}"
                )
        except Exception as e:
            self.logger.error(f"Startup cache scan error: {e}")

        try:
            from Guardian.docker_log_cap import check as dlc_check
            dlc_check(auto_fix_daemon=True)
        except Exception as e:
            self.logger.error(f"Startup docker log cap error: {e}")

        self._startup_complete = True
        self.logger.info("Startup scans complete.")

    def stop(self):
        """Stop the guardian."""
        self._running = False

    def run_once(self) -> Dict[str, Any]:
        """Run a single monitoring cycle."""
        return self.run_cycle()


def create_guardian(**kwargs) -> ProactiveGuardian:
    """Create a proactive guardian with custom config."""
    config = GuardianConfig(**kwargs)
    return ProactiveGuardian(config)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Proactive Guardian")
    parser.add_argument("--once", action="store_true", help="Run once instead of loop")
    parser.add_argument("--no-ai", action="store_true", help="Disable AI brain")
    parser.add_argument(
        "--interval", type=int, default=60, help="Check interval (seconds)"
    )
    parser.add_argument("--duration", type=int, help="Run for N seconds")
    parser.add_argument("--distro", type=str, default="Ubuntu", help="WSL distro name")

    args = parser.parse_args()

    config = GuardianConfig(
        check_interval=args.interval, use_ai=not args.no_ai, wsl_distro=args.distro
    )

    guardian = ProactiveGuardian(config)

    if args.once:
        result = guardian.run_once()
        print(json.dumps(result, indent=2, default=str))
    else:
        guardian.start(duration=args.duration)
