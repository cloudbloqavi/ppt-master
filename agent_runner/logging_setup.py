"""
Logging Configuration Module for Presentation Builder Agent Runner

Handles creation of file-based logger handlers when --log-file is selected,
allowing execution logs to be co-located with output artifacts.
"""
import os
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
        logger.warning(
            "Failed to create per-run log folder %s (falling back to root): %s",
            run_dir, e,
        )
        _RUN_LOG_DIR = Path(output_dir)
    return _RUN_LOG_DIR


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
