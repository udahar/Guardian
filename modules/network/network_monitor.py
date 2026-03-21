#!/usr/bin/env python3
"""
Network Monitor - Network Health Checking
PromptOS Module

Network health monitoring including:
- Internet connectivity checks
- Tailscale/Cloudflare Tunnel health
- DNS resolution testing
- Latency monitoring
- Auto-restart on tunnel drop
"""

import subprocess
import time
import logging
from dataclasses import dataclass
from typing import Optional, List, Dict
from datetime import datetime
import json


try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


@dataclass
class NetworkStatus:
    internet_reachable: bool
    dns_working: bool
    latency_ms: Optional[float]
    tunnel_healthy: bool
    tunnel_name: Optional[str]
    interfaces: List[str]
    timestamp: str


class NetworkMonitor:
    def __init__(self):
        self.logger = self._setup_logging()
        self.test_hosts = [
            "8.8.8.8",  # Google DNS
            "1.1.1.1",  # Cloudflare DNS
            "google.com",
            "github.com",
        ]

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("NetworkMonitor")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_command(self, cmd: list, timeout: int = 10) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def check_internet(self) -> bool:
        """Check if internet is reachable."""
        success, _ = self._run_command(["ping", "-n", "1", "-w", "1000", "8.8.8.8"])
        return success

    def check_dns(self) -> bool:
        """Check if DNS is working."""
        try:
            if REQUESTS_AVAILABLE:
                requests.get("https://google.com", timeout=5)
                return True
        except Exception:
            pass

        success, _ = self._run_command(["nslookup", "google.com"])
        return success

    def measure_latency(self, host: str = "8.8.8.8") -> Optional[float]:
        """Measure latency to a host in ms."""
        success, output = self._run_command(["ping", "-n", "1", "-w", "2000", host])

        if success:
            try:
                for line in output.split("\n"):
                    if "time=" in line.lower():
                        time_str = line.lower().split("time=")[1].split()[0]
                        return float(time_str)
            except Exception:
                pass

        return None

    def check_tailscale(self) -> tuple[bool, Optional[str]]:
        """Check Tailscale status."""
        success, output = self._run_command(["tailscale", "status"])

        if success:
            lines = output.split("\n")
            for line in lines:
                if "tailscale" in line.lower() and "online" in line.lower():
                    return True, "online"
                if "tailscale" in line.lower() and "offline" in line.lower():
                    return False, "offline"
            return True, "running"

        return False, "not_running"

    def check_cloudflare_tunnel(self) -> tuple[bool, Optional[str]]:
        """Check Cloudflare Tunnel status."""
        success, output = self._run_command(["cloudflared", "tunnel", "info"])

        if success:
            return True, "running"

        success, output = self._run_command(
            [
                "powershell",
                "-Command",
                "Get-Process cloudflared -ErrorAction SilentlyContinue",
            ]
        )

        if success:
            return True, "running"

        return False, "not_running"

    def get_interfaces(self) -> List[str]:
        """Get network interfaces."""
        interfaces = []

        success, output = self._run_command(["ipconfig"])
        if success:
            for line in output.split("\n"):
                if "IPv4" in line:
                    ip = line.split(":")[-1].strip()
                    if ip and not ip.startswith("127."):
                        interfaces.append(ip)

        return interfaces

    def check_health(self) -> NetworkStatus:
        """Full network health check."""
        internet = self.check_internet()
        dns = self.check_dns()
        latency = self.measure_latency()

        tailscale_status, tailscale_state = self.check_tailscale()
        cloudflare_status, cloudflare_state = self.check_cloudflare_tunnel()

        tunnel_healthy = tailscale_status or cloudflare_status
        tunnel_name = None
        if tailscale_status:
            tunnel_name = "tailscale"
        elif cloudflare_status:
            tunnel_name = "cloudflare"

        return NetworkStatus(
            internet_reachable=internet,
            dns_working=dns,
            latency_ms=latency,
            tunnel_healthy=tunnel_healthy,
            tunnel_name=tunnel_name,
            interfaces=self.get_interfaces(),
            timestamp=datetime.now().isoformat(),
        )

    def restart_cloudflare(self) -> bool:
        """Restart Cloudflare Tunnel service."""
        try:
            subprocess.run(
                [
                    "powershell",
                    "-Command",
                    "Restart-Service cloudflared -ErrorAction SilentlyContinue",
                ],
                timeout=30,
            )
            self.logger.info("Cloudflare service restart attempted")
            return True
        except Exception as e:
            self.logger.error(f"Failed to restart cloudflared: {e}")
            return False

    def get_summary(self) -> dict:
        status = self.check_health()

        return {
            "internet_reachable": status.internet_reachable,
            "dns_working": status.dns_working,
            "latency_ms": status.latency_ms,
            "tunnel_healthy": status.tunnel_healthy,
            "tunnel": status.tunnel_name,
            "interfaces": status.interfaces,
            "timestamp": status.timestamp,
        }


def get_network_status() -> dict:
    """Quick function to get network status."""
    monitor = NetworkMonitor()
    return monitor.get_summary()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Network Monitor")
    parser.add_argument("--check", action="store_true", help="Full health check")
    parser.add_argument("--latency", action="store_true", help="Measure latency")
    parser.add_argument("--tunnel", action="store_true", help="Check tunnel status")

    args = parser.parse_args()

    monitor = NetworkMonitor()

    if args.check or (not any([args.latency, args.tunnel])):
        print(json.dumps(monitor.get_summary(), indent=2))

    elif args.latency:
        lat = monitor.measure_latency()
        print(f"Latency: {lat}ms" if lat else "Failed to measure")

    elif args.tunnel:
        ts_ok, ts_state = monitor.check_tailscale()
        cf_ok, cf_state = monitor.check_cloudflare_tunnel()
        print(f"Tailscale: {ts_state}")
        print(f"Cloudflare: {cf_state}")
