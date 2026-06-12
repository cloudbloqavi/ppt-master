"""
Configuration & Environment Module for Presentation Builder Agent Runner

Handles command-line arguments parsing, environment validation, logging logger
creation, and early runtime configuration.
"""
import os
import sys
import argparse
import logging
from pathlib import Path

# Structured logging for Cloud Logging compatibility (JSON-friendly on stdout/stderr)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("ppt-master-agent")

# Set protobuf implementation to pure-python before importing google.antigravity.
# Avoids "TypeError: Couldn't build proto file into descriptor pool: Edition
# UNKNOWN is later than the maximum edition 2023" on some Python 3.13+ builds.
os.environ.setdefault("PROTOCOL_BUFFERS_PYTHON_IMPLEMENTATION", "python")

# Reconfigure stdout/stderr to UTF-8 on Windows to prevent UnicodeEncodeError
# when the agent streams Unicode tokens.  No-op on Linux/macOS.
if sys.platform == "win32":
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except AttributeError:
            pass

# Set fallback harness path on Windows for Antigravity IDE users
if not os.environ.get("ANTIGRAVITY_HARNESS_PATH") and sys.platform == "win32":
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidate = Path(local_app_data) / "agy" / "bin" / "agy.exe"
        if candidate.exists():
            os.environ["ANTIGRAVITY_HARNESS_PATH"] = str(candidate)

# Load environment variables from .env (if python-dotenv is available).
try:
    import dotenv
    dotenv.load_dotenv()
except ImportError:
    pass

# Set GCE check skip to prevent metadata server query hangs in Go harness
os.environ["NO_GCE_CHECK"] = "true"


def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="Presentation Builder - Antigravity SDK Agent Runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mcp",
        action="store_true",
        help="Enable loading local MCP servers from mcp_config.json.",
    )
    parser.add_argument(
        "--self-test",
        action="store_true",
        help="Run self-test of the workspace tools in isolation (no API key needed).",
    )
    parser.add_argument(
        "--prompt",
        type=str,
        default=None,
        help=(
            "The prompt to send to the agent. "
            "Overrides the AGENT_PROMPT environment variable. "
            "Also used as the Cloud Run Job override argument."
        ),
    )
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Automatically find and resume the latest failed execution from OUTPUT_ARTIFACTS_DIR.",
    )
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Number of recent project directories to verify when resuming (defaults to WATCHDOG_DEPTH env var or 3).",
    )
    parser.add_argument(
        "--no-visual-review",
        action="store_true",
        help="Opt out of running the visual review phase (which runs by default).",
    )
    parser.add_argument(
        "--verbose",
        action="store_true",
        help="Enable verbose output (e.g. streaming of model thoughts and detailed tool results).",
    )
    parser.add_argument(
        "--thinking-level",
        type=str,
        default=None,
        choices=["MINIMAL", "LOW", "MEDIUM", "HIGH"],
        help="Explicitly set the model's thinking level (overrides default/verbose defaults).",
    )
    parser.add_argument(
        "--log-file",
        "--file-log",
        action="store_true",
        dest="log_file",
        help="Simultaneously write execution logs to run_agent.log inside the OUTPUT_ARTIFACTS_DIR.",
    )
    parser.add_argument(
        "--status-progress",
        action="store_true",
        help="Generate non-technical status progress logs in the OUTPUT_ARTIFACTS_DIR.",
    )
    parser.add_argument(
        "--model",
        type=str,
        default="gemini-3.5-flash",
        help="Google Gemini model name to use for the main agent run (default: gemini-3.5-flash).",
    )
    # Use parse_known_args so unknown flags don't crash the script
    args, _ = parser.parse_known_args()
    return args


ARGS = parse_args()


def _validate_env():
    """Validate that all required environment variables are present.

    Exits with a descriptive error if any mandatory variable is missing.
    Validation is skipped when running --self-test.
    """
    errors = []

    api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if not api_key:
        errors.append(
            "  • GEMINI_API_KEY (or GOOGLE_API_KEY) — your Google Gemini API key."
        )

    output_dir = os.environ.get("OUTPUT_ARTIFACTS_DIR")
    if not output_dir:
        errors.append(
            "  • OUTPUT_ARTIFACTS_DIR — absolute path where output projects will be copied after a run."
        )

    if errors:
        logger.error(
            "Startup validation failed. The following required environment variables are not set:\n%s\n"
            "Set them in your .env file or as environment variables (Cloud Run Job env/secrets).",
            "\n".join(errors),
        )
        sys.exit(1)

    # Normalise GEMINI_API_KEY
    os.environ["GEMINI_API_KEY"] = api_key


if not ARGS.self_test:
    _validate_env()
else:
    # Even in self-test mode, set up GEMINI_API_KEY if it exists (optional)
    _api_key = os.environ.get("GEMINI_API_KEY") or os.environ.get("GOOGLE_API_KEY")
    if _api_key:
        os.environ["GEMINI_API_KEY"] = _api_key
