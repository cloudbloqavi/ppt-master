"""
Core Execution Module for Presentation Builder Agent Runner

Coordinates SDK setup, imports, dependencies checking, main runner execution loop
(with retry attempt logic), and auto-resumption entry.
"""
import os
import sys
import time
import shutil
import subprocess
import asyncio
import json
import argparse
from pathlib import Path
from typing import Any

from agent_runner.config import ARGS, logger
from agent_runner.logging_setup import setup_file_logging, sweep_orphan_root_logs
from agent_runner.status_logger import (
    setup_status_logging, log_status, set_research_topic, reset_run_state,
    _check_text_for_status, _check_thought_for_status,
    _check_tool_call_for_status, _check_tool_result_for_status,
    _mark_all_slides_ready,
)
from agent_runner.tools import run_self_test
from agent_runner.resumption import find_and_restore_incomplete_project
from agent_runner.checkpoints import build_resume_directive, default_project_roots
from agent_runner.artifacts import (
    copy_output_artifacts, _snapshot_project_files, _snapshot_output_pptx_files,
    finalize_log_placement
)
from agent_runner.visual_enforcement import enforce_visual_review, status_line
from agent_runner.retheme_enforcement import (
    enforce_retheme, status_line as retheme_status_line,
)
from agent_runner.provenance_enforcement import (
    enforce_chart_provenance,
    status_line as provenance_status_line,
)
from agent_runner.catalog_match import run_catalog_match

# Process start time. Used to scope warm-retry research reuse to briefs written
# during THIS invocation, so a retry never imports a stale brief left in the
# shared projects/ dir by an unrelated earlier run.
_RUN_PROCESS_START = time.time()

# ─────────────────────────────────────────────────────────────
# Subagent Tool Detection
# ─────────────────────────────────────────────────────────────

_SUBAGENT_TOOL_NAMES = frozenset({
    "invoke_subagent", "start_subagent",
    "delegate", "spawn_agent", "subagent",
    "invoke_sub_agent", "browser_subagent",
})


def _is_subagent_tool(name: str) -> bool:
    """Check if a tool call name represents subagent invocation."""
    name_lower = name.lower()
    return (
        name_lower in _SUBAGENT_TOOL_NAMES
        or "subagent" in name_lower
        or "sub_agent" in name_lower
    )

# ─────────────────────────────────────────────────────────────
# SDK Imports (deferred so protobuf env is set first in config)
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
# Prompt Resolution & Execution
# ─────────────────────────────────────────────────────────────

_DEFAULT_PROMPT = (
    "Please turn the following into a PPT: "
    "Fictional music festival annual book in the Memphis design movement's "
    "flat-graphic, hi-saturation style — geometric shapes, terrazzo, 80s typography."
)


def resolve_prompt(args) -> str:
    """Resolve the agent prompt from CLI arg > env var > built-in default."""
    raw_prompt = None
    source = None

    if args.prompt:
        raw_prompt = args.prompt
        source = "--prompt argument"
    else:
        env_prompt = os.environ.get("AGENT_PROMPT", "").strip()
        if env_prompt:
            raw_prompt = env_prompt
            source = "AGENT_PROMPT environment variable"

    if raw_prompt:
        try:
            potential_file = Path(raw_prompt)
            if potential_file.is_file():
                logger.info(f"Loading prompt from file: '{raw_prompt}' (resolved via {source}).")
                content = potential_file.read_text(encoding="utf-8")
                # TODO: Clean up this temporary verification logging code before production merge
                print(f"\n[VERIFICATION] Resolved Input Type: File Input ('{raw_prompt}')")
                print(f"[VERIFICATION] Content Preview:\n---\n{content}\n---\n")
                return content
        except Exception as e:
            logger.debug(f"Attempted to check if prompt is a file but failed: {e}")

        logger.info(f"Using raw prompt text from {source}.")
        # TODO: Clean up this temporary verification logging code before production merge
        print(f"\n[VERIFICATION] Resolved Input Type: Raw String Input")
        print(f"[VERIFICATION] Content Preview:\n---\n{raw_prompt}\n---\n")
        return raw_prompt

    logger.info("No --prompt or AGENT_PROMPT set — using built-in default prompt.")
    # TODO: Clean up this temporary verification logging code before production merge
    print(f"\n[VERIFICATION] Resolved Input Type: Built-in Default Prompt")
    print(f"[VERIFICATION] Content Preview:\n---\n{_DEFAULT_PROMPT}\n---\n")
    return _DEFAULT_PROMPT


def _get_max_attempt_count() -> int:
    """Return total attempt count for the run from RUN_AGENT_MAX_RETRIES."""
    raw = os.environ.get("RUN_AGENT_MAX_RETRIES", "3").strip()
    try:
        value = int(raw)
        if value < 1:
            raise ValueError("must be >= 1")
        return value
    except Exception:
        logger.warning("Invalid RUN_AGENT_MAX_RETRIES=%r; using default 3.", raw)
        return 3


def _build_retry_prompt(base_prompt: str, attempt_index: int) -> str:
    """Add a deterministic non-interactive continuation directive for retries.

    Resume is artifact-driven (see agent_runner/checkpoints.py): the runner reads
    what the previous attempt left on disk — research brief, project folder,
    design_spec/spec_lock, partial or complete SVG pages, notes, finalized SVGs —
    and tells the agent to continue from the furthest-completed stage instead of
    cold-restarting and redoing work. Falls back to a plain continuation directive
    when no reusable state is found.
    """
    retry_directive = (
        "Previous run ended before producing a PPTX. "
        "Continue fully autonomously in non-interactive mode and complete the pipeline through Step 7 export in this same run. "
        "Do not ask for confirmations, and do not stop after Eight Confirmations or split-mode hints. "
        "If anything is ambiguous, choose the best default and proceed."
    )

    try:
        resume = build_resume_directive(default_project_roots(), _RUN_PROCESS_START)
    except Exception as exc:
        logger.warning("Resume-state detection failed (%s); using plain retry directive.", exc)
        resume = None
    if resume:
        retry_directive += "\n\n" + resume

    return f"{base_prompt}\n\n[RETRY ATTEMPT {attempt_index}] {retry_directive}"


def load_mcp_servers() -> list:
    """Read the local IDE mcp_config.json to load all enabled local MCP servers."""
    servers: list = []
    home = Path.home()

    candidates = [
        home / ".gemini" / "antigravity-ide" / "mcp_config.json",
    ]
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


async def run_agent(prompt_message: str, use_mcp: bool = False, no_visual_review: bool = False):
    """Initialize the Antigravity agent and send a single prompt."""
    logger.info("Initializing Agent using Google Antigravity SDK...")
    logger.info("Platform: %s | Python: %s", sys.platform, sys.version.split()[0])
    logger.info(
        "Web research runs via native Google Search grounding (in-model): it does NOT "
        "appear as a tool call, subprocess, or subagent. Cited sources are surfaced as "
        "discrete citation events from the model's manifest/reasoning, not from a search tool."
    )
    logger.info("Prompt: %s", prompt_message[:120] + ("..." if len(prompt_message) > 120 else ""))

    # Reset per-attempt status state and record the topic so native web-research
    # (Google Search grounding) updates can be surfaced cleanly and named.
    reset_run_state()
    set_research_topic(prompt_message)

    # Load system instructions dynamically from external markdown file if it exists
    instructions_path = Path(__file__).parent / "system_instructions.md"
    system_instructions = None
    if instructions_path.exists():
        try:
            with open(instructions_path, "r", encoding="utf-8") as f:
                system_instructions = f.read()
            logger.info("Loaded system instructions dynamically from %s", instructions_path)
        except Exception as e:
            logger.warning("Failed to load dynamic system instructions: %s. Falling back to built-in default.", e)

    if not system_instructions:
        system_instructions = (
            "You are an expert AI developer and strategist inside the 'ppt-master' repository. "
            "Your goal is to execute repository-specific workflows. "
            "You have tools to read/write files, search code, list directories, run shell commands, and do web searches. "
            "Always execute commands, verify results, and follow the workflows specified in AGENTS.md and SKILL.md. "
            "When running steps, proceed logically and verify that outputs (e.g. project directories, spec files, SVGs, PPTX files) "
            "are successfully created."
            "\n\nCRITICAL SPEED & IMAGE PATH RULES (MANDATORY):"
            "\n1. SVG Image References: When designing slide SVGs in `svg_output/`, always reference images using relative paths (e.g. `../images/filename.png`) instead of `images/filename.png`. This is mandatory because slide SVGs are nested under `svg_output/` and referencing them without `../` will fail static checks and trigger expensive file rewrites."
            "\n2. Command Chaining (Internal Run): Minimize execution latency in Steps 2, 3, and 4 by chaining sequential commands together using '&&' inside a single `run_command` execution. For example, run project initialization, source import, and template copies in one shell execution turn rather than separate command calls. This is done entirely internally; the end user only sees mapped status updates, not raw command outputs."
            "\n3. Batch Icon Verification: Minimize individual file lookups when checking available icons. Query all required icons in a single batch listing (e.g., using `ls templates/icons/tabler-outline | grep -E 'icon1|icon2|icon3'`) rather than calling sequential individual checks."
            "\n\nSubagent Delegation & Coordination Rules:"
            "\n1. You MUST delegate parallelizable tasks to subagents using the native `invoke_subagent` tool. Note that `define_subagent` is not supported; use `invoke_subagent` directly to spawn clone 'self' or general-purpose subagents."
            "\n2. Specific delegation scenarios:"
            "\n   - Step 1 (Source Content Ingestion): If the user provides multiple source files or links, spawn one subagent per source to run the conversion scripts (e.g. `pdf_to_md.py`, `web_to_md.py`) concurrently and summarize their outputs."
            "\n   - Step 5 (Image Acquisition): If the design specification requires both AI image generation (`ai` acquisition) and web search (`web` acquisition), you MUST parallelize the work. Spawn a subagent via the `invoke_subagent` tool to perform the web searches concurrently while the main agent executes the AI image generation manifest script (`image_gen.py`)."
            "\n   - Step 6 (Visual Review): After all SVGs are generated, run the deterministic layout auditor `python3 core-ppt-master-engine/skills/ppt-master/scripts/svg_layout_auditor.py <project_path>`. It mathematically detects and auto-fixes the unambiguous layout defects (text-overlap, y=0 baseline origin, out-of-bounds) and writes per-page findings to `<project_path>/.review/`. For any remaining AMBIGUOUS visual issues when N > 2 slides, you MAY additionally partition the pages into batches of <= 5 and spawn parallel `invoke_subagent` review subagents (launch the preview server `svg_editor/server.py <project_path> --no-browser` first). IMPORTANT: the runner independently re-runs this auditor and rebuilds the deck after your turn, so it cannot be skipped — and you MUST NOT claim visual review is complete unless you actually ran the auditor."
            "\n   - Web Research / Fact-Gathering: If the user prompt requires searching for latest information or reports, Recency-based information for MULTIPLE persona, companies, products, or distinct topics (e.g. comparing Nike and Microsoft sales in current year), you MUST parallelize this web research phase in a very efficient and optimized way. Spawn parallel subagents using the `invoke_subagent` tool to execute web searches and URL reads concurrently, then aggregate their research findings in the workspace."
            "\n3. IMPORTANT: When you spawn any subagent, you MUST explicitly wait for the tool to finish and return its result. You MUST NOT finish your response, conclude the conversation, or output your final answer while any subagents are still running in the background. Doing so terminates the agent session and orphans the subagents. Always consume the subagent's result (ToolResult) and verify its outcomes before declaring the task complete."
            "\n4. Explicit Decision Logging: Every time you evaluate a phase where a subagent could be spawned, you MUST output a clear statement of your decision in your text or thought output using the format: `[Subagent Decision] Phase: <PhaseName> | Decision: <Bypass/Spawn> | Reason: <DetailReason>`."
            "\n\nOutput Discipline (Token Efficiency):"
            "\n- You are an autonomous execution engine, NOT a conversational assistant."
            "\n- NEVER narrate what you are about to do, what you just did, or why. Just do it."
            "\n- NEVER echo, reprint, or summarize file contents you just read or wrote."
            "\n- NEVER explain your thinking, reasoning, or decision-making process in text output."
            "\n- NEVER greet, apologize, confirm receipt, or use conversational filler."
            "\n- Output text ONLY when: (a) reporting a blocking error that halts the workflow, "
            "(b) logging a subagent decision in the format `[Subagent Decision] ...`, "
            "(c) the workflow explicitly requires a user-facing summary (e.g. visual-review aggregate table), "
            "or (d) the final completion message at the very end."
            "\n- Keep all text outputs under 3 sentences. Prefer structured formats (tables, bullet points) over prose."
            "\n\nNon-Interactive Batch Execution (Highest Priority):"
            "\n- This run is fully programmatic: there is no human-in-the-loop after the initial prompt."
            "\n- NEVER ask for user confirmation, approval, choice, or clarification during execution."
            "\n- For Step 4 Eight Confirmations, treat them as non-blocking and continue immediately."
            "\n- NEVER stop after split-mode guidance; default to continuous mode in this session."
            "\n- Continue autonomously through Strategist -> (Image Acquisition if needed) -> Executor -> Step 7 export."
            "\n- If details are missing or ambiguous, pick a strong default and proceed."
            "\n- The task is complete only when at least one native PPTX has been exported."
        )

    # Dynamic overrides append
    if no_visual_review:
        system_instructions += "\n\nUser has opted out of the visual review phase (--no-visual-review). DO NOT execute the visual self-check / visual-review workflow or the layout auditor at Step 6. The runner will also skip its enforced post-turn audit."
    else:
        system_instructions += "\n\nVisual review is enabled by default (opt-out mode). At Step 6, after all SVGs are generated, you MUST run the deterministic layout auditor (`svg_layout_auditor.py <project_path>`) and address its findings. The runner ALSO enforces this audit after your turn and rebuilds the deck if it changed any SVG — so never report visual review as done without having actually run the auditor."

    # Catalog match stage (Directive prompts only): the runner consults the
    # company-first + stock catalogs up front via ONE normal LLM call and injects
    # ranked per-slide candidates, so template selection cannot be silently
    # dropped under token pressure. Fail-open — a Brief prompt or any error injects
    # nothing and leaves selection model-driven (see agent_runner/catalog_match.py).
    catalog_candidates = None
    try:
        catalog_candidates, _inject = run_catalog_match(
            prompt_message, ARGS.model, os.environ.get("GEMINI_API_KEY", "")
        )
        if _inject:
            system_instructions += "\n" + _inject
            log_status("Matched slide visuals against the in-house template catalog...")
    except Exception as cm_exc:  # noqa: BLE001 — never let the match stage break a run
        logger.warning("Catalog match stage errored (non-fatal): %s", cm_exc)

    mcp_servers = load_mcp_servers() if use_mcp else []
    if use_mcp:
        logger.info("Enabled %d local MCP server(s).", len(mcp_servers))
    else:
        logger.info("MCP servers disabled. Pass --mcp to enable them.")

    capabilities = CapabilitiesConfig(
        enable_subagents=True
    )

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

    logged_decisions = set()
    accumulated_text = ""
    accumulated_thoughts = ""

    # Early detection of Step 1 (Ingestion) subagent decision based on user prompt.
    import re
    urls = re.findall(r'https?://[^\s]+', prompt_message)
    files = re.findall(r'[\w\-./\\]+\.(?:pdf|docx|xlsx|pptx|txt|md)', prompt_message)
    sources_count = len(urls) + len(files)
    if sources_count <= 1:
        early_msg = f"[Subagent Decision] Phase: Step 1 (Source Ingestion) | Decision: Bypass | Reason: Single or inline text source provided ({sources_count} files/URLs found in prompt). No parallel conversion subagents required."
        logger.info(early_msg)
        logged_decisions.add(early_msg)
    else:
        early_msg = f"[Subagent Decision] Phase: Step 1 (Source Ingestion) | Decision: Spawn | Reason: Multiple source files/URLs provided ({sources_count} found in prompt). Invoking parallel conversion subagents."
        logger.info(early_msg)
        logged_decisions.add(early_msg)

    # Early detection of Web Research / Fact-Gathering subagent decision
    has_outline = bool(re.search(r'(?i)slide\s*\d+|page\s*\d+|##\s+slide|##\s+page', prompt_message))
    if has_outline or sources_count > 0:
        research_msg = "[Subagent Decision] Phase: Web Research / Fact-Gathering | Decision: Bypass | Reason: Detailed presentation outline or source documents provided. Bypassing background research phase."
        logger.info(research_msg)
        logged_decisions.add(research_msg)
    else:
        research_msg = "[Subagent Decision] Phase: Web Research / Fact-Gathering | Decision: Spawn | Reason: Topic-only prompt provided without detailed slides. Spawning research subagent to gather web sources."
        logger.info(research_msg)
        logged_decisions.add(research_msg)

    # Log Step 6 bypass early if visual review is disabled by command line
    if no_visual_review:
        early_visual_msg = "[Subagent Decision] Phase: Step 6 (Visual Review) | Decision: Bypass | Reason: User explicitly opted out via --no-visual-review command line flag."
        logger.info(early_visual_msg)
        logged_decisions.add(early_visual_msg)

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

                    # Surface native web-research (Google Search grounding) that
                    # only appears in the model's reasoning, not as a tool call.
                    _check_thought_for_status(chunk.text)

                    # Parse thought stream for [Subagent Decision]
                    accumulated_thoughts += chunk.text
                    lines = accumulated_thoughts.split("\n")
                    for line in lines[:-1]:
                        if "[Subagent Decision]" in line and line.strip() not in logged_decisions:
                            decision_line = line.strip()
                            logger.info("%s", decision_line)
                            logged_decisions.add(decision_line)

                elif isinstance(chunk, Text):
                    if last_chunk_type != "text":
                        print("\n[Agent] ", end="", flush=True)
                        last_chunk_type = "text"
                    print(chunk.text, end="", flush=True)
                    _check_text_for_status(chunk.text)

                    # Parse text stream for [Subagent Decision]
                    accumulated_text += chunk.text
                    lines = accumulated_text.split("\n")
                    for line in lines[:-1]:
                        if "[Subagent Decision]" in line and line.strip() not in logged_decisions:
                            decision_line = line.strip()
                            logger.info("%s", decision_line)
                            logged_decisions.add(decision_line)

                elif isinstance(chunk, ToolCall):
                    _check_tool_call_for_status(chunk)
                    if _is_subagent_tool(chunk.name):
                        subagent_stats["total_spawned"] += 1
                        args_dict = chunk.args if isinstance(chunk.args, dict) else {}
                        task_desc = args_dict.get("task", args_dict.get("Task", ""))
                        subagent_type = args_dict.get("subagent_type", args_dict.get("SubagentType", "self"))
                        logger.info(
                            "[Subagent Spawned] Subagent #%d (type: %s, tool: %s) invoked. Task: %s",
                            subagent_stats["total_spawned"],
                            subagent_type,
                            chunk.name,
                            task_desc[:150] + ("..." if len(task_desc) > 150 else "")
                        )
                        subagent_stats["details"].append({
                            "id": chunk.id,
                            "type": subagent_type,
                            "task": task_desc,
                            "tool_name": chunk.name,
                            "status": "running"
                        })
                    else:
                        if ARGS.verbose:
                            logger.info("[Tool Call] '%s' args: %s", chunk.name, chunk.args)
                        else:
                            logger.info("[Tool Call] '%s'", chunk.name)
                    last_chunk_type = "tool_call"
                elif isinstance(chunk, ToolResult):
                    _check_tool_result_for_status(chunk)
                    if _is_subagent_tool(chunk.name):
                        subagent_stats["completed"] += 1
                        for detail in subagent_stats["details"]:
                            if detail["id"] == chunk.id:
                                detail["status"] = "completed"
                                break
                        logger.info("[Subagent Completed] Subagent (id: %s, tool: %s) finished its task.", chunk.id, chunk.name)

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

            # Final check for any decision lines at the very end (without trailing newlines)
            for text_source in (accumulated_text, accumulated_thoughts):
                for line in text_source.split("\n"):
                    if "[Subagent Decision]" in line and line.strip() not in logged_decisions:
                        decision_line = line.strip()
                        logger.info("%s", decision_line)
                        logged_decisions.add(decision_line)

            # ── Subagent delegation reconciliation (no fabrication) ──────────
            # The model may LOG a planning decision ("[Subagent Decision] … Spawn")
            # without the harness ever surfacing a START_SUBAGENT ToolCall — it
            # reconsiders, or the phase is satisfied inline. We report planned
            # spawns separately and NEVER inflate the real (observed) spawn count.
            # In particular, web research runs via native Google Search grounding
            # in-model and legitimately never spawns a subagent or subprocess.
            spawn_decisions = [d for d in logged_decisions if "Decision: Spawn" in d]
            planned_not_executed = (
                len(spawn_decisions) if subagent_stats["total_spawned"] == 0 else 0
            )
            if planned_not_executed:
                logger.info(
                    "Subagent delegation was planned in %d decision-log entr(ies) but no "
                    "START_SUBAGENT tool call was observed — the model satisfied those "
                    "phases inline (e.g. native Google Search grounding does web research "
                    "in-model and never spawns a subagent).",
                    planned_not_executed,
                )

            # Report only OBSERVED facts about the agent's in-turn review activity.
            # Whether the agent spawned its own review subagents is no longer how
            # visual review is guaranteed — the runner enforces a deterministic
            # layout audit after this turn (see enforce_visual_review). Do NOT
            # fabricate a "static checks passed / slide count <= 2" justification:
            # earlier that line claimed checks had passed even when none had run.
            if not no_visual_review and subagent_stats["total_spawned"] == 0:
                logger.info("Agent spawned no in-turn visual-review subagents; the runner's "
                            "enforced deterministic layout audit will run post-turn.")

            print("\n" + "═" * 60)
            print("SUBAGENT EXECUTION SUMMARY")
            print(f"  Subagents Enabled in Config: {subagent_stats['enabled']}")
            print(f"  Total Subagents Spawned:     {subagent_stats['total_spawned']} (observed START_SUBAGENT calls)")
            print(f"  Total Subagents Completed:   {subagent_stats['completed']}")
            if subagent_stats["total_spawned"] > 0 and subagent_stats["details"]:
                print("  Spawned Subagents Details:")
                for idx, detail in enumerate(subagent_stats["details"], 1):
                    tool_info = f" via {detail['tool_name']}" if detail.get('tool_name') else ""
                    print(f"    {idx}. [Type: {detail['type']}{tool_info}] Status: {detail['status']}")
                    print(f"       Task: {detail['task'][:120]}...")
            elif subagent_stats["enabled"]:
                print("  Note: Subagents were enabled and available, but the model did not delegate.")
                print("        Expected for small decks and for web research — native Google Search")
                print("        grounding runs in-model and never spawns a subagent or background process.")
                if planned_not_executed:
                    print(f"  Planned-but-not-executed: {planned_not_executed} '[Subagent Decision] … Spawn' "
                          "log entr(ies) had no matching tool call (satisfied inline):")
                    for idx, decision in enumerate(spawn_decisions, 1):
                        print(f"    {idx}. {decision[:140]}")
            else:
                print("  Reason not invoked: Subagents were disabled in CapabilitiesConfig.")
            print("═" * 60 + "\n")
            return response.usage_metadata, subagent_stats, catalog_candidates

    except Exception as e:
        logger.error("Execution error: %s", e, exc_info=True)
        raise


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
            project_root = Path(__file__).parent.parent.resolve()
            req_path = project_root / "requirements.txt"
            logger.info("Missing dependencies detected. Running pip install -r %s...", req_path)
            try:
                subprocess.run([sys.executable, "-m", "pip", "install", "-r", str(req_path)], check=True)
            except Exception as pip_exc:
                logger.error("Failed to run pip install: %s", pip_exc)

        if not ARGS.no_visual_review:
            try:
                from playwright.sync_api import sync_playwright
                with sync_playwright() as p:
                    browser = p.chromium.launch()
                    browser.close()
            except Exception:
                logger.info("Playwright Chromium browser binary not found or unable to launch. Installing chromium...")
                try:
                    subprocess.run([sys.executable, "-m", "playwright", "install", "chromium"], check=True)
                    logger.info("Playwright Chromium browser binary installed successfully.")
                except Exception as play_exc:
                    logger.error("Failed to install Playwright Chromium: %s", play_exc)


def main_run() -> int:
    """Main execution entry point for agent runner."""
    if ARGS.self_test:
        success = run_self_test()
        return 0 if success else 1

    # Clean up any loose logs left at the artifacts root by older runner versions
    # or runs killed before cleanup, BEFORE this run creates its own logs.
    sweep_orphan_root_logs()

    setup_file_logging()
    check_and_install_dependencies()
    prompt = resolve_prompt(ARGS)

    setup_status_logging()
    log_status("Agent runner initialized. Resolving configuration and validating environment...")

    # Auto-resumption check
    resumed_project = None
    if ARGS.resume or prompt.lower().strip() == "resume":
        log_status("Scanning for incomplete projects to resume...")
        logger.info("Auto-resumption mode activated.")
        resumed_project = find_and_restore_incomplete_project(ARGS.depth)
        if not resumed_project:
            log_status("No incomplete projects found to resume. Workflow is up to date.")
            logger.info("No incomplete projects found to resume. Everything is up to date. Exiting successfully.")
            return 0
        prompt = f"resume generating projects/{resumed_project}"
        log_status(f"Resuming generation for project '{resumed_project}'...")
        logger.info(f"Target resumption prompt: '{prompt}'")

    max_attempts = _get_max_attempt_count()
    exit_code = 1
    final_status = "failed"

    logger.info(
        "Run guard active: total attempts=%d. Silent failure is defined as no new PPTX output.",
        max_attempts,
    )

    for attempt in range(1, max_attempts + 1):
        attempt_prompt = prompt if attempt == 1 else _build_retry_prompt(prompt, attempt)

        if attempt > 1:
            log_status(f"Starting execution retry (attempt {attempt}/{max_attempts})...")
            logger.warning(
                "Retrying run: attempt %d/%d.",
                attempt,
                max_attempts,
            )
        else:
            log_status("Launching main agent execution workflow...")

        t_snap_start = time.time()
        projects_snapshot = _snapshot_project_files()
        pptx_before = _snapshot_output_pptx_files()
        t_snap_dur = time.time() - t_snap_start
        logger.info("Pre-run snapshot completed in %.2fs.", t_snap_dur)
        start_time = time.time()
        token_usage_dict = None
        subagent_stats_dict = None
        run_status = "started"
        interrupted = False

        try:
            result = asyncio.run(
                run_agent(
                    attempt_prompt,
                    use_mcp=ARGS.mcp,
                    no_visual_review=ARGS.no_visual_review,
                )
            )
            catalog_candidates = None
            if isinstance(result, tuple):
                usage = result[0]
                subagent_stats_dict = result[1] if len(result) > 1 else None
                catalog_candidates = result[2] if len(result) > 2 else None
            else:
                usage = result
            run_status = "success"
            # Safety-net flush: emit a closing "Slide N is ready" for any slide
            # that was designed but never got its ready event. The per-slide flush
            # is normally driven off the finalize/export tool call, but when the
            # agent chains the whole tail (total_md_split && finalize_svg &&
            # svg_to_pptx) into a single run_command, that detection can be missed
            # and the final slide's ready line is dropped. Flushing here guarantees
            # the last slide is reported regardless of how export was invoked.
            _mark_all_slides_ready()
            log_status("Agent execution completed successfully.")
            logger.info("Agent run completed successfully.")
            if usage:
                token_usage_dict = {
                    "prompt_tokens": usage.prompt_token_count,
                    "cached_content_tokens": usage.cached_content_token_count,
                    "candidates_tokens": usage.candidates_token_count,
                    "thoughts_tokens": usage.thoughts_token_count,
                    "total_tokens": usage.total_token_count,
                }

            # Raw-template re-theme (runs BEFORE visual review): some company
            # templates are raw PPTX exports the model copies verbatim; the runner
            # deterministically re-themes those pages (colors + typography) to the
            # project palette and rebuilds the deck. Done first so the layout
            # auditor below sees the final themed fonts. Never fails the run.
            try:
                rt_result = enforce_retheme(start_time)
                rt_line = retheme_status_line(rt_result)
                if rt_line:
                    log_status(rt_line)
            except Exception as rt_exc:  # noqa: BLE001
                logger.error("Raw-template re-theme stage errored (non-fatal): %s",
                             rt_exc, exc_info=True)

            # Enforced visual review (Part C): runs runner-side, so it cannot be
            # skipped or narrated-but-not-done by the agent. The deterministic
            # auditor auto-fixes unambiguous layout defects (text overlap, y=0
            # origin, out-of-bounds) in svg_output/ and, if anything changed,
            # rebuilds the deck — because the agent had already exported from the
            # un-fixed SVGs. Honors --no-visual-review. Never fails the run.
            try:
                if not ARGS.no_visual_review:
                    log_status("Reviewing slide layouts for visual issues...")
                vr_result = enforce_visual_review(ARGS.no_visual_review, start_time)
                log_status(status_line(vr_result))
            except Exception as vr_exc:
                logger.error("Enforced visual-review stage errored (non-fatal): %s",
                             vr_exc, exc_info=True)

            # Persist the runner's catalog candidates into the project folder so the
            # candidate-aware provenance check below has a ground-truth record of
            # what was offered — independent of whether the model wrote it itself.
            try:
                if catalog_candidates:
                    from agent_runner.catalog_match import persist_candidates
                    from agent_runner.visual_enforcement import _find_active_project_dirs
                    _dirs = _find_active_project_dirs(start_time)
                    n = persist_candidates(_dirs, catalog_candidates)
                    if n:
                        logger.info("Wrote chart_candidates.json into %d project folder(s).", n)
            except Exception as pc_exc:  # noqa: BLE001
                logger.warning("Persisting catalog candidates failed (non-fatal): %s", pc_exc)

            # Chart provenance validation + structural-mimic review (advisory):
            # verifies viz slides recorded which template they used (company
            # catalog first) and that company/stock slides carry the matched
            # template's structure. Report-only — never fails the run.
            try:
                cp_result = enforce_chart_provenance(start_time)
                log_status(provenance_status_line(cp_result))
            except Exception as cp_exc:
                logger.error("Chart provenance/structural review errored (non-fatal): %s",
                             cp_exc, exc_info=True)
        except KeyboardInterrupt:
            run_status = "interrupted"
            log_status("Agent execution interrupted by user.")
            exit_code = 130
            interrupted = True
            logger.warning("Agent run interrupted by user (KeyboardInterrupt).")
        except Exception as exc:
            run_status = "failed"
            log_status(f"Agent execution failed: {exc}")
            logger.error("Agent run failed: %s", exc, exc_info=True)
        finally:
            log_status("Synchronizing generated artifacts and writing run metadata...")
            execution_duration = time.time() - start_time
            t_copy_start = time.time()
            copy_output_artifacts(
                run_status=run_status,
                prompt=attempt_prompt,
                token_usage=token_usage_dict,
                execution_duration=execution_duration,
                subagent_stats=subagent_stats_dict,
                projects_snapshot=projects_snapshot,
                resumed_project=resumed_project,
                start_time=start_time,
            )
            t_copy_dur = time.time() - t_copy_start
            logger.info("Artifact copy stage completed in %.2fs.", t_copy_dur)

        if interrupted:
            final_status = run_status
            break

        pptx_after = _snapshot_output_pptx_files()
        new_pptx = sorted(pptx_after - pptx_before)

        if run_status == "success" and new_pptx:
            logger.info("Detected %d new PPTX output artifact(s).", len(new_pptx))
            exit_code = 0
            final_status = "success"
            break

        if run_status == "success" and not new_pptx:
            run_status = "silent_failure"
            logger.error(
                "Silent failure detected: run completed without producing any new .pptx artifact."
            )
        else:
            logger.error("Run attempt ended with status: %s", run_status)

        final_status = run_status
        exit_code = 1

        if attempt < max_attempts:
            logger.warning(
                "Will retry after status '%s' (attempt %d/%d).",
                run_status,
                attempt,
                max_attempts,
            )
        else:
            logger.error(
                "Exhausted all attempts (%d). Final status: %s.",
                max_attempts,
                final_status,
            )

    log_status(f"Workflow execution finished with status: {final_status}")
    logger.info("Runner finished with status: %s", final_status)
    # Logs were copied into the project artifacts folder during the artifact-copy
    # stage; remove the now-redundant top-level originals so they don't pile up at
    # the OUTPUT_ARTIFACTS_DIR root. Must run last — it closes the execution log
    # FileHandler. (No-op if logs were not placed inside a project folder.)
    finalize_log_placement()
    return exit_code


def main_resume() -> int:
    """Main execution entry point for auto-resumption watchdog wrapper."""
    parser = argparse.ArgumentParser(description="Presentation Builder Auto Resumption Watchdog Wrapper")
    parser.add_argument(
        "--depth",
        type=int,
        default=None,
        help="Number of recent project directories to verify (defaults to WATCHDOG_DEPTH env var or 3).",
    )
    args = parser.parse_args()

    # Locate and run run_agent.py at project root
    project_root = Path(__file__).parent.parent.resolve()
    runner_script = project_root / "run_agent.py"
    if not runner_script.exists():
        logger.error(f"Runner script not found: {runner_script}")
        return 1

    cmd = [sys.executable, str(runner_script), "--resume"]
    if args.depth is not None:
        cmd.extend(["--depth", str(args.depth)])

    logger.info(f"Delegating to agent runner: {' '.join(cmd)}")
    try:
        res = subprocess.run(cmd, check=True)
        return res.returncode
    except subprocess.CalledProcessError as err:
        logger.error(f"Agent runner failed with exit code {err.returncode}")
        return err.returncode
