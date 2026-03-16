"""
ncaab_predict.py - Matchup and bracket predictions for the March Madness app.
"""

from __future__ import annotations

import logging

import numpy as np
import pandas as pd

import ncaab_config
import config
from src.evaluate import kelly_fraction
from src.ncaab_data import load_raw_csv
from src.ncaab_features import build_matchup_feature_row, slot_round_label
from src.ncaab_model import load_model

logger = logging.getLogger(__name__)


def apply_elo_anchor_probability(raw_prob: float, elo_diff: float | None) -> float:
    """Shrink extreme NCAA model outputs toward a neutral-site Elo baseline."""
    prob = float(np.clip(raw_prob, 1e-6, 1.0 - 1e-6))
    if not ncaab_config.ENABLE_ELO_SHRINK:
        return prob
    try:
        elo_gap = float(elo_diff)
    except (TypeError, ValueError):
        return prob
    if not np.isfinite(elo_gap):
        return prob

    elo_baseline = 1.0 / (1.0 + 10.0 ** (-elo_gap / 400.0))
    shrink = float(
        np.clip(
            1.0 - (abs(elo_gap) - ncaab_config.ELO_SHRINK_RAMP_START) / ncaab_config.ELO_SHRINK_RAMP_SCALE,
            ncaab_config.ELO_SHRINK_MIN,
            1.0,
        )
    )
    adjusted = elo_baseline + shrink * (prob - elo_baseline)
    return float(np.clip(adjusted, 1e-6, 1.0 - 1e-6))


def _predict_ordered_matchup_probs(
    feature_row: pd.DataFrame,
    model,
    feature_cols: list[str],
    fill_values: pd.Series,
) -> tuple[float, float]:
    """Return raw and post-anchor win probabilities for one ordered matchup row."""
    X = feature_row.reindex(columns=feature_cols).fillna(fill_values.reindex(feature_cols))
    raw_prob = float(model.predict_proba(X)[:, 1][0])
    elo_diff = pd.to_numeric(feature_row.get("elo_diff"), errors="coerce").iloc[0] if "elo_diff" in feature_row.columns else np.nan
    adjusted_prob = apply_elo_anchor_probability(raw_prob, elo_diff)
    return raw_prob, adjusted_prob


def load_team_features() -> pd.DataFrame:
    """Load processed NCAA team profiles."""
    return pd.read_csv(ncaab_config.NCAAB_TEAM_FEATURES_CSV)


def load_current_team_features() -> pd.DataFrame:
    """Load the current projected tournament field team profiles."""
    if not ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV.exists():
        return pd.DataFrame()
    return pd.read_csv(ncaab_config.NCAAB_CURRENT_TEAM_FEATURES_CSV)


def load_current_all_team_features() -> pd.DataFrame:
    """Load the current all-teams NCAA profiles used for live pricing."""
    if ncaab_config.NCAAB_CURRENT_ALL_TEAM_FEATURES_CSV.exists():
        return pd.read_csv(ncaab_config.NCAAB_CURRENT_ALL_TEAM_FEATURES_CSV)
    return load_current_team_features()


def compute_seed_matchup_baselines(model_ready: pd.DataFrame) -> pd.DataFrame:
    """Aggregate historical tournament win rates by ordered seed matchup."""
    required = {"team_a_seed_num", "team_b_seed_num", "team_a_win"}
    if not required.issubset(model_ready.columns):
        return pd.DataFrame(columns=["team_a_seed_num", "team_b_seed_num", "seed_baseline_prob", "games"])

    baseline = (
        model_ready.groupby(["team_a_seed_num", "team_b_seed_num"])
        .agg(
            seed_baseline_prob=("team_a_win", "mean"),
            games=("team_a_win", "size"),
        )
        .reset_index()
    )
    return baseline


def load_seed_matchup_baselines() -> pd.DataFrame:
    """Load historical seed-matchup baselines from the model-ready dataset."""
    model_ready = pd.read_csv(ncaab_config.NCAAB_MODEL_READY_CSV)
    return compute_seed_matchup_baselines(model_ready)


def lookup_seed_baseline_prob(
    team_a_seed_num: int,
    team_b_seed_num: int,
    seed_baselines: pd.DataFrame | None = None,
) -> float:
    """Return the historical baseline win probability for an ordered seed matchup."""
    baselines = seed_baselines if seed_baselines is not None else load_seed_matchup_baselines()
    if baselines.empty:
        return 0.5

    match = baselines[
        (baselines["team_a_seed_num"] == int(team_a_seed_num))
        & (baselines["team_b_seed_num"] == int(team_b_seed_num))
    ]
    if not match.empty:
        return float(match["seed_baseline_prob"].iloc[0])
    return 0.5


def predict_matchup(
    season: int,
    team_a_id: int,
    team_b_id: int,
    team_features: pd.DataFrame | None = None,
    model_bundle: tuple | None = None,
    seed_baselines: pd.DataFrame | None = None,
) -> dict:
    """Predict a neutral-site NCAA tournament matchup."""
    if int(team_a_id) == int(team_b_id):
        raise ValueError("Team A and Team B must be different teams.")

    team_features = team_features if team_features is not None else load_team_features()
    model, feature_cols, fill_values = model_bundle or load_model()
    feature_row = build_matchup_feature_row(season, team_a_id, team_b_id, team_features)
    reverse_feature_row = build_matchup_feature_row(season, team_b_id, team_a_id, team_features)

    raw_forward, adjusted_forward = _predict_ordered_matchup_probs(feature_row, model, feature_cols, fill_values)
    raw_reverse, adjusted_reverse = _predict_ordered_matchup_probs(reverse_feature_row, model, feature_cols, fill_values)

    # Enforce neutral-site symmetry: flipping team order should flip the probabilities.
    raw_team_a_prob = float(np.clip(0.5 * (raw_forward + (1.0 - raw_reverse)), 1e-6, 1.0 - 1e-6))
    team_a_prob = float(np.clip(0.5 * (adjusted_forward + (1.0 - adjusted_reverse)), 1e-6, 1.0 - 1e-6))
    team_a_seed_num = int(feature_row["team_a_seed_num"].iloc[0]) if "team_a_seed_num" in feature_row.columns else None
    team_b_seed_num = int(feature_row["team_b_seed_num"].iloc[0]) if "team_b_seed_num" in feature_row.columns else None
    seed_baseline_prob = (
        lookup_seed_baseline_prob(team_a_seed_num, team_b_seed_num, seed_baselines=seed_baselines)
        if team_a_seed_num is not None and team_b_seed_num is not None
        else 0.5
    )
    return {
        "season": int(season),
        "team_a": int(team_a_id),
        "team_b": int(team_b_id),
        "team_a_name": feature_row["team_a_name"].iloc[0],
        "team_b_name": feature_row["team_b_name"].iloc[0],
        "team_a_win_prob": team_a_prob,
        "team_b_win_prob": 1.0 - team_a_prob,
        "team_a_win_prob_model": raw_team_a_prob,
        "team_b_win_prob_model": 1.0 - raw_team_a_prob,
        "seed_baseline_prob": seed_baseline_prob,
        "team_a_seed_edge": team_a_prob - seed_baseline_prob,
        "team_b_seed_edge": (1.0 - team_a_prob) - (1.0 - seed_baseline_prob),
        "feature_row": feature_row,
    }


def predict_market_games(
    odds_df: pd.DataFrame,
    team_features: pd.DataFrame | None = None,
    model_bundle: tuple | None = None,
    seed_baselines: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Generate NCAA game predictions for a live market board."""
    if odds_df is None or odds_df.empty:
        return pd.DataFrame()

    team_features = team_features if team_features is not None else load_current_team_features()
    if team_features.empty:
        logger.warning("Current NCAA team features are unavailable; cannot price live market games.")
        return pd.DataFrame()

    season = int(pd.to_numeric(team_features["Season"], errors="coerce").dropna().iloc[0])
    model_bundle = model_bundle or load_model()
    seed_baselines = seed_baselines if seed_baselines is not None else load_seed_matchup_baselines()
    team_lookup = (
        team_features.drop_duplicates(subset=["TeamName"])
        .set_index("TeamName")["TeamID"]
        .to_dict()
    )

    rows: list[dict[str, object]] = []
    for market in odds_df.to_dict("records"):
        home_team = market.get("home_team")
        away_team = market.get("away_team")
        if home_team not in team_lookup or away_team not in team_lookup:
            continue

        prediction = predict_matchup(
            season,
            int(team_lookup[home_team]),
            int(team_lookup[away_team]),
            team_features=team_features,
            model_bundle=model_bundle,
            seed_baselines=seed_baselines,
        )

        tipoff = pd.to_datetime(market.get("tipoff_utc"), errors="coerce", utc=True)
        market_row = {
            "game_id": (
                f"{season}_{str(away_team).lower().replace(' ', '_')}_"
                f"{str(home_team).lower().replace(' ', '_')}_"
                f"{tipoff.strftime('%Y%m%d') if pd.notna(tipoff) else 'live'}"
            ),
            "season": season,
            "tipoff_utc": tipoff,
            "game_date": tipoff.tz_convert("America/New_York").date() if pd.notna(tipoff) else pd.NaT,
            "home_team": home_team,
            "away_team": away_team,
            "home_team_id": int(team_lookup[home_team]),
            "away_team_id": int(team_lookup[away_team]),
            "home_win_prob": prediction["team_a_win_prob"],
            "away_win_prob": prediction["team_b_win_prob"],
            "home_win_prob_model": prediction["team_a_win_prob_model"],
            "away_win_prob_model": prediction["team_b_win_prob_model"],
            "seed_baseline_prob": prediction["seed_baseline_prob"],
            "home_seed_edge": prediction["team_a_seed_edge"],
            "away_seed_edge": prediction["team_b_seed_edge"],
        }
        market_row.update({k: v for k, v in market.items() if k not in market_row})
        rows.append(market_row)

    return pd.DataFrame(rows)


def generate_market_recommendation_table(
    predictions_df: pd.DataFrame,
    odds_df: pd.DataFrame | None = None,
    edge_threshold: float = ncaab_config.EDGE_THRESHOLD,
) -> pd.DataFrame:
    """Build an NCAA picks table with real market edge and Kelly sizing."""
    if predictions_df is None or predictions_df.empty:
        return pd.DataFrame()

    df = predictions_df.copy()

    if odds_df is not None and not odds_df.empty:
        odds_source = odds_df.copy()
        merge_keys = ["home_team", "away_team"]
        if "tipoff_utc" in df.columns and "tipoff_utc" in odds_source.columns:
            df["tipoff_utc"] = pd.to_datetime(df["tipoff_utc"], errors="coerce", utc=True)
            odds_source["tipoff_utc"] = pd.to_datetime(odds_source["tipoff_utc"], errors="coerce", utc=True)
            merge_keys.append("tipoff_utc")
        elif "market_date" in df.columns and "market_date" in odds_source.columns:
            df["market_date"] = pd.to_datetime(df["market_date"], errors="coerce", utc=True)
            odds_source["market_date"] = pd.to_datetime(odds_source["market_date"], errors="coerce", utc=True)
            merge_keys.append("market_date")

        odds_cols = [col for col in odds_source.columns if col not in set(merge_keys)]
        df = df.merge(
            odds_source[merge_keys + odds_cols].drop_duplicates(subset=merge_keys),
            on=merge_keys,
            how="left",
            suffixes=("", "_odds"),
        )

    if "market_home_implied" not in df.columns and "market_home_prob" in df.columns:
        df["market_home_implied"] = df["market_home_prob"]
    if "market_home_implied" not in df.columns and "home_prob" in df.columns:
        df["market_home_implied"] = pd.to_numeric(df["home_prob"], errors="coerce")
    if "market_away_implied" not in df.columns and "market_away_prob" in df.columns:
        df["market_away_implied"] = df["market_away_prob"]
    if "market_away_implied" not in df.columns and "away_prob" in df.columns:
        df["market_away_implied"] = pd.to_numeric(df["away_prob"], errors="coerce")

    if "home_odds_decimal" not in df.columns:
        df["home_odds_decimal"] = np.nan
    if "away_odds_decimal" not in df.columns:
        df["away_odds_decimal"] = np.nan

    home_implied = pd.to_numeric(df.get("market_home_implied"), errors="coerce")
    away_implied = pd.to_numeric(df.get("market_away_implied"), errors="coerce")
    df["home_odds_decimal"] = pd.to_numeric(df["home_odds_decimal"], errors="coerce").fillna(
        pd.Series(np.where(home_implied > 0, 1.0 / home_implied, np.nan), index=df.index)
    )
    df["away_odds_decimal"] = pd.to_numeric(df["away_odds_decimal"], errors="coerce").fillna(
        pd.Series(np.where(away_implied > 0, 1.0 / away_implied, np.nan), index=df.index)
    )

    df["home_edge"] = pd.to_numeric(df["home_win_prob"], errors="coerce") - home_implied
    df["away_edge"] = pd.to_numeric(df["away_win_prob"], errors="coerce") - away_implied
    df["best_edge"] = df[["home_edge", "away_edge"]].max(axis=1)
    df["best_seed_edge"] = df[["home_seed_edge", "away_seed_edge"]].max(axis=1)

    df["bet_side"] = np.where(df["home_edge"] >= df["away_edge"], "home", "away")
    df["bet_team"] = np.where(df["bet_side"] == "home", df["home_team"], df["away_team"])
    df["bet_prob"] = np.where(df["bet_side"] == "home", df["home_win_prob"], df["away_win_prob"])
    df["bet_market"] = np.where(df["bet_side"] == "home", df["market_home_implied"], df["market_away_implied"])
    df["bet_odds_decimal"] = np.where(df["bet_side"] == "home", df["home_odds_decimal"], df["away_odds_decimal"])
    df["seed_edge"] = np.where(df["bet_side"] == "home", df["home_seed_edge"], df["away_seed_edge"])
    df["best_source"] = np.where(
        df["bet_side"] == "home",
        df.get("best_home_source", df.get("best_source")),
        df.get("best_away_source", df.get("best_source")),
    )
    df["break_even_prob"] = np.where(df["bet_odds_decimal"] > 0, 1.0 / df["bet_odds_decimal"], np.nan)
    df["expected_value_per_dollar"] = df["bet_prob"] * df["bet_odds_decimal"] - 1.0

    df["kelly"] = df.apply(
        lambda row: kelly_fraction(
            float(pd.to_numeric(pd.Series([row["bet_prob"]]), errors="coerce").iloc[0]),
            float(pd.to_numeric(pd.Series([row["bet_odds_decimal"]]), errors="coerce").iloc[0]),
        )
        * config.KELLY_FRACTION,
        axis=1,
    )
    df["kelly"] = pd.to_numeric(df["kelly"], errors="coerce").clip(lower=0.0, upper=0.25)

    df["bet"] = (
        pd.to_numeric(df["best_edge"], errors="coerce").fillna(-1.0) >= float(edge_threshold)
    ) & (
        pd.to_numeric(df["bet_prob"], errors="coerce").fillna(0.0) >= float(ncaab_config.MIN_WIN_PROB)
    )

    def confidence_label(row: pd.Series) -> str:
        if not row["bet"]:
            return "No Bet"
        edge = float(row["best_edge"])
        if edge >= 0.07:
            return "Strong Edge"
        if edge >= 0.04:
            return "Moderate Edge"
        return "Marginal"

    df["confidence"] = df.apply(confidence_label, axis=1)

    ordered_cols = [
        "game_id",
        "tipoff_utc",
        "game_date",
        "home_team",
        "away_team",
        "home_win_prob",
        "away_win_prob",
        "market_home_implied",
        "market_away_implied",
        "home_odds_decimal",
        "away_odds_decimal",
        "home_edge",
        "away_edge",
        "best_edge",
        "home_seed_edge",
        "away_seed_edge",
        "best_seed_edge",
        "bet_side",
        "bet_team",
        "bet_prob",
        "bet_market",
        "bet_odds_decimal",
        "break_even_prob",
        "expected_value_per_dollar",
        "kelly",
        "bet",
        "confidence",
        "best_source",
        "best_home_source",
        "best_away_source",
        "sportsbook_home_prob",
        "kalshi_home_prob",
        "polymarket_home_prob",
    ]
    ordered_cols = [col for col in ordered_cols if col in df.columns]
    extra_cols = [col for col in df.columns if col not in ordered_cols]

    return (
        df[ordered_cols + extra_cols]
        .sort_values(["bet", "best_edge", "bet_prob"], ascending=[False, False, False])
        .reset_index(drop=True)
    )


def simulate_bracket(
    season: int = ncaab_config.LATEST_BRACKET_SEASON,
    team_features: pd.DataFrame | None = None,
) -> pd.DataFrame:
    """Simulate the full bracket deterministically using model probabilities."""
    team_features = team_features if team_features is not None else load_team_features()
    seeds = load_raw_csv("MNCAATourneySeeds.csv")
    slots = load_raw_csv("MNCAATourneySlots.csv")
    seed_map = (
        seeds[seeds["Season"] == season][["Seed", "TeamID"]]
        .drop_duplicates()
        .set_index("Seed")["TeamID"]
        .to_dict()
    )
    slot_rows = slots[slots["Season"] == season].copy()
    slot_lookup = slot_rows.set_index("Slot").to_dict("index")
    winners: dict[str, int] = {}
    picks: list[dict] = []
    model_bundle = load_model()
    seed_baselines = load_seed_matchup_baselines()

    def resolve_entry(entry: str) -> int:
        if entry in winners:
            return winners[entry]
        if entry in seed_map:
            return int(seed_map[entry])
        if entry not in slot_lookup:
            raise KeyError(f"Unknown bracket entry {entry!r} for season {season}")
        slot_row = slot_lookup[entry]
        return simulate_slot(entry, slot_row)

    def simulate_slot(slot_name: str, slot_row: dict) -> int:
        if slot_name in winners:
            return winners[slot_name]

        team_a_id = resolve_entry(str(slot_row["StrongSeed"]))
        team_b_id = resolve_entry(str(slot_row["WeakSeed"]))
        prediction = predict_matchup(
            season,
            team_a_id,
            team_b_id,
            team_features=team_features,
            model_bundle=model_bundle,
            seed_baselines=seed_baselines,
        )
        winner_id = team_a_id if prediction["team_a_win_prob"] >= 0.5 else team_b_id
        winner_name = prediction["team_a_name"] if winner_id == team_a_id else prediction["team_b_name"]
        loser_name = prediction["team_b_name"] if winner_id == team_a_id else prediction["team_a_name"]
        win_prob = prediction["team_a_win_prob"] if winner_id == team_a_id else prediction["team_b_win_prob"]

        winners[slot_name] = winner_id
        picks.append(
            {
                "slot": slot_name,
                "round": slot_round_label(slot_name),
                "team_a_id": team_a_id,
                "team_b_id": team_b_id,
                "team_a_name": prediction["team_a_name"],
                "team_b_name": prediction["team_b_name"],
                "winner_id": winner_id,
                "winner_name": winner_name,
                "loser_name": loser_name,
                "win_prob": win_prob,
                "seed_baseline_prob": prediction["seed_baseline_prob"],
                "winner_seed_edge": prediction["team_a_seed_edge"] if winner_id == team_a_id else prediction["team_b_seed_edge"],
            }
        )
        return winner_id

    for slot_name, slot_row in slot_lookup.items():
        simulate_slot(slot_name, slot_row)

    bracket = pd.DataFrame(picks)
    round_order = {
        "First Four": 0,
        "Round of 64": 1,
        "Round of 32": 2,
        "Sweet 16": 3,
        "Elite 8": 4,
        "Final Four": 5,
        "National Championship": 6,
    }
    bracket["round_order"] = bracket["round"].map(round_order)
    bracket = bracket.sort_values(["round_order", "slot"]).reset_index(drop=True)
    return bracket.drop(columns=["round_order"])
