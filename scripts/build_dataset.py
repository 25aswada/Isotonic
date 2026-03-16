"""
build_dataset.py — End-to-end pipeline: collect raw data → engineer features → save.

Usage:
    python scripts/build_dataset.py [--force] [--seasons 2021-22 2022-23]
    python scripts/build_dataset.py --skip-player-logs   # skip slow player-log pull
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from src.data_collection import (
    pull_all_game_logs,
    parse_game_logs_to_matchups,
    save_to_db,
)
from src.feature_engineering import build_all_features
from src.player_availability import (
    pull_all_player_game_logs,
    build_team_game_availability,
    merge_availability_into_features,
    build_star_player_form,
    merge_star_form_into_features,
)
from src.runtime import setup_project_logging

logger = setup_project_logging(__name__, "build_dataset.log")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Build NBA prediction dataset")
    p.add_argument("--force", action="store_true",
                   help="Re-pull all data even if cached CSVs exist")
    p.add_argument("--seasons", nargs="+", default=None,
                   help="Specific seasons to process (e.g. 2021-22 2022-23)")
    p.add_argument("--skip-player-logs", action="store_true",
                   help="Skip player game log pull (use cached or skip availability features)")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    seasons = args.seasons or config.SEASONS

    logger.info("=" * 60)
    logger.info("NBA Prediction Dataset Builder")
    logger.info("Seasons: %s", seasons)
    logger.info("=" * 60)

    # ── Step 1: Raw game logs ────────────────────────────────────────────────
    logger.info("\n[1/4] Pulling game logs...")
    raw_logs = pull_all_game_logs(seasons=seasons, force=args.force)
    logger.info("  Collected %d team-game rows", len(raw_logs))

    # ── Step 2: Parse into matchup-level table ───────────────────────────────
    logger.info("\n[2/4] Parsing game logs into matchups...")
    matchups = parse_game_logs_to_matchups(raw_logs)
    logger.info("  Parsed %d unique games", len(matchups))

    # ── Step 3: Feature engineering (rolling stats, Elo, rest, etc.) ────────
    logger.info("\n[3/4] Engineering features...")
    features = build_all_features(matchups, raw_logs)
    logger.info("  Feature matrix: %d games × %d features", len(features), len(features.columns))

    # ── Step 4: Player availability features ────────────────────────────────
    if not args.skip_player_logs:
        logger.info("\n[4/4] Building player availability features...")
        avail_cache = Path("data/processed/player_availability.csv")

        if avail_cache.exists() and not args.force:
            logger.info("  Loading availability features from cache: %s", avail_cache)
            avail_df = pd.read_csv(avail_cache)
        else:
            logger.info("  Pulling player game logs for %d seasons...", len(seasons))
            player_logs = pull_all_player_game_logs(seasons, force=args.force)
            if player_logs.empty:
                logger.warning("  No player logs retrieved; skipping availability features.")
                avail_df = pd.DataFrame()
            else:
                logger.info("  Pulled %d player-game rows across all seasons", len(player_logs))
                avail_df = build_team_game_availability(player_logs)
                if not avail_df.empty:
                    avail_cache.parent.mkdir(parents=True, exist_ok=True)
                    avail_df.to_csv(avail_cache, index=False)
                    logger.info("  Cached availability features to %s", avail_cache)

        if not avail_df.empty:
            before_cols = len(features.columns)
            features = merge_availability_into_features(features, avail_df)
            logger.info("  Added %d availability columns (total features: %d)",
                        len(features.columns) - before_cols, len(features.columns))
        else:
            logger.warning("  Availability features unavailable; model will train without them.")

        # ── Star player rolling form ─────────────────────────────────────────
        star_cache = Path("data/processed/star_player_form.csv")
        # Ensure player_logs is loaded (may have been skipped if avail cache was used)
        if "player_logs" not in dir() or player_logs.empty:
            logger.info("  Loading player logs from cache for star form...")
            player_logs = pull_all_player_game_logs(seasons, force=False)
        if star_cache.exists() and not args.force:
            logger.info("  Loading star form features from cache: %s", star_cache)
            star_df = pd.read_csv(star_cache)
        elif not player_logs.empty:
            logger.info("  Computing star player rolling form...")
            star_df = build_star_player_form(player_logs)
            if not star_df.empty:
                star_df.to_csv(star_cache, index=False)
                logger.info("  Cached star form features to %s", star_cache)
        else:
            star_df = pd.DataFrame()

        if not star_df.empty:
            before_cols = len(features.columns)
            features = merge_star_form_into_features(features, star_df)
            logger.info("  Added %d star form columns (total features: %d)",
                        len(features.columns) - before_cols, len(features.columns))
    else:
        logger.info("\n[4/4] Skipping player logs (--skip-player-logs set).")

    # ── Save ─────────────────────────────────────────────────────────────────
    save_to_db(matchups, "matchups")
    save_to_db(features, "model_features")

    # model_ready.csv is written inside build_all_features via assemble_features;
    # overwrite it now with the availability-enriched version
    out_path = Path(config.MODEL_READY_CSV)
    features.to_csv(out_path, index=False)
    logger.info("\n✓ Dataset build complete.")
    logger.info("  model_ready.csv → %s  (%d rows × %d cols)",
                out_path, len(features), len(features.columns))
    logger.info("  SQLite DB       → %s", config.DB_PATH)


if __name__ == "__main__":
    main()
