#!/usr/bin/env python3
"""
Proactive Guardian - AI-Powered Auto-Healing System
PromptOS Module

The ultimate proactive system guardian that:
- Monitors all sensors (Windows, WSL, Network)
- Uses Alfred's governed single model lane to make intelligent decisions
- Automatically triggers healing actions
- Logs everything with heartbeat reports
- Learns patterns from past decisions

Auto-Healing Triggers:
- RAM > 60%: WSL memory reclaim
- RAM > 80%: Windows cleanup + WSL reclaim
- RAM > 90%: Aggressive cleanup
- Disk > 85%: WSL trim
- Disk > 90%: WSL shrink + Windows cleanup
- Load average > cores: Throttle processes
- Temperature > 85°C: Thermal throttle
- Temperature > 90°C: Aggressive throttle
- OOM events: Log and alert
- Zombie processes: Reap
- Network down: Log and retry
"""

import time
import logging
import threading
from dataclasses import dataclass, field, asdict
from typing import Optional, List, Dict, Any
from datetime import datetime
import json
from pathlib import Path


@dataclass
class GuardianConfig:
    # Memory thresholds
    wsl_memory_threshold: float = 60.0
    windows_memory_warning: float = 70.0
    windows_memory_critical: float = 85.0

    # Disk thresholds
    disk_warning: float = 80.0
    disk_critical: float = 90.0

    # CPU thresholds
    load_threshold_ratio: float = 1.0  # load / cores
    cpu_critical: float = 95.0

    # Temperature thresholds
    temp_warning: float = 80.0
    temp_critical: float = 90.0

    # Intervals
    check_interval: int = 60  # seconds
    heartbeat_interval: int = 60  # seconds

    # Features
    auto_heal: bool = True
    use_ai: bool = True
    log_heartbeats: bool = True
    report_interval_minutes: int = 360

    # WSL
    wsl_distro: str = "Ubuntu"


class ProactiveGuardian:
    """
    The main proactive guardian that monitors everything and auto-heals.
    """

    def __init__(self, config: GuardianConfig = None):
        self.config = config or GuardianConfig()
        self.logger = self._setup_logging()

        self._running = False
        self._health_history: List[Dict] = []
        self._event_cooldowns: Dict[str, float] = {}
        self._paging_hot_cycles: int = 0
        self._remediation_state_path = self._guardian_log_dir() / "remediation_state.json"
        self._latest_report_path = self._guardian_log_dir() / "latest_report.json"
        self._remediation_state: Dict[str, Dict[str, Any]] = self._load_json_state(
            self._remediation_state_path
        )
        self._last_report_sent_at: float = 0.0

        self._init_modules()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("ProactiveGuardian")
        logger.setLevel(logging.INFO)

        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter(
                "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)

        return logger

    def _init_modules(self):
        """Initialize all sensor modules."""
        self.logger.info("Initializing Guardian modules...")

        try:
            from Guardian.modules.sensors import (
                LinuxSensors,
                WSLMemoryBalancer,
                ZombieProcessKiller,
            )

            self.linux_sensors = LinuxSensors(self.config.wsl_distro)
            self.wsl_balancer = WSLMemoryBalancer(
                self.config.wsl_distro, self.config.wsl_memory_threshold
            )
            self.zombie_killer = ZombieProcessKiller(self.config.wsl_distro)
        except Exception as e:
            self.logger.warning(f"Linux sensors unavailable: {e}")
            self.linux_sensors = None
            self.wsl_balancer = None
            self.zombie_killer = None

        try:
            from Guardian.modules.sensors import WindowsSensors

            self.windows_sensors = WindowsSensors()
        except Exception as e:
            self.logger.warning(f"Windows sensors unavailable: {e}")
            self.windows_sensors = None

        try:
            from Guardian.modules.network import NetworkMonitor

            self.network_monitor = NetworkMonitor()
        except Exception as e:
            self.logger.warning(f"Network monitor unavailable: {e}")
            self.network_monitor = None

        try:
            from Guardian.modules.services.ai_guardian import AIGuardianBrain

            self.ai_brain = AIGuardianBrain()
        except Exception as e:
            self.logger.warning(f"AI brain unavailable: {e}")
            self.ai_brain = None

        try:
            from Guardian.modules.monitor.heartbeat_logger import HeartbeatLogger

            self.heartbeat_logger = HeartbeatLogger()
        except Exception as e:
            self.logger.warning(f"Heartbeat logger unavailable: {e}")
            self.heartbeat_logger = None

        try:
            from Guardian.modules.wsl import WSLManager

            self.wsl_manager = WSLManager(self.config.wsl_distro)
        except Exception as e:
            self.logger.warning(f"WSL manager unavailable: {e}")
            self.wsl_manager = None

        try:
            from Guardian.modules.alerts.alfred_bridge import notify_alfred
            self._notify = notify_alfred
        except Exception as e:
            self.logger.warning(f"Alfred bridge unavailable: {e}")
            self._notify = None

        # Keep Telegram as fallback if Alfred is unreachable
        try:
            from Guardian.modules.alerts.telegram_alerts import TelegramAlerts
            self.telegram = TelegramAlerts()
        except Exception as e:
            self.telegram = None

        self._last_disk_alert_pct: float = 0.0
        self._last_runaway_scan: float = 0.0

        try:
            from Guardian.modules.docker.docker_guardian import DockerGuardian

            self.docker_guardian = DockerGuardian(
                cache_prune_threshold_gb=getattr(self.config, "docker_cache_prune_threshold_gb", 3.0),
                vhd_bloat_alert_gb=getattr(self.config, "docker_vhd_bloat_alert_gb", 4.0),
                images_warn_gb=getattr(self.config, "docker_images_warn_gb", 10.0),
                auto_prune=getattr(self.config, "docker_auto_prune", True),
            )
        except Exception as e:
            self.logger.warning(f"Docker guardian unavailable: {e}")
            self.docker_guardian = None

        try:
            from Guardian.modules.services.service_health import ServiceHealthMonitor
            self.service_health = ServiceHealthMonitor()
        except Exception as e:
            self.logger.warning(f"Service health monitor unavailable: {e}")
            self.service_health = None

        try:
            from Guardian.modules.services.ollama_monitor import scan as ollama_scan
            self._ollama_scan = ollama_scan
        except Exception as e:
            self.logger.warning(f"Ollama monitor unavailable: {e}")
            self._ollama_scan = None

        try:
            from Guardian.modules.docker.docker_log_cap import check as docker_log_check
            self._docker_log_check = docker_log_check
        except Exception as e:
            self.logger.warning(f"Docker log cap unavailable: {e}")
            self._docker_log_check = None

        try:
            from Guardian.modules.wsl.vhd_compact import VHDCompactor
            self.vhd_compactor = VHDCompactor()
        except Exception as e:
            self.logger.warning(f"VHD compactor unavailable: {e}")
            self.vhd_compactor = None

        try:
            from Guardian.modules.performance.runaway_detector import RunawayDetector
            self.runaway_detector = RunawayDetector(
                warn_gb=2.0,
                kill_gb=8.0,
                auto_kill=False,
                alert_callback=self._on_runaway_process,
            )
        except Exception as e:
            self.logger.warning(f"Runaway detector unavailable: {e}")
            self.runaway_detector = None

        try:
            from Guardian.modules.monitor.log_watcher import get_summary as log_summary
            self._log_summary = log_summary
        except Exception as e:
            self.logger.warning(f"Log watcher unavailable: {e}")
            self._log_summary = None

        # Run disk report + cache scan once at startup (background-safe)
        self._startup_complete = False

        self.logger.info("Guardian modules initialized")

    def _guardian_log_dir(self) -> Path:
        log_dir = Path(__file__).resolve().parents[2] / "logs"
        log_dir.mkdir(parents=True, exist_ok=True)
        return log_dir

    def _load_json_state(self, path: Path) -> Dict[str, Dict[str, Any]]:
        try:
            if path.exists():
                payload = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(payload, dict):
                    return payload
        except Exception as e:
            self.logger.warning(f"Failed to load Guardian state from {path.name}: {e}")
        return {}

    def _save_json_state(self, path: Path, payload: Dict[str, Dict[str, Any]]) -> None:
        try:
            path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        except Exception as e:
            self.logger.warning(f"Failed to persist Guardian state to {path.name}: {e}")

    def _notify_guardian(
        self,
        level: str,
        title: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        force: bool = False,
    ) -> bool:
        delivered = False
        if self._notify:
            try:
                delivered = bool(self._notify(level, title, message, data))
            except Exception as e:
                self.logger.warning(f"Guardian notify failed via Alfred: {e}")

        if delivered or not self.telegram:
            return delivered

        try:
            from Guardian.modules.alerts.telegram_alerts import AlertLevel

            level_name = str(level or "INFO").upper()
            alert_level = getattr(AlertLevel, level_name, AlertLevel.INFO)
            return bool(
                self.telegram.send(
                    alert_level,
                    title,
                    message,
                    data or {},
                    force=force or alert_level in {AlertLevel.ERROR, AlertLevel.CRITICAL},
                )
            )
        except Exception as e:
            self.logger.warning(f"Guardian notify failed via Telegram fallback: {e}")
            return False

    def _remediation_entry(self, key: str) -> Dict[str, Any]:
        entry = self._remediation_state.get(key)
        if not isinstance(entry, dict):
            entry = {}
            self._remediation_state[key] = entry
        return entry

    def _remediation_blocked(self, key: str) -> bool:
        entry = self._remediation_entry(key)
        return float(entry.get("cooldown_until", 0) or 0) > time.time()

    def _set_remediation_cooldown(
        self,
        key: str,
        seconds: int,
        *,
        reason: str = "",
        failures: Optional[int] = None,
    ) -> None:
        entry = self._remediation_entry(key)
        entry["cooldown_until"] = time.time() + max(0, int(seconds))
        entry["last_error"] = reason
        entry["last_attempt_at"] = datetime.now().isoformat()
        if failures is not None:
            entry["failures"] = failures
        self._save_json_state(self._remediation_state_path, self._remediation_state)

    def _on_runaway_process(self, process, ram_gb: float) -> None:
        """Alert callback fired when RunawayDetector finds a RAM hog."""
        self._notify_guardian(
            "WARNING",
            f"Runaway process: {process.name} using {ram_gb:.1f}GB RAM",
            f"PID {process.pid} ({process.name}) is consuming {ram_gb:.1f}GB RAM.\n"
            f"Command: {process.cmdline[:100]}\n"
            f"{'AI model server — consider stopping if not needed.' if process.is_ai_server else ''}",
            {"pid": process.pid, "name": process.name, "ram_gb": round(ram_gb, 2)},
            force=ram_gb > 5.0,
        )

    def _attempt_docker_vhd_compact(self, disk: float, actions: List[str]) -> None:
        """Prune Docker first, then compact VHD only if real slack remains."""
        if not self.vhd_compactor:
            return

        compact_key = "docker-vhd-compact"
        if self._remediation_blocked(compact_key):
            return

        try:
            prune_summary = None
            docker_state = None
            vhd_bloat_threshold = 1.0
            reclaimable_threshold = 1.0

            if self.docker_guardian:
                try:
                    state = self.docker_guardian.get_disk_state()
                    if not state.error:
                        docker_state = state
                        vhd_bloat_threshold = max(
                            1.0,
                            float(getattr(self.docker_guardian, "vhd_bloat_alert_gb", 4.0) or 4.0),
                        )
                        reclaimable_threshold = max(
                            1.0,
                            float(getattr(self.docker_guardian, "cache_prune_threshold_gb", 3.0) or 3.0),
                        )
                except Exception as e:
                    self.logger.warning(f"Docker state pre-check failed: {e}")

            if docker_state and docker_state.docker_running and docker_state.total_reclaimable_gb >= reclaimable_threshold:
                prune_result = self.docker_guardian.prune(aggressive=False)
                prune_summary = {
                    "success": prune_result.success,
                    "space_freed_gb": round(prune_result.space_freed_gb, 2),
                    "actions": prune_result.actions,
                    "errors": prune_result.errors,
                }
                actions.append(f"docker_prune:{prune_result.space_freed_gb:.1f}GB")
                if not prune_result.success:
                    self.logger.warning(f"Docker prune before compact had errors: {prune_result.errors}")

                try:
                    refreshed = self.docker_guardian.get_disk_state()
                    if not refreshed.error:
                        docker_state = refreshed
                except Exception as e:
                    self.logger.warning(f"Docker state refresh after prune failed: {e}")

            if docker_state and docker_state.vhd_bloat_gb < vhd_bloat_threshold:
                actions.append("docker_vhd_compact_skipped")
                self._mark_remediation_success(compact_key, cooldown_seconds=24 * 60 * 60)
                self._notify_guardian(
                    "INFO",
                    "Docker prune completed; compact not needed",
                    f"Guardian pruned Docker reclaimable content and re-measured the VHD. "
                    f"Remaining slack is only {docker_state.vhd_bloat_gb:.1f}GB, below the compact threshold.",
                    {
                        "disk_percent": disk,
                        "docker_state": {
                            "vhd_file_gb": round(docker_state.vhd_file_gb, 2),
                            "vhd_bloat_gb": round(docker_state.vhd_bloat_gb, 2),
                            "total_reclaimable_gb": round(docker_state.total_reclaimable_gb, 2),
                        },
                        "prune_summary": prune_summary,
                    },
                    force=True,
                )
                return

            vhds = self.vhd_compactor.find_vhds()
            docker_vhds = [v for v in vhds if "Docker" in v.label]
            if not docker_vhds:
                return

            total_gb = sum(v.size_gb for v in docker_vhds)
            if total_gb < 5.0:
                # Not worth the disruption
                return

            if not getattr(self.vhd_compactor, "is_admin", lambda: False)():
                scheduled = getattr(
                    self.vhd_compactor,
                    "trigger_compact_task",
                    lambda: {"success": False, "details": "scheduler unavailable"},
                )()
                if scheduled.get("success"):
                    actions.append("docker_vhd_compact_scheduled")
                    self._mark_remediation_success(compact_key, cooldown_seconds=24 * 60 * 60)
                    self._notify_guardian(
                        "WARNING",
                        f"Docker VHD compact queued ({total_gb:.1f}GB total)",
                        "Guardian is not elevated in this session, so it handed Docker compaction off "
                        "to the elevated scheduled task. Docker will be stopped, compacted, restarted, and verified there.",
                        {
                            "disk_percent": disk,
                            "docker_vhd_gb": round(total_gb, 1),
                            "task": scheduled.get("task_name"),
                            "prune_summary": prune_summary,
                        },
                        force=True,
                    )
                    return
                self.logger.error(f"Docker VHD compact scheduling failed: {scheduled.get('details')}")

            self.logger.info(f"Attempting Docker VHD compact ({total_gb:.1f}GB total)...")
            self._notify_guardian(
                "WARNING",
                f"Docker VHD bloated ({total_gb:.1f}GB) — compacting now",
                f"Disk is at {disk:.0f}%. Docker VHD is {total_gb:.1f}GB. "
                f"Guardian is running diskpart compact. WSL/Docker will restart.",
                {"disk_percent": disk, "docker_vhd_gb": round(total_gb, 1)},
                force=True,
            )

            result = self.vhd_compactor.compact_all(shutdown_first=True)
            freed = result.get("total_freed_gb", 0)

            if result.get("vhds_compacted", 0) > 0:
                actions.append(f"docker_vhd_compact:{freed:.1f}GB")
                self._mark_remediation_success(compact_key, cooldown_seconds=24 * 60 * 60)
                docker_restart = result.get("docker_restart", {}) or {}
                self._notify_guardian(
                    "INFO",
                    f"Docker VHD compacted — freed {freed:.1f}GB",
                    f"Guardian compacted Docker VHDs and recovered {freed:.1f}GB of disk space. "
                    f"Docker restart ready={docker_restart.get('ready') is True}.",
                    {
                        "freed_gb": freed,
                        "disk_percent": disk,
                        "docker_restart": docker_restart,
                        "prune_summary": prune_summary,
                    },
                    force=True,
                )
            else:
                err = str(result.get("results", [{}])[0].get("error", "unknown"))
                self._mark_remediation_failure(compact_key, err, base_cooldown_seconds=3600)
                self.logger.error(f"Docker VHD compact failed: {err}")

        except Exception as e:
            self._mark_remediation_failure(compact_key, str(e), base_cooldown_seconds=3600)
            self.logger.error(f"Docker VHD compact exception: {e}")

    def _mark_remediation_success(self, key: str, cooldown_seconds: int = 0) -> None:
        self._remediation_state[key] = {
            "cooldown_until": time.time() + max(0, int(cooldown_seconds)),
            "failures": 0,
            "last_error": None,
            "last_success_at": datetime.now().isoformat(),
        }
        self._save_json_state(self._remediation_state_path, self._remediation_state)

    def _mark_remediation_failure(
        self,
        key: str,
        reason: str,
        *,
        base_cooldown_seconds: int = 900,
        max_cooldown_seconds: int = 21600,
    ) -> int:
        entry = self._remediation_entry(key)
        failures = int(entry.get("failures", 0) or 0) + 1
        cooldown = min(max_cooldown_seconds, base_cooldown_seconds * (2 ** (failures - 1)))
        self._set_remediation_cooldown(
            key,
            cooldown,
            reason=reason,
            failures=failures,
        )
        return cooldown

    def _should_emit_event(self, key: str, cooldown_seconds: int = 900) -> bool:
        now = time.time()
        last = self._event_cooldowns.get(key, 0.0)
        if now - last < cooldown_seconds:
            return False
        self._event_cooldowns[key] = now
        return True

    def _log_guardian_event(
        self,
        level: str,
        message: str,
        data: Optional[Dict[str, Any]] = None,
        notify: bool = False,
        cooldown_key: Optional[str] = None,
        cooldown_seconds: int = 900,
    ) -> None:
        if cooldown_key and not self._should_emit_event(cooldown_key, cooldown_seconds):
            return

        if self.heartbeat_logger:
            try:
                if level == "CRITICAL":
                    self.heartbeat_logger.log_critical("guardian", message, data)
                elif level == "ERROR":
                    self.heartbeat_logger.log_error("guardian", message, data)
                elif level == "WARNING":
                    self.heartbeat_logger.log_warning("guardian", message, data)
                else:
                    self.heartbeat_logger.log_info("guardian", message, data)
            except Exception as e:
                self.logger.error(f"Guardian event logging failed: {e}")

        if notify:
            self._notify_guardian(level, "Guardian", message, data)

    def _record_memory_events(self, health_data: Dict[str, Any]) -> None:
        memory = health_data.get("memory_pressure", {})
        if not memory:
            return

        top_groups = memory.get("top_groups", [])
        heavy_groups = [
            group for group in top_groups
            if group.get("name", "").lower().replace(".exe", "") in {"claude", "codex", "node", "ollama", "vmmem", "vmmemwsl", "qdrant", "onedrive"}
        ]
        pages_per_sec = float(memory.get("pages_per_sec", 0) or 0.0)
        page_reads_per_sec = float(memory.get("page_reads_per_sec", 0) or 0.0)
        commit_percent = float(memory.get("commit_percent", 0) or 0.0)

        if pages_per_sec >= 100 or page_reads_per_sec >= 50:
            self._paging_hot_cycles += 1
        else:
            self._paging_hot_cycles = 0

        if commit_percent >= 90 or page_reads_per_sec >= 50:
            self._log_guardian_event(
                "CRITICAL",
                f"Memory pressure critical: commit {commit_percent:.0f}%, paging {pages_per_sec:.0f}/s",
                {
                    "commit_percent": commit_percent,
                    "available_gb": memory.get("available_gb"),
                    "pages_per_sec": pages_per_sec,
                    "page_reads_per_sec": page_reads_per_sec,
                    "paging_hot_cycles": self._paging_hot_cycles,
                    "top_groups": heavy_groups[:5],
                },
                notify=True,
                cooldown_key="memory-critical",
                cooldown_seconds=600,
            )
        elif commit_percent >= 85:
            self._log_guardian_event(
                "WARNING",
                f"Memory pressure elevated: commit {commit_percent:.0f}%",
                {
                    "commit_percent": commit_percent,
                    "available_gb": memory.get("available_gb"),
                    "pages_per_sec": pages_per_sec,
                    "page_reads_per_sec": page_reads_per_sec,
                    "paging_hot_cycles": self._paging_hot_cycles,
                    "top_groups": heavy_groups[:5],
                },
                notify=True,
                cooldown_key="memory-warning",
                cooldown_seconds=900,
            )

        if self._paging_hot_cycles >= 3:
            self._log_guardian_event(
                "CRITICAL",
                f"Sustained paging anomaly: {pages_per_sec:.0f} pages/s, {page_reads_per_sec:.0f} reads/s for {self._paging_hot_cycles} cycles",
                {
                    "commit_percent": commit_percent,
                    "available_gb": memory.get("available_gb"),
                    "pages_per_sec": pages_per_sec,
                    "page_reads_per_sec": page_reads_per_sec,
                    "paging_hot_cycles": self._paging_hot_cycles,
                    "top_groups": heavy_groups[:5],
                },
                notify=True,
                cooldown_key="paging-anomaly",
                cooldown_seconds=600,
            )

        for group in heavy_groups:
            name = str(group.get("name", "")).lower().replace(".exe", "")
            procs = int(group.get("processes", 0) or 0)
            private_gb = float(group.get("private_gb", 0) or 0.0)
            if procs >= 2 and private_gb >= 0.8:
                self._log_guardian_event(
                    "WARNING",
                    f"Duplicate heavy process group: {group.get('name')} {private_gb:.2f}GB across {procs} processes",
                    group,
                    notify=True,
                    cooldown_key=f"dup-{name}",
                    cooldown_seconds=1800,
                )

    def _record_runtime_events(self, health_data: Dict[str, Any]) -> None:
        services = health_data.get("services", {})
        for svc in services.get("down_services", []):
            name = svc.get("name", "unknown")
            port = svc.get("port", "?")
            self._log_guardian_event(
                "ERROR",
                f"Service down: {name} (:{port})",
                svc,
                notify=True,
                cooldown_key=f"service-down-{str(name).lower().replace(' ', '-')}",
                cooldown_seconds=900,
            )

        ollama = health_data.get("ollama", {})
        serve_process_count = int(ollama.get("serve_process_count", 0) or 0)
        runner_process_count = int(ollama.get("runner_process_count", 0) or 0)
        loaded_by_port = ollama.get("loaded_by_port", {}) or {}
        active_loaded = sum(len(models or []) for models in loaded_by_port.values())
        if serve_process_count > 3:
            self._log_guardian_event(
                "WARNING",
                f"Ollama serve-process anomaly: {serve_process_count} serve processes running",
                ollama,
                notify=True,
                cooldown_key="ollama-serve-process-count",
                cooldown_seconds=1200,
            )
        elif runner_process_count > active_loaded:
            self._log_guardian_event(
                "WARNING",
                f"Ollama runner anomaly: {runner_process_count} runner processes for {active_loaded} loaded model(s)",
                ollama,
                notify=True,
                cooldown_key="ollama-runner-process-count",
                cooldown_seconds=1200,
            )

        duplicate_loaded = list(ollama.get("duplicate_loaded", []) or [])
        if duplicate_loaded:
            self._log_guardian_event(
                "WARNING",
                f"Ollama duplicate model loads detected: {', '.join(duplicate_loaded[:4])}",
                {"duplicate_loaded": duplicate_loaded},
                notify=True,
                cooldown_key="ollama-duplicate-loaded",
                cooldown_seconds=1800,
            )

    def _attempt_wsl_disk_remediation(self, disk: float, actions: List[str]) -> None:
        if not self.wsl_manager:
            return

        from Guardian.modules.wsl import optimize_wsl, shrink_wsl_disk

        running = bool(getattr(self.wsl_manager, "is_running", lambda *_: False)(self.config.wsl_distro))

        optimize_key = "wsl-disk-optimize"
        if running and not self._remediation_blocked(optimize_key):
            try:
                optimize_result = optimize_wsl(self.config.wsl_distro, shrink=False)
                if optimize_result.get("memory_optimized"):
                    actions.append("wsl_memory_optimized")
                if optimize_result.get("filesystem_trimmed"):
                    actions.append("wsl_filesystem_trimmed")
                self._mark_remediation_success(optimize_key)
            except Exception as e:
                cooldown = self._mark_remediation_failure(
                    optimize_key,
                    str(e),
                    base_cooldown_seconds=1800,
                    max_cooldown_seconds=14400,
                )
                self.logger.error(f"WSL pre-shrink optimize failed: {e}")
                self._notify_guardian(
                    "ERROR",
                    "WSL pre-shrink optimize failed",
                    f"Guardian could not trim/prepare WSL before compaction: {e}. "
                    f"Retry suppressed for {cooldown // 60} minutes.",
                    {"disk_percent": disk},
                    force=True,
                )

        shrink_key = "wsl-disk-shrink"
        if self._remediation_blocked(shrink_key):
            return

        try:
            result = shrink_wsl_disk(self.config.wsl_distro)
            if result.get("success"):
                saved = float(
                    result.get("space_saved_gb", result.get("saved_gb", 0)) or 0.0
                )
                actions.append(f"wsl_shrink:{saved:.1f}GB")
                self._mark_remediation_success(shrink_key)
                if saved > 0.1:
                    self._notify_guardian(
                        "INFO",
                        f"WSL VHD compacted — freed {saved:.1f}GB",
                        "Guardian compacted the WSL VHD to recover disk space.",
                        {"disk_percent": disk, "space_saved_gb": saved},
                    )
                return

            err = str(result.get("error", "unknown"))
            error_text = err.lower()
            if "e_invalidarg" in error_text or "set-sparse" in error_text or "sparse vhd support is currently disabled" in error_text:
                cooldown = 12 * 60 * 60
                self._set_remediation_cooldown(
                    shrink_key,
                    cooldown,
                    reason=err,
                    failures=int(self._remediation_entry(shrink_key).get("failures", 0) or 0) + 1,
                )
                actions.append("wsl_shrink_unsupported")
                self.logger.error(f"WSL shrink unsupported on this host: {err}")
                self._notify_guardian(
                    "ERROR",
                    "WSL disk shrink unsupported on this host",
                    f"Guardian tried to compact the WSL VHD but Windows rejected sparse compaction: {err}. "
                    f"That path is now paused for {cooldown // 3600} hours instead of repeating every cycle.",
                    {"disk_percent": disk, "distro": self.config.wsl_distro},
                    force=True,
                )
                # Fallback: compact Docker VHD instead (diskpart method, no sparse needed)
                self._attempt_docker_vhd_compact(disk, actions)
                return

            cooldown = self._mark_remediation_failure(
                shrink_key,
                err,
                base_cooldown_seconds=1800,
                max_cooldown_seconds=21600,
            )
            actions.append(f"wsl_shrink_failed:{err}")
            self.logger.error(f"WSL shrink failed: {err}")
            self._notify_guardian(
                "ERROR",
                "WSL disk shrink failed",
                f"Tried to compact the WSL VHD but failed: {err}. Retry suppressed for {cooldown // 60} minutes.",
                {"disk_percent": disk, "distro": self.config.wsl_distro},
                force=True,
            )
        except Exception as e:
            cooldown = self._mark_remediation_failure(
                shrink_key,
                str(e),
                base_cooldown_seconds=1800,
                max_cooldown_seconds=21600,
            )
            actions.append(f"wsl_shrink_error:{str(e)[:50]}")
            self.logger.error(f"WSL shrink failed: {e}")
            self._notify_guardian(
                "ERROR",
                "WSL disk shrink raised an exception",
                f"Guardian hit an exception while compacting WSL: {e}. Retry suppressed for {cooldown // 60} minutes.",
                {"disk_percent": disk, "distro": self.config.wsl_distro},
                force=True,
            )

    def _attempt_safe_cleanup(self, disk: float, actions: List[str]) -> None:
        cleanup_key = "safe-cleanup-pass"
        if self._remediation_blocked(cleanup_key):
            return

        try:
            import psutil as _ps
            from Guardian.modules.performance.safe_cleanup_pass import run_safe_cleanup

            before = _ps.disk_usage("C:")
            report = run_safe_cleanup()
            after = _ps.disk_usage("C:")
            freed_gb = max(0.0, float(after.free - before.free) / (1024 ** 3))

            cleanup_log = self._guardian_log_dir() / "latest_safe_cleanup.json"
            cleanup_log.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")

            action = f"safe_cleanup:{freed_gb:.2f}GB"
            actions.append(action)
            self._mark_remediation_success(cleanup_key)

            error_count = len(report.errors)
            removed = len(report.stale_temp_paths_removed) + len(report.stale_partial_downloads_removed)
            self._notify_guardian(
                "INFO" if freed_gb > 0 else "WARNING",
                f"Guardian safe cleanup ran — freed {freed_gb:.2f}GB",
                f"Disk pressure triggered Guardian cleanup. Removed {removed} stale paths; "
                f"Windows cleanup freed {report.windows_space_freed_mb:.0f}MB; "
                f"errors={error_count}.",
                {
                    "disk_percent": disk,
                    "freed_gb": round(freed_gb, 2),
                    "windows_space_freed_mb": report.windows_space_freed_mb,
                    "stale_temp_paths_removed": report.stale_temp_paths_removed[:10],
                    "stale_partial_downloads_removed": report.stale_partial_downloads_removed[:10],
                    "errors": report.errors[:10],
                },
                force=disk >= 95.0,
            )
        except Exception as e:
            cooldown = self._mark_remediation_failure(
                cleanup_key,
                str(e),
                base_cooldown_seconds=1800,
                max_cooldown_seconds=21600,
            )
            actions.append(f"safe_cleanup_failed:{str(e)[:50]}")
            self.logger.error(f"Safe cleanup failed: {e}")
            self._notify_guardian(
                "ERROR",
                "Guardian safe cleanup failed",
                f"Guardian tried the safe cleanup pass but it failed: {e}. "
                f"Retry suppressed for {cooldown // 60} minutes.",
                {"disk_percent": disk},
                force=True,
            )

    def _build_operator_report(self, health_data: Dict[str, Any], actions: List[str]) -> Dict[str, Any]:
        memory = health_data.get("memory_pressure", {})
        windows = health_data.get("windows", {})
        ollama = health_data.get("ollama", {})
        top_groups = memory.get("top_groups", [])[:8]
        top_processes = memory.get("top_processes", [])[:12]
        cause_chain = []
        if top_groups:
            lead = top_groups[0]
            cause_chain.append(
                f"Top memory group is {lead.get('name')} at {float(lead.get('private_gb', 0) or 0):.2f}GB across {int(lead.get('processes', 0) or 0)} process(es)."
            )
        if ollama.get("runner_process_count", 0):
            cause_chain.append(
                f"Ollama has {ollama.get('serve_process_count', 0)} serve process(es) and {ollama.get('runner_process_count', 0)} loaded runner(s)."
            )
        loaded_by_port = ollama.get("loaded_by_port", {})
        loaded_models = []
        for port_name, models in loaded_by_port.items():
            for model in models or []:
                loaded_models.append(f"{port_name}:{model.get('name')}")
        if loaded_models:
            cause_chain.append(f"Loaded Ollama models: {', '.join(loaded_models[:6])}.")
        if memory.get("page_reads_per_sec", 0) or memory.get("pages_per_sec", 0):
            cause_chain.append(
                f"Paging is at {float(memory.get('pages_per_sec', 0) or 0):.0f} pages/s and "
                f"{float(memory.get('page_reads_per_sec', 0) or 0):.0f} reads/s."
            )
        report = {
            "timestamp": datetime.now().isoformat(),
            "windows": {
                "cpu_percent": windows.get("cpu_percent", 0),
                "memory_percent": windows.get("memory_percent", 0),
                "disk_percent": windows.get("disk_percent", 0),
            },
            "memory_pressure": {
                "ram_percent": memory.get("ram_percent", 0),
                "commit_percent": memory.get("commit_percent", 0),
                "available_gb": memory.get("available_gb"),
                "pages_per_sec": memory.get("pages_per_sec", 0),
                "page_reads_per_sec": memory.get("page_reads_per_sec", 0),
                "top_groups": top_groups,
                "top_processes": top_processes,
                "causes": memory.get("causes", []),
                "recommendations": memory.get("recommendations", []),
            },
            "services": health_data.get("services", {}),
            "ollama": ollama,
            "network": health_data.get("network", {}),
            "wsl": health_data.get("wsl", {}),
            "alerts": health_data.get("alerts", []),
            "issues": health_data.get("issues", []),
            "actions": actions,
            "cause_chain": cause_chain,
            "remediation_state": self._remediation_state,
        }
        return report

    def _persist_operator_report(self, report: Dict[str, Any]) -> None:
        self._save_json_state(self._latest_report_path, report)

    def _maybe_send_periodic_report(self, report: Dict[str, Any]) -> None:
        if not self.telegram:
            return

        interval_seconds = max(30, int(self.config.report_interval_minutes)) * 60
        now = time.time()
        if self._last_report_sent_at and (now - self._last_report_sent_at) < interval_seconds:
            return

        memory = report.get("memory_pressure", {})
        top_groups = memory.get("top_groups", [])[:4]
        hogs = ", ".join(
            f"{group.get('name')} {float(group.get('private_gb', 0) or 0):.2f}GB"
            for group in top_groups
        ) or "none"

        summary_lines = [
            f"CPU {report.get('windows', {}).get('cpu_percent', 0):.0f}%",
            f"RAM {report.get('windows', {}).get('memory_percent', 0):.0f}%",
            f"Disk {report.get('windows', {}).get('disk_percent', 0):.0f}%",
            f"Commit {float(memory.get('commit_percent', 0) or 0):.0f}%",
            f"Paging {float(memory.get('pages_per_sec', 0) or 0):.0f}/s",
        ]
        cause_headline = report.get("cause_chain", [None])[0] or "No dominant cause chain recorded."
        message = (
            "Guardian operator report\n\n"
            + "\n".join(summary_lines)
            + f"\n\nTop RAM hogs: {hogs}"
            + f"\nCause: {cause_headline}"
            + f"\nAlerts: {len(report.get('alerts', []))}"
            + f"\nActions: {', '.join(report.get('actions', [])[:6]) or 'none'}"
        )

        sent = self._notify_guardian(
            "INFO",
            "Guardian operator report",
            message,
            {
                "issues": report.get("issues", [])[:8],
                "alerts": report.get("alerts", [])[:8],
                "top_groups": top_groups,
            },
            force=True,
        )
        if sent:
            self._last_report_sent_at = now

    def collect_health_data(self) -> Dict[str, Any]:
        """Collect all health data from all sensors."""
        data = {
            "timestamp": datetime.now().isoformat(),
            "windows": {},
            "memory_pressure": {},
            "wsl": {},
            "network": {},
            "docker": {},
            "services": {},
            "ollama": {},
            "logs": {},
            "issues": [],
            "alerts": [],
        }

        if self.windows_sensors:
            try:
                win_summary = self.windows_sensors.get_summary()
                data["windows"] = win_summary

                if win_summary.get("cpu_temp", {}).get("throttling"):
                    data["alerts"].append(
                        f"CPU thermal throttling: {win_summary['cpu_temp']['celsius']}°C"
                    )

                if win_summary.get("cpu_percent", 0) > self.config.cpu_critical:
                    data["issues"].append(
                        f"High CPU usage: {win_summary['cpu_percent']}%"
                    )

                if (
                    win_summary.get("memory_percent", 0)
                    > self.config.windows_memory_critical
                ):
                    data["issues"].append(
                        f"High memory usage: {win_summary['memory_percent']}%"
                    )

                for spike in win_summary.get("spikes", []):
                    if spike.get("system"):
                        data["alerts"].append(
                            f"System process spike: {spike['name']} ({spike['cpu']}%)"
                        )

            except Exception as e:
                self.logger.error(f"Windows sensors error: {e}")

        try:
            from Guardian.modules.memory.memory_pressure import analyze_memory_pressure

            memory_report = analyze_memory_pressure()
            data["memory_pressure"] = {
                "ram_percent": memory_report.ram_percent,
                "commit_percent": memory_report.commit_percent,
                "available_gb": memory_report.available_gb,
                "pages_per_sec": memory_report.pages_per_sec,
                "page_reads_per_sec": memory_report.page_reads_per_sec,
                "top_groups": [
                    {
                        "name": group.name,
                        "private_gb": group.private_gb,
                        "rss_gb": group.rss_gb,
                        "processes": group.processes,
                    }
                    for group in memory_report.top_groups[:5]
                ],
                "top_processes": [
                    {
                        "name": proc.name,
                        "pid": proc.pid,
                        "private_gb": proc.private_gb,
                        "rss_gb": proc.rss_gb,
                        "threads": proc.threads,
                    }
                    for proc in memory_report.top_processes[:8]
                ],
                "causes": memory_report.causes,
                "recommendations": memory_report.recommendations,
            }

            if memory_report.commit_percent >= 85:
                data["issues"].append(
                    f"Commit pressure high: {memory_report.commit_percent:.0f}%"
                )

            if (
                memory_report.pages_per_sec >= 100
                or memory_report.page_reads_per_sec >= 20
            ):
                data["alerts"].append("Active paging pressure detected")
        except Exception as e:
            self.logger.error(f"Memory pressure analysis error: {e}")

        if self.linux_sensors and self.linux_sensors.is_running():
            try:
                wsl_summary = self.linux_sensors.get_summary()
                data["wsl"] = wsl_summary

                if wsl_summary.get("load", {}).get("overloaded"):
                    data["issues"].append(
                        f"WSL load overloaded: {wsl_summary['load']['1m']}"
                    )

                if wsl_summary.get("zombies", 0) > 0:
                    data["alerts"].append(f"Zombie processes: {wsl_summary['zombies']}")

                if wsl_summary.get("oom_events", 0) > 0:
                    data["issues"].append(
                        f"OOM events detected: {wsl_summary['oom_events']}"
                    )

            except Exception as e:
                self.logger.error(f"WSL sensors error: {e}")

        if self.network_monitor:
            try:
                net_summary = self.network_monitor.get_summary()
                data["network"] = net_summary

                if not net_summary.get("internet_reachable"):
                    data["alerts"].append("Internet unreachable")

            except Exception as e:
                self.logger.error(f"Network monitor error: {e}")

        if self.docker_guardian:
            try:
                docker_result = self.docker_guardian.check_and_heal()
                data["docker"] = docker_result.get("state", {})
                for alert in docker_result.get("alerts", []):
                    data["alerts"].append(alert)
                for action in docker_result.get("actions", []):
                    data["issues"].append(f"docker_auto: {action}")
            except Exception as e:
                self.logger.error(f"Docker guardian error: {e}")

        if self.service_health:
            try:
                svc_summary = self.service_health.get_summary()
                data["services"] = svc_summary
                for svc in svc_summary.get("down_services", []):
                    data["alerts"].append(
                        f"Service DOWN: {svc['name']} (:{svc['port']}) — {svc.get('error', '')}"
                    )
            except Exception as e:
                self.logger.error(f"Service health error: {e}")

        if self._ollama_scan:
            try:
                ollama_report = self._ollama_scan()
                data["ollama"] = {
                    "process_count": ollama_report.process_count,
                    "total_vram_gb": ollama_report.total_vram_gb,
                    "duplicate_loaded": ollama_report.duplicate_loaded,
                }
                for alert in ollama_report.alerts:
                    data["alerts"].append(alert)
            except Exception as e:
                self.logger.error(f"Ollama monitor error: {e}")

        if self._docker_log_check:
            try:
                log_cap = self._docker_log_check(auto_fix_daemon=True)
                for alert in log_cap.alerts:
                    data["alerts"].append(alert)
            except Exception as e:
                self.logger.error(f"Docker log cap error: {e}")

        if self._log_summary:
            try:
                log_data = self._log_summary(hours=1)
                data["logs"] = log_data
                for evt in log_data.get("top_critical", []):
                    data["alerts"].append(
                        f"CRITICAL LOG [{evt['source']}]: {evt['message'][:120]}"
                    )
                if log_data.get("critical", 0) > 0:
                    data["issues"].append(
                        f"{log_data['critical']} critical log events in last hour"
                    )
            except Exception as e:
                self.logger.error(f"Log watcher error: {e}")

        return data

    def auto_heal(self, health_data: Dict) -> List[str]:
        """Execute auto-healing based on health data."""
        actions = []

        issues = health_data.get("issues", [])
        alerts = health_data.get("alerts", [])

        win_mem = health_data.get("windows", {}).get("memory_percent", 0)
        wsl_load = health_data.get("wsl", {}).get("load", {}).get("1m", 0)
        wsl_cores = health_data.get("wsl", {}).get("load", {}).get("cores", 1)
        wsl_zombies = health_data.get("wsl", {}).get("zombies", 0)
        disk = health_data.get("windows", {}).get("disk_percent", 0)
        temp = health_data.get("windows", {}).get("cpu_temp", {}).get("celsius", 0)
        docker_state = health_data.get("docker", {}) or {}

        if self.config.use_ai and self.ai_brain:
            try:
                decision = self.ai_brain.make_decision()
                if decision.decision.value != "monitor":
                    self.logger.info(
                        f"AI Decision: {decision.decision.value} - {decision.reasoning}"
                    )
                    actions.append(f"ai_decision:{decision.decision.value}")
            except Exception as e:
                self.logger.warning(f"AI decision failed: {e}")

        if disk >= 85.0:
            # Only alert if disk got worse by >2% since last alert
            if disk >= self._last_disk_alert_pct + 2.0 or disk >= 75.0:
                import psutil as _ps
                _du = _ps.disk_usage("C:")
                free_gb = _du.free / 1e9
                level = "CRITICAL" if disk >= 90.0 else "WARNING"
                self._notify_guardian(
                    level,
                    f"Disk {disk:.0f}% full — {free_gb:.1f}GB free",
                    f"C: drive is {disk:.1f}% used with only {free_gb:.1f}GB remaining. "
                    f"Run Guardian disk report to see top space hogs.",
                    {"disk_percent": disk, "free_gb": round(free_gb, 2)},
                    force=disk >= 95.0,
                )
                self._last_disk_alert_pct = disk

        if disk > self.config.disk_critical:
            self.logger.warning(f"Critical disk usage: {disk}%")
            self._attempt_safe_cleanup(disk, actions)
            self._attempt_wsl_disk_remediation(disk, actions)
            docker_vhd_bloat = float(docker_state.get("vhd_bloat_gb", 0) or 0.0)
            docker_bloat_threshold = getattr(self.config, "docker_vhd_bloat_alert_gb", 4.0)
            if docker_vhd_bloat >= docker_bloat_threshold or disk > 95.0:
                self._attempt_docker_vhd_compact(disk, actions)

        # Runaway process scan every 5 minutes
        if self.runaway_detector and (time.time() - self._last_runaway_scan > 300):
            self._last_runaway_scan = time.time()
            try:
                scan = self.runaway_detector.scan()
                if scan.runaway_processes:
                    actions.append(f"runaway_procs:{len(scan.runaway_processes)}")
            except Exception as e:
                self.logger.error(f"Runaway scan failed: {e}")

        if win_mem > self.config.windows_memory_critical or wsl_load > wsl_cores:
            self.logger.warning(f"Memory pressure: Win {win_mem}%, WSL load {wsl_load}")

            if self.wsl_balancer:
                try:
                    result = self.wsl_balancer.reclaim_memory()
                    if result.get("success"):
                        actions.append("wsl_memory_reclaim")
                except Exception as e:
                    self.logger.error(f"WSL memory reclaim failed: {e}")

            if self.zombie_killer and wsl_zombies > 0:
                try:
                    result = self.zombie_killer.kill_zombies()
                    if result.get("zombies_killed", 0) > 0:
                        actions.append(f"zombie_kill:{result['zombies_killed']}")
                except Exception as e:
                    self.logger.error(f"Zombie kill failed: {e}")

        if temp > self.config.temp_critical:
            self.logger.warning(f"Critical temperature: {temp}°C")
            if self.windows_sensors:
                try:
                    result = self.windows_sensors.apply_thermal_throttle()
                    actions.append("thermal_throttle")
                except Exception as e:
                    self.logger.error(f"Thermal throttle failed: {e}")

        if "OOM events detected" in issues:
            self.logger.critical("OOM event detected!")
            actions.append("oom_detected")

        if not health_data.get("network", {}).get("internet_reachable", True):
            self.logger.warning("Network unreachable")
            actions.append("network_down")

        return actions

    def run_cycle(self) -> Dict[str, Any]:
        """Run one monitoring cycle."""
        self.logger.info("Running monitoring cycle...")

        health_data = self.collect_health_data()
        self._record_memory_events(health_data)
        self._record_runtime_events(health_data)

        actions = []
        if self.config.auto_heal:
            actions = self.auto_heal(health_data)

        if self.config.log_heartbeats and self.heartbeat_logger:
            try:
                self.heartbeat_logger.heartbeat(
                    cpu=health_data.get("windows", {}).get("cpu_percent", 0),
                    ram=health_data.get("windows", {}).get("memory_percent", 0),
                    disk=health_data.get("windows", {}).get("disk_percent", 0),
                    wsl_running=bool(health_data.get("wsl", {}).get("hostname")),
                    wsl_memory=health_data.get("wsl", {})
                    .get("memory", {})
                    .get("used_mb"),
                    network_healthy=health_data.get("network", {}).get(
                        "internet_reachable", True
                    ),
                    active_distros=[self.config.wsl_distro]
                    if health_data.get("wsl", {}).get("hostname")
                    else [],
                    issues=health_data.get("issues", []),
                    actions=actions,
                )
            except Exception as e:
                self.logger.error(f"Heartbeat failed: {e}")

        report = self._build_operator_report(health_data, actions)
        self._persist_operator_report(report)
        self._maybe_send_periodic_report(report)

        return {"health": health_data, "actions": actions}

    def start(self, duration: Optional[int] = None):
        """Start the proactive guardian."""
        self._running = True
        start_time = time.time()

        print("=" * 50)
        print("  PROACTIVE GUARDIAN STARTED")
        print("=" * 50)
        print(f"Auto-heal: {self.config.auto_heal}")
        print(f"AI Brain: {self.config.use_ai}")
        print(f"Check interval: {self.config.check_interval}s")
        print(f"WSL Distro: {self.config.wsl_distro}")
        print("=" * 50)

        # Run startup scans (disk report + cache sweep) in background thread
        if not self._startup_complete:
            threading.Thread(target=self._run_startup_scans, daemon=True).start()

        while self._running:
            try:
                result = self.run_cycle()

                issues = result["health"].get("issues", [])
                actions = result["actions"]

                if issues:
                    print(f"\n[!] Issues: {', '.join(issues)}")

                if actions:
                    print(f"[+] Actions: {', '.join(actions)}")

                if duration and (time.time() - start_time) >= duration:
                    break

                time.sleep(self.config.check_interval)

            except KeyboardInterrupt:
                print("\nStopping Guardian...")
                break
            except Exception as e:
                self.logger.error(f"Monitoring cycle error: {e}")
                time.sleep(self.config.check_interval)

        self._running = False
        print("Guardian stopped.")

    def _run_startup_scans(self):
        """Run slow one-off scans at startup and log findings."""
        self.logger.info("Running startup scans (disk report + cache sweep)...")
        try:
            from Guardian.modules.disk.disk_report import scan as disk_scan, print_report
            report = disk_scan()
            print_report(report)
            if report.reclaimable_gb >= 2.0:
                self.logger.warning(
                    f"Startup disk scan: {report.reclaimable_gb:.1f}GB reclaimable. "
                    f"Top hog: {report.top_10[0].label if report.top_10 else 'n/a'}"
                )
        except Exception as e:
            self.logger.error(f"Startup disk scan error: {e}")

        try:
            from Guardian.modules.performance.stale_cache_cleaner import scan as cache_scan
            cache_report = cache_scan()
            if cache_report.total_gb >= 1.0:
                self.logger.warning(
                    f"Startup cache scan: {cache_report.total_gb:.1f}GB in stale caches. "
                    f"Top: {cache_report.entries[0].label if cache_report.entries else 'n/a'}"
                )
        except Exception as e:
            self.logger.error(f"Startup cache scan error: {e}")

        try:
            from Guardian.modules.docker.docker_log_cap import check as dlc_check
            dlc_check(auto_fix_daemon=True)
        except Exception as e:
            self.logger.error(f"Startup docker log cap error: {e}")

        self._startup_complete = True
        self.logger.info("Startup scans complete.")

    def stop(self):
        """Stop the guardian."""
        self._running = False

    def run_once(self) -> Dict[str, Any]:
        """Run a single monitoring cycle."""
        return self.run_cycle()


def create_guardian(**kwargs) -> ProactiveGuardian:
    """Create a proactive guardian with custom config."""
    config = GuardianConfig(**kwargs)
    return ProactiveGuardian(config)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Proactive Guardian")
    parser.add_argument("--once", action="store_true", help="Run once instead of loop")
    parser.add_argument("--no-ai", action="store_true", help="Disable AI brain")
    parser.add_argument(
        "--interval", type=int, default=60, help="Check interval (seconds)"
    )
    parser.add_argument("--duration", type=int, help="Run for N seconds")
    parser.add_argument("--distro", type=str, default="Ubuntu", help="WSL distro name")

    args = parser.parse_args()

    config = GuardianConfig(
        check_interval=args.interval, use_ai=not args.no_ai, wsl_distro=args.distro
    )

    guardian = ProactiveGuardian(config)

    if args.once:
        result = guardian.run_once()
        print(json.dumps(result, indent=2, default=str))
    else:
        guardian.start(duration=args.duration)
