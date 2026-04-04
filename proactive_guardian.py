#!/usr/bin/env python3
"""
Compatibility wrapper for legacy task/module paths.

This keeps older scheduled tasks that launch `python -m Guardian.proactive_guardian`
working while the real implementation lives under `Guardian.modules.monitor`.
"""

from Guardian.modules.monitor.proactive_guardian import *  # noqa: F401,F403


if __name__ == "__main__":
    import json
    import argparse

    from Guardian.modules.monitor.proactive_guardian import (
        GuardianConfig,
        ProactiveGuardian,
    )

    parser = argparse.ArgumentParser(description="Proactive Guardian")
    parser.add_argument("--once", action="store_true", help="Run once instead of loop")
    parser.add_argument("--no-ai", action="store_true", help="Disable AI brain")
    parser.add_argument("--interval", type=int, default=60, help="Check interval (seconds)")
    parser.add_argument("--duration", type=int, help="Run for N seconds")
    parser.add_argument("--distro", type=str, default="Ubuntu", help="WSL distro name")
    args = parser.parse_args()

    guardian = ProactiveGuardian(
        GuardianConfig(
            check_interval=args.interval,
            use_ai=not args.no_ai,
            wsl_distro=args.distro,
        )
    )

    if args.once:
        print(json.dumps(guardian.run_once(), indent=2, default=str))
    else:
        guardian.start(duration=args.duration)
