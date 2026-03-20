"""
ncaab_model.py - Train and load the March Madness prediction model.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import log_loss
from sklearn.model_selection import TimeSeriesSplit
from xgboost import XGBClassifier

import ncaab_config

logger = logging.getLogger(__name__)

MODEL_DIR = ncaab_config.NCAAB_MODEL_DIR
MODEL_DIR.mkdir(parents=True, exist_ok=True)

NON_FEATURE_COLS = {
    "Season",
    "DayNum",
    "team_a",
    "team_b",
    "team_a_name",
    "team_b_name",
    "team_a_win",
    "is_tournament",
    "sample_weight_multiplier",
}


def _clip_probs(probs: np.ndarray) -> np.ndarray:
    """Keep calibrated probabilities inside a safe range.

    Conservative clipping prevents extreme confidence that drives
    catastrophic log-loss on upsets (e.g., 16-over-1).
    """
    return np.clip(np.asarray(probs, dtype=float), 0.04, 0.96)


class CalibratedNCAABModel:
    """Wrap an XGBoost classifier with isotonic calibration."""

    def __init__(self, model: XGBClassifier, calibrator: IsotonicRegression) -> None:
        self.model = model
        self.calibrator = calibrator

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        raw_probs = self.model.predict_proba(X)[:, 1]
        calibrated = _clip_probs(self.calibrator.predict(raw_probs))
        return np.column_stack([1.0 - calibrated, calibrated])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    @property
    def feature_importances_(self) -> np.ndarray:
        return self.model.feature_importances_

    @property
    def estimator(self) -> XGBClassifier:
        return self.model


class EnsembleCalibratedNCAABModel:
    """Blend a calibrated XGBoost model with a calibrated linear NCAA model."""

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
        return _clip_probs(self.xgb_calibrator.predict(raw))

    def _predict_linear_prob(self, X: pd.DataFrame) -> np.ndarray:
        if self.linear_model is None or self.linear_calibrator is None or not self.linear_feature_cols:
            return self._predict_xgb_prob(X)
        raw = self.linear_model.predict_proba(X[self.linear_feature_cols])[:, 1]
        return _clip_probs(self.linear_calibrator.predict(raw))

    def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
        xgb_prob = self._predict_xgb_prob(X)
        linear_prob = self._predict_linear_prob(X)
        blended = self.xgb_weight * xgb_prob + (1.0 - self.xgb_weight) * linear_prob
        return np.column_stack([1.0 - blended, blended])

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return (self.predict_proba(X)[:, 1] >= 0.5).astype(int)

    @property
    def feature_importances_(self) -> np.ndarray:
        xgb_importance = np.zeros(len(self.feature_cols), dtype=float)
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

        return self.xgb_weight * xgb_importance + (1.0 - self.xgb_weight) * linear_importance

    @property
    def estimator(self) -> XGBClassifier:
        return self.xgb_model


def get_feature_columns(df: pd.DataFrame) -> list[str]:
    """Return the live-compatible NCAA feature set used for training and inference."""
    feature_cols: list[str] = []
    for base_feature in ncaab_config.MODEL_BASE_FEATURES:
        for column_name in (f"team_a_{base_feature}", f"team_b_{base_feature}", f"{base_feature}_diff"):
            if column_name in df.columns and pd.api.types.is_numeric_dtype(df[column_name]):
                feature_cols.append(column_name)
    return feature_cols


def get_linear_feature_columns(feature_cols: list[str]) -> list[str]:
    """Return the curated NCAA differential feature set for the linear model."""
    return [col for col in ncaab_config.LINEAR_MODEL_FEATURE_PRIORITY if col in feature_cols]


def compute_fill_values(df: pd.DataFrame, feature_cols: list[str]) -> pd.Series:
    """Compute train-only fill values."""
    return df.reindex(columns=feature_cols).median(numeric_only=True).reindex(feature_cols)


def prepare_xy(
    df: pd.DataFrame,
    feature_cols: list[str],
    fill_values: pd.Series | None = None,
) -> tuple[pd.DataFrame, pd.Series]:
    """Prepare feature matrix and label vector."""
    X = df.reindex(columns=feature_cols).copy()
    if fill_values is not None:
        X = X.fillna(fill_values.reindex(feature_cols))
    y = df["team_a_win"]
    return X, y


def temporal_split(df: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Split the NCAA dataset into train, validation, and test seasons."""
    train = df[df["Season"].isin(ncaab_config.TRAIN_SEASONS)].copy()
    val = df[df["Season"].isin(ncaab_config.VAL_SEASONS)].copy()
    test = df[df["Season"].isin(ncaab_config.TEST_SEASONS)].copy()

    if "is_tournament" in test.columns:
        test_tourney = test[test["is_tournament"] == 1].copy()
        if not test_tourney.empty:
            test = test_tourney

    logger.info("NCAA split sizes - train: %d, val: %d, test: %d", len(train), len(val), len(test))
    return train, val, test


def train_xgb(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    X_val: pd.DataFrame,
    y_val: pd.Series,
    params: dict | None = None,
    sample_weight: np.ndarray | None = None,
) -> XGBClassifier:
    """Train the calibrated NCAA XGBoost model."""
    params = ncaab_config.XGB_PARAMS.copy() if params is None else params.copy()
    n_estimators = params.pop("n_estimators")
    model = XGBClassifier(
        **params,
        n_estimators=n_estimators,
        early_stopping_rounds=ncaab_config.EARLY_STOPPING_ROUNDS,
    )
    model.fit(
        X_train,
        y_train,
        sample_weight=sample_weight,
        eval_set=[(X_val, y_val)],
        verbose=False,
    )
    logger.info("Best NCAA iteration: %d", model.best_iteration)
    return model


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
    """Train a regularized linear NCAA model on curated matchup differentials."""
    if not linear_feature_cols:
        logger.warning("No curated NCAA linear-model features available; skipping linear candidate.")
        return None

    model = LogisticRegression(
        C=ncaab_config.LINEAR_MODEL_C,
        max_iter=5000,
        solver="lbfgs",
    )
    model.fit(X_train[linear_feature_cols], y_train, sample_weight=sample_weight)
    return model


def compute_season_sample_weights(df: pd.DataFrame) -> np.ndarray:
    """Exponentially up-weight more recent NCAA tournament seasons."""
    season_year = pd.to_numeric(df["Season"], errors="coerce").fillna(0).astype(int)
    min_year = int(season_year.min()) if len(season_year) else 0
    base = np.exp(ncaab_config.RECENCY_DECAY * (season_year - min_year)).astype(float)
    if "sample_weight_multiplier" not in df.columns:
        return base
    multiplier = pd.to_numeric(df["sample_weight_multiplier"], errors="coerce").fillna(1.0).to_numpy(dtype=float)
    return base * multiplier


def tune_hyperparameters(
    X_train: pd.DataFrame,
    y_train: pd.Series,
    n_trials: int = 50,
) -> dict:
    """Tune NCAA XGBoost hyperparameters with time-series cross validation."""
    try:
        import optuna

        optuna.logging.set_verbosity(optuna.logging.WARNING)
    except ImportError:
        logger.warning("optuna not installed; skipping NCAA hyperparameter tuning")
        return ncaab_config.XGB_PARAMS.copy()

    if len(X_train) < 300:
        logger.warning("NCAA training set too small for robust tuning; using default params")
        return ncaab_config.XGB_PARAMS.copy()

    n_splits = min(5, max(2, len(X_train) // 400))
    tscv = TimeSeriesSplit(n_splits=n_splits)

    def objective(trial: "optuna.Trial") -> float:
        params = {
            "objective": "binary:logistic",
            "eval_metric": "logloss",
            "random_state": 42,
            "max_depth": trial.suggest_int("max_depth", 2, 5),
            "learning_rate": trial.suggest_float("learning_rate", 0.01, 0.08, log=True),
            "n_estimators": trial.suggest_int("n_estimators", 300, 1200, step=100),
            "min_child_weight": trial.suggest_int("min_child_weight", 4, 20),
            "subsample": trial.suggest_float("subsample", 0.6, 0.95),
            "colsample_bytree": trial.suggest_float("colsample_bytree", 0.4, 0.9),
            "gamma": trial.suggest_float("gamma", 0.0, 3.0),
            "reg_alpha": trial.suggest_float("reg_alpha", 0.1, 10.0, log=True),
            "reg_lambda": trial.suggest_float("reg_lambda", 1.0, 20.0, log=True),
        }
        scores: list[float] = []
        for tr_idx, val_idx in tscv.split(X_train):
            Xtr, Xv = X_train.iloc[tr_idx], X_train.iloc[val_idx]
            ytr, yv = y_train.iloc[tr_idx], y_train.iloc[val_idx]
            n_estimators = params["n_estimators"]
            fold_params = params.copy()
            fold_params.pop("n_estimators")
            model = XGBClassifier(
                **fold_params,
                n_estimators=n_estimators,
                early_stopping_rounds=30,
            )
            model.fit(Xtr, ytr, eval_set=[(Xv, yv)], verbose=False)
            preds = np.clip(model.predict_proba(Xv)[:, 1], 1e-7, 1.0 - 1e-7)
            scores.append(float(log_loss(yv, preds)))
        return float(np.mean(scores))

    study = optuna.create_study(direction="minimize")
    study.optimize(objective, n_trials=n_trials, show_progress_bar=False)
    best = study.best_params
    best["objective"] = "binary:logistic"
    best["eval_metric"] = "logloss"
    best["random_state"] = 42
    logger.info("Best NCAA params: %s | Best log loss: %.4f", best, study.best_value)
    return best


def select_blend_weight(
    y_true: pd.Series,
    xgb_probs: np.ndarray,
    linear_probs: np.ndarray,
) -> tuple[float, float]:
    """Choose the ensemble blend weight using validation log loss."""
    best_weight = 1.0
    xgb_probs = _clip_probs(xgb_probs)
    linear_probs = _clip_probs(linear_probs)
    best_score = float(log_loss(y_true, xgb_probs))

    weight_step = max(float(ncaab_config.ENSEMBLE_WEIGHT_STEP), 0.01)
    grid_size = int(round(1.0 / weight_step))
    for idx in range(grid_size + 1):
        weight = min(idx * weight_step, 1.0)
        blended = _clip_probs(weight * xgb_probs + (1.0 - weight) * linear_probs)
        score = float(log_loss(y_true, blended))
        if score < best_score:
            best_weight = weight
            best_score = score

    return best_weight, best_score


def save_model(
    model: XGBClassifier,
    calibrated_model,
    feature_cols: list[str],
    fill_values: pd.Series,
) -> None:
    """Persist NCAA model artifacts."""
    model.save_model(str(MODEL_DIR / "xgb_model.json"))
    joblib.dump(calibrated_model, MODEL_DIR / "calibrated_model.joblib")
    joblib.dump(feature_cols, MODEL_DIR / "feature_cols.joblib")
    joblib.dump(fill_values, MODEL_DIR / "fill_values.joblib")


def load_model() -> tuple[CalibratedNCAABModel | EnsembleCalibratedNCAABModel, list[str], pd.Series]:
    """Load NCAA model artifacts."""
    model = joblib.load(MODEL_DIR / "calibrated_model.joblib")
    feature_cols = joblib.load(MODEL_DIR / "feature_cols.joblib")
    fill_values = joblib.load(MODEL_DIR / "fill_values.joblib")
    return model, feature_cols, fill_values


def _train_and_blend(
    train_df: pd.DataFrame,
    val_df: pd.DataFrame,
    feature_cols: list[str],
    linear_feature_cols: list[str],
    params: dict | None = None,
) -> CalibratedNCAABModel | EnsembleCalibratedNCAABModel:
    """Internal helper: train XGB + optional linear blend on given splits."""
    sample_weight = compute_season_sample_weights(train_df)
    fill_values = compute_fill_values(train_df, feature_cols)
    X_train, y_train = prepare_xy(train_df, feature_cols, fill_values=fill_values)
    X_val, y_val = prepare_xy(val_df, feature_cols, fill_values=fill_values)

    best_params = params if params is not None else ncaab_config.XGB_PARAMS.copy()
    raw_model = train_xgb(X_train, y_train, X_val, y_val, params=best_params, sample_weight=sample_weight)

    # Use tournament games for calibration only when the set is large enough
    # for isotonic regression to be stable (at least 200 samples).
    val_cal = val_df
    if "is_tournament" in val_df.columns:
        tourney_val = val_df[val_df["is_tournament"] == 1]
        if len(tourney_val) >= 200:
            val_cal = tourney_val
    X_val_cal, y_val_cal = prepare_xy(val_cal, feature_cols, fill_values=fill_values)

    val_raw_probs = raw_model.predict_proba(X_val_cal)[:, 1]
    calibrator = calibrate_probabilities(val_raw_probs, y_val_cal)
    calibrated_model = CalibratedNCAABModel(raw_model, calibrator)

    selected: CalibratedNCAABModel | EnsembleCalibratedNCAABModel = calibrated_model
    if ncaab_config.ENABLE_LINEAR_BLEND:
        linear_model = train_linear_model(X_train, y_train, linear_feature_cols, sample_weight=sample_weight)
        if linear_model is not None:
            val_linear_raw = linear_model.predict_proba(X_val_cal[linear_feature_cols])[:, 1]
            linear_calibrator = calibrate_probabilities(val_linear_raw, y_val_cal)
            val_linear_probs = linear_calibrator.predict(val_linear_raw)
            blend_weight, blend_logloss = select_blend_weight(
                y_val_cal,
                calibrated_model.predict_proba(X_val_cal)[:, 1],
                val_linear_probs,
            )
            logger.info(
                "Ensemble weight: %.2f XGB / %.2f linear (val log loss %.4f)",
                blend_weight, 1.0 - blend_weight, blend_logloss,
            )
            selected = EnsembleCalibratedNCAABModel(
                xgb_model=raw_model,
                xgb_calibrator=calibrator,
                linear_model=linear_model,
                linear_calibrator=linear_calibrator,
                feature_cols=feature_cols,
                linear_feature_cols=linear_feature_cols,
                xgb_weight=blend_weight,
            )
    return selected


def walkforward_cv(
    df: pd.DataFrame,
    test_years: list[int] | None = None,
) -> list[dict]:
    """Evaluate the model via walk-forward cross-validation.

    For each *test_year*, train on all prior seasons (skipping 2020 which
    had no tournament), validate on the season immediately before, and test
    on tournament games from *test_year*.  Returns per-year metrics.
    """
    from sklearn.metrics import accuracy_score, brier_score_loss, roc_auc_score

    if test_years is None:
        test_years = ncaab_config.WALKFORWARD_TEST_YEARS

    feature_cols = get_feature_columns(df)
    linear_feature_cols = get_linear_feature_columns(feature_cols)
    results: list[dict] = []

    for test_year in test_years:
        # Test: tournament games from test_year
        test_mask = (df["Season"] == test_year)
        if "is_tournament" in df.columns:
            tourney_mask = df["is_tournament"] == 1
            test_cand = df[test_mask & tourney_mask]
            if test_cand.empty:
                test_cand = df[test_mask]
        else:
            test_cand = df[test_mask]
        if test_cand.empty:
            logger.warning("No test data for %d, skipping", test_year)
            continue

        # Val: previous season (skip 2020)
        val_year = test_year - 1
        if val_year == 2020:
            val_year = 2019
        val_mask = df["Season"] == val_year
        val_df = df[val_mask]
        if val_df.empty:
            logger.warning("No val data for %d (val year %d), skipping", test_year, val_year)
            continue

        # Train: all years before val_year, skip 2020
        train_mask = (df["Season"] < val_year) & (df["Season"] != 2020)
        train_df = df[train_mask]
        if len(train_df) < 100:
            logger.warning("Insufficient training data for test year %d, skipping", test_year)
            continue

        fill_values = compute_fill_values(train_df, feature_cols)
        model = _train_and_blend(train_df, val_df, feature_cols, linear_feature_cols)

        X_test, y_test = prepare_xy(test_cand, feature_cols, fill_values=fill_values)
        probs = model.predict_proba(X_test)[:, 1]
        preds = (probs >= 0.5).astype(int)

        year_metrics = {
            "year": test_year,
            "n_games": len(y_test),
            "accuracy": float(accuracy_score(y_test, preds)),
            "log_loss": float(log_loss(y_test, _clip_probs(probs))),
            "brier": float(brier_score_loss(y_test, probs)),
        }
        try:
            year_metrics["auc"] = float(roc_auc_score(y_test, probs))
        except ValueError:
            year_metrics["auc"] = float("nan")

        logger.info(
            "WF-CV %d: acc=%.3f  auc=%.3f  logloss=%.3f  brier=%.3f  (n=%d)",
            test_year,
            year_metrics["accuracy"],
            year_metrics.get("auc", 0),
            year_metrics["log_loss"],
            year_metrics["brier"],
            year_metrics["n_games"],
        )
        results.append(year_metrics)

    if results:
        mean_acc = np.mean([r["accuracy"] for r in results])
        mean_ll = np.mean([r["log_loss"] for r in results])
        mean_brier = np.mean([r["brier"] for r in results])
        aucs = [r["auc"] for r in results if not np.isnan(r.get("auc", float("nan")))]
        mean_auc = np.mean(aucs) if aucs else float("nan")
        logger.info(
            "WF-CV MEAN: acc=%.3f  auc=%.3f  logloss=%.3f  brier=%.3f  (%d years)",
            mean_acc, mean_auc, mean_ll, mean_brier, len(results),
        )

    return results


def run_training_pipeline(
    df: pd.DataFrame,
    tune: bool = False,
    n_trials: int = 50,
) -> tuple[CalibratedNCAABModel | EnsembleCalibratedNCAABModel, list[str], pd.DataFrame, np.ndarray]:
    """Train, calibrate, and save the NCAA model."""
    feature_cols = get_feature_columns(df)
    train_df, val_df, test_df = temporal_split(df)
    if train_df.empty:
        raise ValueError("No NCAA training rows found for the configured train seasons.")
    if val_df.empty:
        raise ValueError("No NCAA validation rows found for the configured validation seasons.")
    if test_df.empty:
        raise ValueError("No NCAA test rows found for the configured test seasons.")
    fill_values = compute_fill_values(train_df, feature_cols)
    linear_feature_cols = get_linear_feature_columns(feature_cols)

    X_train, y_train = prepare_xy(train_df, feature_cols, fill_values=fill_values)

    best_params = tune_hyperparameters(X_train, y_train, n_trials=n_trials) if tune else ncaab_config.XGB_PARAMS.copy()
    selected_model = _train_and_blend(train_df, val_df, feature_cols, linear_feature_cols, params=best_params)

    X_test, _ = prepare_xy(test_df, feature_cols, fill_values=fill_values)
    test_probs = selected_model.predict_proba(X_test)[:, 1]

    # Extract raw XGB model for artifact saving
    raw_model = selected_model.xgb_model if hasattr(selected_model, "xgb_model") else selected_model.model
    save_model(raw_model, selected_model, feature_cols, fill_values)
    return selected_model, feature_cols, test_df, test_probs


def save_metrics(metrics: dict) -> None:
    """Persist NCAA evaluation metrics for the app."""
    ncaab_config.NCAAB_METRICS_JSON.write_text(json.dumps(metrics, indent=2))
