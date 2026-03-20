"""
config.py — API keys, constants, and season configuration.
"""

import os
from pathlib import Path


def _load_local_env() -> None:
    env_path = Path(".env")
    if not env_path.exists():
        return

    for raw_line in env_path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip())


_load_local_env()

# ── API Keys ──────────────────────────────────────────────────────────────────
ODDS_API_KEY = os.getenv("ODDS_API_KEY", "")

# ── Data Paths ────────────────────────────────────────────────────────────────
RAW_DATA_DIR = "data/raw"
PROCESSED_DATA_DIR = "data/processed"
MODEL_DIR = "models"
LOG_DIR = "logs"
DB_PATH = "data/nba.db"
PREDICTION_LOG = "data/prediction_log.csv"
PAPER_TRADES_CSV = "data/paper_trades.csv"
PAPER_COMBO_TRADES_CSV = "data/paper_combo_trades.csv"
MODEL_READY_CSV = "data/processed/model_ready.csv"
ELO_CSV = "data/processed/elo_history.csv"
MARKET_SNAPSHOTS_CSV = "data/market_snapshots.csv"
ALERTS_CSV = "data/alerts.csv"
LIVE_INJURY_CACHE = "data/raw/live_injuries.csv"
PLAYER_STATS_CACHE = "data/raw/player_stats_current.csv"

# ── Season Configuration ──────────────────────────────────────────────────────
SEASONS = [
    "2015-16",
    "2016-17",
    "2017-18",
    "2018-19",
    "2019-20",
    "2020-21",
    "2021-22",
    "2022-23",
    "2023-24",
    "2024-25",
    "2025-26",
]

TRAIN_SEASONS = ["2015-16", "2016-17", "2017-18", "2018-19", "2019-20", "2020-21", "2021-22", "2022-23"]
VAL_SEASONS   = ["2023-24"]
TEST_SEASONS  = ["2024-25"]
# 2025-26 is the live current season — used for daily predictions only

# ── Elo Parameters ────────────────────────────────────────────────────────────
ELO_K_FACTOR = 20
ELO_HOME_ADVANTAGE = 100
ELO_BASE = 1500
ELO_MEAN_REVERT_FRAC = 1 / 3

# ── Model Parameters ──────────────────────────────────────────────────────────
XGB_PARAMS = {
    "objective": "binary:logistic",
    "max_depth": 2,
    "learning_rate": 0.04,
    "n_estimators": 1200,
    "min_child_weight": 16,
    "subsample": 0.8,
    "colsample_bytree": 0.5,
    "gamma": 1.0,
    "reg_alpha": 1.5,
    "reg_lambda": 12.0,
    "eval_metric": "logloss",
    "random_state": 42,
}

EARLY_STOPPING_ROUNDS = 50
ENABLE_LINEAR_BLEND = True
RECENCY_DECAY = 0.3   # exp decay rate per season — higher = more weight on recent years
LINEAR_MODEL_C = 0.05
ENSEMBLE_WEIGHT_STEP = 0.05

# ── Prediction / Betting Parameters ──────────────────────────────────────────
EDGE_THRESHOLDS = [0.03, 0.05, 0.07, 0.10]
KELLY_FRACTION   = 0.25
MIN_KELLY_BET    = 0.005
PAPER_BANKROLL_START = 1000.0
PAPER_TRADE_EDGE = 0.03
PAPER_MAX_STAKE_PCT = 0.10
PAPER_ENTRY_SLIPPAGE_BPS = 20
PAPER_EXIT_SLIPPAGE_BPS = 20
PAPER_SPREAD_SLIPPAGE_FRACTION = 0.25
LIVE_POLL_SECONDS = 3
COMBO_MAX_LEGS = 8
COMBO_MIN_LEGS = 2
COMBO_MARGIN_STD = 12.0
COMBO_TOTAL_STD = 18.0

# ── Auto Paper Trader ─────────────────────────────────────────────────────────
AUTO_BET_MIN_EDGE     = 0.05   # minimum model edge to auto-place a paper trade
AUTO_BET_POLL_SECONDS = 900    # poll every 15 minutes
AUTO_BET_ACTIVE_HOURS = (6, 2) # active 6am–2am local time (tuple crosses midnight)
MARKET_SNAPSHOT_TTL_SECONDS = 60

# ── Odds API ──────────────────────────────────────────────────────────────────
ODDS_API_BASE_URL = "https://api.the-odds-api.com/v4"
SPORT_KEY = "basketball_nba"
ODDS_REGIONS = "us"
ODDS_MARKETS = "h2h"
ODDS_FORMAT = "decimal"
POLYMARKET_CLOB_BASE_URL = "https://clob.polymarket.com"
KALSHI_TAKER_FEE_RATE = 0.07
OFFICIAL_NBA_INJURY_REPORT_URL = "https://official.nba.com/nba-injury-report-2025-26-season/"

# ── Live Availability Parameters ─────────────────────────────────────────────
INJURY_STATUS_WEIGHTS = {
    "out": 1.0,
    "doubtful": 0.75,
    "questionable": 0.35,
    "probable": 0.10,
    "available": 0.0,
}
INJURY_IMPACT_ELO_MULTIPLIER = 45.0
INJURY_MAX_TEAM_ELO_PENALTY = 150.0

# ── Rolling Window Sizes ──────────────────────────────────────────────────────
ROLLING_WINDOWS = [5, 10, 15]

# ── nba_api Rate Limiting ─────────────────────────────────────────────────────
API_SLEEP = 0.6

# ── NBA Team Abbreviations (30 teams) ────────────────────────────────────────
NBA_TEAMS = [
    "ATL", "BOS", "BKN", "CHA", "CHI", "CLE", "DAL", "DEN", "DET", "GSW",
    "HOU", "IND", "LAC", "LAL", "MEM", "MIA", "MIL", "MIN", "NOP", "NYK",
    "OKC", "ORL", "PHI", "PHX", "POR", "SAC", "SAS", "TOR", "UTA", "WAS",
]
