"""
model.py — XGBoost training, hyperparameter tuning, and probability calibration.

Temporal data split:
  Train:  2018-19 through 2022-23
  Val:    2023-24
  Test:   2024-25
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import log_loss
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)

MODEL_DIR = Path(config.MODEL_DIR)
MODEL_DIR.mkdir(parents=True, exist_ok=True)

# Columns that are NOT features (identifiers, targets, leakage)
NON_FEATURE_COLS = [
    "game_id", "game_date", "season", "home_team", "away_team",
    "home_win", "home_pts", "away_pts",
]
FORBIDDEN_FEATURE_TOKENS = (
    "market", "odds", "prob", "edge", "kelly", "stake", "pnl",
    "value", "fee", "bankroll", "entry", "current", "close", "line",
)
MATCHUP_FEATURE_COLS = {
    "elo_diff",
    "rest_diff",
    "pace_diff",
    "streak_diff",
    "season_phase",
    "home_off_vs_away_def",
    "away_off_vs_home_def",
    "location_win_pct_diff",
    "h2h_home_win_pct",
    "h2h_games",
    "sos_diff",
}
LINEAR_MODEL_FEATURE_PRIORITY = [
    "elo_diff",
    "rest_diff",
    "point_diff_diff",
    "net_rtg_diff",
    "efg_pct_diff",
    "ts_pct_diff",
    "off_rtg_diff",
    "def_rtg_diff",
    "opp_efg_pct_diff",
    "opp_tov_rate_diff",
    "roll_10_win_pct_diff",
    "roll_15_win_pct_diff",
    "streak_diff",
    "season_phase",
    "home_off_vs_away_def",
    "away_off_vs_home_def",
    "location_win_pct_diff",
    "home_elo",
    "away_elo",
    "home_rest_days",
    "away_rest_days",
]


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return model features using an allowlist-style numeric selector."""
    feature_cols: list[str] = []
    for col in df.columns:
        if col in NON_FEATURE_COLS or not pd.api.types.is_numeric_dtype(df[col]):
            continue

        lower_col = col.lower()
        if any(token in lower_col for token in FORBIDDEN_FEATURE_TOKENS):
            continue

        if col.startswith(("home_", "away_")) or col.endswith("_diff") or col in MATCHUP_FEATURE_COLS:
            feature_cols.append(col)

    return feature_cols


def get_linear_feature_columns(feature_cols: list[str]) -> list[str]:
    """Return the curated differential feature set for the linear model."""
    return [col for col in LINEAR_MODEL_FEATURE_PRIORITY if col in feature_cols]


def temporal_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split dataset into train / val / test by season."""
    train = df[df["season"].isin(config.TRAIN_SEASONS)].copy()
    val   = df[df["season"].isin(config.VAL_SEASONS)].copy()
    test  = df[df["season"].isin(config.TEST_SEASONS)].copy()
    logger.info("Split sizes — train: %d, val: %d, test: %d", len(train), len(val), len(test))
    return train, val, test


def prepare_xy(
    df: pd.DataFrame,
    feature_cols: list[str],
    fill_values: Optional[pd.Series] = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Return (X, y), optionally filling NaNs with training-only values."""
    X = df.reindex(columns=feature_cols).copy()
    if fill_values is not None:
        X = X.fillna(fill_values.reindex(feature_cols))
    y = df["home_win"]
    return X, y


def compute_fill_values(df: pd.DataFrame, feature_cols: list[str]) -> pd.Series:
    """Compute training-only medians for downstream NaN filling."""
    return df.reindex(columns=feature_cols).median(numeric_only=True).reindex(feature_cols)


def train_xgb(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    params: dict | None = None,
    sample_weight=None,
) -> XGBClassifier:
    """
    Train an XGBClassifier with early stopping on the validation set.
    """
    if params is None:
        params = config.XGB_PARAMS.copy()

    n_estimators = params.pop("n_estimators", 500)
    model = XGBClassifier(
        **params,
        n_estimators=n_estimators,
        early_stopping_rounds=config.EARLY_STOPPING_ROUNDS,
    )

    model.fit(
        X_train, y_train,
        sample_weight=sample_weight,
        eval_set=[(X_val, y_val)],
        verbose=50,
    )
    logger.info("Best iteration: %d", model.best_iteration)
    return model


def tune_hyperparameters(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    n_trials: int = 100,
) -> dict:
    """
    Use Optuna to tune XGBoost hyperparameters with TimeSeriesSplit CV.
    Returns the best params dict.
    """
    try:
        import optuna
        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        logger.warning("optuna not installed — skipping hyperparameter tuning")
        return config.XGB_PARAMS.copy()

    tscv = TimeSeriesSplit(n_splits=5)

    def objective(trial: "optuna.Trial") -> float:
        params = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "random_state": 42,
            "max_depth": trial.suggest_int("max_depth", 2, 5),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.08, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 400, 1800, step=100),
            "min_child_weight": trial.suggest_int("min_child_weight", 4, 20),
            "subsample": trial.suggest_float("subsample", 0.6, 0.95),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 0.9),
            "colsample_bylevel": trial.suggest_float("colsample_bylevel", 0.5, 1.0),
            "gamma": trial.suggest_float("gamma", 0.0, 3.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 0.1, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 20.0, log=True),
        }
        scores = []
        for tr_idx, val_idx in tscv.split(X_train):
            Xtr, Xv = X_train.iloc[tr_idx], X_train.iloc[val_idx]
            ytr, yv = y_train.iloc[tr_idx], y_train.iloc[val_idx]
            n_est = params.pop("n_estimators")
            m = XGBClassifier(**params, n_estimators=n_est, early_stopping_rounds=30)
            params["n_estimators"] = n_est
            m.fit(Xtr, ytr, eval_set=[(Xv, yv)], verbose=False)
            preds = m.predict_proba(Xv)[:, 1]
            scores.append(log_loss(yv, preds))
        return float(np.mean(scores))

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=True)
    best = study.best_params
    best["objective"] = "binary:logistic"
    best["eval_metric"] = "logloss"
    best["random_state"] = 42
    logger.info("Best params: %s  |  Best log loss: %.4f", best, study.best_value)
    return best


class CalibratedModel:
    """Wraps an XGBClassifier + IsotonicRegression calibrator."""

    def __init__(self, model: XGBClassifier, calibrator: IsotonicRegression) -> None:
        self.model = model
        self.calibrator = calibrator

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        raw = self.model.predict_proba(X)[:, 1]
        calibrated = self.calibrator.predict(raw)
        return np.column_stack([1.0 - calibrated, calibrated])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    @property
    def feature_importances_(self) -> np.ndarray:
        return self.model.feature_importances_

    @property
    def estimator(self) -> XGBClassifier:
        return self.model


class EnsembleCalibratedModel:
    """Blend a calibrated XGBoost with a calibrated linear differential model."""

    def __init__(
        self,
        xgb_model: XGBClassifier,
        xgb_calibrator: IsotonicRegression,
        linear_model: LogisticRegression | None,
        linear_calibrator: IsotonicRegression | None,
        feature_cols: list[str],
        linear_feature_cols: list[str],
        xgb_weight: float,
    ) -> None:
        self.xgb_model = xgb_model
        self.xgb_calibrator = xgb_calibrator
        self.linear_model = linear_model
        self.linear_calibrator = linear_calibrator
        self.feature_cols = feature_cols
        self.linear_feature_cols = linear_feature_cols
        self.xgb_weight = float(xgb_weight)

    def _predict_xgb_prob(self, X: pd.DataFrame) -> np.ndarray:
        raw = self.xgb_model.predict_proba(X)[:, 1]
        return self.xgb_calibrator.predict(raw)

    def _predict_linear_prob(self, X: pd.DataFrame) -> np.ndarray:
        if self.linear_model is None or self.linear_calibrator is None or not self.linear_feature_cols:
            return self._predict_xgb_prob(X)
        raw = self.linear_model.predict_proba(X[self.linear_feature_cols])[:, 1]
        return self.linear_calibrator.predict(raw)

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        xgb_prob = self._predict_xgb_prob(X)
        linear_prob = self._predict_linear_prob(X)
        blended = self.xgb_weight * xgb_prob + (1.0 - self.xgb_weight) * linear_prob
        return np.column_stack([1.0 - blended, blended])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    @property
    def estimator(self) -> XGBClassifier | None:
        return self.xgb_model if self.xgb_weight > 0 else None

    @property
    def feature_importances_(self) -> np.ndarray:
        xgb_importance = np.zeros(len(self.feature_cols), dtype=float)
        if self.xgb_model is not None:
            raw_importance = np.asarray(self.xgb_model.feature_importances_, dtype=float)
            if raw_importance.sum() > 0:
                xgb_importance = raw_importance / raw_importance.sum()

        linear_importance = np.zeros(len(self.feature_cols), dtype=float)
        if self.linear_model is not None and self.linear_feature_cols:
            coefs = np.abs(self.linear_model.coef_.ravel()).astype(float)
            if coefs.sum() > 0:
                coefs = coefs / coefs.sum()
            feature_index = {feature: idx for idx, feature in enumerate(self.feature_cols)}
            for feature, coef in zip(self.linear_feature_cols, coefs):
                linear_importance[feature_index[feature]] = coef

        blended = self.xgb_weight * xgb_importance + (1.0 - self.xgb_weight) * linear_importance
        return blended


def calibrate_model(
    model: XGBClassifier,
    X_val: pd.DataFrame,
    y_val: pd.Series,
) -> CalibratedModel:
    """
    Apply isotonic regression calibration on the validation set.
    Fits calibrator on raw model probabilities → actual outcomes.
    """
    raw_probs = model.predict_proba(X_val)[:, 1]
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_probs, y_val)
    logger.info("Calibration complete.")
    return CalibratedModel(model, calibrator)


def calibrate_probabilities(raw_probs: np.ndarray, y_true: pd.Series) -> IsotonicRegression:
    """Fit isotonic calibration on already-generated probabilities."""
    calibrator = IsotonicRegression(out_of_bounds="clip")
    calibrator.fit(raw_probs, y_true)
    return calibrator


def train_linear_model(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    linear_feature_cols: list[str],
    sample_weight: np.ndarray | None = None,
) -> LogisticRegression | None:
    """Train a regularized linear model on the strongest differential features."""
    if not linear_feature_cols:
        logger.warning("No curated linear-model features available; skipping linear candidate.")
        return None

    model = LogisticRegression(
        C=config.LINEAR_MODEL_C,
        max_iter=5000,
        solver="lbfgs",
    )
    model.fit(X_train[linear_feature_cols], y_train, sample_weight=sample_weight)
    return model


def select_blend_weight(
    y_true: pd.Series,
    xgb_probs: np.ndarray,
    linear_probs: np.ndarray,
) -> tuple[float, float]:
    """Choose the ensemble blend weight using validation log loss."""
    best_weight = 1.0
    best_score = float(log_loss(y_true, xgb_probs))

    weight_step = max(float(config.ENSEMBLE_WEIGHT_STEP), 0.01)
    grid_size = int(round(1.0 / weight_step))
    for idx in range(grid_size + 1):
        weight = min(idx * weight_step, 1.0)
        blended = weight * xgb_probs + (1.0 - weight) * linear_probs
        score = float(log_loss(y_true, blended))
        if score < best_score:
            best_weight = weight
            best_score = score

    return best_weight, best_score


def save_model(
    model,
    calibrated_model,
    feature_cols: list[str],
    medians: pd.Series,
) -> None:
    """Save model artifacts to disk."""
    # Raw XGB model
    model.save_model(str(MODEL_DIR / "xgb_model.json"))
    # Calibrated model (wrapped sklearn object)
    joblib.dump(calibrated_model, MODEL_DIR / "calibrated_model.joblib")
    # Feature list and fill values
    joblib.dump(feature_cols, MODEL_DIR / "feature_cols.joblib")
    joblib.dump(medians, MODEL_DIR / "fill_medians.joblib")
    logger.info("Model artifacts saved to %s/", MODEL_DIR)


def load_model() -> tuple:
    """
    Load saved model artifacts.
    Returns (calibrated_model, feature_cols, medians).
    """
    calibrated_model = joblib.load(MODEL_DIR / "calibrated_model.joblib")
    feature_cols = joblib.load(MODEL_DIR / "feature_cols.joblib")
    medians = joblib.load(MODEL_DIR / "fill_medians.joblib")
    return calibrated_model, feature_cols, medians


def run_training_pipeline(
    df: pd.DataFrame,
    tune: bool = False,
    n_trials: int = 50,
) -> tuple:
    """
    Full training pipeline: split → tune (optional) → train → calibrate → save.

    Returns (calibrated_model, feature_cols, test_df)
    """
    feature_cols = get_feature_columns(df)
    logger.info("Using %d features", len(feature_cols))

    train_df, val_df, test_df = temporal_split(df)
    medians = compute_fill_values(train_df, feature_cols)

    # Recency weighting: exponentially up-weight recent seasons so the model
    # better reflects current NBA style (pace, load management, 3-pt era).
    train_season_year = train_df['season'].str[:4].astype(int)
    min_year = train_season_year.min()
    sample_weight = np.exp(config.RECENCY_DECAY * (train_season_year - min_year)).values

    X_train, y_train = prepare_xy(train_df, feature_cols, fill_values=medians)
    X_val, y_val     = prepare_xy(val_df, feature_cols, fill_values=medians)
    X_test, y_test   = prepare_xy(test_df, feature_cols, fill_values=medians)

    if tune:
        logger.info("Running Optuna hyperparameter tuning (%d trials)...", n_trials)
        best_params = tune_hyperparameters(X_train, y_train, n_trials=n_trials)
    else:
        best_params = config.XGB_PARAMS.copy()

    logger.info("Training XGBoost model...")
    model = train_xgb(X_train, y_train, X_val, y_val, params=best_params, sample_weight=sample_weight)

    val_preds_raw = model.predict_proba(X_val)[:, 1]
    logger.info("Val log loss (raw): %.4f", log_loss(y_val, val_preds_raw))

    logger.info("Calibrating XGBoost...")
    xgb_calibrator = calibrate_probabilities(val_preds_raw, y_val)
    val_preds_xgb = xgb_calibrator.predict(val_preds_raw)
    logger.info("Val log loss (XGBoost calibrated): %.4f", log_loss(y_val, val_preds_xgb))

    calibrated = CalibratedModel(model, xgb_calibrator)

    if config.ENABLE_LINEAR_BLEND:
        linear_feature_cols = get_linear_feature_columns(feature_cols)
        linear_model = train_linear_model(X_train, y_train, linear_feature_cols, sample_weight=sample_weight)
        linear_calibrator = None
        if linear_model is not None:
            val_linear_raw = linear_model.predict_proba(X_val[linear_feature_cols])[:, 1]
            linear_calibrator = calibrate_probabilities(val_linear_raw, y_val)
            val_preds_linear = linear_calibrator.predict(val_linear_raw)
            logger.info("Val log loss (linear calibrated): %.4f", log_loss(y_val, val_preds_linear))

            blend_weight, blend_logloss = select_blend_weight(y_val, val_preds_xgb, val_preds_linear)
            logger.info(
                "Selected ensemble weight: %.2f XGBoost / %.2f linear (val log loss %.4f)",
                blend_weight,
                1.0 - blend_weight,
                blend_logloss,
            )

            calibrated = EnsembleCalibratedModel(
                xgb_model=model,
                xgb_calibrator=xgb_calibrator,
                linear_model=linear_model,
                linear_calibrator=linear_calibrator,
                feature_cols=feature_cols,
                linear_feature_cols=linear_feature_cols,
                xgb_weight=blend_weight,
            )

    val_preds_cal = np.clip(calibrated.predict_proba(X_val)[:, 1], 1e-7, 1 - 1e-7)
    logger.info("Val log loss (selected model): %.4f", log_loss(y_val, val_preds_cal))
    test_preds_cal = np.clip(calibrated.predict_proba(X_test)[:, 1], 1e-7, 1 - 1e-7)
    logger.info("Test log loss (selected model): %.4f", log_loss(y_test, test_preds_cal))

    save_model(model, calibrated, feature_cols, medians)

    return calibrated, feature_cols, test_df
