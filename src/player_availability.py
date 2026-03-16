"""
player_availability.py — Lineup strength features from player game logs.

For each historical game, computes how complete each team's rotation was:
  - lineup_strength      : fraction of team's expected impact that actually played (0-1)
  - stars_out            : # of top-3 impact players who did not play (0-3)
  - rotation_avail_pct   : fraction of top-8 rotation players who played (0-1)
"""

from __future__ import annotations

import logging
import time
from pathlib import Path

import numpy as np
import pandas as pd
import requests

import config

logger = logging.getLogger(__name__)

_PLAYER_LOG_CACHE = "data/raw/player_logs_{season}.csv"
MIN_AVG_MPG   = 8.0
TOP_N_PLAYERS = 8
TOP_STARS     = 3


# ── Data collection ──────────────────────────────────────────────────────────

def pull_player_game_logs(season: str, force: bool = False) -> pd.DataFrame:
    cache = Path(_PLAYER_LOG_CACHE.format(season=season.replace("/", "-")))
    cache.parent.mkdir(parents=True, exist_ok=True)
    if cache.exists() and not force:
        logger.info("  Loading player logs from cache: %s", cache)
        return pd.read_csv(cache)
    logger.info("  Pulling player game logs for %s from NBA API...", season)
    from nba_api.stats.endpoints import LeagueGameLog
    time.sleep(config.API_SLEEP)
    resp = LeagueGameLog(
        season=season,
        player_or_team_abbreviation="P",
        season_type_all_star="Regular Season",
    )
    df = resp.get_data_frames()[0]
    df.to_csv(cache, index=False)
    logger.info("  Saved %d player-game rows for %s", len(df), season)
    return df


def pull_all_player_game_logs(seasons: list[str], force: bool = False) -> pd.DataFrame:
    dfs = []
    for season in seasons:
        try:
            df = pull_player_game_logs(season, force=force)
            df["season"] = season
            dfs.append(df)
            time.sleep(config.API_SLEEP)
        except Exception as exc:
            logger.warning("Failed to pull player logs for %s: %s", season, exc)
    return pd.concat(dfs, ignore_index=True) if dfs else pd.DataFrame()


# ── Impact scores ────────────────────────────────────────────────────────────

def compute_player_impact_scores(player_logs: pd.DataFrame) -> pd.DataFrame:
    """impact_score = 0.6 * minutes_share + 0.4 * points_share per player per season."""
    logs = player_logs.copy()
    logs.columns = [c.upper() for c in logs.columns]

    # Normalise the season column name
    for cand in ("SEASON", "season"):
        if cand in logs.columns and cand != "SEASON":
            logs = logs.rename(columns={cand: "SEASON"})
    if "SEASON" not in logs.columns:
        logs["SEASON"] = "unknown"

    logs["MIN_F"] = pd.to_numeric(logs.get("MIN", 0), errors="coerce").fillna(0.0)
    logs["PTS_F"] = pd.to_numeric(logs.get("PTS", 0), errors="coerce").fillna(0.0)

    agg = (
        logs.groupby(["SEASON", "TEAM_ABBREVIATION", "PLAYER_ID", "PLAYER_NAME"])
        .agg(games_played=("GAME_ID", "count"), avg_min=("MIN_F", "mean"), avg_pts=("PTS_F", "mean"))
        .reset_index()
    )
    agg = agg[agg["avg_min"] >= MIN_AVG_MPG].copy()

    team_totals = (
        agg.groupby(["SEASON", "TEAM_ABBREVIATION"])
        .agg(team_avg_min=("avg_min", "sum"), team_avg_pts=("avg_pts", "sum"))
        .reset_index()
    )
    agg = agg.merge(team_totals, on=["SEASON", "TEAM_ABBREVIATION"], how="left")

    min_share = np.where(agg["team_avg_min"] > 0, agg["avg_min"] / agg["team_avg_min"], 0)
    pts_share = np.where(agg["team_avg_pts"] > 0, agg["avg_pts"] / agg["team_avg_pts"], 0)
    agg["impact_score"] = 0.6 * min_share + 0.4 * pts_share

    agg = (
        agg.sort_values("impact_score", ascending=False)
        .groupby(["SEASON", "TEAM_ABBREVIATION"])
        .head(TOP_N_PLAYERS)
        .reset_index(drop=True)
    )
    return agg[["SEASON", "TEAM_ABBREVIATION", "PLAYER_ID", "PLAYER_NAME",
                "games_played", "avg_min", "avg_pts", "impact_score"]]


# ── Per-game availability ─────────────────────────────────────────────────────

def build_historical_availability_features(
    player_logs: pd.DataFrame,
    impact_df: pd.DataFrame,
) -> pd.DataFrame:
    logs = player_logs.copy()
    logs.columns = [c.upper() for c in logs.columns]
    for cand in ("season",):
        if cand in logs.columns:
            logs = logs.rename(columns={cand: "SEASON"})
    if "SEASON" not in logs.columns:
        logs["SEASON"] = "unknown"

    logs["MIN_F"] = pd.to_numeric(logs.get("MIN", 0), errors="coerce").fillna(0.0)
    logs["played"] = logs["MIN_F"] > 0
    logs["game_id_int"] = pd.to_numeric(logs["GAME_ID"], errors="coerce").fillna(0).astype(int)

    records = []
    for (season, team), team_impact in impact_df.groupby(["SEASON", "TEAM_ABBREVIATION"]):
        team_impact = team_impact.sort_values("impact_score", ascending=False).reset_index(drop=True)
        total_expected = team_impact["impact_score"].sum()
        top_stars   = set(team_impact.head(TOP_STARS)["PLAYER_ID"].tolist())
        rotation    = set(team_impact["PLAYER_ID"].tolist())

        team_games = logs[
            (logs["SEASON"] == season) & (logs["TEAM_ABBREVIATION"] == team)
        ]
        if team_games.empty:
            continue

        for game_id, game_players in team_games.groupby("game_id_int"):
            played_ids = set(game_players[game_players["played"]]["PLAYER_ID"].tolist())
            avail_impact = team_impact[team_impact["PLAYER_ID"].isin(played_ids)]["impact_score"].sum()

            records.append({
                "game_id":             int(game_id),
                "TEAM_ABBREVIATION":   team,
                "SEASON":              season,
                "lineup_strength":     round(float(avail_impact / total_expected if total_expected > 0 else 1.0), 4),
                "stars_out":           int(sum(1 for p in top_stars if p not in played_ids)),
                "rotation_avail_pct":  round(float(sum(1 for p in rotation if p in played_ids) / len(rotation) if rotation else 1.0), 4),
            })

    return pd.DataFrame(records)


def build_team_game_availability(player_logs: pd.DataFrame) -> pd.DataFrame:
    """Full pipeline: player_logs → availability DataFrame (one row per game-team)."""
    if player_logs.empty:
        return pd.DataFrame()
    impact_df = compute_player_impact_scores(player_logs)
    logger.info("  Impact scores computed for %d player-season records", len(impact_df))
    avail_df = build_historical_availability_features(player_logs, impact_df)
    logger.info("  Availability features built for %d team-game records", len(avail_df))
    return avail_df


# ── Merge into feature matrix ────────────────────────────────────────────────

def merge_availability_into_features(
    features_df: pd.DataFrame,
    avail_df: pd.DataFrame,
) -> pd.DataFrame:
    if avail_df.empty:
        logger.warning("Availability DataFrame empty; skipping merge.")
        return features_df

    df = features_df.copy()

    home_avail = avail_df.rename(columns={
        "lineup_strength": "home_lineup_strength",
        "stars_out": "home_stars_out",
        "rotation_avail_pct": "home_rotation_avail_pct",
        "TEAM_ABBREVIATION": "home_team",
    })[["game_id", "home_team", "home_lineup_strength", "home_stars_out", "home_rotation_avail_pct"]]

    away_avail = avail_df.rename(columns={
        "lineup_strength": "away_lineup_strength",
        "stars_out": "away_stars_out",
        "rotation_avail_pct": "away_rotation_avail_pct",
        "TEAM_ABBREVIATION": "away_team",
    })[["game_id", "away_team", "away_lineup_strength", "away_stars_out", "away_rotation_avail_pct"]]

    # Align game_id types
    for d in [df, home_avail, away_avail]:
        if "game_id" in d.columns:
            d["game_id"] = pd.to_numeric(d["game_id"], errors="coerce").astype("Int64")

    df = df.merge(home_avail, on=["game_id", "home_team"], how="left")
    df = df.merge(away_avail, on=["game_id", "away_team"], how="left")

    for col in ["home_lineup_strength", "away_lineup_strength",
                "home_rotation_avail_pct", "away_rotation_avail_pct"]:
        if col in df.columns:
            df[col] = df[col].fillna(1.0)
    for col in ["home_stars_out", "away_stars_out"]:
        if col in df.columns:
            df[col] = df[col].fillna(0.0)

    df["lineup_strength_diff"] = df["home_lineup_strength"]    - df["away_lineup_strength"]
    df["stars_out_diff"]       = df["away_stars_out"]          - df["home_stars_out"]
    df["rotation_avail_diff"]  = df["home_rotation_avail_pct"] - df["away_rotation_avail_pct"]

    logger.info("  Availability features merged: lineup_strength_diff, stars_out_diff, rotation_avail_diff + per-team")
    return df


# ── Live availability for upcoming games ─────────────────────────────────────

# ── ESPN roster-based injury fetch (reliable fallback) ────────────────────────

ESPN_TEAM_IDS: dict[str, int] = {
    "ATL": 1,  "BKN": 17, "BOS": 2,  "CHA": 30, "CHI": 4,
    "CLE": 5,  "DAL": 6,  "DEN": 7,  "DET": 8,  "GSW": 9,
    "HOU": 10, "IND": 11, "LAC": 12, "LAL": 13, "MEM": 29,
    "MIA": 14, "MIL": 15, "MIN": 16, "NOP": 3,  "NYK": 18,
    "OKC": 25, "ORL": 19, "PHI": 20, "PHX": 21, "POR": 22,
    "SAS": 24, "SAC": 23, "TOR": 28, "UTA": 26, "WAS": 27,
}
# ESPN uses slightly different abbreviations for some teams
_ESPN_ABR_MAP: dict[str, str] = {"GS": "GSW", "NO": "NOP", "NY": "NYK", "SA": "SAS", "UTAH": "UTA", "WSH": "WAS"}


def _fetch_espn_roster_injuries(team_abr: str) -> list[dict]:
    """Fetch injured players for one team via ESPN roster endpoint."""
    abr = _ESPN_ABR_MAP.get(team_abr, team_abr)
    team_id = ESPN_TEAM_IDS.get(abr)
    if not team_id:
        return []
    try:
        url = f"https://site.api.espn.com/apis/site/v2/sports/basketball/nba/teams/{team_id}/roster"
        resp = requests.get(url, timeout=8, headers={"User-Agent": "Mozilla/5.0"})
        resp.raise_for_status()
        athletes = resp.json().get("athletes", [])
    except Exception as exc:
        logger.debug("ESPN roster fetch failed for %s: %s", team_abr, exc)
        return []

    out = []
    for athlete in athletes:
        injuries = athlete.get("injuries", [])
        if not injuries:
            continue
        for inj in injuries:
            status = str(inj.get("status", "")).strip()
            if status in ("Out", "Doubtful", "Questionable", "Day-To-Day"):
                out.append({
                    "player_name": athlete.get("displayName", ""),
                    "status": status,
                    "team": abr,
                    "reason": inj.get("shortComment", "") or inj.get("type", {}).get("description", ""),
                })
    return out


def fetch_all_espn_injuries(teams: list[str] | None = None) -> dict[str, list[dict]]:
    """
    Return {team_abr: [injury_dict, ...]} for all (or specified) NBA teams.
    Uses ESPN roster endpoint — no PDF, no rate limits, always fresh.
    """
    targets = teams if teams else list(ESPN_TEAM_IDS.keys())
    result: dict[str, list[dict]] = {}
    for abr in targets:
        injuries = _fetch_espn_roster_injuries(abr)
        if injuries:
            result[abr] = injuries
    return result


# Weight applied per injury status (fraction of full Elo penalty)
_STATUS_WEIGHT: dict[str, float] = {
    "Out":         1.00,
    "Doubtful":    0.60,
    "Day-To-Day":  0.25,
    "Questionable":0.25,
}
# Elo penalty = PPG * _PPG_SCALE, clamped to [_MIN_PENALTY, _MAX_PENALTY] per player
_PPG_SCALE   = 2.5   # 20 PPG player → 50 Elo pts, 27 PPG Curry → 67.5 Elo pts
_MIN_PENALTY = 10.0  # floor — even a backup missing matters a little
_MAX_PENALTY_PER_PLAYER = 80.0  # cap — no single player worth more than this


def _build_ppg_lookup(stats_df: pd.DataFrame) -> dict[str, float]:
    """Return {normalized_name: ppg} from the player stats cache."""
    if stats_df is None or stats_df.empty or "PLAYER_NAME" not in stats_df.columns:
        return {}
    lookup: dict[str, float] = {}
    for _, row in stats_df.iterrows():
        name = str(row.get("PLAYER_NAME", "")).strip().lower()
        ppg  = float(row.get("PTS", 0) or 0)
        if name:
            lookup[name] = ppg
    return lookup


def _player_elo_penalty(player_name: str, status: str, ppg_lookup: dict[str, float]) -> float:
    """Compute Elo penalty for one injured player, scaled by their season PPG."""
    norm = player_name.strip().lower()
    ppg  = ppg_lookup.get(norm, 0.0)

    # Fuzzy fallback: match on last name if exact match fails
    if ppg == 0.0:
        last = norm.split()[-1] if norm else ""
        candidates = {k: v for k, v in ppg_lookup.items() if last and k.endswith(last)}
        if len(candidates) == 1:
            ppg = next(iter(candidates.values()))

    # Fallback when player not in cache — use a conservative league-average starter estimate
    if ppg == 0.0:
        ppg = 12.0

    raw_penalty = float(np.clip(ppg * _PPG_SCALE, _MIN_PENALTY, _MAX_PENALTY_PER_PLAYER))
    weight      = _STATUS_WEIGHT.get(status, 0.0)
    return raw_penalty * weight


def _espn_injuries_to_adjustments(
    espn_injuries: dict[str, list[dict]],
    player_stats_df: pd.DataFrame | None = None,
    max_penalty: float = 150.0,
) -> dict[str, dict]:
    """
    Convert ESPN injury dicts to per-team Elo adjustments.
    Penalty scales with each player's season PPG so losing Curry hurts
    far more than losing a backup.
    Returns {team_abr: {penalty_elo, out_count, doubtful_count, ...}}.
    """
    # Load stats cache if not provided
    if player_stats_df is None:
        try:
            player_stats_df = pd.read_csv(config.PLAYER_STATS_CACHE)
        except Exception:
            player_stats_df = pd.DataFrame()

    ppg_lookup = _build_ppg_lookup(player_stats_df)

    adj: dict[str, dict] = {}
    for team, injuries in espn_injuries.items():
        out_ct  = sum(1 for i in injuries if i["status"] == "Out")
        dbt_ct  = sum(1 for i in injuries if i["status"] == "Doubtful")
        q_ct    = sum(1 for i in injuries if i["status"] in ("Questionable", "Day-To-Day"))

        total_penalty = 0.0
        player_details: list[dict] = []
        for inj in injuries:
            pen = _player_elo_penalty(inj["player_name"], inj["status"], ppg_lookup)
            total_penalty += pen
            player_details.append({
                "name":   inj["player_name"],
                "status": inj["status"],
                "penalty": round(pen, 1),
            })

        total_penalty = min(max_penalty, total_penalty)

        adj[team] = {
            "penalty_elo":        round(total_penalty, 1),
            "out_count":          out_ct,
            "doubtful_count":     dbt_ct,
            "questionable_count": q_ct,
            "players_out":        [i["player_name"] for i in injuries if i["status"] == "Out"],
            "player_details":     player_details,
        }
    return adj


def get_live_availability_features(games_df: pd.DataFrame) -> pd.DataFrame:
    """
    For upcoming games, approximate lineup features from the live NBA injury report.
    Falls back to full-strength defaults if the report is unavailable.
    """
    df = games_df.copy()
    for col in ["home_lineup_strength", "away_lineup_strength",
                "home_rotation_avail_pct", "away_rotation_avail_pct"]:
        if col not in df.columns:
            df[col] = 1.0
    for col in ["home_stars_out", "away_stars_out"]:
        if col not in df.columns:
            df[col] = 0.0

    try:
        # Primary: ESPN roster endpoint — always fresh, no PDF dependency
        all_teams = list({row.get("home_team","") for _, row in df.iterrows()} |
                         {row.get("away_team","") for _, row in df.iterrows()})
        espn_injuries = fetch_all_espn_injuries(teams=all_teams)
        adj = _espn_injuries_to_adjustments(espn_injuries, max_penalty=config.INJURY_MAX_TEAM_ELO_PENALTY)

        if adj:
            max_penalty = config.INJURY_MAX_TEAM_ELO_PENALTY
            for i, row in df.iterrows():
                for side, team in [("home", row.get("home_team", "")), ("away", row.get("away_team", ""))]:
                    info    = adj.get(team, {})
                    penalty = float(info.get("penalty_elo", 0.0))
                    out_ct  = int(info.get("out_count", 0))
                    dbt_ct  = int(info.get("doubtful_count", 0))
                    players_out = info.get("players_out", [])
                    df.at[i, f"{side}_lineup_strength"]        = round(max(0.0, 1.0 - penalty / max_penalty), 4)
                    df.at[i, f"{side}_stars_out"]              = min(TOP_STARS, out_ct + dbt_ct)
                    df.at[i, f"{side}_rotation_avail_pct"]     = round(max(0.0, 1.0 - (out_ct + dbt_ct) / TOP_N_PLAYERS), 4)
                    df.at[i, f"{side}_out_count"]              = out_ct
                    df.at[i, f"{side}_doubtful_count"]         = dbt_ct
                    df.at[i, f"{side}_availability_penalty_elo"] = penalty
                    if players_out:
                        df.at[i, f"{side}_availability_summary"] = f"Out: {', '.join(players_out[:3])}"
            logger.info("  Applied ESPN injury adjustments for %d teams: %s",
                        len(adj), {k: v["out_count"] for k, v in adj.items() if v["out_count"] > 0})
    except Exception as exc:
        logger.warning("  Could not load ESPN injury data (%s); using full-strength defaults.", exc)

    df["lineup_strength_diff"] = df["home_lineup_strength"]    - df["away_lineup_strength"]
    df["stars_out_diff"]       = df["away_stars_out"]          - df["home_stars_out"]
    df["rotation_avail_diff"]  = df["home_rotation_avail_pct"] - df["away_rotation_avail_pct"]
    return df


# ── Star player rolling form ──────────────────────────────────────────────────

def build_star_player_form(player_logs: pd.DataFrame, windows: list[int] = [5, 10]) -> pd.DataFrame:
    """
    For each team-game, compute rolling form metrics for the team's top-2 scorers.

    Features added (per window w, for star rank 1 and 2):
        star{rank}_roll{w}_pts        - rolling avg points
        star{rank}_roll{w}_eff        - rolling true shooting % proxy (pts / fga, min 1)
        star{rank}_pts_vs_season      - current roll5 pts vs season avg (hot/cold indicator)

    Returns one row per (game_id, TEAM_ABBREVIATION).
    """
    logs = player_logs.copy()
    logs.columns = [c.upper() for c in logs.columns]
    for cand in ("season",):
        if cand in logs.columns:
            logs = logs.rename(columns={cand: "SEASON"})
    if "SEASON" not in logs.columns:
        logs["SEASON"] = "unknown"

    logs["MIN_F"] = pd.to_numeric(logs.get("MIN", 0), errors="coerce").fillna(0.0)
    logs["PTS_F"] = pd.to_numeric(logs.get("PTS", 0), errors="coerce").fillna(0.0)
    logs["FGA_F"] = pd.to_numeric(logs.get("FGA", 1), errors="coerce").fillna(1.0).clip(lower=1)
    logs["GAME_DATE_DT"] = pd.to_datetime(logs["GAME_DATE"], errors="coerce")
    logs["game_id_int"]  = pd.to_numeric(logs["GAME_ID"], errors="coerce").fillna(0).astype(int)

    # Identify top-2 scorers per team per season
    season_avgs = (
        logs[logs["MIN_F"] >= MIN_AVG_MPG]
        .groupby(["SEASON", "TEAM_ABBREVIATION", "PLAYER_ID"])
        .agg(avg_pts=("PTS_F", "mean"), season_avg_pts=("PTS_F", "mean"), games=("GAME_ID", "count"))
        .reset_index()
    )
    season_avgs["star_rank"] = (
        season_avgs.sort_values("avg_pts", ascending=False)
        .groupby(["SEASON", "TEAM_ABBREVIATION"])
        .cumcount() + 1
    )
    top2 = season_avgs[season_avgs["star_rank"] <= 2].copy()

    records = []
    for (season, team), star_df in top2.groupby(["SEASON", "TEAM_ABBREVIATION"]):
        team_logs = logs[
            (logs["SEASON"] == season) & (logs["TEAM_ABBREVIATION"] == team)
        ].sort_values("GAME_DATE_DT")

        for _, star_row in star_df.iterrows():
            pid   = star_row["PLAYER_ID"]
            rank  = int(star_row["star_rank"])
            s_avg = float(star_row["season_avg_pts"])
            p_logs = team_logs[team_logs["PLAYER_ID"] == pid].sort_values("GAME_DATE_DT")

            if p_logs.empty:
                continue

            for w in windows:
                roll_pts = p_logs["PTS_F"].rolling(w, min_periods=1).mean()
                roll_eff = (p_logs["PTS_F"] / p_logs["FGA_F"]).rolling(w, min_periods=1).mean()
                # Shift by 1 — pre-game info only
                roll_pts = roll_pts.shift(1).fillna(s_avg)
                roll_eff = roll_eff.shift(1).fillna(s_avg / max(p_logs["FGA_F"].mean(), 1))

                p_logs = p_logs.copy()
                p_logs[f"star{rank}_roll{w}_pts"] = roll_pts.values
                p_logs[f"star{rank}_roll{w}_eff"] = roll_eff.values

            # Hot/cold: roll5 vs season average
            roll5 = p_logs["PTS_F"].rolling(5, min_periods=1).mean().shift(1).fillna(s_avg)
            p_logs[f"star{rank}_pts_vs_season"] = (roll5 - s_avg).values

            for _, game_row in p_logs.iterrows():
                rec = {
                    "game_id": int(game_row["game_id_int"]),
                    "TEAM_ABBREVIATION": team,
                    "SEASON": season,
                }
                for w in windows:
                    rec[f"star{rank}_roll{w}_pts"] = round(float(game_row.get(f"star{rank}_roll{w}_pts", s_avg)), 3)
                    rec[f"star{rank}_roll{w}_eff"] = round(float(game_row.get(f"star{rank}_roll{w}_eff", 0)), 3)
                rec[f"star{rank}_pts_vs_season"] = round(float(game_row.get(f"star{rank}_pts_vs_season", 0)), 3)
                records.append(rec)

    df = pd.DataFrame(records)
    if df.empty:
        return df
    # Collapse star1 and star2 rows into one row per (game_id, TEAM_ABBREVIATION)
    # Each rank's columns are NaN in the other rank's row, so max() picks the real value.
    agg_cols = [c for c in df.columns if c not in ("game_id", "TEAM_ABBREVIATION", "SEASON")]
    df = (
        df.groupby(["game_id", "TEAM_ABBREVIATION", "SEASON"])[agg_cols]
        .max()
        .reset_index()
    )
    return df


def merge_star_form_into_features(
    features_df: pd.DataFrame,
    star_df: pd.DataFrame,
) -> pd.DataFrame:
    """Join star player form onto the main feature matrix with home/away prefixes."""
    if star_df.empty:
        return features_df

    df = features_df.copy()
    star_cols = [c for c in star_df.columns if c not in ("game_id", "TEAM_ABBREVIATION", "SEASON")]

    home_star = star_df.rename(columns={"TEAM_ABBREVIATION": "home_team",
                                         **{c: f"home_{c}" for c in star_cols}})
    away_star = star_df.rename(columns={"TEAM_ABBREVIATION": "away_team",
                                         **{c: f"away_{c}" for c in star_cols}})

    for d in [df, home_star, away_star]:
        if "game_id" in d.columns:
            d["game_id"] = pd.to_numeric(d["game_id"], errors="coerce").astype("Int64")

    df = df.merge(home_star.drop(columns=["SEASON"], errors="ignore"),
                  on=["game_id", "home_team"], how="left")
    df = df.merge(away_star.drop(columns=["SEASON"], errors="ignore"),
                  on=["game_id", "away_team"], how="left")

    # Fill missing with 0 (neutral — unknown form)
    for col in [c for c in df.columns if any(c.startswith(p) for p in ["home_star", "away_star"])]:
        df[col] = df[col].fillna(0.0)

    # Differential: home star1 roll5 pts vs away star1 roll5 pts
    if "home_star1_roll5_pts" in df.columns and "away_star1_roll5_pts" in df.columns:
        df["star1_pts_diff"] = df["home_star1_roll5_pts"] - df["away_star1_roll5_pts"]
    if "home_star1_pts_vs_season" in df.columns and "away_star1_pts_vs_season" in df.columns:
        df["star1_form_diff"] = df["home_star1_pts_vs_season"] - df["away_star1_pts_vs_season"]

    logger.info("  Star player form features merged (%d new columns)", len(star_cols) * 2 + 2)
    return df
