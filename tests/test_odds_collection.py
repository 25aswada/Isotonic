import unittest
from unittest.mock import patch

import pandas as pd

from src.ncaab_odds import _filter_relevant_ncaab_markets, _select_ncaab_polymarket_winner_market, get_all_ncaab_market_odds
from src.odds_collection import _select_polymarket_winner_market


class PolymarketSelectionTests(unittest.TestCase):
    def test_nba_selector_ignores_totals_and_first_half_markets(self) -> None:
        title = "Suns vs. Raptors"
        markets = [
            {
                "question": "Suns vs. Raptors: 1H O/U 112.5",
                "outcomes": ["Over", "Under"],
                "outcomePrices": ["0.5", "0.5"],
            },
            {
                "question": "Suns vs. Raptors: 1H Moneyline",
                "outcomes": ["Suns", "Raptors"],
                "outcomePrices": ["0.68", "0.32"],
            },
            {
                "question": "Suns vs. Raptors",
                "outcomes": ["Suns", "Raptors"],
                "outcomePrices": ["0.385", "0.615"],
            },
        ]

        selected = _select_polymarket_winner_market(title, markets, away_abr="PHX", home_abr="TOR")

        self.assertIsNotNone(selected)
        self.assertEqual(selected["question"], "Suns vs. Raptors")

    def test_ncaab_selector_requires_team_outcomes_for_winner_market(self) -> None:
        title = "Duke vs. Florida"
        markets = [
            {
                "question": "Duke vs. Florida: O/U 154.5",
                "outcomes": ["Over", "Under"],
                "outcomePrices": ["0.5", "0.5"],
            },
            {
                "question": "Duke vs. Florida",
                "outcomes": ["Duke", "Florida"],
                "outcomePrices": ["0.58", "0.42"],
            },
        ]

        selected = _select_ncaab_polymarket_winner_market(
            title,
            markets,
            away_team="Duke",
            home_team="Florida",
            candidates=["Duke", "Florida"],
        )

        self.assertIsNotNone(selected)
        self.assertEqual(selected["question"], "Duke vs. Florida")

    def test_filter_relevant_ncaab_markets_drops_stale_rows(self) -> None:
        now = pd.Timestamp("2026-03-14 12:00:00+00:00")
        df = pd.DataFrame(
            [
                {"home_team": "Michigan", "away_team": "UCLA", "tipoff_utc": "2026-03-28T17:00:00Z"},
                {"home_team": "Alabama", "away_team": "UCF", "tipoff_utc": "2026-01-18T15:03:51Z"},
            ]
        )

        filtered = _filter_relevant_ncaab_markets(df, now=now)

        self.assertEqual(len(filtered), 1)
        self.assertEqual(filtered.iloc[0]["home_team"], "Michigan")
        self.assertEqual(filtered.iloc[0]["away_team"], "UCLA")

    @patch("src.ncaab_odds.get_ncaab_sportsbook_odds")
    @patch("src.ncaab_odds.get_ncaab_polymarket_odds")
    @patch("src.ncaab_odds.get_ncaab_kalshi_odds")
    def test_ncaab_market_merge_keeps_distinct_event_dates(
        self,
        mock_kalshi,
        mock_polymarket,
        mock_sportsbook,
    ) -> None:
        mock_kalshi.return_value = pd.DataFrame(
            [
                {
                    "home_team": "Florida",
                    "away_team": "Vanderbilt",
                    "tipoff_utc": "2026-03-28T17:00:00Z",
                    "home_prob": 0.76,
                    "away_prob": 0.24,
                    "home_odds_decimal": 1.32,
                    "away_odds_decimal": 4.00,
                }
            ]
        )
        mock_polymarket.return_value = pd.DataFrame(
            [
                {
                    "home_team": "Florida",
                    "away_team": "Vanderbilt",
                    "tipoff_utc": "2026-03-13T23:05:47Z",
                    "home_prob": 0.77,
                    "away_prob": 0.23,
                    "home_odds_decimal": 1.28,
                    "away_odds_decimal": 4.17,
                }
            ]
        )
        mock_sportsbook.return_value = pd.DataFrame()

        with patch("src.ncaab_odds._market_window_bounds") as mock_window:
            mock_window.return_value = (
                pd.Timestamp("2026-03-10 00:00:00+00:00"),
                pd.Timestamp("2026-04-05 00:00:00+00:00"),
            )
            combined = get_all_ncaab_market_odds(record_snapshot=False)

        self.assertEqual(len(combined), 2)
        self.assertEqual(sorted(combined["market_home_prob"].round(3).tolist()), [0.76, 0.77])


if __name__ == "__main__":
    unittest.main()
