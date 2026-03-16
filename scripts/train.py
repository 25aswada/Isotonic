"""
train.py — Train and save the XGBoost model.

Usage:
    python scripts/train.py [--tune] [--n-trials 50]
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import numpy as np
import pandas as pd

import config
from src.model import run_training_pipeline
from src.evaluate import (
    compute_metrics,
    plot_calibration,
    plot_feature_importance,
    compute_shap_values,
    run_backtest,
    plot_roi_curves,
)
from src.model import load_model, prepare_xy, get_feature_columns
from src.runtime import setup_project_logging

logger = setup_project_logging(__name__, "train.log")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Train NBA prediction model")
    p.add_argument("--tune", action="store_true", help="Run Optuna hyperparameter tuning")
    p.add_argument("--n-trials", type=int, default=50, help="Number of Optuna trials")
    p.add_argument(
        "--data",
        default=config.MODEL_READY_CSV,
        help="Path to model_ready.csv",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("=" * 60)
    logger.info("NBA Prediction Model Trainer")
    logger.info("=" * 60)

    # Load data
    data_path = Path(args.data)
    if not data_path.exists():
        logger.error("Dataset not found at %s. Run scripts/build_dataset.py first.", data_path)
        sys.exit(1)

    logger.info("Loading dataset from %s...", data_path)
    df = pd.read_csv(data_path)
    df["game_date"] = pd.to_datetime(df["game_date"])
    logger.info("  %d games loaded", len(df))

    # Train
    calibrated_model, feature_cols, test_df = run_training_pipeline(
        df, tune=args.tune, n_trials=args.n_trials
    )

    # Evaluate on test set
    logger.info("\nEvaluating on test set (2024-25)...")
    medians = pd.read_pickle if False else None  # loaded via load_model below
    model, feat_cols, medians = load_model()
    X_test, y_test = prepare_xy(test_df, feat_cols, fill_values=medians)

    test_probs = np.clip(model.predict_proba(X_test)[:, 1], 1e-7, 1 - 1e-7)
    metrics = compute_metrics(y_test, test_probs)

    logger.info("\nTest Set Metrics:")
    for k, v in metrics.items():
        if isinstance(v, float):
            logger.info("  %-20s %.4f", k, v)

    # Plots
    logger.info("\nGenerating evaluation plots...")
    Path("data/plots").mkdir(parents=True, exist_ok=True)
    plot_calibration(y_test, test_probs, save_path="data/plots/calibration.png")
    plot_feature_importance(model, feat_cols, save_path="data/plots/feature_importance.png")

    try:
        compute_shap_values(model, X_test, save_path="data/plots/shap_summary.png")
    except Exception as e:
        logger.warning("SHAP failed: %s", e)

    # ROI backtest
    logger.info("\nRunning ROI backtest...")
    backtest = run_backtest(test_df, test_probs)
    plot_roi_curves(backtest, save_path="data/plots/roi_curves.png")

    logger.info("\n✓ Training complete. Artifacts saved to models/")

    logger.info("\nTraining NBA score regression model...")
    try:
        from src.score_model import train_nba_score_model
        score_metrics = train_nba_score_model(df)
        for tgt, m in score_metrics.items():
            logger.info("  %s — MAE: %.2f  RMSE: %.2f", tgt, m["mae"], m["rmse"])
        logger.info("✓ NBA score model saved.")
    except Exception as e:
        logger.warning("Score model training failed: %s", e)


if __name__ == "__main__":
    main()

# ── re-open and patch to add score model ──
