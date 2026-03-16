"""
ncaab_data.py - NCAA March Madness data download and load helpers.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pandas as pd
import requests

import ncaab_config

logger = logging.getLogger(__name__)


def ensure_directories() -> None:
    """Create NCAA data and model directories if they do not exist."""
    for path in [
        ncaab_config.NCAAB_DATA_DIR,
        ncaab_config.NCAAB_RAW_DIR,
        ncaab_config.NCAAB_PROCESSED_DIR,
        ncaab_config.NCAAB_PLOTS_DIR,
        ncaab_config.NCAAB_MODEL_DIR,
    ]:
        path.mkdir(parents=True, exist_ok=True)


def raw_file_path(file_name: str) -> Path:
    """Return the local path for a raw NCAA file."""
    return ncaab_config.NCAAB_RAW_DIR / file_name


def download_raw_file(file_name: str, force: bool = False) -> Path:
    """Download a single NCAA CSV from the public data mirror."""
    ensure_directories()
    destination = raw_file_path(file_name)
    if destination.exists() and not force:
        logger.info("Using cached NCAA file %s", destination.name)
        return destination

    url = f"{ncaab_config.NCAAB_DATA_BASE_URL}/{file_name}?download=true"
    logger.info("Downloading %s", url)
    response = requests.get(url, timeout=60)
    response.raise_for_status()
    destination.write_bytes(response.content)
    return destination


def download_all_raw_files(force: bool = False) -> dict[str, Path]:
    """Ensure all required NCAA source files are available locally."""
    files: dict[str, Path] = {}
    for file_name in ncaab_config.NCAAB_RAW_FILES:
        files[file_name] = download_raw_file(file_name, force=force)
    return files


def load_raw_csv(file_name: str) -> pd.DataFrame:
    """Load a cached NCAA CSV by file name."""
    path = raw_file_path(file_name)
    if not path.exists():
        download_raw_file(file_name, force=False)
    return pd.read_csv(path)
