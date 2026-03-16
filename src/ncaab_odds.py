"""
ncaab_odds.py - Pull live NCAA prices for projected March Madness teams.
"""

from __future__ import annotations

import json
import logging
import re
from difflib import SequenceMatcher

import concurrent.futures
import numpy as np
import pandas as pd
import requests

import config
import ncaab_config
from src.market_tracking import append_market_snapshot
from src.ncaab_live import normalize_team_name

logger = logging.getLogger(__name__)

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
POLYMARKET_EVENTS_URL = "https://gamma-api.polymarket.com/events"
CLOB_MIDPOINT_URL = "https://clob.polymarket.com/midpoint"
GENERIC_TEAM_TOKENS = {"and", "saint", "state", "north", "south", "east", "west", "college", "university"}


def _fetch_clob_midpoint(token_id: str) -> float:
    """Fetch the current CLOB midpoint price for a single Polymarket token."""
    try:
        r = requests.get(CLOB_MIDPOINT_URL, params={"token_id": token_id}, timeout=5)
        r.raise_for_status()
        mid = r.json().get("mid")
        return float(mid) if mid is not None else np.nan
    except Exception:
        return np.nan


def load_projected_field() -> pd.DataFrame:
    """Load the current projected tournament field."""
    if not ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV.exists():
        return pd.DataFrame()
    df = pd.read_csv(ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV)
    if "TeamName" not in df.columns:
        return pd.DataFrame()
    return df.drop_duplicates(subset=["TeamName"]).reset_index(drop=True)


def _fetch_clob_midpoints_parallel(token_ids: list[str]) -> dict[str, float]:
    """Fetch multiple CLOB midpoints concurrently. Returns {token_id: prob}."""
    unique = [t for t in dict.fromkeys(token_ids) if t]
    if not unique:
        return {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(unique), 5)) as pool:
        results = list(pool.map(_fetch_clob_midpoint, unique))
    return dict(zip(unique, results))

def _projected_team_names() -> list[str]:
    field = load_projected_field()
    if field.empty:
        return []
    return sorted(field["TeamName"].dropna().astype(str).unique().tolist())


def _name_variants(name: str) -> list[str]:
    text = str(name or "").strip()
    if not text:
        return []

    variants = [text]
    words = text.split()
    if len(words) >= 2:
        variants.append(" ".join(words[:-1]))
    if len(words) >= 3:
        variants.append(" ".join(words[:-2]))

    deduped: list[str] = []
    seen: set[str] = set()
    for variant in variants:
        cleaned = variant.strip(" -")
        if cleaned and cleaned not in seen:
            deduped.append(cleaned)
            seen.add(cleaned)
    return deduped


def match_projected_team_name(name: str, candidates: list[str] | None = None) -> str | None:
    """Map a raw market team name to a projected-field team name."""
    candidate_names = candidates if candidates is not None else _projected_team_names()
    if not candidate_names:
        return None

    candidate_map = {normalize_team_name(candidate): candidate for candidate in candidate_names}
    variants = _name_variants(name)

    for variant in variants:
        normalized = normalize_team_name(variant)
        if normalized in candidate_map:
            return candidate_map[normalized]

    for variant in variants:
        normalized = normalize_team_name(variant)
        direct = [
            candidate
            for candidate_norm, candidate in candidate_map.items()
            if normalized and (candidate_norm.startswith(normalized) or normalized.startswith(candidate_norm))
        ]
        if len(direct) == 1:
            return direct[0]

    best_candidate = None
    best_score = -1.0
    best_token_overlap = 0
    for variant in variants:
        normalized = normalize_team_name(variant)
        normalized_tokens = {
            token for token in normalized.split() if token and token not in GENERIC_TEAM_TOKENS
        }
        for candidate_norm, candidate in candidate_map.items():
            score = SequenceMatcher(None, normalized, candidate_norm).ratio()
            if normalized and candidate_norm and (candidate_norm in normalized or normalized in candidate_norm):
                score += 0.12
            candidate_tokens = {
                token for token in candidate_norm.split() if token and token not in GENERIC_TEAM_TOKENS
            }
            token_overlap = len(normalized_tokens & candidate_tokens)
            if score > best_score:
                best_score = score
                best_candidate = candidate
                best_token_overlap = token_overlap

    if best_candidate is None or best_score < 0.72:
        return None
    if best_token_overlap == 0 and best_score < 0.88:
        return None
    return best_candidate


def _to_prob(value) -> float:
    if value is None:
        return np.nan
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return np.nan
    if numeric < 0:
        return np.nan
    return numeric / 100.0 if numeric > 1.0 else numeric


def _to_decimal_from_prob(prob) -> float:
    try:
        numeric = float(prob)
    except (TypeError, ValueError):
        return np.nan
    if numeric <= 0:
        return np.nan
    return 1.0 / numeric


def _normalize_market_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())).strip()


def _select_ncaab_polymarket_winner_market(
    title: str,
    markets: list[dict],
    away_team: str,
    home_team: str,
    candidates: list[str],
) -> dict | None:
    title_norm = _normalize_market_text(title)
    expected = sorted([away_team, home_team])
    best_market = None
    best_score = -1
    best_vol = -1.0

    for market in markets:
        prices = _parse_list_field(market.get("outcomePrices"))
        outcomes = _parse_list_field(market.get("outcomes"))
        if len(prices) != 2 or (outcomes and len(outcomes) != 2):
            continue

        question_norm = _normalize_market_text(market.get("question", ""))
        outcome_names = [match_projected_team_name(outcome, candidates) for outcome in outcomes]
        outcomes_match = (
            len(outcome_names) == 2
            and all(name is not None for name in outcome_names)
            and sorted(outcome_names) == expected
        )

        # Only want the outright game winner market — skip spreads, totals, halves
        spread_keywords = ("spread", "over", "under", "1h", "1st half", "first half",
                           "2nd half", "q1", "q2", "q3", "q4", "quarter", "total", "+", "-")
        if any(kw in question_norm for kw in spread_keywords):
            continue
        if not outcomes_match:
            continue

        is_exact_match = question_norm == title_norm

        try:
            vol = float(market.get("volume") or market.get("volumeNum") or 0)
        except (TypeError, ValueError):
            vol = 0.0

        score = 2 if is_exact_match else 1
        if score > best_score or (score == best_score and vol > best_vol):
            best_market = market
            best_score = score
            best_vol = vol

    return best_market


def _parse_list_field(raw) -> list:
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return list(raw) if raw else []


def _get_odds_api(endpoint: str, params: dict) -> dict | list | None:
    params["apiKey"] = config.ODDS_API_KEY
    url = f"{config.ODDS_API_BASE_URL}/{endpoint}"
    try:
        response = requests.get(url, params=params, timeout=15)
        response.raise_for_status()
        return response.json()
    except Exception as exc:
        logger.warning("NCAA Odds API request failed: %s", exc)
        return None


def get_ncaab_sportsbook_odds(
    projected_only: bool = True,
    candidate_names: list[str] | None = None,
) -> pd.DataFrame:
    """Fetch NCAA sportsbook moneylines for projected-field teams or an arbitrary candidate set."""
    data = _get_odds_api(
        f"sports/{ncaab_config.ODDS_SPORT_KEY}/odds",
        {
            "regions": config.ODDS_REGIONS,
            "markets": config.ODDS_MARKETS,
            "oddsFormat": config.ODDS_FORMAT,
        },
    )
    if not data:
        return pd.DataFrame()

    candidates = candidate_names if candidate_names is not None else _projected_team_names()
    rows: list[dict[str, object]] = []

    for game in data:
        raw_home = str(game.get("home_team", "")).strip()
        raw_away = str(game.get("away_team", "")).strip()
        home_team = match_projected_team_name(raw_home, candidates)
        away_team = match_projected_team_name(raw_away, candidates)

        if projected_only and (home_team is None or away_team is None):
            continue
        if not home_team or not away_team or home_team == away_team:
            continue

        home_prices: list[float] = []
        away_prices: list[float] = []
        bookmakers: list[str] = []
        for bookmaker in game.get("bookmakers", []):
            bookmaker_name = bookmaker.get("title") or bookmaker.get("key")
            for market in bookmaker.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcomes = {outcome["name"]: outcome["price"] for outcome in market.get("outcomes", [])}
                home_price = outcomes.get(raw_home)
                away_price = outcomes.get(raw_away)
                if home_price is None or away_price is None:
                    continue
                try:
                    home_prices.append(float(home_price))
                    away_prices.append(float(away_price))
                    if bookmaker_name:
                        bookmakers.append(str(bookmaker_name))
                except (TypeError, ValueError):
                    continue

        if not home_prices or not away_prices:
            continue

        home_odds_decimal = float(np.mean(home_prices))
        away_odds_decimal = float(np.mean(away_prices))
        home_raw = 1.0 / home_odds_decimal
        away_raw = 1.0 / away_odds_decimal
        total = home_raw + away_raw
        if total <= 0:
            continue

        rows.append(
            {
                "home_team": home_team,
                "away_team": away_team,
                "tipoff_utc": game.get("commence_time"),
                "home_prob": home_raw / total,
                "away_prob": away_raw / total,
                "home_prob_raw": home_raw,
                "away_prob_raw": away_raw,
                "home_bid_prob": np.nan,
                "home_ask_prob": np.nan,
                "away_bid_prob": np.nan,
                "away_ask_prob": np.nan,
                "home_spread_prob": np.nan,
                "away_spread_prob": np.nan,
                "home_odds_decimal": home_odds_decimal,
                "away_odds_decimal": away_odds_decimal,
                "bookmaker_count": len(bookmakers),
                "bookmakers": " | ".join(sorted(set(bookmakers))),
                "source": "sportsbook",
            }
        )

    df = pd.DataFrame(rows)
    logger.info("NCAA sportsbooks: fetched prices for %d games", len(df))
    return df


def _parse_kalshi_title(title: str) -> tuple[str, str] | None:
    patterns = [
        r"^(?P<away>.+?) at (?P<home>.+?) Winner\?$",
        r"^(?P<away>.+?) vs\. (?P<home>.+?) Winner\?$",
        r"^(?P<away>.+?) vs (?P<home>.+?) Winner\?$",
    ]
    for pattern in patterns:
        match = re.match(pattern, str(title).strip())
        if match:
            return match.group("away").strip(), match.group("home").strip()
    return None


def get_ncaab_kalshi_odds(
    projected_only: bool = True,
    candidate_names: list[str] | None = None,
) -> pd.DataFrame:
    """Fetch NCAA Kalshi winner markets for projected-field teams or an arbitrary candidate set."""
    try:
        response = requests.get(
            f"{KALSHI_BASE}/markets",
            params={"limit": 100, "status": "open", "series_ticker": ncaab_config.KALSHI_GAME_SERIES},
            headers={"accept": "application/json"},
            timeout=10,
        )
        response.raise_for_status()
        markets = response.json().get("markets", [])
    except Exception as exc:
        logger.warning("NCAA Kalshi request failed: %s", exc)
        return pd.DataFrame()

    candidates = candidate_names if candidate_names is not None else _projected_team_names()
    game_data: dict[tuple[str, str], dict[str, object]] = {}
    for market in markets:
        parsed = _parse_kalshi_title(str(market.get("title", "")).strip())
        if parsed is None:
            continue

        raw_away, raw_home = parsed
        away_team = match_projected_team_name(raw_away, candidates)
        home_team = match_projected_team_name(raw_home, candidates)
        contract_team = match_projected_team_name(str(market.get("yes_sub_title", "")).strip(), candidates)

        if projected_only and (home_team is None or away_team is None or contract_team is None):
            continue
        if not home_team or not away_team or not contract_team or home_team == away_team:
            continue

        yes_bid = _to_prob(market.get("yes_bid_dollars") or market.get("yes_bid"))
        yes_ask = _to_prob(market.get("yes_ask_dollars") or market.get("yes_ask"))
        mid = float(np.nanmean([yes_bid, yes_ask])) if not (pd.isna(yes_bid) and pd.isna(yes_ask)) else np.nan
        if pd.isna(mid):
            continue

        key = (home_team, away_team)
        entry = game_data.setdefault(
            key,
            {
                "home_team": home_team,
                "away_team": away_team,
                "tipoff_utc": market.get("close_time") or market.get("expected_expiration_time"),
            },
        )

        if contract_team == home_team:
            entry["home_prob_raw"] = mid
            entry["home_bid_prob"] = yes_bid
            entry["home_ask_prob"] = yes_ask
        elif contract_team == away_team:
            entry["away_prob_raw"] = mid
            entry["away_bid_prob"] = yes_bid
            entry["away_ask_prob"] = yes_ask

    rows: list[dict[str, object]] = []
    for entry in game_data.values():
        home_raw = pd.to_numeric(pd.Series([entry.get("home_prob_raw")]), errors="coerce").iloc[0]
        away_raw = pd.to_numeric(pd.Series([entry.get("away_prob_raw")]), errors="coerce").iloc[0]
        if pd.isna(home_raw) or pd.isna(away_raw):
            continue

        total = home_raw + away_raw
        if total <= 0:
            continue

        home_ask_prob = pd.to_numeric(pd.Series([entry.get("home_ask_prob")]), errors="coerce").iloc[0]
        away_ask_prob = pd.to_numeric(pd.Series([entry.get("away_ask_prob")]), errors="coerce").iloc[0]
        home_bid_prob = pd.to_numeric(pd.Series([entry.get("home_bid_prob")]), errors="coerce").iloc[0]
        away_bid_prob = pd.to_numeric(pd.Series([entry.get("away_bid_prob")]), errors="coerce").iloc[0]

        rows.append(
            {
                "home_team": entry["home_team"],
                "away_team": entry["away_team"],
                "tipoff_utc": entry.get("tipoff_utc"),
                "home_prob": home_raw / total,
                "away_prob": away_raw / total,
                "home_prob_raw": home_raw,
                "away_prob_raw": away_raw,
                "home_bid_prob": home_bid_prob,
                "home_ask_prob": home_ask_prob,
                "home_spread_prob": home_ask_prob - home_bid_prob if pd.notna(home_ask_prob) and pd.notna(home_bid_prob) else np.nan,
                "away_bid_prob": away_bid_prob,
                "away_ask_prob": away_ask_prob,
                "away_spread_prob": away_ask_prob - away_bid_prob if pd.notna(away_ask_prob) and pd.notna(away_bid_prob) else np.nan,
                "home_odds_decimal": _to_decimal_from_prob(home_ask_prob if pd.notna(home_ask_prob) else home_raw / total),
                "away_odds_decimal": _to_decimal_from_prob(away_ask_prob if pd.notna(away_ask_prob) else away_raw / total),
                "source": "kalshi",
            }
        )

    df = pd.DataFrame(rows)
    logger.info("NCAA Kalshi: fetched prices for %d games", len(df))
    return df


def get_ncaab_polymarket_odds(
    projected_only: bool = True,
    candidate_names: list[str] | None = None,
) -> pd.DataFrame:
    """Fetch NCAA Polymarket winner prices when game markets are available."""
    events: list[dict] = []
    seen_ids: set[str] = set()
    for tag_slug in ("ncaa-basketball", "college-basketball"):
        try:
            response = requests.get(
                POLYMARKET_EVENTS_URL,
                params={"limit": 200, "active": "true", "closed": "false", "tag_slug": tag_slug},
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
        except Exception as exc:
            logger.warning("NCAA Polymarket request failed for tag %s: %s", tag_slug, exc)
            continue

        for event in payload:
            event_id = str(event.get("id") or event.get("slug") or "")
            if event_id and event_id in seen_ids:
                continue
            if event_id:
                seen_ids.add(event_id)
            events.append(event)

    if not events:
        return pd.DataFrame()

    candidates = candidate_names if candidate_names is not None else _projected_team_names()
    rows: list[dict[str, object]] = []
    # ── Pass 1: parse/filter events, collect token IDs for valid games only ──
    _pending_nc: list[dict] = []
    for event in events:
        title = str(event.get("title", "")).strip()
        if " vs." not in title and " at " not in title:
            continue
        parts = re.split(r"\s+vs\.?\s+|\s+at\s+", title, maxsplit=1)
        if len(parts) != 2:
            continue
        away_team_ev = match_projected_team_name(parts[0], candidates)
        home_team_ev = match_projected_team_name(parts[1], candidates)
        if projected_only and (home_team_ev is None or away_team_ev is None):
            continue
        if not home_team_ev or not away_team_ev or home_team_ev == away_team_ev:
            continue
        wm = _select_ncaab_polymarket_winner_market(title, event.get("markets", []), away_team_ev, home_team_ev, candidates)
        if wm is None:
            continue
        outcomes_ev = _parse_list_field(wm.get("outcomes"))
        tids_ev = _parse_list_field(wm.get("clobTokenIds") or wm.get("clob_token_ids"))
        onames_ev = [match_projected_team_name(o, candidates) for o in outcomes_ev] if outcomes_ev else []
        if len(onames_ev) == 2 and away_team_ev in onames_ev and home_team_ev in onames_ev:
            aidx_ev, hidx_ev = onames_ev.index(away_team_ev), onames_ev.index(home_team_ev)
        else:
            aidx_ev, hidx_ev = 0, 1
        atid = str(tids_ev[aidx_ev]) if len(tids_ev) > aidx_ev else ""
        htid = str(tids_ev[hidx_ev]) if len(tids_ev) > hidx_ev else ""
        _pending_nc.append(dict(event=event, title=title, away_team=away_team_ev, home_team=home_team_ev,
            winner_market=wm, outcomes=outcomes_ev, outcome_names=onames_ev,
            away_idx=aidx_ev, home_idx=hidx_ev, away_token_id=atid, home_token_id=htid))

    # ── Parallel CLOB fetch (only tokens from valid games) ───────────────────
    _nc_tokens = [t for p in _pending_nc for t in (p["away_token_id"], p["home_token_id"]) if t]
    _clob_cache: dict[str, float] = _fetch_clob_midpoints_parallel(_nc_tokens)

    for event in events:
        title = str(event.get("title", "")).strip()
        if " vs." not in title and " at " not in title:
            continue

        parts = re.split(r"\s+vs\.?\s+|\s+at\s+", title, maxsplit=1)
        if len(parts) != 2:
            continue

        away_team = match_projected_team_name(parts[0], candidates)
        home_team = match_projected_team_name(parts[1], candidates)
        if projected_only and (home_team is None or away_team is None):
            continue
        if not home_team or not away_team or home_team == away_team:
            continue

        winner_market = _select_ncaab_polymarket_winner_market(
            title,
            event.get("markets", []),
            away_team,
            home_team,
            candidates,
        )
        if winner_market is None:
            continue

        outcomes = _parse_list_field(winner_market.get("outcomes"))
        token_ids = _parse_list_field(winner_market.get("clobTokenIds") or winner_market.get("clob_token_ids"))

        outcome_names = [match_projected_team_name(outcome, candidates) for outcome in outcomes] if outcomes else []
        if len(outcome_names) == 2 and away_team in outcome_names and home_team in outcome_names:
            away_idx = outcome_names.index(away_team)
            home_idx = outcome_names.index(home_team)
        else:
            away_idx, home_idx = 0, 1

        # Use CLOB midpoints for real-time prices; fall back to outcomePrices if unavailable
        if len(token_ids) == 2:
            away_prob = _clob_cache.get(str(token_ids[away_idx]), np.nan)
            home_prob = _clob_cache.get(str(token_ids[home_idx]), np.nan)
            if np.isnan(away_prob) or np.isnan(home_prob):
                prices = _parse_list_field(winner_market.get("outcomePrices"))
                if len(prices) != 2:
                    continue
                try:
                    away_prob = float(prices[away_idx])
                    home_prob = float(prices[home_idx])
                except (TypeError, ValueError, IndexError):
                    continue
        else:
            prices = _parse_list_field(winner_market.get("outcomePrices"))
            if len(prices) != 2:
                continue
            try:
                away_prob = float(prices[away_idx])
                home_prob = float(prices[home_idx])
            except (TypeError, ValueError, IndexError):
                continue

        total = away_prob + home_prob
        if total <= 0:
            continue

        first_outcome_name = outcome_names[0] if outcome_names else away_team
        first_outcome_bid = pd.to_numeric(pd.Series([winner_market.get("bestBid")]), errors="coerce").iloc[0]
        first_outcome_ask = pd.to_numeric(pd.Series([winner_market.get("bestAsk")]), errors="coerce").iloc[0]
        if first_outcome_name == away_team:
            away_bid_prob = first_outcome_bid
            away_ask_prob = first_outcome_ask
            home_ask_prob = 1.0 - away_bid_prob if pd.notna(away_bid_prob) else np.nan
            home_bid_prob = 1.0 - away_ask_prob if pd.notna(away_ask_prob) else np.nan
        else:
            home_bid_prob = first_outcome_bid
            home_ask_prob = first_outcome_ask
            away_ask_prob = 1.0 - home_bid_prob if pd.notna(home_bid_prob) else np.nan
            away_bid_prob = 1.0 - home_ask_prob if pd.notna(home_ask_prob) else np.nan

        rows.append(
            {
                "home_team": home_team,
                "away_team": away_team,
                "tipoff_utc": event.get("startDate") or event.get("endDate"),
                "home_prob": home_prob / total,
                "away_prob": away_prob / total,
                "home_prob_raw": home_prob,
                "away_prob_raw": away_prob,
                "home_bid_prob": home_bid_prob,
                "home_ask_prob": home_ask_prob,
                "home_spread_prob": home_ask_prob - home_bid_prob if pd.notna(home_ask_prob) and pd.notna(home_bid_prob) else np.nan,
                "away_bid_prob": away_bid_prob,
                "away_ask_prob": away_ask_prob,
                "away_spread_prob": away_ask_prob - away_bid_prob if pd.notna(away_ask_prob) and pd.notna(away_bid_prob) else np.nan,
                "home_odds_decimal": _to_decimal_from_prob(home_ask_prob if pd.notna(home_ask_prob) else home_prob / total),
                "away_odds_decimal": _to_decimal_from_prob(away_ask_prob if pd.notna(away_ask_prob) else away_prob / total),
                "source": "polymarket",
            }
        )

    df = pd.DataFrame(rows)
    logger.info("NCAA Polymarket: fetched prices for %d games", len(df))
    return df


def _prefix_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
    if df.empty:
        return df
    renamed = df.copy()
    rename_map = {
        column: f"{source}_{column}"
        for column in renamed.columns
        if column not in {"home_team", "away_team", "market_date"}
    }
    return renamed.rename(columns=rename_map)


def _market_window_bounds(now: pd.Timestamp | None = None) -> tuple[pd.Timestamp, pd.Timestamp]:
    current = pd.Timestamp.now(tz="UTC") if now is None else pd.Timestamp(now)
    if current.tzinfo is None:
        current = current.tz_localize("UTC")
    else:
        current = current.tz_convert("UTC")
    start = current - pd.Timedelta(days=ncaab_config.MARKET_LOOKBACK_DAYS)
    end = current + pd.Timedelta(days=ncaab_config.MARKET_LOOKAHEAD_DAYS)
    return start, end


def _filter_relevant_ncaab_markets(
    df: pd.DataFrame,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    """Keep only upcoming NCAA markets close enough to the tournament window."""
    if df.empty:
        return df.copy()

    filtered = df.copy()
    filtered["tipoff_utc"] = pd.to_datetime(filtered.get("tipoff_utc"), errors="coerce", utc=True)
    filtered = filtered.dropna(subset=["tipoff_utc"])
    if filtered.empty:
        return filtered

    window_start, window_end = _market_window_bounds(now=now)
    filtered = filtered[
        (filtered["tipoff_utc"] >= window_start)
        & (filtered["tipoff_utc"] <= window_end)
    ].copy()
    if filtered.empty:
        return filtered

    filtered["market_date"] = filtered["tipoff_utc"].dt.normalize()
    filtered = (
        filtered.sort_values("tipoff_utc")
        .drop_duplicates(subset=["home_team", "away_team", "market_date"], keep="last")
        .reset_index(drop=True)
    )
    return filtered


def _prepare_market_frame(
    df: pd.DataFrame,
    source: str,
    now: pd.Timestamp | None = None,
) -> pd.DataFrame:
    filtered = _filter_relevant_ncaab_markets(df, now=now)
    if filtered.empty:
        return filtered
    return _prefix_source(filtered, source)


def _coalesce_columns(df: pd.DataFrame, columns: list[str]) -> pd.Series:
    available = [column for column in columns if column in df.columns]
    if not available:
        return pd.Series(np.nan, index=df.index)
    values = pd.to_numeric(df[available[0]], errors="coerce") if available[0].endswith("_decimal") else df[available[0]]
    for column in available[1:]:
        candidate = pd.to_numeric(df[column], errors="coerce") if column.endswith("_decimal") else df[column]
        values = values.combine_first(candidate)
    return values


def _best_price_source(df: pd.DataFrame, side: str) -> pd.Series:
    decimal_cols = {
        "kalshi": f"kalshi_{side}_odds_decimal",
        "polymarket": f"polymarket_{side}_odds_decimal",
        "sportsbook": f"sportsbook_{side}_odds_decimal",
    }

    sources: list[str | None] = []
    for _, row in df.iterrows():
        available = {
            source: pd.to_numeric(pd.Series([row.get(column)]), errors="coerce").iloc[0]
            for source, column in decimal_cols.items()
            if column in df.columns
        }
        available = {source: price for source, price in available.items() if pd.notna(price)}
        if not available:
            sources.append(None)
            continue
        sources.append(max(available, key=available.get))
    return pd.Series(sources, index=df.index)


def get_all_ncaab_market_odds(
    record_snapshot: bool = True,
    snapshot_context: str = "ncaab_live",
    projected_only: bool = True,
    candidate_names: list[str] | None = None,
) -> pd.DataFrame:
    """Return combined NCAA market prices for projected-field teams or an arbitrary candidate set."""
    frames = [
        _prepare_market_frame(
            get_ncaab_kalshi_odds(projected_only=projected_only, candidate_names=candidate_names),
            "kalshi",
            now=None,
        ),
        _prepare_market_frame(
            get_ncaab_polymarket_odds(projected_only=projected_only, candidate_names=candidate_names),
            "polymarket",
            now=None,
        ),
        _prepare_market_frame(
            get_ncaab_sportsbook_odds(projected_only=projected_only, candidate_names=candidate_names),
            "sportsbook",
            now=None,
        ),
    ]
    frames = [frame for frame in frames if not frame.empty]
    if not frames:
        return pd.DataFrame()

    combined = frames[0]
    for frame in frames[1:]:
        combined = combined.merge(frame, on=["home_team", "away_team", "market_date"], how="outer")

    combined["tipoff_utc"] = _coalesce_columns(
        combined,
        ["sportsbook_tipoff_utc", "kalshi_tipoff_utc", "polymarket_tipoff_utc"],
    )
    combined["tipoff_utc"] = pd.to_datetime(combined["tipoff_utc"], errors="coerce", utc=True)

    reference_cols = [
        column
        for column in [
            "kalshi_home_prob",
            "polymarket_home_prob",
            "sportsbook_home_prob",
        ]
        if column in combined.columns
    ]
    if reference_cols:
        combined["market_home_prob"] = combined[reference_cols].mean(axis=1, skipna=True)
        combined["market_away_prob"] = 1.0 - combined["market_home_prob"]
        combined["market_home_implied"] = combined["market_home_prob"]
        combined["market_away_implied"] = combined["market_away_prob"]

    for side in ["home", "away"]:
        decimal_columns = [
            column
            for column in [
                f"kalshi_{side}_odds_decimal",
                f"polymarket_{side}_odds_decimal",
                f"sportsbook_{side}_odds_decimal",
            ]
            if column in combined.columns
        ]
        if decimal_columns:
            combined[f"{side}_odds_decimal"] = combined[decimal_columns].max(axis=1, skipna=True)
            combined[f"best_{side}_source"] = _best_price_source(combined, side)

    combined["best_source"] = combined["best_home_source"].combine_first(combined.get("best_away_source"))
    combined["sport_key"] = ncaab_config.ODDS_SPORT_KEY

    if record_snapshot:
        append_market_snapshot(combined, context=snapshot_context)

    logger.info("Combined NCAA market odds: %d games", len(combined))
    return combined
