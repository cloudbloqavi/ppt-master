# Google Antigravity SDK — Integration & Deployment Guide

This guide is the **primary technical reference** for the `ppt-master` autonomous agent. It covers everything a new developer needs to get from zero to a running agent — locally on WSL 2 or any Linux machine, and in production on GCP Cloud Run Jobs.

> **New here?** Start at [Local Quick Start](#-local-quick-start-any-linux--wsl-2) and get the agent running before reading anything else.

---

## 📁 Repository Architecture

```
ppt-master/                      # Root: SDK infrastructure & deployment config
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
mkdir -p ~/development/ppt-master

# Sync the repository to your WSL home directory
rsync -ah --info=progress2 /mnt/c/Users/<your-windows-username>/repo/ppt-master/ ~/development/ppt-master/
cd ~/development/ppt-master
```

**If you are on a native Linux machine** (fresh clone):

```bash
# Clone the repository
git clone https://github.com/<org>/ppt-master.git ~/development/ppt-master
cd ~/development/ppt-master
```

Confirm you are on the right path:
```bash
pwd
# Expected: /home/<your-username>/development/ppt-master  (NOT /mnt/c/...)
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
```

What gets installed:
- `google-antigravity` — the autonomous agent SDK (includes the Go `localharness` binary)
- `cairosvg` — SVG → PNG rendering for PPTX export
- `python-dotenv` — `.env` file loading
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
[INFO]   Source dir:      /home/user/development/ppt-master/core-ppt-master-engine/projects
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
cd ~/development/ppt-master
source .venv/bin/activate

# Sync latest code changes from Windows (WSL only)
rsync -av --exclude='.venv' --exclude='__pycache__' --exclude='core-ppt-master-engine/projects' \
  /mnt/c/Users/<your-windows-username>/repo/ppt-master/ ~/development/ppt-master/

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
| Artifact Registry repo | `ppt-master` in your region | `gcloud artifacts repositories create ppt-master --repository-format=docker --location=us-central1` |
| Secret Manager secret | `gemini-api-key` | `echo -n "AIzaSy..." \| gcloud secrets create gemini-api-key --data-file=-` |
| GCS bucket | `your-ppt-master-outputs` | For output persistence |
| Service Account | For Cloud Run Job runtime | Optional — defaults to Compute SA |

### Step 2 — Create the GCS output bucket

```bash
# Create the bucket (outputs land here after every job run)
gcloud storage buckets create gs://your-ppt-master-outputs \
  --project=YOUR_PROJECT_ID \
  --location=us-central1

# Grant the Cloud Run runtime service account write access to the bucket
gcloud storage buckets add-iam-policy-binding gs://your-ppt-master-outputs \
  --member="serviceAccount:YOUR_PROJECT_NUMBER-compute@developer.gserviceaccount.com" \
  --role="roles/storage.objectAdmin"
```

### Step 3 — Build and test the Docker image locally first

> **Always test the image locally** before pushing to GCP. This catches dependency issues, missing env vars, and Dockerfile errors without spending Cloud Build minutes.

```bash
# Build the image locally (from the repo root)
docker build -t ppt-master-agent:local .

# Quick sanity check — run the self-test inside the container (no API key needed)
docker run --rm ppt-master-agent:local python run_agent.py --self-test
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
  ppt-master-agent:local \
  python run_agent.py --prompt "Create a 3-slide test deck."

# Check what was produced
ls -lh /tmp/ppt-local-outputs/
cat /tmp/ppt-local-outputs/run_manifest.json
```

> ✅ If the local Docker run succeeds, the same image will work identically in Cloud Run.

### Step 3 — Deploy the Cloud Run Job

```bash
gcloud run jobs create ppt-master-agent \
  --image=us-central1-docker.pkg.dev/YOUR_PROJECT/ppt-master/ppt-master-agent:latest \
  --region=us-central1 \
  --task-timeout=3600 \
  --max-retries=1 \
  --memory=4Gi \
  --cpu=2 \
  --set-secrets="GEMINI_API_KEY=gemini-api-key:latest" \
  --set-env-vars="OUTPUT_ARTIFACTS_DIR=/workspace/outputs" \
  --add-volume=name=gcs-output,type=cloud-storage,bucket=your-ppt-master-outputs \
  --add-volume-mount=volume=gcs-output,mount-path=/workspace/outputs
```

### Step 5 — Execute the job and verify the run

```bash
# Run with the AGENT_PROMPT env variable (set at job level during create/update)
gcloud run jobs execute ppt-master-agent --region=us-central1 --wait

# Run with a one-off prompt override (overrides AGENT_PROMPT for this execution only)
gcloud run jobs execute ppt-master-agent \
  --region=us-central1 \
  --args="--prompt,Create a 15-slide investor pitch deck for a fintech startup." \
  --wait
```

**Verify the execution succeeded:**

```bash
# List recent executions and their status
gcloud run jobs executions list \
  --job=ppt-master-agent \
  --region=us-central1 \
  --limit=5
```

Expected output:
```
NAME                           COMPLETIONTIME         SUCCEEDED  FAILED
ppt-master-agent-execution-abc  2026-06-04T10:30:00Z  1          0
```

**Check outputs in GCS:**

```bash
# List all output files from the last run
gcloud storage ls -r gs://your-ppt-master-outputs/

# Download the run manifest to check status and file count
gcloud storage cp gs://your-ppt-master-outputs/run_manifest.json /tmp/run_manifest.json
cat /tmp/run_manifest.json

# Download the PPTX output
gcloud storage cp -r gs://your-ppt-master-outputs/<project-name>/ /tmp/ppt-output/
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
    _GAR_REPOSITORY=ppt-master,\
    _CLOUD_RUN_JOB_NAME=ppt-master-agent,\
    _OUTPUT_ARTIFACTS_DIR=/workspace/outputs,\
    _GEMINI_SECRET_NAME=gemini-api-key"

# Option C — update the Cloud Run Job to a specific image tag (no rebuild)
gcloud run jobs update ppt-master-agent \
  --image=us-central1-docker.pkg.dev/YOUR_PROJECT/ppt-master/ppt-master-agent:COMMIT_SHA \
  --region=us-central1
```

#### One-time trigger setup

```bash
gcloud builds triggers create github \
  --project=YOUR_PROJECT_ID \
  --repo-name=ppt-master \
  --repo-owner=YOUR_GITHUB_ORG_OR_USER \
  --branch-pattern="^main$" \
  --build-config=cloudbuild.yaml \
  --substitutions="\
    _REGION=us-central1,\
    _GAR_REPOSITORY=ppt-master,\
    _CLOUD_RUN_JOB_NAME=ppt-master-agent,\
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
    _GAR_REPOSITORY=ppt-master,\
    _CLOUD_RUN_JOB_NAME=ppt-master-agent,\
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
resource.labels.job_name="ppt-master-agent"

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
| **Prompt resolution** | Priority: `--prompt` arg → `AGENT_PROMPT` env → built-in default |
| **Path resolution** | Workspace tools resolve all relative paths from the repo root |
| **Search optimization** | `grep_search` skips `.git`, `node_modules`, `__pycache__`, `icons` (< 2s searches) |
| **Google Search grounding** | Monkey-patches the SDK to enable native Google Search inside the harness |
| **Cloud Logging** | Harness stderr is captured and forwarded to Python's `logger` with `[Harness]` prefix |
| **Artifact copy (FINAL STAGE)** | Always runs — success, failure, or interruption — copies projects → `OUTPUT_ARTIFACTS_DIR` and writes `run_manifest.json` |
| **Exit codes** | `0` = success, `1` = agent failed, `130` = interrupted (Ctrl+C). Cloud Run Job uses exit code for health tracking. |

---

## ⚠️ Troubleshooting

### WS 1006 timeout / connection drops

**Cause**: Running from a `/mnt/c/...` path in WSL.
**Fix**: Copy the repo to `~/development/ppt-master` and run from there. See [Step 1](#step-1--get-the-repository-onto-a-native-linux-filesystem).

### `GEMINI_API_KEY` or `OUTPUT_ARTIFACTS_DIR` missing

**Cause**: `.env` file not configured or virtual environment not active.
**Fix**:
```bash
# Check your .env exists and has both values
cat .env

# Check venv is active (prompt should show (.venv))
which python3
# Expected: /home/.../ppt-master/.venv/bin/python3

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
