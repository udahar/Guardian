#!/usr/bin/env python3
"""
Guardian API Server - Simple HTTP endpoints for monitoring and management
"""

import sys
import os
import subprocess

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime
import threading
import time
import psutil

# Import Guardian modules
from Guardian.config import GuardianSettings
from Guardian.modules.sensors import WindowsSensors
from Guardian.modules.wsl import WSLManager
from Guardian.modules.network import NetworkMonitor
from Guardian.modules.network import PortScanner
from Guardian.modules.alerts import TelegramAlerts
from Guardian.modules.database import GuardianDB
from Guardian.modules.docker import DockerGuardian, DockerDaemonConfig
from Guardian.modules.memory.memory_pressure import analyze_memory_pressure

PORT = int(os.environ.get("GUARDIAN_API_PORT", "4011"))
SUPERVISOR_STATE_FILE = os.environ.get(
    "GUARDIAN_SUPERVISOR_STATE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "supervisor_state.json"),
)
LATEST_REPORT_FILE = os.environ.get(
    "GUARDIAN_LATEST_REPORT_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "latest_report.json"),
)
SAFE_KILL_NAMES = {
    "ollama",
    "claude",
    "codex",
    "node",
    "python",
    "bun",
    "onedrive",
    "rclone",
    "qdrant",
    "vmmem",
    "vmmemwsl",
    "opencode",
}


def _load_supervisor_state():
    try:
        if os.path.exists(SUPERVISOR_STATE_FILE):
            with open(SUPERVISOR_STATE_FILE, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except Exception:
        pass
    return None


def _load_latest_report():
    try:
        if os.path.exists(LATEST_REPORT_FILE):
            with open(LATEST_REPORT_FILE, "r", encoding="utf-8") as handle:
                return json.load(handle)
    except Exception:
        pass
    return None


def _process_cmdline(proc):
    try:
        return " ".join(proc.cmdline())[:500]
    except Exception:
        return ""


def _build_triage():
    ws = WindowsSensors()
    snap = ws.take_snapshot()
    memory = analyze_memory_pressure()
    processes = []
    for proc in psutil.process_iter(
        ["pid", "name", "memory_info", "memory_percent", "num_threads", "create_time"]
    ):
        try:
            mem = proc.info["memory_info"]
            private_bytes = getattr(mem, "private", getattr(mem, "uss", mem.rss))
            processes.append(
                {
                    "pid": proc.info["pid"],
                    "name": proc.info["name"] or "unknown",
                    "rss_gb": round(mem.rss / (1024**3), 2),
                    "private_gb": round(private_bytes / (1024**3), 2),
                    "memory_percent": round(proc.info["memory_percent"] or 0.0, 2),
                    "threads": proc.info["num_threads"] or 0,
                    "started_at": datetime.fromtimestamp(
                        proc.info["create_time"]
                    ).isoformat()
                    if proc.info["create_time"]
                    else None,
                    "cmdline": _process_cmdline(proc),
                }
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    processes.sort(key=lambda item: (item["private_gb"], item["rss_gb"]), reverse=True)
    kill_candidates = [
        p
        for p in processes
        if p["name"].lower().replace(".exe", "") in SAFE_KILL_NAMES and p["private_gb"] >= 0.15
    ][:8]

    return {
        "time": datetime.now().isoformat(),
        "windows": {
            "cpu": round(snap.cpu_percent, 1),
            "ram": round(snap.memory_percent, 1),
            "disk": round(snap.disk_percent, 1),
            "processes": snap.processes,
        },
        "memory": {
            "ram_percent": memory.ram_percent,
            "available_gb": memory.available_gb,
            "commit_used_gb": memory.commit_used_gb,
            "commit_limit_gb": memory.commit_limit_gb,
            "commit_percent": memory.commit_percent,
            "pagefile_usage_percent": memory.pagefile_usage_percent,
            "pages_per_sec": memory.pages_per_sec,
            "page_reads_per_sec": memory.page_reads_per_sec,
            "causes": memory.causes,
            "recommendations": memory.recommendations,
        },
        "top_groups": [
            {
                "name": group.name,
                "processes": group.processes,
                "private_gb": group.private_gb,
                "rss_gb": group.rss_gb,
            }
            for group in memory.top_groups[:8]
        ],
        "top_processes": processes[:12],
        "kill_candidates": kill_candidates,
    }


def _kill_process(pid: int):
    proc = psutil.Process(pid)
    name = (proc.name() or "").lower().replace(".exe", "")
    if name not in SAFE_KILL_NAMES:
        raise PermissionError(f"refusing to kill non-approved process name: {name}")
    subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"], check=True, timeout=20)
    return name


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        print(f"[{datetime.now().strftime('%H:%M:%S')}] {format % args}")

    def send_json(self, data, code=200):
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.end_headers()
        self.wfile.write(json.dumps(data).encode())

    def do_GET(self):
        path = self.path.split("?")[0]

        if path == "/health":
            supervisor = _load_supervisor_state()
            self.send_json(
                {
                    "status": "ok",
                    "service": "guardian",
                    "time": datetime.now().isoformat(),
                    "supervisor": supervisor,
                }
            )

        elif path == "/status":
            try:
                ws = WindowsSensors()
                snap = ws.take_snapshot()
                ps = PortScanner()
                nm = NetworkMonitor()
                supervisor = _load_supervisor_state()

                self.send_json(
                    {
                        "time": datetime.now().isoformat(),
                        "windows": {
                            "cpu": round(snap.cpu_percent, 1),
                            "ram": round(snap.memory_percent, 1),
                            "disk": round(snap.disk_percent, 1),
                        },
                        "ollama_instances": ps.count_ollama_instances(),
                        "internet": nm.check_internet(),
                        "supervisor": supervisor,
                    }
                )
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/metrics":
            try:
                ws = WindowsSensors()
                snap = ws.take_snapshot()
                self.send_json(
                    {
                        "cpu": snap.cpu_percent,
                        "ram": snap.memory_percent,
                        "disk": snap.disk_percent,
                        "processes": snap.processes,
                    }
                )
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/ollama":
            try:
                ps = PortScanner()
                count = ps.count_ollama_instances()
                self.send_json(
                    {
                        "instances": count,
                        "max_allowed": 3,
                        "status": "ok" if count <= 3 else "exceeded",
                    }
                )
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/disk":
            try:
                ws = WindowsSensors()
                snap = ws.take_snapshot()
                self.send_json(
                    {
                        "disk_percent": snap.disk_percent,
                        "status": "critical"
                        if snap.disk_percent > 90
                        else "warning"
                        if snap.disk_percent > 80
                        else "ok",
                    }
                )
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/triage":
            try:
                self.send_json(_build_triage())
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/report/latest":
            report = _load_latest_report()
            if report is None:
                try:
                    self.send_json(
                        {
                            "timestamp": datetime.now().isoformat(),
                            "source": "live_triage_fallback",
                            "supervisor": _load_supervisor_state(),
                            "triage": _build_triage(),
                        }
                    )
                except Exception as e:
                    self.send_json({"error": f"latest report not available: {e}"}, 500)
            else:
                self.send_json(report)

        elif path == "/docker/status":
            try:
                docker = DockerGuardian()
                result = docker.check_and_heal()
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/docker/config":
            try:
                cfg = DockerDaemonConfig()
                self.send_json(cfg.get_current_config())
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif path == "/docker/config-summary":
            try:
                cfg = DockerDaemonConfig()
                self.send_json(cfg.get_config_summary())
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        else:
            self.send_json({"error": "Not found"}, 404)

    def do_POST(self):
        if self.path == "/fix_ollama":
            try:
                ps = PortScanner()
                count = ps.count_ollama_instances()
                result = {"before": count}

                if count > 3:
                    fix = ps.kill_excess_ollama(max_instances=3)
                    result.update(fix)

                result["after"] = ps.count_ollama_instances()
                result["success"] = True
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif self.path == "/docker/prune":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode() if length > 0 else "{}"
                data = json.loads(body)

                docker = DockerGuardian()
                aggressive = data.get("aggressive", False)

                result = docker.prune(aggressive=aggressive)
                self.send_json(
                    {
                        "success": result.success,
                        "actions": result.actions,
                        "space_freed_gb": result.space_freed_gb,
                        "errors": result.errors,
                    }
                )
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif self.path == "/docker/config/setup-cleanup":
            try:
                cfg = DockerDaemonConfig()
                result = cfg.configure_auto_cleanup(restart_daemon=False)
                self.send_json(result)
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif self.path == "/docker/cleanup-containers":
            try:
                docker = DockerGuardian()
                result = docker.prune_containers()
                self.send_json(
                    {
                        "success": result.success,
                        "actions": result.actions,
                        "errors": result.errors,
                    }
                )
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif self.path == "/docker/cleanup-volumes":
            try:
                docker = DockerGuardian()
                result = docker.prune_volumes()
                self.send_json(
                    {
                        "success": result.success,
                        "actions": result.actions,
                        "errors": result.errors,
                    }
                )
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif self.path == "/alert":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode()
                data = json.loads(body)

                alerts = TelegramAlerts()
                alerts.send_alert(
                    data.get("level", "info"),
                    data.get("title", "Guardian"),
                    data.get("message", ""),
                )
                self.send_json({"success": True})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        elif self.path == "/process/kill":
            try:
                length = int(self.headers.get("Content-Length", 0))
                body = self.rfile.read(length).decode() if length > 0 else "{}"
                data = json.loads(body)
                pid = int(data.get("pid", 0))
                if pid <= 0:
                    self.send_json({"error": "pid required"}, 400)
                    return
                name = _kill_process(pid)
                self.send_json({"success": True, "pid": pid, "name": name})
            except Exception as e:
                self.send_json({"error": str(e)}, 500)

        else:
            self.send_json({"error": "Not found"}, 404)


def main():
    print(f"Starting Guardian API on port {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Guardian API: http://localhost:{PORT}")
    print("\nSystem endpoints:")
    print("  GET  /health              - Health check")
    print("  GET  /status              - System status (CPU/RAM/Disk/Ollama)")
    print("  GET  /metrics             - System metrics")
    print("  GET  /ollama              - Ollama instances status")
    print("  GET  /disk                - Disk status")
    print("  GET  /triage              - Memory/disk triage report")
    print("  GET  /report/latest       - Latest Guardian operator report")
    print("  POST /fix_ollama          - Kill excess Ollama instances")
    print("  POST /process/kill        - Kill approved heavy process by PID")
    print("  POST /alert               - Send alert")
    print("\nDocker endpoints:")
    print("  GET  /docker/status       - Docker disk usage and health")
    print("  GET  /docker/config       - Current daemon.json configuration")
    print("  GET  /docker/config-summary - Docker config summary")
    print("  POST /docker/prune        - Prune Docker (body: {aggressive: bool})")
    print("  POST /docker/cleanup-containers - Prune stopped containers")
    print("  POST /docker/cleanup-volumes - Prune dangling volumes")
    print("  POST /docker/config/setup-cleanup - Setup auto-cleanup in daemon.json")
    print()
    server.serve_forever()


if __name__ == "__main__":
    main()
