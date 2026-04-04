#!/usr/bin/env python3
"""
Service Health Monitor - HTTP health pings for all local services
Guardian Module

Checks all known services on Richard's stack and reports which are
up/down. Sends Telegram alert when a previously-healthy service goes down
or when it recovers. Tracks state to avoid alert spam.
"""

import socket
import urllib.request
import urllib.error
import logging
import json
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from datetime import datetime


logger = logging.getLogger("ServiceHealth")


@dataclass
class ServiceDef:
    name: str
    port: int
    health_path: str = "/health"
    method: str = "GET"
    timeout: float = 3.0
    expected_status: int = 200
    optional: bool = False          # optional services don't alert on down
    check_tcp_only: bool = False    # just check if port is open (no HTTP)


@dataclass
class ServiceStatus:
    name: str
    port: int
    up: bool
    latency_ms: float = 0.0
    status_code: Optional[int] = None
    error: Optional[str] = None
    checked_at: datetime = field(default_factory=datetime.now)


# All services in the stack
SERVICES: List[ServiceDef] = [
    ServiceDef("FieldBench API",     4001, "/health",         optional=False),
    ServiceDef("FieldBench React",   4004, "/",               optional=True,  check_tcp_only=True),
    ServiceDef("Benchmark API",      8765, "/health",         optional=False),
    ServiceDef("Crucible",           8767, "/health",         optional=False),
    ServiceDef("vendor-proxy",       8766, "/health",         optional=True,  check_tcp_only=True),
    ServiceDef("DashKit",            9000, "/health",         optional=True),
    ServiceDef("Alfred.js MCP",      3002, "/mcp/tools",      optional=True),
    ServiceDef("Nova Bridge MCP",    8888, "/mcp/tools",      optional=True),
    ServiceDef("Ollama local",      11434, "/api/tags",       optional=False),
    ServiceDef("Ollama cloud",      11436, "/api/tags",       optional=True),
    ServiceDef("Ollama embedding",  11437, "/api/tags",       optional=True),
    ServiceDef("PostgreSQL",         5432, "",                optional=False, check_tcp_only=True),
    ServiceDef("Qdrant",             6333, "/healthz",        optional=True),
]


class ServiceHealthMonitor:
    def __init__(self, alert_after_failures: int = 2):
        self._failure_counts: Dict[str, int] = {}
        self._last_state: Dict[str, bool] = {}
        self._alert_threshold = alert_after_failures
        self._telegram = None
        self._try_init_telegram()

    def _try_init_telegram(self):
        try:
            from Guardian.modules.alerts.telegram_alerts import TelegramAlerts
            self._telegram = TelegramAlerts()
        except Exception:
            pass

    def _alert(self, msg: str, level: str = "warning"):
        logger.warning(msg)
        if self._telegram:
            try:
                if level == "critical":
                    self._telegram.critical(msg)
                else:
                    self._telegram.warning(msg)
            except Exception:
                pass

    def _check_tcp(self, port: int, timeout: float = 2.0) -> Tuple[bool, float, Optional[str]]:
        start = time.perf_counter()
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=timeout):
                return True, (time.perf_counter() - start) * 1000, None
        except ConnectionRefusedError:
            return False, 0.0, "connection refused"
        except socket.timeout:
            return False, 0.0, "timeout"
        except Exception as e:
            return False, 0.0, str(e)

    def _check_http(self, svc: ServiceDef) -> Tuple[bool, float, Optional[int], Optional[str]]:
        url = f"http://127.0.0.1:{svc.port}{svc.health_path}"
        start = time.perf_counter()
        try:
            req = urllib.request.Request(url, method=svc.method)
            with urllib.request.urlopen(req, timeout=svc.timeout) as resp:
                ms = (time.perf_counter() - start) * 1000
                return resp.status == svc.expected_status, ms, resp.status, None
        except urllib.error.HTTPError as e:
            ms = (time.perf_counter() - start) * 1000
            ok = e.code == svc.expected_status
            return ok, ms, e.code, None if ok else f"HTTP {e.code}"
        except urllib.error.URLError as e:
            return False, 0.0, None, str(e.reason)
        except Exception as e:
            return False, 0.0, None, str(e)[:80]

    def check_service(self, svc: ServiceDef) -> ServiceStatus:
        if svc.check_tcp_only or not svc.health_path:
            up, ms, err = self._check_tcp(svc.port, svc.timeout)
            return ServiceStatus(name=svc.name, port=svc.port,
                                 up=up, latency_ms=ms, error=err)
        else:
            up, ms, code, err = self._check_http(svc)
            return ServiceStatus(name=svc.name, port=svc.port,
                                 up=up, latency_ms=ms, status_code=code, error=err)

    def check_all(self, services: List[ServiceDef] = None) -> List[ServiceStatus]:
        results = []
        for svc in (services or SERVICES):
            status = self.check_service(svc)
            results.append(status)

            key = svc.name
            was_up = self._last_state.get(key, True)

            if not status.up:
                self._failure_counts[key] = self._failure_counts.get(key, 0) + 1
                if not svc.optional and self._failure_counts[key] >= self._alert_threshold:
                    if was_up or self._failure_counts[key] == self._alert_threshold:
                        self._alert(
                            f"Service DOWN: {svc.name} (port {svc.port}) — "
                            f"{status.error or 'no response'} "
                            f"[{self._failure_counts[key]} consecutive failures]",
                            level="critical"
                        )
            else:
                if not was_up and self._failure_counts.get(key, 0) >= self._alert_threshold:
                    self._alert(f"Service RECOVERED: {svc.name} (port {svc.port})")
                self._failure_counts[key] = 0

            self._last_state[key] = status.up

        return results

    def get_summary(self) -> Dict:
        results = self.check_all()
        up = [s for s in results if s.up]
        down = [s for s in results if not s.up]

        return {
            "checked": len(results),
            "up": len(up),
            "down": len(down),
            "down_services": [
                {"name": s.name, "port": s.port, "error": s.error}
                for s in down
            ],
            "latency_ms": {
                s.name: round(s.latency_ms, 1) for s in results if s.up
            },
        }

    def print_status(self, results: List[ServiceStatus] = None):
        if results is None:
            results = self.check_all()
        print()
        print(f"  {'SERVICE':<25} {'PORT':>6}  {'STATUS':<10}  {'LATENCY'}")
        print("  " + "-" * 58)
        for s in sorted(results, key=lambda x: (not x.up, x.name)):
            status = "UP" if s.up else "DOWN"
            color_up   = "\033[32m" if s.up else "\033[31m"
            reset      = "\033[0m"
            latency    = f"{s.latency_ms:.0f}ms" if s.up and s.latency_ms else ""
            err        = f"  ({s.error})" if not s.up and s.error else ""
            print(f"  {s.name:<25} {s.port:>6}  "
                  f"{color_up}{status:<10}{reset}  {latency}{err}")
        print()


_monitor_instance: Optional[ServiceHealthMonitor] = None


def get_monitor() -> ServiceHealthMonitor:
    global _monitor_instance
    if _monitor_instance is None:
        _monitor_instance = ServiceHealthMonitor()
    return _monitor_instance


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    monitor = ServiceHealthMonitor()
    results = monitor.check_all()
    monitor.print_status(results)
    summary = monitor.get_summary()
    print(f"Summary: {summary['up']}/{summary['checked']} up")
    if summary["down_services"]:
        print("DOWN:", [s["name"] for s in summary["down_services"]])
