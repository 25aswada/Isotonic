"""
nba_combos.py - NBA Kalshi combo analysis and paper trading helpers.

This module uses Kalshi's official NBA single-game combo collections as the leg
source, then prices paper combo tickets from the underlying leg prices.
"""

from __future__ import annotations

import json
import logging
import math
import os
import re
import sys
import time
from pathlib import Path
from typing import Any
from hashlib import md5

import numpy as np
import pandas as pd
import requests

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.market_tracking import enrich_paper_trades_with_clv
from src.paper_trading import (
    _build_kalshi_position,
    _kalshi_fee_dollars,
    _round_money,
    _safe_float,
)

logger = logging.getLogger(__name__)

KALSHI_BASE = "https://api.elections.kalshi.com/trade-api/v2"
KALSHI_COMBO_SERIES = "KXMVENBASINGLEGAME"
_CACHE_TTL_SECONDS = 30
_PREDICTION_CACHE: dict[str, Any] = {"ts": 0.0, "value": pd.DataFrame()}
_COLLECTION_CACHE: dict[str, Any] = {"ts": 0.0, "value": []}
_BOARD_CACHE: dict[str, Any] = {"ts": 0.0, "value": {"collections": []}}
_EVENT_MARKET_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
_DETAIL_CACHE: dict[str, tuple[float, dict[str, Any]]] = {}


def _norm_cdf(value: float) -> float:
    return 0.5 * (1.0 + math.erf(float(value) / math.sqrt(2.0)))


def _clean_prob(value: float) -> float:
    return float(np.clip(value, 0.01, 0.99))


def _market_price(leg: dict[str, Any], side: str) -> float:
    raw = leg.get(f"yes_{side}_dollars")
    if raw is None:
        return np.nan
    value = _safe_float(raw)
    if 0 < value <= 1:
        return float(value)
    if 1 < value <= 100:
        return float(value / 100.0)
    return np.nan


def _fetch_combo_collections() -> list[dict[str, Any]]:
    now = time.time()
    if now - float(_COLLECTION_CACHE["ts"]) < _CACHE_TTL_SECONDS and _COLLECTION_CACHE["value"]:
        return list(_COLLECTION_CACHE["value"])
    try:
        resp = requests.get(
            f"{KALSHI_BASE}/multivariate_event_collections",
            params={"series_ticker": KALSHI_COMBO_SERIES, "limit": 100},
            headers={"accept": "application/json"},
            timeout=10,
        )
        resp.raise_for_status()
        collections = list(resp.json().get("multivariate_contracts", []))
        _COLLECTION_CACHE.update({"ts": now, "value": collections})
        return collections
    except Exception as exc:
        logger.warning("Failed to fetch Kalshi combo collections: %s", exc)
        return []


def _fetch_event_markets(event_ticker: str) -> list[dict[str, Any]]:
    now = time.time()
    cached = _EVENT_MARKET_CACHE.get(event_ticker)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return list(cached[1])
    delays = [0.0, 0.25, 0.6]
    last_exc: Exception | None = None
    for delay in delays:
        if delay > 0:
            time.sleep(delay)
        try:
            resp = requests.get(
                f"{KALSHI_BASE}/markets",
                params={"event_ticker": event_ticker, "limit": 100},
                headers={"accept": "application/json"},
                timeout=10,
            )
            resp.raise_for_status()
            markets = list(resp.json().get("markets", []))
            _EVENT_MARKET_CACHE[event_ticker] = (time.time(), markets)
            return markets
        except Exception as exc:
            last_exc = exc
            continue
    logger.warning("Failed to fetch markets for %s: %s", event_ticker, last_exc)
    return []


def _winner_event_ticker(collection: dict[str, Any]) -> str | None:
    for event in collection.get("associated_events", []) or []:
        ticker = str(event.get("ticker", "")).strip()
        if ticker.startswith("KXNBAGAME-"):
            return ticker
    return None


def _parse_game_from_event_ticker(event_ticker: str) -> tuple[str, str] | None:
    match = re.match(r"^KXNBAGAME-\d{2}[A-Z]{3}\d{2}([A-Z]{3})([A-Z]{3})$", str(event_ticker))
    if not match:
        return None
    return match.group(1), match.group(2)


def _prediction_context() -> pd.DataFrame:
    now = time.time()
    cached = _PREDICTION_CACHE.get("value")
    if now - float(_PREDICTION_CACHE["ts"]) < _CACHE_TTL_SECONDS and isinstance(cached, pd.DataFrame) and not cached.empty:
        return cached.copy()

    from scripts.daily_predictions import get_todays_features
    from src.injuries import apply_live_availability_adjustments
    from src.predict import predict_batch

    features = get_todays_features()
    if features.empty:
        return pd.DataFrame()

    predictions = predict_batch(features)
    try:
        predictions = apply_live_availability_adjustments(predictions)
    except Exception:
        pass

    keep_cols = [
        c for c in [
            "game_id",
            "game_date",
            "tipoff_utc",
            "home_team",
            "away_team",
            "home_win_prob",
            "away_win_prob",
            "pred_home_score",
            "pred_away_score",
        ]
        if c in predictions.columns
    ]
    result = predictions[keep_cols].copy()
    _PREDICTION_CACHE.update({"ts": now, "value": result})
    return result


def _lookup_prediction(predictions: pd.DataFrame, home_team: str, away_team: str) -> dict[str, Any] | None:
    if predictions.empty:
        return None
    match = predictions[
        (predictions["home_team"].astype(str) == str(home_team))
        & (predictions["away_team"].astype(str) == str(away_team))
    ]
    if match.empty:
        return None
    return match.iloc[0].to_dict()


def _parse_spread_leg(leg: dict[str, Any], home_team: str, away_team: str) -> dict[str, Any] | None:
    title = str(leg.get("title", "")).strip()
    threshold_match = re.match(r"^(.*?) wins by over ([0-9]+(?:\.[0-9]+)?) Points\?$", title)
    ticker = str(leg.get("ticker", "")).strip()
    ticker_match = re.search(r"-([A-Z]{3})([0-9]+)$", ticker)
    if not threshold_match or not ticker_match:
        return None
    threshold = float(threshold_match.group(2))
    team = ticker_match.group(1)
    side = "home" if team == home_team else "away"
    return {
        "market_type": "spread",
        "threshold": threshold,
        "team": team,
        "team_side": side,
        "player": None,
        "selection_group": f"spread::{team}",
        "display": title.replace("?", ""),
    }


def _parse_total_leg(leg: dict[str, Any]) -> dict[str, Any] | None:
    ticker = str(leg.get("ticker", "")).strip()
    if not ticker.startswith("KXNBATOTAL-"):
        return None
    match = re.search(r"-([0-9]+)$", ticker)
    if not match:
        return None
    threshold = float(match.group(1))
    return {
        "market_type": "total",
        "threshold": threshold,
        "team": None,
        "team_side": None,
        "player": None,
        "selection_group": "total",
        "display": f"Total over {threshold}",
    }


def _parse_prop_leg(leg: dict[str, Any]) -> dict[str, Any] | None:
    title = str(leg.get("title", "")).strip()
    match = re.match(
        r"^(.*?):\s*([0-9]+(?:\.[0-9]+)?)\+\s+(points|rebounds|assists|steals|blocks)$",
        title,
        flags=re.IGNORECASE,
    )
    if not match:
        return None
    player = match.group(1).strip()
    threshold = float(match.group(2))
    stat = match.group(3).strip().lower()
    return {
        "market_type": stat,
        "threshold": threshold,
        "team": None,
        "team_side": None,
        "player": player,
        "selection_group": f"{player.lower()}::{stat}",
        "display": title,
    }


def _parse_winner_leg(leg: dict[str, Any], home_team: str, away_team: str) -> dict[str, Any] | None:
    ticker = str(leg.get("ticker", "")).strip()
    if not ticker.startswith("KXNBAGAME-"):
        return None
    team = ticker.split("-")[-1]
    side = "home" if team == home_team else "away"
    return {
        "market_type": "winner",
        "threshold": None,
        "team": team,
        "team_side": side,
        "player": None,
        "selection_group": "winner",
        "display": f"{team} wins",
    }


def _leg_model_probability(
    leg_info: dict[str, Any],
    prediction_row: dict[str, Any] | None,
    market_prob: float,
) -> float:
    if prediction_row is None:
        return market_prob

    home_prob = _safe_float(prediction_row.get("home_win_prob"))
    away_prob = _safe_float(prediction_row.get("away_win_prob"))
    pred_home_score = _safe_float(prediction_row.get("pred_home_score"))
    pred_away_score = _safe_float(prediction_row.get("pred_away_score"))

    market_type = str(leg_info.get("market_type", ""))
    if market_type == "winner":
        if leg_info.get("team_side") == "home" and 0 < home_prob < 1:
            return float(home_prob)
        if leg_info.get("team_side") == "away" and 0 < away_prob < 1:
            return float(away_prob)
        return market_prob

    if market_type in {"points", "rebounds", "assists", "steals", "blocks"}:
        try:
            from src.player_props import estimate_player_prop

            estimate = estimate_player_prop(
                player_name=str(leg_info.get("player", "")),
                stat=market_type,
                threshold=float(leg_info.get("threshold") or 0.0),
                home_team=str(leg_info.get("home_team", "")) or None,
                away_team=str(leg_info.get("away_team", "")) or None,
            )
            if estimate is not None:
                return float(estimate.get("model_prob", market_prob))
        except Exception:
            pass
        return market_prob

    if pd.isna(pred_home_score) or pd.isna(pred_away_score):
        return market_prob

    pred_margin = float(pred_home_score - pred_away_score)
    pred_total = float(pred_home_score + pred_away_score)

    if market_type == "spread":
        threshold = float(leg_info.get("threshold") or 0.0)
        if leg_info.get("team_side") == "home":
            z = (pred_margin - threshold) / config.COMBO_MARGIN_STD
            return _clean_prob(_norm_cdf(z))
        z = ((-pred_margin) - threshold) / config.COMBO_MARGIN_STD
        return _clean_prob(_norm_cdf(z))

    if market_type == "total":
        threshold = float(leg_info.get("threshold") or 0.0)
        z = (pred_total - threshold) / config.COMBO_TOTAL_STD
        return _clean_prob(_norm_cdf(z))

    return market_prob


def _normalize_leg(
    collection_ticker: str,
    home_team: str,
    away_team: str,
    leg: dict[str, Any],
    prediction_row: dict[str, Any] | None,
) -> dict[str, Any] | None:
    ask_price = _market_price(leg, "ask")
    bid_price = _market_price(leg, "bid")
    if not (0 < ask_price < 1):
        return None

    parsed = (
        _parse_winner_leg(leg, home_team, away_team)
        or _parse_spread_leg(leg, home_team, away_team)
        or _parse_prop_leg(leg)
        or _parse_total_leg(leg)
    )
    if parsed is None:
        return None
    parsed["home_team"] = home_team
    parsed["away_team"] = away_team

    market_prob = ask_price
    model_prob = _leg_model_probability(parsed, prediction_row, market_prob)
    record = {
        "collection_ticker": collection_ticker,
        "market_ticker": str(leg.get("ticker", "")).strip(),
        "title": str(leg.get("title", "")).strip(),
        "display": parsed["display"],
        "market_type": parsed["market_type"],
        "team": parsed["team"],
        "team_side": parsed["team_side"],
        "player": parsed.get("player"),
        "selection_group": parsed.get("selection_group", parsed["market_type"]),
        "threshold": parsed["threshold"],
        "entry_price": float(ask_price),
        "mark_price": float(bid_price) if 0 < bid_price < 1 else float(ask_price),
        "market_prob": float(market_prob),
        "model_prob": float(model_prob),
        "edge": float(model_prob - market_prob),
    }
    if parsed["market_type"] in {"points", "rebounds", "assists", "steals", "blocks"}:
        try:
            from src.player_props import estimate_player_prop

            estimate = estimate_player_prop(
                player_name=str(parsed.get("player", "")),
                stat=str(parsed.get("market_type", "")),
                threshold=float(parsed.get("threshold") or 0.0),
                home_team=home_team,
                away_team=away_team,
            )
            if estimate is not None:
                player_team = str(estimate.get("player_team") or "") or None
                team_side = None
                if player_team == home_team:
                    team_side = "home"
                elif player_team == away_team:
                    team_side = "away"
                record.update({
                    "team": player_team,
                    "team_side": team_side,
                    "model_prob": float(estimate.get("model_prob") or model_prob),
                    "edge": float((estimate.get("model_prob") or model_prob) - market_prob),
                    "projected_minutes": float(estimate.get("projected_minutes") or 0.0),
                    "projected_mean": float(estimate.get("projected_mean") or 0.0),
                    "projected_std": float(estimate.get("projected_std") or 0.0),
                    "season_average": float(estimate.get("season_average") or 0.0),
                    "recent_average": float(estimate.get("recent_average") or 0.0),
                    "games_used": int(estimate.get("games_used") or 0),
                    "model_source": str(estimate.get("model_source") or "log_based_prop_estimator_v1"),
                })
        except Exception:
            pass
    return record


def get_combo_board() -> dict[str, Any]:
    now = time.time()
    cached = _BOARD_CACHE.get("value")
    if now - float(_BOARD_CACHE["ts"]) < _CACHE_TTL_SECONDS and isinstance(cached, dict) and cached.get("collections"):
        return {"collections": list(cached.get("collections", []))}

    predictions = _prediction_context()
    from src.odds_collection import get_all_market_odds

    odds_df = get_all_market_odds(record_snapshot=False)
    collections = _fetch_combo_collections()
    board: list[dict[str, Any]] = []

    for collection in collections:
        winner_event = _winner_event_ticker(collection)
        if not winner_event:
            continue
        matchup = _parse_game_from_event_ticker(winner_event)
        if not matchup:
            continue
        away_team, home_team = matchup
        prediction_row = _lookup_prediction(predictions, home_team=home_team, away_team=away_team)
        if prediction_row is None:
            continue

        odds_match = odds_df[
            (odds_df["home_team"].astype(str) == str(home_team))
            & (odds_df["away_team"].astype(str) == str(away_team))
        ] if not odds_df.empty else pd.DataFrame()
        odds_row = odds_match.iloc[0].to_dict() if not odds_match.empty else {}
        home_market = _safe_float(odds_row.get("kalshi_home_prob"))
        away_market = _safe_float(odds_row.get("kalshi_away_prob"))
        home_prob = _safe_float(prediction_row.get("home_win_prob"))
        away_prob = _safe_float(prediction_row.get("away_win_prob"))
        best_edge = max(
            float(home_prob - home_market) if 0 < home_market < 1 else 0.0,
            float(away_prob - away_market) if 0 < away_market < 1 else 0.0,
        )
        board.append({
            "collection_ticker": str(collection.get("collection_ticker", "")),
            "title": str(collection.get("title", "")).strip(),
            "description": str(collection.get("description", "")).strip(),
            "functional_description": str(collection.get("functional_description", "")).strip(),
            "home_team": home_team,
            "away_team": away_team,
            "tipoff_utc": prediction_row.get("tipoff_utc"),
            "pred_home_score": prediction_row.get("pred_home_score"),
            "pred_away_score": prediction_row.get("pred_away_score"),
            "home_win_prob": prediction_row.get("home_win_prob"),
            "away_win_prob": prediction_row.get("away_win_prob"),
            "best_edge": float(best_edge),
            "legs": [],
        })

    board.sort(key=lambda row: row.get("tipoff_utc") or "")
    result = {"collections": board}
    _BOARD_CACHE.update({"ts": now, "value": result})
    return result


def get_collection_detail(collection_ticker: str) -> dict[str, Any] | None:
    now = time.time()
    cached = _DETAIL_CACHE.get(collection_ticker)
    if cached and (now - cached[0]) < _CACHE_TTL_SECONDS:
        return dict(cached[1])

    collections = _fetch_combo_collections()
    collection = next((item for item in collections if str(item.get("collection_ticker", "")).strip() == collection_ticker), None)
    if collection is None:
        return None

    base_board = get_combo_board()
    base = next((item for item in base_board["collections"] if item["collection_ticker"] == collection_ticker), None)
    if base is None:
        return None

    prediction_row = {
        "home_win_prob": base.get("home_win_prob"),
        "away_win_prob": base.get("away_win_prob"),
        "pred_home_score": base.get("pred_home_score"),
        "pred_away_score": base.get("pred_away_score"),
    }

    leg_rows: list[dict[str, Any]] = []
    for event in collection.get("associated_events", []) or []:
        event_ticker = str(event.get("ticker", "")).strip()
        if not (
            event_ticker.startswith("KXNBAGAME-")
            or event_ticker.startswith("KXNBASPREAD-")
            or event_ticker.startswith("KXNBATOTAL-")
            or event_ticker.startswith("KXNBAPTS-")
            or event_ticker.startswith("KXNBAREB-")
            or event_ticker.startswith("KXNBAAST-")
            or event_ticker.startswith("KXNBASTL-")
            or event_ticker.startswith("KXNBABLK-")
        ):
            continue
        for leg in _fetch_event_markets(event_ticker):
            normalized = _normalize_leg(
                collection_ticker=collection_ticker,
                home_team=str(base.get("home_team", "")),
                away_team=str(base.get("away_team", "")),
                leg=leg,
                prediction_row=prediction_row,
            )
            if normalized is not None:
                leg_rows.append(normalized)

    detail = {
        **base,
        "description": str(collection.get("description", "")).strip(),
        "functional_description": str(collection.get("functional_description", "")).strip(),
        "legs": sorted(
            leg_rows,
            key=lambda row: (0 if row["market_type"] == "winner" else 1, row["entry_price"]),
        ),
    }
    _DETAIL_CACHE[collection_ticker] = (now, detail)
    return detail


def _combo_trade_id(collection_ticker: str, market_tickers: list[str]) -> str:
    key = "_".join(sorted(market_tickers))
    today = pd.Timestamp.now().date().isoformat()
    return f"combo_{today}_{collection_ticker}_{md5(key.encode('utf-8')).hexdigest()[:12]}"


def _combo_label(legs: list[dict[str, Any]]) -> str:
    return " + ".join(str(leg.get("display", leg.get("market_ticker", ""))) for leg in legs)


def _leg_sort_key(leg: dict[str, Any]) -> tuple[float, float, float]:
    model_prob = float(leg.get("model_prob", 0.0))
    market_prob = float(leg.get("market_prob", 0.0))
    edge = float(leg.get("edge", 0.0))
    return (
        max(edge, 0.0),
        max(model_prob, market_prob),
        max(market_prob, 0.0),
    )


def _select_unique_legs(legs: list[dict[str, Any]], limit: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    seen_groups: set[str] = set()
    for leg in sorted(legs, key=_leg_sort_key, reverse=True):
        group = str(leg.get("selection_group") or leg.get("market_type") or leg.get("market_ticker"))
        if group in seen_groups:
            continue
        selected.append(leg)
        seen_groups.add(group)
        if len(selected) >= limit:
            break
    return selected


def build_combo_trade(
    collection_ticker: str,
    market_tickers: list[str],
    custom_stake: float,
    bankroll_snapshot: float | None = None,
) -> dict[str, Any] | None:
    if custom_stake <= 0:
        return None
    requested = [str(ticker).strip() for ticker in market_tickers if str(ticker).strip()]
    if len(requested) < config.COMBO_MIN_LEGS or len(requested) > config.COMBO_MAX_LEGS:
        return None

    board = get_combo_board()
    collection = get_collection_detail(collection_ticker)
    if collection is None:
        return None

    leg_lookup = {str(leg["market_ticker"]): leg for leg in collection["legs"]}
    legs = [leg_lookup[ticker] for ticker in requested if ticker in leg_lookup]
    if len(legs) != len(requested):
        return None

    combo_entry = float(np.prod([float(leg["entry_price"]) for leg in legs]))
    combo_mark = float(np.prod([float(leg["mark_price"]) for leg in legs]))
    combo_model = float(np.prod([float(leg["model_prob"]) for leg in legs]))
    combo_market = float(np.prod([float(leg["market_prob"]) for leg in legs]))

    position = _build_kalshi_position(combo_entry, custom_stake)
    if position is None:
        return None

    stake = float(position["cash_outlay"])
    net_decimal = position["payout_if_win"] / stake
    break_even_prob = 1.0 / net_decimal
    expected_value_per_dollar = (combo_model * net_decimal) - 1.0
    bankroll_value = float(bankroll_snapshot if bankroll_snapshot is not None else custom_stake)

    return {
        "trade_id": _combo_trade_id(collection_ticker, requested),
        "candidate_id": _combo_trade_id(collection_ticker, requested),
        "placed_at": pd.Timestamp.now(),
        "collection_ticker": collection_ticker,
        "combo_label": _combo_label(legs),
        "game_id": str(collection_ticker),
        "tipoff_utc": collection.get("tipoff_utc"),
        "home_team": collection.get("home_team"),
        "away_team": collection.get("away_team"),
        "contract_team": _combo_label(legs),
        "market_source": "kalshi",
        "market_type": "combo",
        "leg_count": len(legs),
        "legs_json": json.dumps(legs),
        "status": "open",
        "model_prob": float(combo_model),
        "market_prob": float(combo_market),
        "quoted_entry_price": float(combo_entry),
        "entry_price": float(combo_entry),
        "current_mark_price": float(combo_mark),
        "entry_slippage": 0.0,
        "break_even_prob": float(break_even_prob),
        "edge": float(combo_model - break_even_prob),
        "expected_value_per_dollar": float(expected_value_per_dollar),
        "expected_profit": float(expected_value_per_dollar * stake),
        "stake": float(stake),
        "bankroll_snapshot": bankroll_value,
        "cash_after_trade": _round_money(max(bankroll_value - stake, 0.0)),
        **position,
    }


def build_best_combo_candidates(bankroll: float) -> pd.DataFrame:
    if bankroll <= 0:
        return pd.DataFrame()

    board = get_combo_board()
    trades: list[dict[str, Any]] = []
    remaining_cash = float(bankroll)

    ranked_collections = sorted(board["collections"], key=lambda row: float(row.get("best_edge", 0.0)), reverse=True)[:4]

    for collection_meta in ranked_collections:
        collection = get_collection_detail(str(collection_meta["collection_ticker"]))
        if collection is None:
            continue
        all_legs = collection["legs"]
        model_legs = [leg for leg in all_legs if leg["market_type"] in {"winner", "spread", "total"}]
        prop_legs = [leg for leg in all_legs if leg["market_type"] in {"points", "rebounds", "assists", "steals", "blocks"}]

        anchors = _select_unique_legs(model_legs, limit=3)
        reliable_props = [leg for leg in prop_legs if float(leg.get("market_prob", 0.0)) >= 0.45]
        reliable_props = _select_unique_legs(reliable_props, limit=8)

        candidate_sets: list[list[str]] = []
        short_base = _select_unique_legs(anchors + reliable_props, limit=3)
        if len(short_base) >= 2:
            candidate_sets.append([str(leg["market_ticker"]) for leg in short_base[: min(3, len(short_base))]])

        long_pool = _select_unique_legs(anchors + reliable_props, limit=config.COMBO_MAX_LEGS)
        for leg_count in [5, 6, 7, 8]:
            if len(long_pool) >= leg_count:
                candidate_sets.append([str(leg["market_ticker"]) for leg in long_pool[:leg_count]])

        seen: set[tuple[str, ...]] = set()
        ranked: list[dict[str, Any]] = []
        for market_tickers in candidate_sets:
            deduped = tuple(sorted(set(market_tickers)))
            if len(deduped) < config.COMBO_MIN_LEGS or deduped in seen:
                continue
            seen.add(deduped)
            trade = build_combo_trade(
                collection_ticker=str(collection["collection_ticker"]),
                market_tickers=list(deduped),
                custom_stake=max(remaining_cash * config.MIN_KELLY_BET, 5.0),
                bankroll_snapshot=remaining_cash,
            )
            if trade is None:
                continue
            ranked.append(trade)

        ranked.sort(
            key=lambda trade: (
                float(trade.get("leg_count", 0.0)),
                float(trade.get("model_prob", 0.0)),
                float(trade.get("payout_if_win", 0.0)),
            ),
            reverse=True,
        )
        trades.extend(ranked[:2])

    if not trades:
        return pd.DataFrame()

    frame = pd.DataFrame(trades)
    frame = frame.drop_duplicates(subset=["trade_id"], keep="first")
    return frame.sort_values(["leg_count", "model_prob", "payout_if_win"], ascending=False).reset_index(drop=True)


def load_combo_trades(log_path: str = config.PAPER_COMBO_TRADES_CSV) -> pd.DataFrame:
    path = Path(log_path)
    if not path.exists():
        return pd.DataFrame()
    trades = pd.read_csv(path)
    for col in ["placed_at", "settled_at", "tipoff_utc"]:
        if col in trades.columns:
            trades[col] = pd.to_datetime(trades[col], errors="coerce", utc=("utc" in col))
    return trades


def append_combo_trades(new_trades: pd.DataFrame, log_path: str = config.PAPER_COMBO_TRADES_CSV) -> pd.DataFrame:
    if new_trades.empty:
        return load_combo_trades(log_path)
    existing = load_combo_trades(log_path)
    combined = pd.concat([existing, new_trades], ignore_index=True) if not existing.empty else new_trades.copy()
    if "trade_id" in combined.columns:
        combined = combined.drop_duplicates(subset=["trade_id"], keep="first")
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(log_path, index=False)
    return combined


def compute_combo_bankroll(
    trades_df: pd.DataFrame,
    starting_bankroll: float = config.PAPER_BANKROLL_START,
) -> dict[str, float]:
    if trades_df.empty:
        return {
            "starting_bankroll": float(starting_bankroll),
            "realized_pnl": 0.0,
            "settled_bankroll": float(starting_bankroll),
            "open_risk": 0.0,
            "available_cash": float(starting_bankroll),
            "live_open_value": 0.0,
            "unrealized_pnl": 0.0,
            "estimated_equity": float(starting_bankroll),
        }

    status = trades_df["status"].fillna("open") if "status" in trades_df.columns else pd.Series("open", index=trades_df.index)
    stake = pd.to_numeric(trades_df.get("stake"), errors="coerce").fillna(0.0)
    pnl = pd.to_numeric(trades_df.get("pnl"), errors="coerce").fillna(0.0)
    current_value = pd.to_numeric(trades_df.get("current_value"), errors="coerce").fillna(stake)
    open_mask = status == "open"

    realized_pnl = float(pnl.sum())
    open_risk = float(stake.loc[open_mask].sum())
    settled_bankroll = float(starting_bankroll + realized_pnl)
    available_cash = float(max(settled_bankroll - open_risk, 0.0))
    live_open_value = float(current_value.loc[open_mask].sum())
    unrealized_pnl = float(live_open_value - stake.loc[open_mask].sum())
    estimated_equity = float(available_cash + live_open_value)

    return {
        "starting_bankroll": float(starting_bankroll),
        "realized_pnl": realized_pnl,
        "settled_bankroll": settled_bankroll,
        "open_risk": open_risk,
        "available_cash": available_cash,
        "live_open_value": live_open_value,
        "unrealized_pnl": unrealized_pnl,
        "estimated_equity": estimated_equity,
    }


def mark_combo_trades_to_market(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return trades_df.copy()
    board = get_combo_board()
    marked = trades_df.copy()
    marked["last_marked_at"] = pd.Timestamp.now()

    for idx, trade in marked.iterrows():
        if str(trade.get("status", "open")) != "open":
            continue
        collection = get_collection_detail(str(trade.get("collection_ticker", "")))
        if not collection:
            continue
        leg_lookup = {str(leg["market_ticker"]): leg for leg in collection["legs"]}
        try:
            stored_legs = json.loads(str(trade.get("legs_json", "[]")))
        except Exception:
            stored_legs = []
        leg_tickers = [str(leg.get("market_ticker", "")) for leg in stored_legs if str(leg.get("market_ticker", "")).strip()]
        active_legs = [leg_lookup[ticker] for ticker in leg_tickers if ticker in leg_lookup]
        if len(active_legs) != len(leg_tickers) or not active_legs:
            continue
        mark_price = float(np.prod([float(leg["mark_price"]) for leg in active_legs]))
        quantity = int(round(_safe_float(trade.get("contracts"))))
        exit_fee = _kalshi_fee_dollars(quantity, mark_price)
        current_value = max((quantity * mark_price) - exit_fee, 0.0)
        stake = _safe_float(trade.get("stake"))
        marked.loc[idx, "current_mark_price"] = mark_price
        marked.loc[idx, "current_exit_fee"] = _round_money(exit_fee)
        marked.loc[idx, "current_value"] = _round_money(current_value)
        marked.loc[idx, "unrealized_pnl"] = _round_money(current_value - stake) if pd.notna(stake) else np.nan

    return marked


def _resolve_combo_leg(leg: dict[str, Any], result_row: pd.Series) -> int | None:
    market_type = str(leg.get("market_type", ""))
    home_pts = _safe_float(result_row.get("home_pts"))
    away_pts = _safe_float(result_row.get("away_pts"))
    if pd.isna(home_pts) or pd.isna(away_pts):
        return None

    if market_type == "winner":
        team_side = str(leg.get("team_side", ""))
        if team_side == "home":
            return int(home_pts > away_pts)
        if team_side == "away":
            return int(away_pts > home_pts)
        return None

    if market_type == "spread":
        threshold = float(leg.get("threshold") or 0.0)
        team_side = str(leg.get("team_side", ""))
        margin = float(home_pts - away_pts)
        if team_side == "home":
            return int(margin > threshold)
        if team_side == "away":
            return int((-margin) > threshold)
        return None

    if market_type == "total":
        threshold = float(leg.get("threshold") or 0.0)
        return int((home_pts + away_pts) > threshold)

    return None


def settle_combo_trades(trades_df: pd.DataFrame, results_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty or results_df.empty:
        return trades_df.copy()
    trades = trades_df.copy()
    results = results_df.copy()
    results_lookup = results.drop_duplicates(subset=["home_team", "away_team"]).set_index(["home_team", "away_team"])

    for idx, trade in trades.iterrows():
        if str(trade.get("status", "open")) != "open":
            continue
        key = (trade.get("home_team"), trade.get("away_team"))
        if key not in results_lookup.index:
            continue
        result_row = results_lookup.loc[key]
        try:
            legs = json.loads(str(trade.get("legs_json", "[]")))
        except Exception:
            legs = []
        if not legs:
            continue
        outcomes = [_resolve_combo_leg(leg, result_row) for leg in legs]
        if any(outcome is None for outcome in outcomes):
            continue
        win = int(all(outcome == 1 for outcome in outcomes))
        payout_if_win = _safe_float(trade.get("payout_if_win"))
        stake = _safe_float(trade.get("stake"))
        realized_payout = payout_if_win if win else 0.0
        pnl = realized_payout - stake
        trades.loc[idx, "status"] = "settled"
        trades.loc[idx, "settled_at"] = pd.Timestamp.now()
        trades.loc[idx, "win"] = win
        trades.loc[idx, "realized_payout"] = _round_money(realized_payout)
        trades.loc[idx, "pnl"] = _round_money(pnl)
        trades.loc[idx, "current_value"] = _round_money(realized_payout)

    return trades


def sync_combo_trades_with_results(
    results_df: pd.DataFrame,
    log_path: str = config.PAPER_COMBO_TRADES_CSV,
) -> pd.DataFrame:
    trades = load_combo_trades(log_path)
    if trades.empty:
        return trades
    marked = mark_combo_trades_to_market(trades)
    settled = settle_combo_trades(marked, results_df)
    settled = enrich_paper_trades_with_clv(settled)
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    settled.to_csv(log_path, index=False)
    return settled
