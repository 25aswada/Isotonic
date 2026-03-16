"""
settle_results.py — Fetch yesterday's NBA scores and mark predictions as won/lost.

Usage:
    python scripts/settle_results.py [--date 2026-03-11]
"""

from __future__ import annotations

import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import numpy as np

import config
from src.runtime import setup_project_logging

logger = setup_project_logging(__name__, "settle_results.log")


def fetch_results(target_date: date) -> pd.DataFrame:
    """Pull completed game results for a given date from nba_api."""
    from nba_api.stats.endpoints import LeagueGameFinder
    from nba_api.stats.static import teams as nba_teams_static

    date_str = target_date.strftime("%m/%d/%Y")
    logger.info("Fetching results for %s", date_str)

    finder = LeagueGameFinder(
        date_from_nullable=date_str,
        date_to_nullable=date_str,
        league_id_nullable="00",
    )
    logs = finder.get_data_frames()[0]

    if logs.empty:
        logger.info("No completed games found for %s", date_str)
        return pd.DataFrame()

    id_to_abbr = {t["id"]: t["abbreviation"] for t in nba_teams_static.get_teams()}

    rows = []
    for game_id, group in logs.groupby("GAME_ID"):
        if len(group) != 2:
            continue
        home_row = group[group["MATCHUP"].str.contains(r"vs\.", regex=True)]
        away_row = group[group["MATCHUP"].str.contains(r"@", regex=True)]
        if home_row.empty or away_row.empty:
            continue
        home = home_row.iloc[0]
        away = away_row.iloc[0]

        home_abbr = id_to_abbr.get(home["TEAM_ID"])
        away_abbr = id_to_abbr.get(away["TEAM_ID"])
        if not home_abbr or not away_abbr:
            continue

        home_win = 1 if home["WL"] == "W" else 0
        rows.append({
            "game_id": game_id,
            "game_date": pd.to_datetime(target_date),
            "home_team": home_abbr,
            "away_team": away_abbr,
            "home_pts": int(home["PTS"]),
            "away_pts": int(away["PTS"]),
            "home_win": home_win,
        })

    results = pd.DataFrame(rows)
    logger.info("Found %d completed games", len(results))
    return results


def settle_log(results: pd.DataFrame) -> tuple[int, int]:
    """
    Match results to unsettled predictions in the prediction log.
    Returns (settled_count, already_settled_count).
    """
    log_path = Path(config.PREDICTION_LOG)
    if not log_path.exists():
        logger.info("No prediction log found at %s", log_path)
        return 0, 0

    log = pd.read_csv(log_path)
    if log.empty:
        return 0, 0

    if "game_date" in log.columns:
        log["game_date"] = pd.to_datetime(log["game_date"], errors="coerce")
    if "game_date" in results.columns:
        results["game_date"] = pd.to_datetime(results["game_date"], errors="coerce")

    already_settled = log["home_win"].notna().sum() if "home_win" in log.columns else 0

    # Merge results onto log by (home_team, away_team, game_date)
    results["_game_day"] = results["game_date"].dt.normalize()
    log["_game_day"] = log["game_date"].dt.normalize() if "game_date" in log.columns else pd.NaT

    merged = log.merge(
        results[["home_team", "away_team", "_game_day", "home_win", "home_pts", "away_pts"]],
        on=["home_team", "away_team", "_game_day"],
        how="left",
        suffixes=("", "_result"),
    )

    # Fill in outcome columns
    for col in ["home_win", "home_pts", "away_pts"]:
        result_col = f"{col}_result"
        if result_col in merged.columns:
            if col in merged.columns:
                merged[col] = merged[col].combine_first(merged[result_col])
            else:
                merged[col] = merged[result_col]
            merged = merged.drop(columns=[result_col])

    merged = merged.drop(columns=["_game_day"])

    # Compute flat P&L per bet using actual market execution price
    if "home_win" in merged.columns:
        is_bet = merged.get("bet", pd.Series(False, index=merged.index)).fillna(False)
        bet_side = merged.get("bet_side", pd.Series("home", index=merged.index)).fillna("home")

        # Determine which team we bet on won
        won = np.where(
            bet_side == "home",
            merged["home_win"] == 1,
            merged["home_win"] == 0,
        )

        # Use actual ask price from the recommended market for accurate payout odds
        # Polymarket/Kalshi: payout = 1/ask_price (binary contract pays $1 if correct)
        # Sportsbook: decimal odds stored directly in home/away_odds_decimal
        def _execution_odds(row, side):
            source = str(row.get("best_source", "")).lower()
            ask_cols = {
                "kalshi":      f"kalshi_{side}_ask_prob",
                "polymarket":  f"polymarket_{side}_ask_prob",
            }
            if source in ask_cols:
                ask = pd.to_numeric(row.get(ask_cols[source]), errors="coerce")
                if pd.notna(ask) and 0 < ask < 1:
                    return 1.0 / ask
            # Fallback: use stored decimal odds (vig-free)
            odds_col = "home_odds_decimal" if side == "home" else "away_odds_decimal"
            return pd.to_numeric(row.get(odds_col), errors="coerce")

        odds_used = merged.apply(
            lambda r: _execution_odds(r, r.get("bet_side", "home") or "home"), axis=1
        )

        merged["flat_pnl"] = np.where(
            is_bet & pd.notna(merged["home_win"]),
            np.where(won, odds_used - 1.0, -1.0),
            np.nan,
        )

    merged.to_csv(log_path, index=False)

    newly_settled = merged["home_win"].notna().sum() - already_settled
    logger.info("Settled %d new predictions (total settled: %d)",
                newly_settled, merged["home_win"].notna().sum())
    return int(newly_settled), int(already_settled)


def settle_paper_trades_log(results: pd.DataFrame) -> tuple[int, int]:
    from src.paper_trading import sync_paper_trades_with_results, load_paper_trades
    trades_before = load_paper_trades()
    if trades_before.empty:
        return 0, 0
    already = int((trades_before.get("status", pd.Series()) == "settled").sum())
    # Coerce game_id to string in both to avoid int64/object merge error
    results_copy = results.copy()
    results_copy["game_id"] = results_copy["game_id"].astype(str)
    sync_paper_trades_with_results(results_copy)
    trades_after = load_paper_trades()
    now_settled = int((trades_after.get("status", pd.Series()) == "settled").sum())
    newly = now_settled - already
    logger.info("Paper trades: %d newly settled (total settled: %d)", newly, now_settled)
    return newly, already


def main() -> None:
    parser = argparse.ArgumentParser(description="Settle NBA prediction log with actual results")
    parser.add_argument("--date", default=None,
                        help="Date to settle (YYYY-MM-DD). Defaults to yesterday.")
    args = parser.parse_args()

    if args.date:
        target = date.fromisoformat(args.date)
    else:
        target = date.today() - timedelta(days=1)

    results = fetch_results(target)
    if results.empty:
        logger.info("Nothing to settle.")
        return

    newly_settled, already = settle_log(results)
    logger.info("Prediction log — newly settled: %d | previously settled: %d", newly_settled, already)

    pt_newly, pt_already = settle_paper_trades_log(results)
    logger.info("Paper trades — newly settled: %d | previously settled: %d", pt_newly, pt_already)


if __name__ == "__main__":
    main()
