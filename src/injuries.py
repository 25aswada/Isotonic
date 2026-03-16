"""
injuries.py - Live availability adjustments from the official NBA injury report.
"""

from __future__ import annotations

import io
import logging
import re
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd
import requests
from nba_api.stats.endpoints import LeagueDashPlayerStats
from nba_api.stats.static import teams as nba_teams_static
from pypdf import PdfReader

import config
from src.monitoring import emit_alert
from src.player_availability import _espn_injuries_to_adjustments, fetch_all_espn_injuries

logger = logging.getLogger(__name__)

TEAM_ADJUSTMENT_COLUMNS = [
    "team",
    "availability_penalty_elo",
    "availability_summary",
    "out_count",
    "questionable_count",
    "doubtful_count",
    "probable_count",
    "report_timestamp",
]

STATUS_PATTERN = "(Available|Probable|Questionable|Doubtful|Out)"
NAME_PATTERN = r"[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)*,\s*[A-Z][A-Za-z'.-]+(?:\s+[A-Z][A-Za-z'.-]+)*"
STATUS_VALUES = {"Available", "Probable", "Questionable", "Doubtful", "Out"}
TEAM_NAME_OVERRIDES = {
    "LAC": ["LA Clippers", "Los Angeles Clippers"],
    "LAL": ["Los Angeles Lakers", "LA Lakers"],
    "NOP": ["New Orleans Pelicans"],
    "NYK": ["New York Knicks"],
    "PHX": ["Phoenix Suns"],
    "GSW": ["Golden State Warriors"],
}
INJURY_NAME_NOISE = {
    "abdominal",
    "ankle",
    "assignment",
    "back",
    "calf",
    "core",
    "dislocation",
    "elbow",
    "eye",
    "finger",
    "foot",
    "fracture",
    "g",
    "hand",
    "high",
    "hip",
    "illness",
    "impingement",
    "index",
    "injury",
    "knee",
    "lateral",
    "league",
    "left",
    "low",
    "management",
    "muscle",
    "n/a",
    "nose",
    "oblique",
    "on",
    "pelvic",
    "quadricep",
    "recovery",
    "retinal",
    "right",
    "small",
    "soreness",
    "sprain",
    "strain",
    "surgery",
    "suspension",
    "tendon",
    "tendonitis",
    "thumb",
    "toe",
    "two",
    "way",
    "wrist",
}


def _browser_headers(accept: str) -> dict[str, str]:
    return {
        "User-Agent": (
            "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        ),
        "Accept": accept,
        "Accept-Language": "en-US,en;q=0.9",
    }


def _current_season() -> str:
    return config.SEASONS[-1]


def _name_key(name: str) -> str:
    return re.sub(r"[^a-z0-9]", "", (name or "").lower())


def _name_tokens(name: str) -> set[str]:
    tokens = {
        token
        for token in re.findall(r"[A-Za-z0-9']+", (name or "").lower())
        if token and token not in INJURY_NAME_NOISE
    }
    return tokens


def _team_name_map() -> tuple[dict[str, str], dict[str, list[str]]]:
    abbr_to_name: dict[str, str] = {}
    abbr_to_candidates: dict[str, list[str]] = {}
    for team in nba_teams_static.get_teams():
        abbr = team["abbreviation"]
        full_name = team["full_name"]
        abbr_to_name[abbr] = full_name
        candidates = [full_name]
        if abbr in TEAM_NAME_OVERRIDES:
            candidates = TEAM_NAME_OVERRIDES[abbr] + candidates
        abbr_to_candidates[abbr] = list(dict.fromkeys(candidates))
    return abbr_to_name, abbr_to_candidates


def _parse_report_timestamp_from_url(url: str) -> pd.Timestamp | None:
    match = re.search(r"Injury-Report_(\d{4}-\d{2}-\d{2})_(\d{2})_(\d{2})(AM|PM)\.pdf", url)
    if not match:
        return None

    report_date, hour, minute, meridiem = match.groups()
    stamp = pd.Timestamp(f"{report_date} {hour}:{minute} {meridiem}", tz="America/New_York")
    return stamp


def _extract_report_links(html: str) -> list[tuple[pd.Timestamp, str]]:
    links = re.findall(
        r'https://ak-static\.cms\.nba\.com/referee/injury/Injury-Report_\d{4}-\d{2}-\d{2}_\d{2}_\d{2}(?:AM|PM)\.pdf',
        html,
    )

    parsed_links: list[tuple[pd.Timestamp, str]] = []
    for link in links:
        report_ts = _parse_report_timestamp_from_url(link)
        if report_ts is not None:
            parsed_links.append((report_ts, link))

    parsed_links.sort(key=lambda item: item[0])
    return parsed_links


def _choose_report_link(
    links: list[tuple[pd.Timestamp, str]],
    target_date: pd.Timestamp,
    now_et: pd.Timestamp,
) -> tuple[pd.Timestamp, str] | None:
    if not links:
        return None

    target_day = target_date.normalize()
    same_day_links = [item for item in links if item[0].normalize() == target_day]
    eligible = [item for item in same_day_links if item[0] <= now_et]
    if eligible:
        return eligible[-1]
    if same_day_links:
        return same_day_links[0]

    fallback = [item for item in links if item[0] <= now_et]
    if fallback:
        return fallback[-1]
    return links[0]


def _fetch_report_pdf(report_date: pd.Timestamp) -> tuple[pd.Timestamp, str, bytes]:
    session = requests.Session()
    page_headers = _browser_headers("text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8")
    page_resp = session.get(config.OFFICIAL_NBA_INJURY_REPORT_URL, headers=page_headers, timeout=20)
    page_resp.raise_for_status()

    links = _extract_report_links(page_resp.text)
    now_et = pd.Timestamp.now(tz="America/New_York")
    chosen = _choose_report_link(links, report_date, now_et)
    if chosen is None:
        raise ValueError(f"No injury report links found for {report_date.date()}")

    report_ts, report_url = chosen
    pdf_headers = _browser_headers("application/pdf,*/*")
    pdf_headers["Referer"] = config.OFFICIAL_NBA_INJURY_REPORT_URL
    pdf_resp = session.get(report_url, headers=pdf_headers, timeout=20)
    pdf_resp.raise_for_status()
    return report_ts, report_url, pdf_resp.content


def _pdf_text(pdf_bytes: bytes) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    return "\n".join(page.extract_text() or "" for page in reader.pages)


def _normalize_report_text(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _report_lines(text: str) -> list[str]:
    return [line.strip() for line in text.splitlines() if line.strip()]


def _team_segment(text: str, team_names: Iterable[str]) -> tuple[int, str] | None:
    found = []
    for name in team_names:
        idx = text.find(name)
        if idx >= 0:
            found.append((idx, name))
    if not found:
        return None
    return min(found, key=lambda item: item[0])


def _match_team_name(lines: list[str], candidates: Iterable[str]) -> tuple[int, int, str] | None:
    for idx in range(len(lines)):
        for candidate in candidates:
            tokens = candidate.split()
            if lines[idx:idx + len(tokens)] == tokens:
                return idx, idx + len(tokens), candidate
    return None


def _looks_like_name_token(token: str) -> bool:
    if not token or token in STATUS_VALUES:
        return False
    if any(ch.isdigit() for ch in token):
        return False
    normalized = token.replace(",", "").replace(".", "").replace("'", "").replace("-", "")
    if normalized.lower() in INJURY_NAME_NOISE:
        return False
    return bool(normalized) and normalized[0].isupper()


def _player_name_block(tokens: list[str]) -> tuple[str, str] | None:
    if not tokens or not any("," in token for token in tokens):
        return None

    comma_idx = max(i for i, token in enumerate(tokens) if "," in token)
    last_tokens = tokens[:comma_idx + 1]
    first_tokens = tokens[comma_idx + 1:]
    if not (1 <= len(last_tokens) <= 3 and 1 <= len(first_tokens) <= 3):
        return None
    if not all(_looks_like_name_token(token) for token in last_tokens + first_tokens):
        return None

    last_name = " ".join(last_tokens).replace(" ,", ",").rstrip(",").strip()
    first_name = " ".join(first_tokens).strip()
    player_name = f"{first_name} {last_name}".strip()
    player_report = f"{last_name}, {first_name}".strip()
    return player_name, player_report


def _player_start_metadata(lines: list[str], start_idx: int) -> tuple[int, int, str, str] | None:
    max_stop = min(len(lines), start_idx + 8)
    for status_idx in range(start_idx + 1, max_stop):
        status = lines[status_idx]
        if status not in STATUS_VALUES:
            continue
        parsed_name = _player_name_block(lines[start_idx:status_idx])
        if parsed_name is not None:
            player_name, player_report = parsed_name
            return status_idx, status_idx + 1, player_name, player_report
    return None


def _is_section_break(line: str) -> bool:
    return bool(
        re.fullmatch(r"\d{2}:\d{2}", line)
        or line == "(ET)"
        or re.fullmatch(r"[A-Z]{2,3}@[A-Z]{2,3}", line)
        or line in {"Injury", "Report:", "Page", "Game", "Date", "Time", "Matchup", "Team", "Player", "Name", "Current", "Status", "Reason", "of"}
    )


def _parse_team_players_lines(team_lines: list[str], team_abbr: str, team_name: str, matchup: str) -> list[dict]:
    if not team_lines:
        return []

    if "NOT YET SUBMITTED" in team_lines:
        return [{
            "matchup": matchup,
            "team": team_abbr,
            "team_name": team_name,
            "player_name": np.nan,
            "player_name_report": np.nan,
            "status": "not submitted",
            "reason": "NOT YET SUBMITTED",
        }]

    rows: list[dict] = []
    idx = 0
    while idx < len(team_lines):
        meta = _player_start_metadata(team_lines, idx)
        if meta is None:
            idx += 1
            continue

        status_idx, next_idx, player_name, player_report = meta
        reason_end = next_idx
        while reason_end < len(team_lines):
            if _is_section_break(team_lines[reason_end]) or _player_start_metadata(team_lines, reason_end) is not None:
                break
            reason_end += 1

        rows.append({
            "matchup": matchup,
            "team": team_abbr,
            "team_name": team_name,
            "player_name": player_name,
            "player_name_report": player_report,
            "status": team_lines[status_idx].lower(),
            "reason": " ".join(team_lines[next_idx:reason_end]).strip(" -"),
        })
        idx = max(reason_end, next_idx)

    return rows


def _game_timestamp_from_lines(lines: list[str], matchup_idx: int) -> pd.Timestamp | None:
    game_date_str = None
    game_time_str = None
    for idx in range(matchup_idx - 1, max(matchup_idx - 6, -1), -1):
        token = lines[idx]
        if game_time_str is None and re.fullmatch(r"\d{2}:\d{2}", token):
            game_time_str = token
        if game_date_str is None and re.fullmatch(r"\d{2}/\d{2}/\d{4}", token):
            game_date_str = token
        if game_date_str and game_time_str:
            break

    if game_date_str and game_time_str:
        return pd.Timestamp(f"{game_date_str} {game_time_str}", tz="America/New_York")
    return None


def _parse_team_players(team_text: str, team_abbr: str, team_name: str, matchup: str) -> list[dict]:
    if "NOT YET SUBMITTED" in team_text:
        return [{
            "matchup": matchup,
            "team": team_abbr,
            "team_name": team_name,
            "player_name": np.nan,
            "player_name_report": np.nan,
            "status": "not submitted",
            "reason": "NOT YET SUBMITTED",
        }]

    rows: list[dict] = []
    pattern = re.compile(
        rf"(?P<player>{NAME_PATTERN})\s+(?P<status>{STATUS_PATTERN})\s+(?P<reason>.*?)(?=(?:{NAME_PATTERN}\s+{STATUS_PATTERN})|$)"
    )
    for match in pattern.finditer(team_text):
        player_report = match.group("player").strip()
        last_name, first_name = [part.strip() for part in player_report.split(",", 1)]
        player_name = f"{first_name} {last_name}".strip()
        rows.append({
            "matchup": matchup,
            "team": team_abbr,
            "team_name": team_name,
            "player_name": player_name,
            "player_name_report": player_report,
            "status": match.group("status").lower(),
            "reason": match.group("reason").strip(" -"),
        })
    return rows


def _parse_injury_report_text(text: str) -> pd.DataFrame:
    lines = _report_lines(text)
    matchup_indices = [idx for idx, line in enumerate(lines) if re.fullmatch(r"[A-Z]{2,3}@[A-Z]{2,3}", line)]
    if not matchup_indices:
        return pd.DataFrame()

    abbr_to_name, abbr_to_candidates = _team_name_map()
    rows: list[dict] = []

    for pos, matchup_idx in enumerate(matchup_indices):
        matchup = lines[matchup_idx]
        segment_end = matchup_indices[pos + 1] if pos + 1 < len(matchup_indices) else len(lines)
        segment = lines[matchup_idx + 1:segment_end]
        away_abbr, home_abbr = matchup.split("@")

        away_span = _match_team_name(segment, abbr_to_candidates.get(away_abbr, [abbr_to_name.get(away_abbr, away_abbr)]))
        home_span = _match_team_name(segment, abbr_to_candidates.get(home_abbr, [abbr_to_name.get(home_abbr, home_abbr)]))
        if away_span is None or home_span is None:
            continue

        away_start, away_end, away_name = away_span
        home_start, home_end, home_name = home_span
        if away_start < home_start:
            away_lines = segment[away_end:home_start]
            home_lines = segment[home_end:]
        else:
            home_lines = segment[home_end:away_start]
            away_lines = segment[away_end:]

        game_timestamp = _game_timestamp_from_lines(lines, matchup_idx)
        if game_timestamp is None:
            continue

        for team_abbr, team_name, team_lines in [
            (away_abbr, away_name, away_lines),
            (home_abbr, home_name, home_lines),
        ]:
            for row in _parse_team_players_lines(team_lines, team_abbr, team_name, matchup):
                row["game_date"] = game_timestamp.normalize()
                row["tipoff_et"] = game_timestamp
                rows.append(row)

    return pd.DataFrame(rows)


def pull_live_injury_report(
    report_date: pd.Timestamp | None = None,
    force: bool = False,
    cache_path: str = config.LIVE_INJURY_CACHE,
) -> pd.DataFrame:
    report_date = pd.Timestamp(report_date or pd.Timestamp.now(tz="America/New_York"))
    if report_date.tzinfo is None:
        report_date = report_date.tz_localize("America/New_York")
    else:
        report_date = report_date.tz_convert("America/New_York")
    path = Path(cache_path)

    if path.exists() and not force:
        cached = pd.read_csv(path)
        if {"report_date", "report_timestamp"}.issubset(cached.columns):
            cached["report_date"] = pd.to_datetime(cached["report_date"], errors="coerce")
            cached["report_timestamp"] = pd.to_datetime(cached["report_timestamp"], errors="coerce", utc=True)
            latest_report_day = cached["report_date"].dt.date.max()
            if latest_report_day == report_date.tz_localize(None).date():
                return cached

    try:
        report_ts, report_url, pdf_bytes = _fetch_report_pdf(report_date)
        text = _pdf_text(pdf_bytes)
        injuries = _parse_injury_report_text(text)
        if injuries.empty:
            raise ValueError("Parsed injury report was empty")

        injuries["report_timestamp"] = report_ts.tz_convert("UTC")
        injuries["report_url"] = report_url
        injuries["report_date"] = injuries["game_date"]

        path.parent.mkdir(parents=True, exist_ok=True)
        injuries.to_csv(path, index=False)
        return injuries
    except Exception as exc:
        logger.warning("Failed to fetch live injury report: %s", exc)
        emit_alert(
            code="injury_report_fetch_failed",
            severity="warning",
            message="Failed to fetch live NBA injury report",
            context="injuries.pull_live_injury_report",
            details={"error": str(exc)},
        )
        if path.exists():
            cached = pd.read_csv(path)
            for col in ["report_date", "game_date", "tipoff_et", "report_timestamp"]:
                if col in cached.columns:
                    cached[col] = pd.to_datetime(cached[col], errors="coerce", utc=("timestamp" in col))
            return cached
        return pd.DataFrame()


def pull_current_player_stats(
    season: str | None = None,
    force: bool = False,
    cache_path: str = config.PLAYER_STATS_CACHE,
) -> pd.DataFrame:
    season = season or _current_season()
    path = Path(cache_path)

    if path.exists() and not force:
        df = pd.read_csv(path)
        if "season" in df.columns and season in set(df["season"]):
            return df[df["season"] == season].copy()

    try:
        stats = LeagueDashPlayerStats(
            season=season,
            season_type_all_star="Regular Season",
            per_mode_detailed="PerGame",
            measure_type_detailed_defense="Base",
        )
        df = stats.get_data_frames()[0]
        df["season"] = season
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(path, index=False)
        return df
    except Exception as exc:
        logger.warning("Failed to pull current player stats: %s", exc)
        emit_alert(
            code="player_stats_fetch_failed",
            severity="warning",
            message="Failed to fetch current player stats for availability model",
            context="injuries.pull_current_player_stats",
            details={"error": str(exc), "season": season},
        )
        if path.exists():
            return pd.read_csv(path)
        return pd.DataFrame()


def build_team_availability_adjustments(
    injuries_df: pd.DataFrame,
    player_stats_df: pd.DataFrame,
) -> pd.DataFrame:
    if injuries_df.empty:
        return pd.DataFrame(columns=TEAM_ADJUSTMENT_COLUMNS)

    player_stats = player_stats_df.copy()
    if not player_stats.empty:
        player_stats["name_key"] = player_stats["PLAYER_NAME"].map(_name_key)
        player_stats["name_tokens"] = player_stats["PLAYER_NAME"].map(_name_tokens)
        player_stats["value_proxy"] = (
            pd.to_numeric(player_stats.get("PTS"), errors="coerce").fillna(0.0)
            + 0.7 * pd.to_numeric(player_stats.get("AST"), errors="coerce").fillna(0.0)
            + 0.5 * pd.to_numeric(player_stats.get("REB"), errors="coerce").fillna(0.0)
        )
        team_min = player_stats.groupby("TEAM_ABBREVIATION")["MIN"].transform("sum").replace(0, np.nan)
        team_value = player_stats.groupby("TEAM_ABBREVIATION")["value_proxy"].transform("sum").replace(0, np.nan)
        player_stats["minutes_share"] = (pd.to_numeric(player_stats["MIN"], errors="coerce").fillna(0.0) / team_min).fillna(0.0)
        player_stats["value_share"] = (player_stats["value_proxy"] / team_value).fillna(0.0)
        player_stats["impact_score"] = (
            0.65 * (player_stats["minutes_share"] * 5.0).clip(lower=0.0, upper=1.2)
            + 0.35 * (player_stats["value_share"] * 5.0).clip(lower=0.0, upper=1.2)
        ).clip(lower=0.15, upper=1.25)
    else:
        player_stats = pd.DataFrame(columns=["TEAM_ABBREVIATION", "PLAYER_NAME", "name_key", "name_tokens", "impact_score"])

    injuries = injuries_df.copy()
    injuries["player_key"] = injuries["player_name"].fillna("").map(_name_key)
    injuries["player_name_raw"] = injuries["player_name"]
    injuries["status_weight"] = injuries["status"].map(config.INJURY_STATUS_WEIGHTS).fillna(0.0)
    roster_lookup = {
        team: grp[["PLAYER_NAME", "name_key", "name_tokens", "impact_score"]].to_dict("records")
        for team, grp in player_stats.groupby("TEAM_ABBREVIATION")
    }

    canonical_names: list[str | float] = []
    impact_scores: list[float] = []
    match_methods: list[str] = []

    for _, row in injuries.iterrows():
        team_roster = roster_lookup.get(row.get("team"), [])
        raw_name = row.get("player_name")
        raw_key = row.get("player_key")
        raw_tokens = _name_tokens(raw_name)

        best_match = None
        if raw_key:
            for candidate in team_roster:
                if candidate["name_key"] == raw_key:
                    best_match = candidate
                    match_methods.append("exact")
                    break

        if best_match is None and raw_tokens:
            scored = []
            for candidate in team_roster:
                candidate_tokens = candidate.get("name_tokens") or set()
                if not candidate_tokens:
                    continue
                overlap = len(raw_tokens & candidate_tokens)
                coverage = overlap / len(candidate_tokens)
                if overlap <= 0:
                    continue
                scored.append((coverage, overlap, candidate))

            if scored:
                scored.sort(key=lambda item: (item[0], item[1]), reverse=True)
                top_coverage, top_overlap, top_candidate = scored[0]
                second = scored[1] if len(scored) > 1 else None
                second_coverage = second[0] if second else -1
                second_overlap = second[1] if second else -1
                if top_coverage >= 0.5 and (second is None or (top_coverage, top_overlap) > (second_coverage, second_overlap)):
                    best_match = top_candidate
                    match_methods.append("token")

        if best_match is None:
            canonical_names.append(raw_name)
            impact_scores.append(0.20)
            match_methods.append("fallback")
        else:
            canonical_names.append(best_match["PLAYER_NAME"])
            impact_scores.append(float(best_match["impact_score"]))

    injuries["player_name"] = canonical_names
    injuries["impact_score"] = impact_scores
    injuries["player_match_method"] = match_methods
    injuries["penalty_elo"] = (
        injuries["status_weight"]
        * injuries["impact_score"]
        * config.INJURY_IMPACT_ELO_MULTIPLIER
    )

    summary_rows = []
    for team, grp in injuries.groupby("team"):
        penalty = float(grp["penalty_elo"].sum())
        penalty = min(penalty, config.INJURY_MAX_TEAM_ELO_PENALTY)

        notable = grp[grp["status"].isin(["out", "doubtful", "questionable"])].copy()
        notable = notable.sort_values(["penalty_elo", "impact_score"], ascending=False).head(3)
        if notable.empty:
            summary = "No major availability flags"
        else:
            summary = ", ".join(
                f"{row['player_name']} ({row['status']})"
                for _, row in notable.iterrows()
                if pd.notna(row["player_name"])
            )

        report_ts = pd.to_datetime(grp.get("report_timestamp"), errors="coerce", utc=True).max()
        summary_rows.append({
            "team": team,
            "availability_penalty_elo": penalty,
            "availability_summary": summary,
            "out_count": int((grp["status"] == "out").sum()),
            "questionable_count": int((grp["status"] == "questionable").sum()),
            "doubtful_count": int((grp["status"] == "doubtful").sum()),
            "probable_count": int((grp["status"] == "probable").sum()),
            "report_timestamp": report_ts,
        })

    return pd.DataFrame(summary_rows)


def _prediction_feature_adjustments(predictions_df: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    stat_suffixes = [
        "availability_penalty_elo",
        "availability_summary",
        "out_count",
        "questionable_count",
        "doubtful_count",
        "probable_count",
        "report_timestamp",
    ]

    for side in ("home", "away"):
        team_col = f"{side}_team"
        available_cols = [team_col] + [f"{side}_{suffix}" for suffix in stat_suffixes if f"{side}_{suffix}" in predictions_df.columns]
        if len(available_cols) <= 1:
            continue

        side_df = predictions_df[available_cols].copy().rename(columns={team_col: "team"})
        rename_map = {
            f"{side}_{suffix}": suffix
            for suffix in stat_suffixes
            if f"{side}_{suffix}" in side_df.columns
        }
        side_df = side_df.rename(columns=rename_map)
        frames.append(side_df)

    if not frames:
        return pd.DataFrame(columns=TEAM_ADJUSTMENT_COLUMNS)

    combined = pd.concat(frames, ignore_index=True)
    combined = combined.dropna(subset=["team"]).drop_duplicates(subset=["team"], keep="last")

    for col in TEAM_ADJUSTMENT_COLUMNS:
        if col not in combined.columns:
            combined[col] = pd.NaT if col == "report_timestamp" else (0.0 if col.endswith("_count") or col == "availability_penalty_elo" else np.nan)

    combined["availability_penalty_elo"] = pd.to_numeric(
        combined["availability_penalty_elo"], errors="coerce"
    ).fillna(0.0)
    for col in ["out_count", "questionable_count", "doubtful_count", "probable_count"]:
        combined[col] = pd.to_numeric(combined[col], errors="coerce").fillna(0.0)
    combined["availability_summary"] = combined["availability_summary"].fillna("No major availability flags")
    combined["report_timestamp"] = pd.to_datetime(combined["report_timestamp"], errors="coerce", utc=True)
    return combined[TEAM_ADJUSTMENT_COLUMNS].reset_index(drop=True)


def _resolved_official_report_teams(injuries_df: pd.DataFrame) -> set[str]:
    if injuries_df.empty or "team" not in injuries_df.columns:
        return set()

    reported = injuries_df.copy()
    if "status" in reported.columns:
        reported["status"] = reported["status"].fillna("").astype(str).str.lower()
        reported = reported[reported["status"] != "not submitted"]
    return set(reported["team"].dropna().astype(str))


def _espn_fallback_team_adjustments(teams: list[str], player_stats_df: pd.DataFrame) -> pd.DataFrame:
    if not teams:
        return pd.DataFrame(columns=TEAM_ADJUSTMENT_COLUMNS)

    try:
        espn_injuries = fetch_all_espn_injuries(teams=teams)
        if not espn_injuries:
            return pd.DataFrame(columns=TEAM_ADJUSTMENT_COLUMNS)

        espn_adjustments = _espn_injuries_to_adjustments(
            espn_injuries,
            player_stats_df=player_stats_df,
            max_penalty=config.INJURY_MAX_TEAM_ELO_PENALTY,
        )
        if not espn_adjustments:
            return pd.DataFrame(columns=TEAM_ADJUSTMENT_COLUMNS)

        report_ts = pd.Timestamp.now(tz="UTC")
        rows: list[dict] = []
        for team, info in espn_adjustments.items():
            notable = [
                detail for detail in info.get("player_details", [])
                if detail.get("status") in {"Out", "Doubtful", "Questionable", "Day-To-Day"}
            ]
            notable.sort(key=lambda detail: detail.get("penalty", 0), reverse=True)
            summary = ", ".join(
                f"{detail['name']} ({str(detail['status']).lower()})"
                for detail in notable[:3]
                if detail.get("name")
            ) or "No major availability flags"
            rows.append({
                "team": team,
                "availability_penalty_elo": float(info.get("penalty_elo", 0.0)),
                "availability_summary": summary,
                "out_count": float(info.get("out_count", 0)),
                "questionable_count": float(info.get("questionable_count", 0)),
                "doubtful_count": float(info.get("doubtful_count", 0)),
                "probable_count": 0.0,
                "report_timestamp": report_ts,
            })

        return pd.DataFrame(rows, columns=TEAM_ADJUSTMENT_COLUMNS)
    except Exception as exc:
        logger.warning("Failed ESPN fallback injury fetch for %s: %s", ",".join(teams), exc)
        return pd.DataFrame(columns=TEAM_ADJUSTMENT_COLUMNS)


def apply_live_availability_adjustments(
    predictions_df: pd.DataFrame,
    report_date: pd.Timestamp | None = None,
    season: str | None = None,
) -> pd.DataFrame:
    if predictions_df.empty:
        return predictions_df.copy()

    adjusted = predictions_df.copy()
    adjusted["home_win_prob_model"] = adjusted["home_win_prob"]
    adjusted["away_win_prob_model"] = adjusted["away_win_prob"]

    player_stats = pull_current_player_stats(season=season or _current_season())
    feature_fallback = _prediction_feature_adjustments(adjusted)
    teams_in_scope = sorted(
        set(adjusted.get("home_team", pd.Series(dtype=object)).dropna().astype(str))
        | set(adjusted.get("away_team", pd.Series(dtype=object)).dropna().astype(str))
    )

    injuries_df = pull_live_injury_report(report_date=report_date)
    resolved_official_teams: set[str] = set()
    official_adjustments = pd.DataFrame(columns=TEAM_ADJUSTMENT_COLUMNS)
    if not injuries_df.empty:
        resolved_official_teams = _resolved_official_report_teams(injuries_df)
        official_adjustments = build_team_availability_adjustments(injuries_df, player_stats)
        if resolved_official_teams and not official_adjustments.empty:
            official_adjustments = official_adjustments[official_adjustments["team"].isin(resolved_official_teams)].copy()

    if resolved_official_teams and not feature_fallback.empty:
        feature_fallback = feature_fallback[~feature_fallback["team"].isin(resolved_official_teams)].copy()

    covered_teams = set()
    if not official_adjustments.empty:
        covered_teams.update(official_adjustments["team"].dropna().astype(str))
    if not feature_fallback.empty:
        covered_teams.update(feature_fallback["team"].dropna().astype(str))

    missing_teams = [team for team in teams_in_scope if team not in covered_teams]
    espn_adjustments = _espn_fallback_team_adjustments(missing_teams, player_stats)

    adjustment_frames = [
        frame for frame in [official_adjustments, feature_fallback, espn_adjustments]
        if not frame.empty
    ]
    team_adjustments = (
        pd.concat(adjustment_frames, ignore_index=True)
        if adjustment_frames else pd.DataFrame(columns=TEAM_ADJUSTMENT_COLUMNS)
    )
    if team_adjustments.empty:
        adjusted["home_availability_penalty_elo"] = 0.0
        adjusted["away_availability_penalty_elo"] = 0.0
        adjusted["availability_adjustment_elo"] = 0.0
        adjusted["availability_adjustment_prob"] = 0.0
        adjusted["home_availability_summary"] = "No live report available"
        adjusted["away_availability_summary"] = "No live report available"
        return adjusted
    team_adjustments = team_adjustments.drop_duplicates(subset=["team"], keep="first")

    home_adj = team_adjustments.rename(columns={
        "team": "home_team",
        "availability_penalty_elo": "home_availability_penalty_elo",
        "availability_summary": "home_availability_summary",
        "out_count": "home_out_count",
        "questionable_count": "home_questionable_count",
        "doubtful_count": "home_doubtful_count",
        "probable_count": "home_probable_count",
        "report_timestamp": "home_report_timestamp",
    })
    away_adj = team_adjustments.rename(columns={
        "team": "away_team",
        "availability_penalty_elo": "away_availability_penalty_elo",
        "availability_summary": "away_availability_summary",
        "out_count": "away_out_count",
        "questionable_count": "away_questionable_count",
        "doubtful_count": "away_doubtful_count",
        "probable_count": "away_probable_count",
        "report_timestamp": "away_report_timestamp",
    })

    # Drop any pre-existing availability columns (added by ESPN injury feature
    # engineering in get_todays_features) to avoid pandas _x/_y column collisions
    # when the merge adds them again from home_adj / away_adj.
    stale_cols = [c for c in home_adj.columns if c != "home_team"] +                  [c for c in away_adj.columns if c != "away_team"]
    adjusted = adjusted.drop(columns=[c for c in stale_cols if c in adjusted.columns], errors="ignore")
    adjusted = adjusted.merge(home_adj, on="home_team", how="left")
    adjusted = adjusted.merge(away_adj, on="away_team", how="left")

    for col in [
        "home_availability_penalty_elo",
        "away_availability_penalty_elo",
        "home_out_count",
        "home_questionable_count",
        "home_doubtful_count",
        "home_probable_count",
        "away_out_count",
        "away_questionable_count",
        "away_doubtful_count",
        "away_probable_count",
    ]:
        if col in adjusted.columns:
            adjusted[col] = pd.to_numeric(adjusted[col], errors="coerce").fillna(0.0)

    adjusted["availability_adjustment_elo"] = (
        adjusted["away_availability_penalty_elo"] - adjusted["home_availability_penalty_elo"]
    )

    base_prob = adjusted["home_win_prob_model"].clip(0.01, 0.99)
    base_logit = np.log(base_prob / (1.0 - base_prob))
    elo_logit_scale = np.log(10.0) / 400.0
    adjusted_logit = base_logit + (adjusted["availability_adjustment_elo"] * elo_logit_scale)
    adjusted["home_win_prob"] = 1.0 / (1.0 + np.exp(-adjusted_logit))
    adjusted["away_win_prob"] = 1.0 - adjusted["home_win_prob"]
    adjusted["availability_adjustment_prob"] = adjusted["home_win_prob"] - adjusted["home_win_prob_model"]

    adjusted["home_availability_summary"] = adjusted["home_availability_summary"].fillna("No major availability flags")
    adjusted["away_availability_summary"] = adjusted["away_availability_summary"].fillna("No major availability flags")
    adjusted["availability_report_timestamp"] = adjusted[["home_report_timestamp", "away_report_timestamp"]].max(axis=1)
    return adjusted
