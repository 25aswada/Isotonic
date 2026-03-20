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
from src.paper_trading import (
    _adjust_exit_price,
    _build_kalshi_position,
    _kalshi_fee_dollars,
    _round_money,
    _safe_float,
)

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

def _iter_live_ncaab_games(payload: dict | None) -> list[dict]:
    if not isinstance(payload, dict):
        return []

    games: list[dict] = []
    for bucket in ("in_progress", "upcoming", "final"):
        bucket_games = payload.get(bucket, [])
        if isinstance(bucket_games, list):
            games.extend(game for game in bucket_games if isinstance(game, dict))
    return games


def _find_live_ncaab_game(payload: dict | None, home_team: str, away_team: str) -> dict | None:
    for game in _iter_live_ncaab_games(payload):
        home_variants = {
            str(value).strip()
            for value in (game.get("home_team"), game.get("home_full_name"))
            if str(value or "").strip()
        }
        away_variants = {
            str(value).strip()
            for value in (game.get("away_team"), game.get("away_full_name"))
            if str(value or "").strip()
        }
        if home_team in home_variants and away_team in away_variants:
            return game
        if home_team in away_variants and away_team in home_variants:
            return game
    return None


def _find_matching_ncaab_market_game(
    odds_df: pd.DataFrame,
    home_team: str,
    away_team: str,
    live_game: dict | None = None,
) -> tuple[pd.Series | None, bool]:
    if odds_df.empty:
        return None, False

    requested_home_variants = {
        str(value).strip()
        for value in (
            home_team,
            live_game.get("home_team") if live_game else None,
            live_game.get("home_full_name") if live_game else None,
        )
        if str(value or "").strip()
    }
    requested_away_variants = {
        str(value).strip()
        for value in (
            away_team,
            live_game.get("away_team") if live_game else None,
            live_game.get("away_full_name") if live_game else None,
        )
        if str(value or "").strip()
    }

    for _, game in odds_df.iterrows():
        market_home = str(game.get("home_team") or "").strip()
        market_away = str(game.get("away_team") or "").strip()
        if not market_home or not market_away:
            continue
        if market_home in requested_home_variants and market_away in requested_away_variants:
            return game, False
        if market_home in requested_away_variants and market_away in requested_home_variants:
            return game, True

    return None, False

def build_custom_ncaab_paper_trade(
    home_team: str,
    away_team: str,
    selected_team: str,
    custom_stake: float,
    market_source: str = "kalshi",
    bankroll_snapshot: float | None = None,
) -> dict | None:
    """
    Build a custom NCAAB paper trade for any team in any game with a custom stake amount.
    
    Args:
        home_team: Home team name
        away_team: Away team name  
        selected_team: Team to bet on (must be either home_team or away_team)
        custom_stake: Custom stake amount in dollars
        market_source: Market source ("kalshi")
        
    Returns:
        Trade dict or None if invalid
    """
    if selected_team not in [home_team, away_team]:
        return None
    if custom_stake <= 0:
        return None
        
    bet_side = "home" if selected_team == home_team else "away"
    
    # Get current market odds
    try:
        from src.ncaab_odds import get_all_ncaab_market_odds
        import requests

        live_payload: dict | None = None
        live_game: dict | None = None
        live_candidate_names: list[str] = []
        try:
            live_response = requests.get("http://127.0.0.1:8000/api/ncaab/live", timeout=5)
            live_response.raise_for_status()
            live_payload = live_response.json()
            live_game = _find_live_ncaab_game(live_payload, home_team, away_team)
            for game in _iter_live_ncaab_games(live_payload):
                for field in ("home_team", "away_team", "home_full_name", "away_full_name"):
                    value = str(game.get(field) or "").strip()
                    if value:
                        live_candidate_names.append(value)
        except Exception:
            live_payload = None
            live_game = None

        odds_df = get_all_ncaab_market_odds(
            record_snapshot=False,
            projected_only=False,
            candidate_names=sorted(set(live_candidate_names)) or None,
        )

        game, teams_flipped = _find_matching_ncaab_market_game(
            odds_df,
            home_team=home_team,
            away_team=away_team,
            live_game=live_game,
        )
        if game is None:
            return None
        
        # Use market probability as model probability for NCAAB (simplified approach)
        market_side = "away" if teams_flipped and bet_side == "home" else "home" if teams_flipped and bet_side == "away" else bet_side
        model_prob = _safe_float(game.get(f"kalshi_{market_side}_prob"))
        if pd.isna(model_prob) or not (0 < model_prob < 1):
            return None
            
        # Get the correct price column
        price_col = MARKET_EXECUTION_PRICE_COLS[market_source][market_side]
        entry_price = _safe_float(game.get(price_col))
        if not (0 < entry_price < 1):
            return None
            
        # Get reference probability
        ref_col = MARKET_REFERENCE_COLS[market_source]
        ref_home_prob = _safe_float(game.get(ref_col))
        if pd.notna(ref_home_prob):
            market_prob = ref_home_prob if market_side == "home" else 1.0 - ref_home_prob
        else:
            market_prob = entry_price
            
        position = _build_kalshi_position(entry_price, custom_stake)
        if position is None:
            return None

        stake = float(position["cash_outlay"])
        entry_decimal = position["payout_if_win"] / stake
        break_even_prob = 1.0 / entry_decimal
        edge = model_prob - break_even_prob
        kelly_pct = max(kelly_fraction(model_prob, entry_decimal) * config.KELLY_FRACTION, 0.0)
        expected_value_per_dollar = (model_prob * entry_decimal) - 1.0
        expected_profit = float(expected_value_per_dollar * stake)
        
        # Build trade record
        game_date = pd.to_datetime(game.get("tipoff_utc"), errors="coerce")
        game_id = f"{away_team}@{home_team}_{game_date.date() if pd.notna(game_date) else 'unknown'}"
        trade_id = f"custom_ncaab_{game_date.date().isoformat() if pd.notna(game_date) else pd.Timestamp.now().date().isoformat()}_{game_id}_{market_source}_{bet_side}"
        bankroll_value = float(bankroll_snapshot if bankroll_snapshot is not None else custom_stake)
        
        return {
            "trade_id": trade_id,
            "placed_at": pd.Timestamp.now(),
            "game_id": game_id,
            "game_date": game_date,
            "tipoff_utc": game.get("tipoff_utc"),
            "market_source": market_source,
            "home_team": home_team,
            "away_team": away_team,
            "bet_side": bet_side,
            "contract_team": selected_team,
            "model_prob": float(model_prob),
            "market_prob": float(market_prob),
            "quoted_entry_price": float(entry_price),
            "entry_price": float(entry_price),
            "entry_slippage": 0.0,
            "entry_decimal": float(entry_decimal),
            "edge": float(edge),
            "kelly_pct": float(max(kelly_pct, 0.0)),
            "stake": float(stake),
            "status": "open",
            "bankroll_snapshot": bankroll_value,
            "expected_profit": float(expected_profit),
            "cash_after_trade": _round_money(max(bankroll_value - stake, 0.0)),
            "break_even_prob": float(break_even_prob),
            "expected_value_per_dollar": float(expected_value_per_dollar),
            **position,
        }
        
    except Exception:
        return None


def mark_open_ncaab_trades_to_market(
    trades_df: pd.DataFrame,
    live_odds_df: pd.DataFrame | None,
) -> pd.DataFrame:
    if trades_df.empty:
        return trades_df.copy()

    marked = trades_df.copy()
    marked["last_marked_at"] = pd.Timestamp.now()

    if live_odds_df is None or live_odds_df.empty:
        live_lookup: dict[tuple[str, str], dict] = {}
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
        side = str(trade_row.get("bet_side", "home") or "home")
        if live_row is not None:
            bid_col = f"kalshi_{side}_bid_prob"
            ask_col = f"kalshi_{side}_ask_prob"
            mark_price = _safe_float(live_row.get(bid_col))
            if not (0 < mark_price < 1):
                mark_price = _safe_float(live_row.get(f"kalshi_{side}_prob"))
            spread = _safe_float(live_row.get(f"kalshi_{side}_spread_prob"))
            if pd.isna(spread):
                ask_price = _safe_float(live_row.get(ask_col))
                if 0 < mark_price < ask_price:
                    spread = ask_price - mark_price
            mark_basis = "bid" if 0 < _safe_float(live_row.get(bid_col)) < 1 else "reference"
        else:
            mark_price = _safe_float(trade_row.get("entry_price"))
            spread = np.nan
            mark_basis = "entry"

        quantity = _safe_float(trade_row.get("payout_if_win"))
        if pd.isna(quantity) or quantity <= 0:
            contracts = _safe_float(trade_row.get("contracts"))
            if contracts > 0:
                quantity = contracts
        if pd.isna(quantity) or quantity <= 0:
            stake = _safe_float(trade_row.get("stake"))
            entry_price = _safe_float(trade_row.get("entry_price"))
            if stake > 0 and 0 < entry_price < 1:
                quantity = stake / entry_price
        if pd.isna(quantity) or quantity <= 0 or not (0 < mark_price < 1):
            continue

        effective_exit_price, _ = _adjust_exit_price(mark_price, spread=spread)
        gross_value = quantity * effective_exit_price
        exit_fee = _kalshi_fee_dollars(int(round(quantity)), effective_exit_price)
        current_value = max(gross_value - exit_fee, 0.0)
        stake = _safe_float(trade_row.get("stake"))
        unrealized_pnl = current_value - stake if pd.notna(stake) else np.nan

        marked.loc[idx, "current_mark_price"] = float(mark_price)
        marked.loc[idx, "mark_basis"] = mark_basis
        marked.loc[idx, "current_mark_spread"] = spread
        marked.loc[idx, "current_exit_fee"] = _round_money(exit_fee)
        marked.loc[idx, "current_value"] = _round_money(current_value)
        marked.loc[idx, "unrealized_pnl"] = _round_money(unrealized_pnl) if pd.notna(unrealized_pnl) else np.nan

    return marked


def build_ncaab_paper_trade_candidates(
    recs_df: pd.DataFrame,
    bankroll: float,
    edge_threshold: float = ncaab_config.EDGE_THRESHOLD,
    sources: Iterable[str] | None = None,
) -> pd.DataFrame:
    """
    Build candidate paper trades from NCAAB recommendations.

    For each game with a valid market price, create a Kalshi
    trade when a valid ask price exists on the recommended side. Size each trade
    with Quarter-Kelly when available, otherwise fall back to a minimum manual stake.
    """
    if recs_df.empty or bankroll <= 0:
        return pd.DataFrame()

    allowed_sources = _normalize_sources(sources)
    max_stake_pct = getattr(config, "PAPER_MAX_STAKE_PCT", 0.10)
    candidates: list[dict] = []

    for _, rec in recs_df.iterrows():
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
            effective_stake_pct = max(kelly_pct, getattr(config, "MIN_KELLY_BET", 0.005))

            stake = _round_money(bankroll * effective_stake_pct)
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
                "kelly_pct": float(max(kelly_pct, 0.0)),
                "stake": float(stake),
                "status": "open",
                "bankroll_snapshot": float(bankroll),
                "expected_profit": float((model_prob * (1.0 / entry_price) - 1.0) * stake),
                "cash_after_trade": _round_money(bankroll - stake),
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
