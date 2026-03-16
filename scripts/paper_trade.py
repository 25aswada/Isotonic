"""
paper_trade.py - Preview or log simulated Kalshi / Polymarket trades.

Usage:
    python scripts/paper_trade.py
    python scripts/paper_trade.py --place
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import config
from scripts.daily_predictions import get_todays_features
from src.injuries import apply_live_availability_adjustments
from src.odds_collection import get_all_market_odds
from src.paper_trading import (
    append_paper_trades,
    build_paper_trade_candidates,
    compute_live_paper_bankroll,
    compute_paper_bankroll,
    load_paper_trades,
    mark_open_trades_to_market,
    sync_paper_trades_with_results,
)
from src.predict import generate_recommendation_table, predict_batch
from src.runtime import setup_project_logging

logger = setup_project_logging(__name__, "paper_trade.log")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Preview or log paper trades")
    p.add_argument("--place", action="store_true", help="Append today's candidates to data/paper_trades.csv")
    p.add_argument("--threshold", type=float, default=config.PAPER_TRADE_EDGE, help="Minimum edge per market")
    p.add_argument(
        "--sources",
        nargs="+",
        default=["kalshi", "polymarket"],
        help="Sources to include (kalshi polymarket)",
    )
    p.add_argument(
        "--bankroll",
        type=float,
        default=config.PAPER_BANKROLL_START,
        help="Starting bankroll used for sizing summary",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("=" * 60)
    logger.info("NBA Paper Trading Engine - %s", pd.Timestamp.now().strftime("%Y-%m-%d"))
    logger.info("=" * 60)

    model_path = Path(config.MODEL_DIR) / "calibrated_model.joblib"
    if not model_path.exists():
        logger.error("No trained model found. Run scripts/train.py first.")
        sys.exit(1)

    if Path(config.MODEL_READY_CSV).exists():
        results_df = pd.read_csv(config.MODEL_READY_CSV)
        if "game_date" in results_df.columns:
            results_df["game_date"] = pd.to_datetime(results_df["game_date"])
        trades_df = sync_paper_trades_with_results(results_df)
    else:
        trades_df = load_paper_trades()

    bankroll_state = compute_paper_bankroll(trades_df, starting_bankroll=args.bankroll)
    available_cash = bankroll_state["available_cash"]

    logger.info("Available paper-trading cash: $%.2f", available_cash)

    logger.info("\n[1/3] Building live features...")
    features = get_todays_features()
    if features.empty:
        logger.info("No games available for paper trading today.")
        return

    logger.info("\n[2/3] Generating predictions...")
    predictions = predict_batch(features)
    predictions = apply_live_availability_adjustments(
        predictions,
        report_date=predictions["game_date"].iloc[0] if "game_date" in predictions.columns and not predictions.empty else None,
    )

    logger.info("\n[3/3] Fetching market prices...")
    odds = get_all_market_odds(snapshot_context="paper_trade_cli")
    marked_trades = mark_open_trades_to_market(trades_df, odds)
    live_bankroll_state = compute_live_paper_bankroll(marked_trades, starting_bankroll=args.bankroll)

    if not marked_trades.empty and "status" in marked_trades.columns:
        open_positions = marked_trades[marked_trades["status"].fillna("open") == "open"].copy()
    else:
        open_positions = marked_trades.copy()

    if not open_positions.empty:
        logger.info(
            "Live open value: $%.2f | Unrealized P/L: %+0.2f | Estimated equity: $%.2f",
            live_bankroll_state["live_open_value"],
            live_bankroll_state["unrealized_pnl"],
            live_bankroll_state["estimated_equity"],
        )
        print("\n" + "=" * 118)
        print(f"{'OPEN POSITIONS MARK-TO-MARKET':^118}")
        print("=" * 118)
        print(
            f"{'Trade ID':<36} {'Source':<12} {'Team':<6} {'Mark':<8} "
            f"{'Value':<10} {'Unrlzd':<10} {'Basis':<10} {'Game'}"
        )
        print("-" * 118)
        for _, row in open_positions.iterrows():
            game = f"{row['away_team']} @ {row['home_team']}"
            print(
                f"{row['trade_id']:<36} "
                f"{row['market_source']:<12} "
                f"{row['contract_team']:<6} "
                f"{row.get('current_mark_price', float('nan')):.3f}   "
                f"${row.get('current_value', float('nan')):<9.2f} "
                f"${row.get('unrealized_pnl', float('nan')):<9.2f} "
                f"{str(row.get('mark_basis', '')):<10} "
                f"{game}"
            )

    recs = generate_recommendation_table(predictions, odds_df=odds, edge_threshold=args.threshold)
    candidates = build_paper_trade_candidates(
        recs,
        bankroll=available_cash,
        edge_threshold=args.threshold,
        sources=args.sources,
    )

    if candidates.empty:
        logger.info("No paper trades met the threshold.")
        return

    print("\n" + "=" * 142)
    print(f"{'PAPER TRADE CANDIDATES':^142}")
    print("=" * 142)
    print(
        f"{'Trade ID':<36} {'Source':<12} {'Team':<6} {'Edge':<8} {'Ask':<8} "
        f"{'Fee':<9} {'Outlay':<10} {'Payout':<10} {'Kelly %':<10} {'Game'}"
    )
    print("-" * 142)
    for _, row in candidates.iterrows():
        game = f"{row['away_team']} @ {row['home_team']}"
        print(
            f"{row['trade_id']:<36} "
            f"{row['market_source']:<12} "
            f"{row['contract_team']:<6} "
            f"{row['edge']:+.1%}   "
            f"{row['entry_price']:.3f}   "
            f"${row['entry_fee']:<8.2f} "
            f"${row['stake']:<9.2f} "
            f"${row['payout_if_win']:<9.2f} "
            f"{row['kelly_pct']:.1%}     "
            f"{game}"
        )

    if args.place:
        combined = append_paper_trades(candidates)
        logger.info("Paper trades logged to %s", config.PAPER_TRADES_CSV)
        logger.info("Total paper trades on file: %d", len(combined))
    else:
        logger.info("Preview only. Re-run with --place to log these trades.")


if __name__ == "__main__":
    main()
