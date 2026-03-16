"""
market_tracking.py - Persist live market snapshots and compute CLV.
"""

from __future__ import annotations

import logging
from pathlib import Path

import numpy as np
import pandas as pd
from pandas.errors import EmptyDataError, ParserError

import config

logger = logging.getLogger(__name__)


def _read_snapshot_csv(path: Path) -> pd.DataFrame:
    """
    Load the market snapshot log defensively.

    Snapshot schema changes over time, and a partially-written row should not
    take down live API endpoints. If the strict parser fails, fall back to the
    Python engine and skip malformed lines.
    """
    if not path.exists():
        return pd.DataFrame()

    try:
        return pd.read_csv(path)
    except (ParserError, EmptyDataError) as exc:
        logger.warning("Market snapshot log is malformed at %s: %s", path, exc)
    except Exception as exc:
        logger.warning("Market snapshot log could not be read at %s: %s", path, exc)
        return pd.DataFrame()

    try:
        recovered = pd.read_csv(path, engine="python", on_bad_lines="skip")
        logger.warning(
            "Recovered %d snapshot rows from malformed log %s using on_bad_lines='skip'",
            len(recovered),
            path,
        )
        return recovered
    except Exception as exc:
        logger.warning("Snapshot recovery failed for %s: %s", path, exc)
        return pd.DataFrame()


def append_market_snapshot(
    odds_df: pd.DataFrame,
    context: str = "live",
    snapshot_path: str = config.MARKET_SNAPSHOTS_CSV,
) -> pd.DataFrame:
    if odds_df.empty:
        return load_market_snapshots(snapshot_path)

    snapshot = odds_df.copy()
    snapshot["snapshot_at"] = pd.Timestamp.now(tz="UTC")
    snapshot["snapshot_context"] = context

    path = Path(snapshot_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    if path.exists():
        existing = _read_snapshot_csv(path)
        if "snapshot_at" in existing.columns:
            existing["snapshot_at"] = pd.to_datetime(existing["snapshot_at"], errors="coerce", utc=True)
        combined = pd.concat([existing, snapshot], ignore_index=True)
    else:
        combined = snapshot

    combined = combined.tail(50_000)
    combined.to_csv(path, index=False)
    return combined


def load_market_snapshots(snapshot_path: str = config.MARKET_SNAPSHOTS_CSV) -> pd.DataFrame:
    path = Path(snapshot_path)
    if not path.exists():
        return pd.DataFrame()

    df = _read_snapshot_csv(path)
    if "snapshot_at" in df.columns:
        df["snapshot_at"] = pd.to_datetime(df["snapshot_at"], errors="coerce", utc=True)
    for col in ["tipoff_utc", "game_date"]:
        if col in df.columns:
            df[col] = pd.to_datetime(df[col], errors="coerce", utc=("utc" in col))
    return df


def _closing_cutoff(row: pd.Series) -> pd.Timestamp | None:
    tipoff = pd.to_datetime(row.get("tipoff_utc"), errors="coerce", utc=True)
    if pd.notna(tipoff):
        return tipoff

    game_date = pd.to_datetime(row.get("game_date"), errors="coerce")
    if pd.notna(game_date):
        return (game_date.normalize() + pd.Timedelta(days=1) - pd.Timedelta(minutes=1)).tz_localize("UTC")
    return None


def _side_price_columns(source: str, side: str) -> tuple[str, str, str]:
    if side == "home":
        return (
            f"{source}_home_prob",
            f"{source}_home_bid_prob",
            f"{source}_home_ask_prob",
        )
    return (
        f"{source}_away_prob",
        f"{source}_away_bid_prob",
        f"{source}_away_ask_prob",
    )


def enrich_paper_trades_with_clv(
    trades_df: pd.DataFrame,
    snapshots_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if trades_df.empty:
        return trades_df.copy()

    snapshots = load_market_snapshots() if snapshots_df is None else snapshots_df.copy()
    if snapshots.empty:
        return trades_df.copy()

    enriched = trades_df.copy()
    for idx, trade in enriched.iterrows():
        source = trade.get("market_source")
        side = trade.get("bet_side", "home")
        if not source:
            continue

        cutoff = _closing_cutoff(trade)
        source_col, bid_col, ask_col = _side_price_columns(source, side)
        if source_col not in snapshots.columns:
            continue

        game_snaps = snapshots[
            (snapshots["home_team"] == trade.get("home_team"))
            & (snapshots["away_team"] == trade.get("away_team"))
        ].copy()
        if cutoff is not None and "snapshot_at" in game_snaps.columns:
            game_snaps = game_snaps[game_snaps["snapshot_at"] <= cutoff]
        if game_snaps.empty:
            continue

        closing = game_snaps.sort_values("snapshot_at").iloc[-1]
        closing_price = pd.to_numeric(closing.get(source_col), errors="coerce")
        closing_bid = pd.to_numeric(closing.get(bid_col), errors="coerce")
        closing_ask = pd.to_numeric(closing.get(ask_col), errors="coerce")
        entry_price = pd.to_numeric(trade.get("entry_price"), errors="coerce")

        enriched.loc[idx, "closing_snapshot_at"] = closing.get("snapshot_at")
        enriched.loc[idx, "closing_price"] = closing_price
        enriched.loc[idx, "closing_bid"] = closing_bid
        enriched.loc[idx, "closing_ask"] = closing_ask
        enriched.loc[idx, "clv"] = closing_price - entry_price if pd.notna(closing_price) and pd.notna(entry_price) else np.nan
        enriched.loc[idx, "clv_bid"] = closing_bid - entry_price if pd.notna(closing_bid) and pd.notna(entry_price) else np.nan
        enriched.loc[idx, "clv_ask"] = closing_ask - entry_price if pd.notna(closing_ask) and pd.notna(entry_price) else np.nan

    return enriched


def enrich_prediction_log_with_clv(
    pred_log_df: pd.DataFrame,
    snapshots_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    if pred_log_df.empty:
        return pred_log_df.copy()

    snapshots = load_market_snapshots() if snapshots_df is None else snapshots_df.copy()
    if snapshots.empty:
        return pred_log_df.copy()

    enriched = pred_log_df.copy()
    for idx, row in enriched.iterrows():
        cutoff = _closing_cutoff(row)
        game_snaps = snapshots[
            (snapshots["home_team"] == row.get("home_team"))
            & (snapshots["away_team"] == row.get("away_team"))
        ].copy()
        if cutoff is not None and "snapshot_at" in game_snaps.columns:
            game_snaps = game_snaps[game_snaps["snapshot_at"] <= cutoff]
        if game_snaps.empty:
            continue

        closing = game_snaps.sort_values("snapshot_at").iloc[-1]
        closing_prob = pd.to_numeric(closing.get("market_home_prob"), errors="coerce")
        entry_prob = pd.to_numeric(row.get("market_home_implied", row.get("market_home_prob")), errors="coerce")
        enriched.loc[idx, "closing_market_home_prob"] = closing_prob
        enriched.loc[idx, "closing_snapshot_at"] = closing.get("snapshot_at")
        enriched.loc[idx, "market_clv"] = closing_prob - entry_prob if pd.notna(closing_prob) and pd.notna(entry_prob) else np.nan

    return enriched
