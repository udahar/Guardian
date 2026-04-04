#!/usr/bin/env python3
"""
ACTION PLAN: Get Guardian Docker Auto-Cleanup Running

This is your step-by-step guide to solve your SSD bloat problem once and for all.
"""

def print_action_plan():
    plan = """
╔════════════════════════════════════════════════════════════════════════════╗
║                 GUARDIAN DOCKER AUTO-CLEANUP ACTION PLAN                   ║
║               Stop Your Weekly SSD Bloat Problem Forever                   ║
╚════════════════════════════════════════════════════════════════════════════╝

YOUR SITUATION:
  • Week-to-week SSD bloat (down to 2GB free before crisis)
  • Manual cleanup cycle (annoying and time-consuming)
  • No visibility into what's using the space
  • Docker keeps using more space until you stop everything

THE SOLUTION:
  • Automatic log rotation (prevents runaway logs)
  • Weekly scheduled cleanup (no manual work)
  • Real-time monitoring (know what's happening)
  • REST API control (cleanup anytime you want)

═════════════════════════════════════════════════════════════════════════════

STEP 1: THE SETUP (5 MINUTES)
────────────────────────────────

Open PowerShell and run:

  cd C:\\Users\\Richard\\clawd\\Guardian
  python setup_docker_autocleanup.py

This single command will:
  ✓ Check Docker is running
  ✓ Show your current Docker disk usage
  ✓ Configure daemon.json for log rotation
  ✓ Run initial cleanup (frees space immediately)
  ✓ Set up weekly scheduled cleanup (Sunday 2:00 AM)
  ✓ Show completion summary

EXPECTED OUTPUT:
  [1/4] Checking Docker status...
  ✓ Docker is running
    Build cache: 2.34GB
    Images: 5.67GB
    ...
  
  [2/4] Configuring daemon.json for auto-cleanup...
  ✓ daemon.json configured
    • Set log-driver to json-file
    • Set max-size to 10m
    • Set max-file to 3
  
  [3/4] Performing initial Docker cleanup...
  ✓ Docker prune completed
    • pruned build cache + dangling images + stopped containers
    Freed: 1.23GB
  
  [4/4] Setting up scheduled cleanup (weekly Sunday 2:00 AM)...
  ✓ Scheduled cleanup configured
    • Created Windows Scheduled Task: GuardianDockerCleanup

═════════════════════════════════════════════════════════════════════════════

STEP 2: VERIFY IT WORKED (2 MINUTES)
─────────────────────────────────────

Open PowerShell and run:

  python api_server.py

  This starts the Guardian API server. You should see:
  Starting Guardian API on port 4001...
  Guardian API: http://localhost:4001
  Endpoints: /health, /status, /metrics, /ollama, /disk, /docker/status...

In another PowerShell window, test it:

  curl http://localhost:4001/docker/config-summary

  You should see:
  {
    "log_rotation_enabled": true,
    "max_log_size": "10m",
    "max_log_files": 3,
    "storage_driver": "overlay2",
    "cleanup_policy": "auto"
  }

  ✓ If you see this, setup worked perfectly!

═════════════════════════════════════════════════════════════════════════════

STEP 3: ONGOING MONITORING (OPTIONAL)
──────────────────────────────────────

You have three options:

OPTION A: Let it run automatically (recommended)
  • Scheduled task runs Sunday 2:00 AM
  • No manual work
  • Cleanup happens while you sleep
  • You're done! Skip to Step 4.

OPTION B: Start continuous monitoring
  cd C:\\Users\\Richard\\clawd\\Guardian
  python continuous_monitor.py

  This runs continuous monitoring that:
  • Checks Docker every 5 minutes
  • Auto-prunes if build cache > 3GB
  • Sends Telegram alerts if issues occur
  • Logs everything to database
  • Runs forever (or until you stop it)

OPTION C: Manual cleanup on-demand
  curl http://localhost:4001/docker/status
  curl -X POST http://localhost:4001/docker/prune -d '{"aggressive": false}'

  Use this anytime you want to trigger cleanup manually

═════════════════════════════════════════════════════════════════════════════

STEP 4: VERIFY IT'S WORKING (NEXT SUNDAY 2:00 AM)
──────────────────────────────────────────────────

The scheduled cleanup will run automatically. To verify:

WINDOWS:
  1. Open Task Scheduler
  2. Navigate to: Task Scheduler Library > Guardian
  3. Find: GuardianDockerCleanup
  4. Check: Last Run Time (should be Sunday ~2:00 AM)
  5. Check: Last Run Result (should be 0 = success)

VERIFY RESULTS:
  curl http://localhost:4001/docker/status

  Watch for:
  • build_cache_gb decreasing
  • total_reclaimable_gb staying low
  • No error messages

═════════════════════════════════════════════════════════════════════════════

THE NUMBERS: WHAT TO EXPECT
────────────────────────────

BEFORE SETUP:
  Week 1: 30GB free
  Week 2: 20GB free (Docker uses 10GB)
  Week 3: 10GB free (Docker uses another 10GB)
  Week 4: 2GB free (CRISIS! Must stop containers and cleanup)
  Then: Restart Docker, rebuild images, get back to 30GB

AFTER SETUP:
  Week 1: 30GB free → Setup runs, cleanup frees 2-3GB, now ~32GB free
  Week 2: 31GB free (normal Docker usage)
  Week 3: 30GB free (normal Docker usage)
  Week 4: 30GB free (Sunday 2AM cleanup runs, stays stable)
  Forever: ~30GB free (automatic maintenance)

RESULT: Stable free space, zero manual intervention

═════════════════════════════════════════════════════════════════════════════

WHAT'S BEING CLEANED UP
────────────────────────

Docker build cache:
  • Iterative builds (Crucible, Benchmark rebuilds)
  • Dangling layers from failed builds
  • Typical space: 500MB-2GB per week

Docker images:
  • Old image versions you don't use
  • Dangling images (broken builds)
  • Typical space: 100-500MB per week

Stopped containers:
  • Containers you stopped but didn't remove
  • Typical space: 50-200MB

Container logs (via daemon.json):
  • Automatic rotation at 10MB per file
  • Keeps max 3 files per container (30MB total)
  • This was probably your BIGGEST culprit
  • Typical savings: 200MB-1GB per week

═════════════════════════════════════════════════════════════════════════════

THE MOST IMPORTANT SETTING (Log Rotation)
──────────────────────────────────────────

The daemon.json log rotation is THE KEY fix. Here's why:

WITHOUT LOG ROTATION:
  Container runs for 52 weeks
  Generates 100MB logs per week
  Total logs after 1 year: 5.2GB
  These logs NEVER delete, they keep growing

WITH LOG ROTATION (what we configured):
  Container runs for 52 weeks
  Generates 100MB logs per week
  But: Logs rotate at 10MB, max 3 files
  Total logs: 30MB (forever)
  Old logs automatically deleted

SAVINGS: 5.2GB → 30MB (173x smaller!)

This single setting probably solves 80% of your SSD bloat problem.

═════════════════════════════════════════════════════════════════════════════

FAQ: ANSWERS TO COMMON QUESTIONS
─────────────────────────────────

Q: Will this break my Docker setup?
A: No. We only add safety measures. Your containers keep running.
   Log rotation just prevents logs from growing infinitely.

Q: What if I want to disable it?
A: Edit daemon.json and remove the log-opts section.
   Or just run setup_docker_autocleanup.py again.

Q: What if I forget to configure it?
A: The scheduled task can do it for you. Just run setup script.

Q: Can I customize the cleanup times?
A: Yes! See DOCKER_SETUP.md for how to change the schedule.

Q: What if cleanup removes an image I need?
A: The non-aggressive mode only removes dangling images.
   Named images and tags are safe.
   (Use aggressive: true only if you really know what you're doing)

Q: How much disk space will I get back?
A: Typically 500MB-2GB per cleanup (once a week).
   Total: 2-8GB per month of stable operation.

Q: Does this affect running containers?
A: No. Cleanup only removes stopped containers and unused images.
   Running containers are untouched.

Q: What if Docker daemon crashes during cleanup?
A: The cleanup has timeouts. It will fail gracefully.
   Docker daemon will restart automatically.

Q: Can I trigger cleanup manually?
A: Yes! API endpoint: curl -X POST http://localhost:4001/docker/prune

Q: Will I get notified when cleanup runs?
A: Yes, if you set up Telegram alerts (optional).
   Otherwise check the logs: ./logs/

═════════════════════════════════════════════════════════════════════════════

QUICK TROUBLESHOOTING
─────────────────────

Setup failed? Try these:
  1. Make sure Docker Desktop is running
  2. Make sure you have write permissions to ~/.docker/
  3. Try running in PowerShell as Administrator
  4. Check: curl http://localhost:4001/docker/status

Scheduled task not running?
  1. Check Task Scheduler: Start > Task Scheduler
  2. Navigate to: Task Scheduler Library > Guardian
  3. Right-click GuardianDockerCleanup > Run

Verify it's working:
  curl http://localhost:4001/docker/config-summary
  Look for: "log_rotation_enabled": true

═════════════════════════════════════════════════════════════════════════════

FINAL CHECKLIST
────────────────

Before you declare victory, confirm these items:

□ Run setup_docker_autocleanup.py (completes successfully)
□ See "daemon.json configured" message
□ See "Docker prune completed" with space freed
□ See "Scheduled cleanup configured" message
□ Verify API works: curl http://localhost:4001/docker/status
□ See log rotation enabled in config-summary
□ Check Task Scheduler has GuardianDockerCleanup task
□ Feel relief knowing SSD bloat is now automatic

═════════════════════════════════════════════════════════════════════════════

NOW GO DO IT!
─────────────

Ready? Run this one command:

  python setup_docker_autocleanup.py

That's it. Your SSD bloat problem is solved. 🎉

═════════════════════════════════════════════════════════════════════════════

Still have questions? Read these files:
  • DOCKER_SETUP.md - Complete documentation
  • DOCKER_AUTO_CLEANUP.py - Quick start guide
  • IMPLEMENTATION_SUMMARY.txt - What was added

═════════════════════════════════════════════════════════════════════════════
"""
    print(plan)


if __name__ == "__main__":
    print_action_plan()
