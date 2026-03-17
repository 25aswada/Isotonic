"""
ncaab_paper_trading.py - Simulated prediction-market trades for NCAAB (college basketball).

This module mirrors the NBA paper trading system but is tailored for NCAA basketball
markets on Kalshi. It does not place real orders — it logs hypothetical YES
positions at the current executable ask, then settles them on resolution.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Iterable

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config
import ncaab_config
from src.evaluate import kelly_fraction

logger = logging.getLogger(__name__)
SUPPORTED_PAPER_MARKET_SOURCE = "kalshi"

# ── CSV path for NCAAB paper trades ──────────────────────────────────────────
NCAAB_PAPER_TRADES_CSV = Path("data/ncaab/paper_trades.csv")

# ── Market column mappings ───────────────────────────────────────────────────
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


def _normalize_sources(sources: Iterable[str] | None) -> list[str]:
    active_sources = {SUPPORTED_PAPER_MARKET_SOURCE}
    if sources is None:
        return [SUPPORTED_PAPER_MARKET_SOURCE]
    valid = [s for s in sources if s in MARKET_REFERENCE_COLS and s in active_sources]
    return valid or [SUPPORTED_PAPER_MARKET_SOURCE]


def _filter_supported_trade_sources(trades_df: pd.DataFrame) -> pd.DataFrame:
    if trades_df.empty or "market_source" not in trades_df.columns:
        return trades_df.copy()

    trades = trades_df.copy()
    normalized_source = (
        trades["market_source"]
        .fillna(SUPPORTED_PAPER_MARKET_SOURCE)
        .astype(str)
        .str.strip()
        .str.lower()
        .replace("", SUPPORTED_PAPER_MARKET_SOURCE)
    )
    trades["market_source"] = normalized_source

    filtered = trades.loc[normalized_source == SUPPORTED_PAPER_MARKET_SOURCE].copy()
    removed = len(trades) - len(filtered)
    if removed > 0:
        logger.info("Filtered %d unsupported NCAAB paper trades; keeping %s only", removed, SUPPORTED_PAPER_MARKET_SOURCE)
    return filtered


def _round_money(value: float) -> float:
    return round(float(value) + 1e-12, 2)


def _safe_float(value, default: float = np.nan) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


# ── Load / Save ──────────────────────────────────────────────────────────────

def load_ncaab_paper_trades() -> pd.DataFrame:
    """Load the NCAAB paper trades CSV, returning an empty DataFrame if missing."""
    path = NCAAB_PAPER_TRADES_CSV
    if not path.exists():
        return pd.DataFrame()

    df = pd.read_csv(path)
    df = _filter_supported_trade_sources(df)
    for col in ["placed_at", "game_date", "settled_at", "tipoff_utc"]:
        if col in df.columns:
            df[col] = pd.to_datetime(
                df[col], errors="coerce", utc=("utc" in col),
            )
    return df


def append_ncaab_paper_trades(new_trades: pd.DataFrame) -> None:
    """Append new trades to the NCAAB paper trades CSV, deduplicating by trade_id."""
    if new_trades.empty:
        return

    new_trades = _filter_supported_trade_sources(new_trades)
    if new_trades.empty:
        return

    path = NCAAB_PAPER_TRADES_CSV
    existing = load_ncaab_paper_trades()

    if existing.empty:
        combined = new_trades.copy()
    else:
        combined = pd.concat([existing, new_trades], ignore_index=True)
        if "trade_id" in combined.columns:
            combined = combined.drop_duplicates(subset=["trade_id"], keep="first")
    combined = _filter_supported_trade_sources(combined)

    path.parent.mkdir(parents=True, exist_ok=True)
    combined.to_csv(path, index=False)
    logger.info(
        "NCAAB paper trade log saved to %s (%d rows)", path, len(combined),
    )


# ── Trade construction ───────────────────────────────────────────────────────

def build_ncaab_paper_trade_candidates(
    recs_df: pd.DataFrame,
    bankroll: float,
    edge_threshold: float = ncaab_config.EDGE_THRESHOLD,
    sources: Iterable[str] | None = None,
) -> pd.DataFrame:
    """
    Build candidate paper trades from NCAAB recommendations.

    For each game with bet==True and best_edge >= edge_threshold, create a Kalshi
    trade when a valid ask price exists on the recommended side. Size each trade
    with Quarter-Kelly, capped at 10% of bankroll.
    """
    if recs_df.empty or bankroll <= 0:
        return pd.DataFrame()

    allowed_sources = _normalize_sources(sources)
    max_stake_pct = getattr(config, "PAPER_MAX_STAKE_PCT", 0.10)
    candidates: list[dict] = []

    for _, rec in recs_df.iterrows():
        # Only consider rows flagged as bets with sufficient edge
        if not rec.get("bet", False):
            continue
        best_edge = _safe_float(rec.get("best_edge"), default=0.0)
        if best_edge < edge_threshold:
            continue

        home_team = rec.get("home_team")
        away_team = rec.get("away_team")
        bet_side = rec.get("bet_side", "home")
        contract_team = rec.get("bet_team", home_team if bet_side == "home" else away_team)
        model_prob = _safe_float(rec.get("bet_prob"))
        if pd.isna(model_prob) or not (0 < model_prob < 1):
            continue

        game_date = pd.to_datetime(rec.get("game_date"), errors="coerce")
        game_id = rec.get(
            "game_id",
            f"{away_team}@{home_team}_{game_date.date() if pd.notna(game_date) else 'unknown'}",
        )

        # Skip games that have already started
        tipoff = pd.to_datetime(rec.get("tipoff_utc"), errors="coerce", utc=True)
        if pd.notna(tipoff) and tipoff <= pd.Timestamp.now(tz="UTC"):
            continue

        for source in allowed_sources:
            # Get the executable ask price for this side and source
            price_col = MARKET_EXECUTION_PRICE_COLS.get(source, {}).get(bet_side)
            if price_col is None:
                continue
            entry_price = _safe_float(rec.get(price_col))
            if not (0 < entry_price < 1):
                continue

            # Compute sizing
            entry_decimal = 1.0 / entry_price
            full_kelly = kelly_fraction(model_prob, entry_decimal)
            kelly_pct = full_kelly * config.KELLY_FRACTION
            kelly_pct = min(kelly_pct, max_stake_pct)
            if kelly_pct < getattr(config, "MIN_KELLY_BET", 0.005):
                continue

            stake = _round_money(bankroll * kelly_pct)
            max_stake = _round_money(bankroll * max_stake_pct)
            stake = min(stake, max_stake)
            if stake <= 0:
                continue

            # Reference market probability for this source
            ref_col = MARKET_REFERENCE_COLS.get(source)
            ref_home_prob = _safe_float(rec.get(ref_col)) if ref_col else np.nan
            if pd.notna(ref_home_prob):
                market_prob = ref_home_prob if bet_side == "home" else 1.0 - ref_home_prob
            else:
                market_prob = entry_price

            edge = model_prob - entry_price

            trade_id = f"ncaab_{game_id}_{source}_{bet_side}"

            candidates.append({
                "candidate_id": trade_id,
                "trade_id": trade_id,
                "placed_at": pd.Timestamp.now(),
                "game_id": game_id,
                "game_date": game_date,
                "tipoff_utc": rec.get("tipoff_utc"),
                "market_source": source,
                "home_team": home_team,
                "away_team": away_team,
                "bet_side": bet_side,
                "contract_team": contract_team,
                "model_prob": float(model_prob),
                "market_prob": float(market_prob),
                "entry_price": float(entry_price),
                "entry_decimal": float(entry_decimal),
                "edge": float(edge),
                "kelly_pct": float(kelly_pct),
                "stake": float(stake),
                "status": "open",
                "bankroll_snapshot": float(bankroll),
            })

    if not candidates:
        return pd.DataFrame()

    result = pd.DataFrame(candidates)
    result = (
        result.sort_values(["edge", "model_prob"], ascending=[False, False])
        .reset_index(drop=True)
    )
    return result


# ── Bankroll accounting ──────────────────────────────────────────────────────

def compute_ncaab_paper_bankroll(
    trades_df: pd.DataFrame,
    starting_bankroll: float = config.PAPER_BANKROLL_START,
) -> dict[str, float]:
    """
    Compute current paper bankroll state from the NCAAB trades ledger.

    Returns a dict with:
        starting_bankroll, realized_pnl, settled_bankroll, open_risk,
        available_cash, live_open_value, unrealized_pnl, estimated_equity
    """
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

    # Realized P&L from settled trades
    if "pnl" in trades_df.columns:
        realized_pnl = float(
            pd.to_numeric(trades_df["pnl"], errors="coerce").fillna(0).sum()
        )
    else:
        realized_pnl = 0.0

    # Open-trade risk
    if "status" in trades_df.columns:
        open_mask = trades_df["status"].fillna("open") == "open"
    else:
        open_mask = pd.Series(True, index=trades_df.index)

    if "stake" in trades_df.columns:
        open_risk = float(
            pd.to_numeric(trades_df.loc[open_mask, "stake"], errors="coerce")
            .fillna(0)
            .sum()
        )
    else:
        open_risk = 0.0

    settled_bankroll = float(starting_bankroll + realized_pnl)
    available_cash = float(max(settled_bankroll - open_risk, 0.0))

    # For NCAAB one-off games, open value == stake (no live mark-to-market)
    live_open_value = float(open_risk)
    unrealized_pnl = 0.0
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


# ── Trade settlement ────────────────────────────────────────────────────────

def settle_ncaab_paper_trades(trades_df: pd.DataFrame) -> pd.DataFrame:
    """
    Settle open NCAAB paper trades based on game results.

    A trade is settleable when the ``home_win`` column is populated (1 or 0).
    Win/loss logic:
        win = (bet_side == "home" and home_win == 1) or
              (bet_side == "away" and home_win == 0)
    P&L:
        win  -> pnl = (1/entry_price - 1) * stake   (payout minus cost)
        loss -> pnl = -stake
    """
    if trades_df.empty:
        return trades_df.copy()

    trades = trades_df.copy()

    # Determine which trades are open and have a result
    if "status" in trades.columns:
        open_mask = trades["status"].fillna("open") == "open"
    else:
        open_mask = pd.Series(True, index=trades.index)

    if "home_win" not in trades.columns:
        return trades

    home_win = pd.to_numeric(trades["home_win"], errors="coerce")
    resolved_mask = open_mask & home_win.isin([0, 1])

    if not resolved_mask.any():
        return trades

    # Determine win/loss
    side_is_home = trades["bet_side"].fillna("home") == "home"
    win = np.where(side_is_home, home_win == 1, home_win == 0)

    # Compute P&L
    stake = pd.to_numeric(trades["stake"], errors="coerce")
    entry_price = pd.to_numeric(trades["entry_price"], errors="coerce")
    pnl = np.where(
        win,
        (1.0 / entry_price - 1.0) * stake,  # win: payout - cost
        -stake,                               # loss: lose entire stake
    )

    # Update only resolved rows
    trades.loc[resolved_mask, "status"] = "settled"
    trades.loc[resolved_mask, "settled_at"] = pd.Timestamp.now()
    trades.loc[resolved_mask, "win"] = (
        pd.Series(win, index=trades.index)[resolved_mask].astype(int)
    )
    trades.loc[resolved_mask, "pnl"] = (
        pd.Series(pnl, index=trades.index)[resolved_mask].round(2)
    )

    return trades
