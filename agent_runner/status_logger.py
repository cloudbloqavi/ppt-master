"""
Status Progress Logging & Pub/Sub Adapter Module for PPT Master Agent Runner

Handles user-facing, non-technical status progress logging, either to a local
text log file during local testing or publishing to GCP Pub/Sub in production.
Includes interceptors to parse text outputs and tool calls.
"""
import os
import json
from pathlib import Path
from datetime import datetime
from typing import Any
from agent_runner.config import ARGS, logger

# Global track of the active status progress log file path.
_STATUS_LOG_FILE_PATH: Path | None = None
_STATUS_LOGGER: Any = None
_last_status: str | None = None


class StatusProgressLogger:
    """Adapter class for status progress updates.

    Handles both local testing behavior (writing to a date-time based log file
    when --status-progress is provided) and production behavior (publishing to
    GCP Pub/Sub automatically without a CLI flag).

    Local Testing vs. Production Behavior:
    - Local Testing: Logs are formatted and saved to a file in OUTPUT_ARTIFACTS_DIR
      with a date-time based name format consistent with existing logs.
    - Production: Logs are published to the designated GCP Pub/Sub topic to be
      consumed by downstream services or user-facing UIs automatically.
    """
    def __init__(self, file_path: Path | None = None, pubsub_topic: str | None = None):
        """Initialize the logger.

        Args:
            file_path: Optional Path to the local status progress log file.
            pubsub_topic: Optional GCP Pub/Sub topic string.
        """
        self.file_path = file_path
        self.pubsub_topic = pubsub_topic or os.environ.get("STATUS_PUBSUB_TOPIC")
        self.pubsub_client = None

        # Try to resolve default topic in production Cloud Run environments if not set
        if not self.pubsub_topic and "K_SERVICE" in os.environ:
            project_id = os.environ.get("GCP_PROJECT") or os.environ.get("GOOGLE_CLOUD_PROJECT")
            if project_id:
                self.pubsub_topic = f"projects/{project_id}/topics/status-progress"

        # Initialize Pub/Sub client if a topic is targetable
        if self.pubsub_topic:
            try:
                from google.cloud import pubsub_v1
                self.pubsub_client = pubsub_v1.PublisherClient()
                logger.info("Initialized Pub/Sub publisher for topic: %s", self.pubsub_topic)
            except ImportError:
                logger.warning(
                    "google-cloud-pubsub package not found. Status updates "
                    "cannot be published to Pub/Sub."
                )
            except Exception as e:
                logger.warning("Failed to initialize Pub/Sub publisher client: %s", e)

    def log_status(self, status_message: str):
        """Logs a status update.

        If a file path is configured, writes to the local log file.
        In production, publishes the status to the configured GCP Pub/Sub topic.
        """
        timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        formatted_message = f"[{timestamp}] {status_message}\n"

        # 1. Local logging (Testing / file_path provided)
        if self.file_path:
            try:
                with open(self.file_path, "a", encoding="utf-8") as f:
                    f.write(formatted_message)
            except Exception as e:
                logger.warning("Failed to write to status progress log file: %s", e)

        # 2. Production GCP Pub/Sub publishing
        if self.pubsub_client and self.pubsub_topic:
            try:
                data = json.dumps({
                    "timestamp": timestamp,
                    "status": status_message
                }).encode("utf-8")
                self.pubsub_client.publish(self.pubsub_topic, data)
            except Exception as e:
                logger.warning("Failed to publish status progress to Pub/Sub: %s", e)


def setup_status_logging():
    """Configure status progress logging based on CLI args and environment."""
    global _STATUS_LOG_FILE_PATH, _STATUS_LOGGER

    # Status progress updates run automatically in production (Cloud Run),
    # or locally when the CLI flag is passed or Pub/Sub is configured.
    is_production = "K_SERVICE" in os.environ
    opt_in = ARGS.status_progress
    has_pubsub_env = "STATUS_PUBSUB_TOPIC" in os.environ

    if not (opt_in or is_production or has_pubsub_env):
        return

    file_path = None
    if opt_in:
        output_dir = os.environ.get("OUTPUT_ARTIFACTS_DIR") or "."
        try:
            output_path = Path(output_dir)
            output_path.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = output_path / f"status_progress_{timestamp}.log"
            _STATUS_LOG_FILE_PATH = file_path
            logger.info("Writing status progress updates to: %s", file_path)
        except Exception as e:
            logger.warning("Failed to configure status progress log file: %s", e)

    _STATUS_LOGGER = StatusProgressLogger(file_path=file_path)


def log_status(message: str):
    """Log a unique status message to the status progress channels."""
    global _last_status
    if message == _last_status:
        return
    _last_status = message
    if _STATUS_LOGGER:
        _STATUS_LOGGER.log_status(message)
    # Always print to stdout/stderr so logs reflect the progress
    logger.info("[Status Progress] %s", message)


def get_status_log_file_path() -> Path | None:
    """Return the path to the active status progress log file."""
    return _STATUS_LOG_FILE_PATH


def _check_text_for_status(text: str):
    """Parses agent text outputs to detect role switches or phase checkpoints."""
    if not text:
        return
    # Role Switches: ## [Role Switch: <Role Name>]
    if "## [Role Switch:" in text:
        try:
            role = text.split("## [Role Switch:")[1].split("]")[0].strip()
            log_status(f"Switched agent role to: {role}.")
        except Exception:
            pass
    # Step checkpoints in SKILL.md:
    elif "## ✅ Strategist Phase Complete" in text:
        log_status("Strategist Phase completed: Visual design specs and content outline locked.")
    elif "## ✅ Image Acquisition Phase Complete" in text:
        log_status("Image Acquisition Phase completed: Required custom visuals generated.")
    elif "## ✅ Executor Phase Complete" in text:
        log_status("Executor Phase completed: Visual slide layouts constructed.")


def _check_tool_call_for_status(chunk: Any):
    """Parses tool calls to detect and log key pipeline actions."""
    if chunk.name == "run_command":
        cmd = ""
        # Inspect arguments depending on shape/type
        if isinstance(chunk.args, dict):
            cmd = chunk.args.get("command") or chunk.args.get("CommandLine") or ""
        elif isinstance(chunk.args, str):
            cmd = chunk.args
            
        if not cmd:
            return
            
        # Match commands against key scripts in the pipeline
        if "pdf_to_md.py" in cmd:
            log_status("Converting source PDF document to editable Markdown format...")
        elif "doc_to_md.py" in cmd:
            log_status("Converting source Word/text document to editable Markdown format...")
        elif "excel_to_md.py" in cmd:
            log_status("Converting source Excel workbook to editable Markdown format...")
        elif "ppt_to_md.py" in cmd:
            log_status("Converting source PowerPoint presentation to editable Markdown format...")
        elif "web_to_md.py" in cmd:
            log_status("Converting source web URL to editable Markdown format...")
        elif "project_manager.py init" in cmd:
            log_status("Initializing new presentation project workspace...")
        elif "project_manager.py import-sources" in cmd:
            log_status("Importing converted source files and assets into project workspace...")
        elif "latex_render.py" in cmd:
            log_status("Rendering LaTeX mathematical equations to high-resolution images...")
        elif "analyze_images.py" in cmd:
            log_status("Analyzing imported image dimensions and color schemes...")
        elif "image_gen.py" in cmd:
            log_status("Generating tailored AI images for the presentation slides...")
        elif "svg_quality_checker.py" in cmd:
            log_status("Checking generated slide SVGs for formatting, visual issues, and errors...")
        elif "total_md_split.py" in cmd:
            log_status("Splitting speaker notes and aligning them to individual slides...")
        elif "finalize_svg.py" in cmd:
            log_status("Running post-processing on SVGs: embedding icons and optimizing styles...")
        elif "svg_to_pptx.py" in cmd:
            log_status("Assembling and exporting final slides into native PowerPoint format (.pptx)...")
            
    elif chunk.name == "write_file":
        file_path = ""
        if isinstance(chunk.args, dict):
            file_path = chunk.args.get("file_path") or chunk.args.get("TargetFile") or ""
        elif isinstance(chunk.args, str):
            file_path = chunk.args
            
        if not file_path:
            return
            
        # Detect slide SVG writing
        if "svg_output/" in file_path and file_path.endswith(".svg"):
            try:
                slide_name = Path(file_path).stem
                # Convert slide_1 to 'Slide 1'
                formatted_slide_name = slide_name.replace("_", " ").title()
                log_status(f"Designing visual layout and content for {formatted_slide_name}...")
            except Exception:
                log_status("Designing visual layout for next slide...")
        elif "design_spec.md" in file_path:
            log_status("Drafting design specification and structural outline...")
        elif "spec_lock.md" in file_path:
            log_status("Creating visual parameter lock for page layout construction...")
            
    elif "search" in chunk.name.lower():
        query = ""
        if isinstance(chunk.args, dict):
            query = chunk.args.get("query") or chunk.args.get("Query") or chunk.args.get("q") or ""
        if query:
            log_status(f"Performing web search and research on: '{query}'...")
        else:
            log_status("Searching the web for relevant background materials...")
            
    elif "read_url" in chunk.name.lower() or "web_fetch" in chunk.name.lower() or "read_browser" in chunk.name.lower() or "fetch" in chunk.name.lower():
        url = ""
        if isinstance(chunk.args, dict):
            url = chunk.args.get("url") or chunk.args.get("Url") or ""
        if url:
            log_status(f"Fetching and reading content from URL: '{url}'...")
        else:
            log_status("Fetching content from external URL...")
            
    elif chunk.name == "browser_subagent":
        task = ""
        if isinstance(chunk.args, dict):
            task = chunk.args.get("Task") or chunk.args.get("task") or ""
        if task:
            log_status(f"Running browser subagent task: {task}...")
        else:
            log_status("Running browser agent to gather web materials...")

    elif chunk.name in ("invoke_subagent", "start_subagent"):
        # Detect parallel subagents
        log_status("Spawning a parallel subagent to accelerate task execution...")
