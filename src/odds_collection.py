"""
odds_collection.py — Pull live prices from Kalshi, Polymarket, and The Odds API.
"""

from __future__ import annotations

import json
import logging
import os
import re
import sys
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Optional

import concurrent.futures
import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.market_tracking import append_market_snapshot
from src.monitoring import emit_alert

logger = logging.getLogger(__name__)

RAW = Path(config.RAW_DATA_DIR)
RAW.mkdir(parents=True, exist_ok=True)

# ── Team name → abbreviation mappings ────────────────────────────────────────
# Used to parse Polymarket event titles like "Cavaliers vs. Magic"
_NICKNAME_TO_ABR = {
    "hawks": "ATL", "celtics": "BOS", "nets": "BKN", "hornets": "CHA",
    "bulls": "CHI", "cavaliers": "CLE", "mavericks": "DAL", "nuggets": "DEN",
    "pistons": "DET", "warriors": "GSW", "rockets": "HOU", "pacers": "IND",
    "clippers": "LAC", "lakers": "LAL", "grizzlies": "MEM", "heat": "MIA",
    "bucks": "MIL", "timberwolves": "MIN", "pelicans": "NOP", "knicks": "NYK",
    "thunder": "OKC", "magic": "ORL", "76ers": "PHI", "suns": "PHX",
    "trail blazers": "POR", "kings": "SAC", "spurs": "SAS", "raptors": "TOR",
    "jazz": "UTA", "wizards": "WAS",
}


def _name_to_abr(name: str) -> Optional[str]:
    """Convert a full/partial team name to its 3-letter abbreviation."""
    name_lower = name.lower().strip()
    if name_lower in _NICKNAME_TO_ABR:
        return _NICKNAME_TO_ABR[name_lower]
    for nickname, abr in _NICKNAME_TO_ABR.items():
        if name_lower.endswith(nickname):
            return abr
    return None


def _parse_list_field(raw) -> list:
    """Normalise Polymarket JSON-ish list fields into Python lists."""
    if raw is None:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except Exception:
            return []
    return list(raw) if raw else []


def _clean_prob(value) -> float:
    """Return a bounded probability or NaN if the input is unusable."""
    try:
        prob = float(value)
    except (TypeError, ValueError):
        return np.nan
    if prob < 0 or prob > 1:
        return np.nan
    return prob


def _normalize_market_text(text: str) -> str:
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", str(text or "").lower())).strip()


def _select_polymarket_winner_market(
    title: str,
    markets: list[dict],
    away_abr: str,
    home_abr: str,
) -> dict | None:
    """
    Pick the actual full-game winner market for an NBA matchup.

    Polymarket events often contain spreads, totals, first-half markets, and props.
    The winner market is usually the exact event title (e.g. "Suns vs. Raptors")
    or, less commonly, an explicit full-game moneyline market. We skip partial-game
    and prop markets even if they also contain the matchup text.
    """
    title_norm = _normalize_market_text(title)
    expected = sorted([away_abr, home_abr])
    best_market = None
    best_score = -1

    for market in markets:
        prices = _parse_list_field(market.get("outcomePrices"))
        outcomes = _parse_list_field(market.get("outcomes"))
        if len(prices) != 2 or (outcomes and len(outcomes) != 2):
            continue

        question_norm = _normalize_market_text(market.get("question", ""))
        outcome_abrs = [_name_to_abr(outcome) for outcome in outcomes]
        outcomes_match = (
            len(outcome_abrs) == 2
            and all(abr is not None for abr in outcome_abrs)
            and sorted(outcome_abrs) == expected
        )

        is_exact_match = outcomes_match and question_norm == title_norm
        is_full_game_moneyline = (
            outcomes_match
            and "moneyline" in question_norm
            and all(token not in question_norm for token in ("1h", "1st half", "first half", "q1", "q2", "q3", "q4", "quarter"))
        )

        if is_exact_match:
            score = 2
        elif is_full_game_moneyline:
            score = 1
        else:
            continue

        if score > best_score:
            best_market = market
            best_score = score

    return best_market


@lru_cache(maxsize=512)
def _get_polymarket_fee_rate(token_id: str) -> float:
    """
    Fetch the fee rate for a Polymarket token.

    The CLOB fee endpoint currently returns either `fee_rate_bps` or `base_fee`,
    depending on the API surface. This helper normalises both to a decimal rate.
    """
    if not token_id:
        return 0.0

    try:
        resp = requests.get(
            f"{config.POLYMARKET_CLOB_BASE_URL}/fee-rate",
            params={"token_id": token_id},
            timeout=10,
        )
        resp.raise_for_status()
        payload = resp.json()
    except Exception as e:
        logger.warning("Polymarket fee-rate lookup failed for %s: %s", token_id, e)
        return np.nan

    raw_rate = payload.get("fee_rate_bps")
    if raw_rate is None:
        raw_rate = payload.get("base_fee")
    if raw_rate is None:
        return 0.0

    try:
        raw_rate = float(raw_rate)
    except (TypeError, ValueError):
        return np.nan

    if raw_rate <= 0:
        return 0.0
    if raw_rate > 1:
        return raw_rate / 10000.0
    return raw_rate


# ─────────────────────────────────────────────────────────────────────────────
# Kalshi
# ─────────────────────────────────────────────────────────────────────────────

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_SERIES = "KXNBAGAME"


def get_kalshi_odds() -> pd.DataFrame:
    """
    Pull NBA game winner prices from Kalshi's KXNBAGAME series.

    Returns one row per game with:
        - vig-free reference probabilities from the bid/ask midpoint
        - executable YES bid/ask prices for each team
    """
    try:
        resp = requests.get(
            f"{KALSHI_BASE}/markets",
            params={"limit": 100, "status": "open", "series_ticker": KALSHI_SERIES},
            headers={"accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        markets = resp.json().get("markets", [])
    except Exception as e:
        logger.warning("Kalshi request failed: %s", e)
        emit_alert(
            code="kalshi_fetch_failed",
            severity="warning",
            message="Kalshi odds request failed",
            context="odds_collection.get_kalshi_odds",
            details={"error": str(e)},
        )
        return pd.DataFrame()

    if not markets:
        logger.info("No open Kalshi NBA game markets found.")
        return pd.DataFrame()

    # Parse ticker: KXNBAGAME-26MAR11CHASAC-SAC
    # Format: SERIES-{YY}{MON}{DD}{AWAY3}{HOME3}-{TEAM3}
    game_data: dict[str, dict] = {}

    for m in markets:
        ticker = m.get("ticker", "")
        parts = ticker.split("-")
        if len(parts) < 3:
            continue

        date_teams = parts[1]   # e.g. "26MAR11CHASAC"
        contract_team = parts[2]  # e.g. "SAC"

        # Extract the 3-letter team codes (last 6 chars = AWAYHOME)
        team_part = re.sub(r"^\d{2}[A-Z]{3}\d{2}", "", date_teams)  # strip date prefix
        if len(team_part) != 6:
            continue
        away_abr = team_part[:3]
        home_abr = team_part[3:]
        game_key = f"{away_abr}@{home_abr}"

        # Kalshi now returns prices as dollar decimals (0.0–1.0) in yes_bid_dollars /
        # yes_ask_dollars instead of the old integer cent fields yes_bid / yes_ask.
        # Fall back to the old fields in case Kalshi ever reverts.
        yes_bid_raw = m.get("yes_bid_dollars") or m.get("yes_bid")
        yes_ask_raw = m.get("yes_ask_dollars") or m.get("yes_ask")

        if yes_bid_raw is None and yes_ask_raw is None:
            continue

        # Old field was integer cents (e.g. 55 = $0.55); new is float dollars (e.g. 0.55)
        def _to_prob(val):
            if val is None:
                return np.nan
            v = float(val)
            return v / 100.0 if v > 1.0 else v  # cents → prob if old format

        yes_bid = _to_prob(yes_bid_raw)
        yes_ask = _to_prob(yes_ask_raw)

        if np.isnan(yes_bid) and np.isnan(yes_ask):
            continue

        mid = np.nanmean([yes_bid, yes_ask])

        if game_key not in game_data:
            game_data[game_key] = {"home_abr": home_abr, "away_abr": away_abr}

        if contract_team == home_abr:
            game_data[game_key]["home_prob_raw"] = mid
            game_data[game_key]["home_bid_prob"] = yes_bid
            game_data[game_key]["home_ask_prob"] = yes_ask
        elif contract_team == away_abr:
            game_data[game_key]["away_prob_raw"] = mid
            game_data[game_key]["away_bid_prob"] = yes_bid
            game_data[game_key]["away_ask_prob"] = yes_ask

    rows = []
    for d in game_data.values():
        home_raw = d.get("home_prob_raw")
        away_raw = d.get("away_prob_raw")
        if home_raw is None or away_raw is None:
            continue
        # Normalise to sum to 1.0 (remove Kalshi's take)
        total = home_raw + away_raw
        if total == 0:
            continue
        rows.append({
            "home_team": d["home_abr"],
            "away_team": d["away_abr"],
            "home_prob": home_raw / total,
            "away_prob": away_raw / total,
            "home_prob_raw": home_raw,
            "away_prob_raw": away_raw,
            "home_bid_prob": d.get("home_bid_prob"),
            "home_ask_prob": d.get("home_ask_prob"),
            "home_spread_prob": d.get("home_ask_prob") - d.get("home_bid_prob") if pd.notna(d.get("home_ask_prob")) and pd.notna(d.get("home_bid_prob")) else np.nan,
            "away_bid_prob": d.get("away_bid_prob"),
            "away_ask_prob": d.get("away_ask_prob"),
            "away_spread_prob": d.get("away_ask_prob") - d.get("away_bid_prob") if pd.notna(d.get("away_ask_prob")) and pd.notna(d.get("away_bid_prob")) else np.nan,
            "source": "kalshi",
        })

    df = pd.DataFrame(rows)
    logger.info("Kalshi: fetched prices for %d games", len(df))
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Polymarket
# ─────────────────────────────────────────────────────────────────────────────

POLYMARKET_EVENTS_URL = "https://gamma-api.polymarket.com/events"
CLOB_MIDPOINT_URL = "https://clob.polymarket.com/midpoint"


def _fetch_clob_midpoint(token_id: str) -> float:
    """Fetch the current CLOB midpoint for a Polymarket token (more real-time than outcomePrices)."""
    if not token_id:
        return np.nan
    try:
        r = requests.get(CLOB_MIDPOINT_URL, params={"token_id": token_id}, timeout=5)
        r.raise_for_status()
        mid = r.json().get("mid")
        return float(mid) if mid is not None else np.nan
    except Exception:
        return np.nan


def _fetch_clob_midpoints_parallel(token_ids: list[str]) -> dict[str, float]:
    """Fetch multiple CLOB midpoints concurrently. Returns {token_id: prob}."""
    unique = [t for t in dict.fromkeys(token_ids) if t]
    if not unique:
        return {}
    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(unique), 5)) as pool:
        results = list(pool.map(_fetch_clob_midpoint, unique))
    return dict(zip(unique, results))

def get_polymarket_odds() -> pd.DataFrame:
    """
    Pull NBA game winner prices from Polymarket.

    Searches for events tagged 'nba' and extracts game winner markets.
    Event titles are like "Cavaliers vs. Magic" — we map nicknames to abbreviations.

    Returns one row per game with:
        - reference probabilities from the current outcome prices
        - executable bid/ask for both sides inferred from the binary orderbook
        - fee-rate metadata from the CLOB
    """
    try:
        resp = requests.get(
            POLYMARKET_EVENTS_URL,
            params={"limit": 100, "active": "true", "closed": "false", "tag_slug": "nba"},
            timeout=10,
        )
        resp.raise_for_status()
        events = resp.json()
    except Exception as e:
        logger.warning("Polymarket request failed: %s", e)
        emit_alert(
            code="polymarket_fetch_failed",
            severity="warning",
            message="Polymarket odds request failed",
            context="odds_collection.get_polymarket_odds",
            details={"error": str(e)},
        )
        return pd.DataFrame()

    # ── Pass 1: filter events, resolve team names, identify CLOB token IDs ──────
    _pending: list[dict] = []
    for event in events:
        title = event.get("title", "")
        markets = event.get("markets", [])
        if not markets or "vs." not in title:
            continue
        parts = re.split(r"\s+vs\.?\s+", title, maxsplit=1)
        if len(parts) != 2:
            continue
        team1_abr = _name_to_abr(parts[0])
        team2_abr = _name_to_abr(parts[1])
        if not team1_abr or not team2_abr:
            continue
        away_abr, home_abr = team1_abr, team2_abr
        winner_market = _select_polymarket_winner_market(title, markets, away_abr, home_abr)
        if winner_market is None:
            continue
        outcomes = _parse_list_field(winner_market.get("outcomes"))
        token_ids = _parse_list_field(winner_market.get("clobTokenIds"))
        outcome_abrs = [_name_to_abr(o) for o in outcomes] if outcomes else []
        if len(outcome_abrs) == 2 and away_abr in outcome_abrs and home_abr in outcome_abrs:
            away_idx = outcome_abrs.index(away_abr)
            home_idx = outcome_abrs.index(home_abr)
        else:
            away_idx, home_idx = 0, 1
        away_token_id = str(token_ids[away_idx]) if len(token_ids) > away_idx else ""
        home_token_id = str(token_ids[home_idx]) if len(token_ids) > home_idx else ""
        _pending.append(dict(
            title=title, away_abr=away_abr, home_abr=home_abr,
            winner_market=winner_market, outcomes=outcomes, outcome_abrs=outcome_abrs,
            token_ids=token_ids, away_idx=away_idx, home_idx=home_idx,
            away_token_id=away_token_id, home_token_id=home_token_id,
        ))

    # ── Parallel CLOB fetch — only the ~20 tokens for valid today's games ─────
    _tokens_needed = list({t for p in _pending for t in (p["away_token_id"], p["home_token_id"]) if t})
    _clob_cache: dict[str, float] = _fetch_clob_midpoints_parallel(_tokens_needed)

    rows = []
    for _p in _pending:
        title         = _p["title"]
        away_abr      = _p["away_abr"]
        home_abr      = _p["home_abr"]
        winner_market = _p["winner_market"]
        outcomes      = _p["outcomes"]
        outcome_abrs  = _p["outcome_abrs"]
        token_ids     = _p["token_ids"]
        away_idx      = _p["away_idx"]
        home_idx      = _p["home_idx"]
        away_token_id = _p["away_token_id"]
        home_token_id = _p["home_token_id"]

        away_prob = _clob_cache.get(away_token_id, np.nan) if away_token_id else np.nan
        home_prob = _clob_cache.get(home_token_id, np.nan) if home_token_id else np.nan
        if np.isnan(away_prob) or np.isnan(home_prob):
            prices = _parse_list_field(winner_market.get("outcomePrices"))
            if len(prices) != 2:
                continue
            try:
                away_prob = float(prices[away_idx])
                home_prob = float(prices[home_idx])
            except (ValueError, TypeError, IndexError):
                continue

        if away_prob == 0 and home_prob == 0:
            continue

        # Normalise
        total = home_prob + away_prob
        if total == 0:
            continue

        first_outcome_abr = outcome_abrs[0] if outcome_abrs else away_abr
        first_outcome_bid = _clean_prob(winner_market.get("bestBid"))
        first_outcome_ask = _clean_prob(winner_market.get("bestAsk"))
        if first_outcome_abr == away_abr:
            away_bid_prob = first_outcome_bid
            away_ask_prob = first_outcome_ask
            home_ask_prob = _clean_prob(1.0 - away_bid_prob) if pd.notna(away_bid_prob) else np.nan
            home_bid_prob = _clean_prob(1.0 - away_ask_prob) if pd.notna(away_ask_prob) else np.nan
        else:
            home_bid_prob = first_outcome_bid
            home_ask_prob = first_outcome_ask
            away_ask_prob = _clean_prob(1.0 - home_bid_prob) if pd.notna(home_bid_prob) else np.nan
            away_bid_prob = _clean_prob(1.0 - home_ask_prob) if pd.notna(home_ask_prob) else np.nan

        fees_enabled = bool(winner_market.get("feesEnabled"))
        if fees_enabled:
            away_fee_rate = _get_polymarket_fee_rate(away_token_id)
            home_fee_rate = _get_polymarket_fee_rate(home_token_id)
            if pd.isna(away_fee_rate) or pd.isna(home_fee_rate):
                logger.warning("Skipping fee-enabled Polymarket market without fee-rate data: %s", title)
                continue
        else:
            away_fee_rate = 0.0
            home_fee_rate = 0.0

        # Prefer CLOB mid (bestBid/bestAsk) over outcomePrices — it's more current.
        # outcomePrices is a snapshot that can lag; the CLOB mid reflects live orderbook.
        clob_away_mid = np.nanmean([v for v in [away_bid_prob, away_ask_prob] if pd.notna(v)]) if (pd.notna(away_bid_prob) or pd.notna(away_ask_prob)) else np.nan
        if pd.notna(clob_away_mid) and 0.01 < clob_away_mid < 0.99:
            # CLOB is live and not settled — use it
            away_prob_final = clob_away_mid
            home_prob_final = 1.0 - clob_away_mid
        else:
            # Fall back to outcomePrices normalised
            away_prob_final = away_prob / total
            home_prob_final = home_prob / total

        # Skip markets that have fully settled (one side >= 99.5%) — stale post-game data
        if away_prob_final >= 0.995 or home_prob_final >= 0.995:
            logger.debug("Skipping settled Polymarket market: %s (%.3f / %.3f)", title, away_prob_final, home_prob_final)
            continue

        rows.append({
            "home_team": home_abr,
            "away_team": away_abr,
            "home_prob": home_prob_final,
            "away_prob": away_prob_final,
            "home_prob_raw": home_prob,
            "away_prob_raw": away_prob,
            "home_bid_prob": home_bid_prob,
            "home_ask_prob": home_ask_prob,
            "home_spread_prob": home_ask_prob - home_bid_prob if pd.notna(home_ask_prob) and pd.notna(home_bid_prob) else np.nan,
            "away_bid_prob": away_bid_prob,
            "away_ask_prob": away_ask_prob,
            "away_spread_prob": away_ask_prob - away_bid_prob if pd.notna(away_ask_prob) and pd.notna(away_bid_prob) else np.nan,
            "home_fee_rate": home_fee_rate,
            "away_fee_rate": away_fee_rate,
            "home_token_id": home_token_id,
            "away_token_id": away_token_id,
            "fees_enabled": fees_enabled,
            "source": "polymarket",
        })

    df = pd.DataFrame(rows)
    logger.info("Polymarket: fetched prices for %d games", len(df))
    return df


# ─────────────────────────────────────────────────────────────────────────────
# The Odds API (sportsbooks — fallback)
# ─────────────────────────────────────────────────────────────────────────────

def _get_odds_api(endpoint: str, params: dict) -> dict | list | None:
    params["apiKey"] = config.ODDS_API_KEY
    url = f"{config.ODDS_API_BASE_URL}/{endpoint}"
    try:
        resp = requests.get(url, params=params, timeout=15)
        remaining = resp.headers.get("x-requests-remaining", "?")
        logger.debug("Odds API requests remaining: %s", remaining)
        resp.raise_for_status()
        return resp.json()
    except Exception as e:
        logger.warning("Odds API request failed: %s", e)
        emit_alert(
            code="sportsbook_fetch_failed",
            severity="warning",
            message="Sportsbook odds request failed",
            context="odds_collection._get_odds_api",
            details={"error": str(e), "endpoint": endpoint},
        )
        return None


def get_sportsbook_odds() -> pd.DataFrame:
    """
    Pull moneyline odds from DraftKings/FanDuel via The Odds API.
    Returns same schema as Kalshi/Polymarket functions.
    """
    data = _get_odds_api(
        f"sports/{config.SPORT_KEY}/odds",
        {
            "regions": config.ODDS_REGIONS,
            "markets": config.ODDS_MARKETS,
            "oddsFormat": config.ODDS_FORMAT,
        },
    )
    if not data:
        return pd.DataFrame()

    rows = []
    for game in data:
        home_team = game.get("home_team", "")
        away_team = game.get("away_team", "")
        # Map full names to abbreviations
        home_abr = _name_to_abr(home_team.split()[-1])  # last word = nickname
        away_abr = _name_to_abr(away_team.split()[-1])
        if not home_abr or not away_abr:
            continue

        home_prices, away_prices = [], []
        for bm in game.get("bookmakers", []):
            for market in bm.get("markets", []):
                if market.get("key") != "h2h":
                    continue
                outcomes = {o["name"]: o["price"] for o in market.get("outcomes", [])}
                h = outcomes.get(home_team)
                a = outcomes.get(away_team)
                if h and a:
                    home_prices.append(h)
                    away_prices.append(a)

        if not home_prices:
            continue

        home_dec = sum(home_prices) / len(home_prices)
        away_dec = sum(away_prices) / len(away_prices)
        home_raw = 1.0 / home_dec
        away_raw = 1.0 / away_dec
        total = home_raw + away_raw

        rows.append({
            "home_team": home_abr,
            "away_team": away_abr,
            "home_prob": home_raw / total,
            "away_prob": away_raw / total,
            "home_prob_raw": home_raw,
            "away_prob_raw": away_raw,
            "home_bid_prob": np.nan,
            "home_ask_prob": np.nan,
            "home_spread_prob": np.nan,
            "away_bid_prob": np.nan,
            "away_ask_prob": np.nan,
            "away_spread_prob": np.nan,
            "source": "sportsbook",
        })

    df = pd.DataFrame(rows)
    logger.info("Sportsbook (Odds API): fetched prices for %d games", len(df))
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Combined — best price across all sources
# ─────────────────────────────────────────────────────────────────────────────

def get_all_market_odds(record_snapshot: bool = True, snapshot_context: str = "live") -> pd.DataFrame:
    """
    Fetch prices from Kalshi, Polymarket, and The Odds API and return all of them
    in a single DataFrame keyed by (home_team, away_team).

    Returns one row per game with per-source fields prefixed by source name.
    """
    kalshi = get_kalshi_odds()
    poly = get_polymarket_odds()

    def _prefix_source(df: pd.DataFrame, source: str) -> pd.DataFrame:
        if df.empty:
            return df
        renamed = df.copy()
        rename_map = {
            col: f"{source}_{col}"
            for col in renamed.columns
            if col not in {"home_team", "away_team"}
        }
        return renamed.rename(columns=rename_map)

    frames = [
        _prefix_source(kalshi, "kalshi"),
        _prefix_source(poly, "polymarket"),
    ]
    frames = [f for f in frames if not f.empty]
    if not frames:
        return pd.DataFrame()

    df = frames[0]
    for frame in frames[1:]:
        df = df.merge(frame, on=["home_team", "away_team"], how="outer")

    reference_cols = [
        col for col in [
            "kalshi_home_prob",
            "polymarket_home_prob",
        ]
        if col in df.columns
    ]

    if reference_cols:
        df["market_home_prob"] = df[reference_cols].mean(axis=1, skipna=True)
        df["market_away_prob"] = 1.0 - df["market_home_prob"]

        def _best_source(row: pd.Series) -> str | None:
            available = {col.split("_")[0]: row[col] for col in reference_cols if pd.notna(row[col])}
            return max(available, key=available.get) if available else None

        df["best_source"] = df.apply(_best_source, axis=1)

    if not df.empty:
        df["market_home_implied"] = df["market_home_prob"]
        df["market_away_implied"] = df["market_away_prob"]
        df["home_odds_decimal"] = np.where(df["market_home_implied"] > 0, 1.0 / df["market_home_implied"], np.nan)
        df["away_odds_decimal"] = np.where(df["market_away_implied"] > 0, 1.0 / df["market_away_implied"], np.nan)
        if record_snapshot:
            append_market_snapshot(df, context=snapshot_context)
    logger.info("Combined market odds: %d games across all sources", len(df))
    return df


# ─────────────────────────────────────────────────────────────────────────────
# Legacy compatibility
# ─────────────────────────────────────────────────────────────────────────────

def get_live_odds(**kwargs) -> pd.DataFrame:
    """Alias for backwards compatibility — returns combined odds in old format."""
    combined = get_all_market_odds()
    if combined.empty:
        return pd.DataFrame()
    combined["home_market_implied"] = combined["market_home_implied"]
    return combined


def vig_free_prob(home_decimal: float, away_decimal: float) -> tuple[float, float]:
    """Remove vig from decimal odds. Returns (home_prob, away_prob) summing to 1."""
    home_raw = 1.0 / home_decimal
    away_raw = 1.0 / away_decimal
    total = home_raw + away_raw
    return home_raw / total, away_raw / total
