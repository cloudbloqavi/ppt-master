# Presentation Builder Agent Runner — Quick Start Guide

This guide is the primary user onboarding document for the `ppt-master` presentation generation runner. It covers workspace setup and execution commands for running the autonomous agent locally or in development.

For detailed SDK internals, Go harness architecture, FUSE mount details, and Cloud Run Job production deployment instructions, see [ANTIGRAVITY.md](ANTIGRAVITY.md).

---

## 🚀 Local Quick Start (Linux / WSL 2 / macOS / Windows)

Follow these steps exactly to get the agent runner set up locally. Each step builds on the previous one.

### Step 1: Get the repository onto a native Linux filesystem

> ⚠️ **Critical for WSL users**: Always work from your WSL **home directory** (`~/...`), NOT from a `/mnt/c/...` path.
>
> The SDK's Go harness (`localharness`) indexes the workspace filesystem at startup. On `/mnt/c/` paths it goes through the Windows 9P bridge, adding **40–60+ second latency** that causes the connection to time out with `WS 1006`. On the native WSL ext4 filesystem, indexing completes in **under 3 seconds**.

**If you are on WSL** (copying from your Windows clone):
```bash
# Create the destination directory
mkdir -p ~/development/ai-builder-engine

# Sync the repository to your WSL home directory
# Use --checksum (-c) to ensure file edits (even with identical sizes/unreliable NTFS timestamps) are detected.
# Use --delete to keep the directories cleanly synchronized.
rsync -ahc --delete --info=progress2 /mnt/c/Users/<your-windows-username>/repo/ai-builder-engine/ ~/development/ai-builder-engine/
cd ~/development/ai-builder-engine
```

# Without checksum
```bash
rsync -ah --delete --info=progress2 /mnt/c/Users/<your-windows-username>/repo/ai-builder-engine/ ~/development/ai-builder-engine/
cd ~/development/ai-builder-engine
```

**If you are on a native Linux machine** (fresh clone):
```bash
# Clone the repository
git clone https://github.com/<org>/ai-builder-engine.git ~/development/ai-builder-engine
cd ~/development/ai-builder-engine
```

Confirm you are on the right path:
```bash
pwd
# Expected: /home/<your-username>/development/ai-builder-engine  (NOT /mnt/c/...)
```

---

### Step 2: Install System Prerequisites and Dependencies

Some Python packages have system-level dependencies. In particular, `cairosvg` requires the Cairo graphic library installed on the host system.

**On Linux / Ubuntu / WSL 2:**
```bash
sudo apt-get update && sudo apt-get install -y \
  python3 \
  python3-pip \
  python3-venv \
  libcairo2 \
  libcairo2-dev \
  libffi-dev \
  build-essential \
  git

# Verify Python version (must be 3.10+)
python3 --version
```

**On macOS:**
```bash
brew install python cairo
```

**On Windows:**
Download and install the Cairo graphics binaries from the [Cairo graphics website](https://cairographics.org/download/).

---

### Step 3: Create a Python Virtual Environment

Always use a virtual environment to keep dependencies isolated:

```bash
# Create the venv (do this once)
python3 -m venv .venv

# Activate it (do this every time you open a new terminal)
source .venv/bin/activate

# Upgrade pip
pip install --upgrade pip
```

Your terminal prompt should now show `(.venv)` at the start.

---

### Step 4: Install the Google Antigravity SDK and Dependencies

`requirements.txt` is the single source of truth — it installs the SDK, CairoSVG, and all Presentation Builder skill tools in one command:

```bash
pip install -r requirements.txt

# Install the required headless Chromium browser binary for Playwright (needed for visual review)
python3 -m playwright install chromium
```

Verify the SDK installed correctly:
```bash
python3 -c "import google.antigravity; print('SDK import OK')"
# Expected: SDK import OK
```

---

### Step 5: Configure Environment Variables

```bash
# Copy the example template
cp .env.example .env

# Open it in your editor
nano .env   # or: vim .env  / code .env
```

Set these two **required** values at minimum inside your `.env`:

```bash
# .env contents
GEMINI_API_KEY=AIzaSy...your-key-here...

# Where outputs go after a run. Choose one:
# Option A — native WSL path (recommended for performance)
OUTPUT_ARTIFACTS_DIR=/home/<your-username>/ppt-outputs

# Option B — write directly to Windows (convenient, slightly slower)
OUTPUT_ARTIFACTS_DIR=/mnt/c/Users/<your-windows-username>/Desktop/ppt-outputs
```

Get a Gemini API key at: [Google AI Studio](https://aistudio.google.com/apikey)

---

### Step 6: Run the Self-Test (No API Key Consumed)

Before running the full agent, verify the workspace tools work:

```bash
python3 run_agent.py --self-test
```

Expected output:
```
=== STARTING WORKSPACE TOOLS SELF-TEST ===

1. Testing write_file...
Result: Successfully wrote to test_run_agent_temp.txt

2. Testing read_file...
Result: 'This is a temporary test file...'

3. Testing list_directory...
Result (truncated): 'AGENTS.md...'

4. Testing grep_search...
Result: test_run_agent_temp.txt:1: ...

5. Testing run_command...
Result: {'stdout': 'Tools self-test command execution is working\n', ...}

6. Cleaning up test file...
Cleanup completed.

=== ALL WORKSPACE TOOLS PASSED SELF-TEST ===
```

If you see `FAIL` on any step, check that your virtual environment is activated and all dependencies are installed.

---

### Step 7: Run the Agent

Run the agent via the root-level wrappers. All arguments are forwarded to the modular package.

```bash
# Run with a custom prompt (recommended for testing)
python3 run_agent.py --prompt "Create a 5-slide product overview deck for a B2B SaaS company."

# Run with maximum verbosity (detailed tool logs and streamed thinking) and high thinking level
python3 run_agent.py --verbose --prompt "Create a B2B SaaS product overview deck."

# Run with custom prompt and manual override of the model's thinking level
python3 run_agent.py --thinking-level LOW --prompt "Create a B2B SaaS product overview deck."

# Run with status progress logging enabled (writes status_progress_YYYYMMDD_HHMMSS.log to output dir)
python3 run_agent.py --status-progress --prompt "Create a SaaS product deck."

# Run with the built-in default prompt (Memphis-style music festival)
python3 run_agent.py

# Run with a prompt set via environment variable (useful for scripts)
AGENT_PROMPT="Create a 10-slide investor pitch deck." python3 run_agent.py

# Auto-resume the latest failed/incomplete project from OUTPUT_ARTIFACTS_DIR
python3 auto_resume.py

# Auto-resume scanning up to 5 recent folders deep (overriding defaults)
python3 auto_resume.py --depth 5

# Alternative: Auto-resume via the main script --resume flag
python3 run_agent.py --resume
```

What you will see during a normal (default, quiet) run:
```
[INFO] Initializing Agent using Google Antigravity SDK...
[INFO] Platform: linux | Python: 3.11.x
[INFO] Prompt: Create a 5-slide product overview deck...
[INFO] MCP servers disabled. Pass --mcp to enable them.

[Agent] I'll start by creating a new project and following the SKILL.md workflow...
[INFO] [Tool Call] 'run_command'
[INFO] [Tool OK] 'run_command'
...
[INFO] ════════════════════════════════════════════════════════════
[INFO] ARTIFACT COPY STAGE
[INFO]   Source dir:      /home/user/development/ai-builder-engine/core-ppt-master-engine/projects
[INFO]   Destination dir: /home/user/ppt-outputs
[INFO]   Run status:      success
[INFO] ════════════════════════════════════════════════════════════
[INFO]   Files copied: 14
[INFO]   Manifest written: /home/user/ppt-outputs/run_manifest.json
```

---

### Step 8: Check the Outputs

```bash
# List what was produced
ls -lh $OUTPUT_ARTIFACTS_DIR

# Check the run manifest for status and file count
cat $OUTPUT_ARTIFACTS_DIR/run_manifest.json
```

The `run_manifest.json` always contains:
```json
{
  "run_status": "success",
  "timestamp_utc": "2026-06-04T10:00:00+00:00",
  "prompt": "Create a 5-slide product overview deck...",
  "files_copied": 14,
  "copy_errors": []
}
```

The `.pptx` file is in: `$OUTPUT_ARTIFACTS_DIR/<project-name>/`

---

### Subsequent Runs (After Initial Setup)

Once set up, your daily workflow is just:

```bash
cd ~/development/ai-builder-engine
source .venv/bin/activate

# Sync latest code changes from Windows (WSL only)
# --checksum (-c) is crucial when syncing from NTFS to WSL to detect code edits reliably.
rsync -avc --delete --exclude='.venv' --exclude='__pycache__' --exclude='core-ppt-master-engine/projects' \
  /mnt/c/Users/<your-windows-username>/repo/ai-builder-engine/ ~/development/ai-builder-engine/

# Run the agent
python3 run_agent.py --prompt "Your prompt here"
```

---

## 📡 Status Feed → GCP Pub/Sub (Local & Hosted)

The runner emits a non-technical, user-facing **status feed** (e.g. *"Designing slide 2 of 5…"*, *"Research source captured: …"*). Locally, `--status-progress` writes it to a log file. Independently, the runner **also publishes every event to GCP Pub/Sub** whenever a topic is targetable — so a frontend can show live progress.

Key guarantees (why this needs setup, not just a topic):
- **Ordered:** events publish with message ordering enabled, keyed by `RUN_ID`, so they reach the topic in emission order. **The subscription must also enable ordering** or the consumer can still receive them out of order.
- **No lost events:** the runner flushes in-flight publishes before the process exits — important for a Cloud Run Job, which terminates the instant the agent finishes.
- **Message shape:** JSON `{ timestamp, status, event_type ("progress"|"citation"), run_id, data? }`. `run_id` doubles as the ordering key.

### Mode A — Local testing (`gcloud auth` / ADC)

Publish from your own machine using Application Default Credentials. Requires the `gcloud` CLI and a GCP project (`google-cloud-pubsub` is already in `requirements.txt`).

```bash
# 0. One-time: authenticate and select a project
gcloud auth login
gcloud config set project YOUR_PROJECT_ID
gcloud auth application-default login          # ADC the publisher client uses

# 1. One-time: create the topic + an ORDER-PRESERVING subscription
gcloud pubsub topics create status-progress
gcloud pubsub subscriptions create status-progress-sub \
  --topic=status-progress \
  --enable-message-ordering                    # REQUIRED for in-order delivery

# 2. Run the agent, pointed at the topic
export GOOGLE_CLOUD_PROJECT=YOUR_PROJECT_ID
export STATUS_PUBSUB_TOPIC=projects/$GOOGLE_CLOUD_PROJECT/topics/status-progress
python3 run_agent.py --prompt "Create a 5-slide product overview deck."

# 3. Observe the published events (a second terminal)
gcloud pubsub subscriptions pull status-progress-sub --auto-ack --limit=50
```

> **Fully offline (no GCP, no ADC)** — use the Pub/Sub emulator. The client auto-detects `PUBSUB_EMULATOR_HOST`.
> ```bash
> gcloud beta emulators pubsub start --host-port=localhost:8085     # terminal 1
> export PUBSUB_EMULATOR_HOST=localhost:8085                         # terminal 2
> export STATUS_PUBSUB_TOPIC=projects/local-test/topics/status-progress
> python3 run_agent.py --prompt "Create a 5-slide deck."
> ```
> (Emulator message-ordering support is partial — fine for smoke tests, not for verifying strict ordering.)

### Mode B — Hosted (Cloud Run Job)

In production the feed **auto-enables** — no CLI flag and, if you use the default topic name, no topic env var. Cloud Run Jobs set `CLOUD_RUN_JOB` / `CLOUD_RUN_EXECUTION`, which the runner detects.

#### One-time prerequisites

```bash
PROJECT_ID=YOUR_PROJECT_ID
RUNTIME_SA=YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com   # or your custom SA

# 1. Pub/Sub topic + ORDER-PRESERVING subscription
gcloud pubsub topics create status-progress --project=$PROJECT_ID
gcloud pubsub subscriptions create status-progress-sub \
  --topic=status-progress --project=$PROJECT_ID --enable-message-ordering

# 2. Grant the runtime SA publisher access
gcloud pubsub topics add-iam-policy-binding status-progress \
  --project=$PROJECT_ID \
  --member="serviceAccount:$RUNTIME_SA" \
  --role="roles/pubsub.publisher"
```

> **Automated alternative:** set `_BOOTSTRAP_PUBSUB=true` in your `cloudbuild.yaml` trigger substitutions and these two steps run automatically on the first Cloud Build deploy — idempotent on all subsequent pushes.

#### Deploy wiring

The Cloud Build pipeline (`cloudbuild.yaml`) handles the full wiring. Key substitutions to set in your trigger (or `--substitutions` on a manual submit):

| Substitution | What it does |
|---|---|
| `_OUTPUT_BUCKET` | GCS bucket mounted at `_OUTPUT_ARTIFACTS_DIR` — outputs persist across runs |
| `_RUNTIME_SA` | Service account the job runs as (must hold `storage.objectAdmin` + `pubsub.publisher`) |
| `_STATUS_PUBSUB_TOPIC` | Override the auto-resolved topic (leave empty to use the default `status-progress`) |
| `_BOOTSTRAP_PUBSUB=true` | Set once, on first deploy, to auto-create the topic + ordered subscription |

```bash
# Default topic auto-resolves from GOOGLE_CLOUD_PROJECT — nothing to set.
# OR pin an explicit topic:
gcloud run jobs update ai-builder-agent --region=us-central1 \
  --set-env-vars=STATUS_PUBSUB_TOPIC=projects/$PROJECT_ID/topics/status-progress

# Optional: per-execution output isolation (each run writes to its own GCS prefix)
gcloud run jobs update ai-builder-agent --region=us-central1 \
  --set-env-vars=OUTPUT_ARTIFACTS_DIR=/workspace/outputs/'${CLOUD_RUN_EXECUTION}'
```

Notes:
- `RUN_ID` (the Pub/Sub ordering key) defaults to `CLOUD_RUN_EXECUTION` automatically, so **each job execution is its own ordered stream** — no extra config needed.
- For the complete build/deploy reference (Artifact Registry, Secret Manager, GCS FUSE mount, Cloud Build IAM), see **[ANTIGRAVITY.md → "Production Deployment: GCP Cloud Run Job"](ANTIGRAVITY.md)**.

---

## 🎛️ CLI Arguments Reference

The runner scripts support the following command-line options for control and customization.

### Detailed Options & Examples

#### 1. `--prompt "<text>"`
* **Description**: The instruction prompt sent to the agent. Overrides the `AGENT_PROMPT` environment variable.
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --prompt "Create a 5-slide deck on renewable energy trends."
  ```

#### 2. `--status-progress`
* **Description**: Enables generating simplified, user-facing, non-technical status progress logs inside the `OUTPUT_ARTIFACTS_DIR` (e.g. `status_progress_YYYYMMDD_HHMMSS.log`). Independently, status updates are published to GCP Pub/Sub whenever a topic is targetable (auto-enabled on Cloud Run). See the **"Status Feed → GCP Pub/Sub (Local & Hosted)"** section above for local and hosted setup.
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --status-progress --prompt "Create a quick marketing timeline."
  ```

#### 3. `--verbose`
* **Description**: Enables verbose diagnostics. Streams the model's reasoning/thoughts blocks, lists exact tool inputs/outputs, and logs detailed SDK messages directly to the terminal.
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --verbose --prompt "Create a SaaS product launch slide."
  ```

#### 4. `--thinking-level <MINIMAL|LOW|MEDIUM|HIGH>`
* **Description**: Manually overrides the model's thinking budget level. Defaults to `MEDIUM` (or `HIGH` when running under `--verbose`).
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --thinking-level HIGH --prompt "Refactor slide layout colors."
  ```

#### 5. `--resume`
* **Description**: Watchdog mode. Scans `OUTPUT_ARTIFACTS_DIR` for incomplete projects, restores the latest incomplete project folder to the active workspace, and resumes generation.
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --resume
  ```

#### 6. `--depth <number>`
* **Description**: The number of recent project directories under `OUTPUT_ARTIFACTS_DIR` to inspect when scanning for auto-resumption candidates. Defaults to the `WATCHDOG_DEPTH` env variable, or `3`.
* **Script Support**: `run_agent.py`, `auto_resume.py`
* **Example**:
  ```bash
  python3 auto_resume.py --depth 5
  ```

#### 7. `--no-visual-review`
* **Description**: Opts out of the visual review phase. By default, the runner triggers a Playwright/Chromium-based automated screenshot and visual review gate to verify layout correcteness.
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --no-visual-review --prompt "Create a B2B SaaS pitch."
  ```

#### 8. `--mcp`
* **Description**: Enables loading local Model Context Protocol (MCP) servers configured inside `mcp_config.json` (such as local filesystem search, git adapters, or database connectors).
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --mcp --prompt "Refactor template styles."
  ```

#### 9. `--self-test`
* **Description**: Runs an isolated verification of workspace tools (writing, reading, searching, listing, and command running) to ensure environment permissions are functional. No LLM calls are made and no API key is required.
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --self-test
  ```

#### 10. `--log-file` (or `--file-log`)
* **Description**: Configures a log handler to simultaneously write all execution and diagnostic logs to a file inside the `OUTPUT_ARTIFACTS_DIR` (e.g. `run_agent_YYYYMMDD_HHMMSS.log`).
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --log-file --prompt "Create a B2B SaaS pitch."
  ```

#### 11. `--model <name>`
* **Description**: Explicitly sets the Google Gemini model ID for execution. Defaults to `gemini-3.5-flash`.
* **Script Support**: `run_agent.py`
* **Example**:
  ```bash
  python3 run_agent.py --model gemini-3.5-pro --prompt "Create a 5-slide deck."
  ```

---

## 📁 Repository Structure

*   `run_agent.py` — Thin delegator wrapper to run the agent.
*   `auto_resume.py` — Watchdog wrapper to resume incomplete runs.
*   `agent_runner/` — Refactored core modules containing config, logging setup, status log adapter, self-test tools, resumption, and manifest/artifacts logic.
*   `core-ppt-master-engine/` — Contains application workflows (`SKILL.md`), scripts, layout templates, and output project folders.
