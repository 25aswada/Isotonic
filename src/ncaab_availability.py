"""
ncaab_availability.py - Live NCAA availability adjustments from ESPN college rosters.
"""

from __future__ import annotations

import logging
import math
import re
import time
from typing import Any

import pandas as pd
import requests

from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

ESPN_NCAAB_TEAMS_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams"
ESPN_NCAAB_TEAM_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{team_id}"
ESPN_NCAAB_ROSTER_URL = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/teams/{team_id}/roster"

_CACHE_TTL_SECONDS = 900
_TEAM_DIRECTORY_CACHE: dict[str, Any] = {"fetched_at": 0.0, "teams": []}
_TEAM_ADJUSTMENT_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}

_STATUS_WEIGHTS = {
    "out": 1.0,
    "doubtful": 0.7,
    "questionable": 0.4,
    "day-to-day": 0.3,
}
_STATUS_LABELS = {"out", "doubtful", "questionable", "day-to-day"}
_BASE_PLAYER_ELO_PENALTY = 7.0
_MAX_TEAM_ELO_PENALTY = 35.0
_TEAM_ALIASES = {
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
    "miami": "miami fl",
    "nc state": "north carolina state",
    "unc": "north carolina",
    "usf": "south florida",
    "ucf": "central florida",
    "n dakota st": "north dakota state",
    "cal baptist": "california baptist",
    "mcneese": "mcneese state",
    "wright st": "wright state",
    "tennessee st": "tennessee state",
    "long island": "long island university",
    "prairie view": "prairie view a&m",
    "hawai'i": "hawaii",
    "queens": "queens nc",
    "kennesaw st": "kennesaw state",
}


def _normalize_team_name(name: str) -> str:
    text = str(name or "").lower()
    text = text.replace("&", " and ")
    text = re.sub(r"\(([^)]*)\)", r" \1 ", text)
    text = text.replace("st.", "saint")
    text = re.sub(r"\bst\b", "saint", text)
    text = text.replace("'", "")
    text = text.replace("’", "")
    text = re.sub(r"[^a-z0-9]+", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return _TEAM_ALIASES.get(text, text)


def _best_name_match(name: str, candidates: list[str]) -> str:
    normalized_target = _normalize_team_name(name)
    candidate_map = {_normalize_team_name(candidate): candidate for candidate in candidates}

    if normalized_target in candidate_map:
        return candidate_map[normalized_target]
    if normalized_target in _TEAM_ALIASES and _TEAM_ALIASES[normalized_target] in candidate_map:
        return candidate_map[_TEAM_ALIASES[normalized_target]]

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


def _session_get_json(url: str) -> dict[str, Any]:
    response = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
    response.raise_for_status()
    return response.json()


def _fetch_espn_team_directory(force: bool = False) -> list[dict[str, Any]]:
    now = time.time()
    if not force and _TEAM_DIRECTORY_CACHE["teams"] and (now - _TEAM_DIRECTORY_CACHE["fetched_at"]) < _CACHE_TTL_SECONDS:
        return list(_TEAM_DIRECTORY_CACHE["teams"])

    payload = _session_get_json(f"{ESPN_NCAAB_TEAMS_URL}?limit=500")
    sports = payload.get("sports") or []
    leagues = sports[0].get("leagues") if sports else []
    teams = leagues[0].get("teams") if leagues else []
    parsed = [entry.get("team") or {} for entry in teams if (entry.get("team") or {}).get("id")]
    _TEAM_DIRECTORY_CACHE["fetched_at"] = now
    _TEAM_DIRECTORY_CACHE["teams"] = parsed
    return list(parsed)


def _resolve_espn_team(team_name: str) -> dict[str, Any] | None:
    cache_key = f"team::{str(team_name).strip().lower()}"
    cached = _TEAM_ADJUSTMENT_CACHE.get(cache_key)
    now = time.time()
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return dict(cached[1])

    directory = _fetch_espn_team_directory()
    if not directory:
        return None

    candidates: list[str] = []
    candidate_lookup: dict[str, dict[str, Any]] = {}
    for team in directory:
        for field in ("displayName", "shortDisplayName", "nickname", "location", "abbreviation", "name"):
            value = team.get(field)
            if value:
                candidate_lookup[str(value)] = team
                candidates.append(str(value))

    try:
        matched = _best_name_match(team_name, sorted(set(candidates)))
    except KeyError:
        return None

    team = candidate_lookup.get(matched)
    if team is None:
        return None
    _TEAM_ADJUSTMENT_CACHE[cache_key] = (now, team)
    return dict(team)


def _fetch_team_roster_injuries(team_name: str) -> list[dict[str, Any]]:
    team = _resolve_espn_team(team_name)
    team_id = str((team or {}).get("id") or "").strip()
    if not team_id:
        return []

    try:
        payload = _session_get_json(ESPN_NCAAB_ROSTER_URL.format(team_id=team_id))
    except Exception as exc:
        logger.debug("NCAA roster fetch failed for %s: %s", team_name, exc)
        return []

    out: list[dict[str, Any]] = []
    for athlete in payload.get("athletes") or []:
        for injury in athlete.get("injuries") or []:
            status = str(injury.get("status") or "").strip()
            if status.lower() not in _STATUS_LABELS:
                continue
            out.append(
                {
                    "player_name": athlete.get("displayName") or athlete.get("fullName") or "",
                    "status": status,
                    "team": str(team.get("shortDisplayName") or team_name),
                }
            )
    return out


def _team_adjustment_from_injuries(team_name: str) -> dict[str, Any]:
    injuries = _fetch_team_roster_injuries(team_name)
    if not injuries:
        return {
            "team": team_name,
            "availability_penalty_elo": 0.0,
            "availability_summary": "No major availability flags",
            "out_count": 0.0,
            "questionable_count": 0.0,
            "doubtful_count": 0.0,
        }

    penalty = 0.0
    out_count = 0
    questionable_count = 0
    doubtful_count = 0
    notable: list[str] = []
    for item in injuries:
        status = str(item.get("status") or "").strip()
        weight = _STATUS_WEIGHTS.get(status.lower(), 0.0)
        penalty += _BASE_PLAYER_ELO_PENALTY * weight
        if status == "Out":
            out_count += 1
        elif status == "Questionable" or status == "Day-To-Day":
            questionable_count += 1
        elif status == "Doubtful":
            doubtful_count += 1
        if len(notable) < 3:
            notable.append(f'{item.get("player_name", "Unknown")} ({status})')

    penalty = min(penalty, _MAX_TEAM_ELO_PENALTY)
    summary = ", ".join(notable) if notable else "No major availability flags"
    return {
        "team": team_name,
        "availability_penalty_elo": round(float(penalty), 2),
        "availability_summary": summary,
        "out_count": float(out_count),
        "questionable_count": float(questionable_count),
        "doubtful_count": float(doubtful_count),
    }


def get_ncaab_team_adjustments(team_names: list[str]) -> pd.DataFrame:
    rows = []
    now = time.time()
    for team_name in sorted({str(name).strip() for name in team_names if str(name).strip()}):
        cache_key = f"adj::{team_name.lower()}"
        cached = _TEAM_ADJUSTMENT_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            rows.append(dict(cached[1]))
            continue
        adjustment = _team_adjustment_from_injuries(team_name)
        _TEAM_ADJUSTMENT_CACHE[cache_key] = (now, adjustment)
        rows.append(adjustment)
    return pd.DataFrame(rows)


def adjust_ncaab_win_probs(
    prob_a: float,
    prob_b: float,
    team_a_penalty_elo: float = 0.0,
    team_b_penalty_elo: float = 0.0,
) -> tuple[float, float]:
    base_a = float(min(max(prob_a, 0.01), 0.99))
    base_logit = math.log(base_a / (1.0 - base_a))
    elo_logit_scale = math.log(10.0) / 400.0
    adjusted_logit = base_logit + (float(team_b_penalty_elo) - float(team_a_penalty_elo)) * elo_logit_scale
    adj_a = 1.0 / (1.0 + math.exp(-adjusted_logit))
    adj_a = float(min(max(adj_a, 0.01), 0.99))
    return adj_a, 1.0 - adj_a


def apply_ncaab_availability_adjustments(
    df: pd.DataFrame,
    team_a_col: str,
    team_b_col: str,
    prob_a_col: str,
    prob_b_col: str,
    prefix_a: str = "team_a",
    prefix_b: str = "team_b",
) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    adjusted = df.copy()
    team_names = (
        adjusted.get(team_a_col, pd.Series(dtype=object)).dropna().astype(str).tolist()
        + adjusted.get(team_b_col, pd.Series(dtype=object)).dropna().astype(str).tolist()
    )
    team_adjustments = get_ncaab_team_adjustments(team_names)
    if team_adjustments.empty:
        return adjusted

    a_cols = team_adjustments.rename(
        columns={
            "team": team_a_col,
            "availability_penalty_elo": f"{prefix_a}_availability_penalty_elo",
            "availability_summary": f"{prefix_a}_availability_summary",
            "out_count": f"{prefix_a}_out_count",
            "questionable_count": f"{prefix_a}_questionable_count",
            "doubtful_count": f"{prefix_a}_doubtful_count",
        }
    )
    b_cols = team_adjustments.rename(
        columns={
            "team": team_b_col,
            "availability_penalty_elo": f"{prefix_b}_availability_penalty_elo",
            "availability_summary": f"{prefix_b}_availability_summary",
            "out_count": f"{prefix_b}_out_count",
            "questionable_count": f"{prefix_b}_questionable_count",
            "doubtful_count": f"{prefix_b}_doubtful_count",
        }
    )
    adjusted = adjusted.merge(a_cols, on=team_a_col, how="left")
    adjusted = adjusted.merge(b_cols, on=team_b_col, how="left")

    for col in [
        f"{prefix_a}_availability_penalty_elo",
        f"{prefix_b}_availability_penalty_elo",
        f"{prefix_a}_out_count",
        f"{prefix_b}_out_count",
        f"{prefix_a}_questionable_count",
        f"{prefix_b}_questionable_count",
        f"{prefix_a}_doubtful_count",
        f"{prefix_b}_doubtful_count",
    ]:
        if col in adjusted.columns:
            adjusted[col] = pd.to_numeric(adjusted[col], errors="coerce").fillna(0.0)

    if f"{prob_a_col}_model" not in adjusted.columns:
        adjusted[f"{prob_a_col}_model"] = adjusted[prob_a_col]
    if f"{prob_b_col}_model" not in adjusted.columns:
        adjusted[f"{prob_b_col}_model"] = adjusted[prob_b_col]

    new_probs = adjusted.apply(
        lambda row: adjust_ncaab_win_probs(
            row.get(f"{prob_a_col}_model", row.get(prob_a_col, 0.5)),
            row.get(f"{prob_b_col}_model", row.get(prob_b_col, 0.5)),
            row.get(f"{prefix_a}_availability_penalty_elo", 0.0),
            row.get(f"{prefix_b}_availability_penalty_elo", 0.0),
        ),
        axis=1,
        result_type="expand",
    )
    adjusted[prob_a_col] = new_probs[0]
    adjusted[prob_b_col] = new_probs[1]
    adjusted["availability_adjustment_elo"] = (
        adjusted[f"{prefix_b}_availability_penalty_elo"] - adjusted[f"{prefix_a}_availability_penalty_elo"]
    )
    adjusted["availability_adjustment_prob"] = adjusted[prob_a_col] - adjusted[f"{prob_a_col}_model"]
    adjusted[f"{prefix_a}_availability_summary"] = adjusted[f"{prefix_a}_availability_summary"].fillna(
        "No major availability flags"
    )
    adjusted[f"{prefix_b}_availability_summary"] = adjusted[f"{prefix_b}_availability_summary"].fillna(
        "No major availability flags"
    )
    return adjusted
