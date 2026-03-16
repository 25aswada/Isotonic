"""
feature_engineering.py — Build pre-game features for historical and upcoming games.

All model features are derived from information available before tip-off.
Rolling stats are shifted by 1 game for historical training rows, while
upcoming-game features are built from each team's latest completed-game state.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.elo import EloSystem
# ─────────────────────────────────────────────────────────────────────────────
# Travel distance + timezone shift
# ─────────────────────────────────────────────────────────────────────────────

# (lat, lon, utc_offset_standard) for each NBA franchise home arena
_TEAM_GEO = {
    'ATL': (33.757,  -84.396,  -5), 'BOS': (42.366,  -71.062,  -5),
    'BKN': (40.683,  -73.975,  -5), 'CHA': (35.225,  -80.839,  -5),
    'CHI': (41.881,  -87.674,  -6), 'CLE': (41.497,  -81.688,  -5),
    'DAL': (32.790,  -96.810,  -6), 'DEN': (39.749, -105.007,  -7),
    'DET': (42.341,  -83.055,  -5), 'GSW': (37.768, -122.388,  -8),
    'HOU': (29.751,  -95.362,  -6), 'IND': (39.764,  -86.156,  -5),
    'LAC': (34.043, -118.267,  -8), 'LAL': (34.043, -118.267,  -8),
    'MEM': (35.138,  -90.051,  -6), 'MIA': (25.781,  -80.188,  -5),
    'MIL': (43.045,  -87.917,  -6), 'MIN': (44.979,  -93.276,  -6),
    'NOP': (29.949,  -90.082,  -6), 'NYK': (40.750,  -73.994,  -5),
    'OKC': (35.463,  -97.515,  -6), 'ORL': (28.539,  -81.384,  -5),
    'PHI': (39.901,  -75.172,  -5), 'PHX': (33.446, -112.071,  -7),
    'POR': (45.532, -122.667,  -8), 'SAC': (38.580, -121.500,  -8),
    'SAS': (29.427,  -98.438,  -6), 'TOR': (43.643,  -79.379,  -5),
    'UTA': (40.768, -111.901,  -7), 'WAS': (38.898,  -77.021,  -5),
    # aliases
    'BRK': (40.683,  -73.975,  -5), 'NJN': (40.683,  -73.975,  -5),
    'NOH': (29.949,  -90.082,  -6), 'SEA': (47.622, -122.354,  -8),
    'VAN': (49.278, -123.109,  -8), 'NZN': (40.683,  -73.975,  -5),
}

def _haversine_miles(lat1, lon1, lat2, lon2):
    """Great-circle distance in miles between two lat/lon points."""
    R = 3958.8
    phi1, phi2 = np.radians(lat1), np.radians(lat2)
    dphi  = np.radians(lat2 - lat1)
    dlam  = np.radians(lon2 - lon1)
    a = np.sin(dphi/2)**2 + np.cos(phi1)*np.cos(phi2)*np.sin(dlam/2)**2
    return 2 * R * np.arcsin(np.sqrt(a))


def build_travel_features(team_rolling: pd.DataFrame) -> pd.DataFrame:
    """
    Add travel distance and timezone shift features to each team-game row.

    Requires: team, game_date, game_id, opponent columns (plus is_home).
    Adds per-row:
        travel_miles       - miles traveled to reach this game's venue
        timezone_shift     - hours of timezone change (west→east = positive)
        travel_fatigue     - composite: miles/500 + abs(timezone_shift)
    """
    df = team_rolling.copy().sort_values(["team", "game_date"]).reset_index(drop=True)

    # Determine venue for each game: home team's city
    # We know is_home flag tells us if this team is the home team.
    # Venue = home team's arena.  For away team, venue = opponent's arena.
    def _venue_team(row):
        """Return the abbreviation whose arena is the venue."""
        if row.get("is_home", True):
            return row["team"]
        return row.get("opp_team", row.get("opponent", row["team"]))

    df["_venue_team"] = df.apply(_venue_team, axis=1)

    def _geo(abbr):
        return _TEAM_GEO.get(str(abbr).upper(), (39.5, -98.35, -6))  # US geographic center as fallback

    travel_miles_list, tz_shift_list = [], []

    for team, grp in df.groupby("team"):
        grp = grp.sort_values("game_date").reset_index(drop=False)
        miles_col, tz_col = [], []
        prev_venue = team  # first game: assume starting from home
        for _, row in grp.iterrows():
            cur_venue = row["_venue_team"]
            prev_lat, prev_lon, prev_tz = _geo(prev_venue)
            cur_lat,  cur_lon,  cur_tz  = _geo(cur_venue)
            miles = _haversine_miles(prev_lat, prev_lon, cur_lat, cur_lon)
            tz    = cur_tz - prev_tz      # negative = traveling west
            miles_col.append(round(miles, 1))
            tz_col.append(tz)
            prev_venue = cur_venue
        grp["travel_miles"]    = miles_col
        grp["timezone_shift"]   = tz_col
        travel_miles_list.append(grp[["team", "game_id", "travel_miles", "timezone_shift"]])

    travel_df = pd.concat(travel_miles_list, ignore_index=True)
    df = df.merge(travel_df, on=["team", "game_id"], how="left")

    df["travel_miles"]   = df["travel_miles"].fillna(0)
    df["timezone_shift"] = df["timezone_shift"].fillna(0)
    df["travel_fatigue"] = df["travel_miles"] / 500.0 + df["timezone_shift"].abs()
    df = df.drop(columns=["_venue_team"])
    return df



logger = logging.getLogger(__name__)

PROCESSED = Path(config.PROCESSED_DATA_DIR)
PROCESSED.mkdir(parents=True, exist_ok=True)

# ─────────────────────────────────────────────────────────────────────────────
# Column maps / constants
# ─────────────────────────────────────────────────────────────────────────────

RAW_BOX_COLS = {
    "FGM": "fgm", "FGA": "fga", "FG_PCT": "fg_pct",
    "FG3M": "fg3m", "FG3A": "fg3a", "FG3_PCT": "fg3_pct",
    "FTM": "ftm", "FTA": "fta", "FT_PCT": "ft_pct",
    "OREB": "oreb", "DREB": "dreb", "REB": "reb",
    "AST": "ast", "STL": "stl", "BLK": "blk", "TOV": "tov",
    "PF": "pf", "PTS": "pts",
}

ROLLING_STATS = ["pts", "fg_pct", "fg3_pct", "ft_pct", "reb", "ast", "tov", "oreb", "dreb"]
ADVANCED_ROLLING_WINDOW = 10
ADVANCED_SOURCE_TO_FEATURE = {
    "off_rtg_game": "off_rtg",
    "def_rtg_game": "def_rtg",
    "net_rtg_game": "net_rtg",
    "pace_game": "pace",
    "efg_pct_game": "efg_pct",
    "ts_pct_game": "ts_pct",
    # Four Factors
    "tov_rate_game": "tov_rate",
    "ft_rate_game": "ft_rate",
    "oreb_pct_game": "oreb_pct",
    "dreb_pct_game": "dreb_pct",
    "opp_efg_pct_game": "opp_efg_pct",
    "opp_tov_rate_game": "opp_tov_rate",
    # Point differential
    "point_diff_game": "point_diff",
}
MATCHUP_DIFFERENTIAL_STATS = [
    "off_rtg",
    "def_rtg",
    "net_rtg",
    "pace",
    "efg_pct",
    "ts_pct",
    "tov_rate",
    "ft_rate",
    "oreb_pct",
    "dreb_pct",
    "opp_efg_pct",
    "opp_tov_rate",
    "point_diff",
]
ROLLING_DIFF_STATS = [
    "win_pct",
    "pts",
    "opp_pts",
    "pts_std",
]


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, np.nan)
    return numerator / denominator


def _prepare_team_games(raw_logs: pd.DataFrame) -> pd.DataFrame:
    """
    Normalize raw LeagueGameFinder rows to one team-game per row with opponent stats.
    """
    df = raw_logs.copy()
    df.columns = [c.upper() for c in df.columns]

    rename = {
        "TEAM_ABBREVIATION": "team",
        "GAME_DATE": "game_date",
        "GAME_ID": "game_id",
        "MATCHUP": "matchup",
        "WL": "wl",
        "SEASON": "season",
    }
    rename.update({k: v for k, v in RAW_BOX_COLS.items() if k in df.columns})
    df = df.rename(columns=rename)

    df["game_date"] = pd.to_datetime(df["game_date"])
    df["win"] = (df["wl"] == "W").astype(int)
    df["is_home"] = df["matchup"].str.contains(r"vs\.", regex=True)

    opp_cols = ["pts", "fgm", "fg3m", "fga", "fta", "oreb", "dreb", "tov"]
    opp_cols = [c for c in opp_cols if c in df.columns]
    opp_lookup = df[["game_id", "team"] + opp_cols].copy()
    opp_lookup = opp_lookup.rename(columns={"team": "opp_team", **{c: f"opp_{c}" for c in opp_cols}})

    df = df.merge(opp_lookup, on="game_id", how="left")
    df = df[df["team"] != df["opp_team"]].copy()

    team_possessions = (
        df.get("fga", pd.Series(index=df.index, dtype=float))
        - df.get("oreb", pd.Series(index=df.index, dtype=float))
        + df.get("tov", pd.Series(index=df.index, dtype=float))
        + 0.44 * df.get("fta", pd.Series(index=df.index, dtype=float))
    )
    opp_possessions = (
        df.get("opp_fga", pd.Series(index=df.index, dtype=float))
        - df.get("opp_oreb", pd.Series(index=df.index, dtype=float))
        + df.get("opp_tov", pd.Series(index=df.index, dtype=float))
        + 0.44 * df.get("opp_fta", pd.Series(index=df.index, dtype=float))
    )
    possessions = ((team_possessions + opp_possessions) / 2.0).replace(0, np.nan)

    df["estimated_possessions"] = possessions
    df["off_rtg_game"] = 100.0 * _safe_divide(df["pts"], possessions)
    df["def_rtg_game"] = 100.0 * _safe_divide(df["opp_pts"], possessions)
    df["net_rtg_game"] = df["off_rtg_game"] - df["def_rtg_game"]
    df["pace_game"] = possessions
    df["efg_pct_game"] = _safe_divide(df["fgm"] + 0.5 * df["fg3m"], df["fga"])
    df["ts_pct_game"] = _safe_divide(df["pts"], 2.0 * (df["fga"] + 0.44 * df["fta"]))

    # Four Factors (Dean Oliver) — offensive
    tov_denom = df["fga"] + 0.44 * df["fta"] + df["tov"]
    df["tov_rate_game"] = _safe_divide(df["tov"], tov_denom)           # turnover rate
    df["ft_rate_game"]  = _safe_divide(df["fta"], df["fga"])           # free-throw rate
    df["oreb_pct_game"] = _safe_divide(df["oreb"], df.get("oreb", pd.Series(dtype=float)) + df.get("opp_dreb", pd.Series(dtype=float)))

    # Four Factors — defensive (what we allow)
    if "opp_fgm" in df.columns and "opp_fg3m" in df.columns and "opp_fga" in df.columns:
        df["opp_efg_pct_game"] = _safe_divide(df["opp_fgm"] + 0.5 * df["opp_fg3m"], df["opp_fga"])
    if "opp_tov" in df.columns and "opp_fga" in df.columns and "opp_fta" in df.columns:
        opp_tov_denom = df["opp_fga"] + 0.44 * df["opp_fta"] + df["opp_tov"]
        df["opp_tov_rate_game"] = _safe_divide(df["opp_tov"], opp_tov_denom)  # forced turnover rate
    if "opp_oreb" in df.columns and "dreb" in df.columns:
        df["dreb_pct_game"] = _safe_divide(df["dreb"], df["dreb"] + df["opp_oreb"])   # def rebound %

    # Point differential
    df["point_diff_game"] = df["pts"] - df["opp_pts"]

    return df.sort_values(["team", "game_date"]).reset_index(drop=True)


def _team_feature_columns(team_features: pd.DataFrame) -> list[str]:
    feat_cols = (
        ["game_id", "team", "rest_days", "is_b2b", "win_streak", "consec_road_games",
         "roll_10_home_win_pct", "roll_10_away_win_pct"]
        + [f"roll_{w}_{s}" for w in config.ROLLING_WINDOWS for s in ROLLING_STATS]
        + [f"roll_{w}_opp_pts" for w in config.ROLLING_WINDOWS]
        + [f"roll_{w}_win_pct" for w in config.ROLLING_WINDOWS]
        + [f"roll_{w}_pts_std" for w in config.ROLLING_WINDOWS]
        + list(ADVANCED_SOURCE_TO_FEATURE.values())
    )
    return [c for c in feat_cols if c in team_features.columns]


def _add_matchup_differentials(df: pd.DataFrame) -> pd.DataFrame:
    """Add clean home-vs-away differential features shared by train and live paths."""
    for stat in MATCHUP_DIFFERENTIAL_STATS:
        home_col, away_col = f"home_{stat}", f"away_{stat}"
        if home_col in df.columns and away_col in df.columns:
            df[f"{stat}_diff"] = df[home_col] - df[away_col]

    for window in config.ROLLING_WINDOWS:
        for stat in ROLLING_DIFF_STATS:
            home_col, away_col = f"home_roll_{window}_{stat}", f"away_roll_{window}_{stat}"
            if home_col in df.columns and away_col in df.columns:
                df[f"roll_{window}_{stat}_diff"] = df[home_col] - df[away_col]

    if "home_roll_10_home_win_pct" in df.columns and "away_roll_10_away_win_pct" in df.columns:
        df["location_win_pct_diff"] = (
            df["home_roll_10_home_win_pct"] - df["away_roll_10_away_win_pct"]
        )

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Historical team-game features
# ─────────────────────────────────────────────────────────────────────────────

def build_team_rolling_stats(raw_logs: pd.DataFrame) -> pd.DataFrame:
    """
    Build per-team rolling features for every completed game.

    The resulting row represents the team's state before that game.
    """
    df = _prepare_team_games(raw_logs)
    result_frames = []

    for team, grp in df.groupby("team"):
        grp = grp.copy().sort_values("game_date").reset_index(drop=True)
        for w in config.ROLLING_WINDOWS:
            for stat in ROLLING_STATS:
                if stat in grp.columns:
                    grp[f"roll_{w}_{stat}"] = grp[stat].shift(1).rolling(w, min_periods=1).mean()
            if "opp_pts" in grp.columns:
                grp[f"roll_{w}_opp_pts"] = grp["opp_pts"].shift(1).rolling(w, min_periods=1).mean()
            grp[f"roll_{w}_win_pct"] = grp["win"].shift(1).rolling(w, min_periods=1).mean()
            if "pts" in grp.columns:
                grp[f"roll_{w}_pts_std"] = grp["pts"].shift(1).rolling(w, min_periods=1).std()
        result_frames.append(grp)

    return pd.concat(result_frames, ignore_index=True)


def build_rest_features(team_rolling: pd.DataFrame) -> pd.DataFrame:
    """
    Add rest_days, is_b2b, win_streak, and travel fatigue columns.
    """
    df = team_rolling.copy().sort_values(["team", "game_date"]).reset_index(drop=True)
    df["prev_game_date"] = df.groupby("team")["game_date"].shift(1)
    df["rest_days"] = (df["game_date"] - df["prev_game_date"]).dt.days - 1
    df["rest_days"] = df["rest_days"].fillna(3).clip(lower=0)
    df["is_b2b"] = (df["rest_days"] == 0).astype(int)

    # Win streak: positive = winning streak, negative = losing streak
    streak_frames = []
    for team, grp in df.groupby("team"):
        grp = grp.sort_values("game_date").reset_index(drop=True)
        streaks = []
        current = 0
        for i, row in grp.iterrows():
            # streak represents state BEFORE this game (shift by 1)
            streaks.append(current)
            if row["win"] == 1:
                current = max(current, 0) + 1
            else:
                current = min(current, 0) - 1
        grp["win_streak"] = streaks
        streak_frames.append(grp[["team", "game_id", "win_streak"]])
    streak_df = pd.concat(streak_frames, ignore_index=True)
    df = df.merge(streak_df, on=["team", "game_id"], how="left")

    # Consecutive road games (travel fatigue proxy)
    road_frames = []
    for team, grp in df.groupby("team"):
        grp = grp.sort_values("game_date").reset_index(drop=True)
        road_count = []
        count = 0
        for i, row in grp.iterrows():
            road_count.append(count)
            if not row.get("is_home", True):
                count += 1
            else:
                count = 0
        grp["consec_road_games"] = road_count
        road_frames.append(grp[["team", "game_id", "consec_road_games"]])
    road_df = pd.concat(road_frames, ignore_index=True)
    df = df.merge(road_df, on=["team", "game_id"], how="left")

    return df


def build_home_away_win_pct(team_rolling: pd.DataFrame) -> pd.DataFrame:
    """
    Add team-specific rolling home/away win percentages over the last 10 games.
    """
    df = team_rolling.copy()

    for location, flag in [("home", True), ("away", False)]:
        result_col = f"roll_10_{location}_win_pct"
        dfs = []
        for team, grp in df.groupby("team"):
            grp = grp.copy().sort_values("game_date")
            loc_grp = grp[grp["is_home"] == flag].copy()
            loc_grp[result_col] = loc_grp["win"].shift(1).rolling(10, min_periods=1).mean()
            dfs.append(loc_grp[["team", "game_id", result_col]])
        loc_df = pd.concat(dfs, ignore_index=True)
        df = df.merge(loc_df, on=["team", "game_id"], how="left")

    return df


def build_advanced_rolling(
    adv_stats: pd.DataFrame | None,
    team_rolling: pd.DataFrame,
) -> pd.DataFrame:
    """
    Build leak-free rolling advanced metrics from completed game logs.

    Season-summary advanced stats are intentionally ignored because they leak
    future information into earlier games.
    """
    if adv_stats is not None and not adv_stats.empty:
        logger.info("Ignoring season-summary advanced stats to avoid future leakage.")

    df = team_rolling.copy().sort_values(["team", "game_date"]).reset_index(drop=True)

    for source_col, target_col in ADVANCED_SOURCE_TO_FEATURE.items():
        if source_col not in df.columns:
            continue
        df[target_col] = (
            df.groupby("team")[source_col]
            .transform(lambda s: s.shift(1).rolling(ADVANCED_ROLLING_WINDOW, min_periods=1).mean())
        )

    return df


# ─────────────────────────────────────────────────────────────────────────────
# Strength of schedule
# ─────────────────────────────────────────────────────────────────────────────

def build_sos(matchups: pd.DataFrame, elo_df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute avg opponent Elo over last 10 games for each team as an SoS proxy.
    """
    home_view = elo_df[["game_id", "game_date", "home_team", "away_elo"]].copy()
    home_view = home_view.rename(columns={"home_team": "team", "away_elo": "opp_elo"})

    away_view = elo_df[["game_id", "game_date", "away_team", "home_elo"]].copy()
    away_view = away_view.rename(columns={"away_team": "team", "home_elo": "opp_elo"})

    opp_elo_df = pd.concat([home_view, away_view], ignore_index=True).sort_values(["team", "game_date"])

    sos_rows = []
    for team, grp in opp_elo_df.groupby("team"):
        grp = grp.sort_values("game_date").reset_index(drop=True)
        grp["sos_10"] = grp["opp_elo"].shift(1).rolling(10, min_periods=1).mean()
        sos_rows.append(grp[["game_id", "team", "sos_10"]])

    return pd.concat(sos_rows, ignore_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Upcoming-game team snapshots
# ─────────────────────────────────────────────────────────────────────────────

def build_team_snapshots(raw_logs: pd.DataFrame) -> pd.DataFrame:
    """
    Build each team's latest completed-game state for upcoming predictions.
    """
    df = _prepare_team_games(raw_logs)
    if df.empty:
        return pd.DataFrame()

    snapshots: list[dict] = []
    for team, grp in df.groupby("team"):
        grp = grp.copy().sort_values("game_date").reset_index(drop=True)
        snapshot = {
            "team": team,
            "last_game_date": grp["game_date"].iloc[-1],
        }

        for w in config.ROLLING_WINDOWS:
            for stat in ROLLING_STATS:
                if stat in grp.columns:
                    snapshot[f"roll_{w}_{stat}"] = grp[stat].rolling(w, min_periods=1).mean().iloc[-1]
            if "opp_pts" in grp.columns:
                snapshot[f"roll_{w}_opp_pts"] = grp["opp_pts"].rolling(w, min_periods=1).mean().iloc[-1]
            snapshot[f"roll_{w}_win_pct"] = grp["win"].rolling(w, min_periods=1).mean().iloc[-1]
            if "pts" in grp.columns:
                snapshot[f"roll_{w}_pts_std"] = grp["pts"].rolling(w, min_periods=1).std().iloc[-1]

        home_games = grp[grp["is_home"]].copy()
        away_games = grp[~grp["is_home"]].copy()
        snapshot["roll_10_home_win_pct"] = (
            home_games["win"].rolling(10, min_periods=1).mean().iloc[-1]
            if not home_games.empty else np.nan
        )
        snapshot["roll_10_away_win_pct"] = (
            away_games["win"].rolling(10, min_periods=1).mean().iloc[-1]
            if not away_games.empty else np.nan
        )

        for source_col, target_col in ADVANCED_SOURCE_TO_FEATURE.items():
            if source_col in grp.columns:
                snapshot[target_col] = grp[source_col].rolling(ADVANCED_ROLLING_WINDOW, min_periods=1).mean().iloc[-1]

        # Win streak (positive = win streak, negative = loss streak)
        streak = 0
        for _, r in grp.iterrows():
            streak = max(streak, 0) + 1 if r["win"] == 1 else min(streak, 0) - 1
        snapshot["win_streak"] = streak

        # Consecutive road games
        road_count = 0
        for _, r in grp.iterrows():
            if not r.get("is_home", True):
                road_count += 1
            else:
                road_count = 0
        snapshot["consec_road_games"] = road_count

        # Travel: distance from last venue to next game venue
        # For snapshot we record the last known travel values so the upcoming-game
        # builder can carry them forward via rest-day recalculation.
        last_venue = team if grp["is_home"].iloc[-1] else grp["opp_team"].iloc[-1] if "opp_team" in grp.columns else grp.get("opponent", pd.Series([team])).iloc[-1]
        snapshot["last_venue_team"] = last_venue  # used by upcoming-game builder

        snapshots.append(snapshot)

    return pd.DataFrame(snapshots)


# ─────────────────────────────────────────────────────────────────────────────
# Assemble matchup-level feature matrices
# ─────────────────────────────────────────────────────────────────────────────

def assemble_features(
    matchups: pd.DataFrame,
    team_features: pd.DataFrame,
    elo_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Join historical team-game features onto the matchup table.
    """
    feat_cols = _team_feature_columns(team_features)
    tf = team_features[feat_cols].drop_duplicates(subset=["game_id", "team"])

    home_tf = tf.copy()
    home_tf = home_tf.rename(columns={c: f"home_{c}" for c in home_tf.columns if c not in ["game_id", "team"]})
    home_tf = home_tf.rename(columns={"team": "home_team"})

    away_tf = tf.copy()
    away_tf = away_tf.rename(columns={c: f"away_{c}" for c in away_tf.columns if c not in ["game_id", "team"]})
    away_tf = away_tf.rename(columns={"team": "away_team"})

    df = matchups.merge(home_tf, on=["game_id", "home_team"], how="left")
    df = df.merge(away_tf, on=["game_id", "away_team"], how="left")

    elo_cols = ["game_id", "home_elo", "away_elo", "elo_diff"]
    elo_cols = [c for c in elo_cols if c in elo_df.columns]
    df = df.merge(elo_df[elo_cols], on="game_id", how="left")

    df["rest_diff"] = df["home_rest_days"] - df["away_rest_days"]

    if "home_off_rtg" in df.columns and "away_def_rtg" in df.columns:
        df["home_off_vs_away_def"] = df["home_off_rtg"] - df["away_def_rtg"]
    if "away_off_rtg" in df.columns and "home_def_rtg" in df.columns:
        df["away_off_vs_home_def"] = df["away_off_rtg"] - df["home_def_rtg"]
    if "home_pace" in df.columns and "away_pace" in df.columns:
        df["pace_diff"] = df["home_pace"] - df["away_pace"]

    # Streak differential
    if "home_win_streak" in df.columns and "away_win_streak" in df.columns:
        df["streak_diff"] = df["home_win_streak"] - df["away_win_streak"]

    # Travel differentials
    if "home_travel_miles" in df.columns and "away_travel_miles" in df.columns:
        df["travel_miles_diff"]   = df["home_travel_miles"]   - df["away_travel_miles"]
        df["timezone_shift_diff"] = df["home_timezone_shift"] - df["away_timezone_shift"]
        df["travel_fatigue_diff"] = df["home_travel_fatigue"] - df["away_travel_fatigue"]

    df = _add_matchup_differentials(df)

    # Season phase
    df["season_phase"] = (
        (df["game_date"] - pd.to_datetime(df["game_date"].dt.year.astype(str) + "-10-01"))
        .dt.days.clip(lower=0) / 180.0
    ).clip(upper=1.0)

    return df.sort_values("game_date").reset_index(drop=True)


def build_features_for_upcoming_games(
    games: pd.DataFrame,
    raw_logs: pd.DataFrame,
    historical_matchups: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Build model-ready features for scheduled games using current team state.
    """
    if games.empty:
        return pd.DataFrame()

    upcoming = games.copy()
    upcoming["game_date"] = pd.to_datetime(upcoming["game_date"])

    snapshots = build_team_snapshots(raw_logs)
    if snapshots.empty:
        logger.warning("No historical raw logs available for upcoming-game features.")
        return pd.DataFrame()

    feature_cols = [c for c in _team_feature_columns(snapshots) if c not in ["game_id", "team"]]

    home_snapshot = snapshots[["team", "last_game_date"] + feature_cols].copy()
    home_snapshot = home_snapshot.rename(columns={"team": "home_team", "last_game_date": "home_last_game_date"})
    home_snapshot = home_snapshot.rename(columns={c: f"home_{c}" for c in feature_cols})

    away_snapshot = snapshots[["team", "last_game_date"] + feature_cols].copy()
    away_snapshot = away_snapshot.rename(columns={"team": "away_team", "last_game_date": "away_last_game_date"})
    away_snapshot = away_snapshot.rename(columns={c: f"away_{c}" for c in feature_cols})

    upcoming = upcoming.merge(home_snapshot, on="home_team", how="left")
    upcoming = upcoming.merge(away_snapshot, on="away_team", how="left")

    for side in ["home", "away"]:
        last_game_col = f"{side}_last_game_date"
        rest_col = f"{side}_rest_days"
        b2b_col = f"{side}_is_b2b"

        rest = (upcoming["game_date"] - pd.to_datetime(upcoming[last_game_col])).dt.days - 1
        upcoming[rest_col] = rest.fillna(3).clip(lower=0)
        upcoming[b2b_col] = (upcoming[rest_col] == 0).astype(int)

    # Travel distance for upcoming games: last known venue → game venue
    for side in ["home", "away"]:
        team_col    = f"{side}_team"
        venue_col   = f"{side}_last_venue_team"
        miles_col   = f"{side}_travel_miles"
        tz_col      = f"{side}_timezone_shift"
        fatigue_col = f"{side}_travel_fatigue"
        game_venue  = upcoming["home_team"]  # home team's arena is always the venue

        def _travel_row(row, side=side, game_venue_col="home_team"):
            team  = row.get(f"{side}_team",  row.get("home_team" if side=="home" else "away_team", ""))
            origin = row.get(f"{side}_last_venue_team", team)
            venue  = row.get(game_venue_col, team)
            olat, olon, otz = _TEAM_GEO.get(str(origin).upper(), (39.5, -98.35, -6))
            vlat, vlon, vtz = _TEAM_GEO.get(str(venue).upper(),  (39.5, -98.35, -6))
            miles = _haversine_miles(olat, olon, vlat, vlon)
            tz    = vtz - otz
            return pd.Series({miles_col: round(miles, 1), tz_col: tz,
                              fatigue_col: round(miles/500.0 + abs(tz), 3)})

        travel_vals = upcoming.apply(_travel_row, axis=1)
        upcoming[miles_col]   = travel_vals[miles_col]
        upcoming[tz_col]      = travel_vals[tz_col]
        upcoming[fatigue_col] = travel_vals[fatigue_col]

    elo_df = pd.DataFrame()
    if historical_matchups is not None and not historical_matchups.empty:
        elo_system = EloSystem()
        elo_system.compute(historical_matchups)
        elo_df = elo_system.get_current_ratings()

    if elo_df.empty:
        upcoming["home_elo"] = config.ELO_BASE
        upcoming["away_elo"] = config.ELO_BASE
    else:
        home_elo = elo_df.rename(columns={"team": "home_team", "elo": "home_elo"})[["home_team", "home_elo"]]
        away_elo = elo_df.rename(columns={"team": "away_team", "elo": "away_elo"})[["away_team", "away_elo"]]
        upcoming = upcoming.merge(home_elo, on="home_team", how="left")
        upcoming = upcoming.merge(away_elo, on="away_team", how="left")
        upcoming["home_elo"] = upcoming["home_elo"].fillna(config.ELO_BASE)
        upcoming["away_elo"] = upcoming["away_elo"].fillna(config.ELO_BASE)

    upcoming["elo_diff"] = upcoming["home_elo"] - upcoming["away_elo"]
    upcoming["rest_diff"] = upcoming["home_rest_days"] - upcoming["away_rest_days"]

    if "home_off_rtg" in upcoming.columns and "away_def_rtg" in upcoming.columns:
        upcoming["home_off_vs_away_def"] = upcoming["home_off_rtg"] - upcoming["away_def_rtg"]
    if "away_off_rtg" in upcoming.columns and "home_def_rtg" in upcoming.columns:
        upcoming["away_off_vs_home_def"] = upcoming["away_off_rtg"] - upcoming["home_def_rtg"]
    if "home_pace" in upcoming.columns and "away_pace" in upcoming.columns:
        upcoming["pace_diff"] = upcoming["home_pace"] - upcoming["away_pace"]

    # Streak differential (home streak advantage)
    if "home_win_streak" in upcoming.columns and "away_win_streak" in upcoming.columns:
        upcoming["streak_diff"] = upcoming["home_win_streak"] - upcoming["away_win_streak"]

    # Travel differentials for upcoming games (use last-game venue as origin)
    if "home_travel_miles" in upcoming.columns and "away_travel_miles" in upcoming.columns:
        upcoming["travel_miles_diff"]   = upcoming["home_travel_miles"]   - upcoming["away_travel_miles"]
        upcoming["timezone_shift_diff"] = upcoming["home_timezone_shift"] - upcoming["away_timezone_shift"]
        upcoming["travel_fatigue_diff"] = upcoming["home_travel_fatigue"] - upcoming["away_travel_fatigue"]

    upcoming = _add_matchup_differentials(upcoming)

    # Season phase: fraction of 82 games played (0=opening night, 1=final game)
    # Proxy: days since Oct 1 of current season year, normalized to ~180-day season
    upcoming["season_phase"] = (
        (upcoming["game_date"] - pd.to_datetime(upcoming["game_date"].dt.year.astype(str) + "-10-01"))
        .dt.days.clip(lower=0) / 180.0
    ).clip(upper=1.0)

    # ── Player availability (live injury report) ────────────────────────────
    try:
        from src.player_availability import get_live_availability_features
        upcoming = get_live_availability_features(upcoming)
        logger.info("Applied live player availability features.")
    except Exception as exc:
        logger.warning("Could not apply live availability features: %s", exc)

    return upcoming.drop(columns=["home_last_game_date", "away_last_game_date"]).sort_values("game_date").reset_index(drop=True)


# ─────────────────────────────────────────────────────────────────────────────
# Head-to-head record (within season)
# ─────────────────────────────────────────────────────────────────────────────

def build_h2h_record(matchups: pd.DataFrame) -> pd.DataFrame:
    """
    For each game, compute the home team's prior head-to-head win rate.
    """
    df = matchups.sort_values("game_date").copy()
    h2h_records = []

    for _, row in df.iterrows():
        mask = (
            (df["game_date"] < row["game_date"])
            & (df["season"] == row["season"])
            & (
                ((df["home_team"] == row["home_team"]) & (df["away_team"] == row["away_team"]))
                | ((df["home_team"] == row["away_team"]) & (df["away_team"] == row["home_team"]))
            )
        )
        prior = df[mask]
        if prior.empty:
            h2h_records.append({"game_id": row["game_id"], "h2h_home_win_pct": 0.5, "h2h_games": 0})
        else:
            home_wins = 0
            for _, game in prior.iterrows():
                if game["home_team"] == row["home_team"]:
                    home_wins += game["home_win"]
                else:
                    home_wins += (1 - game["home_win"])
            h2h_records.append({
                "game_id": row["game_id"],
                "h2h_home_win_pct": home_wins / len(prior),
                "h2h_games": len(prior),
            })

    h2h_df = pd.DataFrame(h2h_records)
    return matchups.merge(h2h_df, on="game_id", how="left")


# ─────────────────────────────────────────────────────────────────────────────
# Main historical pipeline
# ─────────────────────────────────────────────────────────────────────────────

def build_all_features(
    matchups: pd.DataFrame,
    raw_logs: pd.DataFrame,
    adv_stats: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """
    Full historical feature engineering pipeline.
    """
    logger.info("Step 1/5: Building team rolling stats...")
    team_rolling = build_team_rolling_stats(raw_logs)

    logger.info("Step 2/5: Adding rest features...")
    team_rolling = build_rest_features(team_rolling)

    logger.info("Step 2b: Adding travel distance / timezone features...")
    team_rolling = build_travel_features(team_rolling)

    logger.info("Step 3/5: Adding home/away win percentages...")
    team_rolling = build_home_away_win_pct(team_rolling)

    logger.info("Step 4/5: Building rolling advanced metrics...")
    team_rolling = build_advanced_rolling(adv_stats, team_rolling)

    logger.info("Step 5/5: Computing Elo ratings and assembling features...")
    elo_system = EloSystem()
    elo_df = elo_system.compute(matchups)
    elo_df[["game_id", "home_elo", "away_elo", "elo_diff"]].to_csv(
        PROCESSED / "elo_history.csv", index=False
    )

    features = assemble_features(matchups, team_rolling, elo_df)
    out_path = PROCESSED / "model_ready.csv"
    features.to_csv(out_path, index=False)
    logger.info("Saved model_ready.csv with %d rows and %d columns", len(features), len(features.columns))

    return features
