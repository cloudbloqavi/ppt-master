"""
Logging Configuration Module for Presentation Builder Agent Runner

Handles creation of file-based logger handlers when --log-file is selected,
allowing execution logs to be co-located with output artifacts.
"""
import os
import shutil
import logging
from pathlib import Path
from datetime import datetime
from agent_runner.config import ARGS, logger

# Global track of the active log file path.
_LOG_FILE_PATH: Path | None = None
# Per-run subfolder (under OUTPUT_ARTIFACTS_DIR) that holds the log files while a
# run is in progress. Computed once, shared by the execution log and the status
# progress log so both land in the same place.
_RUN_LOG_DIR: Path | None = None


def get_run_log_dir() -> Path | None:
    """Return (creating once) the per-run subfolder that log files are written to.

    Log files must never be written to the OUTPUT_ARTIFACTS_DIR *root*: that root
    holds one output subfolder per run, and loose ``run_agent_*.log`` /
    ``status_progress_*.log`` files there accumulate across runs — especially when
    a run fails or is killed before the end-of-run cleanup can fire. Writing them
    into a dedicated ``_run_logs_<timestamp>/`` folder from the very first line
    keeps the root clean and lets ``copy_output_artifacts`` relocate them into the
    final project folder once its name is known.

    The result is cached, so the execution log and status progress log (configured
    in separate calls) share one folder. Falls back to the root only if the
    subfolder cannot be created.
    """
    global _RUN_LOG_DIR
    if _RUN_LOG_DIR is not None:
        return _RUN_LOG_DIR

    output_dir = os.environ.get("OUTPUT_ARTIFACTS_DIR") or "."
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    run_dir = Path(output_dir) / f"_run_logs_{timestamp}"
    try:
        run_dir.mkdir(parents=True, exist_ok=True)
        _RUN_LOG_DIR = run_dir
    except Exception as e:
        # Never fall back to the artifacts root itself — loose log files there are
        # exactly what this module exists to prevent. Degrade to a stable
        # ``_run_logs/`` subfolder; only if even that cannot be created do we use
        # the root as a true last resort.
        fallback = Path(output_dir) / "_run_logs"
        try:
            fallback.mkdir(parents=True, exist_ok=True)
            logger.warning(
                "Failed to create per-run log folder %s (falling back to %s): %s",
                run_dir, fallback, e,
            )
            _RUN_LOG_DIR = fallback
        except Exception as e2:
            logger.warning(
                "Failed to create per-run log folder %s and fallback %s "
                "(last-resort: artifacts root): %s / %s",
                run_dir, fallback, e, e2,
            )
            _RUN_LOG_DIR = Path(output_dir)
    return _RUN_LOG_DIR


def sweep_orphan_root_logs() -> None:
    """Relocate any pre-existing loose log files at the OUTPUT_ARTIFACTS_DIR root.

    The current pipeline writes run/status logs into a per-run ``_run_logs_<ts>/``
    folder and then relocates them into each project folder (see
    :func:`get_run_log_dir` and ``finalize_log_placement``). But older runner
    versions — and runs killed before end-of-run cleanup — could leave loose
    ``run_agent_*.log`` / ``status_progress_*.log`` (and a stray
    ``run_manifest.json``) directly at the artifacts root. Those orphans are never
    cleaned automatically and violate the "no log files at the artifacts root"
    invariant.

    This moves any such loose files into a single ``_run_logs_orphaned/`` subfolder,
    keeping the root clean without destroying log data. Best-effort and idempotent:
    failures are logged and skipped. Call once at the very start of a run, before
    the new run's own logs are created (so the current run's logs are never swept).
    """
    output_dir_str = os.environ.get("OUTPUT_ARTIFACTS_DIR")
    if not output_dir_str:
        return
    root = Path(output_dir_str).expanduser()
    try:
        if not root.is_dir():
            return
    except Exception:
        return

    # Only loose files directly at the root match — glob is non-recursive, so logs
    # already inside project folders or _run_logs_* folders are left untouched.
    orphans: list[Path] = []
    for pattern in ("run_agent_*.log", "status_progress_*.log"):
        orphans.extend(p for p in root.glob(pattern) if p.is_file())
    root_manifest = root / "run_manifest.json"  # belongs inside a project, never at root
    if root_manifest.is_file():
        orphans.append(root_manifest)

    if not orphans:
        return

    quarantine = root / "_run_logs_orphaned"
    try:
        quarantine.mkdir(parents=True, exist_ok=True)
    except Exception as e:
        logger.warning("Could not create orphan-log folder %s: %s", quarantine, e)
        return

    moved = 0
    for src in orphans:
        dest = quarantine / src.name
        if dest.exists():
            # Disambiguate same-named orphans from different runs.
            try:
                stamp = int(src.stat().st_mtime)
            except Exception:
                stamp = 0
            dest = quarantine / f"{src.stem}_{stamp}{src.suffix}"
        try:
            shutil.move(str(src), str(dest))
            moved += 1
        except Exception as e:
            logger.warning("Could not relocate orphan log %s: %s", src, e)

    if moved:
        logger.info(
            "Relocated %d loose log file(s) from the artifacts root into %s",
            moved, quarantine,
        )


def setup_file_logging():
    """If log_file CLI argument is passed, add a FileHandler to the logging setup with a dynamic filename based on timestamp."""
    global _LOG_FILE_PATH
    if not ARGS.log_file:
        return

    try:
        # Logs go into a per-run subfolder, never the shared artifacts root.
        output_path = get_run_log_dir()

        # Format: run_agent_YYYYMMDD_HHMMSS.log
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        log_filepath = output_path / f"run_agent_{timestamp}.log"
        
        file_handler = logging.FileHandler(log_filepath, encoding="utf-8")
        file_handler.setFormatter(
            logging.Formatter("%(asctime)s [%(levelname)s] %(name)s: %(message)s")
        )
        # Add to the root logger so it catches all library logs + our custom logs
        logging.getLogger().addHandler(file_handler)
        _LOG_FILE_PATH = log_filepath
        logger.info("Writing execution logs simultaneously to file: %s", log_filepath)
    except Exception as e:
        logger.warning("Failed to configure file logging: %s", e)


def get_log_file_path() -> Path | None:
    """Return the path to the active execution log file."""
    return _LOG_FILE_PATH
