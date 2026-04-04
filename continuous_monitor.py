#!/usr/bin/env python3
"""
Guardian Continuous Monitor
Runs Guardian monitoring loop continuously with auto-healing and Docker management
"""

import sys
import os
import time
import threading
import json

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Guardian.config import GuardianSettings
from Guardian.modules.alerts import TelegramAlerts
from Guardian.modules.sensors import WindowsSensors
from Guardian.modules.wsl import WSLManager
from Guardian.modules.network import NetworkMonitor
from Guardian.modules.network import PortScanner
from Guardian.modules.performance import ReclamationEngine
from Guardian.modules.database import GuardianDB
from Guardian.modules.docker import DockerGuardian
from datetime import datetime

# Config
CHECK_INTERVAL = 60  # seconds
OLLAMA_MAX = 3
DOCKER_CHECK_INTERVAL = 300  # Check Docker every 5 minutes


class GuardianMonitor:
    def __init__(self):
        self.config = GuardianSettings()
        self.alerts = TelegramAlerts()

        # Setup DB
        pg_config = {
            "host": self.config.db_host,
            "port": self.config.db_port,
            "database": self.config.db_name,
            "user": self.config.db_user,
            "password": self.config.db_password,
        }
        self.db = GuardianDB(pg_config=pg_config, qdrant_url=self.config.qdrant_url)

        # Docker Guardian
        self.docker = DockerGuardian(
            cache_prune_threshold_gb=self.config.docker_cache_prune_threshold_gb,
            vhd_bloat_alert_gb=self.config.docker_vhd_bloat_alert_gb,
            images_warn_gb=self.config.docker_images_warn_gb,
            auto_prune=self.config.docker_auto_prune,
        )

        self.running = True
        self.last_docker_check = 0

    def initialize(self):
        """Initialize Guardian with daemon configuration."""
        print("Initializing Guardian Monitor...")

        # Initialize Docker auto-cleanup
        docker_init = self.docker.initialize(restart_daemon=False)
        if docker_init.get("changes"):
            print(f"  Docker: {'; '.join(docker_init['changes'])}")
        if docker_init.get("errors"):
            print(f"  Docker errors: {'; '.join(docker_init['errors'])}")

        # Send startup alert
        self.alerts.send_alert(
            "info",
            "Guardian Monitor Started",
            f"Monitoring every {CHECK_INTERVAL}s\n"
            f"Docker check every {DOCKER_CHECK_INTERVAL}s\n"
            f"Ollama max: {OLLAMA_MAX}",
        )

    def check_system(self):
        """Check all system metrics"""
        issues = []
        actions = []

        # Windows
        ws = WindowsSensors()
        snap = ws.take_snapshot()

        if snap.cpu_percent > 80:
            issues.append(f"CPU HIGH: {snap.cpu_percent:.0f}%")
        if snap.memory_percent > 80:
            issues.append(f"RAM HIGH: {snap.memory_percent:.0f}%")
        if snap.disk_percent > 90:
            issues.append(f"DISK CRITICAL: {snap.disk_percent:.0f}%")
            actions.append("disk_cleanup_needed")
        elif snap.disk_percent > 80:
            issues.append(f"DISK WARNING: {snap.disk_percent:.0f}%")

        # Ollama
        ps = PortScanner()
        ollama_count = ps.count_ollama_instances()

        if ollama_count > OLLAMA_MAX:
            issues.append(f"Ollama EXCESS: {ollama_count} instances")
            # Auto-fix
            result = ps.kill_excess_ollama(max_instances=OLLAMA_MAX)
            actions.append(f"killed_{result['killed']}_ollama")

        # Network
        nm = NetworkMonitor()
        if not nm.check_internet():
            issues.append("Network DOWN")

        # WSL Memory gap
        re = ReclamationEngine()
        gap = re.check_memory_gap()
        if gap.get("needs_reclaim"):
            issues.append(f"WSL Memory gap: {gap.get('gap_mb', 0):.0f}MB")

        return {
            "cpu": snap.cpu_percent,
            "ram": snap.memory_percent,
            "disk": snap.disk_percent,
            "ollama": ollama_count,
            "issues": issues,
            "actions": actions,
        }

    def check_docker(self):
        """Check Docker disk usage and health."""
        issues = []
        actions = []

        result = self.docker.check_and_heal()
        state = result.get("state", {})

        if state.get("docker_running"):
            # Track Docker metrics
            issues.extend(result.get("alerts", []))
            actions.extend(result.get("actions", []))
        else:
            issues.append(f"Docker status: {state.get('error', 'unknown')}")

        return {
            "docker_running": state.get("docker_running", False),
            "build_cache_gb": state.get("build_cache_gb", 0),
            "images_gb": state.get("images_size_gb", 0),
            "containers_gb": state.get("containers_size_gb", 0),
            "vhd_bloat_gb": state.get("vhd_bloat_gb", 0),
            "issues": issues,
            "actions": actions,
        }

    def save_to_db(self, status, docker_status=None):
        """Save status to database"""
        try:
            metrics = {
                "cpu": status["cpu"],
                "ram": status["ram"],
                "disk": status["disk"],
                "ollama": status["ollama"],
            }

            if docker_status:
                metrics.update(
                    {
                        "docker_running": docker_status["docker_running"],
                        "docker_build_cache_gb": docker_status["build_cache_gb"],
                        "docker_images_gb": docker_status["images_gb"],
                        "docker_containers_gb": docker_status["containers_gb"],
                        "docker_vhd_bloat_gb": docker_status["vhd_bloat_gb"],
                    }
                )

            issues = status.get("issues", [])
            if docker_status:
                issues.extend(docker_status.get("issues", []))

            actions = status.get("actions", [])
            if docker_status:
                actions.extend(docker_status.get("actions", []))

            self.db.save_decision(
                {
                    "timestamp": datetime.now().isoformat(),
                    "metrics": metrics,
                    "decision": "monitor",
                    "confidence": "high",
                    "reasoning": "; ".join(issues) if issues else "All OK",
                    "actions_taken": actions,
                }
            )
        except Exception as e:
            print(f"DB save error: {e}")

    def send_alerts(self, status, docker_status=None):
        """Send Telegram alerts if needed"""
        all_issues = status.get("issues", [])
        all_actions = status.get("actions", [])

        if docker_status:
            all_issues.extend(docker_status.get("issues", []))
            all_actions.extend(docker_status.get("actions", []))

        if all_issues:
            # Critical issues
            critical = [
                i
                for i in all_issues
                if "CRITICAL" in i or "EXCESS" in i or "bloat" in i.lower()
            ]
            if critical:
                self.alerts.send_alert("critical", "Guardian Alert", "; ".join(critical))

            # Warnings
            warnings = [i for i in all_issues if i not in critical]
            if warnings:
                self.alerts.send_alert("warning", "Guardian Warning", "; ".join(warnings))

        if all_actions:
            self.alerts.send_alert("info", "Guardian Action", "; ".join(all_actions))

    def run_cycle(self):
        """Run one monitoring cycle"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking system...")

        status = self.check_system()
        docker_status = None

        # Check Docker periodically
        now = time.time()
        if now - self.last_docker_check >= DOCKER_CHECK_INTERVAL:
            docker_status = self.check_docker()
            self.last_docker_check = now

        # Report
        print(
            f"  CPU:{status['cpu']:.0f}% RAM:{status['ram']:.0f}% Disk:{status['disk']:.0f}% Ollama:{status['ollama']}"
        )

        if docker_status:
            print(
                f"  Docker: Cache={docker_status['build_cache_gb']:.1f}GB Images={docker_status['images_gb']:.1f}GB VHD_bloat={docker_status['vhd_bloat_gb']:.1f}GB"
            )

        if status["issues"]:
            print(f"  Issues: {status['issues']}")
        if docker_status and docker_status.get("issues"):
            print(f"  Docker Issues: {docker_status['issues']}")

        if status["actions"]:
            print(f"  Actions: {status['actions']}")
        if docker_status and docker_status.get("actions"):
            print(f"  Docker Actions: {docker_status['actions']}")

        # Save and alert
        self.save_to_db(status, docker_status)
        self.send_alerts(status, docker_status)

        return status, docker_status

    def run(self):
        """Main loop"""
        print("=" * 60)
        print("GUARDIAN MONITOR STARTED")
        print(f"System check interval: {CHECK_INTERVAL}s")
        print(f"Docker check interval: {DOCKER_CHECK_INTERVAL}s")
        print(f"Ollama max instances: {OLLAMA_MAX}")
        print("=" * 60)
        print()

        self.initialize()

        while self.running:
            try:
                self.run_cycle()
            except Exception as e:
                print(f"Error: {e}")

            time.sleep(CHECK_INTERVAL)

    def stop(self):
        """Stop monitoring"""
        self.running = False
        self.db.close()
        self.alerts.send_alert("info", "Guardian Stopped", "Monitoring ended")


def main():
    monitor = GuardianMonitor()

    try:
        monitor.run()
    except KeyboardInterrupt:
        print("\nStopping...")
        monitor.stop()


if __name__ == "__main__":
    main()
