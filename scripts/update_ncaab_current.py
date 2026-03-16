"""
update_ncaab_current.py - Fetch current NCAA team stats and projected bracket.

Usage:
    python scripts/update_ncaab_current.py
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import ncaab_config
from src.ncaab_live import write_current_projection_artifacts
from src.runtime import setup_project_logging
import pandas as pd

logger = setup_project_logging(__name__, "update_ncaab_current.log")


def main() -> None:
    logger.info("=" * 60)
    logger.info("Current March Madness Projection Updater")
    logger.info("=" * 60)
    team_features, bracket_df = write_current_projection_artifacts()
    all_team_count = 0
    if ncaab_config.NCAAB_CURRENT_ALL_TEAM_FEATURES_CSV.exists():
        all_team_count = len(pd.read_csv(ncaab_config.NCAAB_CURRENT_ALL_TEAM_FEATURES_CSV))
    logger.info("Current projected field teams: %d", len(team_features))
    logger.info("Current all-team features: %d", all_team_count)
    logger.info("Current projected bracket games: %d", len(bracket_df))
    logger.info("Projection date: %s", ncaab_config.CURRENT_PROJECTION_DATE)


if __name__ == "__main__":
    main()
