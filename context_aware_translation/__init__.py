"""
Term disambiguation package.
"""

import logging
import logging.handlers
import os
import sys
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from context_aware_translation.config import Config

# Track if we've already configured logging to avoid duplicate handlers
_logging_configured = False

# Default log file location
DEFAULT_LOG_MAX_BYTES = 10 * 1024 * 1024  # 10MB
DEFAULT_LOG_BACKUP_COUNT = 50


def configure_logging(config: "Config") -> None:
    """
    Configure logging with Config.

    Uses config.log_dir for the log file location.
    Can be called multiple times - if called again, it updates
    the file handler location while preserving the console handler.

    Args:
        config: Config instance with log_dir set
    """
    global _logging_configured

    # Skip configuration if we're in a test environment (pytest will handle it)
    is_test_env = (
        "pytest" in sys.modules
        or "_pytest" in sys.modules
        or any("pytest" in arg.lower() for arg in sys.argv)
        or os.environ.get("PYTEST_CURRENT_TEST") is not None
    )

    if is_test_env:
        _logging_configured = True
        return

    root_logger = logging.root

    assert config.log_dir is not None, "log_dir should be set after Config.__post_init__"
    log_file_path = config.log_dir / "app.log"
    # Create formatters
    detailed_formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s", datefmt="%Y-%m-%d %H:%M:%S"
    )
    console_formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", datefmt="%H:%M:%S")

    # Set up console handler (only if not already configured)
    # Check if we already have a console handler (StreamHandler writing to stderr)
    has_console_handler = any(
        isinstance(h, logging.StreamHandler) and h.stream is sys.stderr for h in root_logger.handlers
    )
    if not has_console_handler:
        console_handler = logging.StreamHandler(sys.stderr)
        console_handler.setFormatter(console_formatter)
        console_handler.setLevel(logging.INFO)  # Only INFO and above to console
        root_logger.addHandler(console_handler)

    # Remove existing file handlers (if any) to update location
    file_handlers = [h for h in root_logger.handlers if isinstance(h, logging.handlers.RotatingFileHandler)]
    for handler in file_handlers:
        root_logger.removeHandler(handler)
        handler.close()

    # Create file handler with rotation
    try:
        log_file_path.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.handlers.RotatingFileHandler(
            filename=str(log_file_path),
            maxBytes=DEFAULT_LOG_MAX_BYTES,
            backupCount=DEFAULT_LOG_BACKUP_COUNT,
            encoding="utf-8",
        )
        file_handler.setFormatter(detailed_formatter)
        file_handler.setLevel(logging.DEBUG)  # All levels to file

        root_logger.setLevel(logging.DEBUG)
        root_logger.addHandler(file_handler)
        root_logger.info(f"Logging to file: {log_file_path.absolute()}")
    except (PermissionError, OSError) as e:
        root_logger.warning(f"Could not create log file at {log_file_path}: {e}")
        root_logger.warning("Continuing with console logging only")

    _logging_configured = True
