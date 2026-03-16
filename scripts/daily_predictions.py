"""
daily_predictions.py — Pull today's games, generate predictions, compare to market odds.

Usage:
    python scripts/daily_predictions.py [--threshold 0.05]
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import config
from src.data_collection import get_todays_games, pull_all_game_logs, parse_game_logs_to_matchups
from src.feature_engineering import build_features_for_upcoming_games
from src.injuries import apply_live_availability_adjustments
from src.odds_collection import get_all_market_odds
from src.predict import predict_batch, generate_recommendation_table, log_predictions
from src.runtime import setup_project_logging

logger = setup_project_logging(__name__, "daily_predictions.log")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Generate daily NBA predictions")
    p.add_argument("--threshold", type=float, default=0.05, help="Minimum edge to recommend")
    return p.parse_args()


def get_todays_features() -> pd.DataFrame:
    """
    Build features for today's games from the latest completed raw game history.
    """
    todays_games = get_todays_games()
    if todays_games.empty:
        logger.info("No games scheduled for today.")
        return pd.DataFrame()

    logger.info("Found %d games today", len(todays_games))

    logger.info("Loading cached historical game logs...")
    raw_logs = pull_all_game_logs(force=False)
    if raw_logs.empty:
        logger.error("No historical game logs available for feature generation.")
        return pd.DataFrame()

    matchups = parse_game_logs_to_matchups(raw_logs)
    features = build_features_for_upcoming_games(
        todays_games,
        raw_logs=raw_logs,
        historical_matchups=matchups,
    )
    logger.info("Built %d feature rows for today's games", len(features))
    return features


def main() -> None:
    args = parse_args()

    logger.info("=" * 60)
    logger.info("NBA Daily Prediction Engine — %s", pd.Timestamp.now().strftime("%Y-%m-%d"))
    logger.info("=" * 60)

    # Check model is trained
    model_path = Path(config.MODEL_DIR) / "calibrated_model.joblib"
    if not model_path.exists():
        logger.error("No trained model found. Run scripts/train.py first.")
        sys.exit(1)

    # Get today's features
    logger.info("\n[1/3] Building features for today's games...")
    features = get_todays_features()
    if features.empty:
        logger.info("No predictions to generate.")
        return

    # Generate predictions
    logger.info("\n[2/3] Generating predictions...")
    predictions = predict_batch(features)
    predictions = apply_live_availability_adjustments(
        predictions,
        report_date=predictions["game_date"].iloc[0] if "game_date" in predictions.columns and not predictions.empty else None,
    )

    # Get live odds
    logger.info("\n[3/3] Fetching live odds...")
    odds = get_all_market_odds(snapshot_context="daily_predictions")

    # Build recommendation table
    recs = generate_recommendation_table(predictions, odds_df=odds, edge_threshold=args.threshold)

    # Display
    print("\n" + "=" * 80)
    print(f"{'NBA GAME PREDICTIONS':^80}")
    print(f"{'Edge Threshold: ' + str(args.threshold):^80}")
    print("=" * 80)

    if recs.empty:
        print("No games with sufficient data for predictions today.")
        return

    bets = recs[recs["bet"] == True]
    print(f"\n{len(bets)} bet(s) found | Edge threshold: {args.threshold:.0%}\n")

    # Pretty table
    print(f"{'Game':<25} {'Model P(Home)':<15} {'Market Implied':<16} {'Edge':<8} {'Bet?':<6} {'Kelly':<8} {'Signal'}")
    print("-" * 90)
    for _, r in recs.iterrows():
        game = f"{r.get('away_team', '?')} @ {r.get('home_team', '?')}"
        model_p = f"{r['home_win_prob']:.1%}"
        market_p = f"{r.get('market_home_implied', 0):.1%}"
        edge = f"{r['edge']:+.1%}"
        bet = "YES ✓" if r["bet"] else "NO"
        kelly = f"{r['kelly']:.1%}" if r["bet"] else "—"
        signal = r.get("confidence", "")
        print(f"{game:<25} {model_p:<15} {market_p:<16} {edge:<8} {bet:<6} {kelly:<8} {signal}")

    print("\n" + "=" * 80)

    # Log predictions
    log_predictions(recs)
    logger.info("Predictions logged to %s", config.PREDICTION_LOG)


if __name__ == "__main__":
    main()
