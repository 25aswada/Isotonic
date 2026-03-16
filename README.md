# NBA Prediction Model

An end-to-end NBA game outcome prediction system using XGBoost, built for finding +EV trades on Kalshi and Polymarket.

## Setup

```bash
pip install -r requirements.txt
```

## Workflow

### 1. Collect Data
```bash
python scripts/build_dataset.py
```
Pulls 8 seasons of NBA game logs from `nba_api`, engineers leak-free pregame features, and saves to `data/processed/model_ready.csv`.

### 2. Train Model
```bash
python scripts/train.py
```
Trains XGBoost with temporal splits, runs calibration, saves to `models/`.

### 3. Daily Predictions
```bash
python scripts/daily_predictions.py
```
Pulls today's games, rebuilds current team state from cached raw logs, applies the official NBA injury report as a live availability overlay, compares model probabilities to live market odds, and outputs a bet recommendation table.

### 4. Launch Dashboard
```bash
streamlit run app.py
```
Opens the interactive Streamlit dashboard at `http://localhost:8501`.

### 5. Paper Trade Kalshi / Polymarket
```bash
python scripts/paper_trade.py
python scripts/paper_trade.py --place
```
Previews or logs simulated YES-share trades using live Kalshi / Polymarket prices and settles them into `data/paper_trades.csv` once results are available.
The paper trader uses executable ask prices, includes Kalshi taker fees, applies Polymarket's market-specific fee schedule when the API reports one, models entry and exit slippage, tracks live mark-to-market value off the current bid, and stores market snapshots for later CLV analysis.

### 6. Run Tests
```bash
python -m unittest discover -s tests -v
```
Runs the regression tests for injury parsing, CLV tracking, and live paper-trading valuation.

## March Madness NCAAB App

### 1. Build NCAA Data
```bash
python scripts/build_ncaab_dataset.py
```
Downloads the public March Machine Learning Mania-style CSVs, builds seeded team-season profiles, and writes the tournament training set to `data/ncaab/processed/model_ready.csv`.

### 2. Train NCAA Tournament Model
```bash
python scripts/train_ncaab.py
```
Trains a calibrated XGBoost tournament winner model on historical NCAA tournament games and saves artifacts to `models/ncaab/`.

### 3. Launch NCAA Dashboard
```bash
streamlit run ncaab_app.py
```
Opens the separate March Madness dashboard with a bracket board, matchup lab, model report, and seeded-team board.

### 4. Refresh The Current Projected 2026 Field
```bash
python scripts/update_ncaab_current.py
```
Pulls the current 2026 Sports Reference team stats, the official NCAA NET rankings, and the latest Inside the Hall bracketology projection, then writes the projected 68-team field and a simulated bracket into `data/ncaab/processed/`.

## Project Structure

```
nba-predictor/
├── config.py              # API keys, constants
├── app.py                 # Streamlit dashboard
├── data/
│   ├── raw/               # Cached API pulls
│   └── processed/         # Feature-engineered datasets
├── src/
│   ├── data_collection.py
│   ├── odds_collection.py
│   ├── feature_engineering.py
│   ├── elo.py
│   ├── model.py
│   ├── evaluate.py
│   └── predict.py
├── scripts/
│   ├── build_dataset.py
│   ├── train.py
│   └── daily_predictions.py
└── models/                # Saved model artifacts
```

## Key Design Decisions

- **Calibrated probabilities**: Uses isotonic regression calibration so model outputs are true win probabilities, not just rankings.
- **No data leakage**: All features use only pre-game data. Rolling stats computed with `.shift(1)` to exclude current game.
- **Rolling advanced metrics**: Offensive rating, defensive rating, pace, eFG%, and TS% are derived from completed game logs instead of leaked end-of-season summaries.
- **Temporal splits**: Train/val/test split by season to prevent future leakage.
- **Elo ratings**: Dynamic team strength that adapts game-by-game, mean-reverts each season.
- **Kelly Criterion**: Quarter-Kelly sizing for conservative bankroll management.
- **Live availability overlay**: Uses the official NBA injury report and current player stats to shift probabilities when major absences are confirmed.
- **Paper trading**: Simulates prediction-market trades with executable prices, exchange fees, slippage assumptions, live mark-to-market tracking, CLV tracking, bankroll tracking, and settled P/L before risking real money.
- **Market snapshots and CLV**: Every live odds pull can be written to `data/market_snapshots.csv`, which powers closing-line value analysis in the CLI and Streamlit app.
- **Ops monitoring**: Alerts and runtime logs are stored locally in `data/alerts.csv` and `logs/`, and the dashboard includes an Ops Monitor page for quick health checks.

## Dashboard Pages

- **Today's Picks**: Split into `Best Value Bets`, `Most Likely Winners`, and `Full Board`, with short explanations for why the model leans each way.
- **Paper Trader**: Shows candidate trades, open positions, live P/L, estimated equity, CLV, and settled performance.
- **Model Performance**: Test-set metrics, calibration, and ROI backtests.
- **Team Explorer**: Team-level Elo and rolling form.
- **Bet Tracker**: Historical model picks with flat-bet P/L and closing-line comparisons.
- **Ops Monitor**: Recent alerts, market snapshot freshness, and ingestion coverage.

## Important Files

- `data/paper_trades.csv`: Paper-trading ledger.
- `data/market_snapshots.csv`: Stored live market prices for CLV tracking.
- `data/alerts.csv`: Runtime alerts from odds and injury ingestion.
- `logs/*.log`: Rotating runtime logs for the app and scripts.

## Notes

- NBA markets are semi-efficient. A 2–3% ROI edge is genuinely useful.
- Add `ODDS_API_KEY` to `config.py` before running odds-related scripts.
- Initial data collection can take a while due to `nba_api` rate limits, but cached reruns are fast.
- The app uses polling-based live refresh, not exchange websockets, so marks update on refresh or on the configured auto-refresh interval.
