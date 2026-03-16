"""
evaluate.py — Model evaluation: metrics, calibration plots, feature importance,
ROI backtest, Kelly criterion sizing.
"""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Core metrics
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(y_true: pd.Series, y_pred: np.ndarray) -> dict:
    y_pred = np.clip(y_pred, 1e-7, 1 - 1e-7)
    """
    Compute log loss, Brier score, accuracy, and AUC-ROC.
    """
    from sklearn.metrics import (
        accuracy_score,
        brier_score_loss,
        log_loss,
        roc_auc_score,
    )

    metrics = {
        "log_loss": log_loss(y_true, y_pred),
        "brier_score": brier_score_loss(y_true, y_pred),
        "accuracy": accuracy_score(y_true, (y_pred >= 0.5).astype(int)),
        "auc_roc": roc_auc_score(y_true, y_pred),
        "n_games": len(y_true),
    }
    for k, v in metrics.items():
        if k != "n_games":
            logger.info("  %s: %.4f", k, v)
    return metrics


# ─────────────────────────────────────────────────────────────────────────────
# Calibration
# ─────────────────────────────────────────────────────────────────────────────

def calibration_data(y_true: pd.Series, y_pred: np.ndarray, n_bins: int = 10) -> pd.DataFrame:
    """
    Return a DataFrame with bin midpoints, mean predicted prob, and actual win rate.
    """
    from sklearn.calibration import calibration_curve
    fraction_of_positives, mean_predicted = calibration_curve(y_true, y_pred, n_bins=n_bins)
    return pd.DataFrame({
        "mean_predicted": mean_predicted,
        "fraction_positive": fraction_of_positives,
    })


def plot_calibration(
    y_true: pd.Series,
    y_pred: np.ndarray,
    save_path: str | None = None,
    title: str = "Calibration Plot - Prediction Model",
) -> None:
    """Plot a reliability diagram (calibration plot)."""
    import matplotlib.pyplot as plt
    from sklearn.calibration import calibration_curve

    fraction_pos, mean_pred = calibration_curve(y_true, y_pred, n_bins=10)

    fig, ax = plt.subplots(figsize=(7, 6))
    ax.plot([0, 1], [0, 1], "k--", label="Perfect calibration")
    ax.plot(mean_pred, fraction_pos, "s-", color="#FF6B35", label="Model (calibrated)")
    ax.set_xlabel("Mean Predicted Probability")
    ax.set_ylabel("Fraction of Positives (Actual Win Rate)")
    ax.set_title(title)
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150)
        logger.info("Calibration plot saved to %s", save_path)
    else:
        plt.show()
    plt.close(fig)


# ─────────────────────────────────────────────────────────────────────────────
# Feature importance
# ─────────────────────────────────────────────────────────────────────────────

def plot_feature_importance(model, feature_cols: list[str], top_n: int = 20, save_path: str | None = None) -> pd.DataFrame:
    """
    Plot top-N features by XGBoost gain importance.
    Returns a DataFrame with feature importances.
    """
    import matplotlib.pyplot as plt

    raw_model = getattr(model, "estimator", None)
    if raw_model is not None and hasattr(raw_model, "calibrated_classifiers_"):
        raw_model = raw_model.calibrated_classifiers_[0].estimator

    if raw_model is not None and hasattr(raw_model, "feature_importances_"):
        importances = np.asarray(raw_model.feature_importances_, dtype=float)
    elif hasattr(model, "feature_importances_"):
        importances = np.asarray(model.feature_importances_, dtype=float)
    else:
        raise ValueError("Model does not expose feature importances.")

    imp_df = pd.DataFrame({"feature": feature_cols, "importance": importances})
    imp_df = imp_df.sort_values("importance", ascending=False).head(top_n)

    fig, ax = plt.subplots(figsize=(10, 8))
    ax.barh(imp_df["feature"][::-1], imp_df["importance"][::-1], color="#FF6B35")
    ax.set_xlabel("Feature Importance (Gain)")
    ax.set_title(f"Top {top_n} Features — Winner Model")
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150)
        logger.info("Feature importance plot saved to %s", save_path)
    else:
        plt.show()
    plt.close(fig)

    return imp_df


def compute_shap_values(model, X: pd.DataFrame, save_path: str | None = None) -> np.ndarray | None:
    """Compute SHAP values if the shap library is available."""
    try:
        import shap

        raw_model = getattr(model, "estimator", None)
        if raw_model is None or not hasattr(raw_model, "feature_importances_"):
            logger.warning("Model has no tree estimator available for SHAP; skipping.")
            return None
        if hasattr(raw_model, "calibrated_classifiers_"):
            raw_model = raw_model.calibrated_classifiers_[0].estimator

        explainer = shap.TreeExplainer(raw_model)
        shap_values = explainer.shap_values(X)

        shap.summary_plot(shap_values, X, show=False)
        import matplotlib.pyplot as plt
        if save_path:
            plt.savefig(save_path, dpi=150, bbox_inches="tight")
            logger.info("SHAP summary plot saved to %s", save_path)
        else:
            plt.show()
        plt.close()

        return shap_values
    except ImportError:
        logger.warning("shap library not installed — skipping SHAP analysis")
        return None


# ─────────────────────────────────────────────────────────────────────────────
# ROI Backtest
# ─────────────────────────────────────────────────────────────────────────────

def american_to_decimal(american_odds: float) -> float:
    """Convert American moneyline odds to decimal odds."""
    if american_odds > 0:
        return 1.0 + american_odds / 100.0
    else:
        return 1.0 + 100.0 / abs(american_odds)


def decimal_to_implied_prob(decimal_odds: float) -> float:
    """Convert decimal odds to implied probability (raw, not vig-adjusted)."""
    return 1.0 / decimal_odds


def kelly_fraction(model_prob: float, decimal_odds: float) -> float:
    """
    Full Kelly fraction. Use quarter-Kelly (multiply by KELLY_FRACTION) in practice.

    kelly = (p * decimal_odds - 1) / (decimal_odds - 1)
    """
    b = decimal_odds - 1.0
    if b <= 0:
        return 0.0
    kelly = (model_prob * decimal_odds - 1.0) / b
    return max(kelly, 0.0)


def run_backtest(
    test_df: pd.DataFrame,
    model_probs: np.ndarray,
    thresholds: list[float] | None = None,
    bankroll: float = 1000.0,
) -> dict:
    """
    Simulate flat-bet and Kelly-bet strategies for each edge threshold.

    Parameters
    ----------
    test_df : pd.DataFrame
        Must have columns: home_win, and optionally home_odds_decimal / away_odds_decimal.
        If odds columns are missing, uses a fixed -110 line (decimal 1.909).
    model_probs : np.ndarray
        Model's predicted home-win probability for each game.
    thresholds : list[float]
        Minimum edge (model_prob - market_implied) to place a bet.
    bankroll : float
        Starting bankroll for Kelly sizing.

    Returns
    -------
    dict of threshold → results dict
    """
    if thresholds is None:
        thresholds = config.EDGE_THRESHOLDS

    DEFAULT_HOME_DECIMAL = 1.909  # -110 moneyline
    DEFAULT_AWAY_DECIMAL = 1.909

    df = test_df.copy().reset_index(drop=True)
    df["model_prob"] = model_probs

    if "home_odds_decimal" not in df.columns:
        df["home_odds_decimal"] = DEFAULT_HOME_DECIMAL
    if "away_odds_decimal" not in df.columns:
        df["away_odds_decimal"] = DEFAULT_AWAY_DECIMAL
    if "home_odds_decimal" not in test_df.columns or "away_odds_decimal" not in test_df.columns:
        logger.warning("Backtest is using placeholder -110 odds because historical closing prices are unavailable.")

    df["market_home_implied"] = 1.0 / df["home_odds_decimal"]
    df["edge"] = df["model_prob"] - df["market_home_implied"]

    results = {}
    for thresh in thresholds:
        bet_df = df[df["edge"] >= thresh].copy()
        if bet_df.empty:
            results[thresh] = {"n_bets": 0, "win_rate": None, "roi": None}
            continue

        # Flat bet: $1 per game
        bet_df["flat_pnl"] = np.where(
            bet_df["home_win"] == 1,
            bet_df["home_odds_decimal"] - 1,  # win: decimal_odds - 1
            -1.0,
        )
        flat_roi = bet_df["flat_pnl"].sum() / len(bet_df)

        # Kelly bet
        bet_df["kelly"] = bet_df.apply(
            lambda r: kelly_fraction(r["model_prob"], r["home_odds_decimal"]) * config.KELLY_FRACTION,
            axis=1,
        )
        bet_df["kelly"] = bet_df["kelly"].clip(lower=config.MIN_KELLY_BET, upper=0.25)
        bet_df["kelly_stake"] = bet_df["kelly"] * bankroll
        bet_df["kelly_pnl"] = np.where(
            bet_df["home_win"] == 1,
            bet_df["kelly_stake"] * (bet_df["home_odds_decimal"] - 1),
            -bet_df["kelly_stake"],
        )
        kelly_roi = bet_df["kelly_pnl"].sum() / bet_df["kelly_stake"].sum()

        # Max drawdown (flat)
        cumulative = bet_df["flat_pnl"].cumsum()
        roll_max = cumulative.cummax()
        drawdown = cumulative - roll_max
        max_dd = drawdown.min()

        results[thresh] = {
            "n_bets": len(bet_df),
            "win_rate": bet_df["home_win"].mean(),
            "flat_roi": flat_roi,
            "kelly_roi": kelly_roi,
            "max_drawdown": max_dd,
            "total_pnl_flat": bet_df["flat_pnl"].sum(),
            "total_pnl_kelly": bet_df["kelly_pnl"].sum(),
            "cumulative_pnl": bet_df["flat_pnl"].cumsum().tolist(),
            "bet_dates": bet_df["game_date"].astype(str).tolist() if "game_date" in bet_df.columns else [],
        }
        logger.info(
            "Threshold %.2f → %d bets | win rate %.1f%% | flat ROI %.1f%% | Kelly ROI %.1f%% | max DD %.2f",
            thresh,
            results[thresh]["n_bets"],
            results[thresh]["win_rate"] * 100,
            results[thresh]["flat_roi"] * 100,
            results[thresh]["kelly_roi"] * 100,
            results[thresh]["max_drawdown"],
        )

    return results


def plot_roi_curves(backtest_results: dict, save_path: str | None = None) -> None:
    """Plot cumulative P/L over time for each threshold."""
    import matplotlib.pyplot as plt

    fig, ax = plt.subplots(figsize=(12, 6))
    colors = ["#FF6B35", "#4ECDC4", "#45B7D1", "#96CEB4"]

    for (thresh, res), color in zip(backtest_results.items(), colors):
        if res.get("cumulative_pnl"):
            ax.plot(res["cumulative_pnl"], label=f"Edge ≥ {thresh:.0%}", color=color, linewidth=2)

    ax.axhline(0, color="white", linestyle="--", alpha=0.5)
    ax.set_xlabel("Bet Number")
    ax.set_ylabel("Cumulative P/L (flat $1 bets)")
    ax.set_title("ROI Backtest — Test Set (2024-25 Season)")
    ax.legend()
    ax.grid(alpha=0.3)
    fig.tight_layout()

    if save_path:
        fig.savefig(save_path, dpi=150)
        logger.info("ROI plot saved to %s", save_path)
    else:
        plt.show()
    plt.close(fig)
