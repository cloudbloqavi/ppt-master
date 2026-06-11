#!/usr/bin/env python3
"""
PPT Master - Antigravity SDK Agent Runner Entry Wrapper

Thin delegation script that invokes the core agent execution flow modularized
under the `agent_runner` package. This keeps the root interface backward compatible
with all container environments, Cloud Build configs, and local CLI execution commands.
"""
import sys
from agent_runner.core import main_run

if __name__ == "__main__":
    sys.exit(main_run())
