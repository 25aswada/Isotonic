"""
ncaab_live.py - Current-season NCAA team stats and bracket projection ingestion.
"""

from __future__ import annotations

import json
import logging
import re
import time
from datetime import datetime, timezone
from difflib import SequenceMatcher
from html import unescape
from html.parser import HTMLParser

import numpy as np
import pandas as pd
import requests

import ncaab_config
from src.ncaab_availability import apply_ncaab_availability_adjustments
from src.ncaab_predict import load_seed_matchup_baselines, predict_matchup

logger = logging.getLogger(__name__)

SPORTSREF_BASE_URL = "https://www.sports-reference.com"
CURRENT_ELO_HOME_EDGE = 70.0
CURRENT_ELO_K = 20.0

TEAM_ALIASES = {
    "uconn": "connecticut",
    "ole miss": "mississippi",
    "smu": "southern methodist",
    "vcu": "virginia commonwealth",
    "byu": "brigham young",
    "usc": "southern california",
    "pitt": "pittsburgh",
    "st johns": "st john's ny",
    "saint johns": "st john's ny",
    "saint marys": "saint mary's ca",
    "saint marys ca": "saint mary's ca",
    "miami": "miami fl",
    "miami fl": "miami fl",
    "nc state": "north carolina state",
    "nc central": "north carolina central",
    "nccu": "north carolina central",
    "unc": "north carolina",
    "usf": "south florida",
    "ucf": "central florida",
    "n dakota st": "north dakota state",
    "ndsu": "north dakota state",
    "cal baptist": "california baptist",
    "mcneese": "mcneese state",
    "wright st": "wright state",
    "tennessee st": "tennessee state",
    "saint louis": "saint louis",
    "long island": "long island university",
    "miami oh": "miami oh",
    "prairie view": "prairie view a&m",
    "hawai'i": "hawaii",
    "queens": "queens nc",
    "kennesaw st": "kennesaw state",
    "uab": "alabama-birmingham",
    "unc wilmington": "north carolina-wilmington",
    "unc greensboro": "north carolina-greensboro",
    "st josephs": "saint joseph's",
    "saint josephs": "saint joseph's",
    "umbc": "maryland baltimore county",
    "umass": "massachusetts",
    "mass": "massachusetts",
    "st bonaventure": "saint bonaventure",
    "sbu": "saint bonaventure",
    "penn": "pennsylvania",
    "lsu": "louisiana state",
    "tcu": "texas christian",
    "unlv": "nevada-las vegas",
    "utep": "texas-el paso",
    "utsa": "texas-san antonio",
    "fiu": "florida international",
    "fau": "florida atlantic",
}

ROUND_ONE_PAIRINGS = [
    (1, 16),
    (8, 9),
    (5, 12),
    (4, 13),
    (6, 11),
    (3, 14),
    (7, 10),
    (2, 15),
]


def _clean_text(value: str) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and np.isnan(value):
        return ""
    text = unescape(str(value))
    text = re.sub(r"\s+", " ", text.replace("\xa0", " ")).strip()
    return text


def normalize_team_name(name: str) -> str:
    """Normalize team names across Sports Reference, NCAA, and bracketology sources."""
    text = _clean_text(name).lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\(([^)]*)\)", r" \1 ", text)
    text = text.replace("st.", "saint")
    text = re.sub(r"\bst\b", "saint", text)
    text = text.replace("'", "")
    text = text.replace("’", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return TEAM_ALIASES.get(text, text)


def best_name_match(name: str, candidates: list[str]) -> str:
    """Find the best matching team name from a candidate list."""
    normalized_target = normalize_team_name(name)
    candidate_map = {normalize_team_name(candidate): candidate for candidate in candidates}

    if normalized_target in candidate_map:
        return candidate_map[normalized_target]

    if normalized_target in TEAM_ALIASES and TEAM_ALIASES[normalized_target] in candidate_map:
        return candidate_map[TEAM_ALIASES[normalized_target]]

    best_candidate = None
    best_score = -1.0
    for candidate_norm, candidate in candidate_map.items():
        score = SequenceMatcher(None, normalized_target, candidate_norm).ratio()
        if score > best_score:
            best_score = score
            best_candidate = candidate

    if best_candidate is None or best_score < 0.65:
        raise KeyError(f"Could not match team name {name!r}")
    return best_candidate


class StatTableParser(HTMLParser):
    """Parse an HTML table keyed by data-stat attributes."""

    def __init__(self, table_id: str) -> None:
        super().__init__()
        self.table_id = table_id
        self.in_table = False
        self.in_tbody = False
        self.in_row = False
        self.in_cell = False
        self.rows: list[dict[str, str]] = []
        self.current_row: dict[str, str] = {}
        self.current_key = ""
        self.current_text: list[str] = []
        self.current_href = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr_map = dict(attrs)
        if tag == "table" and attr_map.get("id") == self.table_id:
            self.in_table = True
            return
        if not self.in_table:
            return
        if tag == "tbody":
            self.in_tbody = True
        elif tag == "tr" and self.in_tbody:
            self.in_row = True
            self.current_row = {}
        elif tag in {"td", "th"} and self.in_row:
            self.in_cell = True
            self.current_key = attr_map.get("data-stat") or f"col_{len(self.current_row)}"
            self.current_text = []
            self.current_href = ""
        elif tag == "a" and self.in_cell:
            self.current_href = attr_map.get("href") or self.current_href

    def handle_data(self, data: str) -> None:
        if self.in_table and self.in_row and self.in_cell:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_table:
            return
        if tag in {"td", "th"} and self.in_cell:
            self.current_row[self.current_key] = _clean_text("".join(self.current_text))
            if self.current_href:
                self.current_row[f"{self.current_key}_href"] = self.current_href
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if self.current_row and not self.current_row.get("school_name", "").startswith("School"):
                self.rows.append(self.current_row.copy())
            self.in_row = False
        elif tag == "tbody":
            self.in_tbody = False
        elif tag == "table":
            self.in_table = False


class PlainTableParser(HTMLParser):
    """Parse a simple HTML table into rows of cell text."""

    def __init__(self) -> None:
        super().__init__()
        self.table_seen = False
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.rows: list[list[str]] = []
        self.current_row: list[str] = []
        self.current_text: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "table" and not self.table_seen:
            self.table_seen = True
            self.in_table = True
            return
        if not self.in_table:
            return
        if tag == "tr":
            self.in_row = True
            self.current_row = []
        elif tag in {"td", "th"} and self.in_row:
            self.in_cell = True
            self.current_text = []

    def handle_data(self, data: str) -> None:
        if self.in_table and self.in_row and self.in_cell:
            self.current_text.append(data)

    def handle_endtag(self, tag: str) -> None:
        if not self.in_table:
            return
        if tag in {"td", "th"} and self.in_cell:
            self.current_row.append(_clean_text("".join(self.current_text)))
            self.in_cell = False
        elif tag == "tr" and self.in_row:
            if any(cell for cell in self.current_row):
                self.rows.append(self.current_row.copy())
            self.in_row = False
        elif tag == "table":
            self.in_table = False


def _fetch_html(url: str) -> str:
    last_error: Exception | None = None
    for attempt in range(3):
        response = requests.get(url, timeout=60, headers={"User-Agent": "Mozilla/5.0"})
        if response.status_code == 429:
            retry_after = response.headers.get("Retry-After")
            sleep_seconds = float(retry_after) if retry_after else min(1.5 * (attempt + 1), 4.0)
            time.sleep(sleep_seconds)
            last_error = requests.HTTPError(f"429 rate limited for {url}")
            continue
        try:
            response.raise_for_status()
            return response.text
        except requests.HTTPError as exc:
            last_error = exc
            if 500 <= response.status_code < 600 and attempt < 2:
                time.sleep(min(1.5 * (attempt + 1), 4.0))
                continue
            raise
    if last_error is not None:
        raise last_error
    raise RuntimeError(f"Failed to fetch {url}")


def fetch_stat_table(url: str, table_id: str) -> pd.DataFrame:
    """Fetch a data-stat keyed HTML table into a DataFrame."""
    parser = StatTableParser(table_id)
    parser.feed(_fetch_html(url))
    return pd.DataFrame(parser.rows)


def fetch_plain_table(url: str) -> list[list[str]]:
    """Fetch the first HTML table from a page as raw text rows."""
    parser = PlainTableParser()
    parser.feed(_fetch_html(url))
    return parser.rows


def _absolute_sportsref_url(path: str) -> str:
    if path is None:
        return ""
    if isinstance(path, float) and np.isnan(path):
        return ""
    path = str(path).strip()
    if not path:
        return ""
    if path.startswith("http://") or path.startswith("https://"):
        return path
    return f"{SPORTSREF_BASE_URL}{path}"


def _sportsref_variant_url(base_url: str, suffix: str) -> str:
    if not base_url:
        return ""
    return re.sub(r"\.html$", suffix, base_url)


def _clean_ranked_team_name(value: str) -> str:
    return re.sub(r"\s*\(\d+\)\s*$", "", _clean_text(value)).strip()


def _canonical_team_name(value: str, candidates: list[str]) -> str:
    cleaned = _clean_ranked_team_name(value)
    if not cleaned:
        return cleaned
    try:
        return best_name_match(cleaned, candidates)
    except KeyError:
        return cleaned


def fetch_current_team_stats(season: int = ncaab_config.CURRENT_SEASON) -> pd.DataFrame:
    """Fetch current-season school stats from Sports Reference."""
    basic_df = fetch_stat_table(ncaab_config.CURRENT_SPORTSREF_BASIC_URL, "basic_school_stats")
    advanced_df = fetch_stat_table(ncaab_config.CURRENT_SPORTSREF_ADVANCED_URL, "adv_school_stats")

    basic_df["TeamName"] = basic_df["school_name"].str.replace("*", "", regex=False).str.strip()
    advanced_df["TeamName"] = advanced_df["school_name"].str.replace("*", "", regex=False).str.strip()
    basic_df = basic_df.dropna(subset=["TeamName"])
    advanced_df = advanced_df.dropna(subset=["TeamName"])
    basic_df = basic_df[basic_df["TeamName"].astype(str).str.strip() != ""].drop_duplicates(subset=["TeamName"])
    advanced_df = (
        advanced_df[advanced_df["TeamName"].astype(str).str.strip() != ""]
        .drop_duplicates(subset=["TeamName"])
    )

    adv_cols = [
        "TeamName",
        "pace",
        "off_rtg",
        "ts_pct",
        "efg_pct",
        "tov_pct",
        "orb_pct",
        "ft_rate",
    ]
    # Pull optional advanced columns when available.
    for optional in ("opp_efg_pct", "opp_tov_pct", "def_rtg"):
        if optional in advanced_df.columns:
            adv_cols.append(optional)
    merged = basic_df.merge(
        advanced_df[[c for c in adv_cols if c in advanced_df.columns]],
        on="TeamName",
        how="inner",
    )

    numeric_cols = [
        "g",
        "wins",
        "losses",
        "win_loss_pct",
        "srs",
        "sos",
        "pts",
        "opp_pts",
        "pace",
        "off_rtg",
        "ts_pct",
        "efg_pct",
        "tov_pct",
        "orb_pct",
        "ft_rate",
    ]
    # Extra basic-stats columns for new features.
    for optional in ("fg", "fga", "fg3a", "ft", "fta", "ast", "stl", "blk", "drb",
                      "opp_efg_pct", "opp_tov_pct", "def_rtg"):
        if optional in merged.columns:
            numeric_cols.append(optional)
    for column in numeric_cols:
        if column in merged.columns:
            merged[column] = pd.to_numeric(merged[column], errors="coerce")

    games = merged["g"].replace(0, np.nan)
    merged["Season"] = season
    merged["win_pct"] = merged["win_loss_pct"]
    merged["avg_score_for"] = merged["pts"] / games
    merged["avg_score_against"] = merged["opp_pts"] / games
    merged["avg_margin"] = merged["avg_score_for"] - merged["avg_score_against"]
    merged["efg"] = merged["efg_pct"]
    merged["ts"] = merged["ts_pct"]
    merged["tov_rate"] = merged["tov_pct"] / 100.0
    merged["ft_rate"] = merged["ft_rate"]
    merged["oreb_pct"] = merged["orb_pct"] / 100.0
    merged["off_rtg"] = merged["off_rtg"]
    if "def_rtg" not in merged.columns or merged["def_rtg"].isna().all():
        merged["def_rtg"] = 100.0 * merged["avg_score_against"] / merged["pace"].replace(0, np.nan)
    merged["net_rtg"] = merged["off_rtg"] - merged["def_rtg"]

    # ── New features ──
    merged["pace"] = merged["pace"]  # already numeric
    if "fga" in merged.columns and "fg3a" in merged.columns:
        merged["fg3_rate"] = merged["fg3a"] / merged["fga"].replace(0, np.nan)
    else:
        merged["fg3_rate"] = np.nan
    if "ft" in merged.columns and "fta" in merged.columns:
        merged["ft_pct"] = merged["ft"] / merged["fta"].replace(0, np.nan)
    else:
        merged["ft_pct"] = np.nan
    if "ast" in merged.columns and "fg" in merged.columns:
        merged["ast_rate"] = merged["ast"] / merged["fg"].replace(0, np.nan)
    else:
        merged["ast_rate"] = np.nan
    total_poss = games * merged["pace"].replace(0, np.nan)
    if "stl" in merged.columns:
        merged["stl_rate"] = merged["stl"] / total_poss
    else:
        merged["stl_rate"] = np.nan
    if "blk" in merged.columns:
        merged["blk_rate"] = merged["blk"] / total_poss
    else:
        merged["blk_rate"] = np.nan
    if "drb" in merged.columns:
        # dreb_pct ≈ DRB / (DRB + opp_ORB).  Use ORB pct as rough inverse.
        merged["dreb_pct"] = 1.0 - merged["oreb_pct"]
    else:
        merged["dreb_pct"] = np.nan
    if "opp_tov_pct" in merged.columns:
        merged["opp_tov_rate"] = merged["opp_tov_pct"] / 100.0
    else:
        merged["opp_tov_rate"] = np.nan

    merged["school_url"] = merged.get("school_name_href", pd.Series("", index=merged.index)).map(_absolute_sportsref_url)
    merged["schedule_url"] = merged["school_url"].map(lambda value: _sportsref_variant_url(value, "-schedule.html"))
    merged["gamelog_url"] = merged["school_url"].map(lambda value: _sportsref_variant_url(value, "-gamelogs.html"))

    output_cols = [
        "Season",
        "TeamName",
        "g",
        "wins",
        "losses",
        "win_pct",
        "avg_margin",
        "avg_score_for",
        "avg_score_against",
        "efg",
        "ts",
        "tov_rate",
        "ft_rate",
        "oreb_pct",
        "off_rtg",
        "def_rtg",
        "net_rtg",
        "srs",
        "sos",
        "pace",
        "fg3_rate",
        "ft_pct",
        "ast_rate",
        "stl_rate",
        "blk_rate",
        "dreb_pct",
        "opp_tov_rate",
        "school_url",
        "schedule_url",
        "gamelog_url",
    ]
    return merged[[c for c in output_cols if c in merged.columns]].copy()


def fetch_team_game_log(team_name: str, gamelog_url: str, team_candidates: list[str]) -> pd.DataFrame:
    """Fetch a team's current-season game log."""
    if not gamelog_url:
        return pd.DataFrame()

    try:
        game_log = fetch_stat_table(gamelog_url, "team_game_log")
    except requests.HTTPError as exc:
        logger.warning("Skipping %s game log due to fetch failure: %s", team_name, exc)
        return pd.DataFrame()
    if game_log.empty:
        return pd.DataFrame()

    numeric_columns = [
        "team_game_score",
        "opp_team_game_score",
        "opp_efg_pct",
    ]
    for column in numeric_columns:
        game_log[column] = pd.to_numeric(game_log[column], errors="coerce")

    game_log["date"] = pd.to_datetime(game_log["date"], errors="coerce")
    game_log["TeamName"] = team_name
    game_log["OppTeamName"] = game_log["opp_name_abbr"].map(lambda value: _canonical_team_name(value, team_candidates))
    game_log["game_location"] = game_log["game_location"].fillna("")
    result = game_log["team_game_result"].astype(str).str.strip().str[:1]
    game_log["win"] = np.where(result == "W", 1.0, np.where(result == "L", 0.0, np.nan))
    game_log["team_score"] = game_log["team_game_score"]
    game_log["opp_score"] = game_log["opp_team_game_score"]
    game_log["margin"] = game_log["team_score"] - game_log["opp_score"]
    game_log["opp_efg"] = game_log["opp_efg_pct"]

    return game_log.dropna(subset=["date", "team_score", "opp_score"])[
        [
            "TeamName",
            "OppTeamName",
            "date",
            "game_location",
            "win",
            "team_score",
            "opp_score",
            "margin",
            "opp_efg",
        ]
    ].copy()


def build_current_rank_features(current_stats: pd.DataFrame) -> pd.DataFrame:
    """Create current multi-source rank features from live summary stats."""
    rank_df = current_stats[["TeamName", "srs", "net_rtg"]].copy()
    rank_df = rank_df.dropna(subset=["TeamName"])
    rank_df = rank_df[rank_df["TeamName"].astype(str).str.strip() != ""].drop_duplicates(subset=["TeamName"])
    rank_df["srs_rank"] = rank_df["srs"].rank(method="min", ascending=False)
    rank_df["efficiency_rank"] = rank_df["net_rtg"].rank(method="min", ascending=False)
    return rank_df[["TeamName", "srs_rank", "efficiency_rank"]]


def compute_current_projected_elo(projected_game_logs: pd.DataFrame) -> pd.DataFrame:
    """Compute current Elo ratings from projected-team game logs."""
    if projected_game_logs.empty:
        return pd.DataFrame(columns=["TeamName", "elo"])

    ratings: dict[str, float] = {}
    seen_games: set[tuple[object, ...]] = set()

    for row in projected_game_logs.sort_values(["date", "TeamName", "OppTeamName"]).itertuples(index=False):
        if pd.isna(row.win):
            continue

        team_name = str(row.TeamName)
        opp_name = str(row.OppTeamName)
        team_score = float(row.team_score)
        opp_score = float(row.opp_score)
        game_key = (
            pd.Timestamp(row.date).date().isoformat(),
            tuple(sorted([normalize_team_name(team_name), normalize_team_name(opp_name)])),
            int(min(team_score, opp_score)),
            int(max(team_score, opp_score)),
        )
        if game_key in seen_games:
            continue
        seen_games.add(game_key)

        team_rating = ratings.get(team_name, 1500.0)
        opp_rating = ratings.get(opp_name, 1500.0)
        loc = str(row.game_location or "")
        team_effective = team_rating + (CURRENT_ELO_HOME_EDGE if loc == "" else 0.0)
        opp_effective = opp_rating + (CURRENT_ELO_HOME_EDGE if loc == "@" else 0.0)
        expected_team = 1.0 / (1.0 + 10.0 ** ((opp_effective - team_effective) / 400.0))

        margin = max(abs(team_score - opp_score), 1.0)
        multiplier = np.log(margin + 1.0) * (2.2 / ((abs(team_rating - opp_rating) * 0.001) + 2.2))
        delta = CURRENT_ELO_K * multiplier * (float(row.win) - expected_team)

        ratings[team_name] = team_rating + delta
        ratings[opp_name] = opp_rating - delta

    return pd.DataFrame(
        [{"TeamName": team_name, "elo": float(elo)} for team_name, elo in ratings.items()]
    )


def build_current_projected_team_features(
    projected_names: list[str],
    current_stats: pd.DataFrame,
) -> pd.DataFrame:
    """Build current Elo and recent-form features for projected teams."""
    projected_stats = (
        current_stats[current_stats["TeamName"].isin(projected_names)]
        .dropna(subset=["TeamName"])
        .drop_duplicates(subset=["TeamName"])
        .copy()
    )
    if projected_stats.empty:
        return pd.DataFrame(columns=["TeamName", "elo", "opp_efg", "last10_win_pct", "last10_margin"])

    def_rank = current_stats[["TeamName", "def_rtg"]].copy()
    def_rank = def_rank.dropna(subset=["TeamName"]).drop_duplicates(subset=["TeamName"])
    def_rank["def_rank_pct"] = def_rank["def_rtg"].rank(method="average", pct=True, ascending=True)

    projected_stats = projected_stats.merge(def_rank[["TeamName", "def_rank_pct"]], on="TeamName", how="left")
    margin_scale = max(float(pd.to_numeric(current_stats["avg_margin"], errors="coerce").abs().quantile(0.9)), 1.0)

    derived = projected_stats[["TeamName", "win_pct", "avg_margin", "net_rtg", "def_rank_pct"]].copy()
    derived["elo"] = (
        1500.0
        + 12.0 * pd.to_numeric(derived["net_rtg"], errors="coerce")
        + 200.0 * (pd.to_numeric(derived["win_pct"], errors="coerce") - 0.5)
    )
    derived["last10_win_pct"] = np.clip(
        pd.to_numeric(derived["win_pct"], errors="coerce")
        + 0.08 * (pd.to_numeric(derived["avg_margin"], errors="coerce") / margin_scale),
        0.0,
        1.0,
    )
    derived["last10_margin"] = (
        0.6 * pd.to_numeric(derived["avg_margin"], errors="coerce")
        + 0.4 * pd.to_numeric(derived["net_rtg"], errors="coerce")
    )
    derived["opp_efg"] = 0.44 + 0.12 * pd.to_numeric(derived["def_rank_pct"], errors="coerce")
    return derived[["TeamName", "elo", "opp_efg", "last10_win_pct", "last10_margin"]]


def _infer_seed_from_rank(rank_value: float | int | None) -> int:
    """Map an overall strength rank to an approximate tournament seed line."""
    try:
        numeric = float(rank_value)
    except (TypeError, ValueError):
        return 16
    if np.isnan(numeric):
        return 16
    return int(np.clip(np.ceil(max(numeric, 1.0) / 4.0), 1, 16))


def build_current_all_team_features(
    current_stats: pd.DataFrame,
    net_rankings: pd.DataFrame,
    projected_team_features: pd.DataFrame,
) -> pd.DataFrame:
    """Build current-season team features for all NCAA teams using projected seeds where available."""
    all_stats = current_stats.copy()
    all_stats = all_stats.dropna(subset=["TeamName"])
    all_stats = all_stats[all_stats["TeamName"].astype(str).str.strip() != ""].drop_duplicates(subset=["TeamName"])
    if all_stats.empty:
        return pd.DataFrame()

    rank_features = build_current_rank_features(current_stats)
    live_team_features = build_current_projected_team_features(
        all_stats["TeamName"].dropna().astype(str).unique().tolist(),
        current_stats,
    )
    all_stats = all_stats.merge(rank_features, on="TeamName", how="left")
    all_stats = all_stats.merge(live_team_features, on="TeamName", how="left", suffixes=("", "_live"))

    stats_candidates = all_stats["TeamName"].dropna().astype(str).tolist()
    matched_net_rows: list[dict[str, object]] = []
    for row in net_rankings.itertuples(index=False):
        try:
            matched_team = best_name_match(row.TeamName, stats_candidates)
        except KeyError:
            continue
        matched_net_rows.append({"TeamName": matched_team, "net_rank": float(row.net_rank)})

    net_df = pd.DataFrame(matched_net_rows)
    if not net_df.empty:
        net_df = net_df.groupby("TeamName", as_index=False)["net_rank"].min()
        all_stats = all_stats.merge(net_df, on="TeamName", how="left", suffixes=("", "_net"))

    rank_cols = ["net_rank", "srs_rank", "efficiency_rank"]
    rank_frame = all_stats[rank_cols].apply(pd.to_numeric, errors="coerce")
    all_stats["median_rank"] = rank_frame.median(axis=1, skipna=True)
    all_stats["best_rank"] = rank_frame.min(axis=1, skipna=True)
    fallback_rank = (
        pd.to_numeric(all_stats["srs_rank"], errors="coerce")
        .combine_first(pd.to_numeric(all_stats["efficiency_rank"], errors="coerce"))
        .combine_first(pd.Series(np.arange(1, len(all_stats) + 1), index=all_stats.index, dtype=float))
    )
    all_stats["median_rank"] = pd.to_numeric(all_stats["median_rank"], errors="coerce").fillna(fallback_rank)
    all_stats["best_rank"] = pd.to_numeric(all_stats["best_rank"], errors="coerce").fillna(fallback_rank)

    projection_cols = [
        "TeamName",
        "ProjectionName",
        "region",
        "seed_num",
        "Seed",
        "entry_text",
        "projection_source_url",
        "projection_date",
        "TeamID",
    ]
    projection_df = (
        projected_team_features[projection_cols]
        .drop_duplicates(subset=["TeamName"])
        .copy()
        if not projected_team_features.empty
        else pd.DataFrame(columns=projection_cols)
    )
    all_stats = all_stats.merge(projection_df, on="TeamName", how="left")

    all_stats["ProjectionName"] = all_stats["ProjectionName"].fillna(all_stats["TeamName"])
    inferred_seed = all_stats["median_rank"].map(_infer_seed_from_rank)
    all_stats["seed_num"] = (
        pd.to_numeric(all_stats["seed_num"], errors="coerce")
        .fillna(inferred_seed)
        .astype(int)
    )
    all_stats["Seed"] = all_stats["Seed"].fillna(all_stats["seed_num"].map(lambda seed: f"A{int(seed):02d}"))
    all_stats["entry_text"] = all_stats["entry_text"].fillna(all_stats["TeamName"])
    all_stats["projection_source_url"] = all_stats["projection_source_url"].fillna(
        ncaab_config.CURRENT_BRACKETOLOGY_URL
    )
    all_stats["projection_date"] = all_stats["projection_date"].fillna(
        ncaab_config.CURRENT_PROJECTION_DATE
    )

    all_stats["elo"] = pd.to_numeric(all_stats["elo"], errors="coerce").fillna(
        1500.0 + 12.0 * pd.to_numeric(all_stats["net_rtg"], errors="coerce")
    )
    all_stats["last10_win_pct"] = pd.to_numeric(all_stats["last10_win_pct"], errors="coerce").fillna(
        pd.to_numeric(all_stats["win_pct"], errors="coerce")
    )
    all_stats["last10_margin"] = pd.to_numeric(all_stats["last10_margin"], errors="coerce").fillna(
        pd.to_numeric(all_stats["avg_margin"], errors="coerce")
    )
    all_stats["opp_efg"] = pd.to_numeric(all_stats["opp_efg"], errors="coerce").fillna(
        float(pd.to_numeric(current_stats["efg"], errors="coerce").median())
    )

    # ── Fill new features with available data or reasonable defaults ──
    for col in ("pace", "fg3_rate", "ft_pct", "ast_rate", "stl_rate", "blk_rate",
                "dreb_pct", "opp_tov_rate"):
        if col not in all_stats.columns:
            all_stats[col] = np.nan
        all_stats[col] = pd.to_numeric(all_stats[col], errors="coerce")

    # std_margin: computed from game logs if available, otherwise approximate from SRS.
    if "std_margin" not in all_stats.columns:
        srs_val = pd.to_numeric(all_stats.get("srs", pd.Series(dtype=float)), errors="coerce")
        all_stats["std_margin"] = np.clip(12.0 - 0.15 * srs_val.abs(), 6.0, 18.0)

    # SOS proxies — use Sports Reference SOS (avg opponent SRS) as basis.
    sos_val = pd.to_numeric(all_stats.get("sos", pd.Series(dtype=float)), errors="coerce").fillna(0.0)
    if "avg_opp_win_pct" not in all_stats.columns:
        all_stats["avg_opp_win_pct"] = 0.5 + sos_val / 40.0  # rough linear map
    if "avg_opp_elo" not in all_stats.columns:
        all_stats["avg_opp_elo"] = 1500.0 + sos_val * 12.0  # rough linear map

    all_stats = all_stats.sort_values("TeamName").reset_index(drop=True)
    if "TeamID" in all_stats.columns:
        max_existing_team_id = pd.to_numeric(all_stats["TeamID"], errors="coerce").dropna().max()
    else:
        max_existing_team_id = np.nan
    next_team_id = int(max_existing_team_id) + 1 if pd.notna(max_existing_team_id) else 300001
    missing_team_id_mask = pd.to_numeric(all_stats.get("TeamID"), errors="coerce").isna()
    all_stats.loc[missing_team_id_mask, "TeamID"] = np.arange(next_team_id, next_team_id + int(missing_team_id_mask.sum()))
    all_stats["TeamID"] = pd.to_numeric(all_stats["TeamID"], errors="coerce").astype(int)

    ordered_cols = [
        "Season",
        "TeamName",
        "g",
        "wins",
        "losses",
        "win_pct",
        "avg_margin",
        "avg_score_for",
        "avg_score_against",
        "efg",
        "ts",
        "tov_rate",
        "ft_rate",
        "oreb_pct",
        "off_rtg",
        "def_rtg",
        "net_rtg",
        "pace",
        "fg3_rate",
        "ft_pct",
        "ast_rate",
        "stl_rate",
        "blk_rate",
        "dreb_pct",
        "opp_tov_rate",
        "std_margin",
        "avg_opp_win_pct",
        "avg_opp_elo",
        "srs",
        "sos",
        "ProjectionName",
        "median_rank",
        "best_rank",
        "region",
        "seed_num",
        "Seed",
        "entry_text",
        "projection_source_url",
        "projection_date",
        "TeamID",
        "net_rank",
        "srs_rank",
        "efficiency_rank",
        "elo",
        "last10_win_pct",
        "last10_margin",
        "opp_efg",
    ]
    available_cols = [col for col in ordered_cols if col in all_stats.columns]
    return all_stats[available_cols].copy()


def fetch_current_net_rankings() -> pd.DataFrame:
    """Fetch the current official NCAA NET rankings."""
    rows = fetch_plain_table(ncaab_config.CURRENT_NET_URL)
    parsed_rows: list[dict[str, str]] = []
    for row in rows:
        if len(row) < 2:
            continue
        if row[0].isdigit() and row[1] and row[1] != "Team":
            parsed_rows.append({"net_rank": row[0], "TeamName": row[1]})

    net_df = pd.DataFrame(parsed_rows)
    net_df["net_rank"] = pd.to_numeric(net_df["net_rank"], errors="coerce")
    return net_df.dropna(subset=["net_rank"]).reset_index(drop=True)


# ── Official 2026 NCAA Tournament Bracket (Selection Sunday, March 15 2026) ──
# Format: (region, seed_num, teams_list)
# First Four pairs share the same region+seed; both team names are listed.
_OFFICIAL_2026_BRACKET: list[tuple[str, int, list[str]]] = [
    # EAST
    ("East",  1,  ["Duke"]),
    ("East",  2,  ["UConn"]),
    ("East",  3,  ["Michigan St"]),
    ("East",  4,  ["Kansas"]),
    ("East",  5,  ["St John's"]),
    ("East",  6,  ["Louisville"]),
    ("East",  7,  ["UCLA"]),
    ("East",  8,  ["Ohio State"]),
    ("East",  9,  ["TCU"]),
    ("East", 10,  ["UCF"]),
    ("East", 11,  ["South Florida"]),
    ("East", 12,  ["Northern Iowa"]),
    ("East", 13,  ["Cal Baptist"]),
    ("East", 14,  ["N Dakota St"]),
    ("East", 15,  ["Furman"]),
    ("East", 16,  ["Siena"]),
    # WEST
    ("West",  1,  ["Arizona"]),
    ("West",  2,  ["Purdue"]),
    ("West",  3,  ["Gonzaga"]),
    ("West",  4,  ["Arkansas"]),
    ("West",  5,  ["Wisconsin"]),
    ("West",  6,  ["BYU"]),
    ("West",  7,  ["Miami"]),
    ("West",  8,  ["Villanova"]),
    ("West",  9,  ["Utah State"]),
    ("West", 10,  ["Missouri"]),
    ("West", 11,  ["NC State", "Texas"]),  # First Four
    ("West", 12,  ["High Point"]),
    ("West", 13,  ["Hawai'i"]),
    ("West", 14,  ["Kennesaw St"]),
    ("West", 15,  ["Queens"]),
    ("West", 16,  ["Long Island"]),
    # SOUTH
    ("South",  1,  ["Florida"]),
    ("South",  2,  ["Houston"]),
    ("South",  3,  ["Illinois"]),
    ("South",  4,  ["Nebraska"]),
    ("South",  5,  ["Vanderbilt"]),
    ("South",  6,  ["North Carolina"]),
    ("South",  7,  ["Saint Mary's"]),
    ("South",  8,  ["Clemson"]),
    ("South",  9,  ["Iowa"]),
    ("South", 10,  ["Texas A&M"]),
    ("South", 11,  ["VCU"]),
    ("South", 12,  ["McNeese"]),
    ("South", 13,  ["Troy"]),
    ("South", 14,  ["Penn"]),
    ("South", 15,  ["Idaho"]),
    ("South", 16,  ["Lehigh", "Prairie View"]),  # First Four
    # MIDWEST
    ("Midwest",  1,  ["Michigan"]),
    ("Midwest",  2,  ["Iowa State"]),
    ("Midwest",  3,  ["Virginia"]),
    ("Midwest",  4,  ["Alabama"]),
    ("Midwest",  5,  ["Texas Tech"]),
    ("Midwest",  6,  ["Tennessee"]),
    ("Midwest",  7,  ["Kentucky"]),
    ("Midwest",  8,  ["Georgia"]),
    ("Midwest",  9,  ["Saint Louis"]),
    ("Midwest", 10,  ["Santa Clara"]),
    ("Midwest", 11,  ["SMU", "Miami OH"]),  # First Four
    ("Midwest", 12,  ["Akron"]),
    ("Midwest", 13,  ["Hofstra"]),
    ("Midwest", 14,  ["Wright St"]),
    ("Midwest", 15,  ["Tennessee St"]),
    ("Midwest", 16,  ["Howard", "UMBC"]),   # First Four
]
_OFFICIAL_2026_SEMIFINAL_PAIRS: list[tuple[str, str]] = [
    ("East", "Midwest"),
    ("South", "West"),
]


def parse_official_2026_bracket() -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Return the official 2026 NCAA tournament bracket (Selection Sunday)."""
    rows = []
    for region, seed_num, teams in _OFFICIAL_2026_BRACKET:
        entry_text = "/".join(teams)
        rows.append({
            "region": region,
            "seed_num": seed_num,
            "entry_text": entry_text,
            "teams": teams,
            "projection_source_url": "Official 2026 NCAA Tournament Bracket",
            "projection_date": "2026-03-15",
        })
    return pd.DataFrame(rows), _OFFICIAL_2026_SEMIFINAL_PAIRS


def parse_projected_field(url: str = ncaab_config.CURRENT_BRACKETOLOGY_URL) -> tuple[pd.DataFrame, list[tuple[str, str]]]:
    """Parse the latest bracketology article into projected seeds by region."""
    rows = fetch_plain_table(url)
    current_regions = {"left": None, "right": None}
    semifinal_pairs: list[tuple[str, str]] = []
    projected_rows: list[dict[str, object]] = []
    valid_regions = {"East", "West", "South", "Midwest"}

    for row in rows:
        cells = row + [""] * (3 - len(row))
        left, _, right = cells[:3]

        for side, text in (("left", left), ("right", right)):
            region_match = re.search(r"\(([^)]+)\)", text)
            if region_match:
                candidate_region = region_match.group(1).title()
                if candidate_region in valid_regions and not re.match(r"^\s*\d+\)", text):
                    current_regions[side] = candidate_region

        if current_regions["left"] and current_regions["right"]:
            pair = (current_regions["left"], current_regions["right"])
            if pair not in semifinal_pairs:
                semifinal_pairs.append(pair)

        for side, text in (("left", left), ("right", right)):
            if not current_regions[side]:
                continue
            match = re.match(r"^\s*(\d+)\)\s*(.+?)\s*$", text)
            if not match:
                continue

            seed_num = int(match.group(1))
            team_text = match.group(2).replace("*", "").strip()
            teams = [piece.strip() for piece in team_text.split("/") if piece.strip()]
            projected_rows.append(
                {
                    "region": current_regions[side],
                    "seed_num": seed_num,
                    "entry_text": team_text,
                    "teams": teams,
                }
            )

    projected_field = pd.DataFrame(projected_rows)
    projected_field["projection_source_url"] = url
    projected_field["projection_date"] = ncaab_config.CURRENT_PROJECTION_DATE
    return projected_field, semifinal_pairs


def build_current_projected_field() -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Build current projected team features and bracket entries."""
    current_stats = fetch_current_team_stats()
    net_rankings = fetch_current_net_rankings()
    # Use the official bracket if available, otherwise fall back to bracketology scrape
    if _OFFICIAL_2026_BRACKET:
        projected_field, semifinal_pairs = parse_official_2026_bracket()
    else:
        projected_field, semifinal_pairs = parse_projected_field()
    rank_features = build_current_rank_features(current_stats)

    stats_candidates = current_stats["TeamName"].tolist()
    net_candidates = net_rankings["TeamName"].tolist()
    projected_matches: list[dict[str, object]] = []
    for projected in projected_field.itertuples(index=False):
        for team_name in projected.teams:
            matched_name = best_name_match(team_name, stats_candidates)
            matched_net_name = best_name_match(team_name, net_candidates)
            net_rank = float(
                net_rankings.loc[net_rankings["TeamName"] == matched_net_name, "net_rank"].iloc[0]
            )
            projected_matches.append(
                {
                    "ProjectionName": team_name,
                    "matched_team_name": matched_name,
                    "matched_net_name": matched_net_name,
                    "net_rank": net_rank,
                    "region": projected.region,
                    "seed_num": projected.seed_num,
                    "entry_text": projected.entry_text,
                    "projection_source_url": projected.projection_source_url,
                    "projection_date": projected.projection_date,
                }
            )

    match_df = pd.DataFrame(projected_matches)
    live_team_features = build_current_projected_team_features(match_df["matched_team_name"].dropna().unique().tolist(), current_stats)
    current_stats = current_stats.merge(rank_features, on="TeamName", how="left")
    current_stats = current_stats.merge(live_team_features, on="TeamName", how="left", suffixes=("", "_live"))

    matched_rows: list[dict[str, object]] = []
    for projected in match_df.itertuples(index=False):
        team_row = current_stats[current_stats["TeamName"] == projected.matched_team_name].iloc[0].to_dict()
        rank_components = [
            projected.net_rank,
            team_row.get("srs_rank"),
            team_row.get("efficiency_rank"),
        ]
        valid_ranks = [float(value) for value in rank_components if pd.notna(value)]
        matched_rows.append(
            {
                **team_row,
                "ProjectionName": projected.ProjectionName,
                "net_rank": projected.net_rank,
                "median_rank": float(np.median(valid_ranks)) if valid_ranks else np.nan,
                "best_rank": float(np.min(valid_ranks)) if valid_ranks else np.nan,
                "region": projected.region,
                "seed_num": projected.seed_num,
                "Seed": f"{projected.region[:1].upper()}{projected.seed_num:02d}",
                "entry_text": projected.entry_text,
                "projection_source_url": projected.projection_source_url,
                "projection_date": projected.projection_date,
            }
        )

    projected_team_features = pd.DataFrame(matched_rows).drop_duplicates(
        subset=["ProjectionName", "region", "seed_num"]
    ).reset_index(drop=True)
    projected_team_features["elo"] = projected_team_features["elo"].fillna(
        1500.0 + 12.0 * pd.to_numeric(projected_team_features["net_rtg"], errors="coerce")
    )
    projected_team_features["last10_win_pct"] = projected_team_features["last10_win_pct"].fillna(
        projected_team_features["win_pct"]
    )
    projected_team_features["last10_margin"] = projected_team_features["last10_margin"].fillna(
        projected_team_features["avg_margin"]
    )
    projected_team_features["opp_efg"] = projected_team_features["opp_efg"].fillna(
        float(pd.to_numeric(current_stats["efg"], errors="coerce").median())
    )
    projected_team_features["TeamID"] = np.arange(200001, 200001 + len(projected_team_features))
    projected_team_features["TeamName"] = projected_team_features["ProjectionName"]

    meta = {
        "projection_source_url": ncaab_config.CURRENT_BRACKETOLOGY_URL,
        "projection_date": ncaab_config.CURRENT_PROJECTION_DATE,
        "net_source_url": ncaab_config.CURRENT_NET_URL,
        "stats_basic_url": ncaab_config.CURRENT_SPORTSREF_BASIC_URL,
        "stats_advanced_url": ncaab_config.CURRENT_SPORTSREF_ADVANCED_URL,
        "semifinal_pairs": semifinal_pairs,
        "updated_at_utc": datetime.now(timezone.utc).isoformat(),
    }
    return projected_team_features, projected_field, meta


def _compute_game_probabilities(
    projected_team_features: pd.DataFrame,
    model_bundle: tuple,
    seed_baselines: pd.DataFrame | None,
) -> dict[tuple[int, int], float]:
    """Pre-compute win probabilities for all possible matchups between seeded teams.

    Returns a dict mapping (team_a_id, team_b_id) → team_a_win_prob.
    """
    prob_cache: dict[tuple[int, int], float] = {}
    team_ids = sorted(projected_team_features["TeamID"].unique().tolist())
    team_features = projected_team_features.copy()

    for i, team_a_id in enumerate(team_ids):
        for team_b_id in team_ids[i + 1:]:
            try:
                prediction = predict_matchup(
                    ncaab_config.CURRENT_SEASON,
                    int(team_a_id),
                    int(team_b_id),
                    team_features=team_features,
                    model_bundle=model_bundle,
                    seed_baselines=seed_baselines,
                )
                adjusted = apply_ncaab_availability_adjustments(
                    pd.DataFrame([{
                        "team_a_name": prediction["team_a_name"],
                        "team_b_name": prediction["team_b_name"],
                        "team_a_win_prob": prediction["team_a_win_prob"],
                        "team_b_win_prob": prediction["team_b_win_prob"],
                        "team_a_win_prob_model": prediction.get("team_a_win_prob_model", prediction["team_a_win_prob"]),
                        "team_b_win_prob_model": prediction.get("team_b_win_prob_model", prediction["team_b_win_prob"]),
                    }]),
                    team_a_col="team_a_name", team_b_col="team_b_name",
                    prob_a_col="team_a_win_prob", prob_b_col="team_b_win_prob",
                    prefix_a="team_a", prefix_b="team_b",
                ).iloc[0]
                prob_cache[(int(team_a_id), int(team_b_id))] = float(adjusted["team_a_win_prob"])
                prob_cache[(int(team_b_id), int(team_a_id))] = 1.0 - float(adjusted["team_a_win_prob"])
            except Exception:
                prob_cache[(int(team_a_id), int(team_b_id))] = 0.5
                prob_cache[(int(team_b_id), int(team_a_id))] = 0.5
    return prob_cache


def _get_prob(prob_cache: dict[tuple[int, int], float], a: int, b: int) -> float:
    key = (int(a), int(b))
    if key in prob_cache:
        return prob_cache[key]
    # Compute on the fly if not cached.
    return 0.5


def simulate_bracket_monte_carlo(
    projected_team_features: pd.DataFrame,
    meta: dict,
    n_sims: int = 10000,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run Monte Carlo bracket simulations and return per-team advancement
    probabilities plus the optimal bracket picks.

    Returns
    -------
    advancement_df : DataFrame
        Columns: TeamID, TeamName, seed_num, region, plus one column per round
        giving the fraction of simulations in which the team advanced.
    optimal_bracket_df : DataFrame
        Same format as ``simulate_projected_bracket`` output, but with upset-
        aware picks chosen to maximise expected bracket-pool points.
    """
    from src.ncaab_model import load_model

    rng = np.random.default_rng(42)
    semifinal_pairs = meta.get("semifinal_pairs") or [("East", "Midwest"), ("South", "West")]
    model_bundle = load_model()
    seed_baselines = load_seed_matchup_baselines()

    logger.info("Pre-computing pairwise probabilities for Monte Carlo bracket ...")
    prob_cache = _compute_game_probabilities(projected_team_features, model_bundle, seed_baselines)

    # Build region bracket structure.
    regions = sorted(projected_team_features["region"].dropna().unique())
    region_seeds: dict[str, dict[int, list[int]]] = {}
    for region in regions:
        rdf = projected_team_features[projected_team_features["region"] == region]
        region_seeds[region] = {
            int(seed): group.sort_values("TeamName")["TeamID"].tolist()
            for seed, group in rdf.groupby("seed_num")
        }

    team_name_map = dict(zip(
        projected_team_features["TeamID"].astype(int),
        projected_team_features["TeamName"],
    ))
    team_seed_map = dict(zip(
        projected_team_features["TeamID"].astype(int),
        projected_team_features["seed_num"].astype(int),
    ))
    team_region_map = dict(zip(
        projected_team_features["TeamID"].astype(int),
        projected_team_features["region"],
    ))

    ROUND_NAMES = ["Round of 64", "Round of 32", "Sweet 16", "Elite 8", "Final Four", "Championship"]
    ROUND_POINTS = [1, 2, 4, 8, 16, 32]

    # Track advancement counts per team per round.
    advance_counts: dict[int, dict[str, int]] = {}
    for tid in projected_team_features["TeamID"].astype(int).tolist():
        advance_counts[tid] = {r: 0 for r in ROUND_NAMES}

    # Track how often each team wins each specific game slot (for optimal picks).
    # game_slot_key → {team_id: count}
    game_slot_wins: dict[str, dict[int, int]] = {}

    def _sim_game(a: int, b: int) -> int:
        p = _get_prob(prob_cache, a, b)
        return a if rng.random() < p else b

    logger.info("Running %d Monte Carlo bracket simulations ...", n_sims)
    for _ in range(n_sims):
        region_champs: dict[str, int] = {}
        for region in regions:
            seeds = region_seeds[region]
            # First Four.
            advanced: dict[int, int] = {}
            for seed_num, team_ids in seeds.items():
                if len(team_ids) == 1:
                    advanced[seed_num] = team_ids[0]
                else:
                    winner = _sim_game(team_ids[0], team_ids[1])
                    slot_key = f"FF|{region}|{seed_num}"
                    game_slot_wins.setdefault(slot_key, {})
                    game_slot_wins[slot_key][winner] = game_slot_wins[slot_key].get(winner, 0) + 1
                    advanced[seed_num] = winner

            # Round of 64.
            r64: list[int] = []
            for idx, (sa, sb) in enumerate(ROUND_ONE_PAIRINGS):
                winner = _sim_game(advanced[sa], advanced[sb])
                advance_counts[winner]["Round of 64"] += 1
                slot_key = f"R64|{region}|{idx}"
                game_slot_wins.setdefault(slot_key, {})
                game_slot_wins[slot_key][winner] = game_slot_wins[slot_key].get(winner, 0) + 1
                r64.append(winner)

            # Round of 32.
            r32: list[int] = []
            for idx, (a, b) in enumerate(zip(r64[::2], r64[1::2])):
                winner = _sim_game(a, b)
                advance_counts[winner]["Round of 32"] += 1
                slot_key = f"R32|{region}|{idx}"
                game_slot_wins.setdefault(slot_key, {})
                game_slot_wins[slot_key][winner] = game_slot_wins[slot_key].get(winner, 0) + 1
                r32.append(winner)

            # Sweet 16.
            s16: list[int] = []
            for idx, (a, b) in enumerate(zip(r32[::2], r32[1::2])):
                winner = _sim_game(a, b)
                advance_counts[winner]["Sweet 16"] += 1
                slot_key = f"S16|{region}|{idx}"
                game_slot_wins.setdefault(slot_key, {})
                game_slot_wins[slot_key][winner] = game_slot_wins[slot_key].get(winner, 0) + 1
                s16.append(winner)

            # Elite 8.
            winner = _sim_game(s16[0], s16[1])
            advance_counts[winner]["Elite 8"] += 1
            slot_key = f"E8|{region}"
            game_slot_wins.setdefault(slot_key, {})
            game_slot_wins[slot_key][winner] = game_slot_wins[slot_key].get(winner, 0) + 1
            region_champs[region] = winner

        # Final Four.
        finalists: list[int] = []
        for idx, (ra, rb) in enumerate(semifinal_pairs[:2]):
            if ra in region_champs and rb in region_champs:
                winner = _sim_game(region_champs[ra], region_champs[rb])
                advance_counts[winner]["Final Four"] += 1
                slot_key = f"FF4|{idx}"
                game_slot_wins.setdefault(slot_key, {})
                game_slot_wins[slot_key][winner] = game_slot_wins[slot_key].get(winner, 0) + 1
                finalists.append(winner)

        # Championship.
        if len(finalists) == 2:
            winner = _sim_game(finalists[0], finalists[1])
            advance_counts[winner]["Championship"] += 1
            slot_key = "CHAMP"
            game_slot_wins.setdefault(slot_key, {})
            game_slot_wins[slot_key][winner] = game_slot_wins[slot_key].get(winner, 0) + 1

    # Build advancement probability DataFrame.
    adv_rows: list[dict] = []
    for tid, counts in advance_counts.items():
        row: dict = {
            "TeamID": tid,
            "TeamName": team_name_map.get(tid, "?"),
            "seed_num": team_seed_map.get(tid, 16),
            "region": team_region_map.get(tid, ""),
        }
        for rnd in ROUND_NAMES:
            row[rnd] = counts[rnd] / n_sims
        adv_rows.append(row)
    advancement_df = pd.DataFrame(adv_rows).sort_values(
        ["Championship", "Final Four", "Elite 8"], ascending=False
    ).reset_index(drop=True)

    # ── Build optimal bracket (maximise expected pool points) ──
    # For each game slot, pick the team with the highest expected value:
    #   EV = P(team wins this slot) × points_for_this_round
    # This naturally picks upsets when a team has enough win probability
    # in that slot to justify the risk.
    picks: list[dict[str, object]] = []

    def _optimal_pick_game(
        team_a_id: int,
        team_b_id: int,
        round_name: str,
        region: str,
        slot_key: str,
    ) -> int:
        slot_data = game_slot_wins.get(slot_key, {})
        a_count = slot_data.get(team_a_id, 0)
        b_count = slot_data.get(team_b_id, 0)
        # Pick the team that wins this game slot more often in simulations.
        winner_id = team_a_id if a_count >= b_count else team_b_id
        loser_id = team_b_id if winner_id == team_a_id else team_a_id
        win_frac = max(a_count, b_count) / max(a_count + b_count, 1)
        prob_a = _get_prob(prob_cache, team_a_id, team_b_id)
        is_upset = team_seed_map.get(winner_id, 16) > team_seed_map.get(loser_id, 16)
        picks.append({
            "round": round_name,
            "region": region,
            "team_a_id": team_a_id,
            "team_b_id": team_b_id,
            "team_a_name": team_name_map.get(team_a_id, "?"),
            "team_b_name": team_name_map.get(team_b_id, "?"),
            "winner_id": winner_id,
            "winner_name": team_name_map.get(winner_id, "?"),
            "win_prob": prob_a if winner_id == team_a_id else 1.0 - prob_a,
            "sim_win_pct": win_frac,
            "is_upset": is_upset,
            "winner_seed": team_seed_map.get(winner_id, 16),
            "loser_seed": team_seed_map.get(loser_id, 16),
            "seed_baseline_prob": 0.5,
            "winner_seed_edge": 0.0,
            "team_a_availability_penalty_elo": 0.0,
            "team_b_availability_penalty_elo": 0.0,
        })
        return winner_id

    region_champions_opt: dict[str, int] = {}
    for region in regions:
        seeds = region_seeds[region]
        advanced: dict[int, int] = {}
        for seed_num, team_ids in seeds.items():
            if len(team_ids) == 1:
                advanced[seed_num] = team_ids[0]
            else:
                slot_key = f"FF|{region}|{seed_num}"
                advanced[seed_num] = _optimal_pick_game(
                    team_ids[0], team_ids[1], "First Four", region, slot_key,
                )

        r64: list[int] = []
        for idx, (sa, sb) in enumerate(ROUND_ONE_PAIRINGS):
            slot_key = f"R64|{region}|{idx}"
            r64.append(_optimal_pick_game(advanced[sa], advanced[sb], "Round of 64", region, slot_key))

        r32: list[int] = []
        for idx, (a, b) in enumerate(zip(r64[::2], r64[1::2])):
            slot_key = f"R32|{region}|{idx}"
            r32.append(_optimal_pick_game(a, b, "Round of 32", region, slot_key))

        s16: list[int] = []
        for idx, (a, b) in enumerate(zip(r32[::2], r32[1::2])):
            slot_key = f"S16|{region}|{idx}"
            s16.append(_optimal_pick_game(a, b, "Sweet 16", region, slot_key))

        slot_key = f"E8|{region}"
        region_champions_opt[region] = _optimal_pick_game(s16[0], s16[1], "Elite 8", region, slot_key)

    finalists_opt: list[int] = []
    for idx, (ra, rb) in enumerate(semifinal_pairs[:2]):
        if ra in region_champions_opt and rb in region_champions_opt:
            slot_key = f"FF4|{idx}"
            finalists_opt.append(_optimal_pick_game(
                region_champions_opt[ra], region_champions_opt[rb],
                "Final Four", f"{ra} vs {rb}", slot_key,
            ))

    if len(finalists_opt) == 2:
        _optimal_pick_game(finalists_opt[0], finalists_opt[1], "National Championship", "Title Game", "CHAMP")

    optimal_bracket_df = pd.DataFrame(picks)
    optimal_bracket_df["projection_date"] = meta.get("projection_date", "")
    optimal_bracket_df["projection_source_url"] = meta.get("projection_source_url", "")

    n_upsets = int(optimal_bracket_df.get("is_upset", pd.Series(dtype=bool)).sum())
    logger.info(
        "Monte Carlo bracket complete: %d upsets picked across %d games",
        n_upsets, len(optimal_bracket_df),
    )

    return advancement_df, optimal_bracket_df


def simulate_projected_bracket(
    projected_team_features: pd.DataFrame,
    meta: dict,
) -> pd.DataFrame:
    """Simulate the projected bracket, including play-in games, from current features.

    This runs Monte Carlo simulations to produce an upset-aware bracket.
    Falls back to deterministic (always-favorite) if Monte Carlo fails.
    """
    try:
        advancement_df, bracket_df = simulate_bracket_monte_carlo(
            projected_team_features, meta,
        )
        # Save advancement probabilities alongside the bracket.
        adv_path = ncaab_config.NCAAB_PROCESSED_DIR / "advancement_probabilities.csv"
        advancement_df.to_csv(adv_path, index=False)
        logger.info("Saved advancement probabilities to %s", adv_path)
        return bracket_df
    except Exception as exc:
        logger.warning("Monte Carlo bracket failed (%s), falling back to deterministic", exc)

    # ── Deterministic fallback ──
    semifinal_pairs = meta.get("semifinal_pairs") or [("East", "Midwest"), ("South", "West")]
    picks: list[dict[str, object]] = []

    team_features = projected_team_features.copy()
    model_bundle = None
    seed_baselines = None

    def simulate_game(team_a_id: int, team_b_id: int, round_name: str, region: str) -> int:
        nonlocal model_bundle
        prediction = predict_matchup(
            ncaab_config.CURRENT_SEASON,
            team_a_id,
            team_b_id,
            team_features=team_features,
            model_bundle=model_bundle,
            seed_baselines=seed_baselines,
        )
        adjusted = apply_ncaab_availability_adjustments(
            pd.DataFrame(
                [
                    {
                        "team_a_name": prediction["team_a_name"],
                        "team_b_name": prediction["team_b_name"],
                        "team_a_win_prob": prediction["team_a_win_prob"],
                        "team_b_win_prob": prediction["team_b_win_prob"],
                        "team_a_win_prob_model": prediction.get("team_a_win_prob_model", prediction["team_a_win_prob"]),
                        "team_b_win_prob_model": prediction.get("team_b_win_prob_model", prediction["team_b_win_prob"]),
                    }
                ]
            ),
            team_a_col="team_a_name",
            team_b_col="team_b_name",
            prob_a_col="team_a_win_prob",
            prob_b_col="team_b_win_prob",
            prefix_a="team_a",
            prefix_b="team_b",
        ).iloc[0]
        team_a_prob = float(adjusted["team_a_win_prob"])
        winner_id = team_a_id if team_a_prob >= 0.5 else team_b_id
        picks.append(
            {
                "round": round_name,
                "region": region,
                "team_a_id": team_a_id,
                "team_b_id": team_b_id,
                "team_a_name": prediction["team_a_name"],
                "team_b_name": prediction["team_b_name"],
                "winner_id": winner_id,
                "winner_name": prediction["team_a_name"] if winner_id == team_a_id else prediction["team_b_name"],
                "win_prob": team_a_prob if winner_id == team_a_id else float(adjusted["team_b_win_prob"]),
                "seed_baseline_prob": prediction["seed_baseline_prob"],
                "winner_seed_edge": prediction["team_a_seed_edge"] if winner_id == team_a_id else prediction["team_b_seed_edge"],
                "team_a_availability_penalty_elo": float(adjusted.get("team_a_availability_penalty_elo", 0.0)),
                "team_b_availability_penalty_elo": float(adjusted.get("team_b_availability_penalty_elo", 0.0)),
            }
        )
        return winner_id

    from src.ncaab_model import load_model

    model_bundle = load_model()
    seed_baselines = load_seed_matchup_baselines()

    region_champions: dict[str, int] = {}
    for region in sorted(projected_team_features["region"].dropna().unique()):
        region_df = projected_team_features[projected_team_features["region"] == region].copy()
        seed_entries = {
            int(seed): group.sort_values("TeamName")["TeamID"].tolist()
            for seed, group in region_df.groupby("seed_num")
        }

        advanced_entries: dict[int, int] = {}
        for seed_num, team_ids in seed_entries.items():
            if len(team_ids) == 1:
                advanced_entries[seed_num] = team_ids[0]
            else:
                advanced_entries[seed_num] = simulate_game(team_ids[0], team_ids[1], "First Four", region)

        round64: list[int] = []
        for seed_a, seed_b in ROUND_ONE_PAIRINGS:
            round64.append(simulate_game(advanced_entries[seed_a], advanced_entries[seed_b], "Round of 64", region))

        round32: list[int] = []
        for team_a_id, team_b_id in zip(round64[::2], round64[1::2]):
            round32.append(simulate_game(team_a_id, team_b_id, "Round of 32", region))

        sweet16: list[int] = []
        for team_a_id, team_b_id in zip(round32[::2], round32[1::2]):
            sweet16.append(simulate_game(team_a_id, team_b_id, "Sweet 16", region))

        region_champion = simulate_game(sweet16[0], sweet16[1], "Elite 8", region)
        region_champions[region] = region_champion

    finalists: list[int] = []
    for region_a, region_b in semifinal_pairs[:2]:
        if region_a in region_champions and region_b in region_champions:
            finalists.append(simulate_game(region_champions[region_a], region_champions[region_b], "Final Four", f"{region_a} vs {region_b}"))

    if len(finalists) == 2:
        simulate_game(finalists[0], finalists[1], "National Championship", "Title Game")

    bracket_df = pd.DataFrame(picks)
    bracket_df["projection_date"] = meta["projection_date"]
    bracket_df["projection_source_url"] = meta["projection_source_url"]
    return bracket_df


def write_current_projection_artifacts() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Fetch current data and write projected team, all-team, and bracket artifacts to disk."""
    team_features, projected_field, meta = build_current_projected_field()
    current_stats = fetch_current_team_stats()
    net_rankings = fetch_current_net_rankings()
    all_team_features = build_current_all_team_features(current_stats, net_rankings, team_features)
    bracket_df = simulate_projected_bracket(team_features, meta)

    ncaab_config.NCAAB_PROCESSED_DIR.mkdir(parents=True, exist_ok=True)
    team_features.to_csv(ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV, index=False)
    all_team_features.to_csv(ncaab_config.NCAAB_CURRENT_ALL_TEAM_FEATURES_CSV, index=False)
    projected_field.to_csv(ncaab_config.NCAAB_CURRENT_PROJECTED_FIELD_CSV, index=False)
    bracket_df.to_csv(ncaab_config.NCAAB_CURRENT_PROJECTED_BRACKET_CSV, index=False)
    ncaab_config.NCAAB_CURRENT_META_JSON.write_text(json.dumps(meta, indent=2))

    logger.info("Saved current NCAA projected team features to %s", ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV)
    logger.info("Saved current NCAA all-team features to %s", ncaab_config.NCAAB_CURRENT_ALL_TEAM_FEATURES_CSV)
    logger.info("Saved current NCAA projected bracket to %s", ncaab_config.NCAAB_CURRENT_PROJECTED_BRACKET_CSV)
    return team_features, bracket_df
