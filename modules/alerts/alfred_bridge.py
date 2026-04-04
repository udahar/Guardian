#!/usr/bin/env python3
"""
Alfred Bridge - Guardian → Alfred alerting and reporting.

Sends Guardian alerts through Alfred (already-loaded model) instead of
loading a new Ollama model. Alfred forwards to Telegram and logs to
the FieldBench event stream.

Usage:
    from Guardian.modules.alerts.alfred_bridge import notify_alfred
    notify_alfred("CRITICAL", "Disk 99% full", {"free_gb": 0.3})
"""

import os
import json
import logging
import requests
from typing import Dict, Any, Optional

logger = logging.getLogger("AlfredBridge")

# Alfred.py MCP API (Windows-side)
ALFRED_API_URL = os.environ.get("ALFRED_API_URL", "http://localhost:8000")
# Alfred.js MCP server (Windows-side)
ALFRED_JS_URL = os.environ.get("ALFRED_JS_URL", "http://localhost:3002")
# FieldBench event endpoint
FIELDBENCH_URL = os.environ.get("FIELDBENCH_URL", "http://localhost:4001")
FIELDBENCH_GUARDIAN_URL = os.environ.get(
    "FIELDBENCH_GUARDIAN_URL", "http://localhost:4001/api/auth/guardian"
)


def _post(url: str, payload: dict, timeout: int = 10) -> Optional[dict]:
    try:
        r = requests.post(url, json=payload, timeout=timeout)
        r.raise_for_status()
        return r.json()
    except Exception as exc:
        logger.debug(f"POST {url} failed: {exc}")
        return None


def notify_alfred(
    level: str,
    title: str,
    message: str,
    data: Optional[Dict[str, Any]] = None,
) -> bool:
    """
    Send a Guardian alert through Alfred.

    Alfred receives it and:
    - Forwards to Telegram (via its own bot token)
    - Logs to FieldBench event stream
    - Can take autonomous action (disk cleanup, service restart)

    level: INFO | WARNING | ERROR | CRITICAL
    """
    payload = {
        "source": "guardian",
        "level": level.upper(),
        "title": title,
        "message": message,
        "data": data or {},
    }

    # Guardian-aware FieldBench bridge with Telegram controls
    result = _post(f"{FIELDBENCH_GUARDIAN_URL}/alert", payload)
    if result:
        logger.info(f"Guardian alert delivered via FieldBench: {title}")
        return True

    # Try Alfred.py API first
    result = _post(f"{ALFRED_API_URL}/guardian/alert", payload)
    if result:
        logger.info(f"Alfred notified via Alfred.py: {title}")
        return True

    # Try Alfred.js MCP server
    result = _post(f"{ALFRED_JS_URL}/guardian/alert", payload)
    if result:
        logger.info(f"Alfred notified via Alfred.js: {title}")
        return True

    # Fallback: post directly to FieldBench events table
    fb_payload = {
        "event_type": f"guardian.{level.lower()}",
        "source": "guardian",
        "payload": payload,
    }
    result = _post(f"{FIELDBENCH_URL}/api/events", fb_payload)
    if result:
        logger.info(f"Guardian event posted to FieldBench: {title}")
        return True

    logger.warning(f"Alfred unreachable — alert dropped: {title}")
    return False


def report_disk_status(
    free_gb: float,
    used_pct: float,
    top_hogs: list,
    reclaimable_gb: float,
) -> bool:
    """Send a structured disk status report to Alfred."""
    level = "CRITICAL" if used_pct >= 95 else "WARNING" if used_pct >= 85 else "INFO"
    title = f"Disk {used_pct:.0f}% — {free_gb:.1f}GB free"
    lines = [f"C: drive is {used_pct:.1f}% used, {free_gb:.1f}GB free."]
    if reclaimable_gb >= 1.0:
        lines.append(f"Guardian estimates {reclaimable_gb:.1f}GB reclaimable.")
    if top_hogs:
        lines.append("Top space hogs:")
        for h in top_hogs[:5]:
            flag = " *" if h.get("reclaimable") else ""
            lines.append(f"  {h['label']}: {h['size_gb']:.1f}GB{flag}")
    return notify_alfred(level, title, "\n".join(lines), {
        "free_gb": free_gb,
        "used_pct": used_pct,
        "reclaimable_gb": reclaimable_gb,
    })


if __name__ == "__main__":
    logging.basicConfig(level=logging.DEBUG)
    ok = notify_alfred("INFO", "Guardian test", "Alfred bridge is working.")
    print("Sent:", ok)
