#!/usr/bin/env python3
"""
Memory pressure analysis for the Windows host.
"""

from __future__ import annotations

import json
import logging
import subprocess
from collections import defaultdict
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Dict, List

import psutil


logger = logging.getLogger("MemoryPressure")


COUNTER_ALIASES = {
    r"\Memory\% Committed Bytes In Use": "commit_percent",
    r"\Memory\Committed Bytes": "committed_bytes",
    r"\Memory\Commit Limit": "commit_limit_bytes",
    r"\Paging File(_Total)\% Usage": "pagefile_usage_percent",
    r"\Paging File(_Total)\% Usage Peak": "pagefile_peak_percent",
    r"\Memory\Pages/sec": "pages_per_sec",
    r"\Memory\Page Reads/sec": "page_reads_per_sec",
    r"\Memory\Page Writes/sec": "page_writes_per_sec",
}


def _bytes_to_gb(value: float) -> float:
    return round(float(value) / (1024**3), 2)


@dataclass
class ProcessMemoryEntry:
    name: str
    pid: int
    rss_gb: float
    vms_gb: float
    private_gb: float
    memory_percent: float
    threads: int


@dataclass
class ProcessGroupEntry:
    name: str
    processes: int
    rss_gb: float
    private_gb: float
    vms_gb: float


@dataclass
class MemoryPressureReport:
    timestamp: str
    ram_percent: float
    ram_used_gb: float
    ram_total_gb: float
    available_gb: float
    commit_used_gb: float
    commit_limit_gb: float
    commit_percent: float
    pagefile_usage_percent: float
    pagefile_peak_percent: float
    pages_per_sec: float
    page_reads_per_sec: float
    page_writes_per_sec: float
    top_processes: List[ProcessMemoryEntry] = field(default_factory=list)
    top_groups: List[ProcessGroupEntry] = field(default_factory=list)
    causes: List[str] = field(default_factory=list)
    recommendations: List[str] = field(default_factory=list)


def _sample_counters() -> Dict[str, float]:
    try:
        query = ", ".join([f"'{path}'" for path in COUNTER_ALIASES])
        command = (
            f"Get-Counter {query} | "
            "Select-Object -ExpandProperty CounterSamples | "
            "Select-Object Path,CookedValue | ConvertTo-Json -Compress"
        )
        result = subprocess.run(
            ["powershell", "-NoProfile", "-Command", command],
            capture_output=True,
            text=True,
            timeout=20,
        )
        if result.returncode != 0 or not result.stdout.strip():
            return {}

        rows = json.loads(result.stdout)
        if isinstance(rows, dict):
            rows = [rows]

        values: Dict[str, float] = {}
        for row in rows:
            path = str(row.get("Path", "")).lower()
            for counter_path, alias in COUNTER_ALIASES.items():
                if path.endswith(counter_path.lower()):
                    values[alias] = float(row.get("CookedValue", 0.0))
                    break
        return values
    except Exception as exc:
        logger.warning(f"Failed to sample memory counters: {exc}")
        return {}


def _collect_processes(limit: int = 12) -> List[ProcessMemoryEntry]:
    entries: List[ProcessMemoryEntry] = []
    for proc in psutil.process_iter(
        ["pid", "name", "memory_info", "memory_percent", "num_threads"]
    ):
        try:
            mem = proc.info["memory_info"]
            private_bytes = getattr(mem, "private", getattr(mem, "uss", mem.rss))
            entries.append(
                ProcessMemoryEntry(
                    name=proc.info["name"] or "unknown",
                    pid=proc.info["pid"],
                    rss_gb=_bytes_to_gb(mem.rss),
                    vms_gb=_bytes_to_gb(mem.vms),
                    private_gb=_bytes_to_gb(private_bytes),
                    memory_percent=round(proc.info["memory_percent"] or 0.0, 2),
                    threads=proc.info["num_threads"] or 0,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    return sorted(entries, key=lambda item: (item.private_gb, item.rss_gb), reverse=True)[
        :limit
    ]


def _group_processes(entries: List[ProcessMemoryEntry], limit: int = 10) -> List[ProcessGroupEntry]:
    grouped: Dict[str, Dict[str, float]] = defaultdict(
        lambda: {"processes": 0, "rss_gb": 0.0, "private_gb": 0.0, "vms_gb": 0.0}
    )
    for entry in entries:
        bucket = grouped[entry.name]
        bucket["processes"] += 1
        bucket["rss_gb"] += entry.rss_gb
        bucket["private_gb"] += entry.private_gb
        bucket["vms_gb"] += entry.vms_gb

    rows = [
        ProcessGroupEntry(
            name=name,
            processes=int(values["processes"]),
            rss_gb=round(values["rss_gb"], 2),
            private_gb=round(values["private_gb"], 2),
            vms_gb=round(values["vms_gb"], 2),
        )
        for name, values in grouped.items()
    ]
    return sorted(rows, key=lambda item: (item.private_gb, item.rss_gb), reverse=True)[
        :limit
    ]


def analyze_memory_pressure() -> MemoryPressureReport:
    vm = psutil.virtual_memory()
    counters = _sample_counters()
    processes = _collect_processes()
    groups = _group_processes(processes)

    report = MemoryPressureReport(
        timestamp=datetime.now().isoformat(),
        ram_percent=round(vm.percent, 2),
        ram_used_gb=_bytes_to_gb(vm.used),
        ram_total_gb=_bytes_to_gb(vm.total),
        available_gb=_bytes_to_gb(vm.available),
        commit_used_gb=_bytes_to_gb(counters.get("committed_bytes", 0.0)),
        commit_limit_gb=_bytes_to_gb(counters.get("commit_limit_bytes", 0.0)),
        commit_percent=round(counters.get("commit_percent", 0.0), 2),
        pagefile_usage_percent=round(counters.get("pagefile_usage_percent", 0.0), 2),
        pagefile_peak_percent=round(counters.get("pagefile_peak_percent", 0.0), 2),
        pages_per_sec=round(counters.get("pages_per_sec", 0.0), 2),
        page_reads_per_sec=round(counters.get("page_reads_per_sec", 0.0), 2),
        page_writes_per_sec=round(counters.get("page_writes_per_sec", 0.0), 2),
        top_processes=processes,
        top_groups=groups,
    )

    group_map = {group.name.lower(): group for group in groups}

    if report.commit_percent >= 85:
        report.causes.append(
            f"Commit pressure is high at {report.commit_percent:.1f}% of the system limit."
        )
    if report.pages_per_sec >= 100 or report.page_reads_per_sec >= 20:
        report.causes.append(
            f"Paging is active at about {report.pages_per_sec:.0f} pages/sec with {report.page_reads_per_sec:.0f} page reads/sec."
        )
    if "memory compression" in group_map:
        report.causes.append(
            f"Windows memory compression is holding about {group_map['memory compression'].rss_gb:.2f} GB."
        )

    for group_name in ["vmmem", "vmmemwsl", "claude", "codex", "ollama", "qdrant", "rclone", "opencode"]:
        group = group_map.get(group_name)
        if group and group.private_gb >= 0.25:
            report.causes.append(
                f"{group.name} is using about {group.private_gb:.2f} GB private memory across {group.processes} process(es)."
            )

    if report.available_gb < 2:
        report.recommendations.append(
            "Available RAM is under 2 GB. Close duplicate AI/editor sessions first."
        )
    if group_map.get("vmmemwsl"):
        report.recommendations.append(
            "WSL is a major memory tenant. Reclaim or restart idle distros before opening more local workloads."
        )
    if group_map.get("claude") or group_map.get("codex"):
        report.recommendations.append(
            "Multiple coding-assistant sessions are open. Consolidating those sessions will reduce RAM pressure."
        )
    if group_map.get("ollama"):
        report.recommendations.append(
            "Ollama is contributing to host pressure. Keep concurrent inference sessions low."
        )
    if report.commit_percent >= 90:
        report.recommendations.append(
            "The swap thrash is being driven by total memory demand near the commit ceiling, not just pagefile configuration."
        )

    return report


def print_report(report: MemoryPressureReport) -> None:
    print("=" * 60)
    print("MEMORY PRESSURE REPORT")
    print("=" * 60)
    print(
        f"RAM: {report.ram_used_gb:.2f}/{report.ram_total_gb:.2f} GB ({report.ram_percent:.1f}%)"
    )
    print(
        f"Commit: {report.commit_used_gb:.2f}/{report.commit_limit_gb:.2f} GB ({report.commit_percent:.1f}%)"
    )
    print(
        "Paging: usage "
        f"{report.pagefile_usage_percent:.1f}% | peak {report.pagefile_peak_percent:.1f}% | "
        f"pages/s {report.pages_per_sec:.0f} | reads/s {report.page_reads_per_sec:.0f}"
    )
    print(f"Available RAM: {report.available_gb:.2f} GB")
    print("")
    print("Top Groups:")
    for group in report.top_groups[:8]:
        print(
            f"  {group.name}: private {group.private_gb:.2f} GB, rss {group.rss_gb:.2f} GB, procs {group.processes}"
        )
    if report.causes:
        print("")
        print("Likely Causes:")
        for cause in report.causes:
            print(f"  - {cause}")
    if report.recommendations:
        print("")
        print("Recommendations:")
        for item in report.recommendations:
            print(f"  - {item}")


if __name__ == "__main__":
    report = analyze_memory_pressure()
    print_report(report)
    print("")
    print(json.dumps(asdict(report), indent=2))
