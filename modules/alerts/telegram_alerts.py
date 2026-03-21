#!/usr/bin/env python3
"""
Telegram Alert System - Guardian Notifications
PromptOS Module

Sends alerts and reports via Telegram:
- Real-time alerts for critical issues
- Periodic health reports
- Command responses (via bot)
- Structured messages with formatting

Features:
- Configurable alert thresholds
- Rate limiting to prevent spam
- Rich message formatting
- Command handler for bot interactions
"""

import os
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from datetime import datetime
from enum import Enum
import threading


try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class AlertLevel(Enum):
    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class AlertMessage:
    level: AlertLevel
    title: str
    message: str
    data: Dict[str, Any] = field(default_factory=dict)
    timestamp: datetime = field(default_factory=datetime.now)


@dataclass
class TelegramConfig:
    bot_token: str = ""
    chat_id: str = ""
    enabled: bool = False
    alert_levels: List[str] = field(
        default_factory=lambda: ["info", "warning", "error", "critical"]
    )
    rate_limit_seconds: int = 60
    include_system_info: bool = True


class TelegramAlerts:
    def __init__(self, config: TelegramConfig = None):
        self.config = config or self._load_config()
        self.logger = self._setup_logging()
        self._last_alert_time: Dict[str, float] = {}
        self._lock = threading.Lock()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("TelegramAlerts")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _load_config(self) -> TelegramConfig:
        """Load config from environment or Guardian settings."""
        config = TelegramConfig()

        # First try Guardian settings
        try:
            from Guardian.config import GuardianSettings

            gs = GuardianSettings()
            if gs.telegram_bot_token and gs.telegram_chat_id:
                config.bot_token = gs.telegram_bot_token
                config.chat_id = gs.telegram_chat_id
                config.enabled = True
                return config
        except:
            pass

        # Fall back to environment
        token = os.environ.get("TELEGRAM_BOT_TOKEN", "")
        chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

        if token and chat_id:
            config.bot_token = token
            config.chat_id = chat_id
            config.enabled = True

        return config

    def _format_message(self, alert: AlertMessage) -> str:
        """Format alert as Telegram message."""
        emoji = {
            AlertLevel.INFO: "ℹ️",
            AlertLevel.WARNING: "⚠️",
            AlertLevel.ERROR: "❌",
            AlertLevel.CRITICAL: "🚨",
        }.get(alert.level, "ℹ️")

        level_text = alert.level.value.upper()

        text = f"{emoji} *{level_text}: {alert.title}*\n\n{alert.message}"

        if alert.data:
            text += "\n\n*Details:*\n"
            for key, value in alert.data.items():
                text += f"• {key}: `{value}`\n"

        text += f"\n_{alert.timestamp.strftime('%Y-%m-%d %H:%M:%S')}_"

        return text

    def _should_send(self, level: AlertLevel) -> bool:
        """Check if we should send based on rate limiting."""
        level_key = level.value
        now = time.time()

        with self._lock:
            last_time = self._last_alert_time.get(level_key, 0)

            if now - last_time < self.config.rate_limit_seconds:
                self.logger.debug(f"Rate limited: {level.value}")
                return False

            self._last_alert_time[level_key] = now
            return True

    def send(
        self,
        level: AlertLevel,
        title: str,
        message: str,
        data: Dict = None,
        force: bool = False,
    ) -> bool:
        """Send a Telegram alert."""
        if not self.config.enabled:
            self.logger.debug("Telegram alerts disabled")
            return False

        # Handle both string and enum
        level_obj = level if isinstance(level, AlertLevel) else AlertLevel(level)

        if level_obj.value not in self.config.alert_levels and not force:
            self.logger.debug(f"Alert level {level_obj.value} not in configured levels")
            return False

        if not self._should_send(level_obj) and not force:
            return False

        alert = AlertMessage(level=level, title=title, message=message, data=data or {})

        if not REQUESTS_AVAILABLE:
            self.logger.warning(
                "requests library not available, cannot send Telegram alert"
            )
            return False

        try:
            url = f"https://api.telegram.org/bot{self.config.bot_token}/sendMessage"

            payload = {
                "chat_id": self.config.chat_id,
                "text": self._format_message(alert),
                "parse_mode": "Markdown",
            }

            response = requests.post(url, json=payload, timeout=10)

            if response.status_code == 200:
                self.logger.info(f"Telegram alert sent: {title}")
                return True
            else:
                self.logger.error(
                    f"Telegram API error: {response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            self.logger.error(f"Failed to send Telegram alert: {e}")
            return False

    def send_health_report(self, health_data: Dict) -> bool:
        """Send periodic health report."""
        if not self.config.enabled:
            return False

        cpu = health_data.get("windows", {}).get("cpu_percent", 0)
        ram = health_data.get("windows", {}).get("memory_percent", 0)
        disk = health_data.get("windows", {}).get("disk_percent", 0)

        emoji = "✅"
        if cpu > 80 or ram > 80 or disk > 90:
            emoji = "⚠️"
        if cpu > 95 or ram > 95 or disk > 98:
            emoji = "🚨"

        message = f"{emoji} *Guardian Health Report*\n\n"
        message += f"CPU: {cpu}%\n"
        message += f"RAM: {ram}%\n"
        message += f"Disk: {disk}%\n"

        ollama = health_data.get("ollama", {})
        if ollama:
            message += f"\nOllama: {ollama.get('instances', 0)} instances, {ollama.get('memory_mb', 0):.0f}MB"

        return self.send(AlertLevel.INFO, "Health Report", message, force=True)

    def send_alert(
        self, alert_type: str, title: str, message: str, details: Dict = None
    ) -> bool:
        """Send an alert with automatic level detection."""
        level = AlertLevel.WARNING

        if "critical" in alert_type.lower() or "oom" in alert_type.lower():
            level = AlertLevel.CRITICAL
        elif "error" in alert_type.lower() or "fail" in alert_type.lower():
            level = AlertLevel.ERROR
        elif "info" in alert_type.lower():
            level = AlertLevel.INFO

        return self.send(level, title, message, details)

    def send_system_summary(self, summary: Dict) -> bool:
        """Send full system summary."""
        if not self.config.enabled:
            return False

        lines = ["*🖥️ System Summary*\n"]

        # Windows
        win = summary.get("windows", {})
        lines.append(f"*Windows:*")
        lines.append(f"  CPU: {win.get('cpu_percent', 0):.1f}%")
        lines.append(f"  RAM: {win.get('memory_percent', 0):.1f}%")
        lines.append(f"  Disk: {win.get('disk_percent', 0):.1f}%")

        # WSL
        wsl = summary.get("wsl", {})
        if wsl.get("hostname"):
            lines.append(f"\n*WSL ({wsl.get('hostname')}):*")
            mem = wsl.get("memory", {})
            lines.append(
                f"  RAM: {mem.get('used_mb', 0):.0f}/{mem.get('total_mb', 0):.0f}MB"
            )
            load = wsl.get("load", {})
            lines.append(f"  Load: {load.get('1m', 0):.2f}")

        # Network
        net = summary.get("network", {})
        lines.append(f"\n*Network:*")
        lines.append(f"  Internet: {'✅' if net.get('internet_reachable') else '❌'}")
        lines.append(f"  Tunnel: {'✅' if net.get('tunnel_healthy') else '❌'}")

        # Leaks
        leaks = summary.get("leaks", {})
        if leaks.get("summary", {}).get("critical_count", 0) > 0:
            lines.append(
                f"\n🚨 *{leaks['summary']['critical_count']} CRITICAL LEAKS DETECTED!*"
            )

        message = "\n".join(lines)
        return self.send(AlertLevel.INFO, "System Scan Complete", message, force=True)


def create_telegram_alerts(
    bot_token: str = None, chat_id: str = None
) -> TelegramAlerts:
    """Create Telegram alerts with config."""
    config = TelegramConfig()

    if bot_token:
        config.bot_token = bot_token
    if chat_id:
        config.chat_id = chat_id

    config.enabled = bool(config.bot_token and config.chat_id)

    return TelegramAlerts(config)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Telegram Alerts")
    parser.add_argument("--test", action="store_true", help="Send test message")
    parser.add_argument(
        "--level", choices=["info", "warning", "error", "critical"], default="info"
    )
    parser.add_argument("--title", type=str, default="Test Alert")
    parser.add_argument("--message", type=str, default="This is a test from Guardian")

    args = parser.parse_args()

    alerts = TelegramAlerts()

    if args.test:
        level = AlertLevel(args.level)
        result = alerts.send(level, args.title, args.message)
        print(f"Alert sent: {result}")
    else:
        print("Telegram Alerts Module")
        print("Set TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID env vars to enable")
