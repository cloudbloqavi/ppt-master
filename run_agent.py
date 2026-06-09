#!/usr/bin/env python3
"""
PPT Master - Antigravity SDK Agent Runner

Cross-platform script that initializes an autonomous agent using the Google
Antigravity SDK (google-antigravity) configured with workspace tools (I/O,
search, shell) to execute the ppt-master presentation generation workflow.

The SDK bundles a platform-specific `localharness` binary inside its PyPI
wheel.  On `pip install google-antigravity`, the correct binary for the
current OS/arch is installed automatically.  No manual binary management
is required.

Usage:
    python run_agent.py [--prompt "..."] [--verbose] [--thinking-level LEVEL]
                        [--resume] [--depth N] [--no-visual-review]
                        [--mcp] [--self-test] [--log-file] [--model MODEL]

Options:
    --prompt <text>           The prompt to send to the agent. Overrides AGENT_PROMPT env var.
    --verbose                 Stream thinking blocks and detailed tool logs. Sets thinking to HIGH.
    --thinking-level <level>  Override thinking level (MINIMAL, LOW, MEDIUM, HIGH). Default: MEDIUM.
    --resume                  Automatically resume the latest incomplete run.
    --depth <num>             Lookback depth when checking for resumption candidates.
    --no-visual-review        Skip the visual review / self-check phase.
    --mcp                     Enable loading local MCP servers from mcp_config.json.
    --self-test               Run self-test of the workspace tools (no API key needed).
    --log-file                Write logs simultaneously to run_agent.log in OUTPUT_ARTIFACTS_DIR.
    --model <name>            Google Gemini model name to use for the execution (default: gemini-3.5-flash).

Environment Variables (required at runtime, not at --self-test):
    GEMINI_API_KEY      Your Google Gemini API key.
    OUTPUT_ARTIFACTS_DIR  Absolute path where output PPTX projects will be copied after a run.

Environment Variables (optional):
    AGENT_PROMPT        Fallback prompt if --prompt is not supplied (used for Cloud Run Job env-based config).

Dependencies:
    google-antigravity
    python-dotenv
"""

import argparse
import asyncio
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any
import logging

# Structured logging for Cloud Logging compatibility (JSON-friendly on stdout/stderr)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    stream=sys.stderr,
)
logger = logging.getLogger("ppt-master-agent")

# ─────────────────────────────────────────────────────────────
# Early Environment Setup (before any google.* imports)
# ─────────────────────────────────────────────────────────────

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

# ─────────────────────────────────────────────────────────────
# Argument Parsing
# ─────────────────────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    """Parse CLI arguments."""
    parser = argparse.ArgumentParser(
        description="PPT Master - Antigravity SDK Agent Runner",
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
        "--model",
        type=str,
        default="gemini-3.5-flash",
        help="Google Gemini model name to use for the main agent run (default: gemini-3.5-flash).",
    )
    # Use parse_known_args so unknown flags don't crash the script
    args, _ = parser.parse_known_args()
    return args

ARGS = parse_args()

# ─────────────────────────────────────────────────────────────
# Mandatory Environment Validation
# ─────────────────────────────────────────────────────────────

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


def setup_file_logging():
    """If log_file CLI argument is passed, add a FileHandler to the logging setup with a dynamic filename based on timestamp."""
    if not ARGS.log_file:
        return

    output_dir = os.environ.get("OUTPUT_ARTIFACTS_DIR")
    if not output_dir:
        # Fallback for self-test or local runs without environment variables set
        output_dir = "."

    try:
        from datetime import datetime
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        
        # Format: run_agent_YYYYMMDD_HHMMSS.log
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filepath = output_path / f"run_agent_{timestamp}.log"
        
        file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        # Add to the root logger so it catches all library logs + our custom logs
        logging.getLogger().addHandler(file_handler)
        logger.info("Writing execution logs simultaneously to file: %s", log_filepath)
    except Exception as e:
        logger.warning("Failed to configure file logging: %s", e)


setup_file_logging()

# ─────────────────────────────────────────────────────────────
# SDK Imports (deferred so protobuf env is set first)
# ─────────────────────────────────────────────────────────────

try:
    from google.antigravity import (
        Agent, LocalAgentConfig, GeminiConfig, CapabilitiesConfig,
        ModelConfig, ModelEntry, GenerationConfig, ThinkingLevel,
    )
    from google.antigravity.hooks import policy
    from google.antigravity.types import (
        McpStdioServer,
        Text,
        Thought,
        ToolCall,
        ToolResult,
    )

    # Monkey-patch LocalConnectionStrategy to inject enable_google_search=True in HarnessConfig.
    # This enables native Google Search grounding inside the Go localharness.
    from google.antigravity.connections.local.local_connection import LocalConnectionStrategy
    _orig_build_harness_config = LocalConnectionStrategy._build_harness_config

    def _patched_build_harness_config(self):
        harness_config = _orig_build_harness_config(self)
        if harness_config.gemini_config:
            harness_config.gemini_config.enable_google_search = True
        return harness_config

    LocalConnectionStrategy._build_harness_config = _patched_build_harness_config

    # Monkey-patch subprocess.Popen to insert "localharness" argument when launching agy/agy.exe.
    import subprocess as _subprocess
    _orig_popen = _subprocess.Popen

    def _patched_popen(args, *pargs, **kwargs):
        if isinstance(args, list) and len(args) > 0 and isinstance(args[0], str):
            cmd_lower = args[0].lower()
            if (
                cmd_lower.endswith("agy.exe")
                or cmd_lower.endswith("agy")
                or "agy/bin/agy" in cmd_lower.replace("\\", "/")
            ):
                if len(args) == 1:
                    args = [args[0], "localharness"]
        return _orig_popen(args, *pargs, **kwargs)

    _subprocess.Popen = _patched_popen

    # Monkey-patch LocalConnection to stream harness stderr to Python's stderr.
    # This ensures all harness (Go) logs appear in Google Cloud Logging in Cloud Run Jobs.
    from google.antigravity.connections.local.local_connection import LocalConnection
    _orig_start_stderr_reader = LocalConnection._start_stderr_reader

    class _CloudLoggingStreamWrapper:
        """Wraps the harness stderr stream to log each line to Python stderr.

        In Cloud Run Jobs, anything written to stderr is automatically
        captured and indexed by Google Cloud Logging. The [Harness] prefix
        makes it easy to filter harness-specific lines in the Logs Explorer.
        """

        def __init__(self, stream):
            self.stream = stream

        def __iter__(self):
            return self

        def __next__(self):
            line = next(self.stream)
            try:
                decoded = line.decode("utf-8", errors="replace").rstrip("\n")
                if decoded:
                    logger.info("[Harness] %s", decoded)
            except Exception:
                pass
            return line

    def _patched_start_stderr_reader(self, stderr_stream):
        wrapped = _CloudLoggingStreamWrapper(stderr_stream)
        return _orig_start_stderr_reader(self, wrapped)

    LocalConnection._start_stderr_reader = _patched_start_stderr_reader

except ImportError as e:
    if not ARGS.self_test:
        logger.error("Failed to import Google Antigravity SDK: %s", e)
        logger.error("Install it with:  pip install google-antigravity")
        sys.exit(1)

# ─────────────────────────────────────────────────────────────
# Workspace Tools
# ─────────────────────────────────────────────────────────────


def read_file(file_path: str) -> str:
    """Read the content of a file in the workspace.

    Args:
        file_path: Absolute or relative path to the file.
    Returns:
        The content of the file or an error message.
    """
    try:
        target = Path(file_path).resolve()
        with open(target, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {file_path}: {e}"


def write_file(file_path: str, content: str) -> str:
    """Write or overwrite content to a file, creating any parent folders.

    Args:
        file_path: Absolute or relative path to the file.
        content: The text content to write.
    Returns:
        A success message or an error message.
    """
    try:
        target = Path(file_path).resolve()
        target.parent.mkdir(parents=True, exist_ok=True)
        with open(target, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Successfully wrote to {file_path}"
    except Exception as e:
        return f"Error writing file {file_path}: {e}"


def list_directory(directory_path: str = ".") -> str:
    """List the files and subdirectories inside a given folder.

    Args:
        directory_path: Absolute or relative path to the folder. Defaults to '.'.
    Returns:
        A list of files and directories or an error message.
    """
    try:
        target = Path(directory_path).resolve()
        if not target.exists():
            return f"Directory does not exist: {directory_path}"
        entries = []
        for entry in sorted(target.iterdir()):
            suffix = "/" if entry.is_dir() else ""
            entries.append(f"{entry.name}{suffix}")
        return "\n".join(entries) if entries else "Directory is empty."
    except Exception as e:
        return f"Error listing directory {directory_path}: {e}"


def grep_search(query: str, directory_path: str = ".") -> str:
    """Recursively search for a text pattern in files under a directory.

    Args:
        query: The search term or pattern to look for.
        directory_path: Folder to search in. Defaults to '.'.
    Returns:
        A summary of matches or an error message.
    """
    results: list[str] = []
    try:
        root_dir = Path(directory_path).resolve()
        for file_path in root_dir.rglob("*"):
            if not file_path.is_file():
                continue
            if any(p.startswith(".") for p in file_path.parts):
                continue
            if any(part in file_path.parts for part in ("node_modules", "icons", "__pycache__", "venv", "env", "exports", "images")):
                continue
            try:
                with open(file_path, "r", encoding="utf-8", errors="ignore") as f:
                    for line_num, line in enumerate(f, 1):
                        if query in line:
                            rel = file_path.relative_to(root_dir)
                            results.append(f"{rel}:{line_num}: {line.strip()}")
                            if len(results) >= 50:
                                return "\n".join(results) + "\n... (truncated)"
            except Exception:
                pass
        return "\n".join(results) if results else "No matches found."
    except Exception as e:
        return f"Error searching for query '{query}': {e}"


def run_command(command: str, cwd: str = ".") -> dict:
    """Run a terminal or shell command in the workspace directory.

    Args:
        command: The shell command line to execute.
        cwd: Directory where the command will run. Defaults to '.'.
    Returns:
        A dictionary with stdout, stderr, and the returncode.
    """
    try:
        res = subprocess.run(
            command,
            shell=True,
            cwd=str(Path(cwd).resolve()),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        return {
            "stdout": res.stdout,
            "stderr": res.stderr,
            "returncode": res.returncode,
        }
    except Exception as e:
        return {
            "stdout": "",
            "stderr": f"Error running command '{command}': {e}",
            "returncode": -1,
        }


# ─────────────────────────────────────────────────────────────
# Output Artifact Copy
# ─────────────────────────────────────────────────────────────


def copy_output_artifacts(
    run_status: str = "unknown",
    prompt: str = "",
    token_usage: dict[str, Any] | None = None,
    execution_duration: float | None = None,
    subagent_stats: dict[str, Any] | None = None,
) -> None:
    """Copy generated project outputs to OUTPUT_ARTIFACTS_DIR.

    This is the FINAL stage of every run — it executes regardless of whether
    the agent succeeded or failed, ensuring all produced (or partial) artifacts
    are always persisted.

    How the mount works
    -------------------
    - **Locally / WSL DevTest**: set OUTPUT_ARTIFACTS_DIR to any writable path,
      e.g. ``/home/user/ppt-outputs`` or ``C:/Users/you/ppt-outputs``.
    - **GCP Cloud Run Job**: mount a GCS bucket via Cloud Storage FUSE at the
      same path (e.g. ``/workspace/outputs``).  Writing files there is
      transparent — the container sees a normal filesystem, and GCS receives
      the objects automatically.  No special code path is needed.

    What gets copied
    ----------------
    All files under ``core-ppt-master-engine/projects/`` are mirrored recursively
    to ``OUTPUT_ARTIFACTS_DIR``, preserving the relative directory tree.

    A ``run_manifest.json`` is always written to ``OUTPUT_ARTIFACTS_DIR`` even
    when there are no project files (e.g. the agent failed before creating any).
    It records the run status, timestamp, prompt, and file count so you can
    diagnose failures directly from the output bucket.

    Args:
        run_status: ``"success"``, ``"failed"``, or ``"unknown"``.
        prompt: The prompt that was sent to the agent (recorded in the manifest).
    """
    import json as _json
    from datetime import datetime, timezone

    output_dir_str = os.environ.get("OUTPUT_ARTIFACTS_DIR")
    if not output_dir_str:
        logger.warning(
            "OUTPUT_ARTIFACTS_DIR is not set — skipping artifact copy. "
            "This should not happen if validation passed."
        )
        return

    source_candidates = list(dict.fromkeys([
        Path(__file__).parent.resolve() / "core-ppt-master-engine" / "projects",
        Path(__file__).parent.resolve() / "projects"
    ]))
    destination = Path(output_dir_str).expanduser().resolve()
    timestamp_utc = datetime.now(timezone.utc).isoformat()

    logger.info("")
    logger.info("═" * 60)
    logger.info("ARTIFACT COPY STAGE")
    logger.info("  Source dirs checked:")
    for src in source_candidates:
        logger.info("    - %s", src)
    logger.info("  Destination dir: %s", destination)
    logger.info("  Run status:      %s", run_status)
    logger.info("  Timestamp (UTC): %s", timestamp_utc)
    logger.info("  (On GCP: destination is a GCS FUSE mount — files land in GCS automatically)")
    logger.info("═" * 60)

    # Always create the destination so the manifest can be written even when
    # no project files exist (e.g. agent failed before generating anything).
    destination.mkdir(parents=True, exist_ok=True)

    copied = 0
    copy_errors: list[str] = []
    found_files = False
    copied_projects: set[str] = set()

    for source in source_candidates:
        if source.exists() and any(source.iterdir()):
            for item in source.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(source)
                    # Skip root-level files directly under the projects directory (like README.md)
                    if len(rel.parts) <= 1:
                        continue

                    found_files = True
                    dest_file = destination / rel
                    try:
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest_file)
                        copied += 1
                        copied_projects.add(rel.parts[0])
                    except Exception as exc:
                        msg = f"{rel}: {exc}"
                        copy_errors.append(msg)
                        logger.error("  Copy error — %s", msg)

    if found_files:
        logger.info("  Files copied: %d", copied)
        if copy_errors:
            logger.warning("  Copy errors:  %d file(s) failed", len(copy_errors))
    else:
        logger.info("  No project output files found in checked source dirs — skipping file copy.")

    # ── Write run manifest ───────────────────────────────────
    # Written inside each copied project folder. If no project files were
    # copied (e.g. agent failed early), written to the root as a fallback.
    manifest = {
        "run_status": run_status,
        "timestamp_utc": timestamp_utc,
        "model": getattr(ARGS, "model", "gemini-3.5-flash"),
        "prompt": prompt[:500] if prompt else "",
        "source_projects_dirs": [str(src) for src in source_candidates],
        "source_projects_dir": ", ".join(str(src) for src in source_candidates),
        "output_artifacts_dir": str(destination),
        "files_copied": copied,
        "copy_errors": copy_errors,
    }
    
    # Calculate token cost if usage metadata is available
    if token_usage:
        manifest["token_usage"] = token_usage
        try:
            # Determine the model name from CLI args
            model_name = getattr(ARGS, "model", "gemini-3.5-flash")
            prices_path = Path(__file__).parent.resolve() / "gemini_model_prices.json"
            if prices_path.exists():
                with open(prices_path, "r", encoding="utf-8") as pf:
                    prices = _json.load(pf)
                
                # Retrieve rates
                rates = prices.get(model_name)
                if rates:
                    input_tokens = token_usage.get("prompt_tokens", 0)
                    cached_tokens = token_usage.get("cached_content_tokens", 0)
                    output_tokens = token_usage.get("candidates_tokens", 0)
                    
                    # Effective non-cached input tokens
                    non_cached_input = max(0, input_tokens - cached_tokens)
                    
                    input_cost = (non_cached_input / 1_000_000) * rates["input_cost_per_1m"]
                    cached_cost = (cached_tokens / 1_000_000) * rates["cached_read_cost_per_1m"]
                    output_cost = (output_tokens / 1_000_000) * rates["output_cost_per_1m"]
                    
                    total_cost = input_cost + cached_cost + output_cost
                    
                    cost_info = {
                        "model": model_name,
                        "total_approx_cost_usd": round(total_cost, 6),
                        "input_cost_usd": round(input_cost, 6),
                        "cached_read_cost_usd": round(cached_cost, 6),
                        "output_cost_usd": round(output_cost, 6)
                    }
                    manifest["approximate_cost"] = cost_info
                    logger.info("Approximate API cost calculated: $%f (%s)", total_cost, model_name)
        except Exception as cost_exc:
            logger.warning("Failed to calculate approximate token costs: %s", cost_exc)

    if execution_duration is not None:
        manifest["execution_duration_seconds"] = round(execution_duration, 2)
    if subagent_stats is not None:
        manifest["subagent_stats"] = {
            "enabled": subagent_stats.get("enabled", False),
            "total_spawned": subagent_stats.get("total_spawned", 0),
            "completed": subagent_stats.get("completed", 0),
            "details": [
                {
                    "type": d.get("type", "unknown"),
                    "task": d.get("task", "")[:200],
                    "status": d.get("status", "unknown"),
                }
                for d in subagent_stats.get("details", [])
            ],
        }

    if copied_projects:
        for project_dir in copied_projects:
            manifest_path = destination / project_dir / "run_manifest.json"
            try:
                manifest_path.write_text(_json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info("  Manifest written: %s", manifest_path)
            except Exception as exc:
                logger.error("  Failed to write run manifest inside project %s: %s", project_dir, exc)
    else:
        manifest_path = destination / "run_manifest.json"
        try:
            manifest_path.write_text(_json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("  Manifest written to root (fallback): %s", manifest_path)
        except Exception as exc:
            logger.error("  Failed to write fallback run manifest: %s", exc)

    logger.info("ARTIFACT COPY STAGE COMPLETE")
    logger.info("═" * 60)
    logger.info("")


def find_and_restore_incomplete_project(depth: int | None = None) -> str | None:
    """Scan OUTPUT_ARTIFACTS_DIR for incomplete projects and restore the latest one.

    Returns:
        The name of the project if one was restored/found, or None if all are complete/none found.
    """
    output_dir_str = os.environ.get("OUTPUT_ARTIFACTS_DIR")
    if not output_dir_str:
        logger.warning("OUTPUT_ARTIFACTS_DIR not set. Cannot run auto-resume scan.")
        return None

    output_dir = Path(output_dir_str).expanduser().resolve()
    if not output_dir.exists():
        logger.info(f"Output directory does not exist: {output_dir}. Nothing to resume.")
        return None

    # Resolve depth
    if depth is None:
        env_depth = os.environ.get("WATCHDOG_DEPTH")
        try:
            depth = int(env_depth) if env_depth else 3
        except ValueError:
            logger.warning(f"Invalid WATCHDOG_DEPTH in env: '{env_depth}'. Using 3.")
            depth = 3

    logger.info(f"Scanning output directory for incomplete runs: {output_dir} (depth: {depth})")

    # Scan directories
    import glob
    projects = []
    for entry in output_dir.iterdir():
        if entry.is_dir():
            # Signature of a started project is that it contains design_spec.md
            design_spec = entry / "design_spec.md"
            if design_spec.exists():
                pptx_files = glob.glob(str(entry / "exports" / "*.pptx"))
                projects.append({
                    "name": entry.name,
                    "path": entry,
                    "mtime": entry.stat().st_mtime,
                    "has_pptx": len(pptx_files) > 0
                })

    if not projects:
        logger.info("No projects found in the output directory.")
        return None

    # Sort projects by modification time (newest first)
    projects.sort(key=lambda p: p["mtime"], reverse=True)

    # Inspect up to depth
    targets = projects[:depth]
    for project in targets:
        logger.info(f"Checking project: {project['name']} (Last modified: {project['mtime']})")
        if project["has_pptx"]:
            logger.info(f"  [COMPLETE] PPTX already present.")
        else:
            logger.info(f"  [INCOMPLETE] No PPTX found. Initiating resumption...")
            
            # Determine workspace candidates
            workspace_candidates = [
                Path(__file__).parent.resolve() / "core-ppt-master-engine" / "projects" / project["name"],
                Path(__file__).parent.resolve() / "projects" / project["name"]
            ]
            exists_in_workspace = any(c.exists() for c in workspace_candidates)

            if not exists_in_workspace:
                target_projects_root = Path(__file__).parent.resolve() / "projects"
                if (Path(__file__).parent.resolve() / "core-ppt-master-engine" / "projects").exists():
                    target_projects_root = Path(__file__).parent.resolve() / "core-ppt-master-engine" / "projects"
                
                target_project_path = target_projects_root / project["name"]
                logger.info(f"  [RESTORE] Project folder not found in workspace. Restoring from output artifacts to {target_project_path}...")
                try:
                    shutil.copytree(project["path"], target_project_path)
                    logger.info(f"  [RESTORE] Successfully restored {project['name']} to workspace.")
                except Exception as exc:
                    logger.error(f"  [RESTORE FAILED] Could not restore {project['name']} to workspace: {exc}")
                    sys.exit(1)

            return project["name"]

    logger.info(f"All {len(targets)} scanned projects are already complete.")
    return None


# ─────────────────────────────────────────────────────────────
# Dynamic MCP Config Loader
# ─────────────────────────────────────────────────────────────


def load_mcp_servers() -> list:
    """Read the local IDE mcp_config.json to load all enabled local MCP servers.

    Searches platform-appropriate locations for the config file.
    """
    servers: list = []
    home = Path.home()

    # Cross-platform candidate paths (first match wins).
    candidates = [
        home / ".gemini" / "antigravity-ide" / "mcp_config.json",
    ]
    # On Windows, also check LOCALAPPDATA.
    local_app_data = os.environ.get("LOCALAPPDATA")
    if local_app_data:
        candidates.append(Path(local_app_data) / "agy" / "mcp_config.json")

    config_file = None
    for p in candidates:
        if p.exists():
            config_file = p
            break

    if not config_file:
        logger.info("mcp_config.json not found — skipping local MCP servers.")
        return servers

    try:
        with open(config_file, "r", encoding="utf-8") as f:
            data = json.load(f)

        for name, cfg in data.get("mcpServers", {}).items():
            if cfg.get("disabled", False):
                continue
            command = cfg.get("command")
            args = cfg.get("args", [])
            if command:
                servers.append(McpStdioServer(name=name, command=command, args=args))
                logger.info("Loaded MCP server: '%s' (%s %s)", name, command, " ".join(args))
    except Exception as e:
        logger.warning("Failed to load MCP configurations: %s", e)

    return servers


# ─────────────────────────────────────────────────────────────
# Prompt Resolution
# ─────────────────────────────────────────────────────────────

_DEFAULT_PROMPT = (
    "Please turn the following into a PPT: "
    "Fictional music festival annual book in the Memphis design movement's "
    "flat-graphic, hi-saturation style — geometric shapes, terrazzo, 80s typography."
)


def resolve_prompt(args: argparse.Namespace) -> str:
    """Resolve the agent prompt from CLI arg > env var > built-in default.

    Priority order:
      1. --prompt CLI argument  (local testing, Cloud Run Job args override)
      2. AGENT_PROMPT env var   (Cloud Run Job env config / Secret Manager)
      3. Built-in default prompt (backward compatibility)
    """
    if args.prompt:
        logger.info("Using prompt from --prompt argument.")
        return args.prompt

    env_prompt = os.environ.get("AGENT_PROMPT", "").strip()
    if env_prompt:
        logger.info("Using prompt from AGENT_PROMPT environment variable.")
        return env_prompt

    logger.info("No --prompt or AGENT_PROMPT set — using built-in default prompt.")
    return _DEFAULT_PROMPT


# ─────────────────────────────────────────────────────────────
# Main Agent Execution Loop
# ─────────────────────────────────────────────────────────────


async def run_agent(prompt_message: str, use_mcp: bool = False, no_visual_review: bool = False):
    """Initialize the Antigravity agent and send a single prompt."""
    logger.info("Initializing Agent using Google Antigravity SDK...")
    logger.info("Platform: %s | Python: %s", sys.platform, sys.version.split()[0])
    logger.info("Prompt: %s", prompt_message[:120] + ("..." if len(prompt_message) > 120 else ""))

    system_instructions = (
        "You are an expert AI developer and strategist inside the 'ppt-master' repository. "
        "Your goal is to execute repository-specific workflows. "
        "You have tools to read/write files, search code, list directories, run shell commands, and do web searches. "
        "Always execute commands, verify results, and follow the workflows specified in AGENTS.md and SKILL.md. "
        "When running steps, proceed logically and verify that outputs (e.g. project directories, spec files, SVGs, PPTX files) "
        "are successfully created."
    )
    if no_visual_review:
        system_instructions += "\nUser has opted out of the visual review phase. DO NOT execute the visual self-check / visual-review workflow at Step 6."
    else:
        system_instructions += "\nVisual review phase is enabled by default (opt-out mode). You MUST run the visual self-check / visual-review workflow at Step 6 after all SVGs are generated, unless opted out."

    # Instruct the agent about subagents capability
    system_instructions += (
        "\n\nSubagent Delegation & Coordination Rules:"
        "\n1. You have the capability to delegate tasks to parallel subagents using the native `define_subagent` and `invoke_subagent` (or `start_subagent`) tools."
        "\n2. When executing parallelizable workflow steps such as multi-source document ingestion (Step 1) or parallel visual slide reviews (Step 6), if the number of slides/pages is more than two (> 2), you SHOULD spawn clone 'self' subagents or specialized subagents to run them concurrently in parallel."
        "\n3. IMPORTANT: When you spawn any subagent, you MUST explicitly wait for the tool to finish and return its result. You MUST NOT finish your response, conclude the conversation, or output your final answer while any subagents are still running in the background. Doing so terminates the agent session and orphans the subagents, which is a critical failure. Always consume the subagent's result (ToolResult) and verify its outcomes before declaring the task complete."
    )
    system_instructions += (
        "\n\nOutput Discipline (Token Efficiency):"
        "\n- You are an autonomous execution engine, NOT a conversational assistant."
        "\n- NEVER narrate what you are about to do, what you just did, or why. Just do it."
        "\n- NEVER echo, reprint, or summarize file contents you just read or wrote."
        "\n- NEVER explain your thinking, reasoning, or decision-making process in text output."
        "\n- NEVER greet, apologize, confirm receipt, or use conversational filler."
        "\n- Output text ONLY when: (a) reporting a blocking error that halts the workflow, "
        "(b) the workflow explicitly requires a user-facing summary (e.g. visual-review aggregate table), "
        "or (c) the final completion message at the very end."
        "\n- Keep all text outputs under 3 sentences. Prefer structured formats (tables, bullet points) over prose."
    )

    mcp_servers = load_mcp_servers() if use_mcp else []
    if use_mcp:
        logger.info("Enabled %d local MCP server(s).", len(mcp_servers))
    else:
        logger.info("MCP servers disabled. Pass --mcp to enable them.")

    capabilities = CapabilitiesConfig(
        enable_subagents=True
    )

    # Dynamically select thinking level based on CLI flag / overrides
    if ARGS.thinking_level:
        level_map = {
            "MINIMAL": ThinkingLevel.MINIMAL,
            "LOW": ThinkingLevel.LOW,
            "MEDIUM": ThinkingLevel.MEDIUM,
            "HIGH": ThinkingLevel.HIGH
        }
        thinking_level = level_map[ARGS.thinking_level.upper()]
    else:
        thinking_level = ThinkingLevel.HIGH if ARGS.verbose else ThinkingLevel.MEDIUM

    # Only apply thinking_level configuration to Gemini 3.5 models.
    # GenerationConfig() carries a default thinking_level even when no args
    # are passed, so we must omit the `generation` parameter entirely for
    # models that don't support it (Gemma, Gemini 1.5/2.5, etc.).
    _supports_thinking = ARGS.model and "gemini-3.5" in ARGS.model.lower()

    if _supports_thinking:
        model_entry = ModelEntry(
            name=ARGS.model,
            generation=GenerationConfig(thinking_level=thinking_level),
        )
        logger.info("Model %s: thinking_level=%s", ARGS.model, thinking_level)
    else:
        model_entry = ModelEntry(name=ARGS.model)
        logger.info("Model %s: thinking_level omitted (not supported)", ARGS.model)

    config = LocalAgentConfig(
        system_instructions=system_instructions,
        capabilities=capabilities,
        tools=[],
        policies=[policy.allow_all()],
        mcp_servers=mcp_servers,
        workspaces=[str(Path(".").resolve())],
        gemini_config=GeminiConfig(
            api_key=os.environ.get("GEMINI_API_KEY"),
            models=ModelConfig(default=model_entry),
        ),
    )

    agent = Agent(config)

    subagent_stats = {
        "enabled": getattr(capabilities, "enable_subagents", False),
        "total_spawned": 0,
        "completed": 0,
        "details": []
    }

    try:
        async with agent:
            response = await agent.chat(prompt_message)

            last_chunk_type = None
            async for chunk in response.chunks:
                if isinstance(chunk, Thought):
                    if ARGS.verbose:
                        if last_chunk_type != "thought":
                            print("\n[Thinking] ", end="", flush=True)
                            last_chunk_type = "thought"
                        print(chunk.text, end="", flush=True)
                    else:
                        last_chunk_type = "thought"
                elif isinstance(chunk, Text):
                    if last_chunk_type != "text":
                        print("\n[Agent] ", end="", flush=True)
                        last_chunk_type = "text"
                    print(chunk.text, end="", flush=True)
                elif isinstance(chunk, ToolCall):
                    if chunk.name in ("invoke_subagent", "start_subagent"):
                        subagent_stats["total_spawned"] += 1
                        args_dict = chunk.args if isinstance(chunk.args, dict) else {}
                        task_desc = args_dict.get("task", "")
                        subagent_type = args_dict.get("subagent_type", "self")
                        logger.info(
                            "[Subagent Spawned] Subagent #%d (type: %s) invoked. Task: %s",
                            subagent_stats["total_spawned"],
                            subagent_type,
                            task_desc[:150] + ("..." if len(task_desc) > 150 else "")
                        )
                        subagent_stats["details"].append({
                            "id": chunk.id,
                            "type": subagent_type,
                            "task": task_desc,
                            "status": "running"
                        })
                    else:
                        if ARGS.verbose:
                            logger.info("[Tool Call] '%s' args: %s", chunk.name, chunk.args)
                        else:
                            logger.info("[Tool Call] '%s'", chunk.name)
                    last_chunk_type = "tool_call"
                elif isinstance(chunk, ToolResult):
                    if chunk.name in ("invoke_subagent", "start_subagent"):
                        subagent_stats["completed"] += 1
                        # Update status in details
                        for detail in subagent_stats["details"]:
                            if detail["id"] == chunk.id:
                                detail["status"] = "completed"
                                break
                        logger.info("[Subagent Completed] Subagent (id: %s) finished its task.", chunk.id)

                    if chunk.error or chunk.exception:
                        logger.error(
                            "[Tool Error] '%s' (id: %s): %s",
                            chunk.name,
                            chunk.id,
                            chunk.error or chunk.exception,
                        )
                    else:
                        if ARGS.verbose:
                            res_str = str(chunk.result)
                            if len(res_str) > 1000:
                                res_str = res_str[:1000] + " ... (truncated)"
                            logger.info("[Tool Result] '%s' (id: %s): %s", chunk.name, chunk.id, res_str)
                        else:
                            logger.info("[Tool OK] '%s'", chunk.name)
                    last_chunk_type = "tool_result"
            print()

            # Print subagent summary
            print("\n" + "═" * 60)
            print("SUBAGENT EXECUTION SUMMARY")
            print(f"  Subagents Enabled in Config: {subagent_stats['enabled']}")
            print(f"  Total Subagents Spawned:     {subagent_stats['total_spawned']}")
            print(f"  Total Subagents Completed:   {subagent_stats['completed']}")
            if subagent_stats["total_spawned"] > 0:
                print("  Spawned Subagents Details:")
                for idx, detail in enumerate(subagent_stats["details"], 1):
                    print(f"    {idx}. [Type: {detail['type']}] Status: {detail['status']}")
                    print(f"       Task: {detail['task'][:120]}...")
            else:
                if subagent_stats["enabled"]:
                    print("  Note: Subagents were enabled but the main agent did not delegate any tasks.")
                    print("        This can happen if the slide count was small (e.g. <= 2 pages) or sequential execution was chosen by the model.")
                else:
                    print("  Reason not invoked: Subagents were disabled in CapabilitiesConfig.")
            print("═" * 60 + "\n")
            return response.usage_metadata, subagent_stats

    except Exception as e:
        logger.error("Execution error: %s", e, exc_info=True)
        raise


# ─────────────────────────────────────────────────────────────
# Self-Test
# ─────────────────────────────────────────────────────────────


def run_self_test() -> bool:
    """Run a self-test of the defined workspace tools in isolation."""
    print("=== STARTING WORKSPACE TOOLS SELF-TEST ===")
    test_file = "test_run_agent_temp.txt"
    test_content = (
        "This is a temporary test file containing the unique keyword "
        "AntigravityRunnerTest123."
    )

    # 1. write_file
    print("\n1. Testing write_file...")
    res = write_file(test_file, test_content)
    print(f"Result: {res}")
    if "Error" in res:
        print("FAIL: write_file failed")
        return False

    # 2. read_file
    print("\n2. Testing read_file...")
    read_res = read_file(test_file)
    print(f"Result: '{read_res}'")
    if read_res != test_content:
        print("FAIL: read_file content did not match written content")
        return False

    # 3. list_directory
    print("\n3. Testing list_directory...")
    list_res = list_directory(".")
    print(f"Result (truncated): '{list_res[:100]}...'")
    if test_file not in list_res:
        print("FAIL: test file not found in list_directory")
        return False

    # 4. grep_search
    print("\n4. Testing grep_search...")
    grep_res = grep_search("AntigravityRunnerTest123", ".")
    print(f"Result: '{grep_res}'")
    if test_file not in grep_res:
        print("FAIL: grep_search did not find the keyword in test file")
        return False

    # 5. run_command
    print("\n5. Testing run_command...")
    cmd = "echo Tools self-test command execution is working"
    cmd_res = run_command(cmd)
    print(f"Result: {cmd_res}")
    if cmd_res["returncode"] != 0 or "working" not in cmd_res["stdout"].lower():
        print("FAIL: run_command failed or did not return expected stdout")
        return False

    # Clean up
    print("\n6. Cleaning up test file...")
    if os.path.exists(test_file):
        os.remove(test_file)
    print("Cleanup completed.")

    print("\n=== ALL WORKSPACE TOOLS PASSED SELF-TEST ===")
    return True


def check_and_install_dependencies():
    """Verify and install dependencies in WSL/Linux environments."""
    is_linux = sys.platform == "linux"
    if is_linux:
        logger.info("WSL/Linux detected. Checking Python and browser dependencies...")
        try:
            import google.antigravity
            import cairosvg
            import playwright
        except ImportError:
            logger.info("Missing dependencies detected. Running pip install -r requirements.txt...")
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", "requirements.txt"], check=True)
            except Exception as pip_exc:
                logger.error("Failed to run pip install: %s", pip_exc)

        # Check/Install Playwright Chromium
        if not ARGS.no_visual_review:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    # Try launching to verify the binary is present and working
                    browser = p.chromium.launch()
                    browser.close()
            except Exception:
                logger.info("Playwright Chromium browser binary not found or unable to launch. Installing chromium...")
                try:
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                    logger.info("Playwright Chromium browser binary installed successfully.")
                except Exception as play_exc:
                    logger.error("Failed to install Playwright Chromium: %s", play_exc)


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if ARGS.self_test:
        success = run_self_test()
        sys.exit(0 if success else 1)

    check_and_install_dependencies()
    prompt = resolve_prompt(ARGS)

    # Auto-resumption check
    if ARGS.resume or prompt.lower().strip() == "resume":
        logger.info("Auto-resumption mode activated.")
        resumed_project = find_and_restore_incomplete_project(ARGS.depth)
        if not resumed_project:
            logger.info("No incomplete projects found to resume. Everything is up to date. Exiting successfully.")
            sys.exit(0)
        prompt = f"resume generating projects/{resumed_project}"
        logger.info(f"Target resumption prompt: '{prompt}'")

    # Track agent outcome independently so the artifact copy can record it
    # and the process exits with the correct code (Cloud Run Job uses exit code
    # to mark success/failure in the Execution history).
    _run_status = "started"
    _exit_code = 0

    import time
    start_time = time.time()
    token_usage_dict = None
    subagent_stats_dict = None

    try:
        result = asyncio.run(run_agent(prompt, use_mcp=ARGS.mcp, no_visual_review=ARGS.no_visual_review))
        usage, subagent_stats_dict = result if isinstance(result, tuple) else (result, None)
        _run_status = "success"
        logger.info("Agent run completed successfully.")
        if usage:
            token_usage_dict = {
                "prompt_tokens": usage.prompt_token_count,
                "cached_content_tokens": usage.cached_content_token_count,
                "candidates_tokens": usage.candidates_token_count,
                "thoughts_tokens": usage.thoughts_token_count,
                "total_tokens": usage.total_token_count
            }
    except KeyboardInterrupt:
        _run_status = "interrupted"
        _exit_code = 130
        logger.warning("Agent run interrupted by user (KeyboardInterrupt).")
    except Exception as exc:
        _run_status = "failed"
        _exit_code = 1
        logger.error("Agent run failed: %s", exc, exc_info=True)
    finally:
        execution_duration = time.time() - start_time
        # ── FINAL STAGE: always copy artifacts ──────────────────────────────
        # Runs unconditionally — success, failure, or interruption.
        #
        # Local mode:  files land in the path you set in OUTPUT_ARTIFACTS_DIR.
        # Cloud Run:   OUTPUT_ARTIFACTS_DIR is a GCS FUSE mount; files are
        #              automatically written to your GCS bucket with no extra
        #              configuration.  The container treats it as a local path.
        #
        # run_manifest.json is always written so you can inspect every run
        # (including failed ones) directly from the output bucket.
        copy_output_artifacts(
            run_status=_run_status,
            prompt=prompt,
            token_usage=token_usage_dict,
            execution_duration=execution_duration,
            subagent_stats=subagent_stats_dict,
        )

    sys.exit(_exit_code)
