"""
train_ncaab.py - Train the March Madness XGBoost model.

Usage:
    python scripts/train_ncaab.py
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd

import ncaab_config
from src.evaluate import compute_metrics, compute_shap_values, plot_calibration, plot_feature_importance
from src.ncaab_model import load_model, prepare_xy, run_training_pipeline, save_metrics, walkforward_cv
from src.runtime import setup_project_logging

logger = setup_project_logging(__name__, "train_ncaab.log")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Train March Madness NCAA model")
    parser.add_argument("--tune", action="store_true", help="Run Optuna hyperparameter tuning")
    parser.add_argument("--n-trials", type=int, default=50, help="Number of Optuna trials")
    parser.add_argument("--skip-walkforward", action="store_true", help="Skip walk-forward CV")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    logger.info("=" * 60)
    logger.info("March Madness Model Trainer")
    logger.info("=" * 60)

    dataset_path = (
        ncaab_config.NCAAB_MODEL_READY_AUGMENTED_CSV
        if ncaab_config.NCAAB_MODEL_READY_AUGMENTED_CSV.exists()
        else ncaab_config.NCAAB_MODEL_READY_CSV
    )
    if not dataset_path.exists():
        logger.error("Dataset missing at %s. Run scripts/build_ncaab_dataset.py first.", dataset_path)
        sys.exit(1)

    df = pd.read_csv(dataset_path)
    model, feature_cols, test_df, test_probs = run_training_pipeline(
        df,
        tune=args.tune,
        n_trials=args.n_trials,
    )
    loaded_model, loaded_feature_cols, fill_values = load_model()

    X_test, y_test = prepare_xy(test_df, loaded_feature_cols, fill_values=fill_values)
    metrics = compute_metrics(y_test, loaded_model.predict_proba(X_test)[:, 1])
    model_type = "xgb_isotonic"
    xgb_weight = 1.0
    linear_weight = 0.0
    linear_features: list[str] = []
    if hasattr(loaded_model, "xgb_weight"):
        model_type = "xgb_linear_blend"
        xgb_weight = float(getattr(loaded_model, "xgb_weight", 1.0))
        linear_weight = 1.0 - xgb_weight
        linear_features = list(getattr(loaded_model, "linear_feature_cols", []))
    metrics.update(
        {
            "train_seasons": ncaab_config.TRAIN_SEASONS,
            "val_seasons": ncaab_config.VAL_SEASONS,
            "test_seasons": ncaab_config.TEST_SEASONS,
            "n_features": len(feature_cols),
            "dataset_path": str(dataset_path),
            "train_rows": int(len(df[df["Season"].isin(ncaab_config.TRAIN_SEASONS)])),
            "val_rows": int(len(df[df["Season"].isin(ncaab_config.VAL_SEASONS)])),
            "test_rows": int(len(test_df)),
            "model_type": model_type,
            "xgb_weight": xgb_weight,
            "linear_weight": linear_weight,
            "n_linear_features": len(linear_features),
            "tuned": bool(args.tune),
            "n_trials": int(args.n_trials),
        }
    )
    # ── Walk-forward cross-validation ──
    if not args.skip_walkforward:
        logger.info("\n" + "=" * 60)
        logger.info("Walk-Forward Cross-Validation")
        logger.info("=" * 60)
        wf_results = walkforward_cv(df)
        if wf_results:
            import numpy as _np
            metrics["walkforward"] = wf_results
            metrics["walkforward_mean_accuracy"] = float(_np.mean([r["accuracy"] for r in wf_results]))
            metrics["walkforward_mean_logloss"] = float(_np.mean([r["log_loss"] for r in wf_results]))
            metrics["walkforward_years"] = len(wf_results)

    save_metrics(metrics)

    ncaab_config.NCAAB_PLOTS_DIR.mkdir(parents=True, exist_ok=True)
    plot_calibration(
        y_test,
        test_probs,
        save_path=str(ncaab_config.NCAAB_PLOTS_DIR / "calibration.png"),
        title="Calibration Plot - March Madness Winner Model",
    )
    plot_feature_importance(model, feature_cols, save_path=str(ncaab_config.NCAAB_PLOTS_DIR / "feature_importance.png"))
    try:
        compute_shap_values(model, X_test, save_path=str(ncaab_config.NCAAB_PLOTS_DIR / "shap_summary.png"))
    except Exception as exc:
        logger.warning("NCAA SHAP failed: %s", exc)

    logger.info("Saved NCAA metrics to %s", ncaab_config.NCAAB_METRICS_JSON)

    logger.info("\nTraining NCAA score regression model...")
    try:
        from src.ncaab_data import load_raw_csv
        from src.score_model import train_ncaa_score_model
        reg_season = load_raw_csv("MRegularSeasonDetailedResults.csv")
        score_feature_path = (
            ncaab_config.NCAAB_ALL_TEAM_FEATURES_CSV
            if ncaab_config.NCAAB_ALL_TEAM_FEATURES_CSV.exists()
            else ncaab_config.NCAAB_TEAM_FEATURES_CSV
        )
        team_feats = pd.read_csv(score_feature_path)
        score_metrics = train_ncaa_score_model(
            reg_season, team_feats,
            train_seasons=ncaab_config.TRAIN_SEASONS,
            val_seasons=ncaab_config.VAL_SEASONS,
            test_seasons=ncaab_config.TEST_SEASONS,
        )
        for tgt, m in score_metrics.items():
            logger.info("  %s — MAE: %.2f  RMSE: %.2f", tgt, m["mae"], m["rmse"])
        logger.info("✓ NCAA score model saved.")
    except Exception as e:
        logger.warning("NCAA score model training failed: %s", e)


if __name__ == "__main__":
    main()
