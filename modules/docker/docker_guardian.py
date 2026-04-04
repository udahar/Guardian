#!/usr/bin/env python3
"""
Docker Guardian - Docker disk health monitor and auto-maintenance
PromptOS Module

Monitors Docker disk usage and automatically:
- Prunes build cache / dangling images when usage exceeds threshold
- Tracks VHD bloat (file size vs actual data) and alerts
- Cleans up stopped containers and dangling volumes
- Configures Docker daemon for automatic log rotation
- Manages Docker storage optimization

Common culprits this was built to fight:
- Build cache from iterative Crucible/Benchmark image rebuilds
- Dangling images from failed builds
- VHD file never auto-shrinks after prune (needs diskpart compact as admin)
- Unrotated container logs filling up disk
"""

import subprocess
import json
import logging
import threading
import time
from dataclasses import dataclass, field
from typing import Optional, Dict, Any
from datetime import datetime
from pathlib import Path


DOCKER_VHD_PATH = Path(
    r"C:\Users\Richard\AppData\Local\Docker\wsl\disk\docker_data.vhdx"
)
COMPACT_SCRIPT = Path(r"C:\Users\Richard\compact_docker.bat")


@dataclass
class DockerDiskState:
    timestamp: datetime
    images_size_gb: float = 0.0
    build_cache_gb: float = 0.0
    containers_size_gb: float = 0.0
    volumes_size_gb: float = 0.0
    total_reclaimable_gb: float = 0.0
    vhd_file_gb: float = 0.0
    vhd_bloat_gb: float = 0.0  # vhd_file - actual data inside
    docker_running: bool = False
    error: Optional[str] = None


@dataclass
class DockerCleanupResult:
    success: bool = False
    actions: list = field(default_factory=list)
    space_freed_gb: float = 0.0
    errors: list = field(default_factory=list)


class DockerGuardian:
    """
    Monitors Docker disk usage and automatically prunes when thresholds are hit.

    VHD compaction (recovering bloat) requires admin + Docker fully stopped.
    Guardian alerts when compaction is needed; the compact_docker.bat handles
    the actual diskpart operation when run as Administrator.
    """

    def __init__(
        self,
        cache_prune_threshold_gb: float = 3.0,
        vhd_bloat_alert_gb: float = 4.0,
        images_warn_gb: float = 10.0,
        auto_prune: bool = True,
        vhd_path: Path = DOCKER_VHD_PATH,
        enable_daemon_config: bool = True,
    ):
        self.cache_prune_threshold_gb = cache_prune_threshold_gb
        self.vhd_bloat_alert_gb = vhd_bloat_alert_gb
        self.images_warn_gb = images_warn_gb
        self.auto_prune = auto_prune
        self.vhd_path = vhd_path
        self.enable_daemon_config = enable_daemon_config
        self.logger = logging.getLogger("DockerGuardian")
        self._daemon_config = None
        self._initialized = False

    @property
    def daemon_config(self):
        """Lazy-load daemon configuration manager."""
        if self._daemon_config is None:
            try:
                from Guardian.modules.docker.docker_daemon_config import (
                    DockerDaemonConfig,
                )

                self._daemon_config = DockerDaemonConfig()
            except ImportError:
                self.logger.warning(
                    "DockerDaemonConfig not available — daemon config features disabled"
                )
                self._daemon_config = False
        return self._daemon_config if self._daemon_config else None

    def initialize(self, restart_daemon: bool = False) -> Dict[str, Any]:
        """Initialize Guardian and configure Docker daemon for auto-cleanup."""
        result = {"success": False, "changes": [], "errors": []}

        if not self.enable_daemon_config:
            result["success"] = True
            return result

        if self._initialized:
            result["success"] = True
            return result

        try:
            config_mgr = self.daemon_config
            if not config_mgr:
                result["errors"].append(
                    "Daemon config manager not available"
                )
                return result

            # Configure log rotation to prevent disk bloat
            config_result = config_mgr.configure_auto_cleanup(
                enable_log_rotation=True,
                max_log_size="10m",
                max_log_files=3,
                restart_daemon=restart_daemon,
            )

            result["success"] = config_result.get("success", False)
            result["changes"].extend(config_result.get("changes", []))
            result["errors"].extend(config_result.get("errors", []))

            if config_result.get("daemon_restarted"):
                result["daemon_restarted"] = True

            self._initialized = True
        except Exception as e:
            self.logger.error(f"Error initializing daemon config: {e}")
            result["errors"].append(str(e))

        return result

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _run(self, cmd: list, timeout: int = 60) -> tuple[bool, str, str]:
        try:
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
            return r.returncode == 0, r.stdout.strip(), r.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "timeout"
        except FileNotFoundError:
            return False, "", "docker not found"
        except Exception as e:
            return False, "", str(e)

    def _is_docker_running(self) -> bool:
        ok, out, _ = self._run(
            ["docker", "info", "--format", "{{.ServerVersion}}"], timeout=5
        )
        return ok and bool(out)

    def _get_vhd_size_gb(self) -> float:
        try:
            return self.vhd_path.stat().st_size / (1024**3)
        except Exception:
            return 0.0

    @staticmethod
    def _parse_size(s: str) -> float:
        """Parse Docker size strings ('1.5GB', '512MB', '0B') into GB."""
        s = s.strip()
        if "(" in s:
            s = s.split("(")[0].strip()
        try:
            if s.endswith("GB"):
                return float(s[:-2])
            elif s.endswith("MB"):
                return float(s[:-2]) / 1024
            elif s.endswith("kB"):
                return float(s[:-2]) / (1024**2)
            elif s.endswith("B") and not s.endswith("kB"):
                return float(s[:-1]) / (1024**3)
            return 0.0
        except (ValueError, IndexError):
            return 0.0

    # ── State collection ─────────────────────────────────────────────────────

    def get_disk_state(self) -> DockerDiskState:
        state = DockerDiskState(timestamp=datetime.now())
        state.vhd_file_gb = self._get_vhd_size_gb()
        state.docker_running = self._is_docker_running()

        if not state.docker_running:
            state.error = "Docker not running"
            return state

        ok, out, err = self._run(
            ["docker", "system", "df", "--format", "{{json .}}"], timeout=20
        )
        if not ok:
            state.error = f"docker system df failed: {err}"
            return state

        total_used = 0.0
        total_reclaimable = 0.0
        for line in out.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
                typ = obj.get("Type", "")
                size = self._parse_size(obj.get("Size", "0B"))
                reclaim = self._parse_size(obj.get("Reclaimable", "0B"))
                total_used += size
                total_reclaimable += reclaim

                if "Build Cache" in typ:
                    state.build_cache_gb = size
                elif "Images" in typ:
                    state.images_size_gb = size
                elif "Containers" in typ:
                    state.containers_size_gb = size
                elif "Volumes" in typ:
                    state.volumes_size_gb = size
            except (json.JSONDecodeError, KeyError):
                pass

        state.total_reclaimable_gb = total_reclaimable
        state.vhd_bloat_gb = max(0.0, state.vhd_file_gb - total_used)
        return state

    # ── Actions ───────────────────────────────────────────────────────────────

    def prune(self, aggressive: bool = False) -> DockerCleanupResult:
        """
        Prune Docker disk usage.
        aggressive=True also removes all unused images (not just dangling).
        """
        result = DockerCleanupResult()

        if not self._is_docker_running():
            result.errors.append("Docker not running — cannot prune")
            return result

        before = self.get_disk_state()

        # Standard: build cache + stopped containers + dangling images
        ok, out, err = self._run(
            ["docker", "system", "prune", "-f"], timeout=180
        )
        if ok:
            result.actions.append(
                "pruned build cache + dangling images + stopped containers"
            )
            self.logger.info(f"docker system prune: {out[:300]}")
        else:
            result.errors.append(f"docker system prune failed: {err[:200]}")

        if aggressive:
            ok2, out2, err2 = self._run(
                ["docker", "image", "prune", "-a", "-f"], timeout=180
            )
            if ok2:
                result.actions.append("pruned all unused images")
                self.logger.info(f"image prune -a: {out2[:200]}")
            else:
                result.errors.append(f"image prune -a failed: {err2[:100]}")

        after = self.get_disk_state()
        result.space_freed_gb = max(
            0.0,
            (before.build_cache_gb - after.build_cache_gb)
            + (before.images_size_gb - after.images_size_gb),
        )
        result.success = len(result.errors) == 0
        return result

    def prune_containers(self) -> DockerCleanupResult:
        """Prune stopped containers only."""
        result = DockerCleanupResult()

        if not self._is_docker_running():
            result.errors.append("Docker not running")
            return result

        ok, out, err = self._run(["docker", "container", "prune", "-f"], timeout=60)
        if ok:
            result.actions.append("pruned stopped containers")
            self.logger.info(f"container prune: {out[:200]}")
            result.success = True
        else:
            result.errors.append(f"container prune failed: {err[:100]}")

        return result

    def prune_volumes(self) -> DockerCleanupResult:
        """Prune dangling volumes."""
        result = DockerCleanupResult()

        if not self._is_docker_running():
            result.errors.append("Docker not running")
            return result

        ok, out, err = self._run(["docker", "volume", "prune", "-f"], timeout=60)
        if ok:
            result.actions.append("pruned dangling volumes")
            self.logger.info(f"volume prune: {out[:200]}")
            result.success = True
        else:
            result.errors.append(f"volume prune failed: {err[:100]}")

        return result

    # ── Main check ────────────────────────────────────────────────────────────

    def check_and_heal(self) -> Dict[str, Any]:
        """Check Docker disk state and auto-heal if thresholds are breached."""
        state = self.get_disk_state()
        actions = []
        alerts = []

        if state.error and not state.docker_running:
            return {
                "state": {"docker_running": False, "error": state.error},
                "actions": [],
                "alerts": [],
            }

        # Auto-prune build cache
        if state.build_cache_gb >= self.cache_prune_threshold_gb and self.auto_prune:
            self.logger.warning(
                f"Docker build cache {state.build_cache_gb:.1f}GB "
                f">= {self.cache_prune_threshold_gb:.1f}GB threshold — pruning"
            )
            result = self.prune(aggressive=False)
            actions.extend(result.actions)
            if result.space_freed_gb > 0:
                actions.append(f"docker freed {result.space_freed_gb:.2f}GB")

        # Warn about large image store
        if state.images_size_gb >= self.images_warn_gb:
            alerts.append(
                f"Docker images using {state.images_size_gb:.1f}GB — "
                f"consider: docker image prune -a -f"
            )

        # Alert when VHD bloat warrants compaction
        if state.vhd_bloat_gb >= self.vhd_bloat_alert_gb:
            alerts.append(
                f"Docker VHD bloat {state.vhd_bloat_gb:.1f}GB "
                f"(file={state.vhd_file_gb:.1f}GB, "
                f"data~{state.vhd_file_gb - state.vhd_bloat_gb:.1f}GB). "
                f"Guardian should compact this automatically via its elevated compact task."
            )

        return {
            "state": {
                "build_cache_gb": round(state.build_cache_gb, 2),
                "images_size_gb": round(state.images_size_gb, 2),
                "containers_size_gb": round(state.containers_size_gb, 2),
                "volumes_size_gb": round(state.volumes_size_gb, 2),
                "total_reclaimable_gb": round(state.total_reclaimable_gb, 2),
                "vhd_file_gb": round(state.vhd_file_gb, 2),
                "vhd_bloat_gb": round(state.vhd_bloat_gb, 2),
                "docker_running": state.docker_running,
            },
            "actions": actions,
            "alerts": alerts,
        }

    def get_summary(self) -> Dict[str, Any]:
        """Alias for proactive_guardian compatibility."""
        return self.check_and_heal()


def create_docker_guardian(**kwargs) -> DockerGuardian:
    return DockerGuardian(**kwargs)


if __name__ == "__main__":
    import json as _json

    logging.basicConfig(level=logging.INFO)
    guardian = DockerGuardian()
    
    print("Initializing Docker Guardian...")
    init_result = guardian.initialize(restart_daemon=False)
    print(_json.dumps(init_result, indent=2))
    
    print("\nChecking Docker health...")
    result = guardian.check_and_heal()
    print(_json.dumps(result, indent=2))
