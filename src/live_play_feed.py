"""
live_play_feed.py - Cached ESPN summary play helpers for NBA and NCAA live cards.
"""

from __future__ import annotations

import threading
import time
from typing import Any

import requests

_CACHE_TTL_SECONDS = 2.0
_PLAY_CACHE: dict[tuple[str, str], tuple[float, dict[str, Any] | None]] = {}
_PLAY_CACHE_LOCK = threading.Lock()

_SPORT_URLS = {
    "nba": "https://site.api.espn.com/apis/site/v2/sports/basketball/nba/summary",
    "ncaab": "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/summary",
}


def _extract_latest_play(summary: dict[str, Any]) -> dict[str, Any] | None:
    plays = summary.get("plays") or []
    if not plays:
        return None

    latest = plays[-1]
    clock = ((latest.get("clock") or {}).get("displayValue") or "").strip()
    period = ((latest.get("period") or {}).get("displayValue") or "").strip()
    text = str(latest.get("text") or latest.get("shortDescription") or "").strip()
    if not text:
        return None

    return {
        "text": text,
        "short_text": str(latest.get("shortDescription") or text).strip(),
        "clock": clock or None,
        "period": period or None,
        "home_score": latest.get("homeScore"),
        "away_score": latest.get("awayScore"),
        "scoring_play": bool(latest.get("scoringPlay")),
        "wallclock": latest.get("wallclock"),
    }


def get_latest_play(sport: str, event_id: str | int | None) -> dict[str, Any] | None:
    if not event_id:
        return None

    sport_key = str(sport or "").strip().lower()
    base_url = _SPORT_URLS.get(sport_key)
    if not base_url:
        return None

    event_key = str(event_id).strip()
    cache_key = (sport_key, event_key)
    now = time.time()

    with _PLAY_CACHE_LOCK:
        cached = _PLAY_CACHE.get(cache_key)
        if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
            return cached[1]

    payload: dict[str, Any] | None = None
    try:
        response = requests.get(
            base_url,
            params={"event": event_key},
            timeout=8,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
        payload = _extract_latest_play(response.json())
    except Exception:
        payload = None

    with _PLAY_CACHE_LOCK:
        _PLAY_CACHE[cache_key] = (time.time(), payload)
    return payload
