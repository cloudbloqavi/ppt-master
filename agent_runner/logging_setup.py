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


def setup_file_logging():
    """If log_file CLI argument is passed, add a FileHandler to the logging setup with a dynamic filename based on timestamp."""
    global _LOG_FILE_PATH
    if not ARGS.log_file:
        return

    output_dir = os.environ.get("OUTPUT_ARTIFACTS_DIR")
    if not output_dir:
        # Fallback for self-test or local runs without environment variables set
        output_dir = "."

    try:
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
        _LOG_FILE_PATH = log_filepath
        logger.info("Writing execution logs simultaneously to file: %s", log_filepath)
    except Exception as e:
        logger.warning("Failed to configure file logging: %s", e)


def get_log_file_path() -> Path | None:
    """Return the path to the active execution log file."""
    return _LOG_FILE_PATH
