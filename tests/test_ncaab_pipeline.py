import unittest

import numpy as np
import pandas as pd

from src.ncaab_features import build_matchup_feature_row, infer_seed_from_rank, parse_seed_number, slot_round_label
from src.ncaab_bracket_viz import build_bracket_html
from src.ncaab_live import best_name_match, normalize_team_name
from src.ncaab_live import _infer_seed_from_rank
from src.ncaab_odds import match_projected_team_name
from src.ncaab_predict import (
    apply_elo_anchor_probability,
    compute_seed_matchup_baselines,
    generate_market_recommendation_table,
    lookup_seed_baseline_prob,
    predict_matchup,
)
from src.ncaab_model import compute_season_sample_weights

# Default new-feature values shared by all test fixtures.
_NEW_FEATURE_DEFAULTS = {
    "pace": 68.0,
    "fg3_rate": 0.35,
    "ft_pct": 0.72,
    "ast_rate": 0.55,
    "stl_rate": 0.04,
    "blk_rate": 0.03,
    "dreb_pct": 0.72,
    "opp_tov_rate": 0.17,
    "std_margin": 10.0,
    "avg_opp_win_pct": 0.50,
    "avg_opp_elo": 1500.0,
}


def _with_new_features(row: dict) -> dict:
    """Merge default new-feature values into a test fixture row."""
    merged = dict(_NEW_FEATURE_DEFAULTS)
    merged.update(row)
    return merged


class NcaabPipelineTests(unittest.TestCase):
    class DummyAsymmetricModel:
        def predict_proba(self, X: pd.DataFrame) -> np.ndarray:
            seed_a = pd.to_numeric(X["team_a_seed_num"], errors="coerce").fillna(16).astype(float)
            seed_b = pd.to_numeric(X["team_b_seed_num"], errors="coerce").fillna(16).astype(float)
            elo_diff = pd.to_numeric(X["elo_diff"], errors="coerce").fillna(0.0).astype(float)
            raw = 0.48 + 0.03 * (seed_a == 1).astype(float) - 0.02 * (seed_b == 1).astype(float) + 0.0002 * elo_diff
            raw = np.clip(raw.to_numpy(dtype=float), 0.01, 0.99)
            return np.column_stack([1.0 - raw, raw])

    def test_parse_seed_number_handles_play_in_suffix(self) -> None:
        self.assertEqual(parse_seed_number("W01"), 1)
        self.assertEqual(parse_seed_number("X16b"), 16)

    def test_feature_seed_inference_caps_into_seed_lines(self) -> None:
        self.assertEqual(infer_seed_from_rank(1), 1)
        self.assertEqual(infer_seed_from_rank(8), 2)
        self.assertEqual(infer_seed_from_rank(67), 16)
        self.assertEqual(infer_seed_from_rank(None), 16)

    def test_infer_seed_from_rank_caps_into_seed_lines(self) -> None:
        self.assertEqual(_infer_seed_from_rank(1), 1)
        self.assertEqual(_infer_seed_from_rank(8), 2)
        self.assertEqual(_infer_seed_from_rank(67), 16)
        self.assertEqual(_infer_seed_from_rank(None), 16)

    def test_build_matchup_feature_row_builds_expected_diffs(self) -> None:
        team_features = pd.DataFrame(
            [
                _with_new_features({
                    "Season": 2023,
                    "TeamID": 1,
                    "TeamName": "Alpha",
                    "Seed": "W01",
                    "seed_num": 1,
                    "elo": 1700.0,
                    "win_pct": 0.88,
                    "avg_margin": 14.2,
                    "avg_score_for": 79.0,
                    "avg_score_against": 64.8,
                    "efg": 0.56,
                    "ts": 0.60,
                    "tov_rate": 0.14,
                    "ft_rate": 0.28,
                    "oreb_pct": 0.31,
                    "opp_efg": 0.46,
                    "off_rtg": 115.0,
                    "def_rtg": 95.0,
                    "net_rtg": 20.0,
                    "last10_win_pct": 0.9,
                    "last10_margin": 15.0,
                    "median_rank": 6.0,
                    "best_rank": 2.0,
                }),
                _with_new_features({
                    "Season": 2023,
                    "TeamID": 2,
                    "TeamName": "Beta",
                    "Seed": "W08",
                    "seed_num": 8,
                    "elo": 1600.0,
                    "win_pct": 0.72,
                    "avg_margin": 6.2,
                    "avg_score_for": 74.0,
                    "avg_score_against": 67.8,
                    "efg": 0.52,
                    "ts": 0.56,
                    "tov_rate": 0.17,
                    "ft_rate": 0.24,
                    "oreb_pct": 0.28,
                    "opp_efg": 0.49,
                    "off_rtg": 108.0,
                    "def_rtg": 101.0,
                    "net_rtg": 7.0,
                    "last10_win_pct": 0.6,
                    "last10_margin": 4.0,
                    "median_rank": 24.0,
                    "best_rank": 15.0,
                }),
            ]
        )

        row = build_matchup_feature_row(2023, 1, 2, team_features).iloc[0]

        self.assertEqual(row["team_a_name"], "Alpha")
        self.assertEqual(row["team_b_name"], "Beta")
        self.assertEqual(row["seed_num_diff"], -7)
        self.assertEqual(row["elo_diff"], 100.0)
        # New features should produce diffs of zero (same defaults).
        self.assertAlmostEqual(row["pace_diff"], 0.0)
        self.assertAlmostEqual(row["fg3_rate_diff"], 0.0)

    def test_slot_round_label_maps_known_rounds(self) -> None:
        self.assertEqual(slot_round_label("R1W1"), "Round of 64")
        self.assertEqual(slot_round_label("R5WX"), "Final Four")
        self.assertEqual(slot_round_label("W11"), "First Four")

    def test_team_name_matching_handles_common_aliases(self) -> None:
        self.assertEqual(normalize_team_name("Ole Miss"), "mississippi")
        self.assertEqual(normalize_team_name("UMass"), "massachusetts")
        self.assertEqual(
            best_name_match("SMU", ["Southern Methodist", "Duke", "Houston"]),
            "Southern Methodist",
        )

    def test_seed_baselines_aggregate_ordered_matchups(self) -> None:
        df = pd.DataFrame(
            [
                {"team_a_seed_num": 1, "team_b_seed_num": 16, "team_a_win": 1},
                {"team_a_seed_num": 1, "team_b_seed_num": 16, "team_a_win": 1},
                {"team_a_seed_num": 12, "team_b_seed_num": 5, "team_a_win": 1},
                {"team_a_seed_num": 12, "team_b_seed_num": 5, "team_a_win": 0},
            ]
        )
        baselines = compute_seed_matchup_baselines(df)

        self.assertAlmostEqual(lookup_seed_baseline_prob(1, 16, baselines), 1.0)
        self.assertAlmostEqual(lookup_seed_baseline_prob(12, 5, baselines), 0.5)
        self.assertAlmostEqual(lookup_seed_baseline_prob(8, 9, baselines), 0.5)

    def test_match_projected_team_name_handles_market_nicknames(self) -> None:
        candidates = ["Duke", "Miami FL", "St. John’s"]

        self.assertEqual(match_projected_team_name("Duke Blue Devils", candidates), "Duke")
        self.assertEqual(match_projected_team_name("Miami (FL) Hurricanes", candidates), "Miami FL")
        self.assertEqual(match_projected_team_name("St. John's Red Storm", candidates), "St. John’s")

    def test_match_projected_team_name_avoids_bad_fuzzy_matches(self) -> None:
        candidates = ["Iowa St.", "Duke", "Florida"]

        self.assertIsNone(match_projected_team_name("St. Bonaventure", candidates))

    def test_generate_market_recommendation_table_builds_real_edge_board(self) -> None:
        predictions = pd.DataFrame(
            [
                {
                    "tipoff_utc": pd.Timestamp("2026-03-28 17:00:00+00:00"),
                    "home_team": "Duke",
                    "away_team": "Florida",
                    "home_win_prob": 0.62,
                    "away_win_prob": 0.38,
                    "home_seed_edge": 0.08,
                    "away_seed_edge": -0.08,
                    "market_home_implied": 0.55,
                    "market_away_implied": 0.45,
                    "home_odds_decimal": 2.0,
                    "away_odds_decimal": 2.2,
                    "best_home_source": "sportsbook",
                    "best_away_source": "kalshi",
                }
            ]
        )

        recs = generate_market_recommendation_table(predictions, edge_threshold=0.03)
        row = recs.iloc[0]

        self.assertEqual(row["bet_team"], "Duke")
        self.assertAlmostEqual(row["best_edge"], 0.07)
        self.assertTrue(row["bet"])
        self.assertGreater(row["kelly"], 0.0)
        self.assertEqual(row["best_source"], "sportsbook")

    def test_generate_market_recommendation_table_keeps_same_teams_on_different_dates(self) -> None:
        predictions = pd.DataFrame(
            [
                {
                    "tipoff_utc": pd.Timestamp("2026-03-28 17:00:00+00:00"),
                    "home_team": "Florida",
                    "away_team": "Vanderbilt",
                    "home_win_prob": 0.62,
                    "away_win_prob": 0.38,
                    "home_seed_edge": 0.03,
                    "away_seed_edge": -0.03,
                },
                {
                    "tipoff_utc": pd.Timestamp("2026-03-30 17:00:00+00:00"),
                    "home_team": "Florida",
                    "away_team": "Vanderbilt",
                    "home_win_prob": 0.55,
                    "away_win_prob": 0.45,
                    "home_seed_edge": 0.01,
                    "away_seed_edge": -0.01,
                },
            ]
        )
        odds = pd.DataFrame(
            [
                {
                    "tipoff_utc": pd.Timestamp("2026-03-28 17:00:00+00:00"),
                    "home_team": "Florida",
                    "away_team": "Vanderbilt",
                    "market_home_implied": 0.76,
                    "market_away_implied": 0.24,
                    "home_odds_decimal": 1.32,
                    "away_odds_decimal": 4.0,
                },
                {
                    "tipoff_utc": pd.Timestamp("2026-03-30 17:00:00+00:00"),
                    "home_team": "Florida",
                    "away_team": "Vanderbilt",
                    "market_home_implied": 0.55,
                    "market_away_implied": 0.45,
                    "home_odds_decimal": 1.82,
                    "away_odds_decimal": 2.22,
                },
            ]
        )

        recs = generate_market_recommendation_table(predictions, odds_df=odds, edge_threshold=0.03)

        self.assertEqual(len(recs), 2)
        ordered = recs.sort_values("tipoff_utc").reset_index(drop=True)
        self.assertAlmostEqual(ordered.loc[0, "market_home_implied"], 0.76)
        self.assertAlmostEqual(ordered.loc[1, "market_home_implied"], 0.55)

    def test_apply_elo_anchor_probability_leaves_small_gaps_alone(self) -> None:
        self.assertAlmostEqual(apply_elo_anchor_probability(0.61, 20.0), 0.61)

    def test_apply_elo_anchor_probability_shrinks_large_gap_extremes(self) -> None:
        adjusted = apply_elo_anchor_probability(0.99, 300.0)
        elo_baseline = 1.0 / (1.0 + 10.0 ** (-300.0 / 400.0))
        self.assertLess(adjusted, 0.99)
        self.assertGreater(adjusted, elo_baseline)

    def test_compute_season_sample_weights_upweights_recent_years(self) -> None:
        df = pd.DataFrame({"Season": [2022, 2023, 2024]})
        weights = compute_season_sample_weights(df)

        self.assertEqual(len(weights), 3)
        self.assertLess(weights[0], weights[1])
        self.assertLess(weights[1], weights[2])

    def test_predict_matchup_rejects_same_team(self) -> None:
        team_features = pd.DataFrame(
            [
                _with_new_features({
                    "Season": 2026,
                    "TeamID": 1,
                    "TeamName": "Duke",
                    "Seed": "E01",
                    "seed_num": 1,
                    "elo": 1940.3,
                    "win_pct": 0.90,
                    "avg_margin": 18.0,
                    "avg_score_for": 82.0,
                    "avg_score_against": 64.0,
                    "efg": 0.57,
                    "ts": 0.61,
                    "tov_rate": 0.13,
                    "ft_rate": 0.29,
                    "oreb_pct": 0.32,
                    "opp_efg": 0.45,
                    "off_rtg": 118.0,
                    "def_rtg": 93.0,
                    "net_rtg": 25.0,
                    "last10_win_pct": 1.0,
                    "last10_margin": 16.0,
                    "median_rank": 2.0,
                    "best_rank": 1.0,
                })
            ]
        )

        with self.assertRaisesRegex(ValueError, "different teams"):
            predict_matchup(2026, 1, 1, team_features=team_features)

    def test_predict_matchup_is_symmetric_when_teams_are_flipped(self) -> None:
        team_features = pd.DataFrame(
            [
                _with_new_features({
                    "Season": 2026,
                    "TeamID": 1,
                    "TeamName": "Duke",
                    "Seed": "E01",
                    "seed_num": 1,
                    "elo": 1940.3,
                    "win_pct": 0.90,
                    "avg_margin": 18.0,
                    "avg_score_for": 82.0,
                    "avg_score_against": 64.0,
                    "efg": 0.57,
                    "ts": 0.61,
                    "tov_rate": 0.13,
                    "ft_rate": 0.29,
                    "oreb_pct": 0.32,
                    "opp_efg": 0.45,
                    "off_rtg": 118.0,
                    "def_rtg": 93.0,
                    "net_rtg": 25.0,
                    "last10_win_pct": 1.0,
                    "last10_margin": 16.0,
                    "median_rank": 2.0,
                    "best_rank": 1.0,
                }),
                _with_new_features({
                    "Season": 2026,
                    "TeamID": 2,
                    "TeamName": "Michigan",
                    "Seed": "M01",
                    "seed_num": 1,
                    "elo": 1904.3,
                    "win_pct": 0.89,
                    "avg_margin": 17.0,
                    "avg_score_for": 80.0,
                    "avg_score_against": 65.0,
                    "efg": 0.56,
                    "ts": 0.60,
                    "tov_rate": 0.14,
                    "ft_rate": 0.28,
                    "oreb_pct": 0.31,
                    "opp_efg": 0.46,
                    "off_rtg": 116.0,
                    "def_rtg": 94.0,
                    "net_rtg": 22.0,
                    "last10_win_pct": 0.9,
                    "last10_margin": 14.0,
                    "median_rank": 3.0,
                    "best_rank": 1.0,
                }),
            ]
        )
        feature_cols = ["team_a_seed_num", "team_b_seed_num", "elo_diff"]
        fill_values = pd.Series({feature: 0.0 for feature in feature_cols})
        model_bundle = (self.DummyAsymmetricModel(), feature_cols, fill_values)

        duke_first = predict_matchup(2026, 1, 2, team_features=team_features, model_bundle=model_bundle)
        michigan_first = predict_matchup(2026, 2, 1, team_features=team_features, model_bundle=model_bundle)

        self.assertAlmostEqual(duke_first["team_a_win_prob"], 1.0 - michigan_first["team_a_win_prob"])
        self.assertAlmostEqual(duke_first["team_a_win_prob_model"], 1.0 - michigan_first["team_a_win_prob_model"])

    def test_build_bracket_html_renders_regions_and_champion(self) -> None:
        team_features = pd.DataFrame(
            [
                {"TeamID": 1, "seed_num": 1},
                {"TeamID": 2, "seed_num": 16},
                {"TeamID": 3, "seed_num": 1},
                {"TeamID": 4, "seed_num": 16},
                {"TeamID": 5, "seed_num": 1},
                {"TeamID": 6, "seed_num": 16},
                {"TeamID": 7, "seed_num": 1},
                {"TeamID": 8, "seed_num": 16},
            ]
        )
        bracket = pd.DataFrame(
            [
                {"round": "Round of 64", "region": "East", "team_a_id": 1, "team_b_id": 2, "team_a_name": "Alpha", "team_b_name": "Beta", "winner_id": 1, "winner_name": "Alpha", "win_prob": 0.8},
                {"round": "Elite 8", "region": "East", "team_a_id": 1, "team_b_id": 2, "team_a_name": "Alpha", "team_b_name": "Beta", "winner_id": 1, "winner_name": "Alpha", "win_prob": 0.8},
                {"round": "Round of 64", "region": "South", "team_a_id": 3, "team_b_id": 4, "team_a_name": "Gamma", "team_b_name": "Delta", "winner_id": 3, "winner_name": "Gamma", "win_prob": 0.7},
                {"round": "Elite 8", "region": "South", "team_a_id": 3, "team_b_id": 4, "team_a_name": "Gamma", "team_b_name": "Delta", "winner_id": 3, "winner_name": "Gamma", "win_prob": 0.7},
                {"round": "Round of 64", "region": "Midwest", "team_a_id": 5, "team_b_id": 6, "team_a_name": "Epsilon", "team_b_name": "Zeta", "winner_id": 5, "winner_name": "Epsilon", "win_prob": 0.75},
                {"round": "Elite 8", "region": "Midwest", "team_a_id": 5, "team_b_id": 6, "team_a_name": "Epsilon", "team_b_name": "Zeta", "winner_id": 5, "winner_name": "Epsilon", "win_prob": 0.75},
                {"round": "Round of 64", "region": "West", "team_a_id": 7, "team_b_id": 8, "team_a_name": "Eta", "team_b_name": "Theta", "winner_id": 7, "winner_name": "Eta", "win_prob": 0.72},
                {"round": "Elite 8", "region": "West", "team_a_id": 7, "team_b_id": 8, "team_a_name": "Eta", "team_b_name": "Theta", "winner_id": 7, "winner_name": "Eta", "win_prob": 0.72},
                {"round": "Final Four", "region": "East vs Midwest", "team_a_id": 1, "team_b_id": 5, "team_a_name": "Alpha", "team_b_name": "Epsilon", "winner_id": 1, "winner_name": "Alpha", "win_prob": 0.62},
                {"round": "Final Four", "region": "South vs West", "team_a_id": 3, "team_b_id": 7, "team_a_name": "Gamma", "team_b_name": "Eta", "winner_id": 3, "winner_name": "Gamma", "win_prob": 0.59},
                {"round": "National Championship", "region": "Title Game", "team_a_id": 1, "team_b_id": 3, "team_a_name": "Alpha", "team_b_name": "Gamma", "winner_id": 1, "winner_name": "Alpha", "win_prob": 0.58},
            ]
        )

        html = build_bracket_html(bracket, team_features)

        self.assertIn("East", html)
        self.assertIn("Midwest", html)
        self.assertIn("Model Champion", html)
        self.assertIn("Alpha", html)


if __name__ == "__main__":
    unittest.main()
