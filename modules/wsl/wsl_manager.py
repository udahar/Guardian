#!/usr/bin/env python3
"""
WSL Manager - Multi-Distro WSL Management
PromptOS Module

Manages multiple WSL distributions (Ubuntu, Kali, etc.):
- Discovers all installed distros
- Monitors each distro separately
- Cross-distro resource tracking
- Kali Linux security tools integration
"""

import subprocess
import logging
from dataclasses import dataclass, field
from typing import Optional, List, Dict


@dataclass
class WSLDistro:
    name: str
    state: str
    version: int
    default: bool = False
    is_security_focused: bool = False


@dataclass
class WSLResourceSummary:
    total_memory_mb: float
    total_distros: int
    running_distros: int
    distros: List[Dict]
    security_distros: List[str]


class WSLManager:
    def __init__(self, default_distro: str = None):
        self.default_distro = default_distro
        self.logger = self._setup_logging()
        self._security_distros = ["kali", "parrot", "blackarch", "pentoo"]

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("WSLManager")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_wsl(
        self, distro: str, command: str, timeout: int = 10
    ) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["wsl", "-d", distro, "sh", "-c", command],
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def list_distros(self) -> List[WSLDistro]:
        distros = []
        try:
            result = subprocess.run(
                ["wsl", "-l", "-v"], capture_output=True, timeout=10
            )
            if result.returncode != 0:
                return distros

            raw = result.stdout.decode("utf-16", errors="ignore")
            cleaned = raw.replace("\n\n", "\n").strip()

            for line in cleaned.split("\n")[1:]:
                line = line.strip()
                if not line:
                    continue
                parts = line.split()
                if len(parts) >= 3:
                    name = parts[1] if parts[0] == "*" else parts[0]
                    state = parts[-2]
                    version = int(parts[-1])
                    name = name.replace("*", "")
                    is_security = any(s in name.lower() for s in self._security_distros)
                    distros.append(
                        WSLDistro(
                            name=name,
                            state=state,
                            version=version,
                            default=parts[0] == "*",
                            is_security_focused=is_security,
                        )
                    )
        except Exception as e:
            self.logger.error(f"Error listing distros: {e}")
        return distros

    def get_running_distros(self) -> List[str]:
        return [d.name for d in self.list_distros() if d.state.lower() == "running"]

    def get_distro_memory(self, distro: str) -> Optional[Dict]:
        success, output = self._run_wsl(distro, "free -m")
        if not success:
            return None
        try:
            for line in output.split("\n"):
                if line.startswith("Mem:"):
                    parts = line.split()
                    return {
                        "total_mb": float(parts[1]),
                        "used_mb": float(parts[2]),
                        "free_mb": float(parts[3]),
                    }
        except:
            pass
        return None

    def get_all_distro_memory(self) -> WSLResourceSummary:
        distros = self.list_distros()
        total_memory = 0
        running = 0
        distro_info = []
        security = []

        for d in distros:
            info = {"name": d.name, "state": d.state, "security": d.is_security_focused}
            if d.state.lower() == "running":
                running += 1
                mem = self.get_distro_memory(d.name)
                if mem:
                    info["memory"] = mem
                    total_memory += mem["used_mb"]
            distro_info.append(info)
            if d.is_security_focused:
                security.append(d.name)

        return WSLResourceSummary(
            total_memory_mb=total_memory,
            total_distros=len(distros),
            running_distros=running,
            distros=distro_info,
            security_distros=security,
        )

    def get_ollama_in_wsl(self, distro: str = None) -> List[Dict]:
        ollama_procs = []
        distros_to_check = [distro] if distro else self.get_running_distros()
        for d in distros_to_check:
            success, output = self._run_wsl(
                d, "ps aux | grep -i ollama | grep -v grep", timeout=15
            )
            if success and output.strip():
                for line in output.strip().split("\n"):
                    parts = line.split()
                    if len(parts) >= 2:
                        ollama_procs.append(
                            {
                                "distro": d,
                                "user": parts[0],
                                "pid": parts[1],
                                "command": parts[10:] if len(parts) > 10 else "",
                            }
                        )
        return ollama_procs

    def get_summary(self) -> dict:
        summary = self.get_all_distro_memory()
        return {
            "total_distros": summary.total_distros,
            "running_distros": summary.running_distros,
            "total_memory_mb": summary.total_memory_mb,
            "security_distros": summary.security_distros,
            "distros": summary.distros,
            "ollama_instances": self.get_ollama_in_wsl(),
        }


def get_wsl_summary() -> dict:
    return WSLManager().get_summary()


if __name__ == "__main__":
    import json

    print(json.dumps(get_wsl_summary(), indent=2, default=str))
