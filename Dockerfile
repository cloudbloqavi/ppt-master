# ─────────────────────────────────────────────────────────────
# Presentation Builder - Production Dockerfile (multi-stage, non-root)
# ─────────────────────────────────────────────────────────────
# Designed for Google Cloud Run Jobs.
#
# Build:
#   docker build -t ai-builder-agent .
#
# Run locally (mount an output directory):
#   docker run --rm \
#     -e GEMINI_API_KEY="AIza..." \
#     -e OUTPUT_ARTIFACTS_DIR="/workspace/outputs" \
#     -e AGENT_PROMPT="Create a 10-slide product launch deck" \
#     -v $(pwd)/outputs:/workspace/outputs \
#     ai-builder-agent
#
# To publish the status feed to Pub/Sub from a local container, also pass
# STATUS_PUBSUB_TOPIC + GOOGLE_CLOUD_PROJECT and mount ADC credentials. On GCP
# Cloud Run Jobs, inject GEMINI_API_KEY via Secret Manager, grant the runtime
# service account roles/pubsub.publisher, and mount a Cloud Storage bucket (FUSE)
# at /workspace/outputs. See ANTIGRAVITY.md for the full deployment reference.
#
# NOTE: Never hardcode secrets here. All secrets are injected at runtime.
# ─────────────────────────────────────────────────────────────

# ───────────────────────── Stage 1: builder ─────────────────────────
# Compiles Python wheels with the full toolchain into an isolated venv. None of
# these build tools (gcc, *-dev headers) ship in the runtime image below.
FROM python:3.11-slim AS builder

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/venv/bin:$PATH"

RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    gcc \
    libffi-dev \
    libcairo2-dev \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Self-contained virtualenv so the runtime stage can copy a single tree.
RUN python -m venv /opt/venv

# Copy requirements first (both the root file and the nested skill file it
# references via `-r`) to leverage Docker layer caching.
COPY requirements.txt ./requirements.txt
COPY core-ppt-master-engine/skills/ppt-master/requirements.txt \
     ./core-ppt-master-engine/skills/ppt-master/requirements.txt
RUN pip install --upgrade pip && pip install -r requirements.txt

# ───────────────────────── Stage 2: runtime ─────────────────────────
# Slim image with only the RUNTIME system libraries (no compilers/headers).
FROM python:3.11-slim AS runtime

ENV PYTHONUNBUFFERED=1 \
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
    DEBIAN_FRONTEND=noninteractive \
    PATH="/opt/venv/bin:$PATH" \
    OUTPUT_ARTIFACTS_DIR=/workspace/outputs \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Runtime-only system dependencies:
#   git             - version control operations within the workflow
#   libcairo2       - runtime lib for CairoSVG (SVG → PNG raster fallback)
#   fonts-*         - rendering fonts for SVG text fidelity
#   fontconfig / shared-mime-info - font + MIME resolution for the renderers
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libcairo2 \
    shared-mime-info \
    fontconfig \
    fonts-dejavu \
    fonts-liberation \
    && rm -rf /var/lib/apt/lists/*

# Bring in the pre-built virtualenv from the builder stage.
COPY --from=builder /opt/venv /opt/venv

# Install Playwright's Chromium browser AND its OS dependencies at build time, so
# the agent's visual review never downloads a browser at runtime — mirroring the
# WSL/QUICKSTART setup (`python3 -m playwright install chromium`) and giving full
# local/hosted parity with no network egress required on Cloud Run. Placed before
# the application COPYs so this heavy layer stays cached across code changes, and
# made world-readable so the non-root runtime user can launch it.
RUN apt-get update \
    && playwright install --with-deps chromium \
    && chmod -R a+rx /ms-playwright \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /workspace

# Copy ONLY the root-level files read during an actual run (verified):
#   run_agent.py / auto_resume.py — entrypoint + --resume wrapper
#   gemini_model_prices.json      — cost reporting (agent_runner/artifacts.py)
#   requirements.txt              — used only by the runtime dependency self-heal
#                                   path (core.py check_and_install_dependencies);
#                                   harmless no-op in a correctly built image.
# AGENTS.md is NOT copied here. Instead, agent_runner/AGENTS.RUNTIME.md (included
# via the agent_runner/ COPY below) is copied to ./AGENTS.md at startup by core.py
# so the Antigravity SDK auto-discovers the runtime-only instructions.
# Intentionally NOT copied: AGENTS.md (dev file), ANTIGRAVITY.md, pyproject.toml,
# cloudbuild.yaml, check_dependencies.py, normalize_branding.py, subagents*,
# scripts/svg_doctor/, and all other root *.md docs.
COPY run_agent.py auto_resume.py gemini_model_prices.json requirements.txt ./
COPY agent_runner/ ./agent_runner/

# Copy the core application engine (skills, scripts, templates). This also brings
# in core-ppt-master-engine/skills/ppt-master/requirements.txt, referenced via -r
# by the root requirements.txt on the self-heal path above.
COPY core-ppt-master-engine/ ./core-ppt-master-engine/

# Run as an unprivileged user (least privilege; Cloud Run best practice).
RUN useradd --create-home --uid 1000 appuser \
    && mkdir -p /workspace/outputs \
    && chown -R appuser:appuser /workspace
USER appuser

# Verify the tool suite by running the self-test at build time.
# No API key is required for this step.
RUN python run_agent.py --self-test

# ─────────────────────────────────────────────────────────────
# Runtime secrets — injected at container start, NOT build time.
# ─────────────────────────────────────────────────────────────
# Required:
#   GEMINI_API_KEY        - Gemini API key (inject via Cloud Run secret or -e flag)
#   OUTPUT_ARTIFACTS_DIR  - Destination path for output PPTX files (defaults below)
# Optional:
#   AGENT_PROMPT          - Prompt override (or pass via --prompt job arg)
#   STATUS_PUBSUB_TOPIC   - Publish the status feed to this Pub/Sub topic
#   GOOGLE_CLOUD_PROJECT  - Derives the default topic on Cloud Run when unset
# ─────────────────────────────────────────────────────────────

# Run the agent. Cloud Run Job arguments are appended here automatically
# and forwarded as CLI args (e.g. --prompt "your task").
CMD ["python", "-u", "run_agent.py"]
