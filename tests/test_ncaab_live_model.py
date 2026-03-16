import unittest

import pandas as pd

import config
from src.ncaab_live_model import NCAAB_REGULATION_SECONDS, enrich_with_market_odds, live_win_prob


class NcaabLiveModelTests(unittest.TestCase):
    def test_live_win_prob_moves_toward_leading_team_as_time_runs_down(self) -> None:
        pre_ahead, _ = live_win_prob(
            home_score=0,
            away_score=0,
            seconds_remaining=NCAAB_REGULATION_SECONDS,
            home_elo=1600.0,
            away_elo=1600.0,
            pregame_home_prob=0.50,
            neutral_site=True,
        )
        mid_ahead, _ = live_win_prob(
            home_score=6,
            away_score=0,
            seconds_remaining=20 * 60,
            home_elo=1600.0,
            away_elo=1600.0,
            pregame_home_prob=0.50,
            neutral_site=True,
        )
        late_ahead, _ = live_win_prob(
            home_score=6,
            away_score=0,
            seconds_remaining=2 * 60,
            home_elo=1600.0,
            away_elo=1600.0,
            pregame_home_prob=0.50,
            neutral_site=True,
        )

        self.assertAlmostEqual(pre_ahead, 0.50, places=4)
        self.assertGreater(mid_ahead, pre_ahead)
        self.assertGreater(late_ahead, mid_ahead)

    def test_live_win_prob_uses_home_advantage_only_off_neutral_court(self) -> None:
        neutral_home, _ = live_win_prob(
            home_score=0,
            away_score=0,
            seconds_remaining=NCAAB_REGULATION_SECONDS,
            home_elo=config.ELO_BASE,
            away_elo=config.ELO_BASE,
            pregame_home_prob=None,
            neutral_site=True,
        )
        true_home, _ = live_win_prob(
            home_score=0,
            away_score=0,
            seconds_remaining=NCAAB_REGULATION_SECONDS,
            home_elo=config.ELO_BASE,
            away_elo=config.ELO_BASE,
            pregame_home_prob=None,
            neutral_site=False,
        )

        self.assertAlmostEqual(neutral_home, 0.50, places=4)
        self.assertGreater(true_home, neutral_home)

    def test_enrich_with_market_odds_builds_live_market_and_edge_fields(self) -> None:
        live_df = pd.DataFrame(
            [
                {
                    "home_market_team": "Illinois",
                    "away_market_team": "Wisconsin",
                    "live_home_prob": 0.75,
                    "live_away_prob": 0.25,
                }
            ]
        )
        odds_df = pd.DataFrame(
            [
                {
                    "home_team": "Illinois",
                    "away_team": "Wisconsin",
                    "kalshi_home_prob": 0.70,
                    "kalshi_away_prob": 0.30,
                    "polymarket_home_prob": 0.71,
                    "polymarket_away_prob": 0.29,
                }
            ]
        )

        enriched = enrich_with_market_odds(live_df, odds_df)
        row = enriched.iloc[0]

        self.assertAlmostEqual(row["market_home_live"], 0.70)
        self.assertAlmostEqual(row["market_away_live"], 0.30)
        self.assertAlmostEqual(row["live_home_edge"], 0.05)
        self.assertAlmostEqual(row["live_away_edge"], -0.05)


if __name__ == "__main__":
    unittest.main()
