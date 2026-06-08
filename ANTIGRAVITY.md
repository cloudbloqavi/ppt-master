# Google Antigravity SDK — Integration & Deployment Guide

This guide is the **primary technical reference** for the `ppt-master` autonomous agent. It covers everything a new developer needs to get from zero to a running agent — locally on WSL 2 or any Linux machine, and in production on GCP Cloud Run Jobs.

> **New here?** Start at [Local Quick Start](#-local-quick-start-any-linux--wsl-2) and get the agent running before reading anything else.

---

## 📁 Repository Architecture

```
ai-builder-engine/               # Root: SDK infrastructure & deployment config
├── run_agent.py                 # ← Entry point. Run this to start the agent.
├── requirements.txt             # All Python deps (SDK + skill tools) — single source of truth
├── Dockerfile                   # Production container (Cloud Run Job)
├── cloudbuild.yaml              # GCP Cloud Build CI/CD pipeline
├── .env.example                 # Template for your local .env file
├── .dockerignore                # Docker build exclusions
├── ANTIGRAVITY.md               # [This file] Integration & deployment manual
├── AGENTS.md                    # Workflow rules and skill quick reference
└── core-ppt-master-engine/      # Core application
    ├── skills/ppt-master/
    │   ├── SKILL.md             # Master workflow — read before any PPT task
    │   ├── scripts/             # Post-processing & compilation scripts
    │   ├── templates/           # Slide layouts, icons, brand presets
    │   └── workflows/           # Standalone sub-workflows
    ├── projects/                # Agent working directory (output source)
    ├── examples/                # Pre-built reference projects
    └── docs/                    # Architecture specs and guides
```

---

## 🔐 Environment Variables

These are validated at startup by `run_agent.py`. The runner exits with a clear error if either mandatory variable is missing.

### Required

| Variable | Description | Example |
|:---|:---|:---|
| `GEMINI_API_KEY` | Google Gemini API key | `AIzaSy...` |
| `OUTPUT_ARTIFACTS_DIR` | Path where output PPTX projects are copied after each run | `/home/user/ppt-outputs` |

### Optional

| Variable | Description | Example |
|:---|:---|:---|
| `AGENT_PROMPT` | Prompt sent to the agent (env-based alternative to `--prompt`) | `Create a 10-slide deck` |
| `ANTIGRAVITY_HARNESS_PATH` | Override path to the Go `localharness` binary | `/usr/local/.../localharness` |
| `WATCHDOG_DEPTH` | Number of recent project folders the auto-resumption checks (defaults to `3`) | `5` |

> **`--self-test` skips validation** — you can run `python run_agent.py --self-test` without any API key to verify the workspace tools work.

---

## 🚀 Local Quick Start (Any Linux / WSL 2)

Follow these steps exactly. Each step builds on the previous one.

---

### Step 1 — Get the repository onto a native Linux filesystem

> ⚠️ **Critical for WSL users**: Always work from your WSL **home directory** (`~/...`), NOT from a `/mnt/c/...` path.
>
> The SDK's Go harness (`localharness`) indexes the workspace filesystem at startup. On `/mnt/c/` paths it goes through the Windows 9P bridge, adding **40–60+ second latency** that causes the connection to time out with `WS 1006`. On the native WSL ext4 filesystem, indexing completes in **under 3 seconds**.

**If you are on WSL** (copying from your Windows clone):

```bash
# Create the destination directory
mkdir -p ~/development/ai-builder-engine

# Sync the repository to your WSL home directory
rsync -ah --info=progress2 /mnt/c/Users/<your-windows-username>/repo/ai-builder-engine/ ~/development/ai-builder-engine/
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

### Step 2 — Install system dependencies

The agent needs Python 3.10+, Cairo (for SVG rendering), and some build tools:

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
# Expected: Python 3.10.x or higher
```

---

### Step 3 — Create a Python virtual environment

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

### Step 4 — Install the Google Antigravity SDK and all dependencies

`requirements.txt` is the single source of truth — it installs the SDK, CairoSVG, and all PPT Master skill tools in one command:

```bash
pip install -r requirements.txt

# Install the required headless Chromium browser binary for Playwright (needed for visual review)
python3 -m playwright install chromium
```

What gets installed:
- `google-antigravity` — the autonomous agent SDK (includes the Go `localharness` binary)
- `cairosvg` — SVG → PNG rendering for PPTX export
- `python-dotenv` — `.env` file loading
- Playwright and the headless Chromium browser binary (used for the visual self-review loop)
- All PPT Master skill dependencies (python-pptx, PyMuPDF, Pillow, etc.)

Verify the SDK installed correctly:
```bash
python3 -c "import google.antigravity; print('SDK import OK')"
# Expected: SDK import OK
```

---

### Step 5 — Configure environment variables

```bash
# Copy the example template
cp .env.example .env

# Open it in your editor
nano .env   # or: vim .env  / code .env
```

Set these two **required** values at minimum:

```bash
# .env contents
GEMINI_API_KEY=AIzaSy...your-key-here...

# Where outputs go after a run. Choose one:
# Option A — native WSL path (recommended for performance)
OUTPUT_ARTIFACTS_DIR=/home/<your-username>/ppt-outputs

# Option B — write directly to Windows (convenient, slightly slower)
OUTPUT_ARTIFACTS_DIR=/mnt/c/Users/<your-windows-username>/Desktop/ppt-outputs
```

Get a Gemini API key at: https://aistudio.google.com/apikey

---

### Step 6 — Run the self-test (no API key consumed)

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

### Step 7 — Run the agent

```bash
# Run with a custom prompt (recommended for testing)
python3 run_agent.py --prompt "Create a 5-slide product overview deck for a B2B SaaS company."

# Run with the built-in default prompt (Memphis-style music festival)
python3 run_agent.py

# Run with a prompt set via environment variable (useful for scripts)
AGENT_PROMPT="Create a 10-slide investor pitch deck." python3 run_agent.py
```

What you will see during a run:
```
[INFO] Initializing Agent using Google Antigravity SDK...
[INFO] Platform: linux | Python: 3.11.x
[INFO] Prompt: Create a 5-slide product overview deck...
[INFO] MCP servers disabled. Pass --mcp to enable them.

[Thinking] Reading AGENTS.md to understand the workflow...
[Agent] I'll start by creating a new project and following the SKILL.md workflow...
[INFO] [Tool Call] 'run_command' args: {...}
[INFO] [Tool Result] 'run_command' (id: ...): {...}
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

### Step 8 — Check the outputs

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

### Subsequent runs (after initial setup)

Once set up, your daily workflow is just:

```bash
cd ~/development/ai-builder-engine
source .venv/bin/activate

# Sync latest code changes from Windows (WSL only)
rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='core-ppt-master-engine/projects' \
  /mnt/c/Users/<your-windows-username>/repo/ai-builder-engine/ ~/development/ai-builder-engine/

# Run the agent
python3 run_agent.py --prompt "Your prompt here"
```

---

## 🐳 Production Deployment: GCP Cloud Run Job

For production, staging, or CI/CD environments, the agent runs as a **Google Cloud Run Job** inside a containerized environment. The container uses the same `run_agent.py` entry point — the only difference is how environment variables and outputs are provided.

### Architecture

```
Source push → Cloud Build Trigger
  → docker build (--self-test runs at build time, no secrets needed)
  → Push image to Artifact Registry
  → Create or update Cloud Run Job
       └→ Container starts run_agent.py
          ├── GEMINI_API_KEY   ← bound from Secret Manager at runtime
          ├── OUTPUT_ARTIFACTS_DIR = /workspace/outputs  ← GCS FUSE mount
          └── All logs (agent + harness) → stderr → Cloud Logging
```

### How output persistence works in Cloud Run

Cloud Run containers use ephemeral storage — everything is lost when the container exits. To persist PPTX outputs, mount a **GCS bucket** as a volume using Cloud Storage FUSE. The container writes files to `/workspace/outputs` like a normal directory; GCS receives the objects automatically with no code changes.

`run_agent.py` copies all outputs to `OUTPUT_ARTIFACTS_DIR` at the end of every run (success **and** failure), then writes `run_manifest.json` to confirm the run outcome. This is identical behavior to local mode.

### Step 1 — GCP Prerequisites

| Resource | What to create | Notes |
|:---|:---|:---|
| GCP Project | With billing enabled | |
| Artifact Registry repo | `ai-builder-engine` in your region | `gcloud artifacts repositories create ai-builder-engine --repository-format=docker --location=us-central1` |
| Secret Manager secret | `gemini-api-key` | `echo -n "AIzaSy..." \| gcloud secrets create gemini-api-key --data-file=-` |
| GCS bucket | `your-ai-builder-outputs` | For output persistence |
| Service Account | For Cloud Run Job runtime | Optional — defaults to Compute SA |

### Step 2 — Create the GCS output bucket

```bash
# Create the bucket (outputs land here after every job run)
gcloud storage buckets create gs://your-ai-builder-outputs \
  --project=YOUR_PROJECT_ID \
  --location=us-central1

# Grant the Cloud Run runtime service account write access to the bucket
gcloud storage buckets add-iam-policy-binding gs://your-ai-builder-outputs \
  --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### Step 3 — Build and test the Docker image locally first

> **Always test the image locally** before pushing to GCP. This catches dependency issues, missing env vars, and Dockerfile errors without spending Cloud Build minutes.

```bash
# Build the image locally (from the repo root)
docker build -t ai-builder-agent:local .

# Quick sanity check — run the self-test inside the container (no API key needed)
docker run --rm ai-builder-agent:local python run_agent.py --self-test
```

Expected output from the container self-test:
```
=== STARTING WORKSPACE TOOLS SELF-TEST ===
1. Testing write_file...   Result: Successfully wrote to ...
2. Testing read_file...    Result: 'This is a temporary test file...'
3. Testing list_directory... Result (truncated): 'AGENTS.md...'
4. Testing grep_search...  Result: test_run_agent_temp.txt:1: ...
5. Testing run_command...  Result: {'stdout': 'Tools self-test command execution...'}
6. Cleaning up test file... Cleanup completed.
=== ALL WORKSPACE TOOLS PASSED SELF-TEST ===
```

Full local run (with real API key and a local output folder):
```bash
# Create a local output folder to receive artifacts
mkdir -p /tmp/ppt-local-outputs

# Run the full agent locally inside Docker
docker run --rm \
  -e GEMINI_API_KEY="AIzaSy...your-key..." \
  -e OUTPUT_ARTIFACTS_DIR=/outputs \
  -v /tmp/ppt-local-outputs:/outputs \
  ai-builder-agent:local \
  python run_agent.py --prompt "Create a 3-slide test deck."

# Check what was produced
ls -lh /tmp/ppt-local-outputs/
cat /tmp/ppt-local-outputs/run_manifest.json
```

> ✅ If the local Docker run succeeds, the same image will work identically in Cloud Run.

### Step 3 — Deploy the Cloud Run Job

```bash
gcloud run jobs create ai-builder-agent \
  --image=us-central1-docker.pkg.dev/YOUR_PROJECT/ai-builder-engine/ai-builder-agent:latest \
  --region=us-central1 \
  --task-timeout=3600 \
  --max-retries=1 \
  --memory=4Gi \
  --cpu=2 \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest" \
  --set-env-vars="OUTPUT_ARTIFACTS_DIR=/workspace/outputs" \
  --add-volume=name=gcs-output,type=cloud-storage,bucket=your-ai-builder-outputs \
  --add-volume-mount=volume=gcs-output,mount-path=/workspace/outputs
```

### Step 5 — Execute the job and verify the run

```bash
# Run with the AGENT_PROMPT env variable (set at job level during create/update)
gcloud run jobs execute ai-builder-agent --region=us-central1 --wait

# Run with a one-off prompt override (overrides AGENT_PROMPT for this execution only)
gcloud run jobs execute ai-builder-agent \
  --region=us-central1 \
  --args="--prompt,Create a 15-slide investor pitch deck for a fintech startup." \
  --wait
```

**Verify the execution succeeded:**

```bash
# List recent executions and their status
gcloud run jobs executions list \
  --job=ai-builder-agent \
  --region=us-central1 \
  --limit=5
```

Expected output:
```
NAME                           COMPLETIONTIME         SUCCEEDED  FAILED
ai-builder-agent-execution-abc  2026-06-04T10:30:00Z  1          0
```

**Check outputs in GCS:**

```bash
# List all output files from the last run
gcloud storage ls -r gs://your-ai-builder-outputs/

# Download the run manifest to check status and file count
gcloud storage cp gs://your-ai-builder-outputs/run_manifest.json /tmp/run_manifest.json
cat /tmp/run_manifest.json

# Download the PPTX output
gcloud storage cp -r gs://your-ai-builder-outputs/<project-name>/ /tmp/ppt-output/
```

The `run_manifest.json` in GCS will show:
```json
{
  "run_status": "success",
  "timestamp_utc": "2026-06-04T10:28:00+00:00",
  "prompt": "Create a 15-slide investor pitch deck...",
  "files_copied": 14,
  "copy_errors": []
}
```

> **Even if the job fails**, `run_manifest.json` is written with `"run_status": "failed"` and whatever partial files were produced. Check it first when debugging.

### Step 6 — CI/CD Pipeline (Google Cloud Build)

`cloudbuild.yaml` automates the full build → push → deploy lifecycle. Cloud Build integrates natively with Secret Manager — no GitHub secrets or external credential management needed.

#### Re-deploying after code changes

After any change to `run_agent.py`, `requirements.txt`, or the `core-ppt-master-engine/` code:

```bash
# Option A — let Cloud Build do it automatically (push to main)
git add . && git commit -m "Your change" && git push origin main
# Cloud Build trigger fires, builds new image, updates Cloud Run Job automatically

# Option B — manual one-off submit
gcloud builds submit . \
  --config=cloudbuild.yaml \
  --project=YOUR_PROJECT_ID \
  --substitutions="\
    _REGION=us-central1,\
    _GAR_REPOSITORY=ai-builder-engine,\
    _CLOUD_RUN_JOB_NAME=ai-builder-agent,\
    _OUTPUT_ARTIFACTS_DIR=/workspace/outputs,\
    _GEMINI_SECRET_NAME=gemini-api-key"

# Option C — update the Cloud Run Job to a specific image tag (no rebuild)
gcloud run jobs update ai-builder-agent \
  --image=us-central1-docker.pkg.dev/YOUR_PROJECT/ai-builder-engine/ai-builder-agent:COMMIT_SHA \
  --region=us-central1
```

#### One-time trigger setup

```bash
gcloud builds triggers create github \
  --project=YOUR_PROJECT_ID \
  --repo-name=ai-builder-engine \
  --repo-owner=YOUR_GITHUB_ORG_OR_USER \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml \
  --substitutions="\
    _REGION=us-central1,\
    _GAR_REPOSITORY=ai-builder-engine,\
    _CLOUD_RUN_JOB_NAME=ai-builder-agent,\
    _OUTPUT_ARTIFACTS_DIR=/workspace/outputs,\
    _GEMINI_SECRET_NAME=gemini-api-key"
```

After this, every push to `main` triggers a build and deploy automatically.

#### Manual one-off build

```bash
gcloud builds submit . \
  --config=cloudbuild.yaml \
  --project=YOUR_PROJECT_ID \
  --substitutions="\
    _REGION=us-central1,\
    _GAR_REPOSITORY=ai-builder-engine,\
    _CLOUD_RUN_JOB_NAME=ai-builder-agent,\
    _OUTPUT_ARTIFACTS_DIR=/workspace/outputs,\
    _GEMINI_SECRET_NAME=gemini-api-key"
```

#### Required IAM roles for the Cloud Build Service Account

Grant these roles to `YOUR_PROJECT_NUMBER@cloudbuild.gserviceaccount.com`:

| Role | Purpose |
|:---|:---|
| `roles/artifactregistry.writer` | Push Docker images to Artifact Registry |
| `roles/run.admin` | Create / update Cloud Run Jobs |
| `roles/secretmanager.secretAccessor` | Read `GEMINI_API_KEY` from Secret Manager |
| `roles/iam.serviceAccountUser` | Act as Cloud Run runtime Service Account |

```bash
PROJECT_NUMBER=$(gcloud projects describe YOUR_PROJECT_ID --format='value(projectNumber)')
CB_SA="${PROJECT_NUMBER}@cloudbuild.gserviceaccount.com"

for role in \
  roles/artifactregistry.writer \
  roles/run.admin \
  roles/secretmanager.secretAccessor \
  roles/iam.serviceAccountUser; do
  gcloud projects add-iam-policy-binding YOUR_PROJECT_ID \
    --member="serviceAccount:$CB_SA" \
    --role="$role"
done
```

### Step 6 — Cloud Logging

All agent and harness logs write to stderr and are captured by Cloud Logging automatically. Filter in Logs Explorer:

```
# All Cloud Run Job logs
resource.type="cloud_run_job"
resource.labels.job_name="ai-builder-agent"

# Harness (Go binary) logs only
resource.type="cloud_run_job"
textPayload:"[Harness]"

# Cloud Build pipeline logs
resource.type="build"
```

---

## ⚙️ How the Runner Works

`run_agent.py` is the single entry point for all environments. Here's what it does internally:

| Feature | Detail |
|:---|:---|
| **Env validation** | Checks `GEMINI_API_KEY` + `OUTPUT_ARTIFACTS_DIR` at startup; exits with a clear error if missing |
| **Prompt resolution** | Priority: `--resume` / `--prompt` arg → `AGENT_PROMPT` env → built-in default |
| **Auto-Resumption** | If `--resume` or prompt matches `"resume"`, automatically scans `OUTPUT_ARTIFACTS_DIR` for incomplete projects within `WATCHDOG_DEPTH` depth, restores them to the workspace, and resumes execution. |
| **Path resolution** | Workspace tools resolve all relative paths from the repo root |
| **Search optimization** | `grep_search` skips `.git`, `node_modules`, `__pycache__`, `icons`, `venv`, `env`, `exports`, `images` (< 2s searches) |
| **Google Search grounding** | Monkey-patches the SDK to enable native Google Search inside the harness |
| **Cloud Logging** | Harness stderr is captured and forwarded to Python's `logger` with `[Harness]` prefix |
| **Artifact copy (FINAL STAGE)** | Always runs — success, failure, or interruption — copies projects → `OUTPUT_ARTIFACTS_DIR` and writes `run_manifest.json` |
| **Exit codes** | `0` = success, `1` = agent failed, `130` = interrupted (Ctrl+C). Cloud Run Job uses exit code for health tracking. |

---

### 📡 Programmatic Agent Execution & Tool Flow

The following diagram illustrates how a user prompt moves through the Python runner, the native Go harness, the Gemini API, and dynamic subagent execution, concluding with artifact storage.

```text
+-------------------------------------------------------------------------------+
|                                USER COMMAND                                   |
|      python run_agent.py --prompt "Please turn the following into a PPT..."   |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+---------------------------------------+---------------------------------------+
|  run_agent.py (Python SDK Wrapper)                                            |
|  - Validates environment (API key, output dir)                               |
|  - Configures LocalAgentConfig (workspaces=["."], tools=[])                   |
+---------------------------------------+---------------------------------------+
                                        |
                                        v  [Launches (Deferred subprocess)]
+---------------------------------------+---------------------------------------+
|  google.antigravity Go Harness (agy/agy.exe)                                  |
|  - Sandboxes the workspace & monitors folders                                 |
|  - Dynamically injects Workspace Tools (read_file, write_file, run_command)   |
|  - Injects native Platform Tools (invoke_subagent)                            |
+----------------------------------+----+----------------------------------+----+
                                   |                                       |
    [Workspace & Shell Tools]      |                                       | [LLM Messages]
                                   v                                       v
+----------------------------------+----+                       +----------+----+
|  Local Codebase Filesystem            |                       |  Gemini API   |
|  - core-ppt-master-engine/projects/   |                       |  (gemini-     |
|  - scripts (latex_render, etc.)       |                       |  3.5-flash)   |
+---------------------------------------+                       +----+----------+
                                                                     ^
                                                                     | [invoke_subagent]
                                                                     v
                                                        +------------+----------+
                                                        | Parallel Subagents    |
                                                        | (Concurrent Clones)   |
                                                        | - Visual Review       |
                                                        | - Source Processing   |
                                                        +------------+----------+
                                                                     |
                                                                     v [Write reports/JSON]
                                                        +------------+----------+
                                                        | Local Workspace State |
                                                        | - .review/*.json      |
                                                        +------------+----------+
                                                                     |
                                                                     | [Execution Ends]
                                                                     v
+--------------------------------------------------------------------+----------+
|  FINAL STAGE: copy_output_artifacts()                                         |
|  - Mirrors projects/ directory tree to OUTPUT_ARTIFACTS_DIR                   |
|  - Writes run_manifest.json (Run status, metadata)                            |
|  - GCS FUSE mapping automatically uploads files to Google Cloud Storage       |
+-------------------------------------------------------------------------------+
```

#### Step-by-Step Scenario Walkthrough

* **Step A: Invocation & Env Validation**  
  A user runs `python run_agent.py --prompt "Please turn the following into a PPT: ..."` (locally or as a Google Cloud Run Job).  
  `run_agent.py` validates that `GEMINI_API_KEY` and `OUTPUT_ARTIFACTS_DIR` are present. It loads the `google-antigravity` SDK, resolves the prompt, and creates a `LocalAgentConfig` with `tools=[]` and `workspaces=["."]`.

* **Step B: Booting the Native Go Harness**  
  The Python SDK boots the Go-based `localharness` binary (`agy.exe` on Windows or `agy` on Linux/macOS) in the background. The harness serves as the sandbox controller and local API server for the agent.

* **Step C: System Tool Injection**  
  Because the harness manages the workspace directory at the operating system level, it automatically registers and injects standard workspace tools (like `read_file`, `write_file`, `grep_search`, `run_command`, and the subagent-spawning tool `invoke_subagent`) into the agent's LLM context. Consequently, you do not need to register these system tools programmatically in Python (`tools=[]` is kept empty).

* **Step D: Parent Agent Loop & LLM Communication**  
  The parent agent starts communicating with the Google Gemini API to interpret the prompt and execute the workflow. It reads source files, resolves layouts, runs Latin/formula rendering commands, and writes the `design_spec.md` and `spec_lock.md` files.

* **Step E: Parallel Subagent Execution**  
  When running a parallelizable step (such as checking pages in the visual review workflow), the parent agent issues concurrent `invoke_subagent` tool calls to the harness with `"wait_for_completion": false`. The harness boots multiple subagent clones (`self` type) in the background. The subagents read the slide SVGs, inspect the rendered PNGs, perform edits, write slide JSON reports to `.review/<page>.json`, and exit. The parent agent receives the completion signals and aggregates the results.

* **Step F: Artifact Copy & Manifest Logging**  
  Regardless of whether the agent succeeds, fails, or is interrupted (Ctrl+C), a `finally` block in `run_agent.py` always executes the `copy_output_artifacts()` stage. It mirrors the generated project files under `projects/` to the `OUTPUT_ARTIFACTS_DIR` and logs a `run_manifest.json` metadata summary. If running in a Cloud Run Job, the destination directory is mapped transparently to a Google Cloud Storage (GCS) bucket via a Cloud Storage FUSE mount, allowing all outputs to land directly in GCS.

---

### 🔄 Native Auto-Resumption

The agent runner supports native auto-resumption of incomplete runs (ideal for running on cron schedules, like Google Cloud Scheduler).

When `--resume` is supplied or the resolved prompt is `"resume"` (case-insensitive):
1. **Scan**: It scans `OUTPUT_ARTIFACTS_DIR` for the most recent projects up to `WATCHDOG_DEPTH` (defaults to `3`).
2. **Detect Incomplete**: It checks each project for a `.pptx` file inside the `exports/` folder. The first folder missing a `.pptx` is marked for resumption.
3. **Restore**: If the project directory is not present locally in the workspace (common in fresh container environments), it copies the project folder from `OUTPUT_ARTIFACTS_DIR` back to the workspace.
4. **Trigger**: It overrides the prompt to `"resume generating projects/<project_name>"` and starts the agent.
5. **No-op Exit**: If all projects within the scan depth are already complete, it prints a success log and exits with code `0` immediately without calling the Gemini API.

#### Execution Wrapper
`auto_resume.py` is provided as a lightweight wrapper that delegates to `run_agent.py --resume`. You can use it as a cron entry point:
```bash
# Run with default depth (3)
python3 auto_resume.py

# Run with a custom depth (5)
python3 auto_resume.py --depth 5
```

### 🇨🇳 CJK Translation & Verification

The project is strictly 100% English. To enforce the **Zero Chinese Characters Rule** and to prevent CJK (Chinese, Japanese, Korean) characters from being introduced during remote upstream merges, the repository includes an automated scanner and translator.

#### Scanner Utility
A validation script `check_cjk.py` is located in the scripts directory. You can run it locally to audit the repository or automatically translate content:
```bash
# Scan the repository for any Chinese characters (exits with 1 if found)
python3 core-ppt-master-engine/skills/ppt-master/scripts/check_cjk.py --scan

# Automatically translate all CJK characters in place using Gemini API
python3 core-ppt-master-engine/skills/ppt-master/scripts/check_cjk.py --translate

# Scan or translate specific files (e.g. conflicted files)
python3 core-ppt-master-engine/skills/ppt-master/scripts/check_cjk.py --scan --files path/to/file1.py
```
For remote updates, always follow the merge guidelines in [AGENTS.md](AGENTS.md) to ensure all incoming CJK characters are translated and template folders are mapped to lowercase English IDs.

---

## ⚠️ Troubleshooting

### WS 1006 timeout / connection drops

**Cause**: Running from a `/mnt/c/...` path in WSL.
**Fix**: Copy the repo to `~/development/ai-builder-engine` and run from there. See [Step 1](#step-1--get-the-repository-onto-a-native-linux-filesystem).

### `GEMINI_API_KEY` or `OUTPUT_ARTIFACTS_DIR` missing

**Cause**: `.env` file not configured or virtual environment not active.
**Fix**:
```bash
# Check your .env exists and has both values
cat .env

# Check venv is active (prompt should show (.venv))
which python3
# Expected: /home/.../ai-builder-engine/.venv/bin/python3

# Re-activate if needed
source .venv/bin/activate
```

### `RuntimeError: Could not find default localharness binary`

**Cause**: `google-antigravity` not installed, or installed outside the active venv.
**Fix**:
```bash
# Confirm the SDK is installed in the active venv
pip show google-antigravity

# If missing, install it
pip install -r requirements.txt

# If the binary is in a non-standard location, set the path explicitly
export ANTIGRAVITY_HARNESS_PATH="/path/to/.venv/lib/python3.x/site-packages/google/antigravity/bin/localharness"
```

### `SDK import OK` but agent fails immediately

**Cause**: API key invalid or quota exhausted.
**Fix**: Check the key at https://aistudio.google.com/apikey and verify it has the Gemini API enabled.

### `cairosvg` import error or SVG rendering warnings

**Cause**: `libcairo2` system library not installed.
**Fix**:
```bash
sudo apt-get install -y libcairo2 libcairo2-dev
pip install --force-reinstall cairosvg
```

### `E: dpkg was interrupted, you must manually run 'sudo dpkg --configure -a'`

**Cause**: A previous package installation (`apt` or `dpkg` command) was terminated or aborted prematurely, locking the package database.
**Fix**: Repair the database by running:
```bash
sudo dpkg --configure -a
```
Once complete, re-run the dependency installation command.

### `-bash: .venv/bin/pip: No such file or directory` (or command not found)

**Cause**: The `.venv` directory was deleted, moved, or corrupted, but the shell session is still active with the old virtualenv environment variables (prompt still shows `(.venv)`).
**Fix**: Reset the session and recreate the virtual environment:
```bash
deactivate
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

### Orphaned harness processes after Ctrl+C

If the agent is interrupted, the Go harness can stay running in the background:
```bash
# Linux / WSL — kill all harness processes
pkill -f localharness; pkill -f agy

# Verify they're gone
ps aux | grep -E 'localharness|agy'
```

---

## 📚 References

- **PyPI Package**: [google-antigravity](https://pypi.org/project/google-antigravity/)
- **SDK GitHub**: [google-antigravity/antigravity-sdk-python](https://github.com/google-antigravity/antigravity-sdk-python)
- **Gemini API Key**: [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
- **Cairo for Windows**: [cairographics.org/download](https://cairographics.org/download/)
