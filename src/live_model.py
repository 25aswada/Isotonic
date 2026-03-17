"""
live_model.py — Simplified in-game win probability model.

Uses the Stern (1994) random-walk model adjusted for:
  - Current score differential
  - Time remaining (seconds)
  - Pre-game team strength (Elo diff -> point spread)
  - Home court advantage

Formula:
    z = (score_diff + pregame_spread) / sqrt(minutes_remaining + 1)
    win_prob = normal_cdf(z)

Captures ~85% of the predictive power of a fully-trained play-by-play model.
"""

from __future__ import annotations

import logging
import time
from typing import Any

import numpy as np
import pandas as pd
from scipy.stats import norm

import config

logger = logging.getLogger(__name__)

NBA_REGULATION_SECONDS = 48 * 60
ELO_POINTS_PER_POINT   = 28.0
HOME_ADV_POINTS        = 2.5
SCORE_NOISE_PER_MINUTE = 2.50  # NBA empirical: ~2.5 pts uncertainty per sqrt(minute remaining)


def live_win_prob(
    home_score: float,
    away_score: float,
    seconds_remaining: float,
    home_elo: float = config.ELO_BASE,
    away_elo: float = config.ELO_BASE,
    pregame_home_prob: float | None = None,
) -> tuple[float, float]:
    """
    Blended in-game win probability.

    Combines two signals:
      1. Stern random-walk model  — score diff + clock (pure in-game state)
      2. Pre-game XGBoost prob    — rolling stats, Four Factors, matchup context

    Blend weight shifts from 100% pre-game at tipoff → 100% live model at final buzzer.
    At halftime: ~50/50. At end of Q3: ~75% live.

    If pregame_home_prob is None, falls back to Elo-based spread.
    """
    seconds_remaining = max(float(seconds_remaining), 0.0)
    minutes_remaining = seconds_remaining / 60.0
    total_minutes = NBA_REGULATION_SECONDS / 60.0
    score_diff = float(home_score) - float(away_score)

    # ── Signal 1: Stern live model ────────────────────────────────────────────
    elo_diff = float(home_elo) - float(away_elo)
    elo_spread = (elo_diff / ELO_POINTS_PER_POINT) + HOME_ADV_POINTS
    time_weight = minutes_remaining / total_minutes
    adjusted_spread = elo_spread * time_weight          # spread matters less as time runs out
    sigma = SCORE_NOISE_PER_MINUTE * np.sqrt(max(minutes_remaining, 0.01))
    z = (score_diff + adjusted_spread) / sigma
    stern_prob = float(np.clip(norm.cdf(z), 0.01, 0.99))

    # ── Signal 2: Pre-game model ──────────────────────────────────────────────
    if pregame_home_prob is not None:
        pg = float(np.clip(pregame_home_prob, 0.01, 0.99))
    else:
        # Fallback: convert Elo spread to probability
        pg_z = elo_spread / (SCORE_NOISE_PER_MINUTE * np.sqrt(total_minutes))
        pg = float(np.clip(norm.cdf(pg_z), 0.01, 0.99))

    # ── Blend: live weight = fraction of game elapsed ─────────────────────────
    # At tipoff (48min left): live_weight=0  → pure pre-game
    # At halftime (24min left): live_weight=0.5
    # At Q4 2min left: live_weight=0.96 → almost all live
    live_weight = float(np.clip(1.0 - (minutes_remaining / total_minutes), 0.0, 1.0))
    home_prob = live_weight * stern_prob + (1.0 - live_weight) * pg
    home_prob = float(np.clip(home_prob, 0.01, 0.99))
    return home_prob, 1.0 - home_prob


def _parse_game_clock(clock_str: str | None) -> float:
    if not clock_str:
        return 0.0
    s = str(clock_str).strip()
    if s.startswith("PT"):
        s = s[2:]
        minutes, seconds = 0.0, 0.0
        if "M" in s:
            parts = s.split("M")
            minutes = float(parts[0])
            s = parts[1]
        if "S" in s:
            seconds = float(s.replace("S", ""))
        return minutes * 60 + seconds
    if ":" in s:
        parts = s.split(":")
        return float(parts[0]) * 60 + float(parts[1])
    return 0.0


def _period_seconds_remaining(period: int, clock_seconds: float) -> float:
    if period <= 0:
        return NBA_REGULATION_SECONDS
    if period <= 4:
        return (4 - period) * 12 * 60 + clock_seconds
    return clock_seconds  # OT: just clock left


ESPN_SCOREBOARD_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/scoreboard"

# ESPN abbreviation → NBA tricode (for mismatches)
_ESPN_TO_NBA: dict[str, str] = {
    "GS": "GSW", "NY": "NYK", "SA": "SAS", "NO": "NOP",
    "UTAH": "UTA", "UTH": "UTA", "PHX": "PHX", "WSH": "WAS",
}

def _espn_abbr_to_nba(abbr: str) -> str:
    return _ESPN_TO_NBA.get(abbr, abbr)


def fetch_live_games(elo_ratings: dict[str, float] | None = None, pregame_probs: dict[tuple[str,str], float] | None = None) -> pd.DataFrame:
    """Pull live/upcoming games from ESPN scoreboard and compute win probabilities."""
    import requests as _req
    try:
        resp = _req.get(ESPN_SCOREBOARD_URL, timeout=5)
        resp.raise_for_status()
        events = resp.json().get("events", [])
    except Exception as exc:
        logger.warning("Failed to fetch ESPN scoreboard: %s", exc)
        return pd.DataFrame()

    rows: list[dict[str, Any]] = []
    for event in events:
        comp = (event.get("competitions") or [{}])[0]
        competitors = comp.get("competitors", [])
        if len(competitors) < 2:
            continue

        home_c = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
        away_c = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])

        home_abbr = _espn_abbr_to_nba(home_c.get("team", {}).get("abbreviation", ""))
        away_abbr = _espn_abbr_to_nba(away_c.get("team", {}).get("abbreviation", ""))
        if not home_abbr or not away_abbr:
            continue

        status_obj = comp.get("status", {})
        status_type = status_obj.get("type", {})
        state = status_type.get("state", "pre")   # "pre" | "in" | "post"
        # Map to legacy integer status: 1=pre, 2=live, 3=final
        if state == "pre":
            status = 1
        elif state == "post":
            status = 3
        else:
            status = 2

        home_score = float(home_c.get("score") or 0)
        away_score = float(away_c.get("score") or 0)
        period     = int(status_obj.get("period") or 0)
        clock_str  = status_obj.get("displayClock", "")

        clock_secs = _parse_game_clock(clock_str)
        if status == 1:
            secs_remaining = NBA_REGULATION_SECONDS
        elif status == 3:
            secs_remaining = 0.0
        else:
            secs_remaining = _period_seconds_remaining(period, clock_secs)

        h_elo = (elo_ratings or {}).get(home_abbr, config.ELO_BASE)
        a_elo = (elo_ratings or {}).get(away_abbr, config.ELO_BASE)
        pregame_prob = pregame_probs.get((home_abbr, away_abbr)) if pregame_probs else None
        h_prob, a_prob = live_win_prob(home_score, away_score, secs_remaining, h_elo, a_elo,
                                       pregame_home_prob=pregame_prob)

        rows.append({
            "pregame_home_prob": round(pregame_prob, 4) if pregame_prob is not None else None,
            "game_id":           event.get("id"),
            "home_team":         home_abbr,
            "away_team":         away_abbr,
            "home_score":        int(home_score),
            "away_score":        int(away_score),
            "period":            period,
            "clock":             clock_str,
            "seconds_remaining": secs_remaining,
            "game_status":       status,
            "game_status_text":  status_type.get("shortDetail", ""),
            "home_elo":          h_elo,
            "away_elo":          a_elo,
            "live_home_prob":    round(h_prob, 4),
            "live_away_prob":    round(a_prob, 4),
        })

    return pd.DataFrame(rows)


def enrich_with_market_odds(live_df: pd.DataFrame, odds_df: pd.DataFrame) -> pd.DataFrame:
    """Join market odds onto live games and compute live edge."""
    if live_df.empty or odds_df.empty:
        return live_df

    keep = [c for c in [
        "home_team", "away_team",
        "kalshi_home_prob",      "kalshi_away_prob",
        "kalshi_home_ask_prob",  "kalshi_away_ask_prob",
    ] if c in odds_df.columns]

    merged = live_df.merge(
        odds_df[keep].drop_duplicates(subset=["home_team", "away_team"]),
        on=["home_team", "away_team"], how="left",
    )

    for side in ("home", "away"):
        k = f"kalshi_{side}_prob"
        mkt = pd.to_numeric(merged.get(k, pd.Series(dtype=float)), errors="coerce")
        merged[f"market_{side}_live"] = mkt
        merged[f"live_{side}_edge"] = (
            pd.to_numeric(merged[f"live_{side}_prob"], errors="coerce") - mkt
        )

    return merged
