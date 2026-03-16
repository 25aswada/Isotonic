"""
ncaab_bracket_viz.py - Shared visual bracket rendering helpers for NCAA apps.
"""

from __future__ import annotations

from html import escape

import pandas as pd

BRACKET_CSS = """
    .ncaab-bracket-builder {
        display: grid;
        grid-template-columns: minmax(0, 1.45fr) minmax(220px, 0.72fr) minmax(0, 1.45fr);
        gap: 20px;
        margin-top: 12px;
    }
    .ncaab-bracket-side {
        display: grid;
        grid-template-rows: 1fr 1fr;
        gap: 18px;
    }
    .ncaab-region-panel {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 18px;
        padding: 16px;
        box-shadow: var(--shadow, none);
    }
    .ncaab-region-header {
        display: flex;
        justify-content: space-between;
        align-items: baseline;
        gap: 12px;
        margin-bottom: 10px;
    }
    .ncaab-region-name {
        font-size: 1rem;
        font-weight: 700;
        letter-spacing: 0.02em;
    }
    .ncaab-region-rounds {
        font-size: 0.72rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
    }
    .ncaab-playin-row {
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-bottom: 10px;
    }
    .ncaab-playin-pill {
        padding: 4px 8px;
        border-radius: 999px;
        font-size: 0.72rem;
        color: var(--muted);
        background: rgba(255, 255, 255, 0.04);
        border: 1px solid var(--line);
    }
    .ncaab-bracket-grid {
        display: grid;
        grid-template-columns: repeat(4, minmax(92px, 1fr));
        grid-template-rows: repeat(15, 46px);
        column-gap: 22px;
        row-gap: 10px;
        align-items: center;
    }
    .ncaab-bracket-game {
        position: relative;
        border: 1px solid var(--line);
        border-radius: 12px;
        background: rgba(255, 255, 255, 0.03);
        padding: 6px 8px;
        min-height: 42px;
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 3px;
    }
    .ncaab-bracket-side-left .ncaab-bracket-game::after,
    .ncaab-bracket-side-right .ncaab-bracket-game::after {
        content: "";
        position: absolute;
        top: 50%;
        width: 18px;
        border-top: 2px solid rgba(255, 255, 255, 0.14);
    }
    .ncaab-bracket-side-left .ncaab-bracket-game::after {
        right: -19px;
    }
    .ncaab-bracket-side-right .ncaab-bracket-game::after {
        left: -19px;
    }
    .ncaab-bracket-grid .ncaab-bracket-game[data-col="4"]::after {
        display: none;
    }
    .ncaab-bracket-team {
        display: flex;
        align-items: center;
        gap: 6px;
        font-size: 0.75rem;
        line-height: 1.1;
        color: var(--muted);
        white-space: nowrap;
        overflow: hidden;
        text-overflow: ellipsis;
    }
    .ncaab-bracket-team.winner {
        color: var(--text, var(--ink));
        font-weight: 700;
    }
    .ncaab-bracket-seed {
        width: 18px;
        flex: 0 0 18px;
        opacity: 0.7;
        text-align: right;
    }
    .ncaab-bracket-name {
        overflow: hidden;
        text-overflow: ellipsis;
        flex: 1 1 auto;
        min-width: 0;
    }
    .ncaab-bracket-elo {
        flex: 0 0 auto;
        font-size: 0.65rem;
        opacity: 0.55;
        margin-left: auto;
        padding-left: 4px;
        white-space: nowrap;
    }
    .ncaab-bracket-team.winner .ncaab-bracket-elo {
        opacity: 0.8;
    }
    .ncaab-bracket-footer {
        margin-top: 2px;
        font-size: 0.64rem;
        color: var(--muted);
        letter-spacing: 0.03em;
        text-transform: uppercase;
    }
    .ncaab-bracket-center {
        display: flex;
        flex-direction: column;
        justify-content: center;
        gap: 18px;
    }
    .ncaab-bracket-center-card {
        background: var(--panel);
        border: 1px solid var(--line);
        border-radius: 16px;
        padding: 14px 16px;
        box-shadow: var(--shadow, none);
    }
    .ncaab-bracket-center-label {
        font-size: 0.72rem;
        color: var(--muted);
        text-transform: uppercase;
        letter-spacing: 0.08em;
        margin-bottom: 6px;
    }
    .ncaab-bracket-title-card {
        border-width: 2px;
    }
    .ncaab-bracket-champion {
        text-align: center;
        font-weight: 800;
        font-size: 1.05rem;
    }
    .ncaab-bracket-champion small {
        display: block;
        margin-top: 6px;
        font-size: 0.72rem;
        color: var(--muted);
        letter-spacing: 0.08em;
        text-transform: uppercase;
    }
    @media (max-width: 1280px) {
        .ncaab-bracket-builder {
            grid-template-columns: 1fr;
        }
        .ncaab-bracket-center {
            order: -1;
        }
    }
    @media (max-width: 860px) {
        .ncaab-bracket-grid {
            grid-template-columns: repeat(2, minmax(0, 1fr));
            grid-template-rows: none;
        }
        .ncaab-bracket-game {
            min-height: 58px;
        }
        .ncaab-bracket-game::after {
            display: none !important;
        }
    }
"""

_ROUND_ORDER = ["Round of 64", "Round of 32", "Sweet 16", "Elite 8"]
_ROUND_ROW_MAP = {
    "Round of 64": [1, 3, 5, 7, 9, 11, 13, 15],
    "Round of 32": [2, 6, 10, 14],
    "Sweet 16": [4, 12],
    "Elite 8": [8],
}
_PAIR_ORDER = {
    (1, 16): 0,
    (8, 9): 1,
    (5, 12): 2,
    (4, 13): 3,
    (6, 11): 4,
    (3, 14): 5,
    (7, 10): 6,
    (2, 15): 7,
}


def _seed_lookup(team_features: pd.DataFrame) -> dict[int, int]:
    if team_features.empty or "TeamID" not in team_features.columns or "seed_num" not in team_features.columns:
        return {}
    lookup = (
        team_features.drop_duplicates(subset=["TeamID"])
        .set_index("TeamID")["seed_num"]
        .dropna()
        .astype(int)
        .to_dict()
    )
    return {int(team_id): int(seed) for team_id, seed in lookup.items()}


def _elo_lookup(team_features: pd.DataFrame) -> dict[int, int]:
    if team_features.empty or "TeamID" not in team_features.columns or "elo" not in team_features.columns:
        return {}
    lookup = (
        team_features.drop_duplicates(subset=["TeamID"])
        .set_index("TeamID")["elo"]
        .dropna()
        .to_dict()
    )
    return {int(team_id): int(round(elo)) for team_id, elo in lookup.items()}


def _team_line(name: str, seed: int | None, is_winner: bool, elo: int | None = None) -> str:
    seed_copy = str(seed) if seed is not None else ""
    winner_class = " winner" if is_winner else ""
    elo_html = f'<span class="ncaab-bracket-elo">{elo}</span>' if elo is not None else ""
    return (
        f'<div class="ncaab-bracket-team{winner_class}">'
        f'<span class="ncaab-bracket-seed">{escape(seed_copy)}</span>'
        f'<span class="ncaab-bracket-name">{escape(str(name))}</span>'
        f"{elo_html}"
        f"</div>"
    )


def _round64_sort_key(game: pd.Series, seed_lookup: dict[int, int]) -> tuple:
    seed_a = seed_lookup.get(int(game["team_a_id"]), 99)
    seed_b = seed_lookup.get(int(game["team_b_id"]), 99)
    ordered_pair = tuple(sorted((seed_a, seed_b)))
    return (_PAIR_ORDER.get(ordered_pair, 99), min(seed_a, seed_b), max(seed_a, seed_b), str(game["winner_name"]))


def _ordered_region_rounds(bracket: pd.DataFrame, region: str, seed_lookup: dict[int, int]) -> dict[str, list[dict]]:
    region_games = bracket[bracket["region"] == region].copy()
    ordered: dict[str, list[dict]] = {"First Four": []}
    if region_games.empty:
        return ordered

    first_four = region_games[region_games["round"] == "First Four"].copy()
    if not first_four.empty:
        first_four = first_four.sort_values(["team_a_name", "team_b_name"]).reset_index(drop=True)
        ordered["First Four"] = first_four.to_dict("records")

    previous_positions: dict[int, int] = {}
    for round_name in _ROUND_ORDER:
        round_games = region_games[region_games["round"] == round_name].copy()
        if round_games.empty:
            ordered[round_name] = []
            continue

        if round_name == "Round of 64":
            round_games["_sort"] = round_games.apply(lambda row: _round64_sort_key(row, seed_lookup), axis=1)
        else:
            round_games["_sort"] = round_games.apply(
                lambda row: min(
                    previous_positions.get(int(row["team_a_id"]), 99),
                    previous_positions.get(int(row["team_b_id"]), 99),
                ),
                axis=1,
            )

        round_games = round_games.sort_values("_sort").reset_index(drop=True)
        anchors = _ROUND_ROW_MAP[round_name]

        rows: list[dict] = []
        current_positions: dict[int, int] = {}
        for idx, game in round_games.iterrows():
            game_copy = game.to_dict()
            game_copy["row_anchor"] = anchors[idx]
            rows.append(game_copy)
            current_positions[int(game_copy["winner_id"])] = anchors[idx]

        ordered[round_name] = rows
        previous_positions = current_positions

    return ordered


def _matchup_card(game: dict, seed_lookup: dict[int, int], elo_lookup: dict[int, int], grid_column: int) -> str:
    seed_a = seed_lookup.get(int(game["team_a_id"])) if pd.notna(game.get("team_a_id")) else None
    seed_b = seed_lookup.get(int(game["team_b_id"])) if pd.notna(game.get("team_b_id")) else None
    elo_a = elo_lookup.get(int(game["team_a_id"])) if pd.notna(game.get("team_a_id")) else None
    elo_b = elo_lookup.get(int(game["team_b_id"])) if pd.notna(game.get("team_b_id")) else None
    winner_name = str(game.get("winner_name", ""))
    win_prob = pd.to_numeric(pd.Series([game.get("win_prob")]), errors="coerce").iloc[0]
    footer = f"{escape(winner_name)} · {win_prob:.0%}" if pd.notna(win_prob) else escape(winner_name)

    return (
        f'<div class="ncaab-bracket-game" data-col="{grid_column}" '
        f'style="grid-column:{grid_column}; grid-row:{int(game["row_anchor"])};">'
        f'{_team_line(str(game["team_a_name"]), seed_a, str(game["team_a_name"]) == winner_name, elo_a)}'
        f'{_team_line(str(game["team_b_name"]), seed_b, str(game["team_b_name"]) == winner_name, elo_b)}'
        f'<div class="ncaab-bracket-footer">{footer}</div>'
        "</div>"
    )


def _region_panel(bracket: pd.DataFrame, team_features: pd.DataFrame, region: str, side: str) -> str:
    seed_lookup = _seed_lookup(team_features)
    elo_lookup = _elo_lookup(team_features)
    ordered = _ordered_region_rounds(bracket, region, seed_lookup)

    playins = "".join(
        f'<div class="ncaab-playin-pill">{escape(str(game["team_a_name"]))} vs {escape(str(game["team_b_name"]))} '
        f"→ {escape(str(game['winner_name']))}</div>"
        for game in ordered.get("First Four", [])
    )
    if not playins:
        playins = '<div class="ncaab-playin-pill">No play-in game in this region</div>'

    cards: list[str] = []
    for column_index, round_name in enumerate(_ROUND_ORDER, start=1):
        for game in ordered.get(round_name, []):
            cards.append(_matchup_card(game, seed_lookup, elo_lookup, column_index))

    return (
        f'<div class="ncaab-region-panel ncaab-bracket-side-{side}">'
        f'<div class="ncaab-region-header">'
        f'<div class="ncaab-region-name">{escape(region)}</div>'
        f'<div class="ncaab-region-rounds">Round of 64 · 32 · Sweet 16 · Elite 8</div>'
        f"</div>"
        f'<div class="ncaab-playin-row">{playins}</div>'
        f'<div class="ncaab-bracket-grid">{"".join(cards)}</div>'
        "</div>"
    )


def _center_matchup_card(game: pd.Series, team_features: pd.DataFrame, label: str, extra_class: str = "") -> str:
    seed_lookup = _seed_lookup(team_features)
    elo_lookup = _elo_lookup(team_features)
    winner_name = str(game.get("winner_name", ""))
    win_prob = pd.to_numeric(pd.Series([game.get("win_prob")]), errors="coerce").iloc[0]
    seed_a = seed_lookup.get(int(game["team_a_id"])) if pd.notna(game.get("team_a_id")) else None
    seed_b = seed_lookup.get(int(game["team_b_id"])) if pd.notna(game.get("team_b_id")) else None
    elo_a = elo_lookup.get(int(game["team_a_id"])) if pd.notna(game.get("team_a_id")) else None
    elo_b = elo_lookup.get(int(game["team_b_id"])) if pd.notna(game.get("team_b_id")) else None

    return (
        f'<div class="ncaab-bracket-center-card {extra_class}">'
        f'<div class="ncaab-bracket-center-label">{escape(label)}</div>'
        f'{_team_line(str(game["team_a_name"]), seed_a, str(game["team_a_name"]) == winner_name, elo_a)}'
        f'{_team_line(str(game["team_b_name"]), seed_b, str(game["team_b_name"]) == winner_name, elo_b)}'
        f'<div class="ncaab-bracket-footer">{escape(winner_name)} · {win_prob:.0%}</div>'
        "</div>"
    )


def _center_panel(bracket: pd.DataFrame, team_features: pd.DataFrame) -> str:
    final_four_top = bracket[(bracket["round"] == "Final Four") & (bracket["region"] == "East vs Midwest")].head(1)
    final_four_bottom = bracket[(bracket["round"] == "Final Four") & (bracket["region"] == "South vs West")].head(1)
    title_game = bracket[bracket["round"] == "National Championship"].head(1)

    cards: list[str] = ['<div class="ncaab-bracket-center">']
    if not final_four_top.empty:
        cards.append(_center_matchup_card(final_four_top.iloc[0], team_features, "Final Four"))
    if not title_game.empty:
        cards.append(_center_matchup_card(title_game.iloc[0], team_features, "National Championship", "ncaab-bracket-title-card"))
        winner_name = str(title_game.iloc[0]["winner_name"])
        cards.append(
            '<div class="ncaab-bracket-center-card">'
            f'<div class="ncaab-bracket-champion">{escape(winner_name)}<small>Model Champion</small></div>'
            "</div>"
        )
    if not final_four_bottom.empty:
        cards.append(_center_matchup_card(final_four_bottom.iloc[0], team_features, "Final Four"))
    cards.append("</div>")
    return "".join(cards)


def build_bracket_html(bracket: pd.DataFrame, team_features: pd.DataFrame) -> str:
    """Render a visual NCAA bracket from the simulated bracket DataFrame."""
    if bracket.empty or team_features.empty:
        return ""

    left = "".join(
        [
            _region_panel(bracket, team_features, "East", "left"),
            _region_panel(bracket, team_features, "South", "left"),
        ]
    )
    right = "".join(
        [
            _region_panel(bracket, team_features, "Midwest", "right"),
            _region_panel(bracket, team_features, "West", "right"),
        ]
    )
    center = _center_panel(bracket, team_features)

    return (
        '<div class="ncaab-bracket-builder">'
        f'<div class="ncaab-bracket-side">{left}</div>'
        f"{center}"
        f'<div class="ncaab-bracket-side">{right}</div>'
        "</div>"
    )
