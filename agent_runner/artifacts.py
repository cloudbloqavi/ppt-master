"""
Artifacts & Manifest Replication Module for PPT Master Agent Runner

Handles final mirroring of files in projects/ to OUTPUT_ARTIFACTS_DIR, copies
log files alongside outputs, and calculates Gemini token usage costs.
"""
import os
import shutil
import logging
import json as _json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from agent_runner.config import ARGS, logger
from agent_runner.logging_setup import get_log_file_path
from agent_runner.status_logger import get_status_log_file_path


def _snapshot_output_pptx_files() -> set[str]:
    """Snapshot all .pptx files currently present under OUTPUT_ARTIFACTS_DIR."""
    output_dir_str = os.environ.get("OUTPUT_ARTIFACTS_DIR")
    if not output_dir_str:
        return set()

    output_dir = Path(output_dir_str).expanduser().resolve()
    if not output_dir.exists():
        return set()

    snapshot: set[str] = set()
    try:
        for item in output_dir.rglob("*"):
            if item.is_file() and item.suffix.lower() == ".pptx":
                try:
                    snapshot.add(str(item.resolve()))
                except Exception:
                    snapshot.add(str(item))
    except Exception as exc:
        logger.warning("Failed to snapshot existing PPTX files in %s: %s", output_dir, exc)
    return snapshot


def _snapshot_project_files() -> dict[str, tuple[float, int]]:
    """Snapshot all files under the projects directories with their mtimes and sizes."""
    project_root = Path(__file__).parent.parent.resolve()
    source_candidates = [
        project_root / "core-ppt-master-engine" / "projects",
        project_root / "projects"
    ]
    snapshot = {}
    for source in source_candidates:
        if source.exists():
            try:
                for item in source.rglob("*"):
                    if item.is_file():
                        try:
                            stat = item.stat()
                            snapshot[str(item.resolve())] = (stat.st_mtime, stat.st_size)
                        except Exception:
                            pass
            except Exception as exc:
                logger.warning("Failed to snapshot directory %s: %s", source, exc)
    return snapshot


def copy_output_artifacts(
    run_status: str = "unknown",
    prompt: str = "",
    token_usage: dict[str, Any] | None = None,
    execution_duration: float | None = None,
    subagent_stats: dict[str, Any] | None = None,
    projects_snapshot: dict[str, tuple[float, int]] | None = None,
    resumed_project: str | None = None,
    start_time: float | None = None,
) -> None:
    """Copy generated project outputs to OUTPUT_ARTIFACTS_DIR.

    This is the FINAL stage of every run — it executes regardless of whether
    the agent succeeded or failed, ensuring all produced (or partial) artifacts
    are always persisted.

    Args:
        run_status: "success", "failed", or "unknown".
        prompt: The prompt that was sent to the agent.
    """
    output_dir_str = os.environ.get("OUTPUT_ARTIFACTS_DIR")
    if not output_dir_str:
        logger.warning(
            "OUTPUT_ARTIFACTS_DIR is not set — skipping artifact copy. "
            "This should not happen if validation passed."
        )
        return

    project_root = Path(__file__).parent.parent.resolve()
    source_candidates = list(dict.fromkeys([
        project_root / "core-ppt-master-engine" / "projects",
        project_root / "projects"
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

    # Identify which project folders were modified/created during this run.
    active_projects: set[str] = set()
    if resumed_project:
        active_projects.add(resumed_project)

    for source in source_candidates:
        if source.exists():
            for item in source.rglob("*"):
                if item.is_file():
                    rel = item.relative_to(source)
                    # Skip root-level files directly under the projects directory (like README.md)
                    if len(rel.parts) <= 1:
                        continue

                    project_name = rel.parts[0]
                    resolved_path = str(item.resolve())
                    is_modified = False

                    if projects_snapshot is not None:
                        if resolved_path in projects_snapshot:
                            old_mtime, old_size = projects_snapshot[resolved_path]
                            try:
                                stat = item.stat()
                                if stat.st_mtime > old_mtime or stat.st_size != old_size:
                                    is_modified = True
                            except Exception:
                                pass
                        else:
                            # New file
                            is_modified = True
                    elif start_time is not None:
                        try:
                            stat = item.stat()
                            if stat.st_mtime >= start_time - 2:  # 2 second window
                                is_modified = True
                        except Exception:
                            pass
                    else:
                        # Fallback: copy everything if we have no state references
                        is_modified = True

                    if is_modified:
                        active_projects.add(project_name)

    if active_projects:
        logger.info("  Active project(s) identified for copying: %s", ", ".join(active_projects))
    else:
        logger.info("  No active project folder identified from execution.")

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

                    project_name = rel.parts[0]
                    # Only copy files for active projects
                    if project_name not in active_projects:
                        continue

                    found_files = True
                    dest_file = destination / rel
                    try:
                        dest_file.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(item, dest_file)
                        copied += 1
                        copied_projects.add(project_name)
                    except Exception as exc:
                        msg = f"{rel}: {exc}"
                        copy_errors.append(msg)
                        logger.error("  Copy error — %s", msg)

    if found_files:
        logger.info("  Files copied: %d", copied)
        if copy_errors:
            logger.warning("  Copy errors:  %d file(s) failed", len(copy_errors))
    else:
        logger.info("  No active project output files found in checked source dirs — skipping file copy.")

    # ── Write run manifest ───────────────────────────────────
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
            model_name = getattr(ARGS, "model", "gemini-3.5-flash")
            prices_path = project_root / "gemini_model_prices.json"
            if prices_path.exists():
                with open(prices_path, "r", encoding="utf-8") as pf:
                    prices = _json.load(pf)
                
                rates = prices.get(model_name)
                if rates:
                    input_tokens = token_usage.get("prompt_tokens", 0)
                    cached_tokens = token_usage.get("cached_content_tokens", 0)
                    output_tokens = token_usage.get("candidates_tokens", 0)
                    
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

    def _copy_log_alongside(manifest_dir: Path) -> None:
        """Copy the active log file into *manifest_dir* unless it is already there."""
        log_file_path = get_log_file_path()
        if not log_file_path or not log_file_path.exists():
            return
        log_dest = manifest_dir / log_file_path.name
        if log_dest.resolve() == log_file_path.resolve():
            return
        try:
            for handler in logging.getLogger().handlers:
                if isinstance(handler, logging.FileHandler):
                    handler.flush()
            shutil.copy2(log_file_path, log_dest)
            logger.info("  Log file copied to: %s", log_dest)
        except Exception as exc:
            logger.warning("  Failed to copy log file alongside manifest: %s", exc)

    def _copy_status_log_alongside(manifest_dir: Path) -> None:
        """Copy the active status progress log file into *manifest_dir* unless it is already there."""
        status_log_file_path = get_status_log_file_path()
        if not status_log_file_path or not status_log_file_path.exists():
            return
        status_log_dest = manifest_dir / status_log_file_path.name
        if status_log_dest.resolve() == status_log_file_path.resolve():
            return
        try:
            shutil.copy2(status_log_file_path, status_log_dest)
            logger.info("  Status progress log file copied to: %s", status_log_dest)
        except Exception as exc:
            logger.warning("  Failed to copy status progress log file alongside manifest: %s", exc)

    if copied_projects:
        for project_dir in copied_projects:
            manifest_path = destination / project_dir / "run_manifest.json"
            try:
                manifest_path.write_text(_json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info("  Manifest written: %s", manifest_path)
            except Exception as exc:
                logger.error("  Failed to write run manifest inside project %s: %s", project_dir, exc)
            _copy_log_alongside(manifest_path.parent)
            _copy_status_log_alongside(manifest_path.parent)
    else:
        manifest_path = destination / "run_manifest.json"
        try:
            manifest_path.write_text(_json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("  Manifest written to root (fallback): %s", manifest_path)
        except Exception as exc:
            logger.error("  Failed to write fallback run manifest: %s", exc)
        _copy_log_alongside(manifest_path.parent)
        _copy_status_log_alongside(manifest_path.parent)

    # ── Cleanup workspace folders for successful active projects ──────
    if run_status == "success" and copied_projects:
        for project_name in copied_projects:
            dest_proj_dir = destination / project_name
            has_pptx = False
            try:
                if dest_proj_dir.exists():
                    for f in dest_proj_dir.rglob("*.pptx"):
                        if f.is_file():
                            has_pptx = True
                            break
            except Exception as exc:
                logger.warning("Error checking for PPTX in destination %s: %s", dest_proj_dir, exc)

            if has_pptx:
                logger.info("Project '%s' successfully generated and copied to destination. Cleaning up workspace folder...", project_name)
                for source in source_candidates:
                    src_proj_dir = source / project_name
                    if src_proj_dir.exists():
                        try:
                            shutil.rmtree(src_proj_dir)
                            logger.info("Deleted workspace folder: %s", src_proj_dir)
                        except Exception as exc:
                            logger.error("Failed to delete workspace folder %s: %s", src_proj_dir, exc)
            else:
                logger.warning("No PPTX file found in destination for project '%s'. Skipping cleanup.", project_name)

    logger.info("ARTIFACT COPY STAGE COMPLETE")
    logger.info("═" * 60)
    logger.info("")
