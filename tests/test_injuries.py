import unittest
from unittest.mock import patch

import pandas as pd

from src.injuries import (
    _extract_report_links,
    _parse_injury_report_text,
    apply_live_availability_adjustments,
    build_team_availability_adjustments,
)


SAMPLE_REPORT_TEXT = """
Injury
Report:
03/11/26
09:00
PM
Page
1
of
1
Game
Date
Game
Time
Matchup
Team
Player
Name
Current
Status
Reason
03/11/2026
07:30
(ET)
CLE@ORL
Cleveland
Cavaliers
Allen,
Jarrett
Out
Injury/Illness
-
Right
Knee;
Tendonitis
Ellis,
Keon
Available
Injury/Illness
-
Left
Index
Finger;
Fracture
Strus,
Max
Out
Injury/Illness
-
Left
Foot;
Surgery
Orlando
Magic
Black,
Anthony
Out
Injury/Illness
-
Left
Lateral
Abdominal;
Strain
Wagner,
Franz
Out
Injury/Illness
-
Left
High
Ankle;
Sprain
"""


class InjuryTests(unittest.TestCase):
    def test_extract_report_links_matches_standard_pdf_urls(self) -> None:
        html = """
        <a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-03-11_06_45PM.pdf">6:45</a>
        <a href="https://ak-static.cms.nba.com/referee/injury/Injury-Report_2026-03-11_09_00PM.pdf">9:00</a>
        """

        links = _extract_report_links(html)

        self.assertEqual(len(links), 2)
        self.assertEqual(links[-1][0], pd.Timestamp("2026-03-11 21:00:00", tz="America/New_York"))

    def test_parse_injury_report_text_reads_clean_player_names(self) -> None:
        parsed = _parse_injury_report_text(SAMPLE_REPORT_TEXT)

        self.assertEqual(parsed["player_name"].tolist(), [
            "Jarrett Allen",
            "Keon Ellis",
            "Max Strus",
            "Anthony Black",
            "Franz Wagner",
        ])
        self.assertEqual(parsed["status"].tolist(), ["out", "available", "out", "out", "out"])

    def test_build_team_availability_adjustments_reconciles_dirty_names(self) -> None:
        injuries = pd.DataFrame([
            {"team": "CLE", "player_name": "Keon Knee Tendonitis Ellis", "status": "available", "report_timestamp": pd.Timestamp("2026-03-12 01:00:00+00:00")},
            {"team": "CLE", "player_name": "Tyrese Thumb Fracture Proctor", "status": "out", "report_timestamp": pd.Timestamp("2026-03-12 01:00:00+00:00")},
            {"team": "ORL", "player_name": "Franz Back Strain Wagner", "status": "out", "report_timestamp": pd.Timestamp("2026-03-12 01:00:00+00:00")},
        ])
        player_stats = pd.DataFrame([
            {"TEAM_ABBREVIATION": "CLE", "PLAYER_NAME": "Keon Ellis", "MIN": 22.0, "PTS": 8.0, "AST": 2.0, "REB": 3.0},
            {"TEAM_ABBREVIATION": "CLE", "PLAYER_NAME": "Tyrese Proctor", "MIN": 26.0, "PTS": 12.0, "AST": 4.0, "REB": 3.0},
            {"TEAM_ABBREVIATION": "ORL", "PLAYER_NAME": "Franz Wagner", "MIN": 34.0, "PTS": 24.0, "AST": 5.0, "REB": 5.0},
        ])

        adjustments = build_team_availability_adjustments(injuries, player_stats)

        cle_summary = adjustments.loc[adjustments["team"] == "CLE", "availability_summary"].iloc[0]
        orl_summary = adjustments.loc[adjustments["team"] == "ORL", "availability_summary"].iloc[0]
        self.assertIn("Tyrese Proctor (out)", cle_summary)
        self.assertIn("Franz Wagner (out)", orl_summary)

    @patch("src.injuries.fetch_all_espn_injuries")
    @patch("src.injuries.pull_current_player_stats")
    @patch("src.injuries.pull_live_injury_report")
    def test_apply_live_availability_adjustments_falls_back_for_missing_official_teams(
        self,
        mock_pull_live_injury_report,
        mock_pull_current_player_stats,
        mock_fetch_all_espn_injuries,
    ) -> None:
        predictions = pd.DataFrame([
            {"home_team": "LAL", "away_team": "DEN", "home_win_prob": 0.5, "away_win_prob": 0.5},
            {"home_team": "PHI", "away_team": "BKN", "home_win_prob": 0.5, "away_win_prob": 0.5},
        ])
        mock_pull_live_injury_report.return_value = pd.DataFrame([
            {"team": "PHI", "player_name": "Joel Embiid", "status": "out", "report_timestamp": pd.Timestamp("2026-03-14 00:00:00+00:00")},
            {"team": "BKN", "player_name": "Nic Claxton", "status": "out", "report_timestamp": pd.Timestamp("2026-03-14 00:00:00+00:00")},
        ])
        mock_pull_current_player_stats.return_value = pd.DataFrame([
            {"TEAM_ABBREVIATION": "PHI", "PLAYER_NAME": "Joel Embiid", "MIN": 34.0, "PTS": 30.0, "AST": 5.0, "REB": 10.0},
            {"TEAM_ABBREVIATION": "BKN", "PLAYER_NAME": "Nic Claxton", "MIN": 29.0, "PTS": 12.0, "AST": 2.0, "REB": 9.0},
            {"TEAM_ABBREVIATION": "LAL", "PLAYER_NAME": "LeBron James", "MIN": 35.0, "PTS": 26.0, "AST": 8.0, "REB": 7.0},
            {"TEAM_ABBREVIATION": "DEN", "PLAYER_NAME": "Nikola Jokic", "MIN": 36.0, "PTS": 28.0, "AST": 9.0, "REB": 12.0},
        ])
        mock_fetch_all_espn_injuries.return_value = {
            "LAL": [{"player_name": "LeBron James", "status": "Out", "team": "LAL", "reason": "ankle"}],
            "DEN": [{"player_name": "Nikola Jokic", "status": "Questionable", "team": "DEN", "reason": "elbow"}],
        }

        adjusted = apply_live_availability_adjustments(predictions, report_date=pd.Timestamp("2026-03-14"))

        self.assertEqual(sorted(mock_fetch_all_espn_injuries.call_args.kwargs["teams"]), ["DEN", "LAL"])

        lal_row = adjusted.loc[(adjusted["home_team"] == "LAL") & (adjusted["away_team"] == "DEN")].iloc[0]
        self.assertGreater(lal_row["home_availability_penalty_elo"], 0.0)
        self.assertGreater(lal_row["away_availability_penalty_elo"], 0.0)
        self.assertIn("LeBron James (out)", lal_row["home_availability_summary"])
        self.assertIn("Nikola Jokic (questionable)", lal_row["away_availability_summary"])
        self.assertNotEqual(lal_row["availability_adjustment_prob"], 0.0)

        phi_row = adjusted.loc[(adjusted["home_team"] == "PHI") & (adjusted["away_team"] == "BKN")].iloc[0]
        self.assertIn("Joel Embiid (out)", phi_row["home_availability_summary"])
        self.assertIn("Nic Claxton (out)", phi_row["away_availability_summary"])

    @patch("src.injuries.fetch_all_espn_injuries")
    @patch("src.injuries.pull_current_player_stats")
    @patch("src.injuries.pull_live_injury_report")
    def test_apply_live_availability_adjustments_reuses_prediction_feature_fallback(
        self,
        mock_pull_live_injury_report,
        mock_pull_current_player_stats,
        mock_fetch_all_espn_injuries,
    ) -> None:
        predictions = pd.DataFrame([
            {
                "home_team": "LAL",
                "away_team": "DEN",
                "home_win_prob": 0.5,
                "away_win_prob": 0.5,
                "home_availability_penalty_elo": 10.0,
                "away_availability_penalty_elo": 50.0,
                "home_availability_summary": "LeBron James (out)",
                "away_availability_summary": "Nikola Jokic (out)",
                "home_out_count": 1,
                "away_out_count": 1,
            }
        ])
        mock_pull_live_injury_report.return_value = pd.DataFrame()
        mock_pull_current_player_stats.return_value = pd.DataFrame()

        adjusted = apply_live_availability_adjustments(predictions, report_date=pd.Timestamp("2026-03-14"))

        mock_fetch_all_espn_injuries.assert_not_called()
        row = adjusted.iloc[0]
        self.assertEqual(row["home_availability_penalty_elo"], 10.0)
        self.assertEqual(row["away_availability_penalty_elo"], 50.0)
        self.assertEqual(row["home_availability_summary"], "LeBron James (out)")
        self.assertEqual(row["away_availability_summary"], "Nikola Jokic (out)")
        self.assertNotEqual(row["availability_adjustment_prob"], 0.0)


if __name__ == "__main__":
    unittest.main()
