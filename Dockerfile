# ─────────────────────────────────────────────────────────────
# Presentation Builder - Production Dockerfile
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
# On GCP Cloud Run Jobs, pass GEMINI_API_KEY via Secret Manager and
# mount a Cloud Storage bucket (FUSE) at /workspace/outputs.
# See ANTIGRAVITY.md for the full Cloud Run Job deployment reference.
#
# NOTE: Never hardcode API keys here. All secrets are injected at runtime.
# ─────────────────────────────────────────────────────────────

FROM python:3.11-slim

# Set non-secret build-time environment variables only
ENV PYTHONUNBUFFERED=1 \
    PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION=python \
    DEBIAN_FRONTEND=noninteractive

WORKDIR /workspace

# Install system dependencies:
#   git             - for version control operations within the workflow
#   libcairo2       - required for CairoSVG (SVG → PNG raster fallback)
#   libcairo2-dev   - compile-time headers for cairosvg pip wheel
#   fonts-*         - rendering fonts for SVG text fidelity
#   build-essential - C compiler toolchain for pip packages with native extensions
#   libffi-dev      - required for cffi (cairosvg dependency)
RUN apt-get update && apt-get install -y --no-install-recommends \
    git \
    libcairo2 \
    libcairo2-dev \
    libffi-dev \
    shared-mime-info \
    fontconfig \
    fonts-dejavu \
    fonts-liberation \
    gcc \
    build-essential \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first to leverage Docker layer cache
COPY requirements.txt ./

# Install all Python dependencies from requirements.txt.
# This includes:
#   google-antigravity  — Antigravity SDK (autonomous agent runtime)
#   cairosvg            — SVG → PNG rendering for PPTX export
#   python-dotenv       — .env file loading
#   + all core Presentation Builder skill dependencies
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r requirements.txt

# Copy root-level runner, configuration files, and wrapper scripts
COPY run_agent.py auto_resume.py ANTIGRAVITY.md AGENTS.md pyproject.toml gemini_model_prices.json ./
COPY agent_runner/ ./agent_runner/

# Copy the core application engine (skills, scripts, templates)
COPY core-ppt-master-engine/ ./core-ppt-master-engine/

# Verify the tool suite by running the self-test at build time.
# No API key is required for this step.
RUN python run_agent.py --self-test

# ─────────────────────────────────────────────────────────────
# Runtime secrets — injected at container start, NOT build time.
# ─────────────────────────────────────────────────────────────
# Required:
#   GEMINI_API_KEY        - Gemini API key (inject via Cloud Run secret or -e flag)
#   OUTPUT_ARTIFACTS_DIR  - Destination path for output PPTX files
# Optional:
#   AGENT_PROMPT          - Prompt override (or pass via --prompt job arg)
# ─────────────────────────────────────────────────────────────

# Default output directory inside the container.
# Override at runtime by setting OUTPUT_ARTIFACTS_DIR.
ENV OUTPUT_ARTIFACTS_DIR=/workspace/outputs

# Run the agent. Cloud Run Job arguments are appended here automatically
# and forwarded as CLI args (e.g. --prompt "your task").
CMD ["python", "-u", "run_agent.py"]
