"""
ncaab_live_scores.py - Live NCAA men's scoreboard with projected-field model context.
"""

from __future__ import annotations

import logging
from typing import Any

import numpy as np
import pandas as pd
import requests

import config

from src.live_play_feed import get_latest_play
from src.ncaab_availability import apply_ncaab_availability_adjustments
from src.ncaab_live_model import (
    NCAAB_REGULATION_SECONDS,
    enrich_with_market_odds,
    live_win_prob,
)
from src.ncaab_model import load_model
from src.ncaab_odds import get_all_ncaab_market_odds, match_projected_team_name
from src.ncaab_predict import (
    load_current_all_team_features,
    load_current_team_features,
    load_seed_matchup_baselines,
    predict_matchup,
)

logger = logging.getLogger(__name__)

ESPN_NCAAB_SCOREBOARD_URL = (
    "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
)


def _coerce_int(value: Any) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _scoreboard_status_code(state: str) -> int:
    return {"pre": 1, "in": 2, "post": 3}.get(str(state or "").lower(), 0)


def _extract_competitor(competitors: list[dict], side: str) -> dict:
    for competitor in competitors:
        if competitor.get("homeAway") == side:
            return competitor
    return {}


def _sort_games(games: list[dict]) -> list[dict]:
    return sorted(games, key=lambda g: (str(g.get("tipoff_utc", "")), str(g.get("game_id", ""))))


def _parse_display_clock_to_seconds(clock: str | None) -> float:
    if not clock:
        return 0.0
    text = str(clock).strip()
    if ":" not in text:
        return 0.0
    minutes, seconds = text.split(":", 1)
    try:
        return float(minutes) * 60.0 + float(seconds)
    except (TypeError, ValueError):
        return 0.0


def _ncaab_seconds_remaining(game_status: int, period: int, display_clock: str | None) -> float:
    if game_status == 1:
        return float(NCAAB_REGULATION_SECONDS)
    if game_status == 3:
        return 0.0

    clock_seconds = _parse_display_clock_to_seconds(display_clock)
    if period <= 0:
        return float(NCAAB_REGULATION_SECONDS)
    if period == 1:
        return 20.0 * 60.0 + clock_seconds
    if period == 2:
        return clock_seconds
    return clock_seconds  # OT periods


def _ncaab_period_label(game_status_text: str, period: int) -> str:
    status_text = str(game_status_text or "").strip().lower()
    if "halftime" in status_text:
        return "Halftime"
    if "final" in status_text:
        return "Final"
    if period <= 0:
        return ""
    if period == 1:
        return "1st"
    if period == 2:
        return "2nd"
    if period == 3:
        return "OT"
    return f"OT{period - 2}"


def fetch_ncaab_live_games() -> dict[str, list[dict]]:
    """
    Return live NCAA men's games for the current date.

    The scoreboard covers all current men's college basketball games. When both
    teams map to the projected March Madness field, we also attach the current
    tournament-model probability and any live Kalshi odds that match the
    projected-field naming.
    """
    response = requests.get(
        ESPN_NCAAB_SCOREBOARD_URL,
        params={"groups": 50, "limit": 200},
        timeout=20,
        headers={"User-Agent": "Mozilla/5.0"},
    )
    response.raise_for_status()
    payload = response.json()
    events = payload.get("events", [])
    if not events:
        return {"in_progress": [], "upcoming": [], "final": []}

    live_candidate_names: list[str] = []
    # Maps every ESPN name variant -> displayName (canonical). Both live_df market-team
    # lookups and odds_df team columns are normalised through this dict so the merge
    # always uses the same key regardless of which variant each side matched.
    espn_canonical: dict[str, str] = {}
    for event in events:
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors") or []
        for side in ("home", "away"):
            competitor = _extract_competitor(competitors, side)
            team = competitor.get("team") or {}
            canonical = (
                team.get("displayName")
                or team.get("shortDisplayName")
                or team.get("name")
            )
            if not canonical:
                continue
            for name_field in ("displayName", "shortDisplayName", "name"):
                value = team.get(name_field)
                if value:
                    espn_canonical[str(value)] = str(canonical)
                    live_candidate_names.append(str(value))
    live_candidate_names = sorted(set(live_candidate_names))

    all_team_features = load_current_all_team_features()
    projected_team_features = load_current_team_features()
    candidate_names: list[str] = []
    all_candidate_names: list[str] = []
    projected_team_lookup: dict[str, int] = {}
    team_lookup: dict[str, int] = {}
    elo_lookup: dict[str, float] = {}
    season: int | None = None
    model_bundle: tuple | None = None
    seed_baselines = None

    if not all_team_features.empty and {"TeamName", "TeamID"}.issubset(all_team_features.columns):
        all_candidate_names = (
            all_team_features["TeamName"].dropna().astype(str).drop_duplicates().tolist()
        )
        team_lookup = (
            all_team_features.drop_duplicates(subset=["TeamName"])
            .set_index("TeamName")["TeamID"]
            .astype(int)
            .to_dict()
        )
        if "elo" in all_team_features.columns:
            elo_lookup = (
                all_team_features.drop_duplicates(subset=["TeamName"])
                .set_index("TeamName")["elo"]
                .astype(float)
                .to_dict()
            )
        season_series = pd.to_numeric(all_team_features["Season"], errors="coerce").dropna()
        if not season_series.empty:
            season = int(season_series.iloc[0])
            model_bundle = load_model()
            seed_baselines = load_seed_matchup_baselines()

    if not projected_team_features.empty and {"TeamName", "TeamID"}.issubset(projected_team_features.columns):
        candidate_names = (
            projected_team_features["TeamName"].dropna().astype(str).drop_duplicates().tolist()
        )
        projected_team_lookup = (
            projected_team_features.drop_duplicates(subset=["TeamName"])
            .set_index("TeamName")["TeamID"]
            .astype(int)
            .to_dict()
        )

    odds_df = pd.DataFrame()
    try:
        odds_df = get_all_ncaab_market_odds(
            record_snapshot=False,
            projected_only=False,
            candidate_names=live_candidate_names,
        )
        if not odds_df.empty:
            live_day_et = pd.Timestamp.now(tz="America/New_York").normalize()
            source_time_cols = [
                column
                for column in [
                    "kalshi_tipoff_utc",
                    "tipoff_utc",
                ]
                if column in odds_df.columns
            ]

            any_source_in_window = pd.Series(False, index=odds_df.index)
            all_source_times_missing = pd.Series(True, index=odds_df.index)

            for prefix in ("kalshi",):
                time_col = f"{prefix}_tipoff_utc"
                if time_col not in odds_df.columns:
                    continue
                source_time = pd.to_datetime(odds_df[time_col], errors="coerce", utc=True)
                source_day_et = source_time.dt.tz_convert("America/New_York").dt.normalize()
                # Kalshi lists tournament games weeks ahead — use a wide window
                lookahead_days = 30 if prefix == "kalshi" else 1
                in_window = source_day_et.between(
                    live_day_et - pd.Timedelta(days=1),
                    live_day_et + pd.Timedelta(days=lookahead_days),
                )
                any_source_in_window |= in_window.fillna(False)
                all_source_times_missing &= source_time.isna()

                source_cols = [
                    col
                    for col in odds_df.columns
                    if col.startswith(f"{prefix}_") and col != time_col
                ]
                if source_cols:
                    odds_df.loc[source_time.notna() & ~in_window, source_cols] = np.nan

            odds_df = odds_df[any_source_in_window | all_source_times_missing].copy()

            reference_cols = [
                column
                for column in [
                    "kalshi_home_prob",
                ]
                if column in odds_df.columns
            ]
            if reference_cols:
                odds_df["market_home_prob"] = odds_df[reference_cols].mean(axis=1, skipna=True)
                odds_df["market_away_prob"] = 1.0 - odds_df["market_home_prob"]
                odds_df["market_home_implied"] = odds_df["market_home_prob"]
                odds_df["market_away_implied"] = odds_df["market_away_prob"]

            for side in ("home", "away"):
                decimal_columns = [
                    column
                    for column in [
                        f"kalshi_{side}_odds_decimal",
                    ]
                    if column in odds_df.columns
                ]
                if decimal_columns:
                    odds_df[f"{side}_odds_decimal"] = odds_df[decimal_columns].max(axis=1, skipna=True)
    except Exception as exc:
        logger.warning("NCAA live market enrichment failed: %s", exc)

    # Normalise odds_df team names to ESPN canonical (displayName) so the merge key
    # matches home_market_team / away_market_team built in live_df below.
    if not odds_df.empty:
        for _col in ("home_team", "away_team"):
            if _col in odds_df.columns:
                odds_df[_col] = odds_df[_col].map(
                    lambda x, _c=espn_canonical: _c.get(str(x), x) if x is not None else x
                )

    rows: list[dict[str, Any]] = []

    for event in events:
        competition = (event.get("competitions") or [{}])[0]
        competitors = competition.get("competitors") or []
        home = _extract_competitor(competitors, "home")
        away = _extract_competitor(competitors, "away")
        if not home or not away:
            continue

        home_team = home.get("team") or {}
        away_team = away.get("team") or {}

        home_name = (
            home_team.get("shortDisplayName")
            or home_team.get("displayName")
            or home_team.get("name")
            or ""
        )
        away_name = (
            away_team.get("shortDisplayName")
            or away_team.get("displayName")
            or away_team.get("name")
            or ""
        )
        home_abbr = home_team.get("abbreviation") or home_name
        away_abbr = away_team.get("abbreviation") or away_name

        status = event.get("status", {}).get("type", {})
        status_block = event.get("status", {})
        state = status.get("state")
        game_status = _scoreboard_status_code(state)
        status_text = status.get("shortDetail") or status.get("detail") or status.get("description") or ""
        period = int(status_block.get("period") or 0)
        display_clock = status_block.get("displayClock")
        seconds_remaining = _ncaab_seconds_remaining(game_status, period, display_clock)
        period_label = _ncaab_period_label(status_text, period)
        neutral_site = bool(competition.get("neutralSite"))

        tipoff_utc = pd.to_datetime(event.get("date"), errors="coerce", utc=True)
        game_date = (
            tipoff_utc.tz_convert("America/New_York").normalize().tz_localize(None)
            if pd.notna(tipoff_utc)
            else pd.NaT
        )

        home_score = _coerce_int(home.get("score"))
        away_score = _coerce_int(away.get("score"))

        home_field = match_projected_team_name(home_name, candidate_names) if candidate_names else None
        away_field = match_projected_team_name(away_name, candidate_names) if candidate_names else None
        home_all = match_projected_team_name(home_name, all_candidate_names) if all_candidate_names else None
        away_all = match_projected_team_name(away_name, all_candidate_names) if all_candidate_names else None
        projected_field_game = bool(
            season is not None
            and model_bundle is not None
            and seed_baselines is not None
            and home_field in projected_team_lookup
            and away_field in projected_team_lookup
        )

        game_row: dict[str, Any] = {
            "game_id": event.get("id") or competition.get("id") or f"{away_abbr}@{home_abbr}",
            "home_team": home_abbr,
            "away_team": away_abbr,
            "home_full_name": home_name,
            "away_full_name": away_name,
            "neutral_site": neutral_site,
            "home_score": home_score,
            "away_score": away_score,
            "game_date": str(game_date.date()) if pd.notna(game_date) else "",
            "tipoff_utc": tipoff_utc.isoformat() if pd.notna(tipoff_utc) else "",
            "game_status": game_status,
            "game_status_text": status_text,
            "period": period,
            "period_label": period_label,
            "clock_display": display_clock,
            "seconds_remaining": seconds_remaining,
            "projected_field_game": projected_field_game,
            "home_model_team": home_field,
            "away_model_team": away_field,
            "home_all_team": home_all,
            "away_all_team": away_all,
            "home_market_team": espn_canonical.get(
                match_projected_team_name(home_name, live_candidate_names) or "",
                match_projected_team_name(home_name, live_candidate_names),
            ),
            "away_market_team": espn_canonical.get(
                match_projected_team_name(away_name, live_candidate_names) or "",
                match_projected_team_name(away_name, live_candidate_names),
            ),
            "home_elo": None,
            "away_elo": None,
            "home_win_prob": None,
            "away_win_prob": None,
            "pregame_home_prob": None,
            "pregame_away_prob": None,
            "live_home_prob": None,
            "live_away_prob": None,
            "market_home_live": None,
            "market_away_live": None,
            "live_home_edge": None,
            "live_away_edge": None,
            "market_home_implied": None,
            "market_away_implied": None,
            "kalshi_home_prob": None,
            "kalshi_away_prob": None,
            "edge": None,
            "edge_team": None,
            "latest_play": None,
        }

        if game_status == 2:
            latest_play = get_latest_play("ncaab", game_row["game_id"])
            if latest_play:
                game_row["latest_play"] = latest_play

        can_price_game = bool(
            season is not None
            and model_bundle is not None
            and seed_baselines is not None
            and home_all in team_lookup
            and away_all in team_lookup
        )

        if can_price_game:
            prediction = predict_matchup(
                season,
                int(team_lookup[home_all]),
                int(team_lookup[away_all]),
                team_features=all_team_features,
                model_bundle=model_bundle,
                seed_baselines=seed_baselines,
            )
            home_prob = float(prediction["team_a_win_prob"])
            away_prob = float(prediction["team_b_win_prob"])
            home_elo = float(elo_lookup.get(home_all, config.ELO_BASE))
            away_elo = float(elo_lookup.get(away_all, config.ELO_BASE))
            live_home_prob, live_away_prob = live_win_prob(
                home_score or 0,
                away_score or 0,
                seconds_remaining,
                home_elo=home_elo,
                away_elo=away_elo,
                pregame_home_prob=home_prob,
                neutral_site=neutral_site,
            )
            game_row["home_elo"] = home_elo
            game_row["away_elo"] = away_elo
            game_row["pregame_home_prob"] = home_prob
            game_row["pregame_away_prob"] = away_prob
            game_row["live_home_prob"] = live_home_prob
            game_row["live_away_prob"] = live_away_prob
            game_row["home_win_prob"] = live_home_prob
            game_row["away_win_prob"] = live_away_prob
            # Predicted score via ML regression model
            try:
                from src.score_model import predict_ncaa_score
                import math as _math
                ra_row = all_team_features[all_team_features["TeamName"] == home_all]
                rb_row = all_team_features[all_team_features["TeamName"] == away_all]
                if not ra_row.empty and not rb_row.empty:
                    _sc = predict_ncaa_score(ra_row.iloc[0].to_dict(), rb_row.iloc[0].to_dict())
                    if _sc:
                        _total = _sc[0] + _sc[1]
                        _spread_b = 10.5 * _math.log(max(away_prob, 0.01) / max(home_prob, 0.01))
                        game_row["pred_home_score"] = round((_total - _spread_b) / 2)
                        game_row["pred_away_score"] = round((_total + _spread_b) / 2)
            except Exception:
                pass
        rows.append(game_row)

    live_df = pd.DataFrame(rows)
    if not live_df.empty:
        try:
            live_df = apply_ncaab_availability_adjustments(
                live_df,
                team_a_col="home_all_team",
                team_b_col="away_all_team",
                prob_a_col="pregame_home_prob",
                prob_b_col="pregame_away_prob",
                prefix_a="home",
                prefix_b="away",
            )
            for row in live_df.itertuples():
                if pd.isna(getattr(row, "pregame_home_prob", np.nan)):
                    continue
                live_home_prob, live_away_prob = live_win_prob(
                    getattr(row, "home_score", 0) or 0,
                    getattr(row, "away_score", 0) or 0,
                    getattr(row, "seconds_remaining", 0) or 0,
                    home_elo=float(getattr(row, "home_elo", config.ELO_BASE) or config.ELO_BASE),
                    away_elo=float(getattr(row, "away_elo", config.ELO_BASE) or config.ELO_BASE),
                    pregame_home_prob=float(getattr(row, "pregame_home_prob")),
                    neutral_site=bool(getattr(row, "neutral_site", False)),
                )
                live_df.at[row.Index, "live_home_prob"] = live_home_prob
                live_df.at[row.Index, "live_away_prob"] = live_away_prob
                live_df.at[row.Index, "home_win_prob"] = live_home_prob
                live_df.at[row.Index, "away_win_prob"] = live_away_prob
        except Exception as exc:
            logger.warning("NCAA live availability adjustment skipped: %s", exc)
    if not live_df.empty and not odds_df.empty:
        live_df = enrich_with_market_odds(live_df, odds_df)

    if not live_df.empty:
        market_cols = [
            "kalshi_home_prob",
            "kalshi_away_prob",
            "market_home_implied",
            "market_away_implied",
            "market_home_live",
            "market_away_live",
            "live_home_edge",
            "live_away_edge",
        ]
        for col in market_cols:
            if col in live_df.columns:
                live_df[col] = pd.to_numeric(live_df[col], errors="coerce")

        home_live_market = pd.to_numeric(live_df.get("market_home_live"), errors="coerce")
        away_live_market = pd.to_numeric(live_df.get("market_away_live"), errors="coerce")
        if "market_home_implied" in live_df.columns:
            live_df["market_home_implied"] = home_live_market.combine_first(
                pd.to_numeric(live_df["market_home_implied"], errors="coerce")
            )
        if "market_away_implied" in live_df.columns:
            live_df["market_away_implied"] = away_live_market.combine_first(
                pd.to_numeric(live_df["market_away_implied"], errors="coerce")
            )

        home_edge_series = pd.to_numeric(live_df.get("live_home_edge"), errors="coerce")
        away_edge_series = pd.to_numeric(live_df.get("live_away_edge"), errors="coerce")
        best_is_home = home_edge_series.fillna(-np.inf) >= away_edge_series.fillna(-np.inf)
        live_df["edge"] = np.where(best_is_home, home_edge_series, away_edge_series)
        live_df["edge_team"] = np.where(best_is_home, live_df["home_team"], live_df["away_team"])
        no_edge = home_edge_series.isna() & away_edge_series.isna()
        live_df.loc[no_edge, "edge"] = np.nan
        live_df.loc[no_edge, "edge_team"] = None

    def _group(status: int) -> list[dict[str, Any]]:
        if live_df.empty or "game_status" not in live_df.columns:
            return []
        subset = live_df[live_df["game_status"] == status]
        records = subset.to_dict("records")
        return _sort_games(records)

    return {
        "in_progress": _group(2),
        "upcoming": _group(1),
        "final": _group(3),
    }
