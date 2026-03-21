#!/usr/bin/env python3
"""
Guardian API Server - Simple HTTP endpoints
"""

import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from http.server import HTTPServer, BaseHTTPRequestHandler
import json
from datetime import datetime
import threading
import time

# Import Guardian modules
from Guardian.config import GuardianSettings
from Guardian.modules.sensors import WindowsSensors
from Guardian.modules.wsl import WSLManager
from Guardian.modules.network import NetworkMonitor
from Guardian.modules.network import PortScanner
from Guardian.modules.alerts import TelegramAlerts
from Guardian.modules.database import GuardianDB

PORT = 4001


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
            self.send_json(
                {
                    "status": "ok",
                    "service": "guardian",
                    "time": datetime.now().isoformat(),
                }
            )

        elif path == "/status":
            try:
                ws = WindowsSensors()
                snap = ws.take_snapshot()
                ps = PortScanner()
                nm = NetworkMonitor()

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

        else:
            self.send_json({"error": "Not found"}, 404)


def main():
    print(f"Starting Guardian API on port {PORT}...")
    server = HTTPServer(("0.0.0.0", PORT), Handler)
    print(f"Guardian API: http://localhost:{PORT}")
    print("Endpoints: /health, /status, /metrics, /ollama, /disk")
    print("POST: /fix_ollama, /alert")
    print()
    server.serve_forever()


if __name__ == "__main__":
    main()
