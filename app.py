"""
app.py — Streamlit dashboard for the NBA Prediction Model.

Run with:
    streamlit run app.py
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import date, timedelta
from html import escape
from pathlib import Path

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Page config (must be first Streamlit call) ────────────────────────────────
st.set_page_config(
    layout="wide",
    page_title="NBA Edge",
    page_icon="🏀",
    initial_sidebar_state="expanded",
)

# ── Path setup ────────────────────────────────────────────────────────────────
ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))
import config
from src.ncaab_bracket_viz import BRACKET_CSS, build_bracket_html
from src.runtime import setup_project_logging

# ── Custom CSS ────────────────────────────────────────────────────────────────
st.markdown(
    """
    <style>
    :root {
        --bg: #0d0d0d;
        --panel: #161616;
        --panel-strong: #1c1c1c;
        --line: #2a2a2a;
        --text: #f0f0f0;
        --muted: #888888;
        --accent: #ffffff;
        --accent-soft: rgba(255, 255, 255, 0.06);
        --good: #22c55e;
        --warn: #f59e0b;
        --bad: #ef4444;
        --blue: #3b82f6;
    }

    #MainMenu {visibility: hidden;}
    footer {visibility: hidden;}
    [data-testid="stAppViewContainer"] {
        background: #0d0d0d;
        color: var(--text);
        font-family: "Inter", "Segoe UI", "Helvetica Neue", sans-serif;
    }
    [data-testid="stSidebar"] {
        background: #111111;
        border-right: 1px solid var(--line);
    }
    [data-testid="stSidebar"] section[data-testid="stSidebarContent"] {
        padding-top: 1.5rem;
    }
    [data-testid="stMetric"] {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px 16px;
    }
    [data-testid="stTabs"] [role="tablist"] {
        gap: 4px;
        border-bottom: 1px solid var(--line);
        padding-bottom: 0;
    }
    [data-testid="stTabs"] [role="tab"] {
        border-radius: 6px 6px 0 0;
        background: transparent;
        border: none;
        padding: 8px 16px;
        color: var(--muted);
        font-size: 0.88rem;
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        background: transparent;
        border-bottom: 2px solid var(--text);
        color: var(--text);
        font-weight: 600;
    }
    .stButton > button, .stDownloadButton > button {
        border-radius: 6px;
        border: 1px solid var(--line);
        background: var(--panel);
        color: var(--text);
        font-weight: 500;
        font-size: 0.88rem;
        transition: border-color 0.15s ease;
    }
    .stButton > button:hover, .stDownloadButton > button:hover {
        border-color: #444;
        background: var(--panel-strong);
    }

    .game-card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 18px 22px;
        margin-bottom: 10px;
    }
    .game-card:hover {
        border-color: #3a3a3a;
        transition: border-color 0.15s ease;
    }

    .metric-card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 16px;
        text-align: center;
    }
    .metric-value {
        font-size: 1.75rem;
        font-weight: 700;
        color: var(--text);
    }
    .metric-label {
        font-size: 0.82rem;
        color: var(--muted);
        margin-top: 4px;
        text-transform: uppercase;
        letter-spacing: 0.04em;
    }

    .badge-strong  { background:rgba(34,197,94,0.12);  color:#22c55e; padding:3px 10px; border-radius:4px; font-size:0.78rem; font-weight:600; border:1px solid rgba(34,197,94,0.3); }
    .badge-moderate{ background:rgba(59,130,246,0.12);  color:#60a5fa; padding:3px 10px; border-radius:4px; font-size:0.78rem; font-weight:600; border:1px solid rgba(59,130,246,0.3); }
    .badge-marginal{ background:rgba(245,158,11,0.12);  color:#f59e0b; padding:3px 10px; border-radius:4px; font-size:0.78rem; font-weight:600; border:1px solid rgba(245,158,11,0.3); }
    .badge-nobet   { background:rgba(255,255,255,0.04); color:#6b7280; padding:3px 10px; border-radius:4px; font-size:0.78rem; font-weight:600; border:1px solid #2a2a2a; }

    .section-header {
        font-size: 0.78rem;
        font-weight: 600;
        color: var(--muted);
        border: none;
        padding-left: 0;
        margin: 20px 0 10px 0;
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }

    .summary-banner {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 8px;
        padding: 14px 18px;
        margin-bottom: 18px;
        color: var(--muted);
        font-size: 0.88rem;
        line-height: 1.5;
    }

    h1, h2, h3 { letter-spacing: -0.02em; }
    h2 { font-size: 1.4rem; font-weight: 700; color: var(--text); }

    @keyframes scoreFlash {
        0%   { color: #ffffff; text-shadow: 0 0 20px #22c55e, 0 0 40px #22c55e44; transform: scale(1.12); }
        50%  { color: #ffffff; text-shadow: 0 0 10px #22c55e66; transform: scale(1.06); }
        100% { color: #f0f0f0; text-shadow: none; transform: scale(1); }
    }
    .score-flash {
        animation: scoreFlash 0.7s ease-out forwards;
        display: inline-block;
    }
    /* Prevent gray flash on fragment auto-refresh */
    [data-testid="stFragmentContainer"] { opacity: 1 !important; transition: none !important; }
    [data-stale="true"] { opacity: 1 !important; transition: none !important; }

    .ncaam-hero {
        position: relative;
        overflow: hidden;
        background:
            radial-gradient(circle at 12% 16%, rgba(34,197,94,0.18), transparent 22%),
            radial-gradient(circle at 85% 18%, rgba(59,130,246,0.16), transparent 18%),
            linear-gradient(145deg, rgba(10,12,14,0.96), rgba(16,20,24,0.92));
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 28px;
        padding: 28px 30px 22px;
        margin: 8px 0 20px;
        box-shadow: 0 28px 60px rgba(0,0,0,0.34);
        animation: ncaam-fade-up 0.55s ease both;
    }
    .ncaam-hero::after {
        content: "";
        position: absolute;
        inset: 0;
        background: linear-gradient(120deg, transparent 10%, rgba(255,255,255,0.05) 48%, transparent 78%);
        mix-blend-mode: screen;
        pointer-events: none;
    }
    .ncaam-kicker {
        font-size: 0.74rem;
        letter-spacing: 0.16em;
        text-transform: uppercase;
        color: rgba(255,255,255,0.52);
        margin-bottom: 0.7rem;
    }
    .ncaam-hero-headline {
        display: flex;
        justify-content: space-between;
        gap: 18px;
        align-items: flex-start;
        flex-wrap: wrap;
    }
    .ncaam-hero h1 {
        margin: 0;
        font-size: 2.55rem;
        line-height: 0.96;
        color: #f7fbfa;
        font-family: "SF Pro Display", "Avenir Next", "Segoe UI", sans-serif;
    }
    .ncaam-hero p {
        margin: 0.9rem 0 0 0;
        max-width: 52rem;
        color: rgba(255,255,255,0.72);
        font-size: 0.98rem;
        line-height: 1.65;
    }
    .ncaam-hero-badge {
        display: inline-flex;
        align-items: center;
        gap: 8px;
        padding: 10px 14px;
        border-radius: 999px;
        border: 1px solid rgba(255,255,255,0.08);
        background: rgba(255,255,255,0.04);
        color: rgba(255,255,255,0.82);
        font-size: 0.78rem;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        white-space: nowrap;
    }
    .ncaam-chip-row {
        display: flex;
        flex-wrap: wrap;
        gap: 10px;
        margin-top: 16px;
    }
    .ncaam-chip {
        padding: 8px 12px;
        border-radius: 999px;
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.08);
        color: rgba(255,255,255,0.74);
        font-size: 0.8rem;
    }
    .ncaam-chip strong {
        color: #ffffff;
        font-weight: 700;
    }
    .ncaam-stat-grid {
        display: grid;
        grid-template-columns: repeat(6, minmax(0, 1fr));
        gap: 12px;
        margin-top: 18px;
    }
    .ncaam-stat-card {
        background: linear-gradient(180deg, rgba(255,255,255,0.06), rgba(255,255,255,0.02));
        border: 1px solid rgba(255,255,255,0.07);
        border-radius: 18px;
        padding: 14px 14px 12px;
        backdrop-filter: blur(18px);
    }
    .ncaam-stat-label {
        font-size: 0.7rem;
        text-transform: uppercase;
        letter-spacing: 0.12em;
        color: rgba(255,255,255,0.46);
        margin-bottom: 10px;
    }
    .ncaam-stat-value {
        font-size: 1.28rem;
        font-weight: 800;
        color: #f7fbfa;
        line-height: 1;
    }
    .ncaam-stat-sub {
        margin-top: 8px;
        color: rgba(255,255,255,0.54);
        font-size: 0.78rem;
        line-height: 1.35;
    }
    .ncaam-panel {
        background: linear-gradient(160deg, rgba(255,255,255,0.045), rgba(255,255,255,0.02));
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 22px;
        padding: 18px 20px;
        margin-bottom: 14px;
        animation: ncaam-fade-up 0.55s ease both;
    }
    .ncaam-panel-title {
        font-size: 1rem;
        font-weight: 700;
        color: #f7fbfa;
        margin-bottom: 6px;
    }
    .ncaam-panel-copy {
        color: rgba(255,255,255,0.66);
        font-size: 0.92rem;
        line-height: 1.55;
    }
    .ncaam-picks-grid {
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(220px, 1fr));
        gap: 14px;
        margin: 14px 0 8px;
    }
    .ncaam-pick-card {
        position: relative;
        overflow: hidden;
        background: linear-gradient(180deg, rgba(255,255,255,0.05), rgba(255,255,255,0.025));
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 22px;
        padding: 18px 18px 16px;
        box-shadow: 0 18px 40px rgba(0,0,0,0.18);
    }
    .ncaam-pick-card::before {
        content: "";
        position: absolute;
        inset: 0 auto 0 0;
        width: 4px;
        background: linear-gradient(180deg, #22c55e, #3b82f6);
        opacity: 0.92;
    }
    .ncaam-pick-top {
        display: flex;
        justify-content: space-between;
        gap: 12px;
        align-items: center;
        margin-bottom: 12px;
    }
    .ncaam-pill {
        display: inline-flex;
        align-items: center;
        gap: 6px;
        padding: 6px 10px;
        border-radius: 999px;
        font-size: 0.68rem;
        font-weight: 700;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        background: rgba(34,197,94,0.12);
        border: 1px solid rgba(34,197,94,0.22);
        color: #7ef0a8;
    }
    .ncaam-source {
        color: rgba(255,255,255,0.5);
        font-size: 0.75rem;
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .ncaam-pick-team {
        font-size: 1.4rem;
        font-weight: 800;
        color: #f7fbfa;
        line-height: 1.05;
    }
    .ncaam-pick-matchup {
        color: rgba(255,255,255,0.54);
        font-size: 0.84rem;
        margin-top: 6px;
    }
    .ncaam-pick-metrics {
        display: grid;
        grid-template-columns: repeat(3, minmax(0, 1fr));
        gap: 10px;
        margin-top: 14px;
    }
    .ncaam-pick-metric {
        padding: 10px 10px 8px;
        border-radius: 14px;
        background: rgba(255,255,255,0.04);
        border: 1px solid rgba(255,255,255,0.05);
    }
    .ncaam-pick-metric-label {
        font-size: 0.66rem;
        color: rgba(255,255,255,0.46);
        text-transform: uppercase;
        letter-spacing: 0.1em;
    }
    .ncaam-pick-metric-value {
        margin-top: 6px;
        font-size: 1.02rem;
        font-weight: 800;
        color: #ffffff;
    }
    .ncaam-subgrid {
        display: grid;
        grid-template-columns: repeat(2, minmax(0, 1fr));
        gap: 14px;
        margin-top: 12px;
    }
    @keyframes ncaam-fade-up {
        from { opacity: 0; transform: translateY(12px); }
        to { opacity: 1; transform: translateY(0); }
    }
    @media (max-width: 1180px) {
        .ncaam-stat-grid {
            grid-template-columns: repeat(3, minmax(0, 1fr));
        }
    }
    @media (max-width: 760px) {
        .ncaam-hero h1 {
            font-size: 2rem;
        }
        .ncaam-stat-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
        }
        .ncaam-pick-metrics {
            grid-template-columns: 1fr;
        }
        .ncaam-subgrid {
            grid-template-columns: 1fr;
        }
    }
    """
    + BRACKET_CSS
    + """
    </style>
    """,
    unsafe_allow_html=True,
)

# ── Helpers ───────────────────────────────────────────────────────────────────

logger = setup_project_logging(__name__, "app.log")


def _badge(confidence: str) -> str:
    cls_map = {
        "Strong Edge": "badge-strong",
        "Moderate Edge": "badge-moderate",
        "Marginal": "badge-marginal",
        "No Bet": "badge-nobet",
    }
    cls = cls_map.get(confidence, "badge-nobet")
    return f'<span class="{cls}">{confidence}</span>'


def _availability_copy(prefix: str, row: pd.Series) -> str:
    summary = row.get(f"{prefix}_availability_summary")
    out_count = row.get(f"{prefix}_out_count", 0)
    questionable_count = row.get(f"{prefix}_questionable_count", 0)
    doubtful_count = row.get(f"{prefix}_doubtful_count", 0)
    if pd.isna(summary) or not summary:
        summary = "No major availability flags"
    return (
        f"{summary} | out: {int(out_count or 0)}, "
        f"doubtful: {int(doubtful_count or 0)}, questionable: {int(questionable_count or 0)}"
    )


def _game_story(row: pd.Series) -> list[str]:
    notes: list[str] = []
    home = row.get("home_team", "Home")
    away = row.get("away_team", "Away")
    elo_diff = pd.to_numeric(pd.Series([row.get("elo_diff")]), errors="coerce").iloc[0]
    rest_diff = pd.to_numeric(pd.Series([row.get("rest_diff")]), errors="coerce").iloc[0]
    avail_adj = pd.to_numeric(pd.Series([row.get("availability_adjustment_prob")]), errors="coerce").iloc[0]

    if pd.notna(elo_diff) and abs(elo_diff) >= 40:
        if elo_diff > 0:
            notes.append(f"{home} has the stronger long-run Elo profile.")
        else:
            notes.append(f"{away} has the stronger long-run Elo profile.")

    if pd.notna(rest_diff) and abs(rest_diff) >= 1:
        if rest_diff > 0:
            notes.append(f"{home} comes in with a rest edge of {rest_diff:.0f} day(s).")
        else:
            notes.append(f"{away} comes in with a rest edge of {abs(rest_diff):.0f} day(s).")

    if pd.notna(avail_adj) and abs(avail_adj) >= 0.015:
        direction = home if avail_adj > 0 else away
        notes.append(f"Live availability shifts the probability toward {direction}.")

    return notes[:3] if notes else ["No single factor dominates; this is a blended team-state call."]


def _money(value) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "—" if pd.isna(numeric) else f"${numeric:,.2f}"


def _pct(value, decimals: int = 1) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "—" if pd.isna(numeric) else f"{numeric:.{decimals}%}"


def _prob(value) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    return "—" if pd.isna(numeric) else f"{numeric:.3f}"


def _datetime_label(value) -> str:
    stamp = pd.to_datetime(value, errors="coerce")
    if pd.isna(stamp):
        return "—"
    if stamp.tzinfo is not None:
        stamp = stamp.tz_convert("America/New_York")
    return stamp.strftime("%b %d, %I:%M %p")


def _current_nba_season_label(today: date | None = None) -> str:
    current = today or date.today()
    start_year = current.year if current.month >= 7 else current.year - 1
    end_year = str(start_year + 1)[-2:]
    return f"{start_year}-{end_year}"


def _game_label(row: pd.Series) -> str:
    return f"{row.get('away_team', '?')} @ {row.get('home_team', '?')}"


def _series_or_blank(df: pd.DataFrame, column: str) -> pd.Series:
    if column in df.columns:
        return df[column]
    return pd.Series(index=df.index, dtype=object)


def _to_datetime_mixed(values, utc: bool = False):
    try:
        return pd.to_datetime(values, errors="coerce", format="mixed", utc=utc)
    except TypeError:
        return pd.to_datetime(values, errors="coerce", utc=utc)


def _paper_candidates_view(candidates: pd.DataFrame) -> pd.DataFrame:
    if candidates.empty:
        return candidates.copy()

    view = candidates.copy()
    view["Game"] = view.apply(_game_label, axis=1)
    view["Edge"] = view["edge"].map(lambda value: _pct(value))
    view["Breakeven"] = view["break_even_prob"].map(lambda value: _pct(value))
    view["Quoted Ask"] = view["quoted_entry_price"].map(_prob)
    view["Expected Fill"] = view["entry_price"].map(_prob)
    view["Slippage"] = view["entry_slippage"].map(_prob)
    view["Entry Fee"] = view["entry_fee"].map(_money)
    view["Cash Outlay"] = view["stake"].map(_money)
    view["Payout if Win"] = view["payout_if_win"].map(_money)
    view["Kelly %"] = view["kelly_pct"].map(lambda value: _pct(value))
    view["EV / $1"] = view["expected_value_per_dollar"].map(lambda value: _pct(value))
    return view.rename(columns={
        "trade_id": "Trade ID",
        "market_source": "Market",
        "contract_team": "Team",
    })[[
        "Trade ID", "Market", "Team", "Game", "Edge", "Breakeven", "Quoted Ask",
        "Expected Fill", "Slippage", "Entry Fee", "Cash Outlay", "Payout if Win",
        "Kelly %", "EV / $1",
    ]]


def _open_positions_view(open_positions: pd.DataFrame) -> pd.DataFrame:
    if open_positions.empty:
        return open_positions.copy()

    view = open_positions.copy()
    view["Game"] = view.apply(_game_label, axis=1)
    view["Placed"] = _series_or_blank(view, "placed_at").map(_datetime_label)
    view["Entry"] = _series_or_blank(view, "entry_price").map(_prob)
    view["Live Bid"] = _series_or_blank(view, "current_mark_price").map(_prob)
    view["Entry Fee"] = _series_or_blank(view, "entry_fee").map(_money)
    view["Exit Fee"] = _series_or_blank(view, "current_exit_fee").map(_money)
    view["Stake"] = _series_or_blank(view, "stake").map(_money)
    view["Live Value"] = _series_or_blank(view, "current_value").map(_money)
    view["Live P/L"] = _series_or_blank(view, "unrealized_pnl").map(_money)
    view["Return"] = _series_or_blank(view, "unrealized_return").map(lambda value: _pct(value))
    view["CLV"] = _series_or_blank(view, "clv").map(_prob)
    view["Last Mark"] = _series_or_blank(view, "last_marked_at").map(_datetime_label)
    return view.rename(columns={
        "market_source": "Market",
        "contract_team": "Team",
        "trade_stage": "Stage",
        "mark_basis": "Mark Basis",
    })[[
        "Placed", "Market", "Team", "Game", "Stage", "Entry", "Live Bid", "Stake",
        "Entry Fee", "Exit Fee", "Live Value", "Live P/L", "Return", "Mark Basis",
        "CLV", "Last Mark",
    ]]


def _settled_positions_view(settled_positions: pd.DataFrame) -> pd.DataFrame:
    if settled_positions.empty:
        return settled_positions.copy()

    view = settled_positions.copy()
    view["Game"] = view.apply(_game_label, axis=1)
    view["Settled"] = _series_or_blank(view, "settled_at").map(_datetime_label)
    view["Entry"] = _series_or_blank(view, "entry_price").map(_prob)
    view["Entry Fee"] = _series_or_blank(view, "entry_fee").map(_money)
    view["Stake"] = _series_or_blank(view, "stake").map(_money)
    view["Closing Price"] = _series_or_blank(view, "closing_price").map(_prob)
    view["CLV"] = _series_or_blank(view, "clv").map(_prob)
    view["Payout"] = _series_or_blank(view, "realized_payout").map(_money)
    view["P/L"] = _series_or_blank(view, "pnl").map(_money)
    view["Result"] = _series_or_blank(view, "win").map(lambda value: "Win" if value == 1 else ("Loss" if value == 0 else "—"))
    return view.rename(columns={
        "market_source": "Market",
        "contract_team": "Team",
    })[[
        "Settled", "Market", "Team", "Game", "Entry", "Entry Fee", "Stake",
        "Closing Price", "CLV", "Payout", "P/L", "Result",
    ]]


def _ncaab_market_board_view(recs: pd.DataFrame) -> pd.DataFrame:
    if recs.empty:
        return recs.copy()

    view = recs.copy()
    view["Tipoff"] = _series_or_blank(view, "tipoff_utc").map(_datetime_label)
    view["Matchup"] = view["away_team"].astype(str) + " vs " + view["home_team"].astype(str)
    view["Pick"] = view["bet_team"]
    view["Model"] = view["bet_prob"].map(lambda value: _pct(value))
    view["Market"] = view["bet_market"].map(lambda value: _pct(value))
    view["Edge"] = view["best_edge"].map(lambda value: _pct(value))
    view["Seed Edge"] = _series_or_blank(view, "seed_edge").map(lambda value: _pct(value))
    view["Best Price"] = _series_or_blank(view, "bet_odds_decimal").map(
        lambda value: "—" if pd.isna(pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]) else f"{float(value):.2f}"
    )
    view["Breakeven"] = _series_or_blank(view, "break_even_prob").map(lambda value: _pct(value))
    view["Kelly %"] = _series_or_blank(view, "kelly").map(lambda value: _pct(value))
    view["EV / $1"] = _series_or_blank(view, "expected_value_per_dollar").map(lambda value: _pct(value))
    view["Confidence"] = view["confidence"]
    view["Source"] = _series_or_blank(view, "best_source").fillna("—")
    return view[[
        "Tipoff",
        "Matchup",
        "Pick",
        "Model",
        "Market",
        "Edge",
        "Seed Edge",
        "Best Price",
        "Breakeven",
        "Kelly %",
        "EV / $1",
        "Confidence",
        "Source",
    ]]


def _ncaam_hero_html(
    projection_date: str,
    champion: str,
    champion_prob: float,
    accuracy: float,
    avg_pick_edge: float,
    priced_games: int,
    field_teams: int,
) -> str:
    chips = [
        f"<span class='ncaam-chip'><strong>Projection date</strong> {escape(str(projection_date))}</span>",
        "<span class='ncaam-chip'><strong>Selection Sunday</strong> March 15, 2026</span>",
        "<span class='ncaam-chip'><strong>Model</strong> calibrated blend + live market edge</span>",
    ]
    stats = [
        ("Projected Champion", escape(str(champion)), "Current bracket winner"),
        ("Title Game Win Prob", _pct(champion_prob), "Model title-game confidence"),
        ("Holdout Accuracy", _pct(accuracy), "Historical tournament test split"),
        ("Avg Seed Edge", _pct(avg_pick_edge), "Model vs seed baseline"),
        ("Live Games", str(int(priced_games)), "Projected-field games with prices"),
        ("Field Teams", str(int(field_teams)), "Includes First Four teams"),
    ]
    stat_html = "".join(
        f"<div class='ncaam-stat-card'>"
        f"<div class='ncaam-stat-label'>{label}</div>"
        f"<div class='ncaam-stat-value'>{value}</div>"
        f"<div class='ncaam-stat-sub'>{sub}</div>"
        f"</div>"
        for label, value, sub in stats
    )
    return (
        "<div class='ncaam-hero'>"
        "<div class='ncaam-kicker'>NCAAM Tournament Lab</div>"
        "<div class='ncaam-hero-headline'>"
        "<div>"
        "<h1>Bracket intelligence with a Cursor-grade polish.</h1>"
        "<p>Projected-field probabilities, market dislocations, a live bracket builder, and matchup detail in one clean dark workspace.</p>"
        "</div>"
        "<div class='ncaam-hero-badge'>Selection Sunday · Mar 15</div>"
        "</div>"
        f"<div class='ncaam-chip-row'>{''.join(chips)}</div>"
        f"<div class='ncaam-stat-grid'>{stat_html}</div>"
        "</div>"
    )


def _ncaam_panel_html(title: str, copy: str) -> str:
    return (
        "<div class='ncaam-panel'>"
        f"<div class='ncaam-panel-title'>{escape(title)}</div>"
        f"<div class='ncaam-panel-copy'>{escape(copy)}</div>"
        "</div>"
    )


def _ncaam_pick_cards_html(recs: pd.DataFrame, max_cards: int = 4) -> str:
    if recs.empty:
        return _ncaam_panel_html(
            "No current value bets",
            "No NCAA prices clear the current edge and minimum-win-probability thresholds right now.",
        )

    cards: list[str] = []
    top = recs.sort_values(["best_edge", "bet_prob"], ascending=False).head(max_cards)
    for _, row in top.iterrows():
        cards.append(
            "<div class='ncaam-pick-card'>"
            "<div class='ncaam-pick-top'>"
            f"<span class='ncaam-pill'>{escape(str(row.get('confidence', 'Edge')))}</span>"
            f"<span class='ncaam-source'>{escape(str(row.get('best_source', 'market')))}</span>"
            "</div>"
            f"<div class='ncaam-pick-team'>{escape(str(row.get('bet_team', '—')))}</div>"
            f"<div class='ncaam-pick-matchup'>{escape(str(row.get('away_team', '—')))} vs {escape(str(row.get('home_team', '—')))}</div>"
            "<div class='ncaam-pick-metrics'>"
            f"<div class='ncaam-pick-metric'><div class='ncaam-pick-metric-label'>Model</div><div class='ncaam-pick-metric-value'>{_pct(row.get('bet_prob'))}</div></div>"
            f"<div class='ncaam-pick-metric'><div class='ncaam-pick-metric-label'>Market</div><div class='ncaam-pick-metric-value'>{_pct(row.get('bet_market'))}</div></div>"
            f"<div class='ncaam-pick-metric'><div class='ncaam-pick-metric-label'>Edge</div><div class='ncaam-pick-metric-value'>{_pct(row.get('best_edge'))}</div></div>"
            "</div>"
            "<div class='ncaam-pick-metrics'>"
            f"<div class='ncaam-pick-metric'><div class='ncaam-pick-metric-label'>Kelly</div><div class='ncaam-pick-metric-value'>{_pct(row.get('kelly'))}</div></div>"
            f"<div class='ncaam-pick-metric'><div class='ncaam-pick-metric-label'>Seed Edge</div><div class='ncaam-pick-metric-value'>{_pct(row.get('seed_edge'))}</div></div>"
            f"<div class='ncaam-pick-metric'><div class='ncaam-pick-metric-label'>Best Price</div><div class='ncaam-pick-metric-value'>{'—' if pd.isna(pd.to_numeric(pd.Series([row.get('bet_odds_decimal')]), errors='coerce').iloc[0]) else f'{float(row.get('bet_odds_decimal')):.2f}'}</div></div>"
            "</div>"
            "</div>"
        )
    return f"<div class='ncaam-picks-grid'>{''.join(cards)}</div>"


@st.cache_data(ttl=300)
def load_model_ready() -> pd.DataFrame:
    path = ROOT / config.MODEL_READY_CSV
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    df["game_date"] = _to_datetime_mixed(df["game_date"])
    return df


@st.cache_data(ttl=300)
def load_prediction_log() -> pd.DataFrame:
    path = ROOT / config.PREDICTION_LOG
    if not path.exists():
        return pd.DataFrame()
    df = pd.read_csv(path)
    if "game_date" in df.columns:
        df["game_date"] = _to_datetime_mixed(df["game_date"])
    for col in [
        "tipoff_utc",
        "tipoff_et",
        "logged_at",
        "home_report_timestamp",
        "away_report_timestamp",
        "availability_report_timestamp",
        "closing_snapshot_at",
    ]:
        if col in df.columns:
            df[col] = _to_datetime_mixed(
                df[col],
                utc=(col.endswith("_utc") or "timestamp" in col or col == "logged_at"),
            )
    return df


@st.cache_data(ttl=300)
def load_market_snapshots_df() -> pd.DataFrame:
    from src.market_tracking import load_market_snapshots
    return load_market_snapshots()


@st.cache_data(ttl=300)
def load_alerts_df() -> pd.DataFrame:
    from src.monitoring import load_alerts
    return load_alerts()


@st.cache_data(ttl=300)
def load_elo_history() -> pd.DataFrame:
    path = ROOT / config.ELO_CSV
    if not path.exists():
        return pd.DataFrame()
    return pd.read_csv(path)


@st.cache_resource
def load_trained_model():
    """Load the trained calibrated model. Returns None if not trained yet."""
    try:
        from src.model import load_model
        return load_model()
    except Exception:
        return None, None, None


@st.cache_data(ttl=3600)
def load_ncaab_metrics() -> dict:
    import ncaab_config

    path = ROOT / ncaab_config.NCAAB_METRICS_JSON
    if not path.exists():
        return {}
    return json.loads(path.read_text())


@st.cache_data(ttl=3600)
def load_ncaab_team_features_df() -> pd.DataFrame:
    import ncaab_config

    def enrich_current_features(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df

        enriched = df.copy()
        if "net_rank" not in enriched.columns and "median_rank" in enriched.columns:
            enriched["net_rank"] = enriched["median_rank"]
        if "srs_rank" not in enriched.columns and "srs" in enriched.columns:
            enriched["srs_rank"] = pd.to_numeric(enriched["srs"], errors="coerce").rank(method="min", ascending=False)
        if "efficiency_rank" not in enriched.columns and "net_rtg" in enriched.columns:
            enriched["efficiency_rank"] = pd.to_numeric(enriched["net_rtg"], errors="coerce").rank(method="min", ascending=False)
        if {"net_rank", "srs_rank", "efficiency_rank"}.issubset(enriched.columns):
            rank_frame = enriched[["net_rank", "srs_rank", "efficiency_rank"]].apply(pd.to_numeric, errors="coerce")
            if "median_rank" not in enriched.columns or enriched["median_rank"].isna().any():
                enriched["median_rank"] = rank_frame.median(axis=1)
            if "best_rank" not in enriched.columns or enriched["best_rank"].isna().any():
                enriched["best_rank"] = rank_frame.min(axis=1)

        margin_scale = max(float(pd.to_numeric(enriched.get("avg_margin"), errors="coerce").abs().quantile(0.9)), 1.0)
        def_rank_pct = pd.to_numeric(enriched.get("def_rtg"), errors="coerce").rank(method="average", pct=True, ascending=True)
        if "elo" not in enriched.columns:
            enriched["elo"] = np.nan
        enriched["elo"] = pd.to_numeric(enriched["elo"], errors="coerce").fillna(
            1500.0
            + 12.0 * pd.to_numeric(enriched.get("net_rtg"), errors="coerce")
            + 200.0 * (pd.to_numeric(enriched.get("win_pct"), errors="coerce") - 0.5)
        )
        if "last10_win_pct" not in enriched.columns:
            enriched["last10_win_pct"] = np.nan
        enriched["last10_win_pct"] = pd.to_numeric(enriched["last10_win_pct"], errors="coerce").fillna(
            np.clip(
                pd.to_numeric(enriched.get("win_pct"), errors="coerce")
                + 0.08 * (pd.to_numeric(enriched.get("avg_margin"), errors="coerce") / margin_scale),
                0.0,
                1.0,
            )
        )
        if "last10_margin" not in enriched.columns:
            enriched["last10_margin"] = np.nan
        enriched["last10_margin"] = pd.to_numeric(enriched["last10_margin"], errors="coerce").fillna(
            0.6 * pd.to_numeric(enriched.get("avg_margin"), errors="coerce")
            + 0.4 * pd.to_numeric(enriched.get("net_rtg"), errors="coerce")
        )
        if "opp_efg" not in enriched.columns:
            enriched["opp_efg"] = np.nan
        enriched["opp_efg"] = pd.to_numeric(enriched["opp_efg"], errors="coerce").fillna(0.44 + 0.12 * def_rank_pct)
        return enriched

    current_path = ROOT / ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV
    if current_path.exists():
        return enrich_current_features(pd.read_csv(current_path))
    return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_ncaab_projection_meta() -> dict:
    import ncaab_config

    path = ROOT / ncaab_config.NCAAB_CURRENT_META_JSON
    if not path.exists():
        return {}
    return json.loads(path.read_text())


@st.cache_data(ttl=3600)
def load_ncaab_bracket_df() -> pd.DataFrame:
    import ncaab_config
    from src.ncaab_live import simulate_projected_bracket

    current_path = ROOT / ncaab_config.NCAAB_CURRENT_PROJECTED_BRACKET_CSV
    if current_path.exists():
        bracket = pd.read_csv(current_path)
        if {"winner_seed_edge", "seed_baseline_prob"}.issubset(bracket.columns):
            return bracket
        meta = load_ncaab_projection_meta()
        if not load_ncaab_team_features_df().empty and meta:
            return simulate_projected_bracket(load_ncaab_team_features_df(), meta)
        return bracket
    return pd.DataFrame()


@st.cache_data(ttl=3600)
def load_ncaab_seed_baselines_df() -> pd.DataFrame:
    from src.ncaab_predict import load_seed_matchup_baselines

    return load_seed_matchup_baselines()


@st.cache_resource
def load_ncaab_model_bundle():
    try:
        from src.ncaab_model import load_model

        return load_model()
    except Exception:
        return None, None, None


@st.cache_data(ttl=300)
def load_ncaab_market_odds_df() -> pd.DataFrame:
    from src.ncaab_odds import get_all_ncaab_market_odds

    odds = get_all_ncaab_market_odds(snapshot_context="streamlit_ncaab")
    if odds.empty:
        return odds
    if "tipoff_utc" in odds.columns:
        odds["tipoff_utc"] = _to_datetime_mixed(odds["tipoff_utc"], utc=True)
    return odds


@st.cache_data(ttl=300)
def load_ncaab_market_recommendations_df() -> pd.DataFrame:
    from src.ncaab_predict import generate_market_recommendation_table, predict_market_games

    odds = load_ncaab_market_odds_df()
    if odds.empty:
        return pd.DataFrame()

    predictions = predict_market_games(
        odds,
        team_features=load_ncaab_team_features_df(),
        model_bundle=load_ncaab_model_bundle(),
        seed_baselines=load_ncaab_seed_baselines_df(),
    )
    if predictions.empty:
        return pd.DataFrame()

    recs = generate_market_recommendation_table(predictions, odds_df=odds)
    if "tipoff_utc" in recs.columns:
        recs["tipoff_utc"] = _to_datetime_mixed(recs["tipoff_utc"], utc=True)
    return recs


def _ncaab_require_artifacts() -> bool:
    import ncaab_config

    missing = [
        path
        for path in [
            ROOT / ncaab_config.NCAAB_METRICS_JSON,
            ROOT / (ncaab_config.NCAAB_MODEL_DIR / "calibrated_model.joblib"),
            ROOT / ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV,
            ROOT / ncaab_config.NCAAB_CURRENT_META_JSON,
        ]
        if not path.exists()
    ]
    if missing:
        st.warning(
            "NCAA artifacts are missing. Run `python scripts/build_ncaab_dataset.py`, "
            "`python scripts/train_ncaab.py`, and `python scripts/update_ncaab_current.py`.",
            icon="🏀",
        )
        return False
    return True


def _ncaab_round_order(round_name: str) -> int:
    return {
        "First Four": 0,
        "Round of 64": 1,
        "Round of 32": 2,
        "Sweet 16": 3,
        "Elite 8": 4,
        "Final Four": 5,
        "National Championship": 6,
    }.get(str(round_name), 99)


def _ncaab_feature_story(prediction: dict, row: pd.Series) -> list[str]:
    notes: list[str] = []
    team_a = prediction["team_a_name"]
    team_b = prediction["team_b_name"]

    seed_diff = pd.to_numeric(pd.Series([row.get("seed_num_diff")]), errors="coerce").iloc[0]
    elo_diff = pd.to_numeric(pd.Series([row.get("elo_diff")]), errors="coerce").iloc[0]
    net_diff = pd.to_numeric(pd.Series([row.get("net_rtg_diff")]), errors="coerce").iloc[0]
    rank_diff = pd.to_numeric(pd.Series([row.get("median_rank_diff")]), errors="coerce").iloc[0]
    form_diff = pd.to_numeric(pd.Series([row.get("last10_win_pct_diff")]), errors="coerce").iloc[0]
    margin_diff = pd.to_numeric(pd.Series([row.get("last10_margin_diff")]), errors="coerce").iloc[0]
    seed_edge = max(abs(prediction.get("team_a_seed_edge", 0.0)), abs(prediction.get("team_b_seed_edge", 0.0)))

    if pd.notna(seed_diff) and abs(seed_diff) >= 2:
        favorite = team_a if seed_diff < 0 else team_b
        notes.append(f"{favorite} owns the stronger projected seed line.")
    if pd.notna(elo_diff) and abs(elo_diff) >= 35:
        favorite = team_a if elo_diff > 0 else team_b
        notes.append(f"{favorite} has the better NCAA Elo-style strength profile.")
    if pd.notna(net_diff) and abs(net_diff) >= 4:
        favorite = team_a if net_diff > 0 else team_b
        notes.append(f"{favorite} carries the stronger full-season efficiency margin.")
    if pd.notna(rank_diff) and abs(rank_diff) >= 10:
        favorite = team_a if rank_diff < 0 else team_b
        notes.append(f"{favorite} grades better across current ranking inputs.")
    if pd.notna(form_diff) and abs(form_diff) >= 0.10:
        favorite = team_a if form_diff > 0 else team_b
        notes.append(f"{favorite} has been stronger over the last 10 games.")
    elif pd.notna(margin_diff) and abs(margin_diff) >= 4:
        favorite = team_a if margin_diff > 0 else team_b
        notes.append(f"{favorite} brings the better recent scoring-margin form.")
    if seed_edge >= 0.08:
        notes.append("This call is materially stronger than the usual historical seed expectation.")

    return notes[:4] if notes else ["This matchup is close; no single NCAA signal dominates the call."]


def _ncaab_edge_label(edge: float) -> str:
    if edge >= 0.10:
        return "Major Seed Edge"
    if edge >= 0.05:
        return "Solid Seed Edge"
    if edge <= -0.05:
        return "Below Seed Expectation"
    return "Near Seed Expectation"


def settle_prediction_log(pred_log: pd.DataFrame, results_df: pd.DataFrame) -> pd.DataFrame:
    """Attach actual game outcomes to logged predictions when results are available."""
    if pred_log.empty or results_df.empty:
        return pred_log

    settled = pred_log.copy()
    results = results_df.copy()
    if "game_date" in settled.columns:
        settled["game_date"] = _to_datetime_mixed(settled["game_date"])
    if "game_date" in results.columns:
        results["game_date"] = _to_datetime_mixed(results["game_date"])

    actual_cols = [c for c in ["game_id", "game_date", "home_team", "away_team", "home_win", "home_pts", "away_pts"] if c in results.columns]

    if "game_id" in settled.columns and "game_id" in results.columns:
        lookup = results[actual_cols].drop_duplicates(subset=["game_id"])
        settled = settled.merge(lookup, on="game_id", how="left", suffixes=("", "_actual"))
    elif {"home_team", "away_team", "game_date"}.issubset(settled.columns) and {"home_team", "away_team", "game_date"}.issubset(results.columns):
        lookup = results[[c for c in ["home_team", "away_team", "game_date", "home_win", "home_pts", "away_pts"] if c in results.columns]].copy()
        settled["game_day"] = settled["game_date"].dt.normalize()
        lookup["game_day"] = lookup["game_date"].dt.normalize()
        lookup = lookup.drop(columns=["game_date"])
        settled = settled.merge(lookup, on=["home_team", "away_team", "game_day"], how="left", suffixes=("", "_actual"))
        settled = settled.drop(columns=["game_day"])

    for col in ["game_date", "home_win", "home_pts", "away_pts"]:
        actual_col = f"{col}_actual"
        if actual_col not in settled.columns:
            continue
        if col in settled.columns:
            if col == "game_date":
                settled[col] = _to_datetime_mixed(settled[col]).combine_first(_to_datetime_mixed(settled[actual_col]))
            else:
                settled[col] = settled[col].combine_first(settled[actual_col])
            settled = settled.drop(columns=[actual_col])
        else:
            settled = settled.rename(columns={actual_col: col})

    if "market_home_implied" not in settled.columns and "market_home_prob" in settled.columns:
        settled["market_home_implied"] = settled["market_home_prob"]

    if "home_odds_decimal" not in settled.columns:
        settled["home_odds_decimal"] = np.nan

    if "market_home_implied" in settled.columns:
        implied = pd.to_numeric(settled["market_home_implied"], errors="coerce")
    else:
        implied = pd.Series(np.nan, index=settled.index)
    settled["home_odds_decimal"] = pd.to_numeric(settled["home_odds_decimal"], errors="coerce")
    settled["home_odds_decimal"] = settled["home_odds_decimal"].fillna(
        pd.Series(np.where(implied > 0, 1.0 / implied, np.nan), index=settled.index)
    )

    if "home_win" in settled.columns:
        settled["flat_pnl"] = np.where(
            settled["home_win"] == 1,
            settled["home_odds_decimal"] - 1.0,
            np.where(settled["home_win"] == 0, -1.0, np.nan),
        )

    try:
        from src.market_tracking import enrich_prediction_log_with_clv
        settled = enrich_prediction_log_with_clv(settled, snapshots_df=load_market_snapshots_df())
    except Exception:
        logger.exception("Failed to enrich prediction log with CLV")

    return settled


def data_missing_warning(msg: str = "Dataset not built yet.") -> None:
    st.warning(
        f"⚠️ {msg} Run `python scripts/build_dataset.py` to collect data, "
        "then `python scripts/train.py` to train the model.",
        icon="⚠️",
    )


# ─────────────────────────────────────────────────────────────────────────────
# Sidebar navigation
# ─────────────────────────────────────────────────────────────────────────────

with st.sidebar:
    st.markdown("# 🏀 NBA Edge")
    st.markdown("---")
    _pages = ["Today's Picks", "Live Games", "NBA Matchup", "Paper Trader", "Model Accuracy", "Team Explorer", "Bet Tracker", "NCAAM", "System"]
    _qp = st.query_params.get("page", "Today's Picks")
    _default_idx = _pages.index(_qp) if _qp in _pages else 0
    page = st.radio(
        "Navigate",
        _pages,
        index=_default_idx,
        label_visibility="collapsed",
        key="nav_page",
    )
    st.query_params["page"] = page
    st.markdown("---")
    sidebar_copy = (
        "March Madness model + projected bracket<br>for Selection Sunday prep"
        if page == "NCAAM"
        else "AI-powered NBA predictions for<br>Kalshi & Polymarket trading"
    )
    st.markdown(f"<small style='color:#555'>{sidebar_copy}</small>", unsafe_allow_html=True)


# ─────────────────────────────────────────────────────────────────────────────
# Page 1: Today's Picks
# ─────────────────────────────────────────────────────────────────────────────

def page_todays_picks() -> None:
    st.markdown(f"## Today's Picks — {date.today().strftime('%B %d, %Y')}")
    st.markdown(
        """
        <div class="summary-banner">
            Start with <strong>Best Value Bets</strong> to see where our model disagrees most with the market — those are your highest-edge opportunities.
            Use <strong>Favorites to Win</strong> when you just want the most likely outcome. Injury reports are factored in automatically when the official NBA report is available.
        </div>
        """,
        unsafe_allow_html=True,
    )

    col_refresh, col_info = st.columns([1, 5])
    with col_refresh:
        if st.button("🔄 Refresh Data", use_container_width=True):
            st.cache_data.clear()
            st.rerun()

    model_data = load_trained_model()
    model_loaded = model_data[0] is not None

    if not model_loaded:
        data_missing_warning("Model not trained yet.")
        st.markdown("### Quick-start guide")
        st.code(
            "# 1. Collect data (30–60 min)\n"
            "python scripts/build_dataset.py\n\n"
            "# 2. Train model (~5 min)\n"
            "python scripts/train.py\n\n"
            "# 3. Run daily predictions\n"
            "python scripts/daily_predictions.py",
            language="bash",
        )
        return

    with st.spinner("Pulling today's games, Kalshi & Polymarket prices..."):
        try:
            from src.injuries import apply_live_availability_adjustments
            from src.odds_collection import get_all_market_odds
            from scripts.daily_predictions import get_todays_features
            from src.predict import predict_batch, generate_recommendation_table

            features = get_todays_features()
            all_odds = get_all_market_odds(snapshot_context="streamlit_todays_picks")

            if features.empty:
                st.info("No NBA games scheduled for today.", icon="🏀")
                return

            predictions = predict_batch(features)
            predictions = apply_live_availability_adjustments(
                predictions,
                report_date=predictions["game_date"].iloc[0] if "game_date" in predictions.columns and not predictions.empty else None,
            )
            recs = generate_recommendation_table(predictions, odds_df=all_odds, edge_threshold=0.03)
            if recs.empty:
                st.info("No predictions available for today's slate.", icon="🏀")
                return

            # Drop games that have already tipped off
            if "tipoff_utc" in recs.columns:
                now_utc = pd.Timestamp.now(tz="UTC")
                recs = recs[
                    recs["tipoff_utc"].isna() |
                    (pd.to_datetime(recs["tipoff_utc"], utc=True) > now_utc)
                ].copy()
            # Also drop by game_status if available
            if "game_status" in recs.columns:
                recs = recs[recs["game_status"].isna() | (recs["game_status"] == 1)].copy()

            if recs.empty:
                st.info("All of today's games have already started or finished.", icon="🏀")
                return

        except Exception as e:
            st.error(f"Error generating predictions: {e}")
            logger.exception("Error in today's picks")
            return

    # Check which sources loaded
    has_kalshi = "kalshi_home_prob" in recs.columns and recs["kalshi_home_prob"].notna().any()
    has_poly   = "polymarket_home_prob" in recs.columns and recs["polymarket_home_prob"].notna().any()
    odds_loaded = has_kalshi or has_poly

    if not odds_loaded:
        st.warning(
            "⚠️ No Kalshi or Polymarket prices found for today's games yet. "
            "Markets may not have opened. Edge values defaulted to 50% baseline.",
            icon="⚠️",
        )
    else:
        sources = []
        if has_kalshi: sources.append("✅ Kalshi")
        if has_poly:   sources.append("✅ Polymarket")
        st.success(f"Live prices loaded from: {' · '.join(sources)}")

    # Legend
    with st.expander("How to read this page", expanded=False):
        st.markdown("""
| Term | What it means |
|------|--------------|
| **Our Prediction** | Our model's estimated win probability (how often we think the home team wins) |
| **Market Price** | What the market says the probability is (bookmaker odds with the house cut removed) |
| **Edge** | Our prediction minus market price — positive means we think the home team is underpriced |
| **Bet Size** | Suggested % of bankroll to wager (quarter-Kelly formula, conservative) |
| **Strong Edge** | 7%+ edge — high confidence, consider a larger bet |
| **Moderate Edge** | 4–7% edge — worth a normal bet |
| **Marginal** | 2–4% edge — borderline; only bet if you have extra conviction |
| **No Bet** | Less than 2% edge — market is fairly priced, pass on this one |
        """)

    # Summary
    bets = recs[recs["bet"] == True].copy()
    avg_edge = bets["edge"].mean() if not bets.empty else 0.0
    live_adjusted = recs["availability_adjustment_prob"].abs().ge(0.01).sum() if "availability_adjustment_prob" in recs.columns else 0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Bets Found Today", len(bets))
    c2.metric("Avg Edge", f"{avg_edge:+.1%}" if not bets.empty else "—")
    c3.metric("Games Analyzed", len(recs))
    c4.metric("Live Injury Moves", int(live_adjusted))

    st.markdown("---")

    tab_value, tab_likely, tab_all = st.tabs(["Best Value Bets", "Favorites to Win", "All Games"])

    def render_game_cards(board: pd.DataFrame) -> None:
        for _, r in board.iterrows():
            home = r.get("home_team", "?")
            away = r.get("away_team", "?")
            h_prob = r.get("home_win_prob", 0.5)
            a_prob = r.get("away_win_prob", 0.5)
            base_prob = r.get("home_win_prob_model", h_prob)
            market = r.get("market_home_implied", r.get("market_home_prob", 0.5))
            edge = r.get("edge", 0.0)
            kelly = r.get("kelly", 0.0)
            confidence = r.get("confidence", "No Bet")
            is_bet = r.get("bet", False)
            avail_shift = r.get("availability_adjustment_prob", 0.0)

            border_style = "border-left: 3px solid #22c55e; padding-left: 12px; margin-bottom:4px;" if is_bet else "border-left: 3px solid #2a2a2a; padding-left: 12px; margin-bottom:4px;"
            st.markdown(f'<div style="{border_style} margin-bottom: 4px;">', unsafe_allow_html=True)

            header_col, badge_col = st.columns([4, 1])
            with header_col:
                st.markdown(f"### {away} @ {home}")
            with badge_col:
                if confidence == "Strong Edge":
                    st.success(confidence)
                elif confidence == "Moderate Edge":
                    st.info(confidence)
                elif confidence == "Marginal":
                    st.warning(confidence)
                else:
                    st.caption("No Bet")

            col_prob, col_prices, col_edge, col_kelly = st.columns(4)

            with col_prob:
                st.markdown("**Our Prediction**")
                st.markdown(f"🏠 {home}: **{h_prob:.1%}**")
                st.progress(float(h_prob))
                if pd.notna(base_prob) and abs(h_prob - base_prob) >= 0.005:
                    st.caption(f"Base model: {base_prob:.1%} | live adj: {avail_shift:+.1%}")
                st.markdown(f"✈️ {away}: **{a_prob:.1%}**")

            with col_prices:
                st.markdown("**Market Price**")
                k_prob = r.get("kalshi_home_prob")
                pm_prob = r.get("polymarket_home_prob")
                sb_prob = r.get("sportsbook_home_prob")
                st.markdown(f"Consensus: **{market:.1%}**")
                st.caption(
                    " | ".join(
                        item for item in [
                            f"Kalshi {k_prob:.1%}" if pd.notna(k_prob) else "",
                            f"Polymarket {pm_prob:.1%}" if pd.notna(pm_prob) else "",
                            f"Books {sb_prob:.1%}" if pd.notna(sb_prob) else "",
                        ]
                        if item
                    ) or "No live prices"
                )

            # Determine which side the model wants to bet
            bet_side  = r.get("bet_side", "home")
            bet_team  = r.get("bet_team", home)
            bet_prob  = r.get("bet_prob", h_prob)
            bet_mkt   = r.get("bet_market", market)
            best_edge = r.get("best_edge", abs(edge))

            with col_edge:
                display_edge = best_edge if is_bet else edge
                st.metric(
                    label="Edge vs. Market",
                    value=f"{display_edge:+.1%}",
                    delta="BET ✓" if is_bet else "Skip",
                    delta_color="normal" if is_bet else "off",
                )
                best_src = r.get("best_source")
                if best_src and not pd.isna(best_src):
                    st.caption(f"Best source: {str(best_src).title()}")

            with col_kelly:
                st.metric(
                    label="Bet Size (Kelly %)",
                    value=f"{kelly:.1%}" if is_bet else "—",
                    help="How much to bet as a % of your bankroll (quarter-Kelly formula — conservative sizing).",
                )

            # ── Plain-English Recommendation ──────────────────────────────
            st.markdown("")
            if is_bet:
                if best_edge >= 0.10:
                    strength = "significantly undervalued"
                elif best_edge >= 0.07:
                    strength = "heavily undervalued"
                elif best_edge >= 0.04:
                    strength = "undervalued"
                else:
                    strength = "slightly undervalued"

                side_label = "home" if bet_side == "home" else "away"
                rec = (
                    f"**Bet {bet_team} to win ({side_label})** — stake **{kelly:.1%} of your bankroll**.  \n"
                    f"Model gives {bet_team} a **{bet_prob:.0%}** chance; market says **{bet_mkt:.0%}**. "
                    f"{bet_team} is {strength} by **{best_edge:.0%}**."
                )
                st.success(rec)
            else:
                reason = "model and market agree" if abs(edge) < 0.03 else f"recommended team wins only {bet_prob:.0%} of the time — not high enough"
                st.caption(f"No bet — {reason}.")

            story = _game_story(r)
            st.markdown("**Why the model leans this way**")
            for note in story:
                st.markdown(f"- {note}")

            with st.expander("Player Availability (Injuries & Rest)", expanded=False):
                st.markdown(f"**{home}:** {_availability_copy('home', r)}")
                st.markdown(f"**{away}:** {_availability_copy('away', r)}")

            st.markdown('</div>', unsafe_allow_html=True)
            st.divider()

    with tab_value:
        if bets.empty:
            st.info("No positive-edge bets on the current board.", icon="📉")
        else:
            render_game_cards(bets.sort_values("edge", ascending=False))

    with tab_likely:
        likely = recs.copy()
        likely["favorite_win_prob"] = likely[["home_win_prob", "away_win_prob"]].max(axis=1)
        likely = likely.sort_values("favorite_win_prob", ascending=False)
        render_game_cards(likely)

    with tab_all:
        render_game_cards(recs.sort_values("edge", ascending=False))


# ─────────────────────────────────────────────────────────────────────────────
# Page 2: Model Performance
# ─────────────────────────────────────────────────────────────────────────────

def page_model_performance() -> None:
    st.markdown("## Model Accuracy & Backtest")

    model_data = load_trained_model()
    df = load_model_ready()
    pred_log = load_prediction_log()

    if df.empty:
        data_missing_warning()
        return

    # ── Metrics ───────────────────────────────────────────────────────────────
    model, feat_cols, medians = model_data

    if model is not None:
        test_df = df[df["season"].isin(config.TEST_SEASONS)]
        if not test_df.empty:
            try:
                from src.model import prepare_xy
                from src.evaluate import compute_metrics, calibration_data, run_backtest

                X_test, y_test = prepare_xy(test_df, feat_cols, fill_values=medians)
                probs = model.predict_proba(X_test)[:, 1]
                metrics = compute_metrics(y_test, probs)

                m1, m2, m3, m4 = st.columns(4)
                with m1:
                    st.metric("Log Loss (lower = better)", f"{metrics['log_loss']:.4f}", help="Measures how well-calibrated the probabilities are. Random guessing = 0.693. Lower is better.")
                with m2:
                    st.metric("Brier Score (lower = better)", f"{metrics['brier_score']:.4f}", help="Mean squared error of probability predictions. Random = 0.25. Lower is better.")
                with m3:
                    st.metric("Accuracy", f"{metrics['accuracy']:.1%}")
                with m4:
                    st.metric("AUC-ROC", f"{metrics['auc_roc']:.4f}")

                st.markdown("---")

                # ── Calibration plot ──────────────────────────────────────────
                st.markdown('<div class="section-header">Probability Accuracy (Calibration)</div>', unsafe_allow_html=True)
                cal_df = calibration_data(y_test, probs)

                fig = go.Figure()
                fig.add_trace(go.Scatter(
                    x=[0, 1], y=[0, 1], mode="lines",
                    line=dict(color="#6b7280", dash="dash"),
                    name="Perfect calibration",
                ))
                fig.add_trace(go.Scatter(
                    x=cal_df["mean_predicted"], y=cal_df["fraction_positive"],
                    mode="lines+markers",
                    line=dict(color="#22c55e", width=2),
                    marker=dict(size=8),
                    name="Model (calibrated)",
                ))
                fig.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0d0d0d",
                    plot_bgcolor="#111111",
                    xaxis_title="Mean Predicted Probability",
                    yaxis_title="Actual Win Rate",
                    height=400,
                    legend=dict(bgcolor="rgba(0,0,0,0)"),
                )
                st.plotly_chart(fig, use_container_width=True)

                # ── ROI Backtest ──────────────────────────────────────────────
                st.markdown('<div class="section-header">Simulated Returns — Backtest (2024-25)</div>', unsafe_allow_html=True)
                backtest = run_backtest(test_df, probs)

                bt_cols = st.columns(len(config.EDGE_THRESHOLDS))
                for col, (thresh, res) in zip(bt_cols, backtest.items()):
                    with col:
                        if res.get("flat_roi") is not None:
                            st.metric(
                                f"Edge ≥ {thresh:.0%}",
                                f"{res['flat_roi']:+.1%} ROI",
                                f"{res['n_bets']} bets",
                            )
                        else:
                            st.metric(f"Edge ≥ {thresh:.0%}", "No bets", "")

                # Cumulative ROI chart
                fig2 = go.Figure()
                colors = ["#22c55e", "#3b82f6", "#a78bfa", "#f59e0b"]
                for (thresh, res), color in zip(backtest.items(), colors):
                    if res.get("cumulative_pnl"):
                        fig2.add_trace(go.Scatter(
                            y=res["cumulative_pnl"],
                            mode="lines",
                            name=f"Edge ≥ {thresh:.0%}",
                            line=dict(color=color, width=2),
                        ))
                fig2.add_hline(y=0, line_dash="dash", line_color="#6b7280")
                fig2.update_layout(
                    template="plotly_dark",
                    paper_bgcolor="#0d0d0d",
                    plot_bgcolor="#111111",
                    xaxis_title="Bet Number",
                    yaxis_title="Cumulative P/L (flat $1 bets)",
                    height=380,
                    legend=dict(bgcolor="rgba(0,0,0,0)"),
                )
                st.plotly_chart(fig2, use_container_width=True)

            except Exception as e:
                st.error(f"Error computing metrics: {e}")
    else:
        data_missing_warning("Model not trained yet.")

    # ── Recent prediction history ─────────────────────────────────────────────
    if not pred_log.empty:
        st.markdown('<div class="section-header">Recent Predictions</div>', unsafe_allow_html=True)
        recent = pred_log.sort_values("game_date", ascending=False).head(30)
        st.dataframe(
            recent,
            use_container_width=True,
            hide_index=True,
        )


def page_paper_trader() -> None:
    st.markdown("## Paper Trader")
    model_data = load_trained_model()
    if model_data[0] is None:
        data_missing_warning("Model not trained yet.")
        return

    from scripts.daily_predictions import get_todays_features
    from src.injuries import apply_live_availability_adjustments
    from src.odds_collection import get_all_market_odds
    from src.paper_trading import (
        append_paper_trades,
        build_paper_trade_candidates,
        compute_live_paper_bankroll,
        load_paper_trades,
        mark_open_trades_to_market,
        sync_paper_trades_with_results,
    )
    from src.predict import generate_recommendation_table, predict_batch

    results_df = load_model_ready()
    trades = sync_paper_trades_with_results(results_df) if not results_df.empty else load_paper_trades()

    live_odds = pd.DataFrame()
    marked_trades = trades.copy()
    try:
        live_odds = get_all_market_odds(snapshot_context="streamlit_paper_trader")
        if not trades.empty:
            marked_trades = mark_open_trades_to_market(trades, live_odds)
    except Exception:
        logger.exception("Error loading live market marks")

    bankroll_state = compute_live_paper_bankroll(marked_trades, starting_bankroll=config.PAPER_BANKROLL_START)
    snapshots_df = load_market_snapshots_df()
    last_snapshot_at = snapshots_df["snapshot_at"].max() if not snapshots_df.empty and "snapshot_at" in snapshots_df.columns else pd.NaT

    total_pnl = bankroll_state["realized_pnl"] + bankroll_state["unrealized_pnl"]
    total_return = total_pnl / bankroll_state["starting_bankroll"] if bankroll_state["starting_bankroll"] > 0 else 0.0
    open_count = int((marked_trades["status"].fillna("open") == "open").sum()) if not marked_trades.empty and "status" in marked_trades.columns else 0
    settled_count_pt = int((marked_trades["status"].fillna("open") == "settled").sum()) if not marked_trades.empty and "status" in marked_trades.columns else 0

    pnl_color  = "#22c55e" if total_pnl >= 0 else "#ef4444"
    pnl_sign   = "+" if total_pnl >= 0 else ""
    ret_sign   = "+" if total_return >= 0 else ""
    st.markdown(
        f"<div style='border:1px solid {pnl_color}44;border-radius:10px;padding:20px 28px;"
        f"margin-bottom:16px;display:flex;align-items:center;gap:32px'>"
        f"<div style='flex:1'>"
        f"<div style='font-size:0.7rem;color:#555;text-transform:uppercase;letter-spacing:0.1em'>Total P/L</div>"
        f"<div style='font-size:2.4rem;font-weight:800;color:{pnl_color}'>{pnl_sign}${total_pnl:,.2f}</div>"
        f"<div style='font-size:0.95rem;color:{pnl_color}'>{ret_sign}{total_return:.1%} on ${bankroll_state['starting_bankroll']:,.0f} starting bankroll</div>"
        f"</div>"
        f"<div style='text-align:right'>"
        f"<div style='font-size:0.7rem;color:#555;text-transform:uppercase;letter-spacing:0.1em'>Breakdown</div>"
        f"<div style='font-size:0.9rem;margin-top:4px'>"
        f"<span style='color:#888'>Realized</span> "
        f"<span style='color:{"#22c55e" if bankroll_state["realized_pnl"] >= 0 else "#ef4444"};font-weight:600'>"
        f"{'+' if bankroll_state['realized_pnl'] >= 0 else ''}${bankroll_state['realized_pnl']:,.2f}</span>"
        f"</div>"
        f"<div style='font-size:0.9rem;margin-top:2px'>"
        f"<span style='color:#888'>Unrealized</span> "
        f"<span style='color:{"#22c55e" if bankroll_state["unrealized_pnl"] >= 0 else "#ef4444"};font-weight:600'>"
        f"{'+' if bankroll_state['unrealized_pnl'] >= 0 else ''}${bankroll_state['unrealized_pnl']:,.2f}</span>"
        f"</div>"
        f"</div>"
        f"</div>",
        unsafe_allow_html=True,
    )

    r1, r2, r3, r4 = st.columns(4)
    r1.metric("Bankroll", f"${bankroll_state['estimated_equity']:,.2f}")
    r2.metric("Active Bets", f"{open_count}")
    r3.metric("Settled Trades", f"{settled_count_pt}", delta=f"${bankroll_state['realized_pnl']:+,.2f}" if settled_count_pt > 0 else None)
    r4.metric("Cash Available", f"${bankroll_state['available_cash']:,.2f}")

    c_refresh, c_auto = st.columns([1, 2])
    with c_refresh:
        if st.button("Refresh Prices", use_container_width=True):
            st.cache_data.clear()
            st.rerun()
    with c_auto:
        auto_refresh = st.toggle("Auto-refresh", value=False, help=f"Updates every {config.LIVE_POLL_SECONDS}s")

    st.markdown("---")

    # ── TODAY'S PICKS ────────────────────────────────────────────────────────
    st.markdown("### Today's Picks")
    st.caption("Games where our model sees an edge over the market. Approve to log a bet.")

    edge_col, src_col = st.columns([1, 1])
    with edge_col:
        edge_threshold = st.slider("Min edge to show", min_value=0.01, max_value=0.15, value=float(config.PAPER_TRADE_EDGE), step=0.01, label_visibility="collapsed")
    with src_col:
        sources = st.multiselect("Markets", ["kalshi", "polymarket"], default=["kalshi", "polymarket"], label_visibility="collapsed")

    candidates = pd.DataFrame()
    with st.spinner("Loading picks..."):
        try:
            features = get_todays_features()
            if not features.empty:
                predictions = predict_batch(features)
                predictions = apply_live_availability_adjustments(
                    predictions,
                    report_date=predictions["game_date"].iloc[0] if "game_date" in predictions.columns and not predictions.empty else None,
                )
                recs = generate_recommendation_table(
                    predictions,
                    odds_df=live_odds if not live_odds.empty else get_all_market_odds(),
                    edge_threshold=edge_threshold,
                )
                candidates = build_paper_trade_candidates(
                    recs,
                    bankroll=bankroll_state["available_cash"],
                    edge_threshold=edge_threshold,
                    sources=sources,
                )
        except Exception as exc:
            st.error(f"Error loading picks: {exc}")
            logger.exception("Error in paper trader")
            return

    if candidates.empty:
        st.info("No picks meet the current edge threshold.", icon="📄")
    else:
        # Group by game
        game_keys = candidates.groupby(["home_team", "away_team"]).groups
        for (home, away), idx in game_keys.items():
            game_rows = candidates.loc[idx]
            st.markdown(
                f"<div style='font-size:0.78rem;color:#666;text-transform:uppercase;"
                f"letter-spacing:0.08em;margin:18px 0 6px'>{away} @ {home}</div>",
                unsafe_allow_html=True,
            )
            for _, c in game_rows.iterrows():
                team = c.get("contract_team", "?")
                mkt  = str(c.get("market_source", "")).title()
                model_p = float(c.get("model_prob", c.get("bet_prob", 0.5)))
                mkt_p   = float(c.get("market_prob", c.get("break_even_prob", 0.5)))
                edge    = float(c.get("edge", 0))
                stake   = float(c.get("stake", 0))
                payout  = float(c.get("payout_if_win", 0))
                edge_color = "#22c55e" if edge > 0 else "#ef4444"
                st.markdown(
                    f"<div style='border:1px solid #2a2a2a;border-radius:8px;padding:14px 18px;"
                    f"margin-bottom:8px;display:flex;align-items:center;gap:24px'>"
                    f"<div style='flex:1'>"
                    f"<div style='font-weight:700;font-size:1rem'>{team}</div>"
                    f"<div style='color:#666;font-size:0.8rem'>{mkt}</div>"
                    f"</div>"
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:0.7rem;color:#555'>Model</div>"
                    f"<div style='font-weight:600'>{model_p:.0%}</div>"
                    f"</div>"
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:0.7rem;color:#555'>Market</div>"
                    f"<div style='font-weight:600'>{mkt_p:.0%}</div>"
                    f"</div>"
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:0.7rem;color:#555'>Edge</div>"
                    f"<div style='font-weight:700;color:{edge_color}'>{edge:+.1%}</div>"
                    f"</div>"
                    f"<div style='text-align:right'>"
                    f"<div style='font-size:0.7rem;color:#555'>Bet · Win if right</div>"
                    f"<div style='font-weight:600'>${stake:.0f} · ${payout:.0f}</div>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

        if st.button("Log These Trades", use_container_width=True, type="primary"):
            append_paper_trades(candidates)
            st.cache_data.clear()
            st.rerun()

    # ── ACTIVE BETS ──────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Active Bets")

    if trades.empty:
        open_trades = pd.DataFrame()
        settled_trades = pd.DataFrame()
    else:
        status = marked_trades["status"].fillna("open") if "status" in marked_trades.columns else pd.Series("open", index=marked_trades.index)
        open_trades = marked_trades[status == "open"].copy()
        settled_trades = marked_trades[status == "settled"].copy()

    @st.fragment(run_every=f"{config.LIVE_POLL_SECONDS}s" if auto_refresh else None)
    def render_open_positions() -> None:
        live_marked = marked_trades
        if auto_refresh:
            try:
                live_odds_local = get_all_market_odds(snapshot_context="streamlit_paper_trader_auto")
                live_marked = mark_open_trades_to_market(trades, live_odds_local) if not trades.empty else trades
            except Exception:
                logger.exception("Auto-refresh live market update failed")

        live_status = live_marked["status"].fillna("open") if "status" in live_marked.columns else pd.Series("open", index=live_marked.index)
        live_open = live_marked[live_status == "open"].copy()

        if live_open.empty:
            st.info("No active bets right now.", icon="📄")
            return

        # Group by game
        for (home, away), idx in live_open.groupby(["home_team", "away_team"]).groups.items():
            game_rows = live_open.loc[idx]
            st.markdown(
                f"<div style='font-size:0.78rem;color:#666;text-transform:uppercase;"
                f"letter-spacing:0.08em;margin:18px 0 6px'>{away} @ {home}</div>",
                unsafe_allow_html=True,
            )
            for _, row in game_rows.iterrows():
                team  = row.get("contract_team", "?")
                mkt   = str(row.get("market_source", "")).title()
                entry = row.get("entry_price", float("nan"))
                stake = row.get("stake", float("nan"))
                cur_val = row.get("current_value", float("nan"))
                pnl   = row.get("unrealized_pnl", float("nan"))
                pnl_r = row.get("unrealized_return", float("nan"))
                stage = str(row.get("trade_stage", "pregame"))
                stage_color = "#22c55e" if stage == "live" else "#666"
                if pd.notna(pnl) and pnl >= 0:
                    pnl_col = "#22c55e"
                elif pd.notna(pnl):
                    pnl_col = "#ef4444"
                else:
                    pnl_col = "#888"
                pnl_str  = f"{pnl:+,.2f}" if pd.notna(pnl) else "—"
                pnl_r_str = f" ({pnl_r:+.1%})" if pd.notna(pnl_r) else ""
                entry_str = f"{entry:.0%}" if pd.notna(entry) else "—"
                cur_str   = f"${cur_val:,.2f}" if pd.notna(cur_val) else "—"
                stake_str = f"${stake:,.2f}" if pd.notna(stake) else "—"
                st.markdown(
                    f"<div style='border:1px solid #2a2a2a;border-radius:8px;padding:14px 18px;"
                    f"margin-bottom:8px;display:flex;align-items:center;gap:24px'>"
                    f"<div style='flex:1'>"
                    f"<div style='font-weight:700;font-size:1rem'>{team}</div>"
                    f"<div style='color:#666;font-size:0.8rem'>{mkt} · "
                    f"<span style='color:{stage_color}'>{stage}</span></div>"
                    f"</div>"
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:0.7rem;color:#555'>Paid</div>"
                    f"<div style='font-weight:600'>{stake_str} @ {entry_str}</div>"
                    f"</div>"
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:0.7rem;color:#555'>Current value</div>"
                    f"<div style='font-weight:600'>{cur_str}</div>"
                    f"</div>"
                    f"<div style='text-align:right'>"
                    f"<div style='font-size:0.7rem;color:#555'>P/L</div>"
                    f"<div style='font-weight:700;font-size:1.05rem;color:{pnl_col}'>${pnl_str}{pnl_r_str}</div>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    render_open_positions()

    # ── PAST RESULTS ─────────────────────────────────────────────────────────
    st.markdown("---")
    st.markdown("### Past Results")

    if settled_trades.empty:
        st.info("No settled trades yet.", icon="📊")
    else:
        settled_trades = settled_trades.sort_values("game_date", ascending=False)
        wins = int(settled_trades["win"].sum()) if "win" in settled_trades.columns else 0
        total_settled = len(settled_trades)
        losses = total_settled - wins
        roi = settled_trades["pnl"].sum() / settled_trades["stake"].sum() if {"pnl", "stake"}.issubset(settled_trades.columns) and settled_trades["stake"].sum() > 0 else np.nan

        rs1, rs2, rs3 = st.columns(3)
        rs1.metric("Record", f"{wins}W – {losses}L")
        rs2.metric("ROI", f"{roi:+.1%}" if pd.notna(roi) else "—")
        rs3.metric("Total P/L", f"${settled_trades['pnl'].sum():+,.2f}" if "pnl" in settled_trades.columns else "—")

        cumulative = settled_trades.sort_values("game_date")["pnl"].cumsum()
        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=settled_trades.sort_values("game_date").get("game_date", range(len(settled_trades))),
            y=cumulative,
            mode="lines+markers",
            fill="tozeroy",
            fillcolor="rgba(34,197,94,0.08)",
            line=dict(color="#22c55e", width=2),
            marker=dict(size=5),
            name="Cumulative P/L",
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#444")
        fig.update_layout(
            template="plotly_dark", paper_bgcolor="#0d0d0d", plot_bgcolor="#111111",
            xaxis_title="", yaxis_title="P/L ($)", height=260,
            legend=dict(bgcolor="rgba(0,0,0,0)"), margin=dict(t=10, b=10),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Per-game result cards
        for (home, away), idx in settled_trades.groupby(["home_team", "away_team"]).groups.items():
            game_rows = settled_trades.loc[idx]
            st.markdown(
                f"<div style='font-size:0.78rem;color:#666;text-transform:uppercase;"
                f"letter-spacing:0.08em;margin:18px 0 6px'>{away} @ {home}</div>",
                unsafe_allow_html=True,
            )
            for _, row in game_rows.iterrows():
                team  = row.get("contract_team", "?")
                mkt   = str(row.get("market_source", "")).title()
                stake = row.get("stake", float("nan"))
                payout = row.get("realized_payout", float("nan"))
                pnl   = row.get("pnl", float("nan"))
                win   = row.get("win", float("nan"))
                gdate = row.get("game_date", "")
                if pd.notna(win):
                    result_label = "WIN" if int(win) == 1 else "LOSS"
                    result_color = "#22c55e" if int(win) == 1 else "#ef4444"
                    result_border = "#22c55e33" if int(win) == 1 else "#ef444433"
                else:
                    result_label = "PENDING"
                    result_color = "#888"
                    result_border = "#333"
                pnl_str = f"${pnl:+,.2f}" if pd.notna(pnl) else "—"
                payout_str = f"${payout:,.2f}" if pd.notna(payout) else "—"
                stake_str  = f"${stake:,.2f}" if pd.notna(stake) else "—"
                st.markdown(
                    f"<div style='border:1px solid {result_border};border-radius:8px;padding:14px 18px;"
                    f"margin-bottom:8px;display:flex;align-items:center;gap:24px'>"
                    f"<div style='flex:1'>"
                    f"<div style='font-weight:700;font-size:1rem'>{team}</div>"
                    f"<div style='color:#666;font-size:0.8rem'>{mkt} · {gdate}</div>"
                    f"</div>"
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:0.7rem;color:#555'>Bet</div>"
                    f"<div style='font-weight:600'>{stake_str}</div>"
                    f"</div>"
                    f"<div style='text-align:center'>"
                    f"<div style='font-size:0.7rem;color:#555'>Payout</div>"
                    f"<div style='font-weight:600'>{payout_str}</div>"
                    f"</div>"
                    f"<div style='text-align:right'>"
                    f"<div style='font-size:0.85rem;font-weight:800;color:{result_color}'>{result_label}</div>"
                    f"<div style='font-weight:700;color:{result_color}'>{pnl_str}</div>"
                    f"</div>"
                    f"</div>",
                    unsafe_allow_html=True,
                )



# ─────────────────────────────────────────────────────────────────────────────
# Page: NBA Matchup Lab
# ─────────────────────────────────────────────────────────────────────────────

def _get_team_snapshot(df: pd.DataFrame, team: str) -> pd.Series:
    """Get the most recent row of stats for a team."""
    home = df[df["home_team"] == team].sort_values("game_date")
    away = df[df["away_team"] == team].sort_values("game_date")
    if not home.empty and not away.empty:
        last_h = home.iloc[-1]
        last_a = away.iloc[-1]
        source = last_h if last_h["game_date"] >= last_a["game_date"] else last_a
        prefix = "home_" if source.name == last_h.name else "away_"
    elif not home.empty:
        source = home.iloc[-1]; prefix = "home_"
    elif not away.empty:
        source = away.iloc[-1]; prefix = "away_"
    else:
        return pd.Series(dtype=float)

    flat = {}
    for col in source.index:
        if col.startswith(prefix):
            flat[col.replace(prefix, "")] = source[col]
        else:
            flat[col] = source[col]
    return pd.Series(flat)


def _stat_bar(label: str, val_a, val_b, col_a, col_b, higher_is_better: bool = True, fmt: str = ".1f") -> None:
    """Render a side-by-side stat comparison row with colored bars."""
    try:
        va = float(val_a); vb = float(val_b)
    except (TypeError, ValueError):
        return
    if pd.isna(va) or pd.isna(vb):
        return
    max_val = max(abs(va), abs(vb), 0.001)
    pct_a = min(abs(va) / max_val, 1.0)
    pct_b = min(abs(vb) / max_val, 1.0)
    a_wins = (va > vb) == higher_is_better
    a_color = "#22c55e" if a_wins else "#ef4444"
    b_color = "#22c55e" if not a_wins else "#ef4444"
    if abs(va - vb) < 0.005 * max_val:
        a_color = b_color = "#888"
    bar_a = f"width:{pct_a*100:.0f}%;background:{a_color};height:6px;border-radius:3px"
    bar_b = f"width:{pct_b*100:.0f}%;background:{b_color};height:6px;border-radius:3px;float:right"
    fmt_a = f"{va:{fmt}}"
    fmt_b = f"{vb:{fmt}}"
    st.markdown(
        f"""<div style='display:grid;grid-template-columns:1fr 120px 1fr;gap:8px;align-items:center;margin:6px 0'>
          <div>
            <div style='font-size:0.95rem;font-weight:600;color:{col_a}'>{fmt_a}</div>
            <div style='background:#1e1e1e;height:6px;border-radius:3px;margin-top:3px'><div style='{bar_a}'></div></div>
          </div>
          <div style='text-align:center;font-size:0.72rem;color:#555;text-transform:uppercase;letter-spacing:0.07em'>{label}</div>
          <div style='text-align:right'>
            <div style='font-size:0.95rem;font-weight:600;color:{col_b}'>{fmt_b}</div>
            <div style='background:#1e1e1e;height:6px;border-radius:3px;margin-top:3px;direction:rtl'><div style='{bar_b}'></div></div>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )


def page_nba_matchup() -> None:
    st.markdown("## NBA Matchup Lab")
    st.caption("Pick any two teams to see a full head-to-head breakdown — stats, form, Elo, model prediction, and market prices.")

    df = load_model_ready()
    if df.empty:
        data_missing_warning()
        return

    all_teams = sorted(df["home_team"].dropna().unique().tolist())

    col_sel1, col_vs, col_sel2 = st.columns([2, 0.3, 2])
    with col_sel1:
        team_a = st.selectbox("Team A (Away)", all_teams, index=all_teams.index("BOS") if "BOS" in all_teams else 0, key="mu_a")
    with col_vs:
        st.markdown("<div style='text-align:center;padding-top:28px;color:#555;font-weight:700'>vs</div>", unsafe_allow_html=True)
    with col_sel2:
        default_b = all_teams.index("LAL") if "LAL" in all_teams else 1
        team_b = st.selectbox("Team B (Home)", all_teams, index=default_b, key="mu_b")

    if team_a == team_b:
        st.warning("Pick two different teams.")
        return

    a_color = _team_color(team_a)
    b_color = _team_color(team_b)
    snap_a = _get_team_snapshot(df, team_a)
    snap_b = _get_team_snapshot(df, team_b)

    # ── Model prediction ──────────────────────────────────────────────────────
    model_data = load_trained_model()
    model, feat_cols, medians = model_data
    pred_prob_a = None
    if model is not None and not snap_a.empty and not snap_b.empty:
        try:
            from src.feature_engineering import assemble_features
            from src.predict import predict_batch
            from scripts.daily_predictions import get_todays_features
            todays = get_todays_features()
            if not todays.empty:
                match = todays[
                    ((todays["home_team"] == team_b) & (todays["away_team"] == team_a)) |
                    ((todays["home_team"] == team_a) & (todays["away_team"] == team_b))
                ]
                if not match.empty:
                    from src.predict import predict_batch
                    preds = predict_batch(match)
                    row = preds.iloc[0]
                    if row["home_team"] == team_b:
                        pred_prob_a = float(row["away_win_prob"])
                    else:
                        pred_prob_a = float(row["home_win_prob"])
        except Exception:
            pass

    # Fall back to Elo-based estimate
    if pred_prob_a is None:
        elo_a = float(snap_a.get("elo", 1500)) if not snap_a.empty else 1500
        elo_b = float(snap_b.get("elo", 1500)) if not snap_b.empty else 1500
        elo_diff = elo_a - elo_b
        pred_prob_a = 1 / (1 + 10 ** (-elo_diff / 400))
    pred_prob_b = 1 - pred_prob_a

    # ── Hero prediction card ──────────────────────────────────────────────────
    fav = team_a if pred_prob_a >= pred_prob_b else team_b
    fav_prob = max(pred_prob_a, pred_prob_b)
    fav_color = a_color if fav == team_a else b_color
    margin = abs(pred_prob_a - pred_prob_b)
    confidence = "Strong Edge" if margin >= 0.12 else "Moderate" if margin >= 0.06 else "Close Game"

    st.markdown(
        f"""<div style='border:1px solid #222;border-radius:10px;padding:24px 28px;margin:16px 0'>
          <div style='display:flex;align-items:center;justify-content:space-between;gap:16px'>
            <div style='flex:1;text-align:center'>
              <div style='font-size:0.72rem;color:#444;text-transform:uppercase;letter-spacing:0.1em'>Away</div>
              <div style='font-size:1.4rem;font-weight:700;color:{a_color};margin:4px 0'>{team_a}</div>
              <div style='font-size:3rem;font-weight:800;color:{"#22c55e" if pred_prob_a > pred_prob_b else "#ef4444"};line-height:1'>{pred_prob_a:.0%}</div>
              <div style='font-size:0.78rem;color:#555;margin-top:4px'>win probability</div>
            </div>
            <div style='text-align:center;padding:0 16px'>
              <div style='font-size:0.7rem;color:#444;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:8px'>Model Prediction</div>
              <div style='font-size:1.1rem;font-weight:700;color:{fav_color}'>{fav} favored</div>
              <div style='font-size:0.8rem;color:#555;margin-top:4px'>{confidence}</div>
            </div>
            <div style='flex:1;text-align:center'>
              <div style='font-size:0.72rem;color:#444;text-transform:uppercase;letter-spacing:0.1em'>Home</div>
              <div style='font-size:1.4rem;font-weight:700;color:{b_color};margin:4px 0'>{team_b}</div>
              <div style='font-size:3rem;font-weight:800;color:{"#22c55e" if pred_prob_b > pred_prob_a else "#ef4444"};line-height:1'>{pred_prob_b:.0%}</div>
              <div style='font-size:0.78rem;color:#555;margin-top:4px'>win probability</div>
            </div>
          </div>
        </div>""",
        unsafe_allow_html=True,
    )

    # ── Market odds ───────────────────────────────────────────────────────────
    try:
        from src.odds_collection import get_all_market_odds
        odds_df = get_all_market_odds(record_snapshot=False)
        if not odds_df.empty:
            match_odds = odds_df[
                ((odds_df["home_team"] == team_b) & (odds_df["away_team"] == team_a)) |
                ((odds_df["home_team"] == team_a) & (odds_df["away_team"] == team_b))
            ]
            if not match_odds.empty:
                o = match_odds.iloc[0]
                is_flipped = o["home_team"] == team_a
                k_a = float(o.get("kalshi_away_prob" if not is_flipped else "kalshi_home_prob", float("nan")))
                k_b = float(o.get("kalshi_home_prob" if not is_flipped else "kalshi_away_prob", float("nan")))
                pm_a = float(o.get("polymarket_away_prob" if not is_flipped else "polymarket_home_prob", float("nan")))
                pm_b = float(o.get("polymarket_home_prob" if not is_flipped else "polymarket_away_prob", float("nan")))

                mcols = st.columns(2)
                with mcols[0]:
                    if not pd.isna(k_a):
                        st.markdown(
                            f"<div style='border:1px solid #1e1e1e;border-radius:8px;padding:10px 14px'>"
                            f"<div style='font-size:0.65rem;color:#444;text-transform:uppercase;letter-spacing:0.1em'>Kalshi</div>"
                            f"<div style='margin-top:4px'><span style='color:{a_color};font-weight:700'>{team_a} {k_a:.0%}</span>"
                            f"<span style='color:#333'> · </span><span style='color:{b_color};font-weight:700'>{team_b} {k_b:.0%}</span></div>"
                            f"</div>", unsafe_allow_html=True)
                with mcols[1]:
                    if not pd.isna(pm_a):
                        st.markdown(
                            f"<div style='border:1px solid #1e1e1e;border-radius:8px;padding:10px 14px'>"
                            f"<div style='font-size:0.65rem;color:#444;text-transform:uppercase;letter-spacing:0.1em'>Polymarket</div>"
                            f"<div style='margin-top:4px'><span style='color:{a_color};font-weight:700'>{team_a} {pm_a:.0%}</span>"
                            f"<span style='color:#333'> · </span><span style='color:{b_color};font-weight:700'>{team_b} {pm_b:.0%}</span></div>"
                            f"</div>", unsafe_allow_html=True)
    except Exception:
        pass

    st.markdown("---")

    # ── Tabs ──────────────────────────────────────────────────────────────────
    tab_stats, tab_form, tab_h2h, tab_elo = st.tabs(["Stats Breakdown", "Recent Form", "Head-to-Head", "Elo History"])

    with tab_stats:
        st.markdown(
            f"<div style='display:grid;grid-template-columns:1fr 120px 1fr;gap:8px;margin-bottom:12px'>"
            f"<div style='font-size:1rem;font-weight:700;color:{a_color}'>{team_a}</div>"
            f"<div></div>"
            f"<div style='font-size:1rem;font-weight:700;color:{b_color};text-align:right'>{team_b}</div>"
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown('<div class="section-header">Efficiency</div>', unsafe_allow_html=True)
        _stat_bar("Off Rating", snap_a.get("off_rtg"), snap_b.get("off_rtg"), a_color, b_color, higher_is_better=True)
        _stat_bar("Def Rating", snap_a.get("def_rtg"), snap_b.get("def_rtg"), a_color, b_color, higher_is_better=False)
        _stat_bar("Net Rating", snap_a.get("net_rtg"), snap_b.get("net_rtg"), a_color, b_color, higher_is_better=True)
        _stat_bar("Pace", snap_a.get("pace"), snap_b.get("pace"), a_color, b_color, higher_is_better=True)
        _stat_bar("Elo Rating", snap_a.get("elo"), snap_b.get("elo"), a_color, b_color, higher_is_better=True, fmt=".0f")

        st.markdown('<div class="section-header">Four Factors</div>', unsafe_allow_html=True)
        _stat_bar("eFG%", snap_a.get("efg_pct"), snap_b.get("efg_pct"), a_color, b_color, fmt=".3f")
        _stat_bar("TOV Rate", snap_a.get("tov_rate"), snap_b.get("tov_rate"), a_color, b_color, higher_is_better=False, fmt=".3f")
        _stat_bar("OREB%", snap_a.get("oreb_pct"), snap_b.get("oreb_pct"), a_color, b_color, fmt=".3f")
        _stat_bar("FT Rate", snap_a.get("ft_rate"), snap_b.get("ft_rate"), a_color, b_color, fmt=".3f")
        _stat_bar("Opp eFG%", snap_a.get("opp_efg_pct"), snap_b.get("opp_efg_pct"), a_color, b_color, higher_is_better=False, fmt=".3f")

        st.markdown('<div class="section-header">Scoring (Rolling 10 Games)</div>', unsafe_allow_html=True)
        _stat_bar("Pts Scored", snap_a.get("roll_10_pts"), snap_b.get("roll_10_pts"), a_color, b_color)
        _stat_bar("Pts Allowed", snap_a.get("roll_10_opp_pts"), snap_b.get("roll_10_opp_pts"), a_color, b_color, higher_is_better=False)
        _stat_bar("FG%", snap_a.get("roll_10_fg_pct"), snap_b.get("roll_10_fg_pct"), a_color, b_color, fmt=".3f")
        _stat_bar("3P%", snap_a.get("roll_10_fg3_pct"), snap_b.get("roll_10_fg3_pct"), a_color, b_color, fmt=".3f")
        _stat_bar("Assists", snap_a.get("roll_10_ast"), snap_b.get("roll_10_ast"), a_color, b_color)
        _stat_bar("Turnovers", snap_a.get("roll_10_tov"), snap_b.get("roll_10_tov"), a_color, b_color, higher_is_better=False)

        st.markdown('<div class="section-header">Situation</div>', unsafe_allow_html=True)
        _stat_bar("Rest Days", snap_a.get("rest_days"), snap_b.get("rest_days"), a_color, b_color, fmt=".0f")
        _stat_bar("Win Streak", snap_a.get("win_streak"), snap_b.get("win_streak"), a_color, b_color, fmt=".0f")
        _stat_bar("Road Games (consec.)", snap_a.get("consec_road_games"), snap_b.get("consec_road_games"), a_color, b_color, higher_is_better=False, fmt=".0f")

    with tab_form:
        season_df = df[df["season"] == df["season"].max()]

        def _team_games(team: str) -> pd.DataFrame:
            hg = season_df[season_df["home_team"] == team].copy()
            ag = season_df[season_df["away_team"] == team].copy()
            hg["win"] = hg["home_win"]
            ag["win"] = 1 - ag["home_win"]
            hg["pts"] = hg.get("home_pts", pd.Series(dtype=float))
            ag["pts"] = ag.get("away_pts", pd.Series(dtype=float))
            hg["opp_pts"] = hg.get("away_pts", pd.Series(dtype=float))
            ag["opp_pts"] = ag.get("home_pts", pd.Series(dtype=float))
            combined = pd.concat([hg, ag]).sort_values("game_date").tail(20)
            return combined

        ga = _team_games(team_a)
        gb = _team_games(team_b)

        # Last 10 results dots
        for team, games, tc in [(team_a, ga, a_color), (team_b, gb, b_color)]:
            last10 = games.tail(10)
            dots = ""
            for _, gr in last10.iterrows():
                w = int(gr.get("win", 0))
                dots += f"<span style='display:inline-block;width:22px;height:22px;border-radius:50%;background:{'#22c55e' if w else '#ef4444'};margin:2px;text-align:center;line-height:22px;font-size:0.65rem;font-weight:700;color:#fff'>{'W' if w else 'L'}</span>"
            wins10 = int(last10["win"].sum()) if not last10.empty else 0
            st.markdown(
                f"<div style='margin:10px 0'>"
                f"<span style='font-size:1rem;font-weight:700;color:{tc}'>{team}</span>"
                f"<span style='color:#555;font-size:0.8rem;margin-left:8px'>{wins10}-{10-wins10} last 10</span>"
                f"<div style='margin-top:6px'>{dots}</div></div>",
                unsafe_allow_html=True,
            )

        # Points scored/allowed chart
        if not ga.empty and not gb.empty:
            fig = go.Figure()
            for games, team, tc in [(ga, team_a, a_color), (gb, team_b, b_color)]:
                if "roll_10_pts" in games.columns and games["roll_10_pts"].notna().any():
                    fig.add_trace(go.Scatter(
                        x=games["game_date"], y=games["roll_10_pts"],
                        mode="lines", name=f"{team} Pts Scored",
                        line=dict(color=tc, width=2),
                    ))
                if "roll_10_opp_pts" in games.columns and games["roll_10_opp_pts"].notna().any():
                    fig.add_trace(go.Scatter(
                        x=games["game_date"], y=games["roll_10_opp_pts"],
                        mode="lines", name=f"{team} Pts Allowed",
                        line=dict(color=tc, width=1.5, dash="dot"),
                    ))
            fig.update_layout(
                template="plotly_dark", paper_bgcolor="#0d0d0d", plot_bgcolor="#111111",
                height=320, legend=dict(bgcolor="rgba(0,0,0,0)"),
                yaxis_title="Points (rolling 10)", xaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)

    with tab_h2h:
        current_season = df["season"].max()
        h2h = df[
            (df["season"] == current_season) & (
                ((df["home_team"] == team_b) & (df["away_team"] == team_a)) |
                ((df["home_team"] == team_a) & (df["away_team"] == team_b))
            )
        ].sort_values("game_date", ascending=False)

        if h2h.empty:
            st.info(f"No matchups between {team_a} and {team_b} in the current season yet.", icon="📅")
        else:
            a_wins = int(((h2h["home_team"] == team_a) & (h2h["home_win"] == 1) |
                          (h2h["away_team"] == team_a) & (h2h["home_win"] == 0)).sum())
            b_wins = len(h2h) - a_wins
            c1, c2, c3 = st.columns(3)
            c1.metric(f"{team_a} Wins", a_wins)
            c2.metric("Games Played", len(h2h))
            c3.metric(f"{team_b} Wins", b_wins)

            for _, gr in h2h.iterrows():
                ht, at_ = gr["home_team"], gr["away_team"]
                hp, ap = gr.get("home_pts", "?"), gr.get("away_pts", "?")
                winner = ht if gr.get("home_win") == 1 else at_
                w_color = b_color if winner == team_b else a_color
                st.markdown(
                    f"<div style='border:1px solid #1e1e1e;border-radius:8px;padding:10px 16px;margin:6px 0;"
                    f"display:flex;justify-content:space-between;align-items:center'>"
                    f"<span style='color:#555;font-size:0.8rem'>{pd.to_datetime(gr['game_date']).strftime('%b %d') if pd.notna(gr.get('game_date')) else ''}</span>"
                    f"<span style='font-weight:600'>{at_} {ap} @ {ht} {hp}</span>"
                    f"<span style='color:{w_color};font-weight:700;font-size:0.85rem'>{winner} won</span>"
                    f"</div>",
                    unsafe_allow_html=True,
                )

    with tab_elo:
        elo_hist = df[["game_date", "home_team", "away_team", "home_elo", "away_elo"]].dropna(subset=["home_elo"])
        if elo_hist.empty:
            st.info("No Elo history available.")
        else:
            fig = go.Figure()
            for team, tc in [(team_a, a_color), (team_b, b_color)]:
                th = pd.concat([
                    elo_hist[elo_hist["home_team"] == team][["game_date", "home_elo"]].rename(columns={"home_elo": "elo"}),
                    elo_hist[elo_hist["away_team"] == team][["game_date", "away_elo"]].rename(columns={"away_elo": "elo"}),
                ]).sort_values("game_date").tail(100)
                if not th.empty:
                    fig.add_trace(go.Scatter(
                        x=th["game_date"], y=th["elo"],
                        mode="lines", name=team,
                        line=dict(color=tc, width=2),
                    ))
            fig.add_hline(y=1500, line_dash="dot", line_color="#333", line_width=1, annotation_text="League avg")
            fig.update_layout(
                template="plotly_dark", paper_bgcolor="#0d0d0d", plot_bgcolor="#111111",
                height=360, legend=dict(bgcolor="rgba(0,0,0,0)"),
                yaxis_title="Elo Rating", xaxis_title="",
            )
            st.plotly_chart(fig, use_container_width=True)

            ea = float(snap_a.get("elo", 1500))
            eb = float(snap_b.get("elo", 1500))
            e1, e2, e3 = st.columns(3)
            e1.metric(f"{team_a} Elo", f"{ea:.0f}")
            e2.metric("Difference", f"{ea - eb:+.0f}")
            e3.metric(f"{team_b} Elo", f"{eb:.0f}")


# ─────────────────────────────────────────────────────────────────────────────
# Page 3: Team Explorer
# ─────────────────────────────────────────────────────────────────────────────

def page_team_explorer() -> None:
    st.markdown("## Team Explorer")

    df = load_model_ready()
    elo_hist = load_elo_history()

    if df.empty:
        data_missing_warning()
        return

    # Team selector
    all_teams = sorted(df["home_team"].dropna().unique().tolist())
    selected_team = st.selectbox("Select Team", all_teams)

    if not selected_team:
        return

    current_season = _current_nba_season_label()
    season_data = df[df["season"] == current_season].copy()
    if season_data.empty:
        current_season = str(df["season"].max())
        season_data = df[df["season"] == current_season].copy()

    # ── Current Elo ───────────────────────────────────────────────────────────
    col1, col2, col3 = st.columns(3)

    if not df.empty and "home_elo" in df.columns:
        # Get most recent Elo from the main dataset (which has team names + elo together)
        home_rows = df[df["home_team"] == selected_team].sort_values("game_date")
        away_rows = df[df["away_team"] == selected_team].sort_values("game_date")
        last_home_elo = home_rows.iloc[-1]["home_elo"] if not home_rows.empty else None
        last_away_elo = away_rows.iloc[-1]["away_elo"] if not away_rows.empty else None
        # Pick whichever game was more recent
        if not home_rows.empty and not away_rows.empty:
            if home_rows.iloc[-1]["game_date"] >= away_rows.iloc[-1]["game_date"]:
                current_elo = last_home_elo
            else:
                current_elo = last_away_elo
        else:
            current_elo = last_home_elo or last_away_elo
        with col1:
            st.metric("Current Elo", f"{current_elo:.0f}" if current_elo else "N/A")

    st.caption(f"Season record shown below is from the {current_season} season only.")

    # Season record
    team_home = season_data[season_data["home_team"] == selected_team]
    team_away = season_data[season_data["away_team"] == selected_team]
    wins = team_home["home_win"].sum() + (1 - team_away["home_win"]).sum()
    losses = (1 - team_home["home_win"]).sum() + team_away["home_win"].sum()

    with col2:
        st.metric("Season Record", f"{int(wins)}–{int(losses)}")
    with col3:
        win_pct = wins / (wins + losses) if (wins + losses) > 0 else 0
        st.metric("Win %", f"{win_pct:.1%}")

    st.markdown("---")

    # ── Rolling form chart ────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Rolling Form (Last 30 Games)</div>', unsafe_allow_html=True)

    # Combine home and away appearances
    home_games = df[df["home_team"] == selected_team].copy()
    home_games["net_rtg"] = home_games.get("home_net_rtg", pd.Series(dtype=float))
    home_games["roll_10_pts"] = home_games.get("home_roll_10_pts", pd.Series(dtype=float))
    home_games["roll_10_opp_pts"] = home_games.get("home_roll_10_opp_pts", pd.Series(dtype=float))

    away_games = df[df["away_team"] == selected_team].copy()
    away_games["net_rtg"] = away_games.get("away_net_rtg", pd.Series(dtype=float))
    away_games["roll_10_pts"] = away_games.get("away_roll_10_pts", pd.Series(dtype=float))
    away_games["roll_10_opp_pts"] = away_games.get("away_roll_10_opp_pts", pd.Series(dtype=float))

    all_games = pd.concat([home_games, away_games]).sort_values("game_date").tail(30)

    if "roll_10_pts" in all_games.columns:
        fig = go.Figure()
        for col_name, label, color in [
            ("roll_10_pts", "Pts Scored (rolling 10)", "#22c55e"),
            ("roll_10_opp_pts", "Pts Allowed (rolling 10)", "#f87171"),
        ]:
            vals = all_games[col_name] if col_name in all_games.columns else None
            if vals is not None and vals.notna().any():
                fig.add_trace(go.Scatter(
                    x=all_games["game_date"], y=vals,
                    mode="lines", name=label,
                    line=dict(color=color, width=2),
                ))
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0d0d0d",
            plot_bgcolor="#111111",
            height=350,
            legend=dict(bgcolor="rgba(0,0,0,0)"),
        )
        st.plotly_chart(fig, use_container_width=True)
    else:
        st.info("Rolling stats not available — run build_dataset.py to generate features.")

    # ── Upcoming games ────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Upcoming Schedule</div>', unsafe_allow_html=True)
    st.info("Live schedule requires running scripts/daily_predictions.py", icon="ℹ️")


# ─────────────────────────────────────────────────────────────────────────────
# Page 4: Bet Tracker
# ─────────────────────────────────────────────────────────────────────────────

def page_bet_tracker() -> None:
    st.markdown("## Bet Tracker")

    pred_log = settle_prediction_log(load_prediction_log(), load_model_ready())

    if pred_log.empty:
        st.info(
            "No prediction history yet. Run `python scripts/daily_predictions.py` to start logging.",
            icon="📊",
        )
        return

    bets = pred_log[pred_log.get("bet", False) == True].copy() if "bet" in pred_log.columns else pred_log.copy()

    if bets.empty:
        st.info("No bets placed yet according to prediction log.", icon="📊")
        return

    settled_bets = bets[bets["home_win"].isin([0, 1])] if "home_win" in bets.columns else pd.DataFrame()

    # ── Summary metrics ───────────────────────────────────────────────────────
    total_bets = len(bets)
    settled_count = len(settled_bets)
    if not settled_bets.empty and "home_win" in settled_bets.columns:
        if "bet_side" in settled_bets.columns:
            bet_won = (
                ((settled_bets["bet_side"] == "home") & (settled_bets["home_win"] == 1)) |
                ((settled_bets["bet_side"] == "away") & (settled_bets["home_win"] == 0))
            )
        else:
            bet_won = settled_bets["home_win"] == 1
        wins = int(bet_won.sum())
    else:
        wins = 0
    win_rate = wins / settled_count if settled_count > 0 else None

    avg_clv = settled_bets["market_clv"].mean() if "market_clv" in settled_bets.columns and not settled_bets.empty else None
    c1, c2, c3, c4, c5 = st.columns(5)
    with c1:
        st.metric("Total Bets", total_bets)
    with c2:
        st.metric("Settled Bets", settled_count)
    with c3:
        if win_rate is not None:
            st.metric("Win Rate", f"{win_rate:.1%}")
        else:
            st.metric("Win Rate", "—")
    with c4:
        if "flat_pnl" in settled_bets.columns and settled_count > 0:
            # ROI = total profit / total amount wagered (each flat bet = 1 unit)
            total_wagered = settled_count  # 1 unit per bet
            roi = settled_bets["flat_pnl"].sum() / total_wagered
            st.metric("Flat ROI", f"{roi:+.1%}")
        else:
            st.metric("ROI", "—")
    with c5:
        st.metric("Avg CLV", f"{avg_clv:+.2%}" if avg_clv is not None and pd.notna(avg_clv) else "—")

    unsettled_count = total_bets - settled_count
    if unsettled_count > 0:
        st.caption(f"{unsettled_count} logged bet(s) are still awaiting final results.")

    st.markdown("---")

    # ── Cumulative P/L chart ──────────────────────────────────────────────────
    if "flat_pnl" in settled_bets.columns and not settled_bets.empty:
        st.markdown('<div class="section-header">Running Profit / Loss</div>', unsafe_allow_html=True)
        bets_sorted = settled_bets.sort_values("game_date") if "game_date" in settled_bets.columns else settled_bets
        cumulative = bets_sorted["flat_pnl"].cumsum()

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=bets_sorted.get("game_date", range(len(bets_sorted))),
            y=cumulative,
            mode="lines+markers",
            fill="tozeroy",
            fillcolor="rgba(34,197,94,0.08)",
            line=dict(color="#22c55e", width=2),
            marker=dict(size=5),
        ))
        fig.add_hline(y=0, line_dash="dash", line_color="#6b7280")
        fig.update_layout(
            template="plotly_dark",
            paper_bgcolor="#0d0d0d",
            plot_bgcolor="#111111",
            xaxis_title="Date",
            yaxis_title="Cumulative P/L",
            height=380,
        )
        st.plotly_chart(fig, use_container_width=True)
    elif total_bets > 0:
        st.info("Logged bets exist, but none are settled yet.", icon="📊")

    # ── Filters ───────────────────────────────────────────────────────────────
    st.markdown('<div class="section-header">Bet History</div>', unsafe_allow_html=True)

    col_filter1, col_filter2 = st.columns([1, 3])
    with col_filter1:
        if "game_date" in bets.columns and not bets.empty:
            game_dates = _to_datetime_mixed(bets["game_date"])
            min_date = game_dates.min().date()
            max_date = game_dates.max().date()
            date_range = st.date_input(
                "Date range",
                value=(min_date, max_date),
                min_value=min_date,
                max_value=max_date,
            )
            if len(date_range) == 2:
                mask = (game_dates.dt.date >= date_range[0]) & (game_dates.dt.date <= date_range[1])
                bets = bets[mask]

    history_cols = [
        "game_date", "away_team", "home_team", "home_win_prob", "market_home_implied",
        "closing_market_home_prob", "market_clv", "bet", "flat_pnl",
    ]
    st.dataframe(
        bets[[c for c in history_cols if c in bets.columns]],
        use_container_width=True,
        hide_index=True,
    )

    # Export
    csv = bets.to_csv(index=False)
    st.download_button(
        "⬇ Export to CSV",
        data=csv,
        file_name=f"nba_bets_{date.today()}.csv",
        mime="text/csv",
    )

    # ── Methodology expanders ─────────────────────────────────────────────────
    with st.expander("How does Elo work?"):
        st.markdown("""
        **Elo ratings** track team strength dynamically across every game of the season.

        - Each team starts with a rating of **1500**
        - After each game, the winner gains points and the loser loses points
        - The amount transferred depends on the **expected outcome** — beating a much stronger team earns more points
        - We apply a **home court advantage** of +100 Elo points when computing expected outcomes
        - At the start of each new season, ratings are **mean-reverted** 1/3 of the way back to 1500 to account for roster changes
        """)

    with st.expander("What is Kelly Criterion?"):
        st.markdown("""
        **Kelly Criterion** is an optimal bet-sizing formula that maximizes long-run bankroll growth.

        ```
        Kelly % = (p × decimal_odds - 1) / (decimal_odds - 1)
        ```

        Where `p` is the model's true win probability and `decimal_odds` is the market price.

        We use **quarter-Kelly** (25% of full Kelly) for conservative sizing, which reduces variance
        while still capturing most of the edge. Never bet more than 25% of your bankroll on a single game.
        """)

    with st.expander("How are probabilities calibrated?"):
        st.markdown("""
        Raw XGBoost probabilities can be **systematically biased** — the model might say 70% when
        the true frequency is only 62%. Calibration fixes this.

        We apply **isotonic regression** (a non-parametric method) on the validation set to map
        raw model scores to true empirical win rates. After calibration, when the model says 65%,
        teams win approximately 65% of the time.

        This is critical for Kalshi/Polymarket trading — you need to trust the absolute probability,
        not just the relative ranking.
        """)


def page_ncaam() -> None:
    import ncaab_config
    from src.ncaab_predict import predict_matchup

    st.markdown("## NCAAM Tournament Lab")
    if not _ncaab_require_artifacts():
        return

    team_features = load_ncaab_team_features_df()
    bracket = load_ncaab_bracket_df()
    meta = load_ncaab_projection_meta()
    metrics = load_ncaab_metrics()
    model_bundle = load_ncaab_model_bundle()
    seed_baselines = load_ncaab_seed_baselines_df()
    market_recs = load_ncaab_market_recommendations_df()

    if team_features.empty or bracket.empty:
        st.warning(
            "NCAA projected data is empty. Run `python scripts/update_ncaab_current.py` to rebuild the March Madness artifacts.",
            icon="🏀",
        )
        return

    projection_date = meta.get("projection_date", ncaab_config.CURRENT_PROJECTION_DATE)
    champion_row = bracket[bracket["round"] == "National Championship"].tail(1)
    champion = champion_row["winner_name"].iloc[0] if not champion_row.empty else "—"
    champion_prob = champion_row["win_prob"].iloc[0] if not champion_row.empty else np.nan
    avg_pick_edge = (
        pd.to_numeric(bracket["winner_seed_edge"], errors="coerce").mean()
        if "winner_seed_edge" in bracket.columns
        else np.nan
    )
    field_teams = len(team_features)
    priced_games = len(market_recs)

    st.markdown(
        _ncaam_hero_html(
            projection_date=projection_date,
            champion=champion,
            champion_prob=champion_prob,
            accuracy=metrics.get("accuracy", float("nan")),
            avg_pick_edge=avg_pick_edge,
            priced_games=priced_games,
            field_teams=field_teams,
        ),
        unsafe_allow_html=True,
    )

    action_col, info_col = st.columns([1.1, 5.2])
    with action_col:
        if st.button("Refresh NCAAM", use_container_width=True):
            st.cache_data.clear()
            st.cache_resource.clear()
            st.rerun()
    with info_col:
        st.markdown(
            _ncaam_panel_html(
                "How to read this page",
                "Market Edge is model probability minus the live sportsbook or Kalshi price. "
                "Seed Edge is model probability minus the historical win rate for the same ordered seed matchup.",
            ),
            unsafe_allow_html=True,
        )

    tab_market, tab_builder, tab_bracket, tab_matchup, tab_model, tab_teams = st.tabs(
        ["Today's Picks", "Bracket Builder", "Bracket Board", "Matchup Lab", "Model Report", "Team Board"]
    )

    with tab_market:
        st.markdown(
            _ncaam_panel_html(
                "Today's Picks",
                "Only games where both teams are in the projected March Madness field are shown. "
                "The model prices them on a neutral-court basis so the board stays aligned with the tournament use case.",
            ),
            unsafe_allow_html=True,
        )

        if market_recs.empty:
            st.info(
                "No live sportsbook or Kalshi matchups are currently mapped to two projected tournament teams.",
                icon="🏀",
            )
        else:
            bets = market_recs[market_recs["bet"]].copy()
            biggest_edge = pd.to_numeric(market_recs["best_edge"], errors="coerce").max()
            avg_kelly = pd.to_numeric(bets["kelly"], errors="coerce").mean() if not bets.empty else np.nan
            best_sources = (
                market_recs["best_source"].dropna().astype(str).value_counts().to_dict()
                if "best_source" in market_recs.columns
                else {}
            )
            source_copy = " | ".join(f"{source}: {count}" for source, count in best_sources.items()) if best_sources else "—"

            st.markdown(
                _ncaam_panel_html(
                    "Board snapshot",
                    f"{len(market_recs)} games priced, {int(bets['bet'].sum()) if 'bet' in bets.columns else 0} bets flagged, "
                    f"largest edge {f'{biggest_edge:+.1%}' if pd.notna(biggest_edge) else '—'}, average Kelly "
                    f"{f'{avg_kelly:.1%}' if pd.notna(avg_kelly) else '—'}. Best price mix: {source_copy}.",
                ),
                unsafe_allow_html=True,
            )

            if not bets.empty:
                st.markdown(
                    _ncaam_panel_html(
                        "Best Value Bets",
                        "Highest-edge current opportunities, sorted by model disagreement with the live market.",
                    ),
                    unsafe_allow_html=True,
                )
                st.markdown(_ncaam_pick_cards_html(bets), unsafe_allow_html=True)
                st.dataframe(
                    _ncaab_market_board_view(bets),
                    use_container_width=True,
                    hide_index=True,
                )
            else:
                st.markdown(_ncaam_pick_cards_html(bets), unsafe_allow_html=True)

            st.markdown(
                _ncaam_panel_html(
                    "Full Market Board",
                    "The complete projected-field slate with model probability, market reference, edge, seed edge, and best price.",
                ),
                unsafe_allow_html=True,
            )
            st.dataframe(
                _ncaab_market_board_view(market_recs),
                use_container_width=True,
                hide_index=True,
            )

    with tab_builder:
        st.markdown(
            _ncaam_panel_html(
                "Bracket Builder",
                "A full visual bracket generated from the current projected field. Every matchup advances the team with the higher calibrated model win probability.",
            ),
            unsafe_allow_html=True,
        )
        builder_html = build_bracket_html(bracket, team_features)
        if builder_html:
            st.markdown(builder_html, unsafe_allow_html=True)
        else:
            st.info("Visual bracket unavailable because the projected bracket artifact is incomplete.", icon="🏀")

    with tab_bracket:
        st.caption(
            f"Projection source: {meta.get('projection_source_url', ncaab_config.CURRENT_BRACKETOLOGY_URL)}"
        )
        st.caption(
            "Bracket picks are deterministic: every slot advances the team with the higher calibrated win probability."
        )

        seed_lookup = (
            team_features.drop_duplicates(subset=["TeamID"]).set_index("TeamID")["seed_num"].to_dict()
            if "TeamID" in team_features.columns and "seed_num" in team_features.columns
            else {}
        )
        bracket_view = bracket.copy()
        bracket_view["round_order"] = bracket_view["round"].map(_ncaab_round_order)
        bracket_view = bracket_view.sort_values(["round_order", "region", "winner_name"]).reset_index(drop=True)

        if "winner_seed_edge" in bracket_view.columns:
            upset_mask = (
                pd.to_numeric(bracket_view["winner_seed_edge"], errors="coerce").fillna(0.0) >= 0.05
            )
            st.metric("Meaningful Seed Edges", int(upset_mask.sum()))

        for round_name in [
            "First Four",
            "Round of 64",
            "Round of 32",
            "Sweet 16",
            "Elite 8",
            "Final Four",
            "National Championship",
        ]:
            round_games = bracket_view[bracket_view["round"] == round_name]
            if round_games.empty:
                continue
            st.markdown(f'<div class="section-header">{round_name}</div>', unsafe_allow_html=True)
            columns = st.columns(2 if round_name in {"First Four", "Round of 64", "Round of 32"} else 1)
            for idx, game in round_games.reset_index(drop=True).iterrows():
                with columns[idx % len(columns)]:
                    winner_id = game.get("winner_id")
                    team_a_id = game.get("team_a_id")
                    team_b_id = game.get("team_b_id")
                    loser_name = game["team_b_name"] if winner_id == team_a_id else game["team_a_name"]
                    winner_seed = seed_lookup.get(winner_id)
                    loser_seed = seed_lookup.get(team_b_id if winner_id == team_a_id else team_a_id)
                    edge_value = pd.to_numeric(pd.Series([game.get("winner_seed_edge")]), errors="coerce").iloc[0]
                    edge_label = _ncaab_edge_label(edge_value) if pd.notna(edge_value) else "Seed Edge"
                    seed_line = (
                        f"Seed {int(winner_seed)} over Seed {int(loser_seed)}"
                        if pd.notna(winner_seed) and pd.notna(loser_seed)
                        else "Projected matchup"
                    )
                    edge_copy = f"{edge_value:+.1%}" if pd.notna(edge_value) else "—"
                    st.markdown(
                        f"""
                        <div class="game-card">
                            <div style="display:flex; justify-content:space-between; gap:10px; align-items:center;">
                                <strong>{game['winner_name']} over {loser_name}</strong>
                                <span style="color:#60a5fa; font-size:0.82rem; font-weight:600;">{edge_label}</span>
                            </div>
                            <div style="color:#888; margin-top:6px;">{seed_line} · {game['team_a_name']} vs {game['team_b_name']}</div>
                            <div style="display:flex; gap:24px; margin-top:10px;">
                                <div><span style="color:#888;">Win Prob</span><br><strong>{game['win_prob']:.1%}</strong></div>
                                <div><span style="color:#888;">Edge vs Seeds</span><br><strong>{edge_copy}</strong></div>
                                <div><span style="color:#888;">Region</span><br><strong>{game.get('region', '—')}</strong></div>
                            </div>
                        </div>
                        """,
                        unsafe_allow_html=True,
                    )

    with tab_matchup:
        season_df = team_features.sort_values(["region", "seed_num", "TeamName"])
        team_names = season_df["TeamName"].tolist()
        team_a_name = st.selectbox("Team A", team_names, index=0, key="ncaam_team_a")
        team_b_name = st.selectbox("Team B", team_names, index=min(1, len(team_names) - 1), key="ncaam_team_b")

        if team_a_name == team_b_name:
            st.info("Choose two different teams.")
        else:
            team_a_id = int(season_df.loc[season_df["TeamName"] == team_a_name, "TeamID"].iloc[0])
            team_b_id = int(season_df.loc[season_df["TeamName"] == team_b_name, "TeamID"].iloc[0])
            team_a_profile = season_df.loc[season_df["TeamID"] == team_a_id].iloc[0]
            team_b_profile = season_df.loc[season_df["TeamID"] == team_b_id].iloc[0]
            prediction = predict_matchup(
                int(season_df["Season"].iloc[0]),
                team_a_id,
                team_b_id,
                team_features=team_features,
                model_bundle=model_bundle,
                seed_baselines=seed_baselines,
            )
            row = prediction["feature_row"].iloc[0]

            c1, c2, c3, c4 = st.columns(4)
            c1.metric(team_a_name, f"{prediction['team_a_win_prob']:.1%}")
            c2.metric(team_b_name, f"{prediction['team_b_win_prob']:.1%}")
            c3.metric("Seed Baseline", f"{prediction['seed_baseline_prob']:.1%}")
            best_seed_edge = prediction["team_a_seed_edge"]
            best_team = team_a_name
            if prediction["team_b_seed_edge"] > best_seed_edge:
                best_seed_edge = prediction["team_b_seed_edge"]
                best_team = team_b_name
            c4.metric("Best Edge vs Seeds", f"{best_seed_edge:+.1%}", delta=best_team)

            market_mask = (
                ((market_recs["home_team"] == team_a_name) & (market_recs["away_team"] == team_b_name))
                | ((market_recs["home_team"] == team_b_name) & (market_recs["away_team"] == team_a_name))
            ) if not market_recs.empty else pd.Series(dtype=bool)
            live_market = market_recs[market_mask].head(1) if not market_recs.empty else pd.DataFrame()
            if not live_market.empty:
                live_row = live_market.iloc[0]
                if live_row["home_team"] == team_a_name:
                    team_a_market = live_row.get("market_home_implied")
                    team_b_market = live_row.get("market_away_implied")
                    team_a_price = live_row.get("home_odds_decimal")
                    team_b_price = live_row.get("away_odds_decimal")
                    team_a_source = live_row.get("best_home_source", live_row.get("best_source"))
                    team_b_source = live_row.get("best_away_source", live_row.get("best_source"))
                else:
                    team_a_market = live_row.get("market_away_implied")
                    team_b_market = live_row.get("market_home_implied")
                    team_a_price = live_row.get("away_odds_decimal")
                    team_b_price = live_row.get("home_odds_decimal")
                    team_a_source = live_row.get("best_away_source", live_row.get("best_source"))
                    team_b_source = live_row.get("best_home_source", live_row.get("best_source"))

                team_a_market = pd.to_numeric(pd.Series([team_a_market]), errors="coerce").iloc[0]
                team_b_market = pd.to_numeric(pd.Series([team_b_market]), errors="coerce").iloc[0]
                team_a_edge = prediction["team_a_win_prob"] - team_a_market if pd.notna(team_a_market) else np.nan
                team_b_edge = prediction["team_b_win_prob"] - team_b_market if pd.notna(team_b_market) else np.nan
                market_best_team = team_a_name if team_a_edge >= team_b_edge else team_b_name
                market_best_edge = team_a_edge if team_a_edge >= team_b_edge else team_b_edge

                st.markdown(
                    """
                    <div class="summary-banner">
                        Live market context found for this matchup. The table below compares the neutral-court tournament model to the
                        currently quoted market prices for both sides.
                    </div>
                    """,
                    unsafe_allow_html=True,
                )

                mc1, mc2, mc3 = st.columns(3)
                mc1.metric("Team A Market", _pct(team_a_market), delta=(f"{team_a_edge:+.1%}" if pd.notna(team_a_edge) else None))
                mc2.metric("Team B Market", _pct(team_b_market), delta=(f"{team_b_edge:+.1%}" if pd.notna(team_b_edge) else None))
                mc3.metric("Best Market Edge", (f"{market_best_edge:+.1%}" if pd.notna(market_best_edge) else "—"), delta=market_best_team)
                st.caption(
                    f"Best price sources: {team_a_name} {team_a_source or '—'} @ "
                    f"{'—' if pd.isna(pd.to_numeric(pd.Series([team_a_price]), errors='coerce').iloc[0]) else f'{float(team_a_price):.2f}'} | "
                    f"{team_b_name} {team_b_source or '—'} @ "
                    f"{'—' if pd.isna(pd.to_numeric(pd.Series([team_b_price]), errors='coerce').iloc[0]) else f'{float(team_b_price):.2f}'}"
                )

            notes = _ncaab_feature_story(prediction, row)
            st.markdown(
                """
                <div class="summary-banner">
                    Seed Edge is bracket-facing. If a live market exists for the matchup, the market cards above show the separate betting-facing edge.
                </div>
                """,
                unsafe_allow_html=True,
            )
            for note in notes:
                st.write(f"- {note}")

            compare = pd.DataFrame(
                {
                    "Metric": [
                        "Seed",
                        "Current Elo",
                        "Composite Rank",
                        "Official NET",
                        "Net Rating",
                        "Scoring Margin",
                        "Win%",
                        "Last 10 Win%",
                        "Last 10 Margin",
                    ],
                    team_a_name: [
                        row.get("team_a_seed_num"),
                        round(float(row.get("team_a_elo", np.nan)), 1) if pd.notna(row.get("team_a_elo")) else "—",
                        round(float(row.get("team_a_median_rank", np.nan)), 1) if pd.notna(row.get("team_a_median_rank")) else "—",
                        round(float(team_a_profile.get("net_rank", np.nan)), 1) if pd.notna(team_a_profile.get("net_rank")) else "—",
                        round(float(row.get("team_a_net_rtg", np.nan)), 2) if pd.notna(row.get("team_a_net_rtg")) else "—",
                        round(float(row.get("team_a_avg_margin", np.nan)), 2) if pd.notna(row.get("team_a_avg_margin")) else "—",
                        round(float(row.get("team_a_win_pct", np.nan)), 3) if pd.notna(row.get("team_a_win_pct")) else "—",
                        round(float(row.get("team_a_last10_win_pct", np.nan)), 3) if pd.notna(row.get("team_a_last10_win_pct")) else "—",
                        round(float(row.get("team_a_last10_margin", np.nan)), 2) if pd.notna(row.get("team_a_last10_margin")) else "—",
                    ],
                    team_b_name: [
                        row.get("team_b_seed_num"),
                        round(float(row.get("team_b_elo", np.nan)), 1) if pd.notna(row.get("team_b_elo")) else "—",
                        round(float(row.get("team_b_median_rank", np.nan)), 1) if pd.notna(row.get("team_b_median_rank")) else "—",
                        round(float(team_b_profile.get("net_rank", np.nan)), 1) if pd.notna(team_b_profile.get("net_rank")) else "—",
                        round(float(row.get("team_b_net_rtg", np.nan)), 2) if pd.notna(row.get("team_b_net_rtg")) else "—",
                        round(float(row.get("team_b_avg_margin", np.nan)), 2) if pd.notna(row.get("team_b_avg_margin")) else "—",
                        round(float(row.get("team_b_win_pct", np.nan)), 3) if pd.notna(row.get("team_b_win_pct")) else "—",
                        round(float(row.get("team_b_last10_win_pct", np.nan)), 3) if pd.notna(row.get("team_b_last10_win_pct")) else "—",
                        round(float(row.get("team_b_last10_margin", np.nan)), 2) if pd.notna(row.get("team_b_last10_margin")) else "—",
                    ],
                }
            )
            st.dataframe(compare, use_container_width=True, hide_index=True)

    with tab_model:
        model = model_bundle[0]
        feature_cols = model_bundle[1]
        if model is None:
            st.warning("NCAA model is not trained yet.")
        else:
            c1, c2, c3, c4 = st.columns(4)
            c1.metric("Log Loss", f"{metrics.get('log_loss', float('nan')):.4f}")
            c2.metric("Brier Score", f"{metrics.get('brier_score', float('nan')):.4f}")
            c3.metric("Accuracy", f"{metrics.get('accuracy', float('nan')):.1%}")
            c4.metric("AUC", f"{metrics.get('auc_roc', float('nan')):.4f}")
            st.caption(
                f"Train seasons: {metrics.get('train_seasons', [])} | Validation: {metrics.get('val_seasons', [])} | "
                f"Test: {metrics.get('test_seasons', [])} | Features: {metrics.get('n_features', '—')}"
            )
            if metrics.get("model_type") == "xgb_linear_blend":
                st.caption(
                    f"Model stack: calibrated XGBoost + calibrated linear blend "
                    f"({metrics.get('xgb_weight', float('nan')):.0%} XGBoost / {metrics.get('linear_weight', float('nan')):.0%} linear)."
                )
            else:
                st.caption("Model stack: calibrated XGBoost.")
            st.caption(
                "Current 2026 projections now include NCAA Elo-style strength, opponent shooting pressure, and recent-form inputs derived from current team-state data."
            )

            plot_cols = st.columns(2)
            calibration_path = ROOT / (ncaab_config.NCAAB_PLOTS_DIR / "calibration.png")
            importance_path = ROOT / (ncaab_config.NCAAB_PLOTS_DIR / "feature_importance.png")
            if calibration_path.exists():
                plot_cols[0].image(str(calibration_path), caption="Calibration")
            if importance_path.exists():
                plot_cols[1].image(str(importance_path), caption="Feature Importance")

            importance_df = pd.DataFrame(
                {"feature": feature_cols, "importance": model.feature_importances_}
            ).sort_values("importance", ascending=False).head(15)
            chart = px.bar(
                importance_df.sort_values("importance"),
                x="importance",
                y="feature",
                orientation="h",
                color="importance",
                color_continuous_scale=["#60a5fa", "#22c55e"],
            )
            chart.update_layout(
                height=520,
                coloraxis_showscale=False,
                paper_bgcolor="#0d0d0d",
                plot_bgcolor="#111111",
                margin=dict(l=10, r=10, t=10, b=10),
                font=dict(color="#f0f0f0"),
            )
            st.plotly_chart(chart, use_container_width=True)

    with tab_teams:
        board = team_features.sort_values(["region", "seed_num", "TeamName"]).copy()
        st.caption("Current projected field as of March 12, 2026.")
        st.dataframe(
            board[
                [
                    "region",
                    "Seed",
                    "TeamName",
                    "elo",
                    "net_rank",
                    "median_rank",
                    "net_rtg",
                    "last10_win_pct",
                    "last10_margin",
                    "win_pct",
                    "srs",
                ]
            ].rename(
                columns={
                    "region": "Region",
                    "Seed": "Seed",
                    "TeamName": "Team",
                    "elo": "Current Elo",
                    "net_rank": "NET",
                    "median_rank": "Composite Rank",
                    "net_rtg": "Net Rating",
                    "last10_win_pct": "Last 10 Win%",
                    "last10_margin": "Last 10 Margin",
                    "win_pct": "Win%",
                    "srs": "SRS",
                }
            ),
            use_container_width=True,
            hide_index=True,
        )


def _run_subprocess(cmd: list[str]) -> tuple[int, str]:
    """Run a subprocess and return (returncode, combined output)."""
    import subprocess
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT))
    output = (result.stdout or "") + (result.stderr or "")
    return result.returncode, output



# ── NBA team colors — brightened for dark background visibility ───────────────
_TEAM_COLORS: dict[str, str] = {
    "ATL": "#E03A3E", "BOS": "#00C45A", "BKN": "#BBBBBB", "CHA": "#8B7FD4",
    "CHI": "#E8475F", "CLE": "#FDBB30", "DAL": "#4B9CD3", "DEN": "#4FA8D5",
    "DET": "#E03A3E", "GSW": "#4B90D9", "HOU": "#E8475F", "IND": "#FDBB30",
    "LAC": "#E03A3E", "LAL": "#9B72CF", "MEM": "#7B9FC4", "MIA": "#F9A01B",
    "MIL": "#00C45A", "MIN": "#4B90D9", "NOP": "#4B90D9", "NYK": "#F58426",
    "OKC": "#44AADD", "ORL": "#3399DD", "PHI": "#3A8FD4", "PHX": "#8B7FD4",
    "POR": "#E03A3E", "SAC": "#9966CC", "SAS": "#CCCCCC", "TOR": "#E8475F",
    "UTA": "#3A8FD4", "WAS": "#E03A3E",
}

def _team_color(abbr: str) -> str:
    return _TEAM_COLORS.get(abbr.upper(), "#3b82f6")

def page_live_games() -> None:
    st.markdown("## Live Games")
    col_cap, col_btn, col_auto = st.columns([4, 1, 1])
    with col_cap:
        st.caption("Live win chances update in real-time using the current score and game clock (blended with our pre-game model). Edge = our probability minus what the market is pricing.")
    with col_btn:
        if st.button("🔄 Refresh", use_container_width=True):
            st.rerun()
    with col_auto:
        auto_live = st.toggle("Auto", value=False, key="live_auto_toggle", help="Auto-refresh every 5 seconds.")

    # Rerun when toggle changes so fragment is re-registered with correct run_every
    if "live_auto_prev" not in st.session_state:
        st.session_state["live_auto_prev"] = auto_live
    if st.session_state["live_auto_prev"] != auto_live:
        st.session_state["live_auto_prev"] = auto_live
        st.rerun()

    @st.fragment(run_every=5 if auto_live else None)
    def _live_board() -> None:
        from src.live_model import fetch_live_games, enrich_with_market_odds
        from src.odds_collection import get_all_market_odds

        with st.spinner("Fetching live scores..."):
            elo_ratings: dict[str, float] = {}
            try:
                elo_df = pd.read_csv("data/processed/elo_history.csv")
                home_elo = elo_df[["home_team","home_elo","game_date"]].rename(columns={"home_team":"team","home_elo":"elo"})
                away_elo = elo_df[["away_team","away_elo","game_date"]].rename(columns={"away_team":"team","away_elo":"elo"})
                current_elo = pd.concat([home_elo, away_elo]).sort_values("game_date").groupby("team")["elo"].last()
                elo_ratings = current_elo.to_dict()
            except Exception:
                pass

            pregame_probs: dict[tuple[str, str], float] = {}
            try:
                from src.injuries import apply_live_availability_adjustments
                from scripts.daily_predictions import get_todays_features
                from src.predict import predict_batch
                features = get_todays_features()
                if not features.empty:
                    preds = predict_batch(features)
                    preds = apply_live_availability_adjustments(preds)
                    for _, row in preds.iterrows():
                        pregame_probs[(row["home_team"], row["away_team"])] = float(row["home_win_prob"])
            except Exception:
                pass

            live_df = fetch_live_games(elo_ratings=elo_ratings, pregame_probs=pregame_probs)
            if live_df.empty:
                st.info("No NBA games right now. Check back during game time.", icon="🏀")
                return

            try:
                odds_df = get_all_market_odds(snapshot_context="streamlit_live")
                live_df = enrich_with_market_odds(live_df, odds_df)
            except Exception:
                pass

        live_games  = live_df[live_df["game_status"] == 2].copy() if "game_status" in live_df.columns else pd.DataFrame()
        pre_games   = live_df[live_df["game_status"] == 1].copy() if "game_status" in live_df.columns else pd.DataFrame()
        final_games = live_df[live_df["game_status"] == 3].copy() if "game_status" in live_df.columns else pd.DataFrame()

        def render_game_card(row: pd.Series, is_live: bool = False) -> None:
            h, a = row["home_team"], row["away_team"]
            hs, as_ = int(row.get("home_score", 0)), int(row.get("away_score", 0))
            h_prob = float(row.get("live_home_prob", 0.5))
            a_prob = float(row.get("live_away_prob", 0.5))
            status_text = str(row.get("game_status_text", ""))
    
            # Parse clock display
            period = row.get("period", 0)
            clock_raw = str(row.get("clock", "")).strip()
            secs_rem = row.get("seconds_remaining", None)
    
            def _fmt_clock(clock_str: str) -> str:
                import re
                m = re.match(r"PT(\d+)M([\d.]+)S", clock_str)
                if m:
                    mins, secs = int(m.group(1)), int(float(m.group(2)))
                    return f"{mins}:{secs:02d}"
                return clock_str
    
            if is_live and period:
                period_label = f"OT{period-4}" if period > 4 else f"Q{period}"
                clock_display = _fmt_clock(clock_raw) if clock_raw else "—"
                center_html = (
                    f"<div style='text-align:center;padding-top:12px;line-height:1.6'>"
                    f"<div style='font-size:0.7rem;color:#888;letter-spacing:0.08em;text-transform:uppercase'>Live</div>"
                    f"<div style='font-size:1.1rem;font-weight:700;color:#f0f0f0'>{period_label}</div>"
                    f"<div style='font-size:1.4rem;font-weight:700;color:#22c55e;font-variant-numeric:tabular-nums'>{clock_display}</div>"
                    f"</div>"
                )
            else:
                center_html = (
                    f"<div style='text-align:center;padding-top:20px'>"
                    f"<b>{status_text}</b>"
                    f"</div>"
                )
    
            a_color = _team_color(a)
            h_color = _team_color(h)

            # Detect score changes for flash animation
            _sk = f"live_score_{h}_{a}"
            _prev = st.session_state.get(_sk, (None, None))
            _a_flash = "score-flash" if _prev[1] is not None and _prev[1] != as_ else ""
            _h_flash = "score-flash" if _prev[0] is not None and _prev[0] != hs else ""
            st.session_state[_sk] = (hs, as_)

            # Scores + win prob bars
            # Game card
            clock_inner = center_html.replace(
                "<div style='text-align:center;padding-top:12px;line-height:1.6'>", "<div style='line-height:1.5'>"
            ).replace(
                "<div style='text-align:center;padding-top:20px'>", "<div style='text-align:center'>"
            )
            # Build per-element animation CSS only when score changed.
            # Stable IDs + no animation CSS = no animation when unchanged.
            _aid = f"sc-{a}-away"
            _hid = f"sc-{h}-home"
            _kf = """@keyframes scoreFlash {
                    0%   { color:#fff; transform:scale(1.18); text-shadow:0 0 24px #22c55e,0 0 8px #22c55e; }
                    60%  { color:#fff; transform:scale(1.06); text-shadow:0 0 10px #22c55e66; }
                    100% { color:#f0f0f0; transform:scale(1); text-shadow:none; }
                  }"""
            _a_css = f"#{_aid} {{ display:inline-block; animation:scoreFlash 0.75s ease-out forwards; }}" if _a_flash else f"#{_aid} {{ display:inline-block; }}"
            _h_css = f"#{_hid} {{ display:inline-block; animation:scoreFlash 0.75s ease-out forwards; }}" if _h_flash else f"#{_hid} {{ display:inline-block; }}"
            _style_block = f"<style>{_kf if (_a_flash or _h_flash) else ''}{_a_css}{_h_css}</style>" if (_a_flash or _h_flash) else ""
            st.markdown(
                f"""{_style_block}
                <div style='border:1px solid #222;border-radius:10px;padding:20px 28px;margin-bottom:10px'>
                  <div style='display:flex;align-items:center;justify-content:space-between;gap:16px'>
                    <div style='flex:1'>
                      <div style='font-size:0.7rem;color:#444;text-transform:uppercase;letter-spacing:0.1em'>Away</div>
                      <div style='font-size:1.2rem;font-weight:700;color:{a_color};margin:2px 0'>{a}</div>
                      <div id='{_aid}' style='font-size:2.6rem;font-weight:800;color:#f0f0f0;line-height:1;font-variant-numeric:tabular-nums'>{as_}</div>
                      <div style='font-size:1.15rem;font-weight:700;color:{"#22c55e" if a_prob > h_prob else "#ef4444"};margin-top:5px'>{a_prob:.0%} <span style="font-size:0.72rem;font-weight:400;color:#555">to win</span></div>
                    </div>
                    <div style='text-align:center;min-width:90px'>{clock_inner}</div>
                    <div style='flex:1;text-align:right'>
                      <div style='font-size:0.7rem;color:#444;text-transform:uppercase;letter-spacing:0.1em'>Home</div>
                      <div style='font-size:1.2rem;font-weight:700;color:{h_color};margin:2px 0'>{h}</div>
                      <div id='{_hid}' style='font-size:2.6rem;font-weight:800;color:#f0f0f0;line-height:1;font-variant-numeric:tabular-nums'>{hs}</div>
                      <div style='font-size:1.15rem;font-weight:700;color:{"#22c55e" if h_prob > a_prob else "#ef4444"};margin-top:5px'>{h_prob:.0%} <span style="font-size:0.72rem;font-weight:400;color:#555">to win</span></div>
                    </div>
                  </div>
                </div>""",
                unsafe_allow_html=True,
            )

            # Market odds
            k_h  = row.get("kalshi_home_prob")
            k_a  = row.get("kalshi_away_prob")
            pm_h = row.get("polymarket_home_prob")
            pm_a = row.get("polymarket_away_prob")
            has_kalshi = pd.notna(k_h) and pd.notna(k_a)
            has_poly   = pd.notna(pm_h) and pd.notna(pm_a)

            if has_kalshi or has_poly:
                mk1, mk2 = st.columns(2)
                with mk1:
                    if has_kalshi:
                        st.markdown(
                            f"<div style='background:#1a1a1a;border:1px solid #2a2a2a;border-radius:6px;"
                            f"padding:8px 12px;font-size:0.82rem;margin-top:6px'>"
                            f"<span style='color:#555;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.06em'>Kalshi</span><br>"
                            f"<span style='color:{'#22c55e' if float(k_a) > float(k_h) else '#ef4444'};font-weight:700'>{a} {float(k_a):.0%}</span>"
                            f"<span style='color:#444'> vs </span>"
                            f"<span style='color:{'#22c55e' if float(k_h) > float(k_a) else '#ef4444'};font-weight:700'>{h} {float(k_h):.0%}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )
                with mk2:
                    if has_poly:
                        st.markdown(
                            f"<div style='background:#1a1a1a;border:1px solid #2a2a2a;border-radius:6px;"
                            f"padding:8px 12px;font-size:0.82rem;margin-top:6px'>"
                            f"<span style='color:#555;font-size:0.72rem;text-transform:uppercase;letter-spacing:0.06em'>Polymarket</span>"
                            f"<span style='color:#444;font-size:0.65rem'> · pre-game price</span><br>"
                            f"<span style='color:{'#22c55e' if float(pm_a) > float(pm_h) else '#ef4444'};font-weight:700'>{a} {float(pm_a):.0%}</span>"
                            f"<span style='color:#444'> vs </span>"
                            f"<span style='color:{'#22c55e' if float(pm_h) > float(pm_a) else '#ef4444'};font-weight:700'>{h} {float(pm_h):.0%}</span>"
                            f"</div>",
                            unsafe_allow_html=True,
                        )

            # Pre-game context
            pg_prob = row.get("pregame_home_prob")
            if pd.notna(pg_prob):
                pg_a = 1 - float(pg_prob)
                pg_h = float(pg_prob)
                st.markdown(
                    f"""<div style='border:1px solid #1e1e1e;border-radius:8px;padding:10px 16px;margin:6px 0;
                          display:flex;align-items:center;justify-content:space-between;gap:12px'>
                      <div>
                        <div style='font-size:0.65rem;color:#444;text-transform:uppercase;letter-spacing:0.1em;margin-bottom:3px'>Pre-game prediction (XGBoost)</div>
                        <div style='display:flex;gap:20px;align-items:center'>
                          <span style='color:{'#22c55e' if pg_a > pg_h else '#ef4444'};font-weight:700;font-size:1rem'>{a} {pg_a:.0%}</span>
                          <span style='color:#333;font-size:0.8rem'>vs</span>
                          <span style='color:{'#22c55e' if pg_h > pg_a else '#ef4444'};font-weight:700;font-size:1rem'>{h} {pg_h:.0%}</span>
                        </div>
                      </div>
                      <div style='font-size:0.7rem;color:#444;text-align:right'>live weight grows<br>as game progresses</div>
                    </div>""",
                    unsafe_allow_html=True,
                )

            # Edge callout
            h_edge = row.get("live_home_edge")
            a_edge = row.get("live_away_edge")
            if pd.notna(h_edge) and pd.notna(a_edge):
                h_mkt = row.get("market_home_live")
                a_mkt = row.get("market_away_live")
                best_side = "home" if abs(float(h_edge)) >= abs(float(a_edge)) else "away"
                best_team  = h if best_side == "home" else a
                best_edge  = float(h_edge) if best_side == "home" else float(a_edge)
                best_mkt   = float(h_mkt if best_side == "home" else a_mkt)
                our_prob   = float(h_prob if best_side == "home" else a_prob)
                if best_edge >= 0.05:
                    st.success(f"**Edge: Bet {best_team}** — model {our_prob:.0%} vs market {best_mkt:.0%} (+{best_edge:.0%})", icon="📈")
                elif best_edge >= 0.02:
                    st.warning(f"Marginal edge on {best_team} — model {our_prob:.0%} vs market {best_mkt:.0%} (+{best_edge:.0%})", icon="⚠️")
                else:
                    st.caption("No edge — market is fairly priced.")
            st.divider()
    
        if not live_games.empty:
            st.markdown("### In Progress")
            for _, row in live_games.iterrows():
                render_game_card(row, is_live=True)

        if not pre_games.empty:
            st.markdown("### Upcoming Today")
            for _, row in pre_games.iterrows():
                render_game_card(row, is_live=False)

        if not final_games.empty:
            st.markdown("### Final")
            for _, row in final_games.iterrows():
                render_game_card(row, is_live=False)

    _live_board()




def page_ops_monitor() -> None:
    st.markdown("## System")

    # ── Action buttons ────────────────────────────────────────────────────────
    st.markdown("### Actions")
    col_settle, col_update = st.columns(2)

    with col_settle:
        st.markdown("**Settle Yesterday's Results**")
        st.caption("Fetches last night's scores from nba_api and marks each prediction as win/loss.")
        if st.button("Settle Results", use_container_width=True):
            with st.spinner("Fetching results and settling predictions..."):
                code, out = _run_subprocess([sys.executable, "scripts/settle_results.py"])
            if code == 0:
                st.success("Settled! Check Bet Tracker for updated P&L.")
            else:
                st.error("Settle failed.")
            with st.expander("Output"):
                st.code(out)

    with col_update:
        st.markdown("**Update & Retrain Model**")
        st.caption("Pulls the latest games, rebuilds features, and retrains the model. Takes ~2 min.")
        if st.button("Update Model", use_container_width=True, type="primary"):
            with st.spinner("Step 1/2: Rebuilding dataset with latest games..."):
                code1, out1 = _run_subprocess([sys.executable, "scripts/build_dataset.py"])
            if code1 != 0:
                st.error("Dataset build failed.")
                with st.expander("Output"):
                    st.code(out1)
            else:
                with st.spinner("Step 2/2: Retraining model..."):
                    code2, out2 = _run_subprocess([sys.executable, "scripts/train.py"])
                if code2 == 0:
                    st.success("Model updated! Refresh Today's Picks to use the new model.")
                    st.cache_data.clear()
                else:
                    st.error("Training failed.")
                with st.expander("Build output"):
                    st.code(out1)
                with st.expander("Train output"):
                    st.code(out2)

    st.markdown("---")

    alerts = load_alerts_df()
    snapshots = load_market_snapshots_df()
    trades = pd.DataFrame()
    paper_path = ROOT / config.PAPER_TRADES_CSV
    if paper_path.exists():
        trades = pd.read_csv(paper_path)

    latest_snapshot = snapshots["snapshot_at"].max() if not snapshots.empty and "snapshot_at" in snapshots.columns else pd.NaT
    snapshot_age_seconds = (
        (pd.Timestamp.now(tz="UTC") - latest_snapshot).total_seconds()
        if pd.notna(latest_snapshot)
        else np.nan
    )
    stale = pd.notna(snapshot_age_seconds) and snapshot_age_seconds > config.MARKET_SNAPSHOT_TTL_SECONDS * 3

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Recent Alerts (24h)", len(alerts[alerts["created_at"] >= pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24)]) if not alerts.empty and "created_at" in alerts.columns else 0)
    c2.metric("Stored Snapshots", len(snapshots))
    c3.metric("Latest Snapshot", "Stale" if stale else "Fresh" if pd.notna(latest_snapshot) else "Missing")
    c4.metric("Paper Trades Logged", len(trades))

    st.markdown("---")

    if pd.notna(latest_snapshot):
        st.caption(
            f"Last market snapshot: {latest_snapshot.tz_convert('America/New_York').strftime('%b %d, %I:%M:%S %p ET')}"
        )

    st.markdown('<div class="section-header">Recent Alerts</div>', unsafe_allow_html=True)
    if alerts.empty:
        st.success("No alerts recorded.", icon="✅")
    else:
        st.dataframe(
            alerts[[c for c in ["created_at", "severity", "code", "message", "context"] if c in alerts.columns]].head(50),
            use_container_width=True,
            hide_index=True,
        )

    st.markdown('<div class="section-header">Snapshot Coverage</div>', unsafe_allow_html=True)
    if snapshots.empty:
        st.info("No market snapshots recorded yet.", icon="📡")
    else:
        coverage = (
            snapshots.groupby(["home_team", "away_team"])
            .agg(
                snapshots=("snapshot_at", "count"),
                first_seen=("snapshot_at", "min"),
                last_seen=("snapshot_at", "max"),
            )
            .reset_index()
            .sort_values("last_seen", ascending=False)
        )
        st.dataframe(coverage.head(50), use_container_width=True, hide_index=True)


# ─────────────────────────────────────────────────────────────────────────────
# Main router
# ─────────────────────────────────────────────────────────────────────────────

if page == "Today's Picks":
    page_todays_picks()
elif page == "Paper Trader":
    page_paper_trader()
elif page == "Model Accuracy":
    page_model_performance()
elif page == "NBA Matchup":
    page_nba_matchup()
elif page == "Team Explorer":
    page_team_explorer()
elif page == "Bet Tracker":
    page_bet_tracker()
elif page == "NCAAM":
    page_ncaam()
elif page == "Live Games":
    page_live_games()
elif page == "System":
    page_ops_monitor()
