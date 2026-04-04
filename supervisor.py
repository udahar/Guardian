#!/usr/bin/env python3
"""
Guardian supervisor.

Runs the Guardian API and proactive monitor as one supervised app so the
runtime cannot silently come up half-alive.
"""

from __future__ import annotations

import json
import logging
import os
import socket
import threading
import time
from datetime import datetime
from pathlib import Path


LOG = logging.getLogger("GuardianSupervisor")
LOG.setLevel(logging.INFO)
if not LOG.handlers:
    handler = logging.StreamHandler()
    formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")
    handler.setFormatter(formatter)
    LOG.addHandler(handler)


REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
STATE_FILE = os.environ.get(
    "GUARDIAN_SUPERVISOR_STATE_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "supervisor_state.json"),
)
API_PORT = int(os.environ.get("GUARDIAN_API_PORT", "4011"))
LOCK_FILE = os.environ.get(
    "GUARDIAN_SUPERVISOR_LOCK_FILE",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "supervisor.lock"),
)


def _ensure_parent(path: str) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)


def _write_state(state: dict) -> None:
    _ensure_parent(STATE_FILE)
    payload = {
        **state,
        "updated_at": datetime.now().isoformat(),
    }
    with open(STATE_FILE, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2)


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _acquire_lock() -> bool:
    _ensure_parent(LOCK_FILE)
    path = Path(LOCK_FILE)
    if path.exists():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            existing_pid = int(payload.get("pid", 0) or 0)
            if _pid_alive(existing_pid):
                return False
        except Exception:
            pass
        try:
            path.unlink()
        except FileNotFoundError:
            pass

    data = {
        "pid": os.getpid(),
        "created_at": datetime.now().isoformat(),
    }
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return True


def _release_lock() -> None:
    try:
        path = Path(LOCK_FILE)
        if not path.exists():
            return
        payload = json.loads(path.read_text(encoding="utf-8"))
        if int(payload.get("pid", 0) or 0) == os.getpid():
            path.unlink()
    except Exception:
        pass


def _port_listening(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.75)
        return sock.connect_ex(("127.0.0.1", port)) == 0


class GuardianSupervisor:
    def __init__(self):
        self.stop_event = threading.Event()
        self.state = {
            "service": "guardian",
            "mode": "supervisor",
            "roles": {
                "api": {"running": False, "restarts": 0, "last_started_at": None, "last_error": None},
                "monitor": {"running": False, "restarts": 0, "last_started_at": None, "last_error": None},
            },
        }

    def _mark_role(self, role: str, *, running: bool | None = None, error: str | None = None) -> None:
        row = self.state["roles"][role]
        if running is not None:
            row["running"] = running
        if error is not None:
            row["last_error"] = error
        _write_state(self.state)

    def _run_api(self) -> None:
        from Guardian.api_server import main as api_main

        while not self.stop_event.is_set():
            self.state["roles"]["api"]["running"] = True
            self.state["roles"]["api"]["last_started_at"] = datetime.now().isoformat()
            self.state["roles"]["api"]["restarts"] += 1
            self.state["roles"]["api"]["last_error"] = None
            _write_state(self.state)
            try:
                api_main()
            except Exception as exc:
                LOG.error("Guardian API crashed: %s", exc)
                self._mark_role("api", running=False, error=str(exc))
                time.sleep(5)
            else:
                self._mark_role("api", running=False, error="api_main_returned")
                time.sleep(2)

    def _run_monitor(self) -> None:
        from Guardian.modules.monitor.proactive_guardian import ProactiveGuardian, GuardianConfig

        while not self.stop_event.is_set():
            self.state["roles"]["monitor"]["running"] = True
            self.state["roles"]["monitor"]["last_started_at"] = datetime.now().isoformat()
            self.state["roles"]["monitor"]["restarts"] += 1
            self.state["roles"]["monitor"]["last_error"] = None
            _write_state(self.state)
            guardian = None
            try:
                guardian = ProactiveGuardian(GuardianConfig())
                guardian.start()
            except Exception as exc:
                LOG.error("Guardian monitor crashed: %s", exc)
                self._mark_role("monitor", running=False, error=str(exc))
                time.sleep(5)
            else:
                self._mark_role("monitor", running=False, error="monitor_returned")
                time.sleep(2)
            finally:
                try:
                    if guardian is not None:
                        guardian.stop()
                except Exception:
                    pass

    def run(self) -> None:
        LOG.info("Starting Guardian supervisor")
        _write_state(self.state)

        api_thread = threading.Thread(target=self._run_api, daemon=True, name="guardian-api")
        monitor_thread = threading.Thread(target=self._run_monitor, daemon=True, name="guardian-monitor")
        api_thread.start()
        time.sleep(2)
        if not _port_listening(API_PORT):
            LOG.warning("Guardian API port %s is not listening yet", API_PORT)
        monitor_thread.start()

        try:
            while True:
                if not api_thread.is_alive():
                    self._mark_role("api", running=False, error="api_thread_dead")
                    break
                if not monitor_thread.is_alive():
                    self._mark_role("monitor", running=False, error="monitor_thread_dead")
                    break
                time.sleep(5)
        except KeyboardInterrupt:
            LOG.info("Stopping Guardian supervisor")
        finally:
            self.stop_event.set()
            self._mark_role("api", running=False)
            self._mark_role("monitor", running=False)


def main() -> None:
    if not _acquire_lock():
        LOG.info("Guardian supervisor already running; exiting duplicate launch")
        return
    try:
        GuardianSupervisor().run()
    finally:
        _release_lock()


if __name__ == "__main__":
    main()
