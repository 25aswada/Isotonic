"""
paper_trading.py - Simulated prediction-market trades for Kalshi.

This module does not place real orders. It logs hypothetical YES positions at the
current executable ask, then settles them to $1.00 on resolution.
"""

from __future__ import annotations

import logging
import math
import os
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
from src.evaluate import kelly_fraction
from src.market_tracking import enrich_paper_trades_with_clv

logger = logging.getLogger(__name__)

MARKET_REFERENCE_COLS = {
    "kalshi": "kalshi_home_prob",
    "polymarket": "polymarket_home_prob",
}

MARKET_EXECUTION_PRICE_COLS = {
    "kalshi": {
        "home": "kalshi_home_ask_prob",
        "away": "kalshi_away_ask_prob",
    },
    "polymarket": {
        "home": "polymarket_home_ask_prob",
        "away": "polymarket_away_ask_prob",
    },
}

MARKET_MARK_PRICE_COLS = {
    "kalshi": {
        "home": "kalshi_home_bid_prob",
        "away": "kalshi_away_bid_prob",
    },
    "polymarket": {
        "home": "polymarket_home_bid_prob",
        "away": "polymarket_away_bid_prob",
    },
}

MARKET_SPREAD_COLS = {
    "kalshi": {
        "home": "kalshi_home_spread_prob",
        "away": "kalshi_away_spread_prob",
    },
    "polymarket": {
        "home": "polymarket_home_spread_prob",
        "away": "polymarket_away_spread_prob",
    },
}

MARKET_FEE_RATE_COLS = {
    "polymarket": {
        "home": "polymarket_home_fee_rate",
        "away": "polymarket_away_fee_rate",
    },
}


def _normalize_sources(sources: Iterable[str] | None) -> list[str]:
    active_sources = {"kalshi"}
    if sources is None:
        return ["kalshi"]
    valid = [s for s in sources if s in MARKET_REFERENCE_COLS and s in active_sources]
    return valid or ["kalshi"]


def _round_money(value: float) -> float:
    return round(float(value) + 1e-12, 2)


def _round_shares(value: float) -> float:
    return round(float(value) + 1e-12, 4)


def _safe_float(value, default: float = np.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _adjust_entry_price(price: float, bid_price: float = np.nan, spread: float = np.nan) -> tuple[float, float]:
    if not (0 < price < 1):
        return np.nan, np.nan

    effective_spread = 0.0
    if pd.notna(spread) and spread > 0:
        effective_spread = float(spread)
    elif pd.notna(bid_price) and 0 < bid_price < price:
        effective_spread = float(price - bid_price)

    slippage = (price * config.PAPER_ENTRY_SLIPPAGE_BPS / 10000.0) + (
        effective_spread * config.PAPER_SPREAD_SLIPPAGE_FRACTION
    )
    return float(min(price + slippage, 0.995)), float(slippage)


def _adjust_exit_price(price: float, spread: float = np.nan) -> tuple[float, float]:
    if not (0 < price < 1):
        return np.nan, np.nan

    effective_spread = float(spread) if pd.notna(spread) and spread > 0 else 0.0
    slippage = (price * config.PAPER_EXIT_SLIPPAGE_BPS / 10000.0) + (
        effective_spread * config.PAPER_SPREAD_SLIPPAGE_FRACTION
    )
    return float(max(price - slippage, 0.005)), float(slippage)


def _annotate_trade_stage(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty:
        return trades_df.copy()

    trades = trades_df.copy()
    if "tipoff_utc" in trades.columns:
        tipoff = pd.to_datetime(trades["tipoff_utc"], errors="coerce", utc=True)
    else:
        tipoff = pd.Series(pd.NaT, index=trades.index, dtype="datetime64[ns, UTC]")
    status = trades["status"].fillna("open") if "status" in trades.columns else pd.Series("open", index=trades.index)
    now_utc = pd.Timestamp.now(tz="UTC")
    trades["trade_stage"] = np.where(
        status == "settled",
        "settled",
        np.where(tipoff.notna() & (tipoff <= now_utc), "live", "pregame"),
    )
    return trades


def _kalshi_fee_dollars(contracts: int, price: float) -> float:
    """
    Kalshi taker fee schedule:
        ceil(0.07 * C * P * (1 - P) * 100) / 100
    where C is contracts and P is the contract price in dollars.
    """
    if contracts <= 0 or not (0 < price < 1):
        return 0.0
    raw_fee = config.KALSHI_TAKER_FEE_RATE * contracts * price * (1.0 - price)
    if raw_fee <= 0:
        return 0.0
    return math.ceil((raw_fee - 1e-12) * 100.0) / 100.0


def _polymarket_fee_exponent(fee_rate: float) -> int:
    """
    Polymarket currently uses exponent 1 for fee-enabled sports markets and 2 for
    fee-enabled crypto markets. NBA markets are currently fee-free, so this only
    applies when the API reports a non-zero fee rate.
    """
    return 2 if fee_rate >= 0.10 else 1


def _polymarket_fee_usdc(gross_shares: float, price: float, fee_rate: float) -> float:
    if gross_shares <= 0 or not (0 < price < 1) or fee_rate <= 0:
        return 0.0

    exponent = _polymarket_fee_exponent(fee_rate)
    raw_fee = gross_shares * price * fee_rate * ((price * (1.0 - price)) ** exponent)
    rounded_fee = round(raw_fee, 4)
    return rounded_fee if rounded_fee >= 0.0001 else 0.0


def _build_kalshi_position(price: float, target_outlay: float) -> dict | None:
    if not (0 < price < 1) or target_outlay <= 0:
        return None

    contracts = int(target_outlay // price)
    while contracts > 0:
        gross_cost = contracts * price
        entry_fee = _kalshi_fee_dollars(contracts, price)
        cash_outlay = _round_money(gross_cost + entry_fee)
        if cash_outlay <= target_outlay + 1e-9:
            payout_if_win = float(contracts)
            return {
                "contracts": int(contracts),
                "gross_shares": float(contracts),
                "net_shares": float(contracts),
                "gross_cost": _round_money(gross_cost),
                "entry_fee": _round_money(entry_fee),
                "cash_outlay": cash_outlay,
                "payout_if_win": payout_if_win,
                "fee_model": "kalshi_taker_fee",
                "fee_rate": np.nan,
            }
        contracts -= 1

    return None


def _build_polymarket_position(price: float, target_outlay: float, fee_rate: float) -> dict | None:
    if not (0 < price < 1) or target_outlay <= 0:
        return None

    cash_outlay = _round_money(target_outlay)
    if cash_outlay <= 0:
        return None

    gross_shares = _round_shares(cash_outlay / price)
    if gross_shares <= 0:
        return None

    entry_fee = _polymarket_fee_usdc(gross_shares, price, fee_rate)
    fee_shares = _round_shares(entry_fee / price) if entry_fee > 0 else 0.0
    net_shares = _round_shares(max(gross_shares - fee_shares, 0.0))
    payout_if_win = float(net_shares)

    if payout_if_win <= 0:
        return None

    return {
        "contracts": np.nan,
        "gross_shares": float(gross_shares),
        "net_shares": float(net_shares),
        "gross_cost": cash_outlay,
        "entry_fee": float(entry_fee),
        "cash_outlay": cash_outlay,
        "payout_if_win": payout_if_win,
        "fee_model": "polymarket_share_fee" if fee_rate > 0 else "none",
        "fee_rate": float(fee_rate),
    }


def _size_position(
    source: str,
    price: float,
    model_prob: float,
    bankroll: float,
    max_stake_pct: float,
    fee_rate: float = 0.0,
) -> dict | None:
    if bankroll <= 0 or not (0 < price < 1) or not (0 < model_prob < 1):
        return None

    rough_decimal = 1.0 / price
    rough_full_kelly = kelly_fraction(model_prob, rough_decimal)
    rough_stake_pct = min(rough_full_kelly * config.KELLY_FRACTION, max_stake_pct)
    if rough_stake_pct < config.MIN_KELLY_BET:
        return None

    target_outlay = bankroll * rough_stake_pct
    position = None

    for _ in range(4):
        if source == "kalshi":
            position = _build_kalshi_position(price, target_outlay)
        elif source == "polymarket":
            position = _build_polymarket_position(price, target_outlay, fee_rate)
        else:
            return None

        if position is None or position["cash_outlay"] <= 0:
            return None

        net_decimal = position["payout_if_win"] / position["cash_outlay"]
        if not np.isfinite(net_decimal) or net_decimal <= 1.0:
            return None

        full_kelly = kelly_fraction(model_prob, net_decimal)
        stake_pct = min(full_kelly * config.KELLY_FRACTION, max_stake_pct)
        if stake_pct < config.MIN_KELLY_BET:
            return None

        new_target_outlay = bankroll * stake_pct
        if abs(new_target_outlay - target_outlay) < 0.01:
            break
        target_outlay = new_target_outlay

    if position is None:
        return None

    net_decimal = position["payout_if_win"] / position["cash_outlay"]
    break_even_prob = 1.0 / net_decimal
    expected_value_per_dollar = (model_prob * net_decimal) - 1.0
    if expected_value_per_dollar <= 0:
        return None

    position.update({
        "entry_decimal": float(net_decimal),
        "break_even_prob": float(break_even_prob),
        "edge": float(model_prob - break_even_prob),
        "kelly_pct": float(min(kelly_fraction(model_prob, net_decimal) * config.KELLY_FRACTION, max_stake_pct)),
        "expected_value_per_dollar": float(expected_value_per_dollar),
        "expected_profit": float(expected_value_per_dollar * position["cash_outlay"]),
        "stake": float(position["cash_outlay"]),
    })
    return position


def load_paper_trades(log_path: str = config.PAPER_TRADES_CSV) -> pd.DataFrame:
    path = Path(log_path)
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)
    for col in ["placed_at", "game_date", "settled_at", "tipoff_utc", "closing_snapshot_at"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=("utc" in col or "snapshot" in col))
    return _annotate_trade_stage(df)


def compute_paper_bankroll(
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
        }

    if "pnl" in trades_df.columns:
        realized_pnl = float(pd.to_numeric(trades_df["pnl"], errors="coerce").fillna(0).sum())
    else:
        realized_pnl = 0.0

    if "status" in trades_df.columns:
        open_mask = trades_df["status"].fillna("open") == "open"
    else:
        open_mask = pd.Series(True, index=trades_df.index)

    open_risk = 0.0
    if "stake" in trades_df.columns:
        open_risk = float(pd.to_numeric(trades_df.loc[open_mask, "stake"], errors="coerce").fillna(0).sum())

    settled_bankroll = float(starting_bankroll + realized_pnl)
    available_cash = float(max(settled_bankroll - open_risk, 0.0))
    return {
        "starting_bankroll": float(starting_bankroll),
        "realized_pnl": realized_pnl,
        "settled_bankroll": settled_bankroll,
        "open_risk": open_risk,
        "available_cash": available_cash,
    }


def _resolve_mark_price(trade_row: pd.Series, live_row: pd.Series | None) -> tuple[float, str]:
    source = trade_row.get("market_source")
    side = trade_row.get("bet_side", "home")

    if live_row is not None and source in MARKET_MARK_PRICE_COLS:
        bid_col = MARKET_MARK_PRICE_COLS[source][side]
        bid_price = _safe_float(live_row.get(bid_col))
        if 0 < bid_price < 1:
            return float(bid_price), "bid"

    if live_row is not None and source in MARKET_REFERENCE_COLS:
        reference_home_prob = _safe_float(live_row.get(MARKET_REFERENCE_COLS[source]))
        if pd.notna(reference_home_prob):
            reference_prob = reference_home_prob if side == "home" else 1.0 - reference_home_prob
            if 0 < reference_prob < 1:
                return float(reference_prob), "reference"

    entry_price = _safe_float(trade_row.get("entry_price"))
    if 0 < entry_price < 1:
        return float(entry_price), "entry"

    return np.nan, "missing"


def _resolve_fee_rate(trade_row: pd.Series, live_row: pd.Series | None) -> float:
    source = trade_row.get("market_source")
    side = trade_row.get("bet_side", "home")

    if live_row is not None and source in MARKET_FEE_RATE_COLS:
        fee_col = MARKET_FEE_RATE_COLS[source][side]
        fee_rate = _safe_float(live_row.get(fee_col))
        if pd.notna(fee_rate) and fee_rate >= 0:
            return float(fee_rate)

    fee_rate = _safe_float(trade_row.get("fee_rate"), default=0.0)
    return float(max(fee_rate, 0.0))


def _mark_to_market_value(
    source: str,
    quantity: float,
    price: float,
    fee_rate: float,
    spread: float = np.nan,
) -> tuple[float, float]:
    if pd.isna(quantity) or quantity <= 0 or not (0 < price < 1):
        return np.nan, np.nan

    effective_exit_price, _ = _adjust_exit_price(price, spread=spread)
    gross_value = quantity * effective_exit_price
    if source == "kalshi":
        exit_fee = _kalshi_fee_dollars(int(round(quantity)), effective_exit_price)
    elif source == "polymarket":
        exit_fee = _polymarket_fee_usdc(quantity, effective_exit_price, fee_rate)
    else:
        exit_fee = 0.0

    current_value = max(gross_value - exit_fee, 0.0)
    return float(current_value), float(exit_fee)


def mark_open_trades_to_market(
    trades_df: pd.DataFrame,
    live_odds_df: pd.DataFrame | None,
) -> pd.DataFrame:
    """
    Mark open trades to current market prices.

    Current value is the estimated liquidation value:
        shares/contracts * current bid - exit fee
    If a live bid is not available, this falls back to the source reference price,
    then to the trade's entry price.
    """
    if trades_df.empty:
        return trades_df.copy()

    marked = trades_df.copy()
    marked["last_marked_at"] = pd.Timestamp.now()

    if live_odds_df is None or live_odds_df.empty:
        live_lookup = {}
    else:
        live_lookup = (
            live_odds_df.drop_duplicates(subset=["home_team", "away_team"])
            .set_index(["home_team", "away_team"])
            .to_dict("index")
        )

    if "status" in marked.columns:
        open_mask = marked["status"].fillna("open") == "open"
    else:
        open_mask = pd.Series(True, index=marked.index)

    for idx, trade_row in marked.loc[open_mask].iterrows():
        live_row = live_lookup.get((trade_row.get("home_team"), trade_row.get("away_team")))
        mark_price, mark_basis = _resolve_mark_price(trade_row, live_row)
        fee_rate = _resolve_fee_rate(trade_row, live_row)
        spread = np.nan
        source = trade_row.get("market_source")
        side = trade_row.get("bet_side", "home")
        if live_row is not None and source in MARKET_SPREAD_COLS:
            spread = _safe_float(live_row.get(MARKET_SPREAD_COLS[source][side]))

        quantity = _safe_float(trade_row.get("payout_if_win"))
        if pd.isna(quantity) or quantity <= 0:
            quantity = _safe_float(trade_row.get("net_shares"))
        if pd.isna(quantity) or quantity <= 0:
            quantity = _safe_float(trade_row.get("contracts"))
        if pd.isna(quantity) or quantity <= 0:
            legacy_stake = _safe_float(trade_row.get("stake"))
            legacy_entry = _safe_float(trade_row.get("entry_price"))
            if legacy_stake > 0 and 0 < legacy_entry < 1:
                quantity = legacy_stake / legacy_entry

        current_value, exit_fee = _mark_to_market_value(
            source=str(trade_row.get("market_source", "")),
            quantity=quantity,
            price=mark_price,
            fee_rate=fee_rate,
            spread=spread,
        )

        stake = _safe_float(trade_row.get("stake"))
        unrealized_pnl = current_value - stake if pd.notna(current_value) and pd.notna(stake) else np.nan
        unrealized_return = (unrealized_pnl / stake) if pd.notna(unrealized_pnl) and stake > 0 else np.nan

        marked.loc[idx, "current_mark_price"] = mark_price
        marked.loc[idx, "mark_basis"] = mark_basis
        marked.loc[idx, "current_mark_spread"] = spread
        marked.loc[idx, "current_exit_fee"] = _round_money(exit_fee) if pd.notna(exit_fee) else np.nan
        marked.loc[idx, "current_value"] = _round_money(current_value) if pd.notna(current_value) else np.nan
        marked.loc[idx, "unrealized_pnl"] = _round_money(unrealized_pnl) if pd.notna(unrealized_pnl) else np.nan
        marked.loc[idx, "unrealized_return"] = float(unrealized_return) if pd.notna(unrealized_return) else np.nan

    return _annotate_trade_stage(marked)


def compute_live_paper_bankroll(
    trades_df: pd.DataFrame,
    starting_bankroll: float = config.PAPER_BANKROLL_START,
) -> dict[str, float]:
    base_state = compute_paper_bankroll(trades_df, starting_bankroll=starting_bankroll)
    if trades_df.empty:
        return {
            **base_state,
            "live_open_value": 0.0,
            "unrealized_pnl": 0.0,
            "estimated_equity": base_state["available_cash"],
        }

    if "status" in trades_df.columns:
        open_mask = trades_df["status"].fillna("open") == "open"
    else:
        open_mask = pd.Series(True, index=trades_df.index)

    open_trades = trades_df.loc[open_mask].copy()
    if open_trades.empty:
        return {
            **base_state,
            "live_open_value": 0.0,
            "unrealized_pnl": 0.0,
            "estimated_equity": base_state["available_cash"],
        }

    stake = pd.to_numeric(open_trades["stake"] if "stake" in open_trades.columns else pd.Series(dtype=float), errors="coerce").fillna(0.0)
    cv_raw = open_trades["current_value"] if "current_value" in open_trades.columns else pd.Series([None]*len(open_trades), index=open_trades.index)
    current_value = pd.to_numeric(cv_raw, errors="coerce")
    current_value = current_value.where(current_value.notna(), stake)

    live_open_value = float(current_value.fillna(0.0).sum())
    unrealized_pnl = float(live_open_value - stake.sum())
    estimated_equity = float(base_state["available_cash"] + live_open_value)

    return {
        **base_state,
        "live_open_value": live_open_value,
        "unrealized_pnl": unrealized_pnl,
        "estimated_equity": estimated_equity,
    }


def build_paper_trade_candidates(
    recommendations_df: pd.DataFrame,
    bankroll: float,
    edge_threshold: float = config.PAPER_TRADE_EDGE,
    sources: Iterable[str] | None = None,
    max_stake_pct: float = config.PAPER_MAX_STAKE_PCT,
) -> pd.DataFrame:
    """
    Build candidate paper trades from live recommendations.

    For each game and market source, this picks the stronger side, then sizes the
    trade using the executable ask plus source-specific fees.
    """
    if recommendations_df.empty or bankroll <= 0:
        return pd.DataFrame()

    allowed_sources = _normalize_sources(sources)
    raw_candidates: list[dict] = []

    for _, rec in recommendations_df.iterrows():
        home_team = rec.get("home_team")
        away_team = rec.get("away_team")
        home_prob = _safe_float(rec.get("home_win_prob"))
        away_prob = _safe_float(rec.get("away_win_prob"), default=1.0 - home_prob if pd.notna(home_prob) else np.nan)
        game_date = pd.to_datetime(rec.get("game_date"), errors="coerce")
        game_id = rec.get(
            "game_id",
            f"{away_team}@{home_team}_{game_date.date() if pd.notna(game_date) else 'unknown'}",
        )

        if pd.isna(home_prob) or pd.isna(away_prob):
            continue

        # Skip games that have already started — in-game prices are unreliable
        # Check 1: game_status from NBA API (1=pregame, 2=live, 3=final)
        game_status = rec.get("game_status")
        if game_status is not None and str(game_status) != "1":
            continue
        # Check 2: tipoff_utc wall-clock guard (backup if game_status missing)
        tipoff = pd.to_datetime(rec.get("tipoff_utc"), errors="coerce", utc=True)
        if pd.notna(tipoff) and tipoff <= pd.Timestamp.now(tz="UTC"):
            continue

        for source in allowed_sources:
            side_options = []
            for side, team, model_prob in [
                ("home", home_team, home_prob),
                ("away", away_team, away_prob),
            ]:
                price_col = MARKET_EXECUTION_PRICE_COLS[source][side]
                quoted_price = _safe_float(rec.get(price_col))
                if not (0 < quoted_price < 1):
                    continue
                bid_col = MARKET_MARK_PRICE_COLS[source][side]
                bid_price = _safe_float(rec.get(bid_col))
                spread_col = MARKET_SPREAD_COLS[source][side]
                spread = _safe_float(rec.get(spread_col))
                price, entry_slippage = _adjust_entry_price(quoted_price, bid_price=bid_price, spread=spread)
                if not (0 < price < 1):
                    continue

                fee_rate = 0.0
                if source in MARKET_FEE_RATE_COLS:
                    fee_col = MARKET_FEE_RATE_COLS[source][side]
                    fee_rate = max(_safe_float(rec.get(fee_col), default=0.0), 0.0)

                reference_home_prob = _safe_float(rec.get(MARKET_REFERENCE_COLS[source]))
                reference_prob = reference_home_prob if side == "home" else (1.0 - reference_home_prob if pd.notna(reference_home_prob) else np.nan)

                side_options.append({
                    "game_id": game_id,
                    "game_date": game_date,
                    "market_source": source,
                    "home_team": home_team,
                    "away_team": away_team,
                    "bet_side": side,
                    "contract_team": team,
                    "model_prob": float(model_prob),
                    "market_prob": float(reference_prob) if pd.notna(reference_prob) else quoted_price,
                    "tipoff_utc": rec.get("tipoff_utc"),
                    "quoted_entry_price": float(quoted_price),
                    "entry_price": float(price),
                    "entry_slippage": float(entry_slippage),
                    "raw_edge": float(model_prob - price),
                    "fee_rate": float(fee_rate),
                })

            if not side_options:
                continue

            best_side = max(side_options, key=lambda row: row["raw_edge"])
            if best_side["raw_edge"] <= 0:
                continue
            raw_candidates.append(best_side)

    if not raw_candidates:
        return pd.DataFrame()

    raw_candidates.sort(key=lambda row: (row["raw_edge"], row["model_prob"]), reverse=True)

    allocated_rows: list[dict] = []
    remaining_cash = float(bankroll)

    for candidate in raw_candidates:
        position = _size_position(
            source=candidate["market_source"],
            price=candidate["entry_price"],
            model_prob=candidate["model_prob"],
            bankroll=remaining_cash,
            max_stake_pct=max_stake_pct,
            fee_rate=candidate["fee_rate"],
        )
        if position is None:
            continue
        if position["edge"] < edge_threshold or position["stake"] <= 0:
            continue

        trade_day = (
            candidate["game_date"].date().isoformat()
            if pd.notna(candidate["game_date"])
            else pd.Timestamp.now().date().isoformat()
        )
        trade_id = (
            f"{trade_day}_{candidate['game_id']}_{candidate['market_source']}_{candidate['bet_side']}"
        )

        remaining_cash = max(remaining_cash - position["stake"], 0.0)

        allocated_rows.append({
            "candidate_id": trade_id,
            "trade_id": trade_id,
            "placed_at": pd.Timestamp.now(),
            "game_id": candidate["game_id"],
            "game_date": candidate["game_date"],
            "tipoff_utc": candidate.get("tipoff_utc"),
            "market_source": candidate["market_source"],
            "home_team": candidate["home_team"],
            "away_team": candidate["away_team"],
            "bet_side": candidate["bet_side"],
            "contract_team": candidate["contract_team"],
            "model_prob": candidate["model_prob"],
            "market_prob": candidate["market_prob"],
            "quoted_entry_price": candidate["quoted_entry_price"],
            "entry_price": candidate["entry_price"],
            "entry_slippage": candidate["entry_slippage"],
            "status": "open",
            "bankroll_snapshot": float(bankroll),
            "cash_after_trade": _round_money(remaining_cash),
            **position,
        })

    if not allocated_rows:
        return pd.DataFrame()

    candidates = pd.DataFrame(allocated_rows)
    candidates = candidates.sort_values(["edge", "expected_value_per_dollar"], ascending=False).reset_index(drop=True)
    return candidates


def append_paper_trades(
    new_trades: pd.DataFrame,
    log_path: str = config.PAPER_TRADES_CSV,
) -> pd.DataFrame:
    if new_trades.empty:
        return load_paper_trades(log_path)

    path = Path(log_path)
    existing = load_paper_trades(log_path)

    if existing.empty:
        combined = new_trades.copy()
    else:
        combined = pd.concat([existing, new_trades], ignore_index=True)
        if "trade_id" in combined.columns:
            combined = combined.drop_duplicates(subset=["trade_id"], keep="first")

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    logger.info("Paper trade log saved to %s (%d rows)", path, len(combined))
    return combined


def settle_paper_trades(
    trades_df: pd.DataFrame,
    results_df: pd.DataFrame,
) -> pd.DataFrame:
    """
    Settle open paper trades against completed game results.
    """
    if trades_df.empty or results_df.empty:
        return trades_df.copy()

    trades = trades_df.copy()
    results = results_df.copy()
    original_cols = set(trades_df.columns)

    trades["game_date"] = pd.to_datetime(trades.get("game_date"), errors="coerce")
    results["game_date"] = pd.to_datetime(results.get("game_date"), errors="coerce")

    actual_cols = [
        c for c in ["game_id", "game_date", "home_team", "away_team", "home_win", "home_pts", "away_pts"]
        if c in results.columns
    ]

    if "game_id" in trades.columns and "game_id" in results.columns:
        lookup = results[actual_cols].drop_duplicates(subset=["game_id"])
        # Normalize game_id: strip leading zeros, compare as strings
        trades["game_id"] = trades["game_id"].astype(str).str.lstrip("0")
        lookup = lookup.copy()
        lookup["game_id"] = lookup["game_id"].astype(str).str.lstrip("0")
        trades = trades.merge(lookup, on="game_id", how="left", suffixes=("", "_actual"))
    else:
        lookup = results[
            [c for c in ["home_team", "away_team", "game_date", "home_win", "home_pts", "away_pts"] if c in results.columns]
        ].copy()
        trades["game_day"] = pd.to_datetime(trades["game_date"]).dt.normalize()
        lookup["game_day"] = pd.to_datetime(lookup["game_date"]).dt.normalize()
        lookup = lookup.drop(columns=["game_date"])
        trades = trades.merge(lookup, on=["home_team", "away_team", "game_day"], how="left", suffixes=("", "_actual"))
        trades = trades.drop(columns=["game_day"])

    home_win_lookup_col = (
        "home_win_actual"
        if "home_win_actual" in trades.columns
        else ("home_win" if "home_win" in trades.columns and "home_win" not in original_cols else None)
    )
    if home_win_lookup_col is None:
        return trades_df.copy()

    if "status" in trades.columns:
        open_mask = trades["status"].fillna("open") == "open"
    else:
        open_mask = pd.Series(True, index=trades.index)
    resolved_mask = open_mask & pd.to_numeric(trades[home_win_lookup_col], errors="coerce").isin([0, 1])

    if not resolved_mask.any():
        return trades_df.copy()

    for col in ["game_date", "home_team", "away_team", "home_pts", "away_pts"]:
        actual_col = f"{col}_actual"
        if actual_col in trades.columns:
            if col in original_cols:
                if col == "game_date":
                    trades[col] = pd.to_datetime(trades[col]).combine_first(pd.to_datetime(trades[actual_col]))
                else:
                    trades[col] = trades[col].combine_first(trades[actual_col])
                trades = trades.drop(columns=[actual_col])
            else:
                trades = trades.rename(columns={actual_col: col})

    if home_win_lookup_col != "home_win":
        trades["home_win"] = pd.to_numeric(trades[home_win_lookup_col], errors="coerce")
    home_win = pd.to_numeric(trades["home_win"], errors="coerce")
    side_is_home = trades["bet_side"].fillna("home") == "home"
    win = np.where(side_is_home, home_win == 1, home_win == 0)

    stake = pd.to_numeric(trades["stake"], errors="coerce")
    payout_if_win = pd.to_numeric(trades.get("payout_if_win"), errors="coerce")

    if payout_if_win.isna().any():
        legacy_price = pd.to_numeric(trades.get("entry_price"), errors="coerce")
        payout_if_win = payout_if_win.fillna(
            pd.Series(np.where(legacy_price > 0, stake / legacy_price, np.nan), index=trades.index)
        )

    realized_payout = np.where(win, payout_if_win, 0.0)
    pnl = realized_payout - stake

    trades.loc[resolved_mask, "status"] = "settled"
    trades.loc[resolved_mask, "settled_at"] = pd.Timestamp.now()
    trades.loc[resolved_mask, "win"] = pd.Series(win, index=trades.index)[resolved_mask].astype(int)
    trades.loc[resolved_mask, "realized_payout"] = pd.Series(realized_payout, index=trades.index)[resolved_mask].round(4)
    trades.loc[resolved_mask, "pnl"] = pd.Series(pnl, index=trades.index)[resolved_mask].round(2)

    drop_cols = [c for c in trades.columns if c.endswith("_actual")]
    return trades.drop(columns=drop_cols)


def sync_paper_trades_with_results(
    results_df: pd.DataFrame,
    log_path: str = config.PAPER_TRADES_CSV,
) -> pd.DataFrame:
    trades = load_paper_trades(log_path)
    if trades.empty:
        return trades

    settled = settle_paper_trades(trades, results_df)
    settled = enrich_paper_trades_with_clv(settled)
    settled = _annotate_trade_stage(settled)
    Path(log_path).parent.mkdir(parents=True, exist_ok=True)
    settled.to_csv(log_path, index=False)
    return settled
