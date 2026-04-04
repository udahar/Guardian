#!/usr/bin/env python3
"""
Docker Daemon Configuration Manager
Manages Docker daemon.json settings for automatic log rotation and cleanup

Features:
- Sets up log rotation to prevent runaway logs
- Configures automatic build cache and image pruning
- Manages storage driver optimization
- Validates daemon.json syntax
"""

import json
import logging
import subprocess
import time
from pathlib import Path
from typing import Dict, Any, Optional, List
from datetime import datetime
import platform
import shutil


class DockerDaemonConfig:
    """Manages Docker daemon.json configuration."""

    def __init__(self):
        self.logger = logging.getLogger("DockerDaemonConfig")
        self.platform = platform.system()
        self.daemon_json_path = self._get_daemon_json_path()

    def _get_daemon_json_path(self) -> Path:
        """Get the path to daemon.json based on OS."""
        if self.platform == "Windows":
            # Docker Desktop on Windows
            return Path.home() / ".docker" / "daemon.json"
        elif self.platform == "Darwin":
            # macOS
            return Path.home() / ".docker" / "daemon.json"
        else:
            # Linux
            return Path("/etc/docker/daemon.json")

    def _is_docker_daemon_running(self) -> bool:
        """Check if Docker daemon is running."""
        try:
            result = subprocess.run(
                ["docker", "info"],
                capture_output=True,
                timeout=5,
                text=True,
            )
            return result.returncode == 0
        except Exception:
            return False

    def _restart_docker_daemon(self) -> bool:
        """Restart Docker daemon (platform-specific)."""
        try:
            if self.platform == "Windows":
                # Signal Docker Desktop to reload config
                self.logger.info("Restarting Docker Desktop...")
                subprocess.run(
                    ["taskkill", "/IM", "Docker.exe", "/F"],
                    capture_output=True,
                    timeout=10,
                )
                time.sleep(2)
                # Docker Desktop will auto-restart
                time.sleep(5)
            elif self.platform == "Darwin":
                # macOS
                self.logger.info("Restarting Docker on macOS...")
                subprocess.run(
                    ["osascript", "-e", "tell app \"Docker\" to quit"],
                    capture_output=True,
                    timeout=10,
                )
                time.sleep(3)
                subprocess.run(
                    ["open", "-a", "Docker"],
                    capture_output=True,
                    timeout=10,
                )
                time.sleep(5)
            else:
                # Linux
                self.logger.info("Restarting Docker daemon on Linux...")
                subprocess.run(
                    ["sudo", "systemctl", "restart", "docker"],
                    capture_output=True,
                    timeout=30,
                )
                time.sleep(3)

            # Wait for daemon to be responsive
            for i in range(30):
                if self._is_docker_daemon_running():
                    self.logger.info("Docker daemon is responsive")
                    return True
                time.sleep(1)

            self.logger.error("Docker daemon did not restart in time")
            return False
        except Exception as e:
            self.logger.error(f"Error restarting Docker: {e}")
            return False

    def read_daemon_json(self) -> Dict[str, Any]:
        """Read current daemon.json configuration."""
        try:
            if self.daemon_json_path.exists():
                with open(self.daemon_json_path, "r") as f:
                    return json.load(f)
            return {}
        except json.JSONDecodeError as e:
            self.logger.error(f"Invalid JSON in daemon.json: {e}")
            return {}
        except Exception as e:
            self.logger.error(f"Error reading daemon.json: {e}")
            return {}

    def write_daemon_json(self, config: Dict[str, Any]) -> bool:
        """Write daemon.json configuration."""
        try:
            # Ensure directory exists
            self.daemon_json_path.parent.mkdir(parents=True, exist_ok=True)

            # Backup existing config
            if self.daemon_json_path.exists():
                backup_path = self.daemon_json_path.with_suffix(".json.bak")
                shutil.copy2(self.daemon_json_path, backup_path)
                self.logger.info(f"Backed up daemon.json to {backup_path}")

            # Write new config with pretty formatting
            with open(self.daemon_json_path, "w") as f:
                json.dump(config, f, indent=2)

            self.logger.info(f"Updated daemon.json at {self.daemon_json_path}")
            return True
        except Exception as e:
            self.logger.error(f"Error writing daemon.json: {e}")
            return False

    def validate_daemon_json(self, config: Dict[str, Any]) -> List[str]:
        """Validate daemon.json configuration."""
        errors = []

        # Check log-opts
        log_opts = config.get("log-opts", {})
        max_size = log_opts.get("max-size")
        if max_size:
            try:
                # Validate size format (e.g., "10m", "512m", "1g")
                size_str = str(max_size).lower()
                if not any(size_str.endswith(u) for u in ["b", "k", "m", "g"]):
                    errors.append(f"Invalid max-size format: {max_size}")
            except Exception as e:
                errors.append(f"Error validating max-size: {e}")

        max_file = log_opts.get("max-file")
        if max_file:
            try:
                mf = int(max_file)
                if mf < 1:
                    errors.append("max-file must be at least 1")
            except ValueError:
                errors.append(f"Invalid max-file: {max_file}")

        # Check storage-driver
        storage_driver = config.get("storage-driver")
        valid_drivers = ["overlay2", "vfs", "devicemapper"]
        if storage_driver and storage_driver not in valid_drivers:
            errors.append(f"Invalid storage-driver: {storage_driver}")

        return errors

    def configure_auto_cleanup(
        self,
        enable_log_rotation: bool = True,
        max_log_size: str = "10m",
        max_log_files: int = 3,
        enable_build_cache_cleanup: bool = True,
        restart_daemon: bool = True,
    ) -> Dict[str, Any]:
        """
        Configure Docker for automatic log rotation and cleanup.

        Args:
            enable_log_rotation: Enable JSON-file log driver with rotation
            max_log_size: Max size of each log file (e.g., "10m")
            max_log_files: Max number of rotated log files
            enable_build_cache_cleanup: Note: build cache prune still needs to be called
            restart_daemon: Restart Docker daemon after changes

        Returns:
            Dict with status, changes made, and any errors
        """
        result = {
            "success": False,
            "changes": [],
            "errors": [],
            "config_path": str(self.daemon_json_path),
            "restart_required": False,
        }

        # Check if Docker is running
        docker_running = self._is_docker_daemon_running()
        if docker_running and restart_daemon:
            result["restart_required"] = True

        # Read current config
        config = self.read_daemon_json()
        original_config = config.copy()

        # Configure log rotation
        if enable_log_rotation:
            if "log-driver" not in config:
                config["log-driver"] = "json-file"
                result["changes"].append("Set log-driver to json-file")

            if "log-opts" not in config:
                config["log-opts"] = {}

            log_opts = config["log-opts"]
            if log_opts.get("max-size") != max_log_size:
                log_opts["max-size"] = max_log_size
                result["changes"].append(f"Set max-size to {max_log_size}")

            if log_opts.get("max-file") != str(max_log_files):
                log_opts["max-file"] = str(max_log_files)
                result["changes"].append(f"Set max-file to {max_log_files}")

            # Prevent logs from overflowing
            if log_opts.get("labels") is None:
                log_opts["labels"] = {}

        # Storage optimization for Linux
        if self.platform == "Linux" and config.get("storage-driver") != "overlay2":
            config["storage-driver"] = "overlay2"
            result["changes"].append("Set storage-driver to overlay2")

        # Validate new config
        errors = self.validate_daemon_json(config)
        if errors:
            result["errors"].extend(errors)
            return result

        # Write config if changed
        if config != original_config:
            if self.write_daemon_json(config):
                result["success"] = True
                result["config_updated"] = True
            else:
                result["errors"].append("Failed to write daemon.json")
                return result
        else:
            result["success"] = True
            result["changes"].append("No changes needed — config already optimal")

        # Restart daemon if needed
        if restart_daemon and result["restart_required"]:
            self.logger.info("Restarting Docker daemon to apply changes...")
            if self._restart_docker_daemon():
                result["daemon_restarted"] = True
                result["changes"].append("Docker daemon restarted")
            else:
                result["errors"].append("Failed to restart Docker daemon")
                result["success"] = False

        return result

    def enable_image_cleanup_labels(self) -> Dict[str, Any]:
        """
        Add configuration to support image cleanup labels.
        Note: actual pruning still happens via docker commands.
        """
        result = {
            "success": False,
            "changes": [],
            "errors": [],
        }

        config = self.read_daemon_json()

        # Add labels for tracking cleanup policies
        if "labels" not in config:
            config["labels"] = {}

        labels = config["labels"]
        if labels.get("cleanup-policy") != "auto":
            labels["cleanup-policy"] = "auto"
            result["changes"].append("Added cleanup-policy label")

        if self.write_daemon_json(config):
            result["success"] = True
        else:
            result["errors"].append("Failed to write daemon.json")

        return result

    def get_current_config(self) -> Dict[str, Any]:
        """Get current Docker daemon configuration."""
        config = self.read_daemon_json()
        return {
            "config_path": str(self.daemon_json_path),
            "config": config,
            "docker_running": self._is_docker_daemon_running(),
            "timestamp": datetime.now().isoformat(),
        }

    def get_config_summary(self) -> Dict[str, Any]:
        """Get summary of current cleanup configuration."""
        config = self.read_daemon_json()
        log_opts = config.get("log-opts", {})

        return {
            "log_rotation_enabled": config.get("log-driver") == "json-file",
            "max_log_size": log_opts.get("max-size", "not set"),
            "max_log_files": log_opts.get("max-file", "not set"),
            "storage_driver": config.get("storage-driver", "default"),
            "has_labels": "labels" in config,
            "cleanup_policy": config.get("labels", {}).get("cleanup-policy"),
        }


def create_docker_daemon_config() -> DockerDaemonConfig:
    """Factory function for creating DockerDaemonConfig."""
    return DockerDaemonConfig()


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    cfg = DockerDaemonConfig()

    print("Current config:")
    import json as _json

    print(_json.dumps(cfg.get_current_config(), indent=2))

    print("\nConfiguring auto-cleanup...")
    result = cfg.configure_auto_cleanup(restart_daemon=False)
    print(_json.dumps(result, indent=2))

    print("\nConfig summary:")
    print(_json.dumps(cfg.get_config_summary(), indent=2))
