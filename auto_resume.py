#!/usr/bin/env python3
"""
PPT Master - Auto Resumption Watchdog Wrapper

This script is a simple wrapper that delegates to the main agent runner (run_agent.py)
using the native auto-resume capabilities.
"""

import os
import sys
import argparse
import subprocess
import logging
from pathlib import Path

# Load .env configuration
try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stdout,
)
logger = logging.getLogger("auto-resume-wrapper")

def main():
    parser = argparse.ArgumentParser(description="PPT Master Auto Resumption Watchdog Wrapper")
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Number of recent project directories to verify (defaults to WATCHDOG_DEPTH env var or 3).",
    )
    args = parser.parse_args()

    # Locate run_agent.py
    runner_script = Path(__file__).parent.resolve() / "run_agent.py"
    if not runner_script.exists():
        logger.error(f"Runner script not found: {runner_script}")
        sys.exit(1)

    cmd = [sys.executable, str(runner_script), "--resume"]
    if args.depth is not None:
        cmd.extend(["--depth", str(args.depth)])

    logger.info(f"Delegating to agent runner: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, check=True)
        sys.exit(res.returncode)
    except subprocess.CalledProcessError as err:
        logger.error(f"Agent runner failed with exit code {err.returncode}")
        sys.exit(err.returncode)

if __name__ == "__main__":
    main()
