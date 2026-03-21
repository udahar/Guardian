#!/usr/bin/env python3
"""
Disk Audit Script - Find where disk space went
"""

import subprocess
import os
import sys


def run_cmd(cmd):
    result = subprocess.run(cmd, shell=True, capture_output=True, text=True, timeout=30)
    return result.stdout.strip(), result.returncode


def check_wsl():
    """Check WSL disk usage"""
    print("=== WSL Disk Usage ===")
    output, _ = run_cmd('wsl -e bash -c "du -sh /home 2>/dev/null"')
    print(f"  /home: {output}")

    # Check Alfred services
    output, _ = run_cmd('wsl -e bash -c "du -sh /home/udahar/alfred 2>/dev/null"')
    if output:
        print(f"  /alfred: {output}")

    # Qdrant
    output, _ = run_cmd(
        'wsl -e bash -c "du -sh /home/udahar/alfred/services/qdrant 2>/dev/null"'
    )
    if output:
        print(f"  /qdrant: {output}")


def check_windows_large_dirs():
    """Check large Windows directories"""
    print("\n=== Windows Large Directories ===")

    dirs_to_check = [
        "Users",
        "Program Files",
        "Program Files (x86)",
        "Windows",
    ]

    for d in dirs_to_check:
        path = f"C:\\{d}"
        if os.path.exists(path):
            # Quick estimate using dir
            output, code = run_cmd(f'dir /ad "{path}" 2>nul')
            # Just list it
            print(f"  {d}: (see detailed scan)")


def check_hiding_spaces():
    """Check common disk-hogging locations"""
    print("\n=== Common Disk Hogs ===")

    locations = [
        ("Downloads", os.path.expanduser("~\\Downloads")),
        ("OneDrive", os.path.expanduser("~\\OneDrive")),
        ("AppData Local", os.path.expandvars("%LOCALAPPDATA%")),
        ("Temp", os.path.expandvars("%TEMP%")),
    ]

    for name, path in locations:
        if os.path.exists(path):
            try:
                size = subprocess.run(
                    f'powershell -NoProfile -Command "(Get-ChildItem \\"{path}\\" -Recurse -ErrorAction SilentlyContinue | Measure-Object -Property Length -Sum).Sum / 1GB"',
                    shell=True,
                    capture_output=True,
                    text=True,
                    timeout=30,
                )
                gb = float(size.stdout.strip()) if size.stdout.strip() else 0
                if gb > 0.1:
                    print(f"  {name}: {gb:.1f} GB")
            except:
                pass


def check_system_files():
    """Check system files that might hide space"""
    print("\n=== System Files ===")

    # Pagefile
    output, _ = run_cmd("wmic pagefile list /format:list")
    print("Pagefile:")
    for line in output.split("\n")[:3]:
        if line.strip():
            print(f"  {line.strip()}")

    # Hibernate
    hiberfil = "C:\\hiberfil.sys"
    if os.path.exists(hiberfil):
        size = os.path.getsize(hiberfil) / (1024**3)
        print(f"  Hibernate: {size:.1f} GB")

    # System restore
    print("\nSystem Restore:")
    output, _ = run_cmd("vssadmin list shadowstorage /for=c: 2>nul")
    if output:
        for line in output.split("\n")[:2]:
            if "Maximum" in line:
                print(f"  {line.strip()}")


def check_recycle_bin():
    """Check recycle bin"""
    print("\n=== Recycle Bin ===")
    output, _ = run_cmd(
        'powershell -NoProfile -Command "Get-ItemProperty -Path HK:\\SOFTWARE\\Microsoft\\Windows\\CurrentVersion\\Explorer\\BitBucket2 -ErrorAction SilentlyContinue | Select-Object -ExpandProperty VolumeGuid"'
    )
    if output:
        print(f"  Recycle Bin configured: Yes")
    else:
        print(f"  Recycle Bin: Default")


def main():
    print("=" * 50)
    print("DISK AUDIT - Finding lost space")
    print("=" * 50)

    check_wsl()
    check_hiding_spaces()
    check_system_files()

    print("\n=== Summary ===")
    print("Run 'wmic logicaldisk get size,freespace' for totals")
    print("Check OneDrive sync status - might be caching locally")


if __name__ == "__main__":
    main()
