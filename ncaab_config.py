"""
ncaab_config.py - Paths and modeling constants for the March Madness app.
"""

from __future__ import annotations

from pathlib import Path

ELO_BASE = 1500

NCAAB_DATA_DIR = Path("data/ncaab")
NCAAB_RAW_DIR = NCAAB_DATA_DIR / "raw"
NCAAB_PROCESSED_DIR = NCAAB_DATA_DIR / "processed"
NCAAB_PLOTS_DIR = NCAAB_DATA_DIR / "plots"
NCAAB_MODEL_DIR = Path("models/ncaab")

NCAAB_MODEL_READY_CSV = NCAAB_PROCESSED_DIR / "model_ready.csv"
NCAAB_TEAM_FEATURES_CSV = NCAAB_PROCESSED_DIR / "team_features.csv"
NCAAB_METRICS_JSON = NCAAB_PROCESSED_DIR / "metrics.json"
NCAAB_CURRENT_TEAM_FEATURES_CSV = NCAAB_PROCESSED_DIR / "current_team_features.csv"
NCAAB_CURRENT_ALL_TEAM_FEATURES_CSV = NCAAB_PROCESSED_DIR / "current_all_team_features.csv"
NCAAB_CURRENT_PROJECTED_FIELD_CSV = NCAAB_PROCESSED_DIR / "current_projected_field.csv"
NCAAB_CURRENT_PROJECTED_BRACKET_CSV = NCAAB_PROCESSED_DIR / "current_projected_bracket.csv"
NCAAB_CURRENT_META_JSON = NCAAB_PROCESSED_DIR / "current_projection_meta.json"

NCAAB_DATA_BASE_URL = "https://huggingface.co/Jensen-holm/Nigl/resolve/main/data"
NCAAB_RAW_FILES = [
    "MRegularSeasonDetailedResults.csv",
    "MNCAATourneyDetailedResults.csv",
    "MNCAATourneySeeds.csv",
    "MNCAATourneySlots.csv",
    "MTeams.csv",
    "MMasseyOrdinals.csv",
]

TRAIN_SEASONS = list(range(2003, 2023))
VAL_SEASONS = [2023]
TEST_SEASONS = [2024]
LATEST_BRACKET_SEASON = 2023
CURRENT_SEASON = 2026
CURRENT_BRACKETOLOGY_URL = "https://www.insidethehall.com/2026/03/15/bracketology-final-ncaa-tournament-projection-as-of-march-15th-2026/"
CURRENT_NET_URL = "https://www.ncaa.com/rankings/basketball-men/d1/ncaa-mens-basketball-net-rankings"
CURRENT_SPORTSREF_BASIC_URL = "https://www.sports-reference.com/cbb/seasons/men/2026-school-stats.html"
CURRENT_SPORTSREF_ADVANCED_URL = "https://www.sports-reference.com/cbb/seasons/men/2026-advanced-school-stats.html"
CURRENT_PROJECTION_DATE = "2026-03-15"

MODEL_BASE_FEATURES = [
    "seed_num",
    "elo",
    "win_pct",
    "avg_margin",
    "avg_score_for",
    "avg_score_against",
    "efg",
    "ts",
    "tov_rate",
    "ft_rate",
    "oreb_pct",
    "opp_efg",
    "off_rtg",
    "def_rtg",
    "net_rtg",
    "last10_win_pct",
    "last10_margin",
    "median_rank",
    "best_rank",
]

XGB_PARAMS = {
    "objective": "binary:logistic",
    "eval_metric": "logloss",
    "random_state": 42,
    "max_depth": 3,
    "learning_rate": 0.05,
    "n_estimators": 500,
    "min_child_weight": 8,
    "subsample": 0.8,
    "colsample_bytree": 0.7,
    "reg_alpha": 1.0,
    "reg_lambda": 8.0,
}
EARLY_STOPPING_ROUNDS = 50

ENABLE_LINEAR_BLEND = True
RECENCY_DECAY = 0.3
LINEAR_MODEL_C = 0.05
ENSEMBLE_WEIGHT_STEP = 0.05
ENABLE_ELO_SHRINK = True
ELO_SHRINK_RAMP_START = 50
ELO_SHRINK_RAMP_SCALE = 500
ELO_SHRINK_MIN = 0.35

LINEAR_MODEL_FEATURE_PRIORITY = [
    "seed_num_diff",
    "elo_diff",
    "win_pct_diff",
    "avg_margin_diff",
    "avg_score_for_diff",
    "avg_score_against_diff",
    "efg_diff",
    "ts_diff",
    "tov_rate_diff",
    "ft_rate_diff",
    "oreb_pct_diff",
    "opp_efg_diff",
    "off_rtg_diff",
    "def_rtg_diff",
    "net_rtg_diff",
    "last10_win_pct_diff",
    "last10_margin_diff",
    "median_rank_diff",
    "best_rank_diff",
]

ODDS_SPORT_KEY = "basketball_ncaab"
KALSHI_GAME_SERIES = "KXNCAAMBGAME"
MIN_WIN_PROB = 0.45
EDGE_THRESHOLD = 0.03
MARKET_LOOKBACK_DAYS = 0
MARKET_LOOKAHEAD_DAYS = 45
