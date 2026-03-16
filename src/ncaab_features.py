"""
ncaab_features.py - Feature engineering for NCAA tournament prediction.
"""

from __future__ import annotations

import logging
import re

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

TEAM_PROFILE_FEATURES = [
    "seed_num",
    "elo",
    "win_pct",
    "avg_margin",
    "avg_score_for",
    "avg_score_against",
    "efg",
    "ts",
    "tov_rate",
    "ft_rate",
    "oreb_pct",
    "opp_efg",
    "off_rtg",
    "def_rtg",
    "net_rtg",
    "last10_win_pct",
    "last10_margin",
    "median_rank",
    "best_rank",
]


def parse_seed_number(seed: str) -> int:
    """Extract the numeric tournament seed from values like W01 or X16b."""
    match = re.search(r"(\d+)", str(seed))
    if not match:
        raise ValueError(f"Could not parse numeric seed from {seed!r}")
    return int(match.group(1))


def _safe_divide(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    denominator = denominator.replace(0, np.nan)
    return numerator / denominator


def build_team_game_rows(regular_season_results: pd.DataFrame) -> pd.DataFrame:
    """Convert detailed results into one row per team-game."""
    winners = pd.DataFrame(
        {
            "Season": regular_season_results["Season"],
            "DayNum": regular_season_results["DayNum"],
            "TeamID": regular_season_results["WTeamID"],
            "OppTeamID": regular_season_results["LTeamID"],
            "win": 1,
            "score_for": regular_season_results["WScore"],
            "score_against": regular_season_results["LScore"],
            "loc": regular_season_results["WLoc"],
            "FGM": regular_season_results["WFGM"],
            "FGA": regular_season_results["WFGA"],
            "FGM3": regular_season_results["WFGM3"],
            "FGA3": regular_season_results["WFGA3"],
            "FTM": regular_season_results["WFTM"],
            "FTA": regular_season_results["WFTA"],
            "OR": regular_season_results["WOR"],
            "DR": regular_season_results["WDR"],
            "Ast": regular_season_results["WAst"],
            "TO": regular_season_results["WTO"],
            "Stl": regular_season_results["WStl"],
            "Blk": regular_season_results["WBlk"],
            "PF": regular_season_results["WPF"],
            "opp_FGM": regular_season_results["LFGM"],
            "opp_FGA": regular_season_results["LFGA"],
            "opp_FGM3": regular_season_results["LFGM3"],
            "opp_FGA3": regular_season_results["LFGA3"],
            "opp_FTM": regular_season_results["LFTM"],
            "opp_FTA": regular_season_results["LFTA"],
            "opp_OR": regular_season_results["LOR"],
            "opp_DR": regular_season_results["LDR"],
            "opp_Ast": regular_season_results["LAst"],
            "opp_TO": regular_season_results["LTO"],
            "opp_Stl": regular_season_results["LStl"],
            "opp_Blk": regular_season_results["LBlk"],
            "opp_PF": regular_season_results["LPF"],
        }
    )
    losers = pd.DataFrame(
        {
            "Season": regular_season_results["Season"],
            "DayNum": regular_season_results["DayNum"],
            "TeamID": regular_season_results["LTeamID"],
            "OppTeamID": regular_season_results["WTeamID"],
            "win": 0,
            "score_for": regular_season_results["LScore"],
            "score_against": regular_season_results["WScore"],
            "loc": regular_season_results["WLoc"].map({"H": "A", "A": "H", "N": "N"}).fillna("N"),
            "FGM": regular_season_results["LFGM"],
            "FGA": regular_season_results["LFGA"],
            "FGM3": regular_season_results["LFGM3"],
            "FGA3": regular_season_results["LFGA3"],
            "FTM": regular_season_results["LFTM"],
            "FTA": regular_season_results["LFTA"],
            "OR": regular_season_results["LOR"],
            "DR": regular_season_results["LDR"],
            "Ast": regular_season_results["LAst"],
            "TO": regular_season_results["LTO"],
            "Stl": regular_season_results["LStl"],
            "Blk": regular_season_results["LBlk"],
            "PF": regular_season_results["LPF"],
            "opp_FGM": regular_season_results["WFGM"],
            "opp_FGA": regular_season_results["WFGA"],
            "opp_FGM3": regular_season_results["WFGM3"],
            "opp_FGA3": regular_season_results["WFGA3"],
            "opp_FTM": regular_season_results["WFTM"],
            "opp_FTA": regular_season_results["WFTA"],
            "opp_OR": regular_season_results["WOR"],
            "opp_DR": regular_season_results["WDR"],
            "opp_Ast": regular_season_results["WAst"],
            "opp_TO": regular_season_results["WTO"],
            "opp_Stl": regular_season_results["WStl"],
            "opp_Blk": regular_season_results["WBlk"],
            "opp_PF": regular_season_results["WPF"],
        }
    )

    team_games = pd.concat([winners, losers], ignore_index=True)
    team_games = team_games.sort_values(["Season", "TeamID", "DayNum"]).reset_index(drop=True)

    possessions = (
        team_games["FGA"]
        - team_games["OR"]
        + team_games["TO"]
        + 0.44 * team_games["FTA"]
        + team_games["opp_FGA"]
        - team_games["opp_OR"]
        + team_games["opp_TO"]
        + 0.44 * team_games["opp_FTA"]
    ) / 2.0
    possessions = possessions.replace(0, np.nan)

    team_games["possessions"] = possessions
    team_games["margin"] = team_games["score_for"] - team_games["score_against"]
    team_games["efg"] = _safe_divide(team_games["FGM"] + 0.5 * team_games["FGM3"], team_games["FGA"])
    team_games["ts"] = _safe_divide(team_games["score_for"], 2.0 * (team_games["FGA"] + 0.44 * team_games["FTA"]))
    team_games["tov_rate"] = _safe_divide(team_games["TO"], team_games["FGA"] + 0.44 * team_games["FTA"] + team_games["TO"])
    team_games["ft_rate"] = _safe_divide(team_games["FTA"], team_games["FGA"])
    team_games["oreb_pct"] = _safe_divide(team_games["OR"], team_games["OR"] + team_games["opp_DR"])
    team_games["opp_efg"] = _safe_divide(
        team_games["opp_FGM"] + 0.5 * team_games["opp_FGM3"],
        team_games["opp_FGA"],
    )
    team_games["off_rtg"] = 100.0 * _safe_divide(team_games["score_for"], possessions)
    team_games["def_rtg"] = 100.0 * _safe_divide(team_games["score_against"], possessions)
    team_games["net_rtg"] = team_games["off_rtg"] - team_games["def_rtg"]
    return team_games


def compute_pre_tournament_elo(regular_season_results: pd.DataFrame) -> pd.DataFrame:
    """Compute end-of-regular-season Elo ratings for each team and season."""
    elo_rows: list[dict[str, float | int]] = []
    for season, games in regular_season_results.sort_values(["Season", "DayNum"]).groupby("Season"):
        ratings: dict[int, float] = {}

        def rating(team_id: int) -> float:
            return ratings.get(team_id, 1500.0)

        for row in games.itertuples(index=False):
            winner = int(row.WTeamID)
            loser = int(row.LTeamID)
            winner_rating = rating(winner)
            loser_rating = rating(loser)

            winner_effective = winner_rating + (70.0 if row.WLoc == "H" else 0.0)
            loser_effective = loser_rating + (70.0 if row.WLoc == "A" else 0.0)
            expected = 1.0 / (1.0 + 10.0 ** ((loser_effective - winner_effective) / 400.0))

            margin = max(int(row.WScore) - int(row.LScore), 1)
            multiplier = np.log(margin + 1.0) * (2.2 / ((abs(winner_rating - loser_rating) * 0.001) + 2.2))
            delta = 20.0 * multiplier * (1.0 - expected)

            ratings[winner] = winner_rating + delta
            ratings[loser] = loser_rating - delta

        for team_id, elo in ratings.items():
            elo_rows.append({"Season": int(season), "TeamID": int(team_id), "elo": float(elo)})

    return pd.DataFrame(elo_rows)


def build_team_season_features(
    regular_season_results: pd.DataFrame,
    tourney_seeds: pd.DataFrame,
    massey_ordinals: pd.DataFrame,
    teams: pd.DataFrame,
) -> pd.DataFrame:
    """Aggregate team-season features used for tournament prediction."""
    team_games = build_team_game_rows(regular_season_results)
    team_features = team_games.groupby(["Season", "TeamID"]).agg(
        games=("win", "size"),
        wins=("win", "sum"),
        win_pct=("win", "mean"),
        avg_margin=("margin", "mean"),
        avg_score_for=("score_for", "mean"),
        avg_score_against=("score_against", "mean"),
        efg=("efg", "mean"),
        ts=("ts", "mean"),
        tov_rate=("tov_rate", "mean"),
        ft_rate=("ft_rate", "mean"),
        oreb_pct=("oreb_pct", "mean"),
        opp_efg=("opp_efg", "mean"),
        off_rtg=("off_rtg", "mean"),
        def_rtg=("def_rtg", "mean"),
        net_rtg=("net_rtg", "mean"),
    ).reset_index()

    last10 = (
        team_games.sort_values(["Season", "TeamID", "DayNum"])
        .groupby(["Season", "TeamID"])
        .tail(10)
        .groupby(["Season", "TeamID"])
        .agg(last10_win_pct=("win", "mean"), last10_margin=("margin", "mean"))
        .reset_index()
    )
    team_features = team_features.merge(last10, on=["Season", "TeamID"], how="left")

    elo_df = compute_pre_tournament_elo(regular_season_results)
    team_features = team_features.merge(elo_df, on=["Season", "TeamID"], how="left")

    # ── Strength of Schedule: avg opponent win_pct and avg opponent ELO ──────
    # Merge team win_pct onto each game row as the opponent quality signal
    opp_win_pct = team_features[["Season", "TeamID", "win_pct"]].rename(
        columns={"TeamID": "OppTeamID", "win_pct": "opp_season_win_pct"}
    )
    opp_elo = elo_df.rename(columns={"TeamID": "OppTeamID", "elo": "opp_season_elo"})
    games_with_opp = (
        team_games
        .merge(opp_win_pct, on=["Season", "OppTeamID"], how="left")
        .merge(opp_elo,     on=["Season", "OppTeamID"], how="left")
    )
    sos_df = (
        games_with_opp
        .groupby(["Season", "TeamID"])
        .agg(
            avg_opp_win_pct=("opp_season_win_pct", "mean"),
            avg_opp_elo=("opp_season_elo", "mean"),
        )
        .reset_index()
    )
    team_features = team_features.merge(sos_df, on=["Season", "TeamID"], how="left")

    seeds = tourney_seeds.copy()
    seeds["seed_num"] = seeds["Seed"].map(parse_seed_number)
    team_features = team_features.merge(
        seeds[["Season", "TeamID", "Seed", "seed_num"]],
        on=["Season", "TeamID"],
        how="inner",
    )

    ordinals = massey_ordinals.sort_values(["Season", "TeamID", "RankingDayNum", "SystemName"]).copy()
    ordinals = ordinals.groupby(["Season", "TeamID", "SystemName"]).tail(1)
    ordinal_summary = ordinals.groupby(["Season", "TeamID"]).agg(
        median_rank=("OrdinalRank", "median"),
        best_rank=("OrdinalRank", "min"),
    ).reset_index()
    team_features = team_features.merge(ordinal_summary, on=["Season", "TeamID"], how="left")

    team_features = team_features.merge(
        teams[["TeamID", "TeamName"]],
        on="TeamID",
        how="left",
    )
    return team_features.sort_values(["Season", "seed_num", "TeamName"]).reset_index(drop=True)


def build_matchup_feature_row(
    season: int,
    team_a_id: int,
    team_b_id: int,
    team_features: pd.DataFrame,
) -> pd.DataFrame:
    """Build one tournament matchup row from two team-season profiles."""
    season_features = team_features[team_features["Season"] == season]
    team_a = season_features[season_features["TeamID"] == team_a_id]
    team_b = season_features[season_features["TeamID"] == team_b_id]
    if team_a.empty or team_b.empty:
        raise KeyError(f"Missing team features for season={season}, team_a={team_a_id}, team_b={team_b_id}")

    team_a_row = team_a.iloc[0]
    team_b_row = team_b.iloc[0]
    row: dict[str, float | int | str] = {
        "Season": int(season),
        "team_a": int(team_a_id),
        "team_b": int(team_b_id),
        "team_a_name": str(team_a_row["TeamName"]),
        "team_b_name": str(team_b_row["TeamName"]),
        "team_a_win": np.nan,
    }

    available_features = [
        feature
        for feature in TEAM_PROFILE_FEATURES
        if feature in team_a_row.index and feature in team_b_row.index
    ]

    for feature in available_features:
        row[f"team_a_{feature}"] = team_a_row[feature]
        row[f"team_b_{feature}"] = team_b_row[feature]
        row[f"{feature}_diff"] = team_a_row[feature] - team_b_row[feature]

    return pd.DataFrame([row])


def build_tournament_model_dataset(
    tourney_results: pd.DataFrame,
    team_features: pd.DataFrame,
) -> pd.DataFrame:
    """Build a symmetric tournament matchup dataset for model training."""
    rows: list[pd.DataFrame] = []
    for row in tourney_results[["Season", "DayNum", "WTeamID", "LTeamID"]].itertuples(index=False):
        winner_row = build_matchup_feature_row(int(row.Season), int(row.WTeamID), int(row.LTeamID), team_features)
        winner_row["team_a_win"] = 1
        winner_row["DayNum"] = int(row.DayNum)

        loser_row = build_matchup_feature_row(int(row.Season), int(row.LTeamID), int(row.WTeamID), team_features)
        loser_row["team_a_win"] = 0
        loser_row["DayNum"] = int(row.DayNum)

        rows.extend([winner_row, loser_row])

    dataset = pd.concat(rows, ignore_index=True)
    return dataset.sort_values(["Season", "DayNum", "team_a"]).reset_index(drop=True)


def slot_round_label(slot_name: str) -> str:
    """Map NCAA slot codes to human-readable round labels."""
    if slot_name.startswith("R1"):
        return "Round of 64"
    if slot_name.startswith("R2"):
        return "Round of 32"
    if slot_name.startswith("R3"):
        return "Sweet 16"
    if slot_name.startswith("R4"):
        return "Elite 8"
    if slot_name.startswith("R5"):
        return "Final Four"
    if slot_name.startswith("R6"):
        return "National Championship"
    return "First Four"
