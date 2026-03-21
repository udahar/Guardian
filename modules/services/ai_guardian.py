#!/usr/bin/env python3
"""
AI Guardian Brain - Ollama-Powered Decision Making
PromptOS Module

Uses local LLM to analyze system state and make intelligent
decisions about when and how to heal the system.

Features:
- Analyzes process list, resource usage, event logs
- Uses Ollama for local AI inference
- Pattern learning from past decisions
- Explains reasoning behind actions
"""

import json
import subprocess
import time
import logging
from dataclasses import dataclass, field
from typing import Optional, Callable
from datetime import datetime
from enum import Enum
import os


try:
    import psutil

    PSUTIL_AVAILABLE = True
except ImportError:
    PSUTIL_AVAILABLE = False


try:
    import requests

    REQUESTS_AVAILABLE = True
except ImportError:
    REQUESTS_AVAILABLE = False


class DecisionType(Enum):
    MONITOR = "monitor"
    HEAL_WINDOWS = "heal_windows"
    HEAL_WSL = "heal_wsl"
    SHRINK_WSL = "shrink_wsl"
    RECOMMEND_REBOOT = "recommend_reboot"
    ESCALATE = "escalate"
    NO_ACTION = "no_action"


class Confidence(Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class SystemSnapshot:
    timestamp: datetime
    cpu_percent: float
    ram_percent: float
    disk_percent: float
    processes: list
    wsl_running: bool
    wsl_memory_mb: Optional[float]
    recent_errors: list
    boot_time_days: float


@dataclass
class AIDecision:
    decision: DecisionType
    confidence: Confidence
    reasoning: str
    actions: list
    metrics_snapshot: SystemSnapshot


@dataclass
class DecisionRecord:
    timestamp: datetime
    snapshot: SystemSnapshot
    decision: AIDecision
    outcome: Optional[str] = None


class AIGuardianBrain:
    def __init__(self, ollama_url: str = "http://localhost:11434"):
        self.ollama_url = ollama_url
        self.logger = self._setup_logging()
        self.model = "llama3.2"  # Default model
        self._decision_history: list[DecisionRecord] = []

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("AIGuardian")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def set_model(self, model: str):
        self.model = model

    def is_ollama_available(self) -> bool:
        if not REQUESTS_AVAILABLE:
            return False
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            return response.status_code == 200
        except Exception:
            return False

    def get_available_models(self) -> list:
        if not REQUESTS_AVAILABLE:
            return []
        try:
            response = requests.get(f"{self.ollama_url}/api/tags", timeout=5)
            if response.status_code == 200:
                data = response.json()
                return [m["name"] for m in data.get("models", [])]
        except Exception:
            pass
        return []

    def collect_system_snapshot(self, error_lines: int = 10) -> SystemSnapshot:
        cpu = psutil.cpu_percent(interval=1)
        ram = psutil.virtual_memory().percent
        disk = psutil.disk_usage("C:").percent

        processes = []
        for proc in sorted(
            psutil.process_iter(["name", "cpu_percent", "memory_percent"]),
            key=lambda x: x.info.get("memory_percent", 0),
            reverse=True,
        )[:20]:
            try:
                processes.append(
                    {
                        "name": proc.info["name"],
                        "cpu": proc.info.get("cpu_percent", 0),
                        "mem": proc.info.get("memory_percent", 0),
                    }
                )
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                pass

        wsl_running = self._check_wsl_running()
        wsl_memory = self._get_wsl_memory() if wsl_running else None

        boot_time = psutil.boot_time()
        uptime_days = (datetime.now().timestamp() - boot_time) / 86400

        recent_errors = self._get_recent_errors(error_lines)

        return SystemSnapshot(
            timestamp=datetime.now(),
            cpu_percent=cpu,
            ram_percent=ram,
            disk_percent=disk,
            processes=processes,
            wsl_running=wsl_running,
            wsl_memory_mb=wsl_memory,
            recent_errors=recent_errors,
            boot_time_days=uptime_days,
        )

    def _check_wsl_running(self) -> bool:
        try:
            result = subprocess.run(
                ["wsl", "-l", "-v"], capture_output=True, text=True, timeout=10
            )
            return result.returncode == 0 and "Running" in result.stdout
        except Exception:
            return False

    def _get_wsl_memory(self) -> Optional[float]:
        try:
            result = subprocess.run(
                ["wsl", "-d", "Ubuntu", "-u", "root", "free", "-m"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.startswith("Mem:"):
                        parts = line.split()
                        return float(parts[2])
        except Exception:
            pass
        return None

    def _get_recent_errors(self, lines: int = 10) -> list:
        errors = []
        if not REQUESTS_AVAILABLE:
            return errors

        try:
            ps = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"Get-WinEvent -LogName System -MaxEvents {lines} -Level Error -ErrorAction SilentlyContinue | "
                    f"Select-Object TimeCreated,Message | ConvertTo-Json",
                ],
                capture_output=True,
                text=True,
                timeout=30,
            )

            if ps.returncode == 0 and ps.stdout.strip():
                try:
                    data = json.loads(ps.stdout)
                    if isinstance(data, dict):
                        data = [data]
                    for item in data:
                        msg = item.get("Message", "")[:150]
                        if msg:
                            errors.append(msg)
                except json.JSONDecodeError:
                    pass
        except Exception:
            pass

        return errors

    def _build_prompt(self, snapshot: SystemSnapshot) -> str:
        top_procs = "\n".join(
            [
                f"  - {p['name']}: CPU {p['cpu']:.1f}%, MEM {p['mem']:.1f}%"
                for p in snapshot.processes[:10]
            ]
        )

        errors = (
            "\n".join([f"  - {e}" for e in snapshot.recent_errors[:5]]) or "  (none)"
        )

        prompt = f"""You are an expert system administrator AI. Analyze this system state and decide what action to take.

System State:
- CPU: {snapshot.cpu_percent:.1f}%
- RAM: {snapshot.ram_percent:.1f}%
- Disk: {snapshot.disk_percent:.1f}%
- Uptime: {snapshot.boot_time_days:.1f} days
- WSL Running: {snapshot.wsl_running}
- WSL Memory: {snapshot.wsl_memory_mb}MB (if running)

Top Processes:
{top_procs}

Recent System Errors:
{errors}

Available Actions:
1. monitor - Continue monitoring (everything is fine)
2. heal_windows - Clean temp files, flush DNS, empty recycle bin
3. heal_wsl - Clear Linux cache, trim filesystem in WSL
4. shrink_wsl - Compact WSL virtual disk (use sparingly)
5. recommend_reboot - System needs restart for recovery
6. escalate - Critical issue requiring immediate attention

Decision Rules:
- RAM > 90%: Consider heal_windows or heal_wsl
- Disk > 90%: Consider heal_windows or shrink_wsl
- High CPU + high memory: May indicate runaway process
- WSL memory > 80%: heal_wsl
- Many errors: Consider escalate
- Old uptime (>30 days): Consider recommend_reboot
- Disk > 95%: shrink_wsl might help

Respond in JSON format:
{{
  "decision": "action_name",
  "confidence": "high|medium|low",
  "reasoning": "2-3 sentence explanation",
  "actions": ["specific action 1", "specific action 2"]
}}

Respond ONLY with valid JSON, no other text:"""

        return prompt

    def make_decision(self, snapshot: Optional[SystemSnapshot] = None) -> AIDecision:
        if snapshot is None:
            snapshot = self.collect_system_snapshot()

        if not self.is_ollama_available():
            return self._fallback_decision(snapshot)

        prompt = self._build_prompt(snapshot)

        try:
            response = requests.post(
                f"{self.ollama_url}/api/generate",
                json={
                    "model": self.model,
                    "prompt": prompt,
                    "stream": False,
                    "format": "json",
                },
                timeout=60,
            )

            if response.status_code == 200:
                result = response.json()
                content = result.get("response", "{}")

                try:
                    decision_data = json.loads(content)
                    decision = DecisionType(decision_data.get("decision", "monitor"))
                    confidence = Confidence(decision_data.get("confidence", "medium"))

                    self.logger.info(
                        f"AI Decision: {decision.value} ({confidence.value})"
                    )
                    self.logger.info(f"Reasoning: {decision_data.get('reasoning', '')}")

                    return AIDecision(
                        decision=decision,
                        confidence=confidence,
                        reasoning=decision_data.get("reasoning", ""),
                        actions=decision_data.get("actions", []),
                        metrics_snapshot=snapshot,
                    )
                except (json.JSONDecodeError, ValueError) as e:
                    self.logger.warning(f"Failed to parse AI response: {e}")

        except Exception as e:
            self.logger.warning(f"Ollama request failed: {e}")

        return self._fallback_decision(snapshot)

    def _fallback_decision(self, snapshot: SystemSnapshot) -> AIDecision:
        decision = DecisionType.MONITOR
        reasoning = "Using rule-based fallback due to Ollama unavailable"

        if snapshot.disk_percent > 95:
            decision = DecisionType.SHRINK_WSL
            reasoning = f"Disk at {snapshot.disk_percent}% - shrinking WSL"
        elif snapshot.ram_percent > 90:
            decision = DecisionType.HEAL_WINDOWS
            reasoning = f"RAM at {snapshot.ram_percent}% - healing Windows"
        elif snapshot.wsl_memory_mb and snapshot.wsl_memory_mb > 4000:
            decision = DecisionType.HEAL_WSL
            reasoning = f"WSL using {snapshot.wsl_memory_mb}MB - healing WSL"

        return AIDecision(
            decision=decision,
            confidence=Confidence.LOW,
            reasoning=reasoning,
            actions=[],
            metrics_snapshot=snapshot,
        )

    def record_decision(self, decision: AIDecision, outcome: Optional[str] = None):
        record = DecisionRecord(
            timestamp=datetime.now(),
            snapshot=decision.metrics_snapshot,
            decision=decision,
            outcome=outcome,
        )
        self._decision_history.append(record)

    def get_decision_history(self, limit: int = 50) -> list:
        return self._decision_history[-limit:]

    def explain_recent_decisions(self, count: int = 5) -> str:
        if not self._decision_history:
            return "No decision history available."

        lines = ["Recent AI Decisions:\n"]
        for record in self._decision_history[-count:]:
            lines.append(
                f"- {record.timestamp.strftime('%H:%M:%S')}: {record.decision.decision.value}"
            )
            lines.append(f"  Reasoning: {record.decision.reasoning}")
            lines.append(f"  Confidence: {record.decision.confidence.value}")
            if record.outcome:
                lines.append(f"  Outcome: {record.outcome}")
            lines.append("")

        return "\n".join(lines)


class GuardianAI:
    """High-level AI-powered guardian that combines all features."""

    def __init__(self, db_manager=None):
        self.brain = AIGuardianBrain()
        self.db_manager = db_manager

    def analyze_and_act(self, windows_guardian=None, wsl_guardian=None) -> dict:
        snapshot = self.brain.collect_system_snapshot()

        decision = self.brain.make_decision(snapshot)

        results = {
            "timestamp": snapshot.timestamp.isoformat(),
            "decision": decision.decision.value,
            "confidence": decision.confidence.value,
            "reasoning": decision.reasoning,
            "actions_taken": [],
            "metrics": {
                "cpu": snapshot.cpu_percent,
                "ram": snapshot.ram_percent,
                "disk": snapshot.disk_percent,
            },
        }

        if decision.decision == DecisionType.HEAL_WINDOWS and windows_guardian:
            cleanup_result = windows_guardian.cleanup()
            results["actions_taken"].extend(cleanup_result.actions_performed)
            results["space_freed_mb"] = cleanup_result.space_freed_mb
            self.brain.record_decision(decision, "windows_cleanup_done")

        elif decision.decision == DecisionType.HEAL_WSL and wsl_guardian:
            heal_result = wsl_guardian.heal_wsl()
            results["actions_taken"].extend(heal_result.actions_performed)
            self.brain.record_decision(decision, "wsl_healed")

        elif decision.decision == DecisionType.SHRINK_WSL:
            from Guardian.wsl_utils import shrink_wsl_disk

            shrink_result = shrink_wsl_disk()
            results["actions_taken"].append(f"WSL disk shrunk: {shrink_result}")
            self.brain.record_decision(decision, "wsl_shrunk")

        elif decision.decision == DecisionType.RECOMMEND_REBOOT:
            results["actions_taken"].append("REBOOT_RECOMMENDED")
            self.brain.record_decision(decision, "reboot_recommended")

        else:
            self.brain.record_decision(decision, "no_action")

        if self.db_manager:
            self.db_manager.save_decision(results)

        return results


def quick_ai_decision() -> dict:
    """Quick AI decision without full guardian setup."""
    ai = AIGuardianBrain()
    snapshot = ai.collect_system_snapshot()
    decision = ai.make_decision(snapshot)

    return {
        "decision": decision.decision.value,
        "confidence": decision.confidence.value,
        "reasoning": decision.reasoning,
        "metrics": {
            "cpu": snapshot.cpu_percent,
            "ram": snapshot.ram_percent,
            "disk": snapshot.disk_percent,
        },
    }


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="AI Guardian Brain")
    parser.add_argument("--decision", action="store_true", help="Make AI decision")
    parser.add_argument("--history", action="store_true", help="Show decision history")
    parser.add_argument(
        "--models", action="store_true", help="List available Ollama models"
    )
    parser.add_argument(
        "--model", type=str, default="llama3.2", help="Ollama model to use"
    )

    args = parser.parse_args()

    ai = AIGuardianBrain()

    if args.models:
        models = ai.get_available_models()
        print("Available Ollama models:")
        for m in models:
            print(f"  - {m}")

    elif args.decision:
        result = quick_ai_decision()
        print(json.dumps(result, indent=2))

    elif args.history:
        print(ai.explain_recent_decisions())

    else:
        snapshot = ai.collect_system_snapshot()
        print(f"System Snapshot:")
        print(f"  CPU: {snapshot.cpu_percent}%")
        print(f"  RAM: {snapshot.ram_percent}%")
        print(f"  Disk: {snapshot.disk_percent}%")
        print(f"  WSL: {'Running' if snapshot.wsl_running else 'Not running'}")
        print(f"  Uptime: {snapshot.boot_time_days:.1f} days")
