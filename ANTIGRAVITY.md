# Google Antigravity SDK — Integration & Deployment Guide

This guide is the **primary technical reference** for the `ppt-master` autonomous agent. It covers everything a new developer needs to get from zero to a running agent — locally on WSL 2 or any Linux machine, and in production on GCP Cloud Run Jobs.

> **Looking for onboarding details?** Check the streamlined [Quick Start Guide](QUICKSTART.md) for virtual environment setup, dependencies, and command-line execution flags.

---

## 📁 Repository Architecture

```
ai-builder-engine/               # Root: SDK infrastructure & deployment config
├── run_agent.py                 # ← Entry point. Run this to start the agent.
├── auto_resume.py               # ← Watchdog wrapper to resume incomplete runs.
├── requirements.txt             # All Python deps (SDK + skill tools) — single source of truth
├── Dockerfile                   # Production container (Cloud Run Job)
├── cloudbuild.yaml              # GCP Cloud Build CI/CD pipeline
├── .env.example                 # Template for your local .env file
├── .dockerignore                # Docker build exclusions
├── ANTIGRAVITY.md               # [This file] Integration & deployment manual
├── AGENTS.md                    # Workflow rules and skill quick reference
├── QUICKSTART.md                # Onboarding guide (on virtual env, packages, CLI flags)
├── agent_runner/                # Refactored core modular package
│   ├── __init__.py
│   ├── config.py                # Command-line configuration and argument parsing
│   ├── logging_setup.py         # Set up process logging
│   ├── status_logger.py         # User-facing status progress logging
│   ├── tools.py                 # Workspace and self-test execution tools
│   ├── resumption.py            # Watchdog/resumption logic
│   ├── checkpoints.py           # Artifact-driven checkpoint / stage detection for resume
│   ├── artifacts.py             # Replicating workspace to output directory (+ chart_provenance copy)
│   ├── visual_enforcement.py    # Runner-enforced layout audit + auto-fix (post-turn)
│   ├── provenance_enforcement.py# Chart provenance validation + structural-mimic review (post-turn)
│   └── core.py                  # Core agent loop and runner entry points
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
| `RUN_AGENT_MAX_RETRIES` | Max attempts (retries) to retry when agent exits without generating new PPTX files | `3` |
| `STATUS_PUBSUB_TOPIC` | Optional: The GCP Pub/Sub topic to publish status progress updates in production | `projects/...` |

> **`--self-test` skips validation** — you can run `python run_agent.py --self-test` without any API key to verify the workspace tools work.

---

## 🎛️ CLI Arguments Reference

The runner scripts support the following command-line options for control and customization:

| Argument | Description | Script(s) | Example / Choices |
|:---|:---|:---|:---|
| `--prompt <text>` | The prompt to send to the agent (Overrides `AGENT_PROMPT` env var). | `run_agent.py` | `--prompt "Create a 5-slide deck"` |
| `--status-progress` | Enable writing simplified user-facing status log files inside output directory. | `run_agent.py` | (Flag) |
| `--verbose` | Enable verbose execution. Streams thinking blocks and prints detailed tool inputs/outputs. | `run_agent.py` | (Flag) |
| `--thinking-level <level>` | Manually override the model's thinking level. Defaults to `MEDIUM` (or `HIGH` under `--verbose`). | `run_agent.py` | `MINIMAL`, `LOW`, `MEDIUM`, `HIGH` |
| `--resume` | Automatically resume the latest incomplete run. | `run_agent.py` | (Flag) |
| `--depth <num>` | Verify `<num>` recent output folders when checking for resumption candidates. | `run_agent.py`, `auto_resume.py` | `--depth 5` |
| `--no-visual-review` | Skip the visual review / self-check phase entirely. | `run_agent.py` | (Flag) |
| `--mcp` | Enable loading local MCP servers from `mcp_config.json`. | `run_agent.py` | (Flag) |
| `--self-test` | Test workspace tools in isolation (does not call LLM / consume API key). | `run_agent.py` | (Flag) |
| `--log-file` | Simultaneously write all execution logs to `run_agent.log` inside `OUTPUT_ARTIFACTS_DIR`. Also accepts `--file-log`. | `run_agent.py` | (Flag) |
| `--model <name>` | The name of the Google Gemini model to run the agent on. | `run_agent.py` | `--model gemini-2.5-flash` |

---

## 🚀 Local Quick Start (Any Linux / WSL 2)

Follow these steps exactly. Each step builds on the previous one. (These steps have also been detailed in [QUICKSTART.md](QUICKSTART.md).)
---

### Subsequent runs (after initial setup)

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

## 📡 Programmatic Agent Execution & Tool Flow

The following diagram illustrates how a user prompt moves through the Python runner, the native Go harness, the Gemini API, and dynamic subagent execution, concluding with artifact storage.

```text
+-------------------------------------------------------------------------------+
|                                USER COMMAND                                   |
|      python run_agent.py --prompt "Please turn the following into a PPT..."   |
+---------------------------------------+---------------------------------------+
                                        |
                                        v
+---------------------------------------+---------------------------------------+
|  run_agent.py (Delegates to agent_runner core package)                        |
|  - Validates environment (API key, output dir)                               |
|  - Configures LocalAgentConfig (with CapabilitiesConfig for subagents)         |
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
  `run_agent.py` validates that `GEMINI_API_KEY` and `OUTPUT_ARTIFACTS_DIR` are present. It loads the `google-antigravity` SDK, resolves the prompt, and creates a `LocalAgentConfig` with `tools=[]`, `workspaces=["."]`, and `capabilities=CapabilitiesConfig(enable_subagents=True)` to explicitly enable subagents.

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

## ⚙️ How the Runner Works

`run_agent.py` delegates to the `agent_runner` modular package. Here's what it does internally:

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

### SDK Integration and execution details:

#### 1. Harness Path & Protobuf Handling
*   `PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION` is set to `python` before importing the SDK to ensure compatibility with Python 3.13+.
*   On Windows, the runner dynamically looks up `%LOCALAPPDATA%/agy/bin/agy.exe` and registers it in `ANTIGRAVITY_HARNESS_PATH` if not overridden.

#### 2. Google Search Grounding Patches
The SDK is monkey-patched to inject search grounding configurations inside the Go harness launcher:
```python
LocalConnectionStrategy._build_harness_config
```
This forces `enable_google_search = True` in the harness schema, allowing Gemini to ground tool decisions on web knowledge.

#### 3. Harness Command patches
When spawning the background harness subprocess via `subprocess.Popen`, the wrapper intercepts and inserts the mandatory `"localharness"` argument when launching `agy` binaries.

#### 4. Cloud Logging Stream
The harness stderr stream is wrapped and printed as `[Harness] <line>` to Python's stderr. In Google Cloud Run Jobs, this ensures all harness logs are captured, structured, and indexed by Cloud Logging.

---

## 🩺 SVG Quality, Chart Provenance & Structural-Mimic Review

The engine matches every visualization slide to a template — **company catalog first** (`templates/charts/powerslides_infographics/`), then the **stock** catalog (`templates/charts/`), then a bespoke **custom** design — and reproduces that template's structure with the runtime theme. The following artifact + tools make that pipeline auditable and fixable. (Background: company templates were historically never selected, and matched templates were silently redrawn as new shapes; these close both gaps.)

### `chart_provenance.json` — per-slide selection decision record

Written by the Strategist and **confirmed by the Executor** (the Executor is the source of truth for what actually shipped), one entry per chart slide. It is the single reconciled record — `design_spec.md §VII` (intent), `spec_lock.md page_charts` (lock), and the drawn SVG could otherwise disagree. Schema: [`templates/chart_provenance_reference.md`](core-ppt-master-engine/skills/ppt-master/templates/chart_provenance_reference.md).

| `tier` | `reference` resolves to | Reviewed against a reference? |
|:---|:---|:---|
| `company` | `templates/charts/powerslides_infographics/<key>.svg` | yes |
| `stock` | `templates/charts/<key>.svg` | yes |
| `custom` | `null` (bespoke; `decision` MUST say why neither catalog fit) | no — skipped |

It is copied **next to the run logs** in `OUTPUT_ARTIFACTS_DIR/<project>/` (see `artifacts.py` → `_copy_provenance_alongside`) so the decision flow can be inspected alongside `run_manifest.json` and the logs.

### Runner-enforced structural-mimic review

After the agent's turn (right after the visual-review enforcement, in `core.py`), `agent_runner/provenance_enforcement.py`:
1. **Validates** `chart_provenance.json` — references exist on disk for `company`/`stock`, company refs sit under `powerslides_infographics/`, every `custom` page carries a non-empty reason.
2. **Reviews structure** via `core-ppt-master-engine/skills/ppt-master/scripts/chart_structural_review.py` — tier-aware: for `company`/`stock` slides it compares the **generated SVG's topology** against the reference (element-type histogram + repeated-unit count + element mass), and **skips** `custom`. Runtime theme (color/font/exact text) is deliberately ignored — only structure. Report-only/advisory; per-page findings land in `<project>/.review/structural/summary.json`. The affinity formula + thresholds are documented in the script.

> Limitation: this is **topology** comparison — it cannot see geometry-orientation or aesthetic bugs (e.g. an inverted-but-same-shapes pyramid scores ~identical). Those need a rendered look (the visual-review pass), which is why `svg_doctor` flags them rather than auto-fixing.

### `svg_doctor.py` — standalone single-SVG lint & auto-fix

Vets **any one SVG** with no project context — a hand-authored slide, or sweeping the chart catalog to find fragile templates:

```bash
SD=core-ppt-master-engine/skills/ppt-master/scripts/svg_doctor.py
python3 $SD file.svg            # REVIEW (default): list issues, change nothing
python3 $SD file.svg --fix      # FIX: apply AUTO-FIXABLE items only (REVIEW items never touched)
python3 $SD file.svg --fix -o out.svg   # write the fixed copy elsewhere
python3 $SD file.svg --json     # machine-readable findings (for CI / catalog sweeps)
```

Findings split into two classes. **Hard invariant: `--fix` must never change how the SVG renders** — it only repairs internal issues while leaving the visible asset pixel-identical. Anything whose safe fix is *not* visually neutral is flag-only. (Core principle: **not every fix needs AI**.)

| Class | Examples | Fix path |
|:---|:---|:---|
| **AUTO-FIX** (provably visual no-op) | add `xmlns`/`viewBox`, HTML entity → identical glyph, unescaped `&` → `&amp;`, `rgba()` → hex **+ matching `-opacity` (alpha preserved)**, strip non-rendering `<script>`/`<iframe>` | deterministic `--fix` — no AI |
| **NEEDS REVIEW** (intent/aesthetics, OR a fix that would alter appearance) | mirrored/flipped transforms (the pyramid-inversion class), raw-export bloat, out-of-bounds, orphan baseline, heavy SVG; **plus** `<style>`/`<foreignObject>`/`<animate>`, `class=`, `<g opacity>`, `rgba` inside `style="…"` | **flag only** — fix by human/AI while preserving the look |

`--fix` never edits a REVIEW-class item, so it can neither break a slide nor silently change its appearance. Exit code is `1` when REVIEW findings remain (CI-gateable). Sweep the company catalog with:

```bash
for f in core-ppt-master-engine/skills/ppt-master/templates/charts/powerslides_infographics/*.svg; do
  python3 $SD "$f" --json; done
```

> **Catalog note (raw exports):** several company templates are raw PowerPoint exports whose geometry uses `matrix(1 0 0 -1 …)` vertical flips. Faithful mimicry reproduces them as-is, which can render inverted/jagged (the original "broken pyramid"). `svg_doctor` flags these as `mirrored_transform`; the fix is to **re-orient** the paths (flip → `translate`), not to remove them blindly — see the corrected `06_pyramid.svg` for the pattern.

---

## 🔄 Native Auto-Resumption

The agent runner supports native auto-resumption of incomplete runs (ideal for running on cron schedules, like Google Cloud Scheduler).

When `--resume` is supplied or the resolved prompt is `"resume"` (case-insensitive):
1. **Scan**: It scans `OUTPUT_ARTIFACTS_DIR` for the most recent projects up to `WATCHDOG_DEPTH` (defaults to `3`).
2. **Detect Incomplete**: It checks each project for a `.pptx` file inside the `exports/` folder. The first folder missing a `.pptx` is marked for resumption.
3. **Restore**: If the project directory is not present locally in the workspace (common in fresh container environments), it copies the project folder from `OUTPUT_ARTIFACTS_DIR` back to the workspace.
4. **Trigger**: It overrides the prompt to `"resume generating projects/<project_name>"` and starts the agent.
5. **No-op Exit**: If all projects within the scan depth are already complete, it prints a success log and exits with code `0` immediately without calling the Gemini API.

### Execution Wrapper
`auto_resume.py` is provided as a lightweight wrapper that delegates to `run_agent.py --resume`. You can use it as a cron entry point:
```bash
# Run with default depth (3)
python3 auto_resume.py

# Run with a custom depth (5)
python3 auto_resume.py --depth 5
```

---

## 🇨🇳 CJK Translation & Verification

The project is strictly 100% English. To enforce the **Zero Chinese Characters Rule** and to prevent CJK (Chinese, Japanese, Korean) characters from being introduced during remote upstream merges, the repository includes an automated scanner and translator.

### Scanner Utility
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

# Grant Service Account objectAdmin access
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

### Step 4 — Deploy the Cloud Run Job

Deploy the job using `gcloud run jobs create`, linking FUSE mounts and Secret Manager bindings:
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
# Run with env AGENT_PROMPT
gcloud run jobs execute ai-builder-agent --region=us-central1 --wait

# Run with one-off prompt args override
gcloud run jobs execute ai-builder-agent \
  --region=us-central1 \
  --args="--prompt,Create a 10-slide deck on market trends." \
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

After any change to `run_agent.py`, `requirements.txt`, or the codebase:

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

### Step 7 — Cloud Logging

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

## ⚠️ SDK Troubleshooting

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
