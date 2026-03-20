"""
build_ncaab_dataset.py - Download NCAA data and build March Madness features.

Usage:
    python scripts/build_ncaab_dataset.py [--force]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import ncaab_config
from src.ncaab_data import download_all_raw_files, load_raw_csv
from src.ncaab_features import (
    build_regular_season_model_dataset,
    build_team_season_features,
    build_tournament_model_dataset,
)
from src.runtime import setup_project_logging

logger = setup_project_logging(__name__, "build_ncaab_dataset.log")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Build March Madness NCAA dataset")
    parser.add_argument("--force", action="store_true", help="Re-download NCAA source CSVs")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.info("=" * 60)
    logger.info("March Madness Dataset Builder")
    logger.info("=" * 60)

    download_all_raw_files(force=args.force)

    regular_season_results = load_raw_csv("MRegularSeasonDetailedResults.csv")
    tourney_results = load_raw_csv("MNCAATourneyDetailedResults.csv")
    tourney_seeds = load_raw_csv("MNCAATourneySeeds.csv")
    teams = load_raw_csv("MTeams.csv")
    massey_ordinals = load_raw_csv("MMasseyOrdinals.csv")

    logger.info("Building NCAA team-season features...")
    team_features = build_team_season_features(
        regular_season_results=regular_season_results,
        tourney_seeds=tourney_seeds,
        massey_ordinals=massey_ordinals,
        teams=teams,
    )
    team_features.to_csv(ncaab_config.NCAAB_TEAM_FEATURES_CSV, index=False)
    logger.info("Saved %s (%d rows)", ncaab_config.NCAAB_TEAM_FEATURES_CSV, len(team_features))

    logger.info("Building NCAA all-team season features...")
    all_team_features = build_team_season_features(
        regular_season_results=regular_season_results,
        tourney_seeds=tourney_seeds,
        massey_ordinals=massey_ordinals,
        teams=teams,
        include_all_teams=True,
    )
    all_team_features.to_csv(ncaab_config.NCAAB_ALL_TEAM_FEATURES_CSV, index=False)
    logger.info("Saved %s (%d rows)", ncaab_config.NCAAB_ALL_TEAM_FEATURES_CSV, len(all_team_features))

    logger.info("Building NCAA tournament model dataset...")
    model_ready = build_tournament_model_dataset(
        tourney_results=tourney_results,
        team_features=team_features,
    )
    model_ready.to_csv(ncaab_config.NCAAB_MODEL_READY_CSV, index=False)
    logger.info("Saved %s (%d rows, %d columns)", ncaab_config.NCAAB_MODEL_READY_CSV, len(model_ready), len(model_ready.columns))

    logger.info("Building augmented NCAA model dataset with regular-season auxiliary rows...")
    regular_aux = build_regular_season_model_dataset(
        regular_season_results=regular_season_results,
        team_features=all_team_features,
        sample_weight_multiplier=ncaab_config.REGULAR_SEASON_AUX_WEIGHT,
    )
    model_ready_augmented = pd.concat([model_ready, regular_aux], ignore_index=True)
    model_ready_augmented = model_ready_augmented.sort_values(["Season", "DayNum", "team_a"]).reset_index(drop=True)
    model_ready_augmented.to_csv(ncaab_config.NCAAB_MODEL_READY_AUGMENTED_CSV, index=False)
    logger.info(
        "Saved %s (%d rows, %d columns)",
        ncaab_config.NCAAB_MODEL_READY_AUGMENTED_CSV,
        len(model_ready_augmented),
        len(model_ready_augmented.columns),
    )


if __name__ == "__main__":
    main()
