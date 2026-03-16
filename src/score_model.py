"""
score_model.py — XGBoost regression models for predicting final scores.

Two separate models:
  NBA:   predicts home_pts and away_pts for an NBA game
  NCAA:  predicts team_a_score and team_b_score for a neutral-site game
"""

from __future__ import annotations

import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from xgboost import XGBRegressor

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parents[1]
NBA_SCORE_MODEL_PATH  = ROOT / "models" / "score_nba.joblib"
NCAA_SCORE_MODEL_PATH = ROOT / "models" / "ncaab" / "score_model.joblib"

_NBA_EXCLUDE = {
    "game_id", "game_date", "season", "home_team", "away_team",
    "home_win", "home_pts", "away_pts",
}
_NBA_EXCLUDE_TOKENS = {
    "market", "odds", "prob", "edge", "kelly", "stake", "pnl",
    "value", "fee", "bankroll", "entry", "current", "close", "line",
    "player", "injury",
}


def _nba_feature_cols(df: pd.DataFrame) -> list[str]:
    cols = []
    for c in df.columns:
        if c in _NBA_EXCLUDE:
            continue
        if any(tok in c.lower() for tok in _NBA_EXCLUDE_TOKENS):
            continue
        if pd.api.types.is_numeric_dtype(df[c]):
            cols.append(c)
    return cols


def train_nba_score_model(df: pd.DataFrame) -> dict:
    """Train XGBoost regressors for home_pts and away_pts."""
    import config
    feature_cols = _nba_feature_cols(df)

    train = df[df["season"].isin(config.TRAIN_SEASONS)].copy()
    val   = df[df["season"].isin(config.VAL_SEASONS)].copy()
    test  = df[df["season"].isin(config.TEST_SEASONS)].copy()

    fill_values = train[feature_cols].median().to_dict()

    def _fill(d):
        return d[feature_cols].fillna(fill_values).values

    X_train, X_val, X_test = _fill(train), _fill(val), _fill(test)

    params = dict(
        n_estimators=400, learning_rate=0.05, max_depth=6,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=3, reg_alpha=0.1, reg_lambda=1.0,
        random_state=42, n_jobs=-1, tree_method="hist",
    )

    models, metrics = {}, {}
    for target in ("home_pts", "away_pts"):
        y_train = train[target].values
        y_val   = val[target].values
        y_test  = test[target].values

        reg = XGBRegressor(**params, early_stopping_rounds=30, eval_metric="mae")
        reg.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        preds = reg.predict(X_test)
        mae  = float(np.mean(np.abs(preds - y_test)))
        rmse = float(np.sqrt(np.mean((preds - y_test) ** 2)))
        metrics[target] = {"mae": round(mae, 2), "rmse": round(rmse, 2)}
        logger.info("NBA score [%s] MAE=%.2f RMSE=%.2f", target, mae, rmse)
        models[target] = reg

    bundle = {
        "home_model":   models["home_pts"],
        "away_model":   models["away_pts"],
        "feature_cols": feature_cols,
        "fill_values":  fill_values,
    }
    NBA_SCORE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, NBA_SCORE_MODEL_PATH)
    logger.info("Saved NBA score model → %s", NBA_SCORE_MODEL_PATH)
    return metrics


def load_nba_score_model() -> dict | None:
    if not NBA_SCORE_MODEL_PATH.exists():
        return None
    return joblib.load(NBA_SCORE_MODEL_PATH)


def predict_nba_score(snap_home: dict, snap_away: dict) -> tuple[float, float] | None:
    """Return (home_pts, away_pts) using the trained NBA score model."""
    bundle = load_nba_score_model()
    if bundle is None:
        return None

    feature_cols = bundle["feature_cols"]
    fill_values  = bundle["fill_values"]

    row = {}
    for col in feature_cols:
        if col.startswith("home_"):
            row[col] = snap_home.get(col[5:], fill_values.get(col))
        elif col.startswith("away_"):
            row[col] = snap_away.get(col[5:], fill_values.get(col))
        else:
            row[col] = fill_values.get(col)

    X = pd.DataFrame([row])[feature_cols].fillna(fill_values)
    home_pts = float(bundle["home_model"].predict(X)[0])
    away_pts = float(bundle["away_model"].predict(X)[0])
    return round(home_pts, 1), round(away_pts, 1)


# ── NCAA ──────────────────────────────────────────────────────────────────────

def _build_ncaa_score_dataset(
    regular_season: pd.DataFrame,
    team_features: pd.DataFrame,
) -> pd.DataFrame:
    """Join game results with team season features for score regression."""
    feat_cols = [c for c in team_features.columns
                 if c not in {"Season", "TeamID", "TeamName", "Seed", "seed_num",
                               "median_rank", "best_rank"}
                 and pd.api.types.is_numeric_dtype(team_features[c])]

    tf = team_features.set_index(["Season", "TeamID"])
    rows = []
    rng = np.random.default_rng(42)

    for _, game in regular_season.iterrows():
        season = int(game["Season"])
        w_id, l_id = int(game["WTeamID"]), int(game["LTeamID"])
        w_sc, l_sc = float(game["WScore"]), float(game["LScore"])

        try:
            w_feat = tf.loc[(season, w_id)]
            l_feat = tf.loc[(season, l_id)]
        except KeyError:
            continue

        # Randomly assign team_a/team_b to remove order bias
        if rng.random() < 0.5:
            a_feat, b_feat, a_sc, b_sc = w_feat, l_feat, w_sc, l_sc
        else:
            a_feat, b_feat, a_sc, b_sc = l_feat, w_feat, l_sc, w_sc

        row = {"Season": season, "team_a_score": a_sc, "team_b_score": b_sc}
        for c in feat_cols:
            row[f"a_{c}"] = float(a_feat.get(c, np.nan)) if hasattr(a_feat, 'get') else float(getattr(a_feat, c, np.nan))
            row[f"b_{c}"] = float(b_feat.get(c, np.nan)) if hasattr(b_feat, 'get') else float(getattr(b_feat, c, np.nan))

        row["elo_diff"]    = row.get("a_elo", 1500) - row.get("b_elo", 1500)
        row["off_diff"]    = row.get("a_off_rtg", 100) - row.get("b_off_rtg", 100)
        row["def_diff"]    = row.get("a_def_rtg", 100) - row.get("b_def_rtg", 100)
        row["margin_diff"] = row.get("a_avg_margin", 0) - row.get("b_avg_margin", 0)
        # Cross-matchup: how does team A's offense stack up vs team B's defense (and vice versa)
        row["a_off_vs_b_def"] = row.get("a_off_rtg", 100) - row.get("b_def_rtg", 100)
        row["b_off_vs_a_def"] = row.get("b_off_rtg", 100) - row.get("a_def_rtg", 100)
        row["a_net_vs_b_net"] = row.get("a_net_rtg", 0)   - row.get("b_net_rtg", 0)
        rows.append(row)

    return pd.DataFrame(rows)


def train_ncaa_score_model(
    regular_season: pd.DataFrame,
    team_features: pd.DataFrame,
    train_seasons: list[int],
    val_seasons: list[int],
    test_seasons: list[int],
) -> dict:
    """Train XGBoost regressors for team_a_score and team_b_score."""
    logger.info("Building NCAA score dataset from %d regular season games…", len(regular_season))
    df = _build_ncaa_score_dataset(regular_season, team_features)
    logger.info("NCAA score dataset: %d rows", len(df))

    non_feat = {"Season", "team_a_score", "team_b_score"}
    feature_cols = [c for c in df.columns
                    if c not in non_feat and pd.api.types.is_numeric_dtype(df[c])]

    train = df[df["Season"].isin(train_seasons)]
    val   = df[df["Season"].isin(val_seasons)]
    test  = df[df["Season"].isin(test_seasons)] if test_seasons else val

    logger.info("NCAA score split — train: %d  val: %d  test: %d",
                len(train), len(val), len(test))

    fill_values = train[feature_cols].median().to_dict()

    def _fill(d):
        return d[feature_cols].fillna(fill_values).values

    X_train, X_val = _fill(train), _fill(val)
    X_test = _fill(test) if len(test) else X_val

    params = dict(
        n_estimators=500, learning_rate=0.04, max_depth=5,
        subsample=0.8, colsample_bytree=0.8,
        min_child_weight=5, reg_alpha=0.1, reg_lambda=1.5,
        random_state=42, n_jobs=-1, tree_method="hist",
    )

    models, metrics = {}, {}
    for target in ("team_a_score", "team_b_score"):
        y_train = train[target].values
        y_val   = val[target].values
        y_test  = test[target].values if len(test) else y_val

        reg = XGBRegressor(**params, early_stopping_rounds=40, eval_metric="mae")
        reg.fit(X_train, y_train, eval_set=[(X_val, y_val)], verbose=False)

        preds = reg.predict(X_test)
        mae  = float(np.mean(np.abs(preds - y_test)))
        rmse = float(np.sqrt(np.mean((preds - y_test) ** 2)))
        metrics[target] = {"mae": round(mae, 2), "rmse": round(rmse, 2)}
        logger.info("NCAA score [%s] MAE=%.2f RMSE=%.2f", target, mae, rmse)
        models[target] = reg

    bundle = {
        "a_model":      models["team_a_score"],
        "b_model":      models["team_b_score"],
        "feature_cols": feature_cols,
        "fill_values":  fill_values,
    }
    NCAA_SCORE_MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(bundle, NCAA_SCORE_MODEL_PATH)
    logger.info("Saved NCAA score model → %s", NCAA_SCORE_MODEL_PATH)
    return metrics


def load_ncaa_score_model() -> dict | None:
    if not NCAA_SCORE_MODEL_PATH.exists():
        return None
    return joblib.load(NCAA_SCORE_MODEL_PATH)


def predict_ncaa_score(
    team_a_row: pd.Series | dict,
    team_b_row: pd.Series | dict,
) -> tuple[float, float] | None:
    """Return (score_a, score_b) using the trained NCAA score model."""
    bundle = load_ncaa_score_model()
    if bundle is None:
        return None

    feature_cols = bundle["feature_cols"]
    fill_values  = bundle["fill_values"]

    ra = dict(team_a_row if isinstance(team_a_row, dict) else team_a_row.to_dict())
    rb = dict(team_b_row if isinstance(team_b_row, dict) else team_b_row.to_dict())

    # Derive SOS proxy features from Sports Reference `sos` when Kaggle-derived
    # avg_opp_win_pct / avg_opp_elo are unavailable (e.g. current-season inference).
    # Also replace raw computed ELO with SRS-derived ELO when `srs` is present —
    # raw ELO inflates weak-conference teams (e.g. Akron 29-5 in MAC vs Alabama in SEC).
    for r in (ra, rb):
        if "avg_opp_win_pct" not in r and "sos" in r and r.get("sos") is not None:
            sv = float(r["sos"])
            r["avg_opp_win_pct"] = 0.500 + sv / 150.0
            r["avg_opp_elo"]     = 1500.0 + sv * 5.0
        if "srs" in r and r.get("srs") is not None:
            # SRS is schedule-adjusted; map to historical ELO range (~1350–1700).
            # SRS ~0 → elo ~1500; top teams SRS~25 → elo~1650; weak SRS~-15 → elo~1410.
            r["elo"] = 1500.0 + float(r["srs"]) * 6.0

    row = {}
    for col in feature_cols:
        if col.startswith("a_"):
            row[col] = ra.get(col[2:], fill_values.get(col))
        elif col.startswith("b_"):
            row[col] = rb.get(col[2:], fill_values.get(col))
        else:
            row[col] = fill_values.get(col)

    row["elo_diff"]    = float(ra.get("elo", 1500))     - float(rb.get("elo", 1500))
    row["off_diff"]    = float(ra.get("off_rtg", 100))  - float(rb.get("off_rtg", 100))
    row["def_diff"]    = float(ra.get("def_rtg", 100))  - float(rb.get("def_rtg", 100))
    row["margin_diff"] = float(ra.get("avg_margin", 0)) - float(rb.get("avg_margin", 0))
    row["a_off_vs_b_def"] = float(ra.get("off_rtg", 100)) - float(rb.get("def_rtg", 100))
    row["b_off_vs_a_def"] = float(rb.get("off_rtg", 100)) - float(ra.get("def_rtg", 100))
    row["a_net_vs_b_net"] = float(ra.get("net_rtg", 0))   - float(rb.get("net_rtg", 0))

    X = pd.DataFrame([row])[feature_cols].fillna(fill_values)
    score_a = float(bundle["a_model"].predict(X)[0])
    score_b = float(bundle["b_model"].predict(X)[0])
    return round(score_a, 1), round(score_b, 1)
