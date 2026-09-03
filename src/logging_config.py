"""Structured logging configuration for AI Finance Controller."""

import logging
import sys

def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configures structured logging for the application.

    Args:
        level (int): Logging level (default logging.INFO).

    Returns:
        logging.Logger: Configured logger instance.
    """
    logger = logging.getLogger("finance_controller")
    logger.setLevel(level)

    # Avoid duplicate handlers if already set up
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter(
            fmt="[%(asctime)s] [%(levelname)s] [%(name)s] %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        )
        handler.setFormatter(formatter)
        logger.addHandler(handler)

    return logger

logger = setup_logging()
