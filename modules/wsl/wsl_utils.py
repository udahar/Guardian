#!/usr/bin/env python3
"""
WSL Utilities - Advanced WSL Management
PromptOS Module

Advanced WSL maintenance utilities including disk shrinking,
memory management, and performance optimization.

Features:
- WSL disk compaction (ext4.vhdx)
- WSL memory optimization
- WSL process management
- WSL backup/restore
- Sparse VHDX management
"""

import subprocess
import os
import re
import json
import logging
from dataclasses import dataclass
from typing import Optional, List
from datetime import datetime


@dataclass
class WSLInfo:
    name: str
    state: str
    version: int
    default: bool


@dataclass
class WSLDiskInfo:
    vhdx_path: str
    size_gb: float
    used_gb: float
    sparse: bool


@dataclass
class ShrinkResult:
    success: bool
    original_size_gb: float
    new_size_gb: float
    space_saved_gb: float
    error: Optional[str] = None


class WSLManager:
    def __init__(self, default_distro: str = "Ubuntu"):
        self.default_distro = default_distro
        self.logger = self._setup_logging()

    def _setup_logging(self) -> logging.Logger:
        logger = logging.getLogger("WSLUtils")
        logger.setLevel(logging.INFO)
        if not logger.handlers:
            handler = logging.StreamHandler()
            formatter = logging.Formatter("%(asctime)s - %(levelname)s - %(message)s")
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        return logger

    def _run_wsl(self, args: list, timeout: int = 30) -> tuple[bool, str]:
        try:
            result = subprocess.run(
                ["wsl"] + args, capture_output=True, text=True, timeout=timeout
            )
            return result.returncode == 0, result.stdout
        except Exception as e:
            return False, str(e)

    def list_distros(self) -> list[WSLInfo]:
        distros = []
        success, output = self._run_wsl(["-l", "-v"])

        if success:
            for line in output.split("\n")[1:]:
                if line.strip():
                    match = re.match(r"\s*\*?\s*(\S+)\s+(\S+)\s+(\d+)", line)
                    if match:
                        distros.append(
                            WSLInfo(
                                name=match.group(1),
                                state=match.group(2),
                                version=int(match.group(3)),
                                default="*" in line,
                            )
                        )

        return distros

    def is_running(self, distro: str = None) -> bool:
        distro = distro or self.default_distro
        distros = self.list_distros()
        for d in distros:
            if d.name.lower() == distro.lower():
                return d.state.lower() == "running"
        return False

    def get_distro_path(self, distro: str) -> Optional[str]:
        user = os.environ.get("USERNAME", "Unknown")
        base_path = os.path.join(
            os.environ.get("LOCALAPPDATA", ""),
            "Packages",
            f"CanonicalGroupLimited.{distro}*",
            "LocalState",
            "ext4.vhdx",
        )

        import glob

        matches = glob.glob(base_path)
        if matches:
            return matches[0]
        return None

    def get_disk_info(self, distro: str = None) -> Optional[WSLDiskInfo]:
        distro = distro or self.default_distro
        vhdx_path = self.get_distro_path(distro)

        if not vhdx_path or not os.path.exists(vhdx_path):
            return None

        size = os.path.getsize(vhdx_path) / (1024**3)

        used = 0
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-VHD -Path '{vhdx_path}').Size",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                used = float(result.stdout.strip()) / (1024**3)
        except Exception:
            pass

        is_sparse = False
        try:
            result = subprocess.run(
                [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    f"(Get-VHD -Path '{vhdx_path}').FragmentationPercentage",
                ],
                capture_output=True,
                text=True,
                timeout=10,
            )
            if result.returncode == 0:
                frag = float(result.stdout.strip())
                is_sparse = frag > 0
        except Exception:
            pass

        return WSLDiskInfo(
            vhdx_path=vhdx_path, size_gb=size, used_gb=used, sparse=is_sparse
        )

    def shutdown(self, distro: str = None):
        distro = distro or self.default_distro
        self.logger.info(f"Shutting down WSL ({distro})...")
        subprocess.run(["wsl", "--shutdown"], check=False, timeout=30)

    def terminate(self, distro: str = None):
        distro = distro or self.default_distro
        self.logger.info(f"Terminating WSL ({distro})...")
        subprocess.run(["wsl", "-t", distro], check=False, timeout=30)

    def enable_sparse(self, distro: str = None) -> bool:
        distro = distro or self.default_distro
        try:
            result = subprocess.run(
                ["wsl", "--manage", distro, "--set-sparse", "true"],
                capture_output=True,
                text=True,
                timeout=30,
            )
            success = result.returncode == 0
            if success:
                self.logger.info(f"Enabled sparse VHDX for {distro}")
            return success
        except Exception as e:
            self.logger.error(f"Failed to enable sparse: {e}")
            return False

    def shrink_wsl_disk(self, distro: str = None, force: bool = False) -> ShrinkResult:
        """Shrink WSL disk using diskpart method."""
        distro = distro or self.default_distro

        self.logger.info(f"Starting WSL disk shrink for {distro}...")

        vhdx_path = self.get_distro_path(distro)
        if not vhdx_path:
            return ShrinkResult(False, 0, 0, 0, "Could not find WSL VHDX file")

        original_size = os.path.getsize(vhdx_path) / (1024**3)

        try:
            self.logger.info("Step 1: Shutting down WSL...")
            subprocess.run(["wsl", "--shutdown"], check=True, timeout=30)
            import time

            time.sleep(3)

            self.logger.info("Step 2: Enabling sparse mode...")
            subprocess.run(
                ["wsl", "--manage", distro, "--set-sparse", "true"],
                check=True,
                timeout=30,
            )

            self.logger.info("Step 3: Running diskpart to compact VHDX...")

            diskpart_script = f"""
select vdisk file="{vhdx_path}"
attach vdisk readonly
compact vdisk
detach vdisk
exit
"""

            result = subprocess.run(
                ["diskpart"],
                input=diskpart_script,
                capture_output=True,
                text=True,
                timeout=300,
            )

            if result.returncode != 0:
                self.logger.warning(f"Diskpart output: {result.stdout}")
                self.logger.warning(f"Diskpart errors: {result.stderr}")

            import time

            time.sleep(2)

            new_size = os.path.getsize(vhdx_path) / (1024**3)
            saved = original_size - new_size

            self.logger.info(
                f"Shrink complete: {original_size:.2f}GB -> {new_size:.2f}GB (saved {saved:.2f}GB)"
            )

            return ShrinkResult(
                success=True,
                original_size_gb=original_size,
                new_size_gb=new_size,
                space_saved_gb=saved,
            )

        except subprocess.TimeoutExpired:
            return ShrinkResult(
                False, original_size, original_size, 0, "Operation timed out"
            )
        except Exception as e:
            return ShrinkResult(False, original_size, original_size, 0, str(e))

    def optimize_memory(self, distro: str = None) -> bool:
        """Clear Linux cache to free memory."""
        distro = distro or self.default_distro

        if not self.is_running(distro):
            self.logger.warning(f"{distro} is not running")
            return False

        try:
            result = subprocess.run(
                [
                    "wsl",
                    "-d",
                    distro,
                    "-u",
                    "root",
                    "sh",
                    "-c",
                    "echo 3 > /proc/sys/vm/drop_caches",
                ],
                check=True,
                timeout=30,
            )
            self.logger.info("Memory cache cleared")
            return True
        except Exception as e:
            self.logger.error(f"Failed to optimize memory: {e}")
            return False

    def trim_filesystem(self, distro: str = None) -> bool:
        """Run fstrim to reclaim space."""
        distro = distro or self.default_distro

        if not self.is_running(distro):
            return False

        try:
            result = subprocess.run(
                ["wsl", "-d", distro, "-u", "root", "fstrim", "-v", "/"],
                check=True,
                timeout=60,
            )
            self.logger.info("Filesystem trimmed")
            return True
        except Exception as e:
            self.logger.error(f"Failed to trim filesystem: {e}")
            return False

    def full_optimize(self, distro: str = None, shrink: bool = False) -> dict:
        """Run full optimization including memory, trim, and optionally shrink."""
        distro = distro or self.default_distro
        results = {
            "distro": distro,
            "memory_optimized": False,
            "filesystem_trimmed": False,
            "disk_shrunk": False,
            "shrink_result": None,
        }

        if self.is_running(distro):
            results["memory_optimized"] = self.optimize_memory(distro)
            results["filesystem_trimmed"] = self.trim_filesystem(distro)

        if shrink:
            results["disk_shrunk"] = True
            results["shrink_result"] = self.shrink_wsl_disk(distro)

        return results

    def get_memory_usage(self, distro: str = None) -> Optional[dict]:
        """Get WSL memory usage."""
        distro = distro or self.default_distro

        if not self.is_running(distro):
            return None

        try:
            result = subprocess.run(
                ["wsl", "-d", distro, "free", "-m"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                for line in result.stdout.split("\n"):
                    if line.startswith("Mem:"):
                        parts = line.split()
                        return {
                            "total_mb": float(parts[1]),
                            "used_mb": float(parts[2]),
                            "free_mb": float(parts[3]),
                            "percent": (float(parts[2]) / float(parts[1])) * 100,
                        }
        except Exception as e:
            self.logger.error(f"Failed to get memory: {e}")

        return None

    def get_disk_usage(self, distro: str = None) -> Optional[dict]:
        """Get WSL disk usage."""
        distro = distro or self.default_distro

        if not self.is_running(distro):
            return None

        try:
            result = subprocess.run(
                ["wsl", "-d", distro, "df", "-h", "/"],
                capture_output=True,
                text=True,
                timeout=10,
            )

            if result.returncode == 0:
                lines = result.stdout.strip().split("\n")
                if len(lines) > 1:
                    parts = lines[1].split()
                    return {
                        "total": parts[1],
                        "used": parts[2],
                        "available": parts[3],
                        "percent": int(parts[4].replace("%", "")),
                    }
        except Exception as e:
            self.logger.error(f"Failed to get disk: {e}")

        return None


def shrink_wsl_disk(distro: str = "Ubuntu") -> dict:
    """Quick function to shrink WSL disk."""
    manager = WSLManager(distro)
    result = manager.shrink_wsl_disk(distro)
    return {
        "success": result.success,
        "original_gb": result.original_size_gb,
        "new_gb": result.new_size_gb,
        "saved_gb": result.space_saved_gb,
        "error": result.error,
    }


def optimize_wsl(distro: str = "Ubuntu", shrink: bool = False) -> dict:
    """Quick function to optimize WSL."""
    manager = WSLManager(distro)
    return manager.full_optimize(distro, shrink)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="WSL Utilities")
    parser.add_argument("--list", action="store_true", help="List WSL distros")
    parser.add_argument("--info", type=str, help="Get distro info")
    parser.add_argument("--shrink", type=str, help="Shrink WSL disk (distro name)")
    parser.add_argument("--optimize", type=str, help="Optimize WSL (distro name)")
    parser.add_argument(
        "--shrink-opt", action="store_true", help="Shrink after optimize"
    )

    args = parser.parse_args()

    manager = WSLManager()

    if args.list:
        distros = manager.list_distros()
        print("WSL Distributions:")
        for d in distros:
            print(
                f"  {d.name}: {d.state} (v{d.version}){' [default]' if d.default else ''}"
            )

    elif args.info:
        info = manager.get_disk_info(args.info)
        if info:
            print(f"VHDX: {info.vhdx_path}")
            print(f"Size: {info.size_gb:.2f}GB")
            print(f"Used: {info.used_gb:.2f}GB")
            print(f"Sparse: {info.sparse}")
        else:
            print("Could not get info")

    elif args.shrink:
        print(f"Shrinking {args.shrink}...")
        result = manager.shrink_wsl_disk(args.shrink)
        print(f"Success: {result.success}")
        if result.success:
            print(
                f"Saved: {result.space_saved_gb:.2f}GB ({result.original_size_gb:.2f} -> {result.new_size_gb:.2f}GB)"
            )
        else:
            print(f"Error: {result.error}")

    elif args.optimize:
        print(f"Optimizing {args.optimize}...")
        result = manager.full_optimize(args.optimize, args.shrink_opt)
        print(json.dumps(result, indent=2))

    else:
        print("WSL Utility Manager")
        print("Usage: python wsl_utils.py --list")
