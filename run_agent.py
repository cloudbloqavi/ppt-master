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
    python run_agent.py [--mcp] [--self-test] [--prompt "Your prompt here"]

Options:
    --mcp            Enable loading local MCP servers from mcp_config.json.
    --self-test      Run self-test of the custom tools in isolation (no API key needed).
    --prompt <text>  The prompt to send to the agent. Overrides AGENT_PROMPT env var.

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

# ─────────────────────────────────────────────────────────────
# SDK Imports (deferred so protobuf env is set first)
# ─────────────────────────────────────────────────────────────

try:
    from google.antigravity import Agent, LocalAgentConfig, GeminiConfig
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
            if any(part in file_path.parts for part in ("node_modules", "icons", "__pycache__")):
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

    source = Path(".").resolve() / "core-ppt-master-engine" / "projects"
    destination = Path(output_dir_str)
    timestamp_utc = datetime.now(timezone.utc).isoformat()

    logger.info("")
    logger.info("═" * 60)
    logger.info("ARTIFACT COPY STAGE")
    logger.info("  Source dir:      %s", source)
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

    if source.exists() and any(source.iterdir()):
        for item in source.rglob("*"):
            if item.is_file():
                rel = item.relative_to(source)
                dest_file = destination / rel
                try:
                    dest_file.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(item, dest_file)
                    copied += 1
                except Exception as exc:
                    msg = f"{rel}: {exc}"
                    copy_errors.append(msg)
                    logger.error("  Copy error — %s", msg)
        logger.info("  Files copied: %d", copied)
        if copy_errors:
            logger.warning("  Copy errors:  %d file(s) failed", len(copy_errors))
    else:
        logger.info("  No project output files found in source — skipping file copy.")

    # ── Write run manifest ───────────────────────────────────
    # Always written so the output bucket has a record of every run,
    # including failed ones with 0 copied files.
    manifest = {
        "run_status": run_status,
        "timestamp_utc": timestamp_utc,
        "prompt": prompt[:500] if prompt else "",
        "source_projects_dir": str(source),
        "output_artifacts_dir": str(destination),
        "files_copied": copied,
        "copy_errors": copy_errors,
    }
    manifest_path = destination / "run_manifest.json"
    try:
        manifest_path.write_text(_json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
        logger.info("  Manifest written: %s", manifest_path)
    except Exception as exc:
        logger.error("  Failed to write run manifest: %s", exc)

    logger.info("ARTIFACT COPY STAGE COMPLETE")
    logger.info("═" * 60)
    logger.info("")


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


async def run_agent(prompt_message: str, use_mcp: bool = False):
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

    mcp_servers = load_mcp_servers() if use_mcp else []
    if use_mcp:
        logger.info("Enabled %d local MCP server(s).", len(mcp_servers))
    else:
        logger.info("MCP servers disabled. Pass --mcp to enable them.")

    config = LocalAgentConfig(
        system_instructions=system_instructions,
        tools=[],
        policies=[policy.allow_all()],
        mcp_servers=mcp_servers,
        workspaces=[str(Path(".").resolve())],
        gemini_config=GeminiConfig(
            api_key=os.environ.get("GEMINI_API_KEY")
        ),
        model="gemini-3.5-flash",
    )

    agent = Agent(config)

    try:
        async with agent:
            response = await agent.chat(prompt_message)

            last_chunk_type = None
            async for chunk in response.chunks:
                if isinstance(chunk, Thought):
                    if last_chunk_type != "thought":
                        print("\n[Thinking] ", end="", flush=True)
                        last_chunk_type = "thought"
                    print(chunk.text, end="", flush=True)
                elif isinstance(chunk, Text):
                    if last_chunk_type != "text":
                        print("\n[Agent] ", end="", flush=True)
                        last_chunk_type = "text"
                    print(chunk.text, end="", flush=True)
                elif isinstance(chunk, ToolCall):
                    logger.info("[Tool Call] '%s' args: %s", chunk.name, chunk.args)
                    last_chunk_type = "tool_call"
                elif isinstance(chunk, ToolResult):
                    res_str = str(chunk.result)
                    if len(res_str) > 1000:
                        res_str = res_str[:1000] + " ... (truncated)"
                    if chunk.error or chunk.exception:
                        logger.error(
                            "[Tool Error] '%s' (id: %s): %s",
                            chunk.name,
                            chunk.id,
                            chunk.error or chunk.exception,
                        )
                    else:
                        logger.info("[Tool Result] '%s' (id: %s): %s", chunk.name, chunk.id, res_str)
                    last_chunk_type = "tool_result"
            print()

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


# ─────────────────────────────────────────────────────────────
# Entry point
# ─────────────────────────────────────────────────────────────

if __name__ == "__main__":
    if ARGS.self_test:
        success = run_self_test()
        sys.exit(0 if success else 1)

    prompt = resolve_prompt(ARGS)

    # Track agent outcome independently so the artifact copy can record it
    # and the process exits with the correct code (Cloud Run Job uses exit code
    # to mark success/failure in the Execution history).
    _run_status = "started"
    _exit_code = 0

    try:
        asyncio.run(run_agent(prompt, use_mcp=ARGS.mcp))
        _run_status = "success"
        logger.info("Agent run completed successfully.")
    except KeyboardInterrupt:
        _run_status = "interrupted"
        _exit_code = 130
        logger.warning("Agent run interrupted by user (KeyboardInterrupt).")
    except Exception as exc:
        _run_status = "failed"
        _exit_code = 1
        logger.error("Agent run failed: %s", exc, exc_info=True)
    finally:
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
        copy_output_artifacts(run_status=_run_status, prompt=prompt)

    sys.exit(_exit_code)
