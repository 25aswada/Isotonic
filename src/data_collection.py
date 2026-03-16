"""
data_collection.py — Pull NBA game logs, team stats, and schedules from nba_api.

All raw data is cached as CSVs in data/raw/ and stored in data/nba.db.
"""

from __future__ import annotations

import logging
import sqlite3
import time
from pathlib import Path
from typing import Optional

import pandas as pd
from nba_api.stats.endpoints import (
    LeagueDashTeamStats,
    LeagueGameFinder,
    TeamGameLog,
)
from nba_api.stats.static import teams as nba_teams_static

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)

RAW = Path(config.RAW_DATA_DIR)
RAW.mkdir(parents=True, exist_ok=True)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _sleep() -> None:
    time.sleep(config.API_SLEEP)


def _season_to_api(season: str) -> str:
    """Convert '2021-22' → '2021-22' (nba_api already uses this format)."""
    return season


def get_all_team_ids() -> dict[str, int]:
    """Return {abbreviation: team_id} for every NBA team."""
    all_teams = nba_teams_static.get_teams()
    return {t["abbreviation"]: t["id"] for t in all_teams}


# ─────────────────────────────────────────────────────────────────────────────
# Game Logs
# ─────────────────────────────────────────────────────────────────────────────

def pull_season_game_logs(season: str, force: bool = False) -> pd.DataFrame:
    """
    Pull all team game logs for a season using LeagueGameFinder.

    Each row is one team's view of one game (2 rows per game).
    """
    cache_path = RAW / f"game_logs_{season}.csv"
    if cache_path.exists() and not force:
        logger.info("Loading cached game logs for %s", season)
        return pd.read_csv(cache_path)

    logger.info("Pulling game logs for %s from nba_api...", season)
    try:
        finder = LeagueGameFinder(
            season_nullable=_season_to_api(season),
            league_id_nullable="00",
            season_type_nullable="Regular Season",
        )
        _sleep()
        df = finder.get_data_frames()[0]
        df["season"] = season
        df.to_csv(cache_path, index=False)
        logger.info("  Saved %d rows to %s", len(df), cache_path)
        return df
    except Exception as exc:
        logger.error("Failed to pull game logs for %s: %s", season, exc)
        raise


def pull_all_game_logs(seasons: list[str] | None = None, force: bool = False) -> pd.DataFrame:
    """Pull game logs for all seasons and concatenate."""
    if seasons is None:
        seasons = config.SEASONS
    frames = []
    for season in seasons:
        df = pull_season_game_logs(season, force=force)
        frames.append(df)
    return pd.concat(frames, ignore_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Team Game Logs (per-team detail)
# ─────────────────────────────────────────────────────────────────────────────

def pull_team_game_log(team_id: int, season: str, force: bool = False) -> pd.DataFrame:
    """Pull a single team's game log for a season."""
    cache_path = RAW / f"team_{team_id}_{season}.csv"
    if cache_path.exists() and not force:
        return pd.read_csv(cache_path)

    try:
        log = TeamGameLog(team_id=team_id, season=_season_to_api(season), season_type_all_star="Regular Season")
        _sleep()
        df = log.get_data_frames()[0]
        df["team_id"] = team_id
        df["season"] = season
        df.to_csv(cache_path, index=False)
        return df
    except Exception as exc:
        logger.error("Failed team %s season %s: %s", team_id, season, exc)
        return pd.DataFrame()


def pull_all_team_game_logs(seasons: list[str] | None = None, force: bool = False) -> pd.DataFrame:
    """Pull per-team game logs for all seasons. Shows progress."""
    if seasons is None:
        seasons = config.SEASONS
    team_ids = get_all_team_ids()
    frames = []
    total = len(seasons) * len(team_ids)
    done = 0
    for season in seasons:
        logger.info("Pulling team game logs for %s...", season)
        for abbr, tid in team_ids.items():
            df = pull_team_game_log(tid, season, force=force)
            if not df.empty:
                frames.append(df)
            done += 1
            if done % 10 == 0:
                logger.info("  Progress: %d/%d", done, total)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


# ─────────────────────────────────────────────────────────────────────────────
# Advanced Team Stats
# ─────────────────────────────────────────────────────────────────────────────

def pull_advanced_team_stats(season: str, force: bool = False) -> pd.DataFrame:
    """Pull league-wide advanced team stats (off/def rating, pace, etc.) for a season."""
    cache_path = RAW / f"advanced_stats_{season}.csv"
    if cache_path.exists() and not force:
        return pd.read_csv(cache_path)

    logger.info("Pulling advanced stats for %s...", season)
    try:
        stats = LeagueDashTeamStats(
            season=_season_to_api(season),
            measure_type_detailed_defense="Advanced",
            per_mode_detailed="PerGame",
            season_type_all_star="Regular Season",
        )
        _sleep()
        df = stats.get_data_frames()[0]
        df["season"] = season
        df.to_csv(cache_path, index=False)
        return df
    except Exception as exc:
        logger.error("Failed advanced stats for %s: %s", season, exc)
        raise


def pull_all_advanced_stats(seasons: list[str] | None = None, force: bool = False) -> pd.DataFrame:
    if seasons is None:
        seasons = config.SEASONS
    frames = [pull_advanced_team_stats(s, force=force) for s in seasons]
    return pd.concat(frames, ignore_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Parse into canonical game-level table
# ─────────────────────────────────────────────────────────────────────────────

def parse_game_logs_to_matchups(raw_logs: pd.DataFrame) -> pd.DataFrame:
    """
    Convert raw LeagueGameFinder output (2 rows per game) into one row per game.

    Columns added: game_id, game_date, season, home_team, away_team, home_win,
    home_pts, away_pts.
    """
    df = raw_logs.copy()
    df.columns = [c.upper() for c in df.columns]

    # Ensure MATCHUP column exists
    if "MATCHUP" not in df.columns:
        logger.warning("MATCHUP column missing from game logs")
        return pd.DataFrame()

    # Identify home/away from MATCHUP: "LAL vs. GSW" = home, "LAL @ GSW" = away
    df["is_home"] = df["MATCHUP"].str.contains(r"vs\.", regex=True)

    home = df[df["is_home"]].copy()
    away = df[~df["is_home"]].copy()

    home = home.rename(columns={
        "TEAM_ABBREVIATION": "home_team",
        "PTS": "home_pts",
        "WL": "home_wl",
    })
    away = away.rename(columns={
        "TEAM_ABBREVIATION": "away_team",
        "PTS": "away_pts",
    })

    merged = home.merge(
        away[["GAME_ID", "away_team", "away_pts"]],
        on="GAME_ID",
        how="inner",
    )

    merged = merged.rename(columns={
        "GAME_ID": "game_id",
        "GAME_DATE": "game_date",
        "SEASON": "season",
    })

    merged["home_win"] = (merged["home_wl"] == "W").astype(int)
    merged["game_date"] = pd.to_datetime(merged["game_date"])

    keep = ["game_id", "game_date", "season", "home_team", "away_team",
            "home_pts", "away_pts", "home_win"]
    available = [c for c in keep if c in merged.columns]
    return merged[available].drop_duplicates("game_id").sort_values("game_date").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# SQLite storage
# ─────────────────────────────────────────────────────────────────────────────

def save_to_db(df: pd.DataFrame, table_name: str, db_path: str = config.DB_PATH) -> None:
    """Save a DataFrame to SQLite, replacing existing data."""
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(db_path) as conn:
        df.to_sql(table_name, conn, if_exists="replace", index=False)
    logger.info("Saved %d rows to DB table '%s'", len(df), table_name)


def load_from_db(table_name: str, db_path: str = config.DB_PATH) -> pd.DataFrame:
    """Load a table from SQLite."""
    with sqlite3.connect(db_path) as conn:
        return pd.read_sql(f"SELECT * FROM {table_name}", conn)


# ─────────────────────────────────────────────────────────────────────────────
# Today's schedule
# ─────────────────────────────────────────────────────────────────────────────

def get_todays_games() -> pd.DataFrame:
    """
    Pull today's NBA schedule using the live scoreboard endpoint.

    Returns columns:
        game_id, game_date, tipoff_utc, tipoff_et, game_status, game_status_text,
        home_team, away_team.
    """
    from nba_api.stats.endpoints import scoreboardv3

    today_et = pd.Timestamp.now(tz="America/New_York")
    target_date = today_et.date().isoformat()
    logger.info("Pulling today's schedule for %s (America/New_York)", target_date)
    try:
        board = scoreboardv3.ScoreboardV3(game_date=target_date, league_id="00")
        payload = board.get_dict().get("scoreboard", {})
        games = payload.get("games", [])
        if not games:
            logger.info("No games scheduled today.")
            return pd.DataFrame()

        rows = []
        for game in games:
            home = game.get("homeTeam", {})
            away = game.get("awayTeam", {})
            home_abbr = home.get("teamTricode")
            away_abbr = away.get("teamTricode")
            tipoff_et = pd.to_datetime(game.get("gameEt"), errors="coerce")
            tipoff_utc = pd.to_datetime(game.get("gameTimeUTC"), errors="coerce", utc=True)
            if home_abbr and away_abbr:
                rows.append({
                    "game_id": game.get("gameId"),
                    "game_date": (
                        tipoff_utc.tz_convert("America/New_York").normalize().tz_localize(None)
                        if pd.notna(tipoff_utc)
                        else pd.to_datetime(target_date)
                    ),
                    "tipoff_utc": tipoff_utc,
                    "tipoff_et": tipoff_et,
                    "game_status": game.get("gameStatus"),
                    "game_status_text": game.get("gameStatusText"),
                    "home_team": home_abbr,
                    "away_team": away_abbr,
                })

        df = pd.DataFrame(rows)
        logger.info("Found %d games today", len(df))
        return df

    except Exception as exc:
        logger.error("Failed to get today's games: %s", exc)
        return pd.DataFrame()
