#!/usr/bin/env python3
"""
Guardian Configuration - Centralized Configuration Management
PromptOS Module

Provides:
- Centralized config loading from environment/file
- Input validation for security
- Type-safe configuration
- Default values with overrides
"""

import os
import json
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from pathlib import Path
import re


logger = logging.getLogger("GuardianConfig")


@dataclass
class GuardianSettings:
    """Main Guardian settings with validation."""

    # WSL Settings
    wsl_distro: str = "Ubuntu"
    wsl_memory_threshold: float = 60.0
    wsl_auto_heal: bool = True

    # Windows Settings
    windows_memory_warning: float = 70.0
    windows_memory_critical: float = 85.0
    windows_disk_warning: float = 80.0
    windows_disk_critical: float = 90.0
    windows_temp_threshold: float = 80.0
    windows_critical_temp: float = 90.0

    # CPU Settings
    cpu_load_threshold_ratio: float = 1.0
    cpu_critical: float = 95.0

    # Intervals
    check_interval: int = 60
    heartbeat_interval: int = 60

    # Features
    auto_heal: bool = True
    use_ai: bool = True
    log_heartbeats: bool = True

    # Network
    network_check_interval: int = 300
    tunnel_restart_on_fail: bool = True

    # Database
    db_enabled: bool = True
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "zolapress"
    db_user: str = "postgres"
    db_password: str = os.environ.get("GUARDIAN_DB_PASSWORD", "")

    # Qdrant
    qdrant_url: str = "http://localhost:6333"

    # Telegram — set via env, never hardcode
    telegram_bot_token: str = os.environ.get("GUARDIAN_TELEGRAM_BOT_TOKEN", "")
    telegram_chat_id: str = os.environ.get("GUARDIAN_TELEGRAM_CHAT_ID", "")

    # Logging
    log_level: str = "INFO"
    log_dir: str = "logs"
    log_max_size_mb: int = 10
    log_max_files: int = 5

    # Docker
    docker_cache_prune_threshold_gb: float = 3.0   # prune build cache above this
    docker_vhd_bloat_alert_gb: float = 4.0         # alert when VHD-vs-data gap exceeds this
    docker_images_warn_gb: float = 10.0            # warn when image store gets large
    docker_auto_prune: bool = True

    # Security
    dry_run: bool = False
    allowed_cleanup_targets: List[str] = field(
        default_factory=lambda: ["temp", "recycle_bin", "dns", "prefetch", "thumbnails", "docker_prune"]
    )

    # Cleanup targets that require admin
    admin_cleanup_targets: List[str] = field(default_factory=lambda: ["windows_update"])

    def validate(self) -> List[str]:
        """Validate configuration and return list of errors."""
        errors = []

        if self.check_interval < 10:
            errors.append("check_interval must be at least 10 seconds")

        if self.heartbeat_interval < 30:
            errors.append("heartbeat_interval must be at least 30 seconds")

        if not 0 <= self.wsl_memory_threshold <= 100:
            errors.append("wsl_memory_threshold must be 0-100")

        if not 0 <= self.windows_memory_warning <= 100:
            errors.append("windows_memory_warning must be 0-100")

        if not 0 <= self.windows_disk_warning <= 100:
            errors.append("windows_disk_warning must be 0-100")

        if self.log_level not in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            errors.append(f"Invalid log_level: {self.log_level}")

        # Validate distro name (alphanumeric, dash, underscore)
        if not re.match(r"^[a-zA-Z0-9_-]+$", self.wsl_distro):
            errors.append(f"Invalid WSL distro name: {self.wsl_distro}")

        # Validate cleanup targets
        valid_targets = [
            "temp",
            "recycle_bin",
            "dns",
            "prefetch",
            "thumbnails",
            "browser",
            "windows_update",
            "docker_prune",
            "all",
        ]
        for target in self.allowed_cleanup_targets:
            if target not in valid_targets:
                errors.append(f"Invalid cleanup target: {target}")

        return errors

    def is_safe_target(self, target: str) -> bool:
        """Check if a cleanup target is safe to run."""
        return target in self.allowed_cleanup_targets

    def requires_admin(self, target: str) -> bool:
        """Check if a cleanup target requires admin privileges."""
        return target in self.admin_cleanup_targets


def load_config_from_env(prefix: str = "GUARDIAN_") -> GuardianSettings:
    """Load configuration from environment variables."""
    settings = GuardianSettings()

    # Map env vars to settings
    env_mappings = {
        f"{prefix}WSL_DISTRO": "wsl_distro",
        f"{prefix}WSL_MEMORY_THRESHOLD": "wsl_memory_threshold",
        f"{prefix}WINDOWS_MEMORY_WARNING": "windows_memory_warning",
        f"{prefix}WINDOWS_MEMORY_CRITICAL": "windows_memory_critical",
        f"{prefix}WINDOWS_DISK_WARNING": "windows_disk_warning",
        f"{prefix}WINDOWS_DISK_CRITICAL": "windows_disk_critical",
        f"{prefix}CHECK_INTERVAL": "check_interval",
        f"{prefix}HEARTBEAT_INTERVAL": "heartbeat_interval",
        f"{prefix}AUTO_HEAL": "auto_heal",
        f"{prefix}USE_AI": "use_ai",
        f"{prefix}LOG_LEVEL": "log_level",
        f"{prefix}DRY_RUN": "dry_run",
        f"{prefix}DB_ENABLED": "db_enabled",
        f"{prefix}DB_HOST": "db_host",
        f"{prefix}DB_PORT": "db_port",
        f"{prefix}DB_NAME": "db_name",
        f"{prefix}DB_USER": "db_user",
        f"{prefix}DB_PASSWORD": "db_password",
        f"{prefix}QDRANT_URL": "qdrant_url",
        f"{prefix}TELEGRAM_BOT_TOKEN": "telegram_bot_token",
        f"{prefix}TELEGRAM_CHAT_ID": "telegram_chat_id",
    }

    for env_var, setting_name in env_mappings.items():
        value = os.environ.get(env_var)
        if value is not None:
            # Type conversion
            if setting_name in ["auto_heal", "use_ai", "db_enabled", "dry_run"]:
                value = value.lower() in ("true", "1", "yes")
            elif setting_name in ["check_interval", "heartbeat_interval", "db_port"]:
                value = int(value)
            elif setting_name in [
                "wsl_memory_threshold",
                "windows_memory_warning",
                "windows_memory_critical",
                "windows_disk_warning",
                "windows_disk_critical",
            ]:
                value = float(value)

            setattr(settings, setting_name, value)

    return settings


def load_config_from_file(config_path: str) -> GuardianSettings:
    """Load configuration from JSON file."""
    path = Path(config_path)

    if not path.exists():
        logger.warning(f"Config file not found: {config_path}")
        return GuardianSettings()

    try:
        with open(path, "r") as f:
            data = json.load(f)

        settings = GuardianSettings()

        # Apply validated settings
        for key, value in data.items():
            if hasattr(settings, key):
                setattr(settings, key, value)

        return settings

    except json.JSONDecodeError as e:
        logger.error(f"Invalid JSON in config file: {e}")
        return GuardianSettings()
    except Exception as e:
        logger.error(f"Error loading config: {e}")
        return GuardianSettings()


def get_config(config_file: Optional[str] = None) -> GuardianSettings:
    """Get configuration with priority: file > env > defaults."""
    settings = GuardianSettings()

    # Load from file if provided
    if config_file:
        settings = load_config_from_file(config_file)

    # Override with environment variables
    env_settings = load_config_from_env()

    # Merge (env takes precedence)
    for key in dir(env_settings):
        if not key.startswith("_"):
            value = getattr(env_settings, key)
            if value is not None and value != getattr(GuardianSettings, key, None):
                setattr(settings, key, value)

    # Validate
    errors = settings.validate()
    if errors:
        logger.warning(f"Configuration validation errors: {errors}")

    return settings


def validate_command_input(value: str, pattern: str = r"^[a-zA-Z0-9_-]+$") -> bool:
    """Validate command input to prevent injection."""
    return bool(re.match(pattern, value))


def sanitize_path(path: str) -> str:
    """Sanitize a file path to prevent directory traversal."""
    # Remove any null bytes
    path = path.replace("\x00", "")

    # Get absolute path and normalize
    try:
        abs_path = Path(path).resolve()
        return str(abs_path)
    except Exception:
        return ""


if __name__ == "__main__":
    # Test config loading
    config = get_config()
    print(f"WSL Distro: {config.wsl_distro}")
    print(f"Auto Heal: {config.auto_heal}")
    print(f"Check Interval: {config.check_interval}s")
    print(f"Log Level: {config.log_level}")
    print(f"Dry Run: {config.dry_run}")

    errors = config.validate()
    if errors:
        print(f"Validation Errors: {errors}")
    else:
        print("Configuration is valid")
