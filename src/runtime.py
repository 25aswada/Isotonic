"""
runtime.py - Shared runtime helpers for logging.
"""

from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

import config


def setup_project_logging(logger_name: str, log_filename: str | None = None) -> logging.Logger:
    """
    Configure a console logger plus a rotating file handler.

    This is idempotent for a given logger name.
    """
    formatter = logging.Formatter(
        "%(asctime)s  %(levelname)-8s  %(name)s  %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    root_logger = logging.getLogger()
    if not getattr(root_logger, "_project_logging_configured", False):
        root_logger.setLevel(logging.INFO)
        console = logging.StreamHandler()
        console.setFormatter(formatter)
        root_logger.addHandler(console)

        log_dir = Path(config.LOG_DIR)
        log_dir.mkdir(parents=True, exist_ok=True)
        root_file = RotatingFileHandler(
            log_dir / "runtime.log",
            maxBytes=1_000_000,
            backupCount=5,
        )
        root_file.setFormatter(formatter)
        root_logger.addHandler(root_file)
        root_logger._project_logging_configured = True

    logger = logging.getLogger(logger_name)
    if getattr(logger, "_project_logging_configured", False):
        return logger

    logger.setLevel(logging.INFO)
    logger.propagate = True

    log_dir = Path(config.LOG_DIR)
    log_dir.mkdir(parents=True, exist_ok=True)
    file_name = log_filename or f"{logger_name.replace('.', '_')}.log"
    file_handler = RotatingFileHandler(log_dir / file_name, maxBytes=1_000_000, backupCount=5)
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)

    logger._project_logging_configured = True
    return logger
