"""
elo.py — Elo rating system for NBA teams.

K-factor: 20
Home court advantage: +100 Elo points added to home team before computing expected score
Season mean reversion: revert 1/3 of the gap to 1500 at the start of each new season
"""

from __future__ import annotations

import logging
from typing import Dict, Optional

import numpy as np
import pandas as pd

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import config

logger = logging.getLogger(__name__)


def _expected_score(rating_a: float, rating_b: float) -> float:
    """Logistic expected score for team A vs team B."""
    return 1.0 / (1.0 + 10 ** ((rating_b - rating_a) / 400.0))


def _mov_multiplier(margin: float, winner_elo_diff: float) -> float:
    """
    Margin-of-victory multiplier (FiveThirtyEight formula).

    Scales the K-factor so blowouts update ratings more than 1-point wins,
    while correcting for autocorrelation (better teams win by more).

    margin         : abs(home_pts - away_pts)
    winner_elo_diff: pre-game Elo of winner minus Elo of loser
    """
    if margin <= 0:
        return 1.0
    autocorr_correction = 2.2 / (winner_elo_diff * 0.001 + 2.2)
    return float(np.log(margin + 1) * autocorr_correction)


def _update_ratings(
    home_elo: float,
    away_elo: float,
    home_win: int,
    k: float = config.ELO_K_FACTOR,
    home_adv: float = config.ELO_HOME_ADVANTAGE,
    home_pts: float = 0.0,
    away_pts: float = 0.0,
) -> tuple[float, float]:
    """
    Update Elo ratings after a single game with optional MOV adjustment.

    Parameters
    ----------
    home_elo : float
    away_elo : float
    home_win : int  — 1 if home won, 0 if away won
    k : float       — base K-factor
    home_adv : float— Elo points added to home before computing expected score
    home_pts, away_pts : float — final scores; if both >0, applies MOV multiplier
    """
    adjusted_home = home_elo + home_adv
    expected_home = _expected_score(adjusted_home, away_elo)
    expected_away = 1.0 - expected_home

    if home_pts > 0 and away_pts > 0:
        margin = abs(home_pts - away_pts)
        winner_elo = home_elo if home_win else away_elo
        loser_elo  = away_elo if home_win else home_elo
        k = k * _mov_multiplier(margin, winner_elo - loser_elo)

    new_home_elo = home_elo + k * (home_win - expected_home)
    new_away_elo = away_elo + k * ((1 - home_win) - expected_away)

    return new_home_elo, new_away_elo


def _mean_revert(rating: float, base: float = config.ELO_BASE, frac: float = config.ELO_MEAN_REVERT_FRAC) -> float:
    """Revert rating (1-frac) of the way toward base."""
    return rating - frac * (rating - base)


class EloSystem:
    """
    Tracks Elo ratings across multiple seasons for all NBA teams.

    Usage
    -----
    elo = EloSystem()
    history = elo.compute(games_df)
    """

    def __init__(self) -> None:
        self.ratings: Dict[str, float] = {}

    def _get_rating(self, team: str) -> float:
        return self.ratings.get(team, config.ELO_BASE)

    def compute(self, games: pd.DataFrame) -> pd.DataFrame:
        """
        Compute pre-game Elo ratings for every game in the DataFrame.

        Parameters
        ----------
        games : pd.DataFrame
            Must contain columns: game_id, game_date, season, home_team, away_team, home_win
            Sorted ascending by game_date.

        Returns
        -------
        pd.DataFrame
            Original DataFrame with added columns:
            home_elo_pre, away_elo_pre, elo_diff (home - away, with home advantage)
        """
        games = games.sort_values("game_date").reset_index(drop=True)

        home_elos_pre: list[float] = []
        away_elos_pre: list[float] = []
        current_season: Optional[str] = None

        for _, row in games.iterrows():
            season = row["season"]
            home = row["home_team"]
            away = row["away_team"]

            # Mean-revert at start of each new season
            if season != current_season:
                logger.info("New season %s — mean-reverting Elo ratings", season)
                self.ratings = {
                    team: _mean_revert(r)
                    for team, r in self.ratings.items()
                }
                current_season = season

            h_pre = self._get_rating(home)
            a_pre = self._get_rating(away)
            home_elos_pre.append(h_pre)
            away_elos_pre.append(a_pre)

            # Update ratings after game (MOV-adjusted when scores are available)
            h_pts = float(row["home_pts"]) if "home_pts" in row and pd.notna(row["home_pts"]) else 0.0
            a_pts = float(row["away_pts"]) if "away_pts" in row and pd.notna(row["away_pts"]) else 0.0
            h_new, a_new = _update_ratings(h_pre, a_pre, int(row["home_win"]), home_pts=h_pts, away_pts=a_pts)
            self.ratings[home] = h_new
            self.ratings[away] = a_new

        games = games.copy()
        games["home_elo"] = home_elos_pre
        games["away_elo"] = away_elos_pre
        games["elo_diff"] = games["home_elo"] - games["away_elo"]

        return games

    def get_current_ratings(self) -> pd.DataFrame:
        """Return current Elo ratings for all teams as a sorted DataFrame."""
        df = pd.DataFrame(
            list(self.ratings.items()), columns=["team", "elo"]
        ).sort_values("elo", ascending=False).reset_index(drop=True)
        df["rank"] = df.index + 1
        return df
