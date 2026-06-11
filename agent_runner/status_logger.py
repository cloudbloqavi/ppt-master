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

# Active tool call tracking to match ToolCall to ToolResult
_active_tool_calls: dict[str, dict[str, Any]] = {}


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


def _get_project_dir_from_path(file_path: str) -> Path | None:
    """Extracts the active project directory from a file path."""
    path_str = file_path
    if path_str.startswith("file:///"):
        path_str = path_str[8:]
        if len(path_str) > 2 and path_str[1] == ':' and path_str[0] == '/':
            path_str = path_str[1:]
            
    p = Path(path_str).resolve()
    
    # If the file itself is spec_lock.md or design_spec.md, its parent is the project dir
    if p.name in ("spec_lock.md", "design_spec.md"):
        return p.parent
        
    # If the file is inside a subdirectory of the project (like svg_output, svg_final, etc.)
    # then its grandparent is the project dir.
    parent_name = p.parent.name
    if parent_name in ("svg_output", "svg_final", "images", "sources", "notes", "backup", "exports"):
        return p.parent.parent
        
    # Fallback to current working directory if it contains spec_lock.md
    cwd = Path(".").resolve()
    if (cwd / "spec_lock.md").exists():
        return cwd
        
    return None



def _get_page_rhythm_from_spec_lock(project_dir: Path) -> list[str]:
    """Reads spec_lock.md and parses page_rhythm to compute total slides."""
    spec_lock_path = project_dir / "spec_lock.md"
    if not spec_lock_path.exists():
        return []
    
    pages = []
    try:
        with open(spec_lock_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
        
        in_page_rhythm = False
        for line in lines:
            line_strip = line.strip()
            if line_strip.startswith("## page_rhythm"):
                in_page_rhythm = True
                continue
            elif line_strip.startswith("##") and in_page_rhythm:
                in_page_rhythm = False
                break
            
            if in_page_rhythm:
                if line_strip.startswith("-"):
                    parts = line_strip[1:].split(":")
                    if parts:
                        page_id = parts[0].strip()
                        page_id = page_id.lstrip("-").strip()
                        if page_id:
                            pages.append(page_id)
    except Exception as e:
        logger.warning("Failed to parse spec_lock.md page_rhythm: %s", e)
    
    return pages


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
    if not chunk or not hasattr(chunk, "name") or not hasattr(chunk, "id"):
        return
        
    # Track the active tool call for ToolResult matching
    _active_tool_calls[chunk.id] = {
        "name": chunk.name,
        "args": chunk.args
    }

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
            log_status("Verifying SVG syntax and style rules for generated slides...")
        elif "visual_review.py" in cmd:
            log_status("Rendering visual review previews...")
        elif "total_md_split.py" in cmd:
            log_status("Aligning and splitting speaker notes to individual slides...")
        elif "finalize_svg.py" in cmd:
            log_status("Optimizing slide SVG files and embedding font/icon assets...")
        elif "svg_to_pptx.py" in cmd:
            log_status("Assembling and exporting final slides into native PowerPoint format (.pptx)...")
            
    elif chunk.name in ("write_file", "edit_file", "write_to_file", "replace_file_content", "multi_replace_file_content"):
        file_path = ""
        if isinstance(chunk.args, dict):
            file_path = (
                chunk.args.get("filePath") or 
                chunk.args.get("file_path") or 
                chunk.args.get("TargetFile") or 
                chunk.args.get("target_file") or 
                ""
            )
        elif isinstance(chunk.args, str):
            file_path = chunk.args
            
        if not file_path:
            return
            
        # Clean up file:/// prefix
        if file_path.startswith("file:///"):
            file_path = file_path[8:]
            if len(file_path) > 2 and file_path[1] == ':' and file_path[0] == '/':
                file_path = file_path[1:]

        file_path_norm = file_path.replace("\\", "/")
        
        # Detect slide SVG writing
        if "svg_output/" in file_path_norm and file_path_norm.endswith(".svg"):
            try:
                filename = Path(file_path).name
                slide_name = Path(file_path).stem
                project_dir = _get_project_dir_from_path(file_path)
                slide_num = None
                total_pages = None
                
                import re
                match = re.search(r'(?:^|slide_|P|p|slide)(\d+)', filename)
                if match:
                    slide_num = int(match.group(1))
                
                if project_dir:
                    pages = _get_page_rhythm_from_spec_lock(project_dir)
                    if pages:
                        total_pages = len(pages)
                        
                if slide_num is not None and total_pages is not None:
                    log_status(f"Designing slide {slide_num} of {total_pages} ({filename})...")
                else:
                    formatted_slide_name = slide_name.replace("_", " ").title()
                    log_status(f"Designing visual layout and content for {formatted_slide_name}...")
            except Exception as e:
                logger.warning("Failed to parse slide number or total pages: %s", e)
                log_status("Designing visual layout for next slide...")
                
        elif "svg_final/" in file_path_norm and file_path_norm.endswith(".svg"):
            try:
                filename = Path(file_path).name
                slide_name = Path(file_path).stem
                project_dir = _get_project_dir_from_path(file_path)
                slide_num = None
                total_pages = None
                
                import re
                match = re.search(r'(?:^|slide_|P|p|slide)(\d+)', filename)
                if match:
                    slide_num = int(match.group(1))
                
                if project_dir:
                    pages = _get_page_rhythm_from_spec_lock(project_dir)
                    if pages:
                        total_pages = len(pages)
                        
                if slide_num is not None and total_pages is not None:
                    log_status(f"Optimizing styles and embedding icons for slide {slide_num} of {total_pages} ({filename})...")
                else:
                    formatted_slide_name = slide_name.replace("_", " ").title()
                    log_status(f"Optimizing visual layout for {formatted_slide_name}...")
            except Exception as e:
                logger.warning("Failed to parse slide finalization info: %s", e)
                log_status("Optimizing styles and layout for next slide...")
                
        elif "design_spec.md" in file_path_norm:
            log_status("Drafting design specification and structural outline...")
        elif "spec_lock.md" in file_path_norm:
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
        # Detect parallel subagents and check task description
        task_desc = ""
        if isinstance(chunk.args, dict):
            task_desc = chunk.args.get("task") or chunk.args.get("Task") or ""
            
        if task_desc:
            task_desc_lower = task_desc.lower()
            if "visual" in task_desc_lower or "rubric" in task_desc_lower or "self-check" in task_desc_lower:
                log_status("Spawning a parallel subagent to perform visual review on slides...")
            elif "pdf_to_md" in task_desc_lower or "web_to_md" in task_desc_lower or "doc_to_md" in task_desc_lower or "convert" in task_desc_lower:
                log_status("Spawning a parallel subagent to convert and ingest source content...")
            else:
                log_status("Spawning a parallel subagent to accelerate task execution...")
        else:
            log_status("Spawning a parallel subagent to accelerate task execution...")


def _check_tool_result_for_status(chunk: Any):
    """Parses tool results to detect and log outcomes of key pipeline steps."""
    if not chunk or not hasattr(chunk, "name") or not hasattr(chunk, "id"):
        return
        
    tool_call = _active_tool_calls.pop(chunk.id, None)
    if not tool_call:
        return
        
    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    is_error = bool(chunk.error or chunk.exception)
    
    if tool_name == "run_command":
        cmd = ""
        if isinstance(tool_args, dict):
            cmd = tool_args.get("command") or tool_args.get("CommandLine") or ""
        elif isinstance(tool_args, str):
            cmd = tool_args
            
        if not cmd:
            return
            
        returncode = None
        if isinstance(chunk.result, dict):
            returncode = chunk.result.get("returncode")
        elif isinstance(chunk.result, str):
            try:
                res_data = json.loads(chunk.result)
                returncode = res_data.get("returncode")
            except Exception:
                pass
                
        failed = is_error or (returncode is not None and returncode != 0)
        
        if "pdf_to_md.py" in cmd or "web_to_md.py" in cmd or "ppt_to_md.py" in cmd or "doc_to_md.py" in cmd or "excel_to_md.py" in cmd:
            if failed:
                log_status("Source content conversion failed.")
            else:
                log_status("Source content successfully converted to editable Markdown.")
        elif "project_manager.py init" in cmd or "project_manager.py import-sources" in cmd:
            if failed:
                log_status("Project initialization / import failed.")
            else:
                log_status("Project workspace successfully initialized.")
        elif "svg_quality_checker.py" in cmd:
            if failed:
                log_status("Slide quality check completed: identified formatting/visual errors that need correction.")
            else:
                log_status("Slide quality check completed successfully: all SVGs verified.")
        elif "image_gen.py" in cmd:
            if failed:
                log_status("AI image generation failed or encountered errors.")
            else:
                log_status("AI images generated successfully.")
        elif "latex_render.py" in cmd:
            if failed:
                log_status("LaTeX mathematical formula rendering encountered errors.")
            else:
                log_status("LaTeX mathematical formulas rendered successfully.")
        elif "visual_review.py" in cmd:
            if failed:
                log_status("Visual review rendering encountered errors.")
            else:
                log_status("Visual reviews generated successfully.")
        elif "finalize_svg.py" in cmd:
            if failed:
                log_status("SVG post-processing optimization failed.")
            else:
                log_status("SVG post-processing completed: embedded icons and optimized layout styles.")
        elif "svg_to_pptx.py" in cmd:
            if failed:
                log_status("PowerPoint presentation assembly and export failed.")
            else:
                log_status("PowerPoint presentation (.pptx) successfully assembled and exported!")

