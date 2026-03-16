"""
ncaab_app.py - Streamlit app for March Madness predictions.

Run with:
    streamlit run ncaab_app.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).parent
sys.path.insert(0, str(ROOT))

import ncaab_config
from src.ncaab_bracket_viz import BRACKET_CSS, build_bracket_html
from src.ncaab_model import load_model
from src.ncaab_odds import get_all_ncaab_market_odds
from src.ncaab_predict import (
    generate_market_recommendation_table,
    load_seed_matchup_baselines,
    predict_market_games,
    predict_matchup,
)
from src.runtime import setup_project_logging

st.set_page_config(
    layout="wide",
    page_title="March Machine",
    page_icon="🏀",
    initial_sidebar_state="expanded",
)

logger = setup_project_logging(__name__, "ncaab_app.log")

st.markdown(
    """
    <style>
    :root {
        --canvas: #0b0e11;
        --ink: #f6fbfa;
        --muted: rgba(233, 240, 238, 0.58);
        --panel: rgba(17, 21, 25, 0.9);
        --line: rgba(255, 255, 255, 0.08);
        --green: #7ef0a8;
        --gold: #7dd3fc;
        --red: #ff857e;
        --shadow: 0 22px 44px rgba(0, 0, 0, 0.26);
    }

    [data-testid="stAppViewContainer"] {
        background:
            radial-gradient(circle at top left, rgba(34,197,94,0.16), transparent 22%),
            radial-gradient(circle at top right, rgba(59,130,246,0.16), transparent 18%),
            linear-gradient(180deg, #090b0d 0%, #11151a 100%);
        color: var(--ink);
        font-family: "SF Pro Display", "Avenir Next", "Segoe UI", sans-serif;
    }
    [data-testid="stSidebar"] {
        background: linear-gradient(180deg, rgba(11,14,17,0.98) 0%, rgba(15,20,24,0.98) 100%);
        border-right: 1px solid rgba(255,255,255,0.08);
    }
    [data-testid="stSidebar"] * {
        color: #f8fbfa !important;
    }
    .hero {
        background:
            radial-gradient(circle at 12% 18%, rgba(34,197,94,0.18), transparent 24%),
            radial-gradient(circle at 88% 16%, rgba(59,130,246,0.16), transparent 20%),
            linear-gradient(135deg, rgba(10,12,15,0.96), rgba(17,21,25,0.94));
        color: #f8fbfa;
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 22px;
        padding: 28px 30px;
        box-shadow: var(--shadow);
        margin-bottom: 18px;
    }
    .hero-kicker {
        letter-spacing: 0.14em;
        text-transform: uppercase;
        font-size: 0.76rem;
        color: rgba(248,251,250,0.56);
        margin-bottom: 0.55rem;
    }
    .hero h1 {
        margin: 0;
        font-size: 2.35rem;
        line-height: 1;
    }
    .hero p {
        margin: 0.9rem 0 0 0;
        max-width: 58rem;
        color: rgba(248,251,250,0.72);
        font-size: 1rem;
        line-height: 1.6;
    }
    [data-testid="stMetric"] {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 18px;
        box-shadow: var(--shadow);
        padding: 14px 16px;
    }
    [data-testid="stTabs"] [role="tablist"] {
        gap: 6px;
        border-bottom: 1px solid var(--line);
    }
    [data-testid="stTabs"] [role="tab"] {
        border-radius: 999px;
        padding: 8px 16px;
        background: transparent;
        color: var(--muted);
    }
    [data-testid="stTabs"] [aria-selected="true"] {
        background: rgba(255,255,255,0.06);
        border: 1px solid rgba(255,255,255,0.08);
        color: #f8fbfa;
    }
    .panel {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 18px 20px;
        box-shadow: var(--shadow);
    }
    .callout {
        background: rgba(255,255,255,0.05);
        border: 1px solid rgba(255,255,255,0.08);
        border-radius: 16px;
        padding: 14px 16px;
        color: var(--ink);
        margin-bottom: 14px;
    }
    .round-chip {
        display: inline-block;
        padding: 4px 10px;
        border-radius: 999px;
        background: rgba(255,255,255,0.06);
        color: var(--green);
        font-size: 0.78rem;
        font-weight: 700;
        letter-spacing: 0.06em;
        text-transform: uppercase;
    }
    .pick-card {
        background: rgba(255,255,255,0.04);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 14px 16px;
        margin-bottom: 10px;
        box-shadow: var(--shadow);
    }
    .pick-card strong {
        color: var(--green);
    }
    """
    + BRACKET_CSS
    + """
    </style>
    """,
    unsafe_allow_html=True,
)


@st.cache_data(show_spinner=False)
def load_metrics() -> dict:
    if not ncaab_config.NCAAB_METRICS_JSON.exists():
        return {}
    return json.loads(ncaab_config.NCAAB_METRICS_JSON.read_text())


@st.cache_data(show_spinner=False)
def load_team_features_df() -> pd.DataFrame:
    if ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV.exists():
        return pd.read_csv(ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV)
    return pd.DataFrame()


@st.cache_data(show_spinner=False, ttl=300)
def load_market_recommendations_df() -> pd.DataFrame:
    odds = get_all_ncaab_market_odds(snapshot_context="streamlit_ncaab_standalone")
    if odds.empty:
        return pd.DataFrame()
    recs = generate_market_recommendation_table(
        predict_market_games(
            odds,
            team_features=load_team_features_df(),
            model_bundle=load_trained_model(),
            seed_baselines=load_seed_matchup_baselines(),
        ),
        odds_df=odds,
    )
    return recs


@st.cache_data(show_spinner=False)
def load_current_meta() -> dict:
    if not ncaab_config.NCAAB_CURRENT_META_JSON.exists():
        return {}
    return json.loads(ncaab_config.NCAAB_CURRENT_META_JSON.read_text())


@st.cache_data(show_spinner=False)
def load_bracket_df() -> pd.DataFrame:
    if ncaab_config.NCAAB_CURRENT_PROJECTED_BRACKET_CSV.exists():
        return pd.read_csv(ncaab_config.NCAAB_CURRENT_PROJECTED_BRACKET_CSV)
    return pd.DataFrame()


@st.cache_resource(show_spinner=False)
def load_trained_model():
    return load_model()


def require_artifacts() -> bool:
    missing = [
        path
        for path in [
            ncaab_config.NCAAB_METRICS_JSON,
            ncaab_config.NCAAB_MODEL_DIR / "calibrated_model.joblib",
            ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV,
            ncaab_config.NCAAB_CURRENT_PROJECTED_BRACKET_CSV,
            ncaab_config.NCAAB_CURRENT_META_JSON,
        ]
        if not path.exists()
    ]
    if missing:
        st.error(
            "NCAA artifacts are missing. Run `python scripts/build_ncaab_dataset.py`, `python scripts/train_ncaab.py`, and `python scripts/update_ncaab_current.py` first."
        )
        return False
    return True


def feature_story(row: pd.Series) -> list[str]:
    notes: list[str] = []
    seed_diff = float(row.get("seed_num_diff", 0))
    net_diff = float(row.get("net_rtg_diff", 0))
    rank_diff = float(row.get("median_rank_diff", 0))
    margin_diff = float(row.get("avg_margin_diff", 0))
    win_pct_diff = float(row.get("win_pct_diff", 0))

    if seed_diff < 0:
        notes.append(f"{row['team_a_name']} has the stronger projected seed line.")
    elif seed_diff > 0:
        notes.append(f"{row['team_b_name']} has the stronger projected seed line.")

    if abs(net_diff) >= 4:
        favorite = row["team_a_name"] if net_diff > 0 else row["team_b_name"]
        notes.append(f"{favorite} carries the stronger full-season efficiency margin.")

    if abs(rank_diff) >= 8:
        favorite = row["team_a_name"] if rank_diff < 0 else row["team_b_name"]
        notes.append(f"{favorite} sits higher in the current official NET rankings.")

    if abs(margin_diff) >= 4:
        favorite = row["team_a_name"] if margin_diff > 0 else row["team_b_name"]
        notes.append(f"{favorite} owns the better scoring margin profile.")

    if abs(win_pct_diff) >= 0.10:
        favorite = row["team_a_name"] if win_pct_diff > 0 else row["team_b_name"]
        notes.append(f"{favorite} has the stronger season-long win rate.")

    return notes[:4]


def pct(value, decimals: int = 1) -> str:
    numeric = pd.to_numeric(pd.Series([value]), errors="coerce").iloc[0]
    if pd.isna(numeric):
        return "—"
    return f"{numeric:.{decimals}%}"


def render_header() -> None:
    meta = load_current_meta()
    projection_date = meta.get("projection_date", ncaab_config.CURRENT_PROJECTION_DATE)
    st.markdown(
        """
        <div class="hero">
            <div class="hero-kicker">March Madness ML Lab</div>
            <h1>March Machine</h1>
            <p>
                A separate NCAAB tournament dashboard built around a calibrated XGBoost model trained on
                historical NCAA tournament games, seeded with regular-season team profiles, Elo, and final
                Massey ranking signals.
            </p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.markdown(
        f"""
        <div class="callout">
            Projected field updated through <strong>{projection_date}</strong>. This is a projection before Selection Sunday on
            <strong>March 15, 2026</strong>, not the official bracket. Market Edge on the picks board means model probability minus
            the live sportsbook/Kalshi price. Seed Edge in the bracket tools means model probability minus the historical win rate for that seed matchup.
        </div>
        """,
        unsafe_allow_html=True,
    )


def page_market() -> None:
    recs = load_market_recommendations_df()

    st.markdown("## Today's Picks")
    st.caption(
        "Only games where both teams are in the projected March Madness field are shown. "
        "The model prices them on a neutral-court basis so the board lines up with the tournament use case."
    )

    if recs.empty:
        st.info("No live sportsbook or Kalshi games currently match two projected tournament teams.")
        return

    bets = recs[recs["bet"]].copy()
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Games priced", len(recs))
    c2.metric("Bets flagged", int(bets["bet"].sum()) if not bets.empty else 0)
    c3.metric("Biggest edge", pct(recs["best_edge"].max()))
    c4.metric("Avg Kelly", pct(bets["kelly"].mean()) if not bets.empty else "—")

    def market_view(df: pd.DataFrame) -> pd.DataFrame:
        view = df.copy()
        view["Tipoff"] = pd.to_datetime(view.get("tipoff_utc"), errors="coerce", utc=True).dt.tz_convert("America/New_York").dt.strftime("%b %d, %I:%M %p")
        view["Matchup"] = view["away_team"].astype(str) + " vs " + view["home_team"].astype(str)
        view["Pick"] = view["bet_team"]
        view["Model"] = view["bet_prob"].map(pct)
        view["Market"] = view["bet_market"].map(pct)
        view["Edge"] = view["best_edge"].map(pct)
        view["Seed Edge"] = view["seed_edge"].map(pct)
        view["Best Price"] = pd.to_numeric(view["bet_odds_decimal"], errors="coerce").map(lambda value: "—" if pd.isna(value) else f"{value:.2f}")
        view["Kelly %"] = view["kelly"].map(pct)
        view["Source"] = view["best_source"].fillna("—")
        return view[["Tipoff", "Matchup", "Pick", "Model", "Market", "Edge", "Seed Edge", "Best Price", "Kelly %", "confidence", "Source"]]

    if not bets.empty:
        st.markdown("### Best Value Bets")
        st.dataframe(market_view(bets), use_container_width=True, hide_index=True)

    st.markdown("### Full Market Board")
    st.dataframe(market_view(recs), use_container_width=True, hide_index=True)


def page_bracket_builder() -> None:
    bracket = load_bracket_df()
    team_features = load_team_features_df()

    st.markdown("## Bracket Builder")
    st.caption(
        "A visual bracket generated from the current projected field. Each matchup advances the team with the higher calibrated model win probability."
    )
    builder_html = build_bracket_html(bracket, team_features)
    if builder_html:
        st.markdown(builder_html, unsafe_allow_html=True)
    else:
        st.info("Visual bracket unavailable because the projected bracket artifact is incomplete.")


def page_bracket() -> None:
    bracket = load_bracket_df()
    meta = load_current_meta()

    title_col, info_col = st.columns([1.3, 1.0])
    with title_col:
        st.markdown("## Projected 2026 Bracket Board")
        st.markdown(
            f'<div class="callout">Source: <a href="{meta.get("projection_source_url", ncaab_config.CURRENT_BRACKETOLOGY_URL)}" target="_blank">Inside the Hall bracketology</a>. The board is simulated deterministically: every slot advances the team with the higher model win probability.</div>',
            unsafe_allow_html=True,
        )
    with info_col:
        final = bracket[bracket["round"] == "National Championship"].tail(1)
        champion = final["winner_name"].iloc[0] if not final.empty else "—"
        title_prob = final["win_prob"].iloc[0] if not final.empty else float("nan")
        st.metric("Projected champion", champion)
        st.metric("Title game win prob", f"{title_prob:.1%}" if pd.notna(title_prob) else "—")

    for round_name in [
        "First Four",
        "Round of 64",
        "Round of 32",
        "Sweet 16",
        "Elite 8",
        "Final Four",
        "National Championship",
    ]:
        round_games = bracket[bracket["round"] == round_name]
        if round_games.empty:
            continue
        st.markdown(f'<span class="round-chip">{round_name}</span>', unsafe_allow_html=True)
        columns = st.columns(2 if round_name in {"Round of 64", "Round of 32"} else 1)
        for idx, game in round_games.reset_index(drop=True).iterrows():
            with columns[idx % len(columns)]:
                loser_name = game["team_b_name"] if game["winner_id"] == game["team_a_id"] else game["team_a_name"]
                st.markdown(
                    f"""
                    <div class="pick-card">
                        <div><strong>{game['winner_name']}</strong> over {loser_name}</div>
                        <div style="color:#5f6d63; margin-top:4px;">{game['team_a_name']} vs {game['team_b_name']}</div>
                        <div style="margin-top:8px; color:#10231a;">Win probability: {game['win_prob']:.1%}</div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )


def page_matchup_lab() -> None:
    team_features = load_team_features_df()
    season = int(team_features["Season"].iloc[0])
    season_df = team_features.sort_values(["region", "seed_num", "TeamName"])
    team_names = season_df["TeamName"].tolist()
    team_a_name = st.selectbox("Team A", team_names, index=0)
    team_b_name = st.selectbox("Team B", team_names, index=min(1, len(team_names) - 1))

    if team_a_name == team_b_name:
        st.info("Choose two different teams.")
        return

    team_a_id = int(season_df.loc[season_df["TeamName"] == team_a_name, "TeamID"].iloc[0])
    team_b_id = int(season_df.loc[season_df["TeamName"] == team_b_name, "TeamID"].iloc[0])
    prediction = predict_matchup(int(season), team_a_id, team_b_id, team_features=team_features)
    row = prediction["feature_row"].iloc[0]

    st.markdown("## Matchup Lab")
    st.caption("Current projected tournament field as of March 12, 2026.")
    left, right = st.columns(2)
    with left:
        st.metric(team_a_name, f"{prediction['team_a_win_prob']:.1%}")
    with right:
        st.metric(team_b_name, f"{prediction['team_b_win_prob']:.1%}")

    story = feature_story(row)
    if story:
        st.markdown('<div class="panel">', unsafe_allow_html=True)
        st.markdown("### Why the model leans this way")
        for note in story:
            st.write(f"- {note}")
        st.markdown("</div>", unsafe_allow_html=True)

    compare = pd.DataFrame(
        {
            "metric": ["Seed", "NET Rank", "Net Rating", "Scoring Margin", "Win%"],
            team_a_name: [
                row["team_a_seed_num"],
                round(row["team_a_median_rank"], 1),
                round(row["team_a_net_rtg"], 2),
                round(row["team_a_avg_margin"], 2),
                round(row["team_a_win_pct"], 3),
            ],
            team_b_name: [
                row["team_b_seed_num"],
                round(row["team_b_median_rank"], 1),
                round(row["team_b_net_rtg"], 2),
                round(row["team_b_avg_margin"], 2),
                round(row["team_b_win_pct"], 3),
            ],
        }
    )
    st.dataframe(compare, use_container_width=True, hide_index=True)


def page_model_report() -> None:
    metrics = load_metrics()
    model, feature_cols, _ = load_trained_model()

    st.markdown("## Model Report")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Log Loss", f"{metrics.get('log_loss', float('nan')):.4f}")
    c2.metric("Brier Score", f"{metrics.get('brier_score', float('nan')):.4f}")
    c3.metric("Accuracy", f"{metrics.get('accuracy', float('nan')):.1%}")
    c4.metric("AUC", f"{metrics.get('auc_roc', float('nan')):.4f}")

    st.markdown(
        f"""
        <div class="callout">
            Train seasons: {min(metrics.get('train_seasons', [0]))}-{max(metrics.get('train_seasons', [0]))}
            &nbsp;|&nbsp; Validation: {metrics.get('val_seasons', ['—'])}
            &nbsp;|&nbsp; Test: {metrics.get('test_seasons', ['—'])}
            &nbsp;|&nbsp; Features: {metrics.get('n_features', '—')}
        </div>
        """,
        unsafe_allow_html=True,
    )
    st.caption("The live bracket board applies this historical tournament model to the projected 2026 field using current team stats and current NET rankings.")

    left, right = st.columns(2)
    with left:
        if (ncaab_config.NCAAB_PLOTS_DIR / "calibration.png").exists():
            st.image(str(ncaab_config.NCAAB_PLOTS_DIR / "calibration.png"), caption="Calibration")
    with right:
        if (ncaab_config.NCAAB_PLOTS_DIR / "feature_importance.png").exists():
            st.image(str(ncaab_config.NCAAB_PLOTS_DIR / "feature_importance.png"), caption="Feature Importance")

    importance_df = pd.DataFrame(
        {"feature": feature_cols, "importance": model.feature_importances_}
    ).sort_values("importance", ascending=False).head(15)
    chart = px.bar(
        importance_df.sort_values("importance"),
        x="importance",
        y="feature",
        orientation="h",
        color="importance",
        color_continuous_scale=["#c9b179", "#143a2d"],
    )
    chart.update_layout(
        height=520,
        coloraxis_showscale=False,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=10, b=10),
    )
    st.plotly_chart(chart, use_container_width=True)


def page_team_board() -> None:
    team_features = load_team_features_df()
    season_df = team_features.sort_values(["region", "seed_num", "TeamName"])

    st.markdown("## Projected Team Board")
    st.dataframe(
        season_df[
            [
                "region",
                "Seed",
                "TeamName",
                "median_rank",
                "net_rtg",
                "win_pct",
                "avg_margin",
                "srs",
            ]
        ].rename(
            columns={
                "region": "Region",
                "Seed": "Seed",
                "TeamName": "Team",
                "median_rank": "NET Rank",
                "net_rtg": "Net Rating",
                "win_pct": "Win%",
                "avg_margin": "Scoring Margin",
                "srs": "SRS",
            }
        ),
        use_container_width=True,
        hide_index=True,
    )


def main() -> None:
    render_header()
    if not require_artifacts():
        return

    st.sidebar.markdown("## Views")
    view = st.sidebar.radio(
        "Page",
        ["Today's Picks", "Bracket Builder", "Bracket Board", "Matchup Lab", "Model Report", "Team Board"],
        label_visibility="collapsed",
    )

    if view == "Today's Picks":
        page_market()
    elif view == "Bracket Builder":
        page_bracket_builder()
    elif view == "Bracket Board":
        page_bracket()
    elif view == "Matchup Lab":
        page_matchup_lab()
    elif view == "Model Report":
        page_model_report()
    else:
        page_team_board()


if __name__ == "__main__":
    main()
