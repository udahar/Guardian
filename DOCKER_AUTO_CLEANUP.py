#!/usr/bin/env python3
"""
GUARDIAN DOCKER AUTO-CLEANUP FEATURES
Complete implementation of Docker monitoring and automatic cleanup

NEW MODULES & FEATURES:
======================

1. docker_daemon_config.py - Docker daemon.json management
   • Configure automatic log rotation (prevents runaway logs)
   • Set storage driver optimization
   • Validate and backup daemon.json
   • Cross-platform support (Windows/macOS/Linux)

2. Enhanced docker_guardian.py
   • Initialize Docker with daemon config
   • Monitor Docker disk usage continuously
   • Auto-prune build cache when thresholds exceeded
   • Track VHD bloat and alert
   • Prune containers & volumes separately

3. docker_scheduler.py - Scheduled cleanup tasks
   • Windows Scheduled Task (PowerShell)
   • macOS launchd (plist)
   • Linux cron jobs
   • Weekly cleanup: Sunday 2:00 AM

4. Enhanced continuous_monitor.py
   • Docker health check integrated
   • Periodic Docker prune (configurable interval)
   • Database logging of Docker metrics
   • Telegram alerts for Docker issues

5. Enhanced api_server.py
   • GET /docker/status - Current Docker disk usage
   • GET /docker/config - daemon.json config
   • GET /docker/config-summary - Quick config overview
   • POST /docker/prune - Manual prune (aggressive mode optional)
   • POST /docker/cleanup-containers - Prune stopped containers
   • POST /docker/cleanup-volumes - Prune dangling volumes
   • POST /docker/config/setup-cleanup - Configure daemon.json

6. setup_docker_autocleanup.py - Interactive setup wizard
   • Check Docker status
   • Configure daemon.json
   • Run initial prune
   • Set up scheduled cleanup
   • Displays summary with next steps


CONFIGURATION OPTIONS (config.py):
==================================
docker_cache_prune_threshold_gb: float = 3.0   # Prune when build cache exceeds
docker_vhd_bloat_alert_gb: float = 4.0        # Alert when VHD bloat exceeds
docker_images_warn_gb: float = 10.0           # Warn when image store exceeds
docker_auto_prune: bool = True                 # Enable auto-pruning


DAEMON.JSON AUTO-CONFIGURATION:
================================
When setup, adds these settings:
  "log-driver": "json-file"
  "log-opts": {
    "max-size": "10m",        # Rotate logs at 10MB
    "max-file": "3"           # Keep 3 rotated files
  }
  "storage-driver": "overlay2"  # Linux only, for performance


WHAT GETS CLEANED UP:
====================
docker system prune -f removes:
  • Build cache
  • Dangling images
  • Stopped containers
  • Unused networks
  • Anonymous volumes

docker image prune -a -f removes:
  • All unused images (not just dangling)

docker container prune -f removes:
  • All stopped containers

docker volume prune -f removes:
  • All dangling volumes


AUTOMATIC SCHEDULE:
===================
Default: Sunday 2:00 AM UTC
  • Windows: Scheduled Task in Task Scheduler
  • macOS: launchd plist in ~/Library/LaunchAgents
  • Linux: crontab entry

Runs non-aggressive prune (keeps named images, tagged builds)


USAGE EXAMPLES:
===============

1. Quick Setup:
   python setup_docker_autocleanup.py

2. Run API Server:
   python api_server.py
   
   Then:
   curl http://localhost:4001/docker/status
   curl -X POST http://localhost:4001/docker/prune -d '{"aggressive": false}'

3. Continuous Monitoring (includes Docker):
   python continuous_monitor.py

4. Manual Prune:
   python -c "from Guardian.modules.docker import DockerGuardian; \
              d = DockerGuardian(); \
              result = d.prune(aggressive=False); \
              print(f'Freed: {result.space_freed_gb:.2f}GB')"

5. Configure Daemon:
   python -c "from Guardian.modules.docker import DockerDaemonConfig; \
              cfg = DockerDaemonConfig(); \
              result = cfg.configure_auto_cleanup(restart_daemon=False); \
              print(result)"

6. Schedule Cleanup:
   python -c "from Guardian.modules.docker import DockerScheduledCleanup; \
              s = DockerScheduledCleanup(); \
              result = s.setup_weekly_cleanup(); \
              print(result)"


KEY FIXES FOR YOUR SSD BLOAT ISSUE:
===================================

✓ Log rotation (daemon.json max-size/max-file) - PREVENTS logs filling disk
✓ Auto-prune threshold - REMOVES build cache when it gets too large
✓ Weekly scheduled cleanup - MAINTAINS free space automatically
✓ Continuous monitoring - ALERTS before it's a crisis
✓ VHD bloat detection - IDENTIFIES when compaction is needed

The daemon.json setting is the BIGGEST win - container logs were probably your
main culprit. With max-size=10m and max-file=3, you'll never have one container
log consuming more than 30MB total.


WEEKLY MAINTENANCE YOU DON'T HAVE TO THINK ABOUT:
=================================================
1. Sunday 2:00 AM automatically runs docker system prune -f
2. Removes ~500MB-2GB of build cache, dangling images, stopped containers
3. Logs the results
4. Sends Telegram alert (optional)
5. Writes to database for audit trail

Combined with log rotation in daemon.json, your SSD bloat problem should
STOP happening week-to-week.


MONITORING INTEGRATION:
======================
Guardian continuous_monitor.py now checks Docker:
  • Every 5 minutes (configurable via DOCKER_CHECK_INTERVAL)
  • Tracks: build cache, images, containers, volumes, VHD bloat
  • Sends Telegram alerts if thresholds exceeded
  • Logs metrics to database
  • Auto-prunes if build cache > 3GB

This means you get real-time visibility + automatic fixes.


FILES MODIFIED/CREATED:
======================
NEW:
  modules/docker/docker_daemon_config.py (12.3 KB)
  modules/docker/docker_scheduler.py (8.5 KB)
  setup_docker_autocleanup.py (4 KB)

MODIFIED:
  modules/docker/__init__.py - Export new classes
  modules/docker/docker_guardian.py - Added init(), prune_containers(), prune_volumes()
  continuous_monitor.py - Added Docker checking
  api_server.py - Added Docker endpoints
  config.py - Already had Docker settings
"""

import json


def print_quick_start():
    """Print quick start instructions."""
    print("""
╔════════════════════════════════════════════════════════════════════╗
║         GUARDIAN DOCKER AUTO-CLEANUP - QUICK START                ║
╚════════════════════════════════════════════════════════════════════╝

STEP 1: Run Interactive Setup
$ python setup_docker_autocleanup.py

  This will:
  ✓ Check Docker is running
  ✓ Configure daemon.json for log rotation
  ✓ Run initial cleanup
  ✓ Set up weekly scheduled task

STEP 2: Start Continuous Monitor (optional)
$ python continuous_monitor.py

  Runs continuous monitoring with:
  ✓ Real-time Docker metrics
  ✓ Automatic threshold-based pruning
  ✓ Telegram alerts
  ✓ Database logging

STEP 3: Start API Server (optional)
$ python api_server.py

  Provides REST API for:
  ✓ GET  /docker/status - Check Docker health
  ✓ POST /docker/prune - Manual cleanup
  ✓ GET  /docker/config - View daemon.json

STEP 4: Verify Setup
$ curl http://localhost:4001/docker/config-summary
$ curl http://localhost:4001/docker/status


KEY CONFIGURATION:
  Docker check interval: 300 seconds (5 minutes)
  Auto-prune cache threshold: 3GB
  Auto-prune bloat alert: 4GB
  Log rotation: 10MB per file, 3 files max
  Weekly cleanup: Sunday 2:00 AM


THE MOST IMPORTANT FIX:
  The daemon.json log rotation setting prevents container logs from
  ever filling your disk again. This was likely your main problem.


TROUBLESHOOTING:

Q: Docker daemon doesn't respond after setup?
A: It may need to restart. The setup script will do this automatically
   if you enable restart_daemon=True.

Q: How do I know it's working?
A: Check logs:
   - Windows: Event Viewer > Task Scheduler > Logs > Guardian
   - Linux: journalctl -u docker
   - Check Guardian logs in ./logs/

Q: Manual prune when I want it?
A: curl -X POST http://localhost:4001/docker/prune

Q: Want aggressive cleanup (remove all unused images)?
A: curl -X POST http://localhost:4001/docker/prune -d '{"aggressive": true}'

Q: How much space will it free?
A: Typically 500MB-2GB weekly, depends on your build frequency


ESTIMATED SSD SAVINGS:
  Week 1-4: First full cleanup will free 2-5GB
  Week 5+: Minimal bloat (system reaches equilibrium)
  ROI: Stop worrying about SSD space, fix happens automatically

════════════════════════════════════════════════════════════════════════
    """)


if __name__ == "__main__":
    print_quick_start()

    # Show config summary
    print("\nDEFAULT DOCKER SETTINGS:")
    print("  Cache prune threshold: 3.0 GB")
    print("  VHD bloat alert: 4.0 GB")
    print("  Images warn: 10.0 GB")
    print("  Auto-prune: enabled")
    print()
    print("DAEMON.JSON LOG ROTATION:")
    print("  Driver: json-file")
    print("  Max size per log: 10m")
    print("  Max rotated files: 3")
    print("  Total max per container: 30MB")
    print()
    print("To begin: python setup_docker_autocleanup.py")
