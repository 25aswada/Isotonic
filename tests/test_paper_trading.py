import tempfile
import unittest
from pathlib import Path

import pandas as pd

from src.paper_trading import (
    _adjust_exit_price,
    _kalshi_fee_dollars,
    compute_live_paper_bankroll,
    load_paper_trades,
    mark_open_trades_to_market,
)


class PaperTradingTests(unittest.TestCase):
    def test_mark_to_market_uses_bid_slippage_and_exit_fee(self) -> None:
        trades = pd.DataFrame([
            {
                "trade_id": "t1",
                "market_source": "kalshi",
                "bet_side": "home",
                "home_team": "ORL",
                "away_team": "CLE",
                "status": "open",
                "entry_price": 0.40,
                "stake": 41.68,
                "payout_if_win": 100.0,
            }
        ])
        live_odds = pd.DataFrame([
            {
                "home_team": "ORL",
                "away_team": "CLE",
                "kalshi_home_bid_prob": 0.52,
                "kalshi_home_spread_prob": 0.04,
            }
        ])

        marked = mark_open_trades_to_market(trades, live_odds)
        effective_exit_price, _ = _adjust_exit_price(0.52, spread=0.04)
        expected_exit_fee = round(_kalshi_fee_dollars(100, effective_exit_price), 2)
        expected_value = round((100.0 * effective_exit_price) - expected_exit_fee, 2)

        self.assertAlmostEqual(marked.loc[0, "current_mark_price"], 0.52)
        self.assertAlmostEqual(marked.loc[0, "current_exit_fee"], expected_exit_fee)
        self.assertAlmostEqual(marked.loc[0, "current_value"], expected_value)
        self.assertAlmostEqual(marked.loc[0, "unrealized_pnl"], round(expected_value - 41.68, 2))

        bankroll = compute_live_paper_bankroll(marked, starting_bankroll=1000.0)
        self.assertAlmostEqual(bankroll["live_open_value"], expected_value)
        self.assertAlmostEqual(bankroll["estimated_equity"], round(1000.0 - 41.68 + expected_value, 2), places=2)

    def test_load_paper_trades_handles_legacy_rows_without_tipoff(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "paper_trades.csv"
            pd.DataFrame([
                {
                    "trade_id": "legacy",
                    "market_source": "kalshi",
                    "bet_side": "home",
                    "home_team": "ORL",
                    "away_team": "CLE",
                    "status": "open",
                    "entry_price": 0.40,
                    "stake": 20.0,
                }
            ]).to_csv(path, index=False)

            loaded = load_paper_trades(str(path))

        self.assertEqual(loaded.loc[0, "trade_stage"], "pregame")


if __name__ == "__main__":
    unittest.main()
