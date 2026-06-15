"""
Status Progress Logging & Pub/Sub Adapter Module for Presentation Builder Agent Runner

Handles user-facing, non-technical status progress logging, either to a local
text log file during local testing or publishing to GCP Pub/Sub in production.
Includes interceptors to parse text outputs and tool calls.
"""
import os
import re
import json
from pathlib import Path
from datetime import datetime
from typing import Any
from agent_runner.config import ARGS, logger

# Global track of the active status progress log file path.
_STATUS_LOG_FILE_PATH: Path | None = None
_STATUS_LOGGER: Any = None
_last_status: str | None = None
# Stable per-run id stamped onto every streamed event so the production consumer
# (Pub/Sub → Firestore → frontend) can scope events to the right presentation job.
_RUN_ID: str | None = None

# Active tool call tracking to match ToolCall to ToolResult
_active_tool_calls: dict[str, dict[str, Any]] = {}

# ── Per-slide progress tracking (call-driven) ────────────────────────────────
# This SDK does NOT emit ToolResult chunks, so slide "ready" events cannot be
# driven off tool results. Instead we infer them from the tool-CALL stream: a
# slide is "ready" once the agent moves on to the next slide (or once finalize/
# export begins). This state lets us pair each "Designing slide N" with a later
# "Slide N is ready", de-duplicate repeat edits, and surface polish passes as
# "Refining slide N".
_designed_slides: set[int] = set()      # slide numbers announced as "Designing"
_ready_slides: set[int] = set()         # slide numbers already announced "ready"
_current_slide: int | None = None       # slide whose SVG was most recently written
_total_pages_seen: int | None = None     # last known total page count (from spec_lock)
_slide_names: dict[int, str] = {}        # slide_num -> display name (ready w/o total)

# ── Native web-research (Google Search grounding) tracking ───────────────────
# This harness performs web research via native Google Search grounding rather
# than an explicit search tool, so the only trace of it is in the model's
# "thought" stream. The state below lets us surface that research to the user.
_research_topic: str | None = None          # clean topic derived from the prompt
_research_started: bool = False             # have we announced research yet?
_thought_accum: str = ""                    # accumulated thought text (deltas)
_text_accum: str = ""                       # accumulated agent text (deltas)
_seen_research_headers: set[str] = set()     # dedup of reasoning section headers
_research_headers_emitted: int = 0           # count surfaced (capped)
_emitted_source_keys: set[str] = set()       # domains already streamed as citation events (idempotent)
_sources_parsed: bool = False                # manifest already parsed (stop re-scanning)
_thought_scan_pos: int = 0                   # high-water mark scanned in _thought_accum
_text_scan_pos: int = 0                       # high-water mark scanned in _text_accum
_seen_text_markers: set[str] = set()          # phase/step/role checkpoints already emitted
_emitted_once: set[str] = set()               # run_command lines capped to one emit per run

# ── Tunable knobs (env-overridable so they can be readjusted without code) ────
def _env_int(name: str, default: int, minimum: int = 0) -> int:
    """Read a non-negative integer tuning knob from the environment.

    Falls back to ``default`` when unset, non-numeric, or below ``minimum`` —
    a bad value must never crash status logging.
    """
    raw = os.environ.get(name)
    if raw is None:
        return default
    try:
        val = int(str(raw).strip())
    except (TypeError, ValueError):
        logger.warning("Invalid %s=%r; using default %d.", name, raw, default)
        return default
    if val < minimum:
        logger.warning("%s=%d below minimum %d; using %d.", name, val, minimum, minimum)
        return minimum
    return val


# Max number of research sub-topic headers surfaced from reasoning per run.
_MAX_RESEARCH_HEADERS = _env_int("STATUS_MAX_RESEARCH_HEADERS", 8)
# Overlap (chars) re-scanned at the tail of the thought buffer on each delta so a
# pattern split across a streaming boundary is still matched. Must exceed the
# longest pattern we incrementally scan for (a `**Header**` is capped at ~64
# chars; URLs are longer, hence the generous default). Dedup makes re-matches
# inside the overlap harmless, so larger only costs a little CPU.
_SCAN_OVERLAP = _env_int("STATUS_SCAN_OVERLAP_CHARS", 1024, minimum=64)

# Marker the agent prints before its machine-readable citation manifest (see
# system_instructions.md "Research Source Citations").
_RESEARCH_SOURCES_MARKER = "[[RESEARCH_SOURCES]]"

# Domains that are never real research citations (schema/spec/loopback noise).
_NON_CITATION_DOMAINS = frozenset({
    "w3.org", "www.w3.org", "localhost", "127.0.0.1", "schema.org",
    "example.com", "example.org",
})

# Full-URL matcher used to harvest citations that appear only in the model's
# reasoning (native Google Search grounding surfaces some domains nowhere else).
_URL_RE = re.compile(r'https?://[^\s\'"<>)\]]+')

# Technical/internal query patterns that should NOT appear in user-facing status
# progress logs. These are SVG/XML/CSS terms the model searches for during
# internal slide construction, not user-facing research.
_INTERNAL_QUERY_PATTERNS = frozenset({
    "tspan", "manifest", "data-icon", "viewbox", "lineargradient",
    "foreignobject", "clippath", "xmlns", "svg", "rect", "polygon",
    "polyline", "defs", "use xlink", "fecolormatrix", "feblend",
    "feturbulence", "fegaussianblur", "flood-color", "stop-color",
    "stroke-dasharray", "stroke-linecap", "font-face", "glyph",
    "textpath", "animatetransform", "marker-end", "xlink:href",
    "preserveaspectratio", "fill-rule", "clip-rule", "dominant-baseline",
    "text-anchor", "font-weight", "letter-spacing", "rgba",
    "radialGradient", "radialgradient", "lineargradient",
    "stop-opacity", "gradientunits", "gradienttransform",
})

# Technical file extensions that should be suppressed in searches
_TECHNICAL_EXTENSIONS = frozenset({
    ".svg", ".json", ".xml", ".css", ".js", ".html", ".md", ".py", ".sh", ".txt"
})

# General design/code keywords that indicate internal helper queries rather than topic research
_TECHNICAL_KEYWORDS = frozenset({
    "filename", "path", "directory", "code", "class=", "id=", "srcrect", "rx/ry",
    "transform", "translate", "rotate", "scale", "viewbox", "rect", "circle", "ellipse",
    "line", "polyline", "polygon", "path", "text", "tspan", "defs", "g id=", "g transform=",
    "powerpoint", "layout", "template", "slide outline", "slide specifications"
})


# Builtin / local tools that operate on the local workspace (files, shell, code
# search). These must NEVER be reported as user-facing "web research". In this
# SDK `search_directory` is grep over the repository — not a web search — so it
# (and its aliases in other IDEs) must be excluded from research status updates.
_LOCAL_TOOL_NAMES = frozenset({
    "search_directory", "find_file", "view_file", "list_directory",
    "create_file", "edit_file", "run_command", "ask_question",
    "finish", "generate_image", "start_subagent", "invoke_subagent",
    # aliases used by other agentic SDKs / IDEs
    "grep", "grep_search", "ripgrep", "glob", "file_search",
    "codebase_search", "read_file", "write_file", "write_to_file",
    "replace_file_content", "multi_replace_file_content", "search_replace",
    "search_files", "search_symbols", "find_filepath",
})

# Substrings that positively identify a genuine *web* search tool (e.g. provided
# by an MCP server). Only tools matching these may emit "Researching:" updates.
_WEB_SEARCH_HINTS = (
    "web_search", "search_web", "google_search", "googlesearch", "websearch",
    "web.search", "bing", "serpapi", "serp_", "tavily", "brave_search",
    "duckduckgo", "exa_search", "perplexity",
)

# Phrases in the model's reasoning that signal native Google Search grounding is
# happening (since it never surfaces as a tool call).
_RESEARCH_SIGNAL_KEYWORDS = (
    "ground truth", "fresh ground", "web search", "my search", "searched the web",
    "search pinpointed", "grounding", "search results", "i searched",
    "according to this data", "search mandate", "grounded fact", "latest news",
)

# Reasoning section headers that are internal/technical, not topic research.
# Headers containing any of these substrings are suppressed from status output.
_INTERNAL_HEADER_KEYWORDS = (
    "project", "directory", "pathing", "path", "locat", "file", "rules",
    "command", "script", "parser", "svg", "template", "folder", "slug",
    "import", "manifest", "workflow", "pipeline", "clarif", "structuring the",
    "prioritizing search", "spec", "render", "executor", "strategist", "outline",
)


def _is_web_search_tool(name: str) -> bool:
    """True only for genuine web-search tools, never local grep/file tools.

    Prevents local tools like `search_directory` (grep) from being misreported
    as user-facing web research.
    """
    if not name:
        return False
    n = name.lower()
    if n in _LOCAL_TOOL_NAMES:
        return False
    if any(hint in n for hint in _WEB_SEARCH_HINTS):
        return True
    # A generic "search" tool qualifies only when clearly web-oriented.
    if "search" in n and any(w in n for w in ("web", "internet", "online")):
        return True
    return False


def _is_internal_query(query: str) -> bool:
    """Check if a search query is an internal technical lookup, not user-facing research."""
    q_lower = query.strip().lower()
    if not q_lower:
        return True

    # Check for technical extensions
    if any(ext in q_lower for ext in _TECHNICAL_EXTENSIONS):
        return True

    # Check for technical keywords
    if any(kw in q_lower for kw in _TECHNICAL_KEYWORDS):
        return True

    # Use word boundary matching for internal query patterns
    words = re.findall(r'\b\w+\b', q_lower)
    if any(word in _INTERNAL_QUERY_PATTERNS for word in words):
        return True

    return False


def _get_result_text(chunk: Any) -> str:
    """Extract text content from a ToolResult chunk, regardless of attribute name."""
    for attr in ("result", "output", "content", "text"):
        val = getattr(chunk, attr, None)
        if val is not None:
            return str(val)
    return str(chunk)


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

    def log_status(self, status_message: str, event_type: str = "progress",
                   payload: dict | None = None):
        """Logs a status update.

        If a file path is configured, writes to the local log file.
        In production, publishes the status to the configured GCP Pub/Sub topic.

        Args:
            status_message: Human-readable status line (file feed + frontend display).
            event_type: Discriminator for the consumer — "progress" or "citation".
                Citation events are additive deltas (one per source, deduped by
                domain upstream), so a domain-keyed Firestore upsert is idempotent
                under Pub/Sub at-least-once redelivery and out-of-order arrival.
            payload: Optional structured fields (e.g. {name, url, domain}) published
                under "data" so the frontend need not parse the human string.
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
                event = {
                    "timestamp": timestamp,
                    "status": status_message,
                    "event_type": event_type,
                }
                if _RUN_ID:
                    event["run_id"] = _RUN_ID
                if payload:
                    event["data"] = payload
                data = json.dumps(event).encode("utf-8")
                self.pubsub_client.publish(self.pubsub_topic, data)
            except Exception as e:
                logger.warning("Failed to publish status progress to Pub/Sub: %s", e)


def setup_status_logging():
    """Configure status progress logging based on CLI args and environment."""
    global _STATUS_LOG_FILE_PATH, _STATUS_LOGGER, _RUN_ID

    # Stable per-run id for streamed events: prefer an explicit env id, then the
    # Cloud Run execution name, else a timestamp. Lets the frontend group all
    # events (incl. citations) under the correct presentation job.
    _RUN_ID = (
        os.environ.get("RUN_ID")
        or os.environ.get("CLOUD_RUN_EXECUTION")
        or datetime.now().strftime("run_%Y%m%d_%H%M%S")
    )

    # Status progress updates run automatically in production (Cloud Run),
    # or locally when the CLI flag is passed or Pub/Sub is configured.
    is_production = "K_SERVICE" in os.environ
    opt_in = ARGS.status_progress
    has_pubsub_env = "STATUS_PUBSUB_TOPIC" in os.environ

    if not (opt_in or is_production or has_pubsub_env):
        return

    file_path = None
    if opt_in:
        try:
            # Share the same per-run subfolder as the execution log so neither
            # file is ever written to the shared OUTPUT_ARTIFACTS_DIR root.
            from agent_runner.logging_setup import get_run_log_dir
            output_path = get_run_log_dir()
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            file_path = output_path / f"status_progress_{timestamp}.log"
            _STATUS_LOG_FILE_PATH = file_path
            logger.info("Writing status progress updates to: %s", file_path)
        except Exception as e:
            logger.warning("Failed to configure status progress log file: %s", e)

    _STATUS_LOGGER = StatusProgressLogger(file_path=file_path)


def log_status(message: str, event_type: str = "progress", payload: dict | None = None):
    """Log a status message to the status progress channels.

    Consecutive-duplicate suppression applies ONLY to ordinary progress lines.
    Citation events are already deduped by domain upstream and must never be
    dropped here, so they bypass the guard.
    """
    global _last_status
    if event_type == "progress" and message == _last_status:
        return
    _last_status = message
    if _STATUS_LOGGER:
        _STATUS_LOGGER.log_status(message, event_type=event_type, payload=payload)
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


# One-shot text checkpoints: (trigger substrings, status message). Each fires
# once per run the first time ANY of its triggers appears in the text stream.
# Matching against an accumulator window (not a single delta) means a header
# split across streaming chunks is still detected; _seen_text_markers stops it
# re-firing while the marker lingers inside the overlap.
_TEXT_MARKERS: tuple[tuple[tuple[str, ...], str], ...] = (
    (("## ✅ Strategist Phase Complete",),
     "Strategist Phase completed: Slide outline and visual guidelines finalized."),
    (("## ✅ Image Acquisition Phase Complete",),
     "Image Acquisition Phase completed: Generated visual illustrations and assets."),
    (("## ✅ Executor Phase Complete",),
     "Executor Phase completed: Constructed presentation slide layouts."),
    (("## ✅ Topic Research Complete",),
     "Topic research completed: Gathered information and assets successfully."),
    (("## ✅ Template Fill Complete",),
     "Template fill completed successfully."),
    (("## ✅ Customize Animations Complete",),
     "Custom animation overrides successfully applied."),
    (("## ✅ Brand Saved",),
     "Brand guidelines and identity templates saved successfully."),
    (("## Template Creation Complete",),
     "Presentation template package successfully created and registered."),
    (("## Step 1: Confirm topic", "Confirm topic scope autonomously"),
     "Defining research scope and topic focus..."),
    (("## Step 2: Gather via web search",),
     "Initiating multi-phase web research to gather facts and details..."),
    (("Deep fetch", "Deep-dives"),
     "Extracting comprehensive content and images from high-signal sites..."),
    (("Targeted fill",),
     "Conducting targeted search to gather specific missing details..."),
    (("## Step 3: Save materials",),
     "Saving research documents and downloading relevant media assets..."),
)


def _check_text_for_status(text: str):
    """Parses agent text outputs to detect role switches or phase checkpoints.

    Checkpoints are matched against a windowed view of the accumulated text (with
    a fixed overlap) rather than a single delta, so a marker that streams across a
    chunk boundary (e.g. ``## ✅ Strate`` + ``gist Phase Complete``) is still
    detected. _seen_text_markers guarantees each fires exactly once.
    """
    global _text_accum, _text_scan_pos
    if not text:
        return

    _text_accum += text

    window_start = max(0, _text_scan_pos - _SCAN_OVERLAP)
    window = _text_accum[window_start:]
    _text_scan_pos = len(_text_accum)

    # Surface the research citation manifest if present. Extraction uses the full
    # contiguous buffer; `window` is the cheap trigger gate (stays O(window)).
    _scan_research_sources(_text_accum, window)

    # Role switches (dedup by role name). Require the closing ']' so a partial
    # header still mid-stream is not emitted with a truncated role.
    if "## [Role Switch:" in window:
        try:
            for part in window.split("## [Role Switch:")[1:]:
                if "]" not in part:
                    continue
                role = part.split("]")[0].strip()
                if not role:
                    continue
                rkey = "role:" + role.lower()
                if rkey in _seen_text_markers:
                    continue
                _seen_text_markers.add(rkey)
                log_status(f"Switched agent role to: {role}.")
        except Exception:
            pass

    # One-shot phase / step / workflow checkpoints.
    for triggers, message in _TEXT_MARKERS:
        if message in _seen_text_markers:
            continue
        if any(t in window for t in triggers):
            _seen_text_markers.add(message)
            log_status(message)

    # Landscape phase — compound condition kept verbatim, evaluated on the window.
    if "landscape" not in _seen_text_markers:
        if "Landscape phase" in window or (
            "Landscape" in window and "search" in window.lower() and "Step 2" in window
        ):
            _seen_text_markers.add("landscape")
            log_status("Performing broad web landscape scan for authoritative sources...")


def _clean_topic(prompt: str) -> str:
    """Derive a short, user-friendly research topic from the raw prompt."""
    if not prompt:
        return ""
    line = next((ln.strip() for ln in prompt.splitlines() if ln.strip()), "")
    # Drop any retry-directive suffix appended by the runner.
    line = re.split(r"\[RETRY ATTEMPT", line)[0].strip()
    # Strip a leading instructional wrapper, e.g. "Please turn the following into a PPT: ...".
    m = re.match(
        r"(?i)^\s*(?:please\s+)?(?:turn|create|make|generate|build|design|produce|prepare)\b.*?:\s*(.+)$",
        line,
    )
    if m and m.group(1):
        line = m.group(1).strip()
    line = line.strip(" '\"")
    if len(line) > 90:
        line = line[:87].rstrip() + "..."
    return line


def set_research_topic(prompt: str):
    """Record the user's topic so research status updates can name it."""
    global _research_topic
    _research_topic = _clean_topic(prompt)


def reset_run_state():
    """Reset per-run status state so a fresh attempt logs cleanly."""
    global _last_status, _research_started, _thought_accum, _text_accum
    global _seen_research_headers, _research_headers_emitted, _emitted_source_keys
    global _current_slide, _total_pages_seen, _sources_parsed, _thought_scan_pos
    global _text_scan_pos, _seen_text_markers, _emitted_once
    _active_tool_calls.clear()
    _last_status = None
    _research_started = False
    _thought_accum = ""
    _text_accum = ""
    _seen_research_headers = set()
    _research_headers_emitted = 0
    _emitted_source_keys = set()
    _sources_parsed = False
    _thought_scan_pos = 0
    _text_scan_pos = 0
    _seen_text_markers = set()
    _emitted_once = set()
    _designed_slides.clear()
    _ready_slides.clear()
    _slide_names.clear()
    _current_slide = None
    _total_pages_seen = None


def _check_thought_for_status(text: str):
    """Surface native Google Search grounding activity from the model's reasoning.

    Web research in this harness is performed via native Google Search grounding,
    which never appears as a tool call — the only trace is the model's "thought"
    stream. This parses that stream to emit clean, non-technical research updates:
    one announcement naming the topic, then the model's own research sub-topics
    (its reasoning section headers), de-duplicated and capped.
    """
    global _thought_accum, _research_started, _research_headers_emitted, _thought_scan_pos
    if not text:
        return
    _thought_accum += text

    # The incremental scans (headers, URLs) only need to look at what arrived since
    # last time, plus a fixed overlap so a pattern split across a streaming
    # boundary is still caught. This keeps per-delta work ~O(1) instead of
    # re-scanning the whole (ever-growing) buffer — total cost O(n) not O(n²).
    # Dedup (_seen_research_headers / _emitted_source_keys) makes re-matches inside
    # the overlap harmless.
    window_start = max(0, _thought_scan_pos - _SCAN_OVERLAP)
    window = _thought_accum[window_start:]

    # 1) Announce the start of web research once, naming the user's topic. Only
    #    scanned until it fires — after that the (expensive) full-buffer .lower()
    #    is skipped entirely for the rest of the run.
    if not _research_started:
        low = window.lower()
        if any(k in low for k in _RESEARCH_SIGNAL_KEYWORDS):
            _research_started = True
            if _research_topic:
                log_status(f"Searching the web for the latest information on: '{_research_topic}'...")
            else:
                log_status("Searching the web for the latest facts and figures on your topic...")

    # 2) Surface clean research sub-topics from reasoning section headers, e.g.
    #    **Verifying IPO Details** -> "Researching: Verifying IPO Details".
    if _research_started and _research_headers_emitted < _MAX_RESEARCH_HEADERS:
        for raw in re.findall(r"\*\*([A-Z][^*\n]{3,60}?)\*\*", window):
            header = raw.strip().rstrip(":.").strip()
            key = header.lower()
            if not header or key in _seen_research_headers:
                continue
            _seen_research_headers.add(key)
            if any(bad in key for bad in _INTERNAL_HEADER_KEYWORDS):
                continue
            log_status(f"Researching: {header}...")
            _research_headers_emitted += 1
            if _research_headers_emitted >= _MAX_RESEARCH_HEADERS:
                break

    # 3) Surface the research citation manifest if the model emitted it in thoughts.
    #    Extraction uses the full buffer (the marker + JSON block must be
    #    contiguous); `window` is the cheap trigger gate so this stays O(window).
    _scan_research_sources(_thought_accum, window)

    # 4) Harvest bare URLs that surface only in reasoning (grounding leaves no
    #    manifest/`## Sources` trace for some domains). Idempotent by domain;
    #    windowed scan with overlap so URLs split across deltas are still caught.
    _harvest_urls_from_text(window)

    _thought_scan_pos = len(_thought_accum)


def _emit_research_sources(sources: Any):
    """Stream each newly-seen research source as its own additive citation event.

    Accepts a list of dicts ({name,url}) or URL strings. Idempotent by domain:
    every source fires at most once per run no matter how many times this is
    called (manifest, research .md, and thought-harvest all feed here). This is
    the streaming-safe shape — independent per-source deltas, never a growing
    cumulative line — so on Pub/Sub a domain-keyed Firestore upsert converges to
    the same set under at-least-once redelivery and out-of-order arrival, with no
    superseded snapshots and no missing data.
    """
    global _emitted_source_keys
    if not isinstance(sources, list):
        return

    from urllib.parse import urlparse
    for s in sources:
        if isinstance(s, dict):
            name = str(s.get("name") or s.get("title") or "").strip()
            url = str(s.get("url") or s.get("link") or "").strip()
        elif isinstance(s, str):
            name, url = "", s.strip()
        else:
            continue

        domain = ""
        if url:
            domain = urlparse(url).netloc or url
        domain = domain.replace("www.", "").strip("/")
        key = (domain or name).lower()
        if not key or key in _emitted_source_keys:
            continue
        if domain and domain.lower() in _NON_CITATION_DOMAINS:
            continue
        _emitted_source_keys.add(key)

        if name and domain:
            short = name if len(name) <= 60 else name[:57] + "..."
            human = f"Research source captured: '{short}' ({domain})."
        elif domain:
            human = f"Research source captured: {domain}."
        else:
            short = name if len(name) <= 60 else name[:57] + "..."
            human = f"Research source captured: '{short}'."

        log_status(
            human,
            event_type="citation",
            payload={
                "name": name,
                "url": url,
                "domain": domain,
                "index": len(_emitted_source_keys),
            },
        )


def _harvest_urls_from_text(text: str):
    """Capture citations that appear only as inline URLs in model reasoning.

    Native Google Search grounding surfaces some domains nowhere but the thought
    stream (no manifest entry, no `## Sources` line). Harvesting full URLs here
    feeds them through the same idempotent, per-source citation path, so no
    grounded domain is lost from the stream.
    """
    if not text:
        return
    found = _URL_RE.findall(text)
    if found:
        _emit_research_sources([{"name": "", "url": u.rstrip('.,);]')} for u in found])


_SOURCES_BLOCK_RE = re.compile(
    re.escape(_RESEARCH_SOURCES_MARKER) + r"\s*```(?:json)?\s*(\{.*?\}|\[.*?\])\s*```",
    re.DOTALL,
)


def _scan_research_sources(buffer: str, recent: str | None = None):
    """Detect and parse the agent's `[[RESEARCH_SOURCES]]` JSON manifest.

    Parses ALL marker blocks in the buffer (not just the first), so an early
    empty `{"sources": []}` does not lock out a later populated manifest — the
    regex would otherwise always match the first block. Source emission is
    idempotent (deduped by domain), so re-parsing earlier blocks is harmless.

    Cost control: the heavy DOTALL scan only runs when the marker is present in
    `recent` (the small streaming window the callers pass) AND a new marker has
    arrived since the last parse — so per-delta work stays O(window), not O(n).
    Short-circuits permanently only once a NON-empty manifest has been emitted.
    """
    global _sources_parsed
    if _sources_parsed or not buffer:
        return
    # Cheap trigger gate: only run the heavy DOTALL scan when the marker is in the
    # recent streaming window (full buffer if `recent` not supplied, e.g. the .md
    # result path). Once the marker scrolls past the window without a populated
    # manifest (a lone empty `{"sources": []}`), re-scans stop automatically — so
    # per-delta cost stays O(window), not O(n). The block may still be streaming
    # in, so we re-scan on each delta the marker is present until it parses.
    probe = recent if recent is not None else buffer
    if _RESEARCH_SOURCES_MARKER not in probe:
        return

    emitted_real = False
    for m in _SOURCES_BLOCK_RE.finditer(buffer):
        try:
            data = json.loads(m.group(1))
        except Exception:
            continue
        sources = data.get("sources") if isinstance(data, dict) else data
        if isinstance(sources, list):
            _emit_research_sources(sources)
            if sources:
                emitted_real = True
    if emitted_real:
        _sources_parsed = True


def _parse_sources_from_md(file_path: str) -> list:
    """Read a research markdown file and extract URLs from its `## Sources` section."""
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception:
        return []

    m = re.search(
        r"^#{1,4}\s*Sources?\b.*?$(.*?)(?=^#{1,4}\s|\Z)",
        content,
        re.MULTILINE | re.DOTALL | re.IGNORECASE,
    )
    if not m:
        return []

    sources = []
    for line in m.group(1).splitlines():
        line = line.strip().lstrip("*-").strip()
        if not line:
            continue
        link = re.match(r"\[([^\]]+)\]\((https?://[^\s)]+)\)", line)
        if link:
            sources.append({"name": link.group(1), "url": link.group(2)})
            continue
        url = re.search(r"https?://[^\s)]+", line)
        if url:
            sources.append({"name": "", "url": url.group(0)})
        # Prose-only citations (no URL) are skipped — nothing to surface.
    return sources


def _extract_command(args: Any) -> str:
    """Pull the shell command out of a run_command tool's args.

    The SDK passes the command under the camelCase key ``commandLine`` (as seen in
    the raw harness protocol). Older/other shapes use ``command`` / ``CommandLine``
    or nest it under ``runCommand``. Dict ``.get`` is case-sensitive, so we check
    each known spelling explicitly and fall back to a case-insensitive scan — a
    miss here silently drops every run_command-derived status line.
    """
    if isinstance(args, str):
        return args
    if not isinstance(args, dict):
        return ""
    for k in ("commandLine", "command", "CommandLine", "cmd"):
        v = args.get(k)
        if isinstance(v, str) and v:
            return v
    rc = args.get("runCommand")
    if isinstance(rc, dict):
        for k in ("commandLine", "command", "CommandLine"):
            v = rc.get(k)
            if isinstance(v, str) and v:
                return v
    for k, v in args.items():
        if isinstance(k, str) and k.lower() in ("commandline", "command", "cmd") and isinstance(v, str) and v:
            return v
    return ""


def _mark_slide_ready(slide_num: int | None):
    """Announce that a given slide's SVG is complete (idempotent per run).

    Called when the agent moves on from a slide (next slide begins, or finalize/
    export starts). Uses the page total from spec_lock when known so the wording
    matches the paired "Designing slide N of M..." emitter.
    """
    global _ready_slides
    if slide_num is None or slide_num in _ready_slides:
        return
    _ready_slides.add(slide_num)
    if _total_pages_seen is not None:
        log_status(f"Slide {slide_num} of {_total_pages_seen} is ready.")
    else:
        name = _slide_names.get(slide_num, "")
        if name:
            log_status(f"Slide ready: {name.replace('_', ' ').title()}.")
        else:
            log_status(f"Slide {slide_num} is ready.")


def _mark_all_slides_ready():
    """Flush a ready event for every designed-but-not-yet-ready slide, in order.

    Invoked when finalize/export begins so the last slide (and any slide reopened
    by a late polish edit) gets its closing "ready" event.
    """
    for n in sorted(_designed_slides):
        _mark_slide_ready(n)


def _log_status_once(message: str):
    """Emit a status line at most once per run.

    The agent re-runs some pipeline scripts (e.g. finalize/export after fixing a
    slide), so their tool-call status lines would otherwise repeat. This caps the
    noisy ones to a single emission without suppressing genuinely recurring steps
    like the quality checker.
    """
    if message in _emitted_once:
        return
    _emitted_once.add(message)
    log_status(message)


def _extract_target_path(args: Any) -> str:
    """Pull the target file path out of a write/edit tool's args, cleaning file:///."""
    if isinstance(args, dict):
        fp = (
            args.get("filePath") or args.get("file_path") or
            args.get("TargetFile") or args.get("target_file") or ""
        )
    elif isinstance(args, str):
        fp = args
    else:
        fp = ""
    if not fp:
        return ""
    if fp.startswith("file:///"):
        fp = fp[8:]
        if len(fp) > 2 and fp[1] == ":" and fp[0] == "/":
            fp = fp[1:]
    return fp


def _svg_slide_info(file_path: str) -> tuple[int | None, int | None, str]:
    """Return (slide_num, total_pages, slide_name) for an svg_output/svg_final path.

    slide_num is parsed from the filename (e.g. 02_manifesto -> 2); total_pages is
    read from the project's spec_lock page rhythm. Either may be None when not
    determinable. Shared by the "designing"/"polishing" (tool-call) and "ready"
    (tool-result) status emitters so the two can never disagree on numbering.
    """
    filename = Path(file_path).name
    slide_name = Path(file_path).stem
    slide_num = None
    total_pages = None
    match = re.search(r'(?:^|slide_|P|p|slide)(\d+)', filename)
    if match:
        slide_num = int(match.group(1))
    project_dir = _get_project_dir_from_path(file_path)
    if project_dir:
        pages = _get_page_rhythm_from_spec_lock(project_dir)
        if pages:
            total_pages = len(pages)
    return slide_num, total_pages, slide_name


def _check_tool_call_for_status(chunk: Any):
    """Parses tool calls to detect and log key pipeline actions."""
    if not chunk or not hasattr(chunk, "name") or not hasattr(chunk, "id"):
        return
        
    # Track the active tool call for ToolResult matching
    _active_tool_calls[chunk.id] = {
        "name": chunk.name,
        "args": chunk.args
    }

    # Local file-read tools (view_file / find_file) are internal and produce no
    # status, except when the agent opens the topic-research playbook — a
    # reliable early signal that web research is about to begin.
    if chunk.name in ("view_file", "find_file"):
        fp = ""
        if isinstance(chunk.args, dict):
            fp = (
                chunk.args.get("filePath") or chunk.args.get("file_path") or
                chunk.args.get("path") or chunk.args.get("query") or
                chunk.args.get("Query") or ""
            )
        if isinstance(fp, str) and "topic-research" in fp.lower():
            log_status("Preparing to research your topic and gather the latest facts...")
        return

    if chunk.name == "run_command":
        cmd = _extract_command(chunk.args)

        if not cmd:
            return

        # Finalize / export begins → every designed slide is now complete. Emit
        # the closing "Slide N is ready" events before the finalize/export line.
        if "finalize_svg.py" in cmd or "svg_to_pptx.py" in cmd:
            _mark_all_slides_ready()

        # Match commands against key scripts in the pipeline
        if "pdf_to_md.py" in cmd:
            log_status("Extracting content from source PDF...")
        elif "doc_to_md.py" in cmd:
            log_status("Extracting content from source Document...")
        elif "excel_to_md.py" in cmd:
            log_status("Extracting data from source Spreadsheet...")
        elif "ppt_to_md.py" in cmd:
            log_status("Extracting slides and text from source PowerPoint...")
        elif "web_to_md.py" in cmd:
            log_status("Extracting article content from source Webpage...")
        elif "project_manager.py init" in cmd:
            log_status("Setting up presentation project workspace...")
        elif "project_manager.py import-sources" in cmd:
            log_status("Importing source content and files...")
        elif "latex_render.py" in cmd:
            log_status("Rendering mathematical equations into slides...")
        elif "analyze_images.py" in cmd:
            log_status("Analyzing colors and layout spacing...")
        elif "image_gen.py" in cmd:
            log_status("Generating customized illustrations using AI...")
        elif "svg_quality_checker.py" in cmd:
            log_status("Reviewing slide layout and design quality...")
        elif "visual_review.py" in cmd:
            log_status("Generating slide previews for visual check...")
        elif "total_md_split.py" in cmd:
            log_status("Structuring slide content and speaker notes...")
        elif "finalize_svg.py" in cmd:
            # Re-run after slide fixes; cap to one emission per run (see #1).
            _log_status_once("Finalizing slide graphics and optimizing assets...")
        elif "svg_to_pptx.py" in cmd:
            _log_status_once("Exporting presentation to editable PowerPoint (.pptx)...")
        elif "svg_position_calculator.py" in cmd or "verify_charts" in cmd:
            log_status("Calibrating and verifying slide chart geometry...")
        elif "register_template.py" in cmd:
            log_status("Registering template in design library...")
            
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
        
        # Detect slide SVG writing. The first write of a slide announces
        # "Designing slide N" and marks the PREVIOUS slide ready; a later write to
        # the same slide is a polish pass, surfaced as "Refining slide N" (never a
        # duplicate "Designing"). This is the only completion signal available
        # because the SDK emits no ToolResult chunks.
        if "svg_output/" in file_path_norm and file_path_norm.endswith(".svg"):
            global _current_slide, _total_pages_seen
            try:
                slide_num, total_pages, slide_name = _svg_slide_info(file_path)
                if total_pages is not None:
                    _total_pages_seen = total_pages
                if slide_num is not None:
                    _slide_names[slide_num] = slide_name

                if slide_num is not None and slide_num in _designed_slides:
                    # Revisit / polish pass on an already-created slide.
                    if total_pages is not None:
                        log_status(f"Refining slide {slide_num} of {total_pages}...")
                    else:
                        log_status(f"Refining slide for {slide_name.replace('_', ' ').title()}...")
                    # Reopened: it is no longer "ready" until we move on again
                    # (a closing ready event fires at the next slide or finalize).
                    _ready_slides.discard(slide_num)
                    _current_slide = slide_num
                else:
                    # First time on this slide → the previous slide is now ready.
                    _mark_slide_ready(_current_slide)
                    if slide_num is not None:
                        _designed_slides.add(slide_num)
                    if slide_num is not None and total_pages is not None:
                        log_status(f"Designing slide {slide_num} of {total_pages}...")
                    else:
                        log_status(f"Designing slide for {slide_name.replace('_', ' ').title()}...")
                    _current_slide = slide_num
            except Exception as e:
                logger.warning("Failed to parse slide number or total pages: %s", e)
                log_status("Designing layout for next slide...")

        elif "svg_final/" in file_path_norm and file_path_norm.endswith(".svg"):
            try:
                slide_num, total_pages, slide_name = _svg_slide_info(file_path)
                if slide_num is not None and total_pages is not None:
                    log_status(f"Polishing slide {slide_num} of {total_pages}...")
                else:
                    formatted_slide_name = slide_name.replace("_", " ").title()
                    log_status(f"Polishing layout for {formatted_slide_name}...")
            except Exception as e:
                logger.warning("Failed to parse slide finalization info: %s", e)
                log_status("Polishing layout for next slide...")
                
        elif "design_spec.md" in file_path_norm:
            log_status("Drafting presentation outline and layout designs...")
        elif "spec_lock.md" in file_path_norm:
            log_status("Locking in visual styles and slide parameters...")
        elif file_path_norm.endswith(".md") and (
            "/sources/" in file_path_norm
            or re.search(r"/projects/[^/]+\.md$", file_path_norm)
        ):
            log_status("Compiling gathered research into a structured source brief...")

    elif _is_web_search_tool(chunk.name):
        query = ""
        if isinstance(chunk.args, dict):
            query = chunk.args.get("query") or chunk.args.get("Query") or chunk.args.get("q") or ""
        if query and not _is_internal_query(query):
            # Truncate very long queries for readability
            display_query = query if len(query) <= 80 else query[:77] + "..."
            log_status(f"Researching: '{display_query}'...")
        elif not query:
            # Don't log empty/missing queries at all — they add no value
            pass
        # else: internal technical query — silently suppressed
            
    elif "read_url" in chunk.name.lower() or "web_fetch" in chunk.name.lower() or "read_browser" in chunk.name.lower() or "fetch" in chunk.name.lower():
        url = ""
        if isinstance(chunk.args, dict):
            url = chunk.args.get("url") or chunk.args.get("Url") or ""
        if url:
            from urllib.parse import urlparse
            domain = urlparse(url).netloc
            if domain:
                log_status(f"Fetching and reading content from website: {domain}...")
            else:
                log_status(f"Fetching and reading content from URL...")
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
                log_status("Launching parallel visual quality review...")
            elif "pdf_to_md" in task_desc_lower or "web_to_md" in task_desc_lower or "doc_to_md" in task_desc_lower or "convert" in task_desc_lower:
                log_status("Processing source content using parallel helper...")
            else:
                log_status("Spawning helper agent to speed up execution...")
        else:
            log_status("Spawning helper agent to speed up execution...")


def _check_tool_result_for_status(chunk: Any):
    """Parses tool results to detect and log outcomes of key pipeline steps."""
    if not chunk:
        return

    chunk_id = getattr(chunk, "id", None)
    chunk_name = getattr(chunk, "name", None)

    # Primary: match by ID
    tool_call = _active_tool_calls.pop(chunk_id, None) if chunk_id else None

    # Fallback: match by name if ID lookup failed (SDK may use different ID formats)
    if not tool_call and chunk_name:
        for tc_id, tc_data in list(_active_tool_calls.items()):
            if tc_data["name"] == chunk_name:
                tool_call = _active_tool_calls.pop(tc_id)
                break

    # Last resort: infer from chunk.name directly so we can still log outcomes
    if not tool_call:
        if chunk_name:
            tool_call = {"name": chunk_name, "args": {}}
        else:
            return

    tool_name = tool_call["name"]
    tool_args = tool_call["args"]
    is_error = bool(getattr(chunk, "error", None) or getattr(chunk, "exception", None))

    if tool_name == "run_command":
        cmd = _extract_command(tool_args)

        if not cmd:
            return

        returncode = None
        result_data = getattr(chunk, "result", None)
        if isinstance(result_data, dict):
            returncode = result_data.get("returncode")
        elif isinstance(result_data, str):
            try:
                res_data = json.loads(result_data)
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

    # NOTE: per-slide "Slide N is ready" events are emitted from the tool-CALL
    # stream (see _check_tool_call_for_status / _mark_slide_ready), NOT here. This
    # SDK does not emit ToolResult chunks, so a result-driven approach never fires.

    elif _is_web_search_tool(tool_name):
        if is_error:
            log_status("Web search encountered an error.")
        else:
            # Check if the original query was internal first to avoid unnecessary processing
            original_query = ""
            if isinstance(tool_args, dict):
                original_query = tool_args.get("query") or tool_args.get("Query") or tool_args.get("q") or ""
            if original_query and _is_internal_query(original_query):
                return  # Suppress results from internal technical queries

            from urllib.parse import urlparse
            res_str = _get_result_text(chunk)
            results_info = []
            seen_domains = set()

            # Robust JSON extraction fallback for structured search tools
            try:
                data = json.loads(res_str)
                items = []
                if isinstance(data, list):
                    items = data
                elif isinstance(data, dict):
                    # Check common search response formats
                    for key in ("results", "organic_results", "items", "matches"):
                        if isinstance(data.get(key), list):
                            items = data[key]
                            break
                    if not items:
                        # Or search for any top-level list
                        for v in data.values():
                            if isinstance(v, list):
                                items = v
                                break
                                
                if items:
                    for item in items:
                        if isinstance(item, dict):
                            title = item.get("title") or item.get("Title") or item.get("snippet") or ""
                            url = item.get("link") or item.get("Link") or item.get("url") or item.get("Url") or ""
                            if url:
                                domain = urlparse(url).netloc
                                if domain and domain not in seen_domains:
                                    seen_domains.add(domain)
                                    title_clean = title.strip().replace("\n", " ")
                                    if len(title_clean) > 50:
                                        title_clean = title_clean[:47] + "..."
                                    results_info.append(f"'{title_clean}' ({domain})" if title_clean else domain)
                                    if len(results_info) >= 3:
                                        break
            except Exception:
                pass

            # Fallback 1: Extract markdown links [Title](URL) if available
            if not results_info:
                matches = re.findall(r'\[([^\]]+)\]\((https?://[^\s\)]+)\)', res_str)
                for title, url in matches:
                    domain = urlparse(url).netloc
                    if domain and domain not in seen_domains:
                        seen_domains.add(domain)
                        title_clean = title.strip().replace("\n", " ")
                        if len(title_clean) > 50:
                            title_clean = title_clean[:47] + "..."
                        results_info.append(f"'{title_clean}' ({domain})")
                        if len(results_info) >= 3:
                            break

            # Fallback 2: Plain text URL search
            if not results_info:
                found_urls = re.findall(r'https?://[^\s\'"<>#]+', res_str)
                for u in found_urls:
                    domain = urlparse(u).netloc
                    if domain and domain not in seen_domains:
                        seen_domains.add(domain)
                        results_info.append(domain)
                        if len(results_info) >= 3:
                            break

            if results_info:
                log_status(f"Research completed. Found results from: {', '.join(results_info)}")
            else:
                log_status("Web research completed successfully.")

    elif any(kw in tool_name.lower() for kw in ("read_url", "web_fetch", "read_browser", "fetch")):
        if is_error:
            log_status("Failed to read content from website.")
        else:
            url = ""
            if isinstance(tool_args, dict):
                url = (
                    tool_args.get("url") or
                    tool_args.get("Url") or
                    tool_args.get("UrlPath") or
                    tool_args.get("Target") or
                    ""
                )
            res_str = _get_result_text(chunk)

            # Try to extract the page title (markdown header # or Title: key)
            title = ""
            title_match = re.search(r'^#\s+(.+)$', res_str, re.MULTILINE)
            if title_match:
                title = title_match.group(1).strip()
            else:
                title_match = re.search(r'Title:\s*(.+)$', res_str, re.IGNORECASE | re.MULTILINE)
                if title_match:
                    title = title_match.group(1).strip()

            from urllib.parse import urlparse
            domain = urlparse(url).netloc if url else ""

            # Clean up title if found
            if title:
                title = title.replace("\n", " ").strip()
                if len(title) > 60:
                    title = title[:57] + "..."

            if title and domain:
                log_status(f"Finished reading and extracting data from website: '{title}' ({domain})")
            elif domain:
                log_status(f"Finished reading and extracting data from website: {domain}")
            else:
                log_status("Finished reading and extracting data from external webpage.")

    elif tool_name in ("write_file", "edit_file", "write_to_file", "create_file",
                        "replace_file_content", "multi_replace_file_content"):
        # When the research document is written, surface its cited sources (the
        # `## Sources` URLs). Idempotent by domain, so this safely augments the
        # manifest/thought-harvest with any sources only the .md recorded.
        if is_error:
            return
        fp = ""
        if isinstance(tool_args, dict):
            fp = (
                tool_args.get("filePath") or tool_args.get("file_path") or
                tool_args.get("path") or tool_args.get("TargetFile") or
                tool_args.get("target_file") or ""
            )
        if not isinstance(fp, str) or not fp:
            return
        if fp.startswith("file:///"):
            fp = fp[8:]
            if len(fp) > 2 and fp[1] == ':' and fp[0] == '/':
                fp = fp[1:]
        fp_norm = fp.replace("\\", "/")
        if fp_norm.endswith(".md") and (
            "/sources/" in fp_norm or re.search(r"/projects/[^/]+\.md$", fp_norm)
        ):
            _emit_research_sources(_parse_sources_from_md(fp))

