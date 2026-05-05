"""
player_props.py - Lightweight NBA player prop projections from historical logs.

This module turns the cached player game logs into matchup-aware hit-rate
estimates for simple threshold props like "25+ points" or "8+ rebounds".
It is not a full learned model yet, but it produces real player-specific
probabilities instead of echoing market prices back to the UI.
"""

from __future__ import annotations

import glob
import math
import re
import unicodedata
from functools import lru_cache
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
PLAYER_LOG_GLOB = str(ROOT / "data" / "raw" / "player_logs_*.csv")
SUPPORTED_PROP_STATS = {"points": "PTS", "rebounds": "REB", "assists": "AST", "steals": "STL", "blocks": "BLK", "threes": "FG3M"}
def _ascii_fold(value: str) -> str:
    text = unicodedata.normalize("NFKD", value or "")
    return "".join(char for char in text if not unicodedata.combining(char))


def _name_key(name: str) -> str:
    folded = _ascii_fold(name).lower()
    return re.sub(r"[^a-z0-9]", "", folded)


def _name_tokens(name: str) -> set[str]:
    folded = _ascii_fold(name).lower()
    return {token for token in re.findall(r"[a-z0-9']+", folded) if token}


def _safe_float(value: Any) -> float:
    try:
        return float(value)
    except Exception:
        return float("nan")


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def _poisson_tail(mean: float, threshold: float) -> float:
    if mean <= 0:
        return 0.0
    cutoff = max(int(math.ceil(threshold)) - 1, 0)
    term = math.exp(-mean)
    cumulative = term
    for k in range(1, cutoff + 1):
        term *= mean / k
        cumulative += term
    return float(np.clip(1.0 - cumulative, 0.0, 1.0))


def _weighted_mean(values: np.ndarray, weights: np.ndarray) -> float:
    if len(values) == 0:
        return float("nan")
    weights = np.asarray(weights, dtype=float)
    if not np.isfinite(weights).any() or float(weights.sum()) <= 0:
        return float(np.nanmean(values))
    return float(np.average(values, weights=weights))


def _weighted_std(values: np.ndarray, weights: np.ndarray) -> float:
    if len(values) <= 1:
        return 0.0
    mean = _weighted_mean(values, weights)
    weights = np.asarray(weights, dtype=float)
    variance = np.average((values - mean) ** 2, weights=weights) if weights.sum() > 0 else np.var(values)
    return float(max(variance, 0.0) ** 0.5)


def _matchup_columns(matchup: str) -> tuple[str | None, bool | None]:
    text = str(matchup or "").strip()
    match = re.match(r"^([A-Z]{2,3})\s+(vs\.|@)\s+([A-Z]{2,3})$", text)
    if not match:
        return None, None
    return match.group(3), (match.group(2) == "vs.")


@lru_cache(maxsize=1)
def _load_player_logs() -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    for path in sorted(glob.glob(PLAYER_LOG_GLOB)):
        season = Path(path).stem.replace("player_logs_", "")
        frame = pd.read_csv(
            path,
            usecols=[
                "PLAYER_ID",
                "PLAYER_NAME",
                "TEAM_ABBREVIATION",
                "GAME_ID",
                "GAME_DATE",
                "MATCHUP",
                "MIN",
                "PTS",
                "REB",
                "AST",
                "STL",
                "BLK",
                "FG3M",
            ],
        )
        frame["season"] = season
        frames.append(frame)

    if not frames:
        return pd.DataFrame()

    logs = pd.concat(frames, ignore_index=True)
    logs["GAME_DATE"] = pd.to_datetime(logs["GAME_DATE"], errors="coerce")
    for column in ["MIN", "PTS", "REB", "AST", "STL", "BLK", "FG3M"]:
        logs[column] = pd.to_numeric(logs[column], errors="coerce").fillna(0.0)
    logs["opponent_team"], logs["is_home"] = zip(*logs["MATCHUP"].map(_matchup_columns))
    logs["player_key"] = logs["PLAYER_NAME"].map(_name_key)
    logs["player_tokens"] = logs["PLAYER_NAME"].map(_name_tokens)
    logs = logs.dropna(subset=["GAME_DATE"]).sort_values(["GAME_DATE", "GAME_ID", "PLAYER_NAME"]).reset_index(drop=True)
    return logs


@lru_cache(maxsize=1)
def _current_season() -> str:
    seasons = [Path(path).stem.replace("player_logs_", "") for path in sorted(glob.glob(PLAYER_LOG_GLOB))]
    return seasons[-1] if seasons else ""


@lru_cache(maxsize=1)
def _latest_team_lookup() -> dict[str, str]:
    logs = _load_player_logs()
    if logs.empty:
        return {}
    latest = (
        logs.sort_values(["GAME_DATE", "GAME_ID"])
        .groupby("player_key", as_index=False)
        .tail(1)[["player_key", "TEAM_ABBREVIATION"]]
    )
    return dict(zip(latest["player_key"], latest["TEAM_ABBREVIATION"]))


@lru_cache(maxsize=1)
def _current_team_defense_factors() -> dict[str, dict[str, float]]:
    logs = _load_player_logs()
    if logs.empty:
        return {}
    current = logs[(logs["season"] == _current_season()) & logs["opponent_team"].notna()].copy()
    if current.empty:
        return {}

    team_games = (
        current.groupby(["GAME_ID", "opponent_team"], as_index=False)[["PTS", "REB", "AST", "STL", "BLK"]]
        .sum()
        .rename(columns={"opponent_team": "team"})
    )
    league_avgs = team_games[["PTS", "REB", "AST", "STL", "BLK"]].mean()
    if league_avgs.isna().all():
        return {}

    factors: dict[str, dict[str, float]] = {}
    for team, grp in team_games.groupby("team"):
        means = grp[["PTS", "REB", "AST", "STL", "BLK"]].mean()
        factors[str(team)] = {}
        for market_type, stat_col in SUPPORTED_PROP_STATS.items():
            league_avg = _safe_float(league_avgs.get(stat_col))
            team_avg = _safe_float(means.get(stat_col))
            if not np.isfinite(team_avg) or not np.isfinite(league_avg) or league_avg <= 0:
                factors[str(team)][market_type] = 1.0
                continue
            raw = float(team_avg / league_avg)
            clip_low, clip_high = (0.80, 1.20) if market_type == "points" else (0.75, 1.25)
            factors[str(team)][market_type] = float(np.clip(raw, clip_low, clip_high))
    return factors


def _resolve_player_logs(player_name: str) -> pd.DataFrame:
    logs = _load_player_logs()
    if logs.empty:
        return pd.DataFrame()

    key = _name_key(player_name)
    exact = logs[logs["player_key"] == key]
    if not exact.empty:
        return exact.copy()

    query_tokens = _name_tokens(player_name)
    if not query_tokens:
        return pd.DataFrame()

    candidates = []
    sample = logs[["PLAYER_NAME", "player_key", "player_tokens"]].drop_duplicates("player_key")
    for _, row in sample.iterrows():
        tokens = row.get("player_tokens") or set()
        if not tokens:
            continue
        overlap = len(tokens & query_tokens)
        if overlap <= 0:
            continue
        coverage = overlap / max(len(query_tokens), len(tokens))
        candidates.append((coverage, overlap, str(row["player_key"])))

    if not candidates:
        return pd.DataFrame()

    candidates.sort(reverse=True)
    best_key = candidates[0][2]
    return logs[logs["player_key"] == best_key].copy()


def _resolve_matchup_context(player_logs: pd.DataFrame, home_team: str | None, away_team: str | None) -> tuple[str | None, str | None, bool | None]:
    if player_logs.empty:
        return None, None, None

    latest_team = str(player_logs.sort_values(["GAME_DATE", "GAME_ID"]).iloc[-1]["TEAM_ABBREVIATION"])
    home = str(home_team or "").strip().upper() or None
    away = str(away_team or "").strip().upper() or None

    if home and away:
        if latest_team == home:
            return latest_team, away, True
        if latest_team == away:
            return latest_team, home, False

    latest_row = player_logs.sort_values(["GAME_DATE", "GAME_ID"]).iloc[-1]
    return latest_team, latest_row.get("opponent_team"), latest_row.get("is_home")


def _expected_minutes(player_logs: pd.DataFrame) -> tuple[float, float]:
    eligible = player_logs[player_logs["MIN"] > 0].sort_values("GAME_DATE")
    if eligible.empty:
        return 0.0, 0.0

    recent = eligible.tail(12)
    current = eligible[eligible["season"] == _current_season()]
    recent_weights = np.exp(-np.arange(len(recent))[::-1] / 4.0)
    recent_mean = _weighted_mean(recent["MIN"].to_numpy(dtype=float), recent_weights)
    current_mean = float(current["MIN"].mean()) if not current.empty else recent_mean
    career_mean = float(eligible["MIN"].mean())
    projection = (0.6 * recent_mean) + (0.3 * current_mean) + (0.1 * career_mean)
    volatility = _weighted_std(recent["MIN"].to_numpy(dtype=float), recent_weights)
    return float(np.clip(projection, 4.0, 42.0)), float(max(volatility, 2.0))


def _home_away_factor(player_logs: pd.DataFrame, stat_col: str, is_home: bool | None) -> float:
    current = player_logs[player_logs["season"] == _current_season()].copy()
    if current.empty or is_home is None:
        return 1.0

    split = current[current["is_home"] == is_home]
    if len(split) < 4:
        return 1.0

    split_mean = float(split[stat_col].mean())
    season_mean = float(current[stat_col].mean())
    if season_mean <= 0:
        return 1.0
    return float(np.clip(split_mean / season_mean, 0.88, 1.12))


def _project_player_stat(player_name: str, stat: str, home_team: str | None, away_team: str | None) -> dict[str, Any] | None:
    stat = str(stat or "").strip().lower()
    stat_col = SUPPORTED_PROP_STATS.get(stat)
    if stat_col is None:
        return None

    player_logs = _resolve_player_logs(player_name)
    if player_logs.empty:
        return None

    player_logs = player_logs[player_logs["MIN"] > 0].sort_values("GAME_DATE").copy()
    if player_logs.empty:
        return None

    player_team, opponent_team, is_home = _resolve_matchup_context(player_logs, home_team=home_team, away_team=away_team)
    projected_minutes, minute_volatility = _expected_minutes(player_logs)

    current = player_logs[player_logs["season"] == _current_season()].copy()
    recent = player_logs.tail(20).copy()
    recent_weights = np.exp(-np.arange(len(recent))[::-1] / 5.0)

    recent_rate = _weighted_mean((recent[stat_col] / recent["MIN"].clip(lower=1)).to_numpy(dtype=float), recent_weights)
    current_rate = float(current[stat_col].sum() / current["MIN"].sum()) if not current.empty and float(current["MIN"].sum()) > 0 else recent_rate
    career_rate = float(player_logs[stat_col].sum() / player_logs["MIN"].sum()) if float(player_logs["MIN"].sum()) > 0 else current_rate
    base_rate = (0.55 * recent_rate) + (0.3 * current_rate) + (0.15 * career_rate)

    opponent_factors = _current_team_defense_factors()
    opponent_factor = float(opponent_factors.get(str(opponent_team), {}).get(stat, 1.0))
    split_factor = _home_away_factor(player_logs, stat_col=stat_col, is_home=is_home)

    projected_mean = projected_minutes * base_rate * opponent_factor * split_factor
    projected_mean = float(np.clip(projected_mean, 0.0, 80.0))

    sample_std = float(recent[stat_col].std(ddof=0)) if len(recent) > 1 else float(player_logs[stat_col].std(ddof=0))
    sample_std = sample_std if np.isfinite(sample_std) else 0.0
    variance_floor = max(projected_mean * (1.15 if stat == "points" else 0.9), 1.0)
    projected_std = float(max(sample_std, variance_floor ** 0.5, minute_volatility * base_rate * 0.35, 1.0))

    return {
        "player_name": str(player_logs.iloc[-1]["PLAYER_NAME"]),
        "player_team": player_team,
        "opponent_team": opponent_team,
        "is_home": is_home,
        "market_type": stat,
        "stat_col": stat_col,
        "games_used": int(len(player_logs)),
        "current_season_games": int(len(current)),
        "projected_minutes": float(projected_minutes),
        "projected_mean": projected_mean,
        "projected_std": projected_std,
        "recent_logs": recent[[stat_col]].copy(),
        "recent_weights": recent_weights,
        "season_average": float(current[stat_col].mean()) if not current.empty else float(player_logs[stat_col].mean()),
        "recent_average": float(_weighted_mean(recent[stat_col].to_numpy(dtype=float), recent_weights)),
        "model_source": "log_based_prop_estimator_v1",
    }


@lru_cache(maxsize=8192)
def _cached_player_projection(player_name: str, stat: str, home_team: str | None, away_team: str | None) -> dict[str, Any] | None:
    return _project_player_stat(player_name=player_name, stat=stat, home_team=home_team, away_team=away_team)


def estimate_player_prop(
    player_name: str,
    stat: str,
    threshold: float,
    home_team: str | None = None,
    away_team: str | None = None,
) -> dict[str, Any] | None:
    stat = str(stat or "").strip().lower()
    if stat not in SUPPORTED_PROP_STATS:
        return None

    projection = _cached_player_projection(
        player_name=_ascii_fold(player_name).strip(),
        stat=stat,
        home_team=str(home_team or "").strip().upper() or None,
        away_team=str(away_team or "").strip().upper() or None,
    )
    if projection is None:
        return None

    recent_logs = projection["recent_logs"]
    stat_col = str(projection["stat_col"])
    recent_weights = projection["recent_weights"]
    empirical_hit = float(
        _weighted_mean((recent_logs[stat_col].to_numpy(dtype=float) >= float(threshold)).astype(float), recent_weights)
    )

    projected_mean = float(projection["projected_mean"])
    projected_std = float(projection["projected_std"])
    if stat in {"steals", "blocks"}:
        distribution_hit = _poisson_tail(projected_mean, float(threshold))
    else:
        z = ((float(threshold) - 0.5) - projected_mean) / max(projected_std, 1.0)
        distribution_hit = float(np.clip(1.0 - _norm_cdf(z), 0.0, 1.0))

    recent_weight = min(len(recent_logs) / 16.0, 1.0) * 0.35
    distribution_weight = 1.0 - recent_weight
    model_prob = (distribution_weight * distribution_hit) + (recent_weight * empirical_hit)
    model_prob = float(np.clip(model_prob, 0.01, 0.99))

    return {
        "player_name": projection["player_name"],
        "player_team": projection["player_team"],
        "opponent_team": projection["opponent_team"],
        "is_home": projection["is_home"],
        "market_type": stat,
        "threshold": float(threshold),
        "projected_minutes": float(projection["projected_minutes"]),
        "projected_mean": projected_mean,
        "projected_std": projected_std,
        "season_average": float(projection["season_average"]),
        "recent_average": float(projection["recent_average"]),
        "games_used": int(projection["games_used"]),
        "current_season_games": int(projection["current_season_games"]),
        "empirical_hit_rate": float(empirical_hit),
        "distribution_hit_rate": float(distribution_hit),
        "model_prob": model_prob,
        "model_source": str(projection["model_source"]),
    }
