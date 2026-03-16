"""
ncaab_live_model.py - Simplified in-game NCAA win probability model.

Matches the NBA live model structure:
  - score differential + time remaining
  - Elo-based live spread prior
  - optional pre-game model probability
  - live weight increases as the game progresses
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.stats import norm

import config

NCAAB_REGULATION_SECONDS = 40 * 60
NCAAB_ELO_POINTS_PER_POINT = 26.0
NCAAB_HOME_ADV_POINTS = 3.0
NCAAB_SCORE_NOISE_PER_MINUTE = 2.30


def live_win_prob(
    home_score: float,
    away_score: float,
    seconds_remaining: float,
    home_elo: float = config.ELO_BASE,
    away_elo: float = config.ELO_BASE,
    pregame_home_prob: float | None = None,
    neutral_site: bool = False,
) -> tuple[float, float]:
    """
    NCAA in-game win probability using the same blend structure as the NBA path.

    Signal 1:
      score + clock + Elo-derived spread

    Signal 2:
      pre-game calibrated model probability, if available
    """
    seconds_remaining = max(float(seconds_remaining), 0.0)
    minutes_remaining = seconds_remaining / 60.0
    total_minutes = NCAAB_REGULATION_SECONDS / 60.0
    score_diff = float(home_score) - float(away_score)

    home_adv = 0.0 if neutral_site else NCAAB_HOME_ADV_POINTS
    elo_diff = float(home_elo) - float(away_elo)
    elo_spread = (elo_diff / NCAAB_ELO_POINTS_PER_POINT) + home_adv

    time_weight = minutes_remaining / total_minutes
    adjusted_spread = elo_spread * time_weight
    sigma = NCAAB_SCORE_NOISE_PER_MINUTE * np.sqrt(max(minutes_remaining, 0.01))
    z = (score_diff + adjusted_spread) / sigma
    stern_prob = float(np.clip(norm.cdf(z), 0.01, 0.99))

    if pregame_home_prob is not None:
        pg = float(np.clip(pregame_home_prob, 0.01, 0.99))
    else:
        pg_z = elo_spread / (NCAAB_SCORE_NOISE_PER_MINUTE * np.sqrt(total_minutes))
        pg = float(np.clip(norm.cdf(pg_z), 0.01, 0.99))

    live_weight = float(np.clip(1.0 - (minutes_remaining / total_minutes), 0.0, 1.0))
    home_prob = live_weight * stern_prob + (1.0 - live_weight) * pg
    home_prob = float(np.clip(home_prob, 0.01, 0.99))
    return home_prob, 1.0 - home_prob


def enrich_with_market_odds(live_df: pd.DataFrame, odds_df: pd.DataFrame) -> pd.DataFrame:
    """
    Join NCAA market odds onto live games and compute live edge fields.

    NCAA live rows use normalized match names because the live scoreboard
    abbreviations do not match the market data schema.
    """
    if live_df.empty or odds_df.empty:
        return live_df

    keep = [c for c in [
        "home_team", "away_team",
        "kalshi_home_prob", "kalshi_away_prob",
        "kalshi_home_ask_prob", "kalshi_away_ask_prob",
        "polymarket_home_prob", "polymarket_away_prob",
        "polymarket_home_ask_prob", "polymarket_away_ask_prob",
        "sportsbook_home_prob", "sportsbook_away_prob",
        "market_home_implied", "market_away_implied",
    ] if c in odds_df.columns]
    if not keep:
        return live_df

    join_home_col = "home_market_team" if "home_market_team" in live_df.columns else "home_model_team"
    join_away_col = "away_market_team" if "away_market_team" in live_df.columns else "away_model_team"

    odds_join = (
        odds_df[keep]
        .drop_duplicates(subset=["home_team", "away_team"])
        .rename(columns={"home_team": join_home_col, "away_team": join_away_col})
    )

    overlap = [
        col for col in odds_join.columns
        if col in live_df.columns and col not in {join_home_col, join_away_col}
    ]
    base_df = live_df.drop(columns=overlap, errors="ignore")

    merged = base_df.merge(
        odds_join,
        on=[join_home_col, join_away_col],
        how="left",
    )

    for side in ("home", "away"):
        k = f"kalshi_{side}_prob"
        p = f"polymarket_{side}_prob"
        s = f"sportsbook_{side}_prob"
        m = f"market_{side}_implied"

        market = pd.to_numeric(merged.get(k, pd.Series(dtype=float)), errors="coerce")
        if p in merged.columns:
            market = market.combine_first(pd.to_numeric(merged[p], errors="coerce"))
        if s in merged.columns:
            market = market.combine_first(pd.to_numeric(merged[s], errors="coerce"))
        if m in merged.columns:
            market = market.combine_first(pd.to_numeric(merged[m], errors="coerce"))

        merged[f"market_{side}_live"] = market
        merged[f"live_{side}_edge"] = (
            pd.to_numeric(merged[f"live_{side}_prob"], errors="coerce") - market
        )

    return merged
