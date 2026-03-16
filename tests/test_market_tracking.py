import unittest

import pandas as pd

from src.market_tracking import enrich_paper_trades_with_clv, enrich_prediction_log_with_clv


class MarketTrackingTests(unittest.TestCase):
    def test_enrich_paper_trades_uses_last_snapshot_before_tipoff(self) -> None:
        trades = pd.DataFrame([
            {
                "market_source": "kalshi",
                "bet_side": "home",
                "home_team": "ORL",
                "away_team": "CLE",
                "entry_price": 0.43,
                "tipoff_utc": pd.Timestamp("2026-03-12 00:30:00+00:00"),
            }
        ])
        snapshots = pd.DataFrame([
            {
                "home_team": "ORL",
                "away_team": "CLE",
                "snapshot_at": pd.Timestamp("2026-03-11 23:00:00+00:00"),
                "kalshi_home_prob": 0.46,
                "kalshi_home_bid_prob": 0.45,
                "kalshi_home_ask_prob": 0.47,
            },
            {
                "home_team": "ORL",
                "away_team": "CLE",
                "snapshot_at": pd.Timestamp("2026-03-12 00:20:00+00:00"),
                "kalshi_home_prob": 0.49,
                "kalshi_home_bid_prob": 0.48,
                "kalshi_home_ask_prob": 0.50,
            },
            {
                "home_team": "ORL",
                "away_team": "CLE",
                "snapshot_at": pd.Timestamp("2026-03-12 01:00:00+00:00"),
                "kalshi_home_prob": 0.61,
                "kalshi_home_bid_prob": 0.60,
                "kalshi_home_ask_prob": 0.62,
            },
        ])

        enriched = enrich_paper_trades_with_clv(trades, snapshots_df=snapshots)

        self.assertAlmostEqual(enriched.loc[0, "closing_price"], 0.49)
        self.assertAlmostEqual(enriched.loc[0, "closing_bid"], 0.48)
        self.assertAlmostEqual(enriched.loc[0, "closing_ask"], 0.50)
        self.assertAlmostEqual(enriched.loc[0, "clv"], 0.06)

    def test_enrich_prediction_log_uses_market_consensus_snapshot(self) -> None:
        prediction_log = pd.DataFrame([
            {
                "home_team": "NOP",
                "away_team": "TOR",
                "game_date": pd.Timestamp("2026-03-11"),
                "market_home_implied": 0.41,
                "tipoff_utc": pd.Timestamp("2026-03-12 01:00:00+00:00"),
            }
        ])
        snapshots = pd.DataFrame([
            {
                "home_team": "NOP",
                "away_team": "TOR",
                "snapshot_at": pd.Timestamp("2026-03-11 23:30:00+00:00"),
                "market_home_prob": 0.44,
            },
            {
                "home_team": "NOP",
                "away_team": "TOR",
                "snapshot_at": pd.Timestamp("2026-03-12 01:30:00+00:00"),
                "market_home_prob": 0.52,
            },
        ])

        enriched = enrich_prediction_log_with_clv(prediction_log, snapshots_df=snapshots)

        self.assertAlmostEqual(enriched.loc[0, "closing_market_home_prob"], 0.44)
        self.assertAlmostEqual(enriched.loc[0, "market_clv"], 0.03)


if __name__ == "__main__":
    unittest.main()
