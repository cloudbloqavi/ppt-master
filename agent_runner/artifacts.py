"""
Artifacts & Manifest Replication Module for Presentation Builder Agent Runner

Handles final mirroring of files in projects/ to OUTPUT_ARTIFACTS_DIR, copies
log files alongside outputs, and calculates Gemini token usage costs.
"""
import os
import shutil
import logging
import time
import json as _json
from pathlib import Path
from datetime import datetime, timezone
from typing import Any
from agent_runner.config import ARGS, logger
from agent_runner.logging_setup import get_log_file_path, get_run_log_dir
from agent_runner.status_logger import get_status_log_file_path

# Set True once the run/status logs have been copied INTO a project artifacts
# subfolder. Gates finalize_log_placement() so the top-level originals are only
# removed when a canonical in-project copy exists (a failed run with no project
# keeps its root-level log + manifest, which is correct there).
_logs_copied_into_project = False


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
    """Snapshot all files under the projects directories with their mtimes and sizes.
    
    Skips known-heavy directories that don't need diffing (e.g., .git,
    __pycache__, node_modules) to reduce NTFS stat call overhead on Windows.
    """
    _SKIP_DIRS = frozenset({
        ".git", "__pycache__", "node_modules", ".mypy_cache",
        ".pytest_cache", ".tox", "venv", ".venv", "env",
    })
    
    project_root = Path(__file__).parent.parent.resolve()
    source_candidates = [
        project_root / "core-ppt-master-engine" / "projects",
        project_root / "projects"
    ]
    snapshot = {}
    t_start = time.time()
    file_count = 0
    for source in source_candidates:
        if source.exists():
            try:
                for item in source.rglob("*"):
                    # Skip heavy directories
                    if item.is_dir():
                        continue
                    if any(part in _SKIP_DIRS for part in item.parts):
                        continue
                    try:
                        stat = item.stat()
                        snapshot[str(item.resolve())] = (stat.st_mtime, stat.st_size)
                        file_count += 1
                    except Exception:
                        pass
            except Exception as exc:
                logger.warning("Failed to snapshot directory %s: %s", source, exc)
    t_dur = time.time() - t_start
    logger.info("Project snapshot: %d files indexed in %.2fs.", file_count, t_dur)
    return snapshot


# Structural markers that distinguish a genuine generated project folder from a
# stray folder the agent may create by writing intermediate files (e.g. failed
# image downloads) to an invented path that never went through `project_manager
# init`. A real project always has at least one of these — a bare junk folder of
# loose images/logs has none. Used to keep stray folders out of the mirrored
# output (see _looks_like_project).
_PROJECT_STRUCTURE_MARKERS = ("svg_output", "exports", "svg_final")
_PROJECT_STRUCTURE_FILES = ("design_spec.md", "spec_lock.md")


def _looks_like_project(source_candidates: list[Path], project_name: str) -> bool:
    """Return whether *project_name* under any source dir is a real project folder.

    A genuine project (created via ``project_manager init``) contains structural
    subfolders (``svg_output/``, ``exports/``, …) or a design spec. Stray folders
    — created when the agent writes intermediate files to an invented bare-slug
    path instead of the canonical path ``init`` returned — have only loose files
    and must not be mirrored to OUTPUT_ARTIFACTS_DIR as if they were deliverables.
    """
    for source in source_candidates:
        proj_dir = source / project_name
        try:
            if not proj_dir.is_dir():
                continue
        except Exception:
            continue
        for marker in _PROJECT_STRUCTURE_MARKERS:
            if (proj_dir / marker).is_dir():
                return True
        for marker_file in _PROJECT_STRUCTURE_FILES:
            if (proj_dir / marker_file).is_file():
                return True
    return False


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

    # Identify active projects AND collect files to copy in a SINGLE PASS.
    # This replaces the previous approach of two separate rglob iterations,
    # reducing filesystem stat overhead significantly on Windows/NTFS.
    t_scan_start = time.time()
    active_projects: set[str] = set()
    files_to_copy: list[tuple[Path, Path, str]] = []  # (src_file, rel_path, project_name)
    
    if resumed_project:
        active_projects.add(resumed_project)

    for source in source_candidates:
        if not source.exists():
            continue
        for item in source.rglob("*"):
            if not item.is_file():
                continue
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
            
            # Collect for potential copy (we filter by active_projects later)
            files_to_copy.append((item, rel, project_name))

    t_scan_dur = time.time() - t_scan_start
    logger.info("  File scan completed in %.2fs (%d files examined).", t_scan_dur, len(files_to_copy))

    # Drop stray folders that picked up new files during the run but are not real
    # projects (e.g. failed image downloads written to an invented bare-slug path
    # that bypassed `project_manager init`). Mirroring those would litter
    # OUTPUT_ARTIFACTS_DIR with junk folders alongside the genuine deliverable.
    # A resumed project is trusted explicitly and never filtered.
    if active_projects:
        stray_projects = {
            name
            for name in active_projects
            if name != resumed_project and not _looks_like_project(source_candidates, name)
        }
        if stray_projects:
            active_projects -= stray_projects
            logger.warning(
                "  Skipping %d stray folder(s) with no project structure "
                "(svg_output/exports/design_spec): %s. These are likely "
                "intermediate files written to a non-canonical path.",
                len(stray_projects), ", ".join(sorted(stray_projects)),
            )

    if active_projects:
        logger.info("  Active project(s) identified for copying: %s", ", ".join(active_projects))
    else:
        logger.info("  No active project folder identified from execution.")

    copied = 0
    copy_errors: list[str] = []
    found_files = False
    copied_projects: set[str] = set()

    # Copy only files belonging to active projects (single pass, no second rglob)
    t_copy_start = time.time()
    for item, rel, project_name in files_to_copy:
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
    t_copy_dur = time.time() - t_copy_start

    if found_files:
        logger.info("  Files copied: %d in %.2fs", copied, t_copy_dur)
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
        global _logs_copied_into_project
        for project_dir in copied_projects:
            manifest_path = destination / project_dir / "run_manifest.json"
            try:
                manifest_path.write_text(_json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
                logger.info("  Manifest written: %s", manifest_path)
            except Exception as exc:
                logger.error("  Failed to write run manifest inside project %s: %s", project_dir, exc)
            _copy_log_alongside(manifest_path.parent)
            _copy_status_log_alongside(manifest_path.parent)
            # Logs now live inside the project folder; the top-level originals
            # at OUTPUT_ARTIFACTS_DIR root are redundant and will be cleaned up
            # by finalize_log_placement() at the end of the run.
            _logs_copied_into_project = True
    else:
        # No project folder was produced (e.g. the agent failed early). Keep the
        # manifest with the logs inside the per-run log folder rather than loose
        # at the artifacts root — the logs already live there, so nothing is left
        # littering the shared OUTPUT_ARTIFACTS_DIR root.
        fallback_dir = get_run_log_dir() or destination
        manifest_path = fallback_dir / "run_manifest.json"
        try:
            manifest_path.write_text(_json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")
            logger.info("  Manifest written alongside logs (no project produced): %s", manifest_path)
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


def finalize_log_placement() -> None:
    """Relocate the per-run log folder's contents into the project, then remove it.

    `run_agent_*.log` and `status_progress_*.log` are written into a per-run
    ``_run_logs_<timestamp>/`` folder (never the shared artifacts root) while the
    run is in progress, since the project name isn't known at startup. Once
    ``copy_output_artifacts`` has copied them alongside each project's
    `run_manifest.json`, this removes the now-redundant originals and deletes the
    empty per-run folder so nothing accumulates under OUTPUT_ARTIFACTS_DIR.

    No-op unless the logs were actually copied into a project subfolder (a failed
    run that produced no project keeps its `_run_logs_<timestamp>/` folder intact —
    that is the canonical copy in that case, and it's still a named folder, not
    loose files at the root). Call this once, at the very end of the run, after all
    logging is finished — it detaches and closes the execution log's FileHandler so
    Windows releases the file lock before unlinking.
    """
    if not _logs_copied_into_project:
        return

    # 1. Status progress log — written with a fresh open()/close() per line, so
    #    there's no persistent handle; unlink directly.
    status_path = get_status_log_file_path()
    if status_path and status_path.exists():
        try:
            status_path.unlink()
            logger.info("Removed redundant per-run status progress log: %s", status_path)
        except Exception as exc:
            logger.warning("Could not remove per-run status progress log %s: %s", status_path, exc)

    # 2. Execution log — held open by a root-logger FileHandler; detach and close
    #    the matching handler first so the OS releases the lock, then unlink.
    log_path = get_log_file_path()
    if log_path and log_path.exists():
        root = logging.getLogger()
        for handler in list(root.handlers):
            if isinstance(handler, logging.FileHandler):
                try:
                    same = Path(handler.baseFilename).resolve() == log_path.resolve()
                except Exception:
                    same = False
                if same:
                    try:
                        handler.flush()
                        handler.close()
                    except Exception:
                        pass
                    root.removeHandler(handler)
        try:
            log_path.unlink()
        except Exception as exc:
            logger.warning("Could not remove per-run execution log %s: %s", log_path, exc)

    # 3. Remove the now-empty per-run log folder so it doesn't linger under the
    #    artifacts root. Only remove if it is genuinely empty (a stray file would
    #    otherwise be silently discarded).
    run_log_dir = get_run_log_dir()
    if run_log_dir and run_log_dir.exists():
        try:
            # Don't remove if it somehow resolved to the artifacts root itself.
            output_dir_str = os.environ.get("OUTPUT_ARTIFACTS_DIR")
            is_root = False
            if output_dir_str:
                try:
                    is_root = run_log_dir.resolve() == Path(output_dir_str).expanduser().resolve()
                except Exception:
                    is_root = False
            if not is_root and not any(run_log_dir.iterdir()):
                run_log_dir.rmdir()
                logger.info("Removed empty per-run log folder: %s", run_log_dir)
        except Exception as exc:
            logger.warning("Could not remove per-run log folder %s: %s", run_log_dir, exc)
