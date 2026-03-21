#!/usr/bin/env python3
"""
Guardian Continuous Monitor
Runs Guardian monitoring loop continuously with auto-healing
"""

import sys
import os
import time
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Guardian.config import GuardianSettings
from Guardian.modules.alerts import TelegramAlerts
from Guardian.modules.sensors import WindowsSensors
from Guardian.modules.wsl import WSLManager
from Guardian.modules.network import NetworkMonitor
from Guardian.modules.network import PortScanner
from Guardian.modules.performance import ReclamationEngine
from Guardian.modules.database import GuardianDB
from datetime import datetime

# Config
CHECK_INTERVAL = 60  # seconds
OLLAMA_MAX = 3


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

        self.running = True

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

    def save_to_db(self, status):
        """Save status to database"""
        try:
            self.db.save_decision(
                {
                    "timestamp": datetime.now().isoformat(),
                    "metrics": {
                        "cpu": status["cpu"],
                        "ram": status["ram"],
                        "disk": status["disk"],
                        "ollama": status["ollama"],
                    },
                    "decision": "monitor",
                    "confidence": "high",
                    "reasoning": "; ".join(status["issues"])
                    if status["issues"]
                    else "All OK",
                    "actions_taken": status["actions"],
                }
            )
        except Exception as e:
            print(f"DB save error: {e}")

    def send_alerts(self, status):
        """Send Telegram alerts if needed"""
        if status["issues"]:
            # Critical issues
            critical = [i for i in status["issues"] if "CRITICAL" in i or "EXCESS" in i]
            if critical:
                self.alerts.send_alert(
                    "critical", "Guardian Alert", "; ".join(critical)
                )

            # Warnings
            warnings = [i for i in status["issues"] if i not in critical]
            if warnings:
                self.alerts.send_alert(
                    "warning", "Guardian Warning", "; ".join(warnings)
                )

        if status["actions"]:
            self.alerts.send_alert(
                "info", "Guardian Action", "; ".join(status["actions"])
            )

    def run_cycle(self):
        """Run one monitoring cycle"""
        print(f"[{datetime.now().strftime('%H:%M:%S')}] Checking system...")

        status = self.check_system()

        # Report
        print(
            f"  CPU:{status['cpu']:.0f}% RAM:{status['ram']:.0f}% Disk:{status['disk']:.0f}% Ollama:{status['ollama']}"
        )

        if status["issues"]:
            print(f"  Issues: {status['issues']}")
        if status["actions"]:
            print(f"  Actions: {status['actions']}")

        # Save and alert
        self.save_to_db(status)
        self.send_alerts(status)

        return status

    def run(self):
        """Main loop"""
        print("=" * 50)
        print("GUARDIAN MONITOR STARTED")
        print(f"Interval: {CHECK_INTERVAL}s")
        print(f"Ollama max: {OLLAMA_MAX}")
        print("=" * 50)

        self.alerts.send_alert(
            "info", "Guardian Started", f"Monitoring every {CHECK_INTERVAL}s"
        )

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
