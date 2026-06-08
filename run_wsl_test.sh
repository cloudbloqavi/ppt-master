#!/bin/bash
cd ~/development/ai-builder-engine
python3 run_agent.py --prompt "$(cat prompt.txt)"
