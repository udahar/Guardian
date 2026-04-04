#!/usr/bin/env python3
"""
Disk Report - Comprehensive startup disk audit
Guardian Module

Runs at daemon startup and on demand. Finds exactly where disk space
is going across Windows + WSL. Surfaces hidden eaters we've hit before:
- Docker VHD, WSL VHDs
- node_modules, pip/cargo/go caches
- AppData bloat (npm, pip, nuget, gradle, ivy, maven)
- Windows shadow copies, hibernation, pagefile
- Temp dirs, crash dumps, WER reports
- Project artifacts (.next, dist, target, __pycache__)
"""

import os
import subprocess
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Tuple
from pathlib import Path
from datetime import datetime
import json


logger = logging.getLogger("DiskReport")

USER_HOME = Path(os.environ.get("USERPROFILE", r"C:\Users\Richard"))
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", USER_HOME / "AppData" / "Local"))
APPDATA = Path(os.environ.get("APPDATA", USER_HOME / "AppData" / "Roaming"))


@dataclass
class DiskEntry:
    label: str
    path: str
    size_gb: float
    category: str  # docker, wsl, cache, project, system, user
    reclaimable: bool = False
    note: str = ""


@dataclass
class DiskReport:
    timestamp: datetime
    c_total_gb: float = 0.0
    c_free_gb: float = 0.0
    c_used_gb: float = 0.0
    entries: List[DiskEntry] = field(default_factory=list)
    top_10: List[DiskEntry] = field(default_factory=list)
    reclaimable_gb: float = 0.0
    errors: List[str] = field(default_factory=list)


def _get_dir_size_gb(path: Path, timeout: int = 20) -> float:
    """Get directory size in GB using PowerShell (handles locked files gracefully)."""
    try:
        cmd = (
            f'(Get-ChildItem "{path}" -Recurse -ErrorAction SilentlyContinue '
            f'| Measure-Object -Property Length -Sum).Sum / 1GB'
        )
        r = subprocess.run(
            ["powershell", "-NoProfile", "-Command", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        val = r.stdout.strip()
        return round(float(val), 3) if val else 0.0
    except Exception:
        return 0.0


def _get_file_size_gb(path: Path) -> float:
    try:
        return path.stat().st_size / (1024 ** 3)
    except Exception:
        return 0.0


def _run_wsl(cmd: str, timeout: int = 15) -> str:
    try:
        r = subprocess.run(
            ["wsl", "-e", "bash", "-c", cmd],
            capture_output=True, text=True, timeout=timeout
        )
        return r.stdout.strip()
    except Exception:
        return ""


def _wsl_size_gb(path: str) -> float:
    """Get WSL directory size in GB."""
    out = _run_wsl(f'du -sb "{path}" 2>/dev/null | cut -f1')
    try:
        return int(out) / (1024 ** 3)
    except Exception:
        return 0.0


def scan(verbose: bool = False) -> DiskReport:
    report = DiskReport(timestamp=datetime.now())

    # ── C: drive totals ──────────────────────────────────────────────────────
    try:
        import psutil
        usage = psutil.disk_usage("C:")
        report.c_total_gb = round(usage.total / (1024**3), 1)
        report.c_free_gb  = round(usage.free  / (1024**3), 1)
        report.c_used_gb  = round(usage.used  / (1024**3), 1)
    except Exception as e:
        report.errors.append(f"disk_usage: {e}")

    entries: List[DiskEntry] = []

    def add(label: str, path, size_gb: float, category: str,
            reclaimable: bool = False, note: str = ""):
        if size_gb >= 0.05:  # skip anything < 50 MB
            entries.append(DiskEntry(
                label=label, path=str(path), size_gb=round(size_gb, 2),
                category=category, reclaimable=reclaimable, note=note
            ))

    # ── Docker & WSL VHDs ────────────────────────────────────────────────────
    # Docker data VHD (docker_data.vhdx or docker-desktop-data.vhdx)
    for vhd_candidate in [
        LOCAL_APPDATA / "Docker" / "wsl" / "disk" / "docker_data.vhdx",
        LOCAL_APPDATA / "Docker" / "wsl" / "disk" / "docker-desktop-data.vhdx",
    ]:
        if vhd_candidate.exists():
            gb = _get_file_size_gb(vhd_candidate)
            add(f"Docker VHD: {vhd_candidate.name}", vhd_candidate, gb, "docker",
                reclaimable=True,
                note="docker system prune -a, then compact: wsl --shutdown + diskpart")
    # Also scan any other VHDs in the Docker wsl disk folder
    vhd_root = LOCAL_APPDATA / "Docker" / "wsl" / "disk"
    if vhd_root.exists():
        for vhd in vhd_root.glob("*.vhdx"):
            if vhd.name not in ("docker_data.vhdx", "docker-desktop-data.vhdx"):
                gb = _get_file_size_gb(vhd)
                add(f"Docker VHD: {vhd.name}", vhd, gb, "docker",
                    reclaimable=True,
                    note="Run docker system prune then diskpart compact")

    # New WSL path (Windows 11 23H2+): %LOCALAPPDATA%\wsl\{guid}\ext4.vhdx
    new_wsl_root = LOCAL_APPDATA / "wsl"
    if new_wsl_root.exists():
        for vhd in new_wsl_root.rglob("ext4.vhdx"):
            gb = _get_file_size_gb(vhd)
            add(f"WSL VHD ({vhd.parent.name[:30]})", vhd, gb, "wsl", reclaimable=True,
                note="wsl --shutdown then diskpart compact vdisk")

    # Legacy WSL path: %LOCALAPPDATA%\Packages\CanonicalGroup*\LocalState\ext4.vhdx
    wsl_pkg_root = LOCAL_APPDATA / "Packages"
    for pkg in wsl_pkg_root.glob("*CanonicalGroup*"):
        vhd = pkg / "LocalState" / "ext4.vhdx"
        if vhd.exists():
            gb = _get_file_size_gb(vhd)
            add(f"WSL VHD ({pkg.name[:30]})", vhd, gb, "wsl", reclaimable=True,
                note="wsl --shutdown then Optimize-VHD or diskpart compact")

    # ── pip / uv cache ───────────────────────────────────────────────────────
    pip_cache = LOCAL_APPDATA / "pip" / "cache"
    if pip_cache.exists():
        add("pip cache", pip_cache, _get_dir_size_gb(pip_cache), "cache", reclaimable=True,
            note="pip cache purge")

    uv_cache = LOCAL_APPDATA / "uv" / "cache"
    if uv_cache.exists():
        add("uv cache", uv_cache, _get_dir_size_gb(uv_cache), "cache", reclaimable=True,
            note="uv cache clean")

    # ── npm / yarn / pnpm cache ──────────────────────────────────────────────
    npm_cache = LOCAL_APPDATA / "npm-cache"
    if npm_cache.exists():
        add("npm cache", npm_cache, _get_dir_size_gb(npm_cache), "cache", reclaimable=True,
            note="npm cache clean --force")

    yarn_cache = LOCAL_APPDATA / "Yarn" / "Cache"
    if yarn_cache.exists():
        add("yarn cache", yarn_cache, _get_dir_size_gb(yarn_cache), "cache", reclaimable=True,
            note="yarn cache clean")

    # ── Rust / Cargo ─────────────────────────────────────────────────────────
    cargo_registry = USER_HOME / ".cargo" / "registry"
    if cargo_registry.exists():
        add("cargo registry", cargo_registry, _get_dir_size_gb(cargo_registry), "cache",
            reclaimable=True, note="cargo clean && rm -rf ~/.cargo/registry")

    # ── Go module cache ───────────────────────────────────────────────────────
    go_cache = USER_HOME / "go" / "pkg" / "mod"
    if go_cache.exists():
        add("go module cache", go_cache, _get_dir_size_gb(go_cache), "cache",
            reclaimable=True, note="go clean -modcache")

    # ── NuGet / Java / Gradle ─────────────────────────────────────────────────
    nuget = LOCAL_APPDATA / "NuGet" / "Cache"
    if nuget.exists():
        add("NuGet cache", nuget, _get_dir_size_gb(nuget), "cache", reclaimable=True,
            note="dotnet nuget locals all --clear")

    gradle = USER_HOME / ".gradle" / "caches"
    if gradle.exists():
        add("Gradle caches", gradle, _get_dir_size_gb(gradle), "cache", reclaimable=True)

    # ── Windows Temp ──────────────────────────────────────────────────────────
    win_temp = Path(r"C:\Windows\Temp")
    if win_temp.exists():
        add("Windows\\Temp", win_temp, _get_dir_size_gb(win_temp, timeout=10), "system",
            reclaimable=True, note="Guardian auto-cleans on RAM pressure")

    user_temp = Path(os.environ.get("TEMP", USER_HOME / "AppData" / "Local" / "Temp"))
    if user_temp.exists():
        add("User Temp", user_temp, _get_dir_size_gb(user_temp, timeout=10), "system",
            reclaimable=True)

    # ── Windows Error Reporting / crash dumps ─────────────────────────────────
    wer = LOCAL_APPDATA / "Microsoft" / "Windows" / "WER"
    if wer.exists():
        add("WER crash reports", wer, _get_dir_size_gb(wer), "system", reclaimable=True,
            note="Safe to delete — old crash reports")

    dumps = Path(r"C:\Windows\Minidump")
    if dumps.exists():
        add("Minidumps", dumps, _get_dir_size_gb(dumps), "system", reclaimable=True)

    # ── Windows Update SoftwareDistribution ──────────────────────────────────
    sw_dist = Path(r"C:\Windows\SoftwareDistribution\Download")
    if sw_dist.exists():
        add("Windows Update cache", sw_dist, _get_dir_size_gb(sw_dist, timeout=15),
            "system", reclaimable=True, note="Safe after updates are applied")

    # ── hibernation / pagefile ────────────────────────────────────────────────
    hiberfil = Path(r"C:\hiberfil.sys")
    if hiberfil.exists():
        add("hiberfil.sys", hiberfil, _get_file_size_gb(hiberfil), "system",
            reclaimable=True, note="powercfg /h off to reclaim (disables hibernate)")

    pagefile = Path(r"C:\pagefile.sys")
    if pagefile.exists():
        add("pagefile.sys", pagefile, _get_file_size_gb(pagefile), "system",
            reclaimable=False, note="System managed — do not delete")

    # ── Downloads ─────────────────────────────────────────────────────────────
    downloads = USER_HOME / "Downloads"
    if downloads.exists():
        add("Downloads", downloads, _get_dir_size_gb(downloads, timeout=20), "user",
            reclaimable=True, note="Manual review recommended")

    # ── OneDrive ──────────────────────────────────────────────────────────────
    for od in [USER_HOME / "OneDrive", USER_HOME / "OneDrive - Personal"]:
        if od.exists():
            add("OneDrive", od, _get_dir_size_gb(od, timeout=30), "user",
                reclaimable=False, note="Cloud-synced — files may be local copies")

    # ── Claude vm_bundles (Claude Code preview VM) ───────────────────────────
    vm_bundles = APPDATA / "Claude" / "vm_bundles"
    if vm_bundles.exists():
        gb = _get_dir_size_gb(vm_bundles, timeout=15)
        add("Claude vm_bundles", vm_bundles, gb, "user", reclaimable=True,
            note="Close Claude desktop app, then delete this folder — re-downloads on demand")

    # ── Claude Code task/session logs ─────────────────────────────────────────
    claude_code_sessions = APPDATA / "Claude" / "claude-code-sessions"
    if claude_code_sessions.exists():
        gb = _get_dir_size_gb(claude_code_sessions, timeout=10)
        add("Claude code sessions", claude_code_sessions, gb, "user", reclaimable=True,
            note="Old session logs — safe to clear")

    # ── Ollama models ─────────────────────────────────────────────────────────
    ollama_models = USER_HOME / ".ollama" / "models"
    if ollama_models.exists():
        add("Ollama models", ollama_models, _get_dir_size_gb(ollama_models, timeout=30),
            "user", reclaimable=False, note="Only remove with: ollama rm <model>")

    # ── Project artifacts ─────────────────────────────────────────────────────
    clawd = Path(r"C:\Users\Richard\clawd")
    if clawd.exists():
        # .next build dirs
        for p in clawd.rglob(".next"):
            if p.is_dir():
                gb = _get_dir_size_gb(p, timeout=10)
                add(f".next: {p.parent.name}", p, gb, "project", reclaimable=True,
                    note="npm run build regenerates this")

        # node_modules — just the big ones
        for nm in clawd.rglob("node_modules"):
            if nm.is_dir() and nm.parent != clawd:
                gb = _get_dir_size_gb(nm, timeout=15)
                if gb >= 0.2:
                    add(f"node_modules: {nm.parent.name}", nm, gb, "project",
                        reclaimable=True, note="npm ci regenerates")

        # Python __pycache__ accumulation
        pycache_total = 0.0
        for pc in clawd.rglob("__pycache__"):
            if pc.is_dir():
                pycache_total += _get_dir_size_gb(pc, timeout=5)
        if pycache_total > 0.05:
            add("__pycache__ (all projects)", clawd, pycache_total, "project",
                reclaimable=True, note="find . -type d -name __pycache__ -exec rm -rf {} +")

    # ── WSL home ──────────────────────────────────────────────────────────────
    wsl_home = _wsl_size_gb("/home")
    if wsl_home > 0:
        add("WSL /home", "/home", wsl_home, "wsl")

    wsl_var_log = _wsl_size_gb("/var/log")
    if wsl_var_log > 0.05:
        add("WSL /var/log", "/var/log", wsl_var_log, "wsl", reclaimable=True,
            note="sudo journalctl --vacuum-size=100M")

    # ── Sort and finalize ────────────────────────────────────────────────────
    entries.sort(key=lambda e: e.size_gb, reverse=True)
    report.entries = entries
    report.top_10 = entries[:10]
    report.reclaimable_gb = round(
        sum(e.size_gb for e in entries if e.reclaimable), 2
    )

    return report


def print_report(report: DiskReport):
    print()
    print("=" * 65)
    print(f"  DISK REPORT  —  {report.timestamp.strftime('%Y-%m-%d %H:%M')}")
    print("=" * 65)
    print(f"  C:  {report.c_used_gb:.1f} GB used / {report.c_total_gb:.1f} GB total  "
          f"({report.c_free_gb:.1f} GB free)")
    print(f"  Potentially reclaimable: {report.reclaimable_gb:.1f} GB")
    print()
    print(f"  {'LOCATION':<40} {'SIZE':>7}  {'RECLAIM?'}")
    print("  " + "-" * 55)
    for e in report.top_10:
        flag = "  <-- reclaim" if e.reclaimable else ""
        print(f"  {e.label:<40} {e.size_gb:>6.1f}G{flag}")
        if e.note and e.size_gb > 1.0:
            print(f"    {'':40} hint: {e.note}")
    if len(report.entries) > 10:
        print(f"  ... and {len(report.entries) - 10} more entries")
    print("=" * 65)
    print()


def get_summary() -> Dict:
    report = scan()
    return {
        "c_free_gb": report.c_free_gb,
        "c_used_gb": report.c_used_gb,
        "reclaimable_gb": report.reclaimable_gb,
        "top_10": [
            {"label": e.label, "size_gb": e.size_gb, "reclaimable": e.reclaimable}
            for e in report.top_10
        ],
        "errors": report.errors,
    }


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    report = scan(verbose=True)
    print_report(report)
