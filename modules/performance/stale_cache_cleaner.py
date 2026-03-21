#!/usr/bin/env python3
"""
Stale Cache Cleaner - Find and optionally clean build/package caches
Guardian Module

Hunts down the silent GB eaters we've hit repeatedly:
- node_modules in dead/stale projects (last used > N days)
- pip, uv, npm, yarn, pnpm, cargo, go module caches
- Python __pycache__ and .pytest_cache accumulation
- .next, dist, build, target (Rust/Java) output dirs
- tsbuildinfo files

Safe mode: report only (default)
Clean mode: remove reclaimable items
"""

import os
import shutil
import subprocess
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Optional
from datetime import datetime, timedelta
from pathlib import Path


logger = logging.getLogger("StaleCacheCleaner")

USER_HOME     = Path(os.environ.get("USERPROFILE", r"C:\Users\Richard"))
LOCAL_APPDATA = Path(os.environ.get("LOCALAPPDATA", USER_HOME / "AppData" / "Local"))
CLAWD         = Path(r"C:\Users\Richard\clawd")

# Directories that are safe to scan for stale caches
SCAN_ROOTS = [CLAWD, USER_HOME / "projects", USER_HOME / "dev"]


@dataclass
class CacheEntry:
    label: str
    path: Path
    size_gb: float
    category: str           # node_modules, pycache, build_output, pkg_cache
    stale_days: int = 0     # days since last modification
    safe_to_delete: bool = True
    delete_cmd: str = ""    # human-readable command to clean


@dataclass
class CacheReport:
    timestamp: datetime
    entries: List[CacheEntry] = field(default_factory=list)
    total_gb: float = 0.0
    cleaned_gb: float = 0.0
    errors: List[str] = field(default_factory=list)


def _dir_size_gb(path: Path, timeout: int = 15) -> float:
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


def _days_since_modified(path: Path) -> int:
    try:
        mtime = max(
            (os.path.getmtime(f) for f in path.rglob("*") if os.path.isfile(f)),
            default=path.stat().st_mtime
        )
        return int((datetime.now().timestamp() - mtime) / 86400)
    except Exception:
        return 0


def _run_cmd(cmd: str, timeout: int = 60) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, r.stdout.strip()
    except Exception as e:
        return False, str(e)


# ── Package manager caches (always safe to clean) ────────────────────────────

def scan_pkg_caches() -> List[CacheEntry]:
    entries = []

    checks = [
        # (label, path, clean_cmd)
        ("pip cache",
         LOCAL_APPDATA / "pip" / "cache",
         "pip cache purge"),

        ("uv cache",
         LOCAL_APPDATA / "uv" / "cache",
         "uv cache clean"),

        ("npm cache",
         LOCAL_APPDATA / "npm-cache",
         "npm cache clean --force"),

        ("yarn v1 cache",
         LOCAL_APPDATA / "Yarn" / "Cache",
         "yarn cache clean"),

        ("pnpm store",
         LOCAL_APPDATA / "pnpm" / "store",
         "pnpm store prune"),

        ("cargo registry",
         USER_HOME / ".cargo" / "registry",
         "cargo clean  (or: rm -rf ~/.cargo/registry/cache)"),

        ("cargo git",
         USER_HOME / ".cargo" / "git",
         "rm -rf ~/.cargo/git"),

        ("go module cache",
         USER_HOME / "go" / "pkg" / "mod",
         "go clean -modcache"),

        ("NuGet http-cache",
         LOCAL_APPDATA / "NuGet" / "v3-cache",
         "dotnet nuget locals http-cache --clear"),

        ("Gradle caches",
         USER_HOME / ".gradle" / "caches",
         "gradle --stop && rm -rf ~/.gradle/caches"),

        ("Maven repository",
         USER_HOME / ".m2" / "repository",
         "rm -rf ~/.m2/repository"),

        ("Ruby gem cache",
         USER_HOME / ".gem",
         "gem cleanup"),

        ("Composer cache",
         LOCAL_APPDATA / "Composer" / "cache",
         "composer clear-cache"),
    ]

    for label, path, clean_cmd in checks:
        if path.exists():
            gb = _dir_size_gb(path)
            if gb >= 0.05:
                entries.append(CacheEntry(
                    label=label, path=path, size_gb=gb,
                    category="pkg_cache", safe_to_delete=True,
                    delete_cmd=clean_cmd
                ))

    return entries


# ── Project-level caches ──────────────────────────────────────────────────────

def scan_project_caches(roots: List[Path] = None,
                        stale_threshold_days: int = 30) -> List[CacheEntry]:
    entries = []
    scan_roots = [r for r in (roots or SCAN_ROOTS) if r.exists()]

    # node_modules
    for root in scan_roots:
        for nm in root.rglob("node_modules"):
            if not nm.is_dir():
                continue
            # Skip nested node_modules (e.g. node_modules/pkg/node_modules)
            if "node_modules" in nm.parent.parts[len(root.parts):]:
                continue
            gb = _dir_size_gb(nm, timeout=20)
            if gb < 0.05:
                continue
            stale = _days_since_modified(nm.parent)
            entries.append(CacheEntry(
                label=f"node_modules/{nm.parent.name}",
                path=nm, size_gb=gb, category="node_modules",
                stale_days=stale, safe_to_delete=(stale >= stale_threshold_days),
                delete_cmd=f"cd {nm.parent} && npm ci  (or just delete the folder)"
            ))

    # __pycache__
    pycache_map: Dict[Path, float] = {}
    for root in scan_roots:
        for pc in root.rglob("__pycache__"):
            if not pc.is_dir():
                continue
            # Roll up to project root (top-level src dir)
            project = pc.parents[max(0, len(pc.parts) - len(root.parts) - 2)]
            pycache_map[project] = pycache_map.get(project, 0.0) + _dir_size_gb(pc, timeout=5)

    for project, gb in pycache_map.items():
        if gb >= 0.05:
            entries.append(CacheEntry(
                label=f"__pycache__ in {project.name}",
                path=project, size_gb=round(gb, 3),
                category="pycache", safe_to_delete=True,
                delete_cmd=f"find {project} -type d -name __pycache__ -exec rm -rf {{}} +"
            ))

    # .pytest_cache
    for root in scan_roots:
        for pc in root.rglob(".pytest_cache"):
            if pc.is_dir():
                gb = _dir_size_gb(pc, timeout=5)
                if gb >= 0.01:
                    entries.append(CacheEntry(
                        label=f".pytest_cache/{pc.parent.name}",
                        path=pc, size_gb=gb, category="pycache", safe_to_delete=True,
                        delete_cmd="pytest --cache-clear  (or delete folder)"
                    ))

    # .next build output
    for root in scan_roots:
        for p in root.rglob(".next"):
            if p.is_dir():
                gb = _dir_size_gb(p, timeout=15)
                if gb >= 0.1:
                    stale = _days_since_modified(p)
                    entries.append(CacheEntry(
                        label=f".next/{p.parent.name}",
                        path=p, size_gb=gb, category="build_output",
                        stale_days=stale,
                        safe_to_delete=(stale >= stale_threshold_days),
                        delete_cmd=f"cd {p.parent} && npm run build"
                    ))

    # dist / build folders (JS/TS projects)
    for root in scan_roots:
        for dist in list(root.rglob("dist")) + list(root.rglob("build")):
            if not dist.is_dir():
                continue
            if "node_modules" in str(dist):
                continue
            pkg = dist.parent / "package.json"
            if not pkg.exists():
                continue
            gb = _dir_size_gb(dist, timeout=10)
            if gb >= 0.1:
                stale = _days_since_modified(dist)
                entries.append(CacheEntry(
                    label=f"{dist.name}/{dist.parent.name}",
                    path=dist, size_gb=gb, category="build_output",
                    stale_days=stale,
                    safe_to_delete=(stale >= stale_threshold_days),
                    delete_cmd=f"cd {dist.parent} && npm run build"
                ))

    # Rust target dir
    for root in scan_roots:
        for target in root.rglob("target"):
            if not target.is_dir():
                continue
            cargo_toml = target.parent / "Cargo.toml"
            if not cargo_toml.exists():
                continue
            gb = _dir_size_gb(target, timeout=20)
            if gb >= 0.1:
                stale = _days_since_modified(target)
                entries.append(CacheEntry(
                    label=f"rust target/{target.parent.name}",
                    path=target, size_gb=gb, category="build_output",
                    stale_days=stale,
                    safe_to_delete=(stale >= stale_threshold_days),
                    delete_cmd=f"cd {target.parent} && cargo clean"
                ))

    # tsbuildinfo files (accumulate in TS projects)
    ts_total = 0.0
    ts_count = 0
    for root in scan_roots:
        for tsb in root.rglob("*.tsbuildinfo"):
            try:
                ts_total += tsb.stat().st_size / (1024**3)
                ts_count += 1
            except Exception:
                pass
    if ts_total > 0.01:
        entries.append(CacheEntry(
            label=f"tsbuildinfo files ({ts_count} files)",
            path=CLAWD, size_gb=round(ts_total, 3),
            category="build_output", safe_to_delete=True,
            delete_cmd="find . -name '*.tsbuildinfo' -delete"
        ))

    return entries


def scan(stale_threshold_days: int = 30) -> CacheReport:
    report = CacheReport(timestamp=datetime.now())
    entries = scan_pkg_caches() + scan_project_caches(
        stale_threshold_days=stale_threshold_days
    )
    entries.sort(key=lambda e: e.size_gb, reverse=True)
    report.entries = entries
    report.total_gb = round(sum(e.size_gb for e in entries), 2)
    return report


def clean(report: CacheReport, dry_run: bool = True) -> CacheReport:
    """Delete safe_to_delete entries. dry_run=True just logs."""
    for entry in report.entries:
        if not entry.safe_to_delete:
            continue
        if dry_run:
            logger.info(f"DRY RUN: would delete {entry.path} ({entry.size_gb:.2f}GB)")
            continue
        try:
            if entry.path.is_dir():
                shutil.rmtree(entry.path, ignore_errors=True)
                report.cleaned_gb += entry.size_gb
                logger.info(f"Deleted {entry.path} ({entry.size_gb:.2f}GB)")
        except Exception as e:
            report.errors.append(f"Failed to delete {entry.path}: {e}")
    return report


def get_summary() -> Dict:
    report = scan()
    return {
        "total_gb": report.total_gb,
        "entry_count": len(report.entries),
        "top_5": [
            {
                "label": e.label,
                "size_gb": e.size_gb,
                "stale_days": e.stale_days,
                "safe_to_delete": e.safe_to_delete,
            }
            for e in report.entries[:5]
        ],
    }


if __name__ == "__main__":
    import sys
    logging.basicConfig(level=logging.INFO)
    do_clean = "--clean" in sys.argv

    report = scan()
    print(f"\nCache scan — {report.timestamp.strftime('%Y-%m-%d %H:%M')}")
    print(f"Total found: {report.total_gb:.2f} GB across {len(report.entries)} entries\n")

    for e in report.entries:
        stale = f"  [{e.stale_days}d stale]" if e.stale_days else ""
        safe  = "  SAFE" if e.safe_to_delete else "  keep"
        print(f"  {e.size_gb:>6.2f}GB  {e.label}{stale}{safe}")
        if e.delete_cmd:
            print(f"             clean: {e.delete_cmd}")

    if do_clean:
        print("\nCleaning safe entries...")
        report = clean(report, dry_run=False)
        print(f"Freed: {report.cleaned_gb:.2f} GB")
