"""
predict.py — Generate predictions for individual games or a list of matchups.
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import date
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.model import load_model
from src.evaluate import kelly_fraction
from src.odds_collection import vig_free_prob

logger = logging.getLogger(__name__)

NBA_TEAM_NAME_TO_ABR = {
    "Atlanta Hawks": "ATL", "Boston Celtics": "BOS", "Brooklyn Nets": "BKN",
    "Charlotte Hornets": "CHA", "Chicago Bulls": "CHI", "Cleveland Cavaliers": "CLE",
    "Dallas Mavericks": "DAL", "Denver Nuggets": "DEN", "Detroit Pistons": "DET",
    "Golden State Warriors": "GSW", "Houston Rockets": "HOU", "Indiana Pacers": "IND",
    "Los Angeles Clippers": "LAC", "Los Angeles Lakers": "LAL", "Memphis Grizzlies": "MEM",
    "Miami Heat": "MIA", "Milwaukee Bucks": "MIL", "Minnesota Timberwolves": "MIN",
    "New Orleans Pelicans": "NOP", "New York Knicks": "NYK", "Oklahoma City Thunder": "OKC",
    "Orlando Magic": "ORL", "Philadelphia 76ers": "PHI", "Phoenix Suns": "PHX",
    "Portland Trail Blazers": "POR", "Sacramento Kings": "SAC", "San Antonio Spurs": "SAS",
    "Toronto Raptors": "TOR", "Utah Jazz": "UTA", "Washington Wizards": "WAS",
}


def predict_game(
    home_team: str,
    away_team: str,
    feature_row: pd.DataFrame,
) -> dict:
    """
    Predict home-win probability for a single game.

    Parameters
    ----------
    home_team : str
        Home team abbreviation.
    away_team : str
        Away team abbreviation.
    feature_row : pd.DataFrame
        Single-row DataFrame with all features (pre-computed).

    Returns
    -------
    dict with keys: home_team, away_team, home_win_prob, away_win_prob
    """
    model, feature_cols, medians = load_model()

    X = feature_row[feature_cols].fillna(medians)
    prob = float(model.predict_proba(X)[:, 1][0])

    return {
        "home_team": home_team,
        "away_team": away_team,
        "home_win_prob": round(prob, 4),
        "away_win_prob": round(1.0 - prob, 4),
    }


def predict_batch(
    feature_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Generate predictions for a batch of games.

    Parameters
    ----------
    feature_df : pd.DataFrame
        One row per game with all model features plus home_team, away_team, game_date.

    Returns
    -------
    pd.DataFrame with predictions appended.
    """
    model, feature_cols, medians = load_model()
    available_cols = [c for c in feature_cols if c in feature_df.columns]
    X = feature_df[available_cols].reindex(columns=feature_cols).fillna(medians)

    raw_probs = model.predict_proba(X)[:, 1]
    df = feature_df.copy()
    df["home_win_prob_model"] = raw_probs  # preserve raw XGBoost output

    # ── Elo-anchored correction ────────────────────────────────────────────
    # XGBoost over-weights home court + situational edges (travel, rest) for
    # large talent-gap games. Fix: shrink the model's deviation from the Elo
    # baseline proportionally to the Elo gap size.
    #
    # Shrink schedule (how much of the model's deviation above Elo we keep):
    #   |elo_diff| <= 50  → keep 100% of model signal (teams are close)
    #   |elo_diff| == 150 → keep 70% of model signal
    #   |elo_diff| >= 350 → keep 35% of model signal (cap — large mismatches)
    ELO_HOME_ADV    = 100   # same constant used in src/elo.py
    SHRINK_RAMP_START = 50  # Elo gap below which no correction applies
    SHRINK_RAMP_SCALE = 500 # additional Elo pts to go from 100% → min shrink
    SHRINK_MIN        = 0.35 # minimum fraction of model signal kept at large gaps

    probs = raw_probs.copy()
    if "elo_diff" in df.columns:
        elo_diff = pd.to_numeric(df["elo_diff"], errors="coerce").fillna(0).values
        # Adjust Elo diff for injuries: home penalty reduces home effective Elo,
        # away penalty reduces away effective Elo (which helps the home team)
        home_pen = pd.to_numeric(df.get("home_availability_penalty_elo", 0), errors="coerce").fillna(0).values
        away_pen = pd.to_numeric(df.get("away_availability_penalty_elo", 0), errors="coerce").fillna(0).values
        elo_diff = elo_diff - home_pen + away_pen
        # Elo win probability for the home team (includes home-court advantage)
        elo_home_prob = 1.0 / (1.0 + 10.0 ** (-(elo_diff + ELO_HOME_ADV) / 400.0))
        # How much the model deviates from the Elo baseline
        model_deviation = probs - elo_home_prob
        # Shrink factor: 1.0 for small gaps, ramps down to SHRINK_MIN for large gaps
        shrink = np.clip(
            1.0 - (np.abs(elo_diff) - SHRINK_RAMP_START) / SHRINK_RAMP_SCALE,
            SHRINK_MIN, 1.0,
        )
        probs = elo_home_prob + shrink * model_deviation
        probs = np.clip(probs, 0.01, 0.99)
        logger.debug(
            "Elo shrink applied — avg shrink: %.2f, avg elo_diff: %.1f",
            shrink.mean(), elo_diff.mean(),
        )

    df["home_win_prob"] = probs
    df["away_win_prob"] = 1.0 - probs

    # ── Score estimation for spread/total combo legs ───────────────────────
    # Uses each team's offensive/defensive efficiency and pace to estimate
    # per-game scores independently of market prices.
    _LEAGUE_AVG_RTG = 113.0
    _HOME_COURT_PTS = 1.5
    try:
        h_off = pd.to_numeric(df.get("home_off_rtg", pd.Series(dtype=float)), errors="coerce")
        a_off = pd.to_numeric(df.get("away_off_rtg", pd.Series(dtype=float)), errors="coerce")
        h_def = pd.to_numeric(df.get("home_def_rtg", pd.Series(dtype=float)), errors="coerce")
        a_def = pd.to_numeric(df.get("away_def_rtg", pd.Series(dtype=float)), errors="coerce")
        h_pace = pd.to_numeric(df.get("home_pace", pd.Series(dtype=float)), errors="coerce")
        a_pace = pd.to_numeric(df.get("away_pace", pd.Series(dtype=float)), errors="coerce")
        if h_off is None or h_off.isna().all():
            raise ValueError("missing rating features")
        avg_pace = (h_pace.fillna(98) + a_pace.fillna(98)) / 2
        home_def_adj = a_def.fillna(_LEAGUE_AVG_RTG) / _LEAGUE_AVG_RTG
        away_def_adj = h_def.fillna(_LEAGUE_AVG_RTG) / _LEAGUE_AVG_RTG
        df["pred_home_score"] = (h_off.fillna(_LEAGUE_AVG_RTG) * home_def_adj * avg_pace / 100 + _HOME_COURT_PTS).round(1)
        df["pred_away_score"] = (a_off.fillna(_LEAGUE_AVG_RTG) * away_def_adj * avg_pace / 100).round(1)
    except Exception:
        pass

    return df


def generate_recommendation_table(
    predictions_df: pd.DataFrame,
    odds_df: Optional[pd.DataFrame] = None,
    edge_threshold: float = 0.03,
) -> pd.DataFrame:
    """
    Build the final recommendation table comparing model probs to market odds.

    Parameters
    ----------
    predictions_df : pd.DataFrame
        Output of predict_batch(), must have home_team, away_team, home_win_prob.
    odds_df : pd.DataFrame | None
        Market odds with home_odds_decimal, away_odds_decimal columns.
        If None, defaults to -110 lines.
    edge_threshold : float
        Minimum edge to flag as a bet.

    Returns
    -------
    pd.DataFrame with recommendation columns.
    """
    df = predictions_df.copy()

    if odds_df is not None and not odds_df.empty:
        odds_cols = [c for c in odds_df.columns if c not in {"home_team", "away_team"}]
        df = df.merge(
            odds_df[["home_team", "away_team"] + odds_cols].drop_duplicates(subset=["home_team", "away_team"]),
            on=["home_team", "away_team"],
            how="left",
        )

    if "market_home_implied" not in df.columns:
        if "market_home_prob" in df.columns:
            df["market_home_implied"] = df["market_home_prob"]
        elif "home_market_implied" in df.columns:
            df["market_home_implied"] = df["home_market_implied"]

    if "market_away_implied" not in df.columns:
        if "market_away_prob" in df.columns:
            df["market_away_implied"] = df["market_away_prob"]
        elif "market_home_implied" in df.columns:
            df["market_away_implied"] = 1.0 - df["market_home_implied"]

    if "home_odds_decimal" not in df.columns:
        df["home_odds_decimal"] = np.nan
    if "away_odds_decimal" not in df.columns:
        df["away_odds_decimal"] = np.nan

    if "market_home_implied" in df.columns:
        df["home_odds_decimal"] = df["home_odds_decimal"].fillna(
            pd.Series(
                np.where(df["market_home_implied"] > 0, 1.0 / df["market_home_implied"], np.nan),
                index=df.index,
            )
        )
    if "market_away_implied" in df.columns:
        df["away_odds_decimal"] = df["away_odds_decimal"].fillna(
            pd.Series(
                np.where(df["market_away_implied"] > 0, 1.0 / df["market_away_implied"], np.nan),
                index=df.index,
            )
        )

    df["home_odds_decimal"] = df["home_odds_decimal"].fillna(1.909)
    df["away_odds_decimal"] = df["away_odds_decimal"].fillna(1.909)

    if "market_home_implied" not in df.columns or "market_away_implied" not in df.columns:
        df[["market_home_implied", "market_away_implied"]] = df.apply(
            lambda r: pd.Series(vig_free_prob(r["home_odds_decimal"], r["away_odds_decimal"])),
            axis=1,
        )
    else:
        missing_market = df["market_home_implied"].isna() | df["market_away_implied"].isna()
        if missing_market.any():
            fallback = df.loc[missing_market].apply(
                lambda r: pd.Series(vig_free_prob(r["home_odds_decimal"], r["away_odds_decimal"])),
                axis=1,
            )
            df.loc[missing_market, ["market_home_implied", "market_away_implied"]] = fallback.values

    # ── Edge calculation ──────────────────────────────────────────────────────
    # Home edge: positive = market undervalues home team
    df["home_edge"] = df["home_win_prob"] - df["market_home_implied"]
    # Away edge: positive = market undervalues away team
    df["away_edge"] = df["away_win_prob"] - df["market_away_implied"]

    # Pick the better side: whichever has the larger edge
    df["bet_side"] = np.where(df["home_edge"] >= df["away_edge"], "home", "away")
    df["bet_team"] = np.where(df["bet_side"] == "home", df["home_team"], df["away_team"])
    df["bet_prob"] = np.where(df["bet_side"] == "home", df["home_win_prob"], df["away_win_prob"])
    df["bet_market"] = np.where(df["bet_side"] == "home", df["market_home_implied"], df["market_away_implied"])
    df["bet_odds_decimal"] = np.where(df["bet_side"] == "home", df["home_odds_decimal"], df["away_odds_decimal"])
    df["best_edge"] = df[["home_edge", "away_edge"]].max(axis=1)

    # ── Minimum win probability filter ───────────────────────────────────────
    # Don't recommend bets on teams the model thinks win < 45% of the time.
    # Even if EV is positive (e.g. model 20%, market 10%), losing 80% of bets
    # is not practical for most traders.
    MIN_WIN_PROB = 0.45

    # ── Kelly sizing on the recommended side ─────────────────────────────────
    df["kelly"] = df.apply(
        lambda r: kelly_fraction(r["bet_prob"], r["bet_odds_decimal"]) * config.KELLY_FRACTION,
        axis=1,
    )
    df["kelly"] = df["kelly"].clip(lower=0, upper=0.25)

    # ── Bet flag ─────────────────────────────────────────────────────────────
    df["bet"] = (df["best_edge"] >= edge_threshold) & (df["bet_prob"] >= MIN_WIN_PROB)

    # Keep backward-compat "edge" column as home_edge (used in display code)
    df["edge"] = df["home_edge"]

    def confidence_label(row: pd.Series) -> str:
        if not row["bet"]:
            return "No Bet"
        e = row["home_edge"] if row["bet_side"] == "home" else row["away_edge"]
        if e >= 0.07:
            return "Strong Edge"
        elif e >= 0.04:
            return "Moderate Edge"
        else:
            return "Marginal"

    df["confidence"] = df.apply(confidence_label, axis=1)

    # Format for display
    ordered_cols = [
        "game_id",
        "game_date", "home_team", "away_team",
        "home_win_prob", "away_win_prob",
        "home_odds_decimal", "away_odds_decimal",
        "market_home_implied", "market_away_implied",
        "home_edge", "away_edge", "best_edge",
        "edge", "bet_side", "bet_team", "bet_prob", "bet_market",
        "bet", "kelly", "confidence",
        "best_source",
        "kalshi_home_prob", "polymarket_home_prob", "sportsbook_home_prob",
    ]
    ordered_cols = [c for c in ordered_cols if c in df.columns]
    extra_cols = [c for c in df.columns if c not in ordered_cols]

    result = df[ordered_cols + extra_cols].sort_values("home_edge", ascending=False).reset_index(drop=True)

    # ── Auto-log all predictions ──────────────────────────────────────────────
    try:
        log_cols = [c for c in [
            "game_id", "game_date", "home_team", "away_team",
            "home_win_prob", "away_win_prob",
            "market_home_implied", "market_away_implied",
            "home_edge", "away_edge", "bet_side", "bet_team", "bet_prob",
            "bet", "kelly", "confidence",
        ] if c in result.columns]
        log_predictions(result[log_cols])
    except Exception as log_err:
        logger.warning("Prediction logging failed: %s", log_err)

    return result


def log_predictions(predictions: pd.DataFrame, log_path: str = config.PREDICTION_LOG) -> None:
    """Append today's predictions to the prediction log CSV, deduplicating by game_id+game_date."""
    log_path = Path(log_path)
    predictions = predictions.copy()
    predictions["logged_at"] = pd.Timestamp.now().isoformat()

    if log_path.exists():
        existing = pd.read_csv(log_path)
        combined = pd.concat([existing, predictions], ignore_index=True)
    else:
        combined = predictions

    # Deduplicate: keep the earliest log entry per game
    dedup_keys = [k for k in ["game_id", "game_date", "home_team", "away_team"] if k in combined.columns]
    if dedup_keys:
        combined = combined.drop_duplicates(subset=dedup_keys, keep="first")

    log_path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(log_path, index=False)
    logger.info("Logged %d predictions to %s (total in log: %d)", len(predictions), log_path, len(combined))
