#!/usr/bin/env python3
"""
PPT Master - Auto Resumption Watchdog Wrapper

Thin delegation script that invokes the resumption watchdog modularized
under the `agent_runner` package. This keeps the root interface backward compatible
with cron schedules, watchdogs, and local execution commands.
"""
import sys
from agent_runner.core import main_resume

if __name__ == "__main__":
    sys.exit(main_resume())
