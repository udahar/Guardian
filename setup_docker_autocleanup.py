#!/usr/bin/env python3
"""
Guardian Docker Setup and Configuration
Quick start guide for Docker auto-cleanup
"""

import sys
import os
import json
import logging

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from Guardian.modules.docker import (
    DockerGuardian,
    DockerDaemonConfig,
    DockerScheduledCleanup,
)


def main():
    logging.basicConfig(level=logging.INFO, format='%(message)s')
    logger = logging.getLogger(__name__)

    print("=" * 70)
    print("GUARDIAN DOCKER AUTO-CLEANUP SETUP")
    print("=" * 70)
    print()

    # Step 1: Check current Docker state
    print("[1/4] Checking Docker status...")
    print("-" * 70)

    docker = DockerGuardian()
    state = docker.get_disk_state()

    if not state.docker_running:
        print("❌ Docker is not running. Please start Docker Desktop first.")
        print()
        return

    print(f"✓ Docker is running")
    print(f"  Build cache:      {state.build_cache_gb:.2f}GB")
    print(f"  Images:           {state.images_size_gb:.2f}GB")
    print(f"  Containers:       {state.containers_size_gb:.2f}GB")
    print(f"  Volumes:          {state.volumes_size_gb:.2f}GB")
    print(f"  Reclaimable:      {state.total_reclaimable_gb:.2f}GB")
    print(f"  VHD file:         {state.vhd_file_gb:.2f}GB")
    print(f"  VHD bloat:        {state.vhd_bloat_gb:.2f}GB")
    print()

    # Step 2: Configure daemon.json
    print("[2/4] Configuring daemon.json for auto-cleanup...")
    print("-" * 70)

    config_mgr = DockerDaemonConfig()
    config_result = config_mgr.configure_auto_cleanup(restart_daemon=False)

    if config_result.get("success"):
        print("✓ daemon.json configured")
        for change in config_result.get("changes", []):
            print(f"  • {change}")
    else:
        print("❌ Failed to configure daemon.json")
        for error in config_result.get("errors", []):
            print(f"  ✗ {error}")
    print()

    # Step 3: Run prune
    print("[3/4] Performing initial Docker cleanup...")
    print("-" * 70)

    prune_result = docker.prune(aggressive=False)

    if prune_result.success:
        print("✓ Docker prune completed")
        for action in prune_result.actions:
            print(f"  • {action}")
        if prune_result.space_freed_gb > 0:
            print(f"  Freed: {prune_result.space_freed_gb:.2f}GB")
    else:
        print("❌ Docker prune failed")
        for error in prune_result.errors:
            print(f"  ✗ {error}")
    print()

    # Step 4: Setup scheduled cleanup
    print("[4/4] Setting up scheduled cleanup (weekly Sunday 2:00 AM)...")
    print("-" * 70)

    scheduler = DockerScheduledCleanup()
    schedule_result = scheduler.setup_weekly_cleanup()

    if schedule_result.get("success"):
        print("✓ Scheduled cleanup configured")
        for change in schedule_result.get("changes", []):
            print(f"  • {change}")
    else:
        print("⚠ Could not set up scheduled task (manual setup may be needed)")
        for change in schedule_result.get("changes", []):
            print(f"  • {change}")
        for error in schedule_result.get("errors", []):
            print(f"  ✗ {error}")
    print()

    # Summary
    print("=" * 70)
    print("SETUP COMPLETE")
    print("=" * 70)
    print()
    print("Docker Auto-Cleanup Configuration:")
    print("  • Log rotation: Enabled (10MB max per file, max 3 files)")
    print("  • Auto-prune: Build cache >3GB, dangling images")
    print("  • Weekly cleanup: Sunday 2:00 AM")
    print()
    print("Next steps:")
    print("  1. Monitor logs: 'docker logs' for container output")
    print("  2. Check status: python api_server.py then GET /docker/status")
    print("  3. Run cleanup manually: python -c 'from Guardian.modules.docker import "
    print("     DockerGuardian; d = DockerGuardian(); print(d.prune())'")
    print()
    print("For continuous monitoring, run:")
    print("  python continuous_monitor.py")
    print()


if __name__ == "__main__":
    main()
