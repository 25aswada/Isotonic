import unittest

import pandas as pd

from src.model import get_feature_columns, prepare_xy, select_blend_weight


class ModelPipelineTests(unittest.TestCase):
    def test_feature_selector_excludes_targets_and_market_columns(self) -> None:
        df = pd.DataFrame(
            {
                "game_id": [1],
                "season": ["2024-25"],
                "home_team": ["CLE"],
                "away_team": ["ORL"],
                "home_win": [1],
                "home_pts": [110],
                "away_pts": [104],
                "home_elo": [1600.0],
                "away_elo": [1540.0],
                "elo_diff": [60.0],
                "net_rtg_diff": [4.2],
                "market_home_implied": [0.61],
                "home_win_prob": [0.58],
            }
        )

        feature_cols = get_feature_columns(df)

        self.assertIn("home_elo", feature_cols)
        self.assertIn("away_elo", feature_cols)
        self.assertIn("elo_diff", feature_cols)
        self.assertIn("net_rtg_diff", feature_cols)
        self.assertNotIn("home_win", feature_cols)
        self.assertNotIn("home_pts", feature_cols)
        self.assertNotIn("market_home_implied", feature_cols)
        self.assertNotIn("home_win_prob", feature_cols)

    def test_prepare_xy_uses_training_fill_values(self) -> None:
        df = pd.DataFrame(
            {
                "home_elo": [None, 1700.0],
                "away_elo": [1500.0, None],
                "home_win": [1, 0],
            }
        )
        fill_values = pd.Series({"home_elo": 1600.0, "away_elo": 1510.0})

        X, y = prepare_xy(df, ["home_elo", "away_elo"], fill_values=fill_values)

        self.assertEqual(X.loc[0, "home_elo"], 1600.0)
        self.assertEqual(X.loc[1, "away_elo"], 1510.0)
        self.assertEqual(y.tolist(), [1, 0])

    def test_select_blend_weight_prefers_better_candidate(self) -> None:
        y_true = pd.Series([1, 0, 1, 0])
        xgb_probs = pd.Series([0.55, 0.45, 0.52, 0.48]).to_numpy()
        linear_probs = pd.Series([0.85, 0.10, 0.80, 0.15]).to_numpy()

        weight, _ = select_blend_weight(y_true, xgb_probs, linear_probs)

        self.assertLess(weight, 0.5)


if __name__ == "__main__":
    unittest.main()
