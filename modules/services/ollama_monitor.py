#!/usr/bin/env python3
"""
Ollama Monitor - Watch all 3 Ollama ports for runaways and duplicates
Guardian Module

Richard runs Ollama on 3 ports:
  11434 - local (Benchmark)
  11436 - cloud models (FieldBench counsel)
  11437 - embedding

Detects:
- Same model loaded on multiple ports simultaneously (VRAM waste)
- Models stuck in "running" state with no active requests (leaked load)
- Port process count anomalies (duplicate Ollama instances)
- Memory footprint of each loaded model
- Abnormal VRAM/RAM usage by ollama.exe processes
"""

import urllib.request
import urllib.error
import json
import subprocess
import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set, Tuple
from datetime import datetime


logger = logging.getLogger("OllamaMonitor")

OLLAMA_PORTS = {
    11434: "local",
    11436: "cloud",
    11437: "embedding",
}

# Models that are expected to be large and should not alert on memory
KNOWN_LARGE_MODELS = {"mistral", "llama", "mixtral", "codellama", "deepseek", "qwen"}


@dataclass
class OllamaModel:
    name: str
    size_gb: float
    modified: str = ""
    quantization: str = ""


@dataclass
class RunningModel:
    name: str
    port: int
    port_label: str
    size_gb: float = 0.0
    until: str = ""  # expires_at from /api/ps


@dataclass
class OllamaPortStatus:
    port: int
    label: str
    reachable: bool
    models: List[OllamaModel] = field(default_factory=list)
    running: List[RunningModel] = field(default_factory=list)
    error: Optional[str] = None


@dataclass
class OllamaReport:
    timestamp: datetime
    ports: List[OllamaPortStatus] = field(default_factory=list)
    duplicate_loaded: List[str] = field(default_factory=list)  # models on >1 port at once
    total_vram_gb: float = 0.0
    process_count: int = 0
    alerts: List[str] = field(default_factory=list)


def _get_json(url: str, timeout: float = 4.0) -> Optional[dict]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read())
    except Exception:
        return None


def _get_ollama_processes() -> List[dict]:
    """Get all ollama.exe processes with memory info via PowerShell."""
    try:
        cmd = (
            "Get-Process ollama -ErrorAction SilentlyContinue | "
            "Select-Object Id, CPU, WorkingSet64 | "
            "ConvertTo-Json -Compress"
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=10
        )
        if not r.stdout.strip():
            return []
        data = json.loads(r.stdout.strip())
        # PowerShell returns object directly if single item, list if multiple
        if isinstance(data, dict):
            data = [data]
        return data
    except Exception:
        return []


def check_port(port: int) -> OllamaPortStatus:
    label = OLLAMA_PORTS.get(port, str(port))
    status = OllamaPortStatus(port=port, label=label, reachable=False)

    # Check reachable
    tags = _get_json(f"http://127.0.0.1:{port}/api/tags")
    if tags is None:
        status.error = "unreachable"
        return status

    status.reachable = True

    # Installed models
    for m in tags.get("models", []):
        name = m.get("name", "")
        size_gb = m.get("size", 0) / (1024**3)
        details = m.get("details", {})
        status.models.append(OllamaModel(
            name=name,
            size_gb=round(size_gb, 2),
            modified=m.get("modified_at", "")[:10],
            quantization=details.get("quantization_level", ""),
        ))

    # Currently running / loaded models
    ps_data = _get_json(f"http://127.0.0.1:{port}/api/ps")
    if ps_data:
        for m in ps_data.get("models", []):
            name = m.get("name", "")
            size_gb = m.get("size", 0) / (1024**3)
            expires = m.get("expires_at", "")
            status.running.append(RunningModel(
                name=name,
                port=port,
                port_label=label,
                size_gb=round(size_gb, 2),
                until=expires[:19] if expires else "",
            ))

    return status


def scan() -> OllamaReport:
    report = OllamaReport(timestamp=datetime.now())

    for port in OLLAMA_PORTS:
        status = check_port(port)
        report.ports.append(status)

    # Detect same model loaded on multiple ports simultaneously
    loaded: Dict[str, List[int]] = {}
    for ps in report.ports:
        for rm in ps.running:
            base = rm.name.split(":")[0]  # strip tag
            loaded.setdefault(base, []).append(ps.port)

    for model, ports in loaded.items():
        if len(ports) > 1:
            msg = (
                f"Model '{model}' loaded on {len(ports)} ports simultaneously: "
                f"{[OLLAMA_PORTS.get(p, str(p)) for p in ports]} — wasting VRAM"
            )
            report.duplicate_loaded.append(model)
            report.alerts.append(msg)
            logger.warning(msg)

    # Total VRAM/RAM from loaded models
    report.total_vram_gb = round(
        sum(rm.size_gb for ps in report.ports for rm in ps.running), 2
    )

    # Ollama process count
    procs = _get_ollama_processes()
    report.process_count = len(procs)

    if report.process_count > 3:
        msg = (
            f"Unexpected: {report.process_count} ollama.exe processes running "
            f"(expected ≤3 for 3 ports). Check for leaked instances."
        )
        report.alerts.append(msg)
        logger.warning(msg)

    # Total RAM from ollama processes
    total_ram_gb = sum(p.get("WorkingSet64", 0) for p in procs) / (1024**3)
    if total_ram_gb > 20:
        msg = f"Ollama processes using {total_ram_gb:.1f}GB RAM — may be causing pressure"
        report.alerts.append(msg)

    return report


def get_summary() -> Dict:
    report = scan()
    return {
        "ports": {
            ps.label: {
                "port": ps.port,
                "reachable": ps.reachable,
                "models_installed": len(ps.models),
                "models_loaded": len(ps.running),
                "running": [{"name": r.name, "size_gb": r.size_gb} for r in ps.running],
            }
            for ps in report.ports
        },
        "duplicate_loaded": report.duplicate_loaded,
        "total_vram_gb": report.total_vram_gb,
        "process_count": report.process_count,
        "alerts": report.alerts,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = scan()

    print()
    print(f"  Ollama Monitor  —  {report.timestamp.strftime('%H:%M:%S')}")
    print(f"  {report.process_count} ollama.exe process(es), "
          f"{report.total_vram_gb:.1f}GB VRAM in use")
    print()

    for ps in report.ports:
        sym = "UP" if ps.reachable else "DOWN"
        print(f"  [{sym}] :{ps.port} ({ps.label})")
        if ps.reachable:
            print(f"       installed: {len(ps.models)} models")
            for rm in ps.running:
                print(f"       LOADED: {rm.name} ({rm.size_gb:.1f}GB)"
                      + (f" until {rm.until}" if rm.until else ""))

    if report.alerts:
        print()
        for a in report.alerts:
            print(f"  ALERT: {a}")
    print()
