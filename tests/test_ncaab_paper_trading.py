import unittest
from unittest.mock import Mock, patch

import pandas as pd

from src.ncaab_paper_trading import build_custom_ncaab_paper_trade


class NcaabPaperTradingTests(unittest.TestCase):
    @patch("requests.get")
    @patch("src.ncaab_odds.get_all_ncaab_market_odds")
    def test_build_custom_trade_matches_in_progress_game_via_live_name_mapping(
        self,
        mock_get_all_ncaab_market_odds,
        mock_requests_get,
    ) -> None:
        mock_live_response = Mock()
        mock_live_response.raise_for_status.return_value = None
        mock_live_response.json.return_value = {
            "in_progress": [
                {
                    "home_team": "UK",
                    "away_team": "SCU",
                    "home_full_name": "Kentucky Wildcats",
                    "away_full_name": "Santa Clara Broncos",
                }
            ],
            "upcoming": [],
            "final": [],
        }
        mock_requests_get.return_value = mock_live_response

        mock_get_all_ncaab_market_odds.return_value = pd.DataFrame(
            [
                {
                    "home_team": "Kentucky Wildcats",
                    "away_team": "Santa Clara Broncos",
                    "tipoff_utc": "2026-03-20T16:15:00Z",
                    "kalshi_home_prob": 0.61,
                    "kalshi_away_prob": 0.39,
                    "kalshi_home_ask_prob": 0.63,
                    "kalshi_away_ask_prob": 0.41,
                }
            ]
        )

        trade = build_custom_ncaab_paper_trade(
            home_team="UK",
            away_team="SCU",
            selected_team="SCU",
            custom_stake=50,
            bankroll_snapshot=200,
        )

        self.assertIsNotNone(trade)
        assert trade is not None
        self.assertEqual(trade["contract_team"], "SCU")
        self.assertEqual(trade["bet_side"], "away")
        self.assertAlmostEqual(float(trade["entry_price"]), 0.41)
        self.assertAlmostEqual(float(trade["market_prob"]), 0.39)
        self.assertAlmostEqual(float(trade["cash_after_trade"]), 150.04, places=2)


if __name__ == "__main__":
    unittest.main()
