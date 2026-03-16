"""
auto_paper_trader.py — Background loop that auto-places paper trades on early lines.

Strategy: poll every 15 minutes during active hours (6am-2am).  For every game
with model edge >= AUTO_BET_MIN_EDGE that doesn't already have an open/settled
trade, place a paper trade immediately — capturing soft early lines before sharp
money corrects them.  Tracks minutes_to_tipoff at placement for CLV analysis.
"""
from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timedelta
from typing import Any

import pandas as pd

import config
from src.runtime import setup_project_logging

logger = setup_project_logging(__name__, "auto_paper_trader.log")

_STATE: dict = {
    "last_run":        None,
    "next_run":        None,
    "games_checked":   0,
    "new_bets_placed": 0,
    "last_error":      None,
    "last_message":    None,
    "is_running":      False,
}
_STATE_LOCK   = threading.Lock()

_CONTROL: dict = {
    "enabled":      False,
    "mode":         "armed",
    "min_edge":     float(config.AUTO_BET_MIN_EDGE),
    "sources":      ["kalshi", "polymarket"],
    "poll_seconds": int(config.AUTO_BET_POLL_SECONDS),
    "active_hours": tuple(config.AUTO_BET_ACTIVE_HOURS),
}
_CONTROL_LOCK = threading.Lock()

_loop_started = False
_loop_lock    = threading.Lock()


def _control_snapshot() -> dict:
    with _CONTROL_LOCK:
        return dict(_CONTROL)


def _is_active_hour() -> bool:
    hour = datetime.now().hour
    control = _control_snapshot()
    start, end = control["active_hours"]
    if start < end:
        return start <= hour < end
    return hour >= start or hour < end


def _existing_keys(trades_df: pd.DataFrame) -> set:
    if trades_df.empty:
        return set()
    keys = set()
    for _, row in trades_df.iterrows():
        gid = str(row.get("game_id", ""))
        src = str(row.get("market_source", ""))
        if gid and src:
            keys.add(f"{gid}::{src}")
    return keys


def _minutes_to_tipoff(tipoff_utc):
    tipoff = pd.to_datetime(tipoff_utc, errors="coerce", utc=True)
    if pd.isna(tipoff):
        return None
    delta = (tipoff - pd.Timestamp.now(tz="UTC")).total_seconds() / 60.0
    return round(delta, 1)


def run_auto_bet_cycle(
    *,
    dry_run: bool | None = None,
    min_edge: float | None = None,
    sources: list[str] | None = None,
) -> dict:
    from scripts.daily_predictions import get_todays_features
    from src.odds_collection import get_all_market_odds
    from src.predict import predict_batch, generate_recommendation_table
    from src.paper_trading import (
        append_paper_trades, build_paper_trade_candidates,
        compute_live_paper_bankroll, load_paper_trades,
    )
    _has_injuries = False
    try:
        from src.injuries import apply_live_availability_adjustments
        _has_injuries = True
    except Exception:
        pass

    control = _control_snapshot()
    cycle_dry_run = control["mode"] == "dry-run" if dry_run is None else bool(dry_run)
    edge_threshold = float(control["min_edge"] if min_edge is None else min_edge)
    cycle_sources = list(control["sources"] if sources is None else sources)

    trades = load_paper_trades()
    already_placed = _existing_keys(trades)
    bankroll_state = compute_live_paper_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
    available_cash = bankroll_state["available_cash"]

    if available_cash <= 0:
        logger.info("[auto-bet] No available cash, skipping cycle")
        return {"games_checked": 0, "new_bets_placed": 0, "error": None, "message": "No available cash"}

    features = get_todays_features()
    if features.empty:
        logger.info("[auto-bet] No games today, skipping cycle")
        return {"games_checked": 0, "new_bets_placed": 0, "error": None, "message": "No games today"}

    games_checked = len(features)
    predictions = predict_batch(features)

    if _has_injuries:
        try:
            predictions = apply_live_availability_adjustments(predictions)
        except Exception:
            pass

    odds_df = get_all_market_odds(record_snapshot=False, snapshot_context="auto_bet_cycle")
    recs = generate_recommendation_table(
        predictions,
        odds_df=odds_df if not odds_df.empty else None,
        edge_threshold=edge_threshold,
    )

    if recs.empty:
        logger.info("[auto-bet] No qualifying edges (min edge %.0f%%)", edge_threshold * 100)
        return {"games_checked": games_checked, "new_bets_placed": 0, "error": None, "message": "No qualifying edges"}

    candidates = build_paper_trade_candidates(
        recs, bankroll=available_cash,
        edge_threshold=edge_threshold,
        sources=cycle_sources,
    )

    if candidates.empty:
        return {"games_checked": games_checked, "new_bets_placed": 0, "error": None, "message": "No executable candidates"}

    new_mask = ~candidates.apply(
        lambda r: f"{r['game_id']}::{r['market_source']}", axis=1
    ).isin(already_placed)
    new_trades = candidates[new_mask].copy()

    if new_trades.empty:
        logger.info("[auto-bet] All qualifying bets already placed")
        return {"games_checked": games_checked, "new_bets_placed": 0, "error": None, "message": "All qualifying trades already logged"}

    new_trades["minutes_to_tipoff_at_placement"] = new_trades["tipoff_utc"].apply(_minutes_to_tipoff)
    new_trades["auto_placed"] = True
    new_trades["placed_by"]   = "auto_bet_loop"

    if cycle_dry_run:
        logger.info("[auto-bet] Dry run found %d trade(s) | games: %d | cash: $%.2f",
                    len(new_trades), games_checked, available_cash)
        return {
            "games_checked": games_checked,
            "new_bets_placed": len(new_trades),
            "error": None,
            "message": f"Dry run found {len(new_trades)} trade(s)",
        }

    append_paper_trades(new_trades)
    logger.info("[auto-bet] Placed %d new trade(s) | games: %d | cash: $%.2f",
                len(new_trades), games_checked, available_cash)
    for _, r in new_trades.iterrows():
        mins = r.get("minutes_to_tipoff_at_placement")
        mins_str = f"{mins:.0f} min to tip" if mins is not None else "?"
        logger.info("  -> %s @ %s  side=%s  stake=$%.2f  edge=%.1f%%  (%s)",
                    r.get("home_team"), r.get("away_team"), r.get("bet_side"),
                    r.get("stake", 0), r.get("edge", 0) * 100, mins_str)

    return {
        "games_checked": games_checked,
        "new_bets_placed": len(new_trades),
        "error": None,
        "message": f"Placed {len(new_trades)} new trade(s)",
    }


def _loop_body() -> None:
    while True:
        control = _control_snapshot()
        poll_seconds = int(control["poll_seconds"])

        if not control["enabled"]:
            with _STATE_LOCK:
                _STATE["is_running"] = False
                _STATE["next_run"] = None
        elif _is_active_hour():
            with _STATE_LOCK:
                _STATE["is_running"] = True
            try:
                result = run_auto_bet_cycle(dry_run=control["mode"] == "dry-run")
            except Exception as exc:
                logger.exception("[auto-bet] Unhandled error")
                result = {"games_checked": 0, "new_bets_placed": 0, "error": str(exc), "message": "Auto-trade cycle failed"}

            with _STATE_LOCK:
                _STATE.update({
                    "last_run":        datetime.now().isoformat(),
                    "next_run":        (datetime.now() + timedelta(seconds=poll_seconds)).isoformat(),
                    "games_checked":   result.get("games_checked", 0),
                    "new_bets_placed": result.get("new_bets_placed", 0),
                    "last_error":      result.get("error"),
                    "last_message":    result.get("message"),
                    "is_running":      False,
                })
        else:
            with _STATE_LOCK:
                _STATE["is_running"] = False
                _STATE["next_run"] = (datetime.now() + timedelta(seconds=poll_seconds)).isoformat()

        time.sleep(poll_seconds)


def start_auto_bet_loop() -> None:
    global _loop_started
    with _loop_lock:
        if _loop_started:
            return
        _loop_started = True
    threading.Thread(target=_loop_body, daemon=True, name="bg-auto-bet").start()
    control = _control_snapshot()
    logger.info("[auto-bet] Loop started — poll every %ds, active %02d:00-%02d:00",
                control["poll_seconds"],
                control["active_hours"][0], control["active_hours"][1])


def get_auto_bet_status() -> dict:
    return get_auto_trade_status()


def get_auto_trade_status() -> dict:
    with _STATE_LOCK:
        state = dict(_STATE)
    with _CONTROL_LOCK:
        control = dict(_CONTROL)
    return {
        "available": True,
        "enabled": bool(control["enabled"]),
        "mode": str(control["mode"]),
        "min_edge": float(control["min_edge"]),
        "sources": list(control["sources"]),
        "poll_seconds": int(control["poll_seconds"]),
        "active_hours": tuple(control["active_hours"]),
        **state,
    }


def update_auto_trade(action: str) -> dict:
    normalized = str(action or "").strip().lower()
    if normalized not in {"arm", "pause", "run_dry_cycle"}:
        raise ValueError("Unsupported auto-trade action")

    if normalized == "arm":
        with _CONTROL_LOCK:
            _CONTROL["enabled"] = True
            _CONTROL["mode"] = "armed"
        with _STATE_LOCK:
            _STATE["next_run"] = (datetime.now() + timedelta(seconds=int(_CONTROL["poll_seconds"]))).isoformat()
            _STATE["last_message"] = "Auto trade armed"
        return get_auto_trade_status()

    if normalized == "pause":
        with _CONTROL_LOCK:
            _CONTROL["enabled"] = False
        with _STATE_LOCK:
            _STATE["next_run"] = None
            _STATE["last_message"] = "Auto trade paused"
            _STATE["is_running"] = False
        return get_auto_trade_status()

    with _CONTROL_LOCK:
        _CONTROL["mode"] = "dry-run"
        _CONTROL["enabled"] = False

    result = run_auto_bet_cycle(dry_run=True)
    with _STATE_LOCK:
        _STATE.update({
            "last_run": datetime.now().isoformat(),
            "next_run": None,
            "games_checked": result.get("games_checked", 0),
            "new_bets_placed": result.get("new_bets_placed", 0),
            "last_error": result.get("error"),
            "last_message": result.get("message"),
            "is_running": False,
        })
    return get_auto_trade_status()
