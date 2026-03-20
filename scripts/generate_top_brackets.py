#!/usr/bin/env python3
"""
Run 1 million Monte Carlo bracket simulations and produce 3 PDF brackets
for the 3 most likely champions.

For each top champion, we find the most likely path through the bracket
by filtering all simulations where that team won the title, then picking
the most common winner of each game slot within those filtered sims.

Usage:
    python scripts/generate_top_brackets.py
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import ncaab_config as nc
from src.ncaab_live import (
    ROUND_ONE_PAIRINGS,
    _compute_game_probabilities,
    _get_prob,
    load_seed_matchup_baselines,
)
from src.ncaab_model import load_model

# ── Configuration ────────────────────────────────────────────────────
N_SIMS = 1_000_000
OUTPUT_DIR = ROOT / "output"
OUTPUT_DIR.mkdir(exist_ok=True)

ROUND_NAMES = [
    "Round of 64",
    "Round of 32",
    "Sweet 16",
    "Elite 8",
    "Final Four",
    "Championship",
]


# ── Simulation engine ───────────────────────────────────────────────
def run_simulations(
    projected_team_features: pd.DataFrame,
    meta: dict,
    n_sims: int = N_SIMS,
) -> tuple[dict[int, dict[str, dict[int, int]]], dict[int, int], dict]:
    """Run n_sims Monte Carlo simulations.

    Returns:
        champ_slot_wins: champion_id -> slot_key -> {team_id: count}
            Game-slot win counts filtered by which team won the championship.
        champ_counts: champion_id -> count
        info: shared metadata dict
    """

    model_bundle = load_model()
    seed_baselines = load_seed_matchup_baselines()

    print("Pre-computing pairwise win probabilities ...")
    prob_cache = _compute_game_probabilities(
        projected_team_features, model_bundle, seed_baselines
    )

    regions = sorted(projected_team_features["region"].dropna().unique())
    region_seeds: dict[str, dict[int, list[int]]] = {}
    for region in regions:
        rdf = projected_team_features[projected_team_features["region"] == region]
        region_seeds[region] = {
            int(seed): group.sort_values("TeamName")["TeamID"].tolist()
            for seed, group in rdf.groupby("seed_num")
        }

    team_name_map = dict(zip(
        projected_team_features["TeamID"].astype(int),
        projected_team_features["TeamName"],
    ))
    team_seed_map = dict(zip(
        projected_team_features["TeamID"].astype(int),
        projected_team_features["seed_num"].astype(int),
    ))
    semifinal_pairs = meta.get("semifinal_pairs") or [("East", "Midwest"), ("South", "West")]

    rng = np.random.default_rng(42)
    max_games_per_sim = 70
    all_randoms = rng.random((n_sims, max_games_per_sim))

    # Track game slot wins per champion
    # champ_slot_wins[champ_id][slot_key][team_id] = count
    champ_slot_wins: dict[int, dict[str, dict[int, int]]] = {}
    champ_counts: dict[int, int] = {}

    print(f"Running {n_sims:,} simulations ...")
    t0 = time.time()
    report_interval = n_sims // 10

    for sim_idx in range(n_sims):
        if sim_idx > 0 and sim_idx % report_interval == 0:
            elapsed = time.time() - t0
            pct = sim_idx / n_sims * 100
            rate = sim_idx / elapsed
            eta = (n_sims - sim_idx) / rate
            print(f"  {pct:.0f}% ({sim_idx:,}/{n_sims:,}) -- {rate:,.0f} sims/s -- ETA {eta:.0f}s")

        randoms = all_randoms[sim_idx]
        game_idx = 0

        # Collect all game results for this sim
        sim_results: list[tuple[str, int]] = []  # (slot_key, winner_id)

        region_champs: dict[str, int] = {}
        for region in regions:
            seeds = region_seeds[region]
            advanced: dict[int, int] = {}
            for seed_num, team_ids in seeds.items():
                if len(team_ids) == 1:
                    advanced[seed_num] = team_ids[0]
                else:
                    p = _get_prob(prob_cache, team_ids[0], team_ids[1])
                    w = team_ids[0] if randoms[game_idx] < p else team_ids[1]
                    sim_results.append((f"FF|{region}|{seed_num}", w))
                    game_idx += 1
                    advanced[seed_num] = w

            r64: list[int] = []
            for idx, (sa, sb) in enumerate(ROUND_ONE_PAIRINGS):
                p = _get_prob(prob_cache, advanced[sa], advanced[sb])
                w = advanced[sa] if randoms[game_idx] < p else advanced[sb]
                sim_results.append((f"R64|{region}|{idx}", w))
                game_idx += 1
                r64.append(w)

            r32: list[int] = []
            for idx, (a, b) in enumerate(zip(r64[::2], r64[1::2])):
                p = _get_prob(prob_cache, a, b)
                w = a if randoms[game_idx] < p else b
                sim_results.append((f"R32|{region}|{idx}", w))
                game_idx += 1
                r32.append(w)

            s16: list[int] = []
            for idx, (a, b) in enumerate(zip(r32[::2], r32[1::2])):
                p = _get_prob(prob_cache, a, b)
                w = a if randoms[game_idx] < p else b
                sim_results.append((f"S16|{region}|{idx}", w))
                game_idx += 1
                s16.append(w)

            p = _get_prob(prob_cache, s16[0], s16[1])
            w = s16[0] if randoms[game_idx] < p else s16[1]
            sim_results.append((f"E8|{region}", w))
            game_idx += 1
            region_champs[region] = w

        finalists: list[int] = []
        for idx, (ra, rb) in enumerate(semifinal_pairs[:2]):
            if ra in region_champs and rb in region_champs:
                p = _get_prob(prob_cache, region_champs[ra], region_champs[rb])
                w = region_champs[ra] if randoms[game_idx] < p else region_champs[rb]
                sim_results.append((f"FF4|{idx}", w))
                game_idx += 1
                finalists.append(w)

        champion_id = -1
        if len(finalists) == 2:
            p = _get_prob(prob_cache, finalists[0], finalists[1])
            w = finalists[0] if randoms[game_idx] < p else finalists[1]
            sim_results.append(("CHAMP", w))
            champion_id = w

        if champion_id < 0:
            continue

        champ_counts[champion_id] = champ_counts.get(champion_id, 0) + 1

        # Record all game results under this champion
        if champion_id not in champ_slot_wins:
            champ_slot_wins[champion_id] = {}
        csw = champ_slot_wins[champion_id]
        for slot_key, winner in sim_results:
            if slot_key not in csw:
                csw[slot_key] = {}
            csw[slot_key][winner] = csw[slot_key].get(winner, 0) + 1

    elapsed = time.time() - t0
    print(f"Done: {n_sims:,} sims in {elapsed:.1f}s ({n_sims/elapsed:,.0f} sims/s)")

    print("\nChampionship probability (top 10):")
    for tid, cnt in sorted(champ_counts.items(), key=lambda x: -x[1])[:10]:
        print(f"  ({team_seed_map[tid]}) {team_name_map[tid]}: {cnt/n_sims*100:.2f}%")

    info = {
        "regions": regions,
        "region_seeds": region_seeds,
        "team_name_map": team_name_map,
        "team_seed_map": team_seed_map,
        "semifinal_pairs": semifinal_pairs,
        "prob_cache": prob_cache,
        "n_sims": n_sims,
    }
    return champ_slot_wins, champ_counts, info


# ── Bracket builder ──────────────────────────────────────────────────
def _make_game(
    round_name: str,
    region: str,
    a_id: int,
    b_id: int,
    winner_id: int,
    win_prob: float,
    sim_pct: float | None,
    name_map: dict,
    seed_map: dict,
) -> dict:
    loser_id = b_id if winner_id == a_id else a_id
    w_seed = seed_map.get(winner_id, 16)
    l_seed = seed_map.get(loser_id, 16)
    return {
        "round": round_name,
        "region": region,
        "team_a": f"({seed_map.get(a_id, '?')}) {name_map.get(a_id, '?')}",
        "team_b": f"({seed_map.get(b_id, '?')}) {name_map.get(b_id, '?')}",
        "winner": f"({w_seed}) {name_map.get(winner_id, '?')}",
        "winner_name": name_map.get(winner_id, "?"),
        "winner_id": winner_id,
        "loser_id": loser_id,
        "winner_seed": w_seed,
        "loser_seed": l_seed,
        "win_prob": win_prob,
        "sim_pct": sim_pct,
        "is_upset": w_seed > l_seed,
    }


def build_most_likely_bracket(
    slot_wins: dict[str, dict[int, int]],
    champ_sim_count: int,
    info: dict,
) -> list[dict]:
    """Build the most likely bracket path given conditional game-slot wins.
    For each game, pick whoever won that slot most often."""
    prob_cache = info["prob_cache"]
    regions = info["regions"]
    region_seeds = info["region_seeds"]
    name_map = info["team_name_map"]
    seed_map = info["team_seed_map"]
    semifinal_pairs = info["semifinal_pairs"]
    games: list[dict] = []

    def pick(a: int, b: int, rnd: str, reg: str, slot_key: str) -> int:
        slot = slot_wins.get(slot_key, {})
        a_cnt = slot.get(a, 0)
        b_cnt = slot.get(b, 0)
        winner = a if a_cnt >= b_cnt else b
        p = _get_prob(prob_cache, winner, b if winner == a else a)
        sim_pct = max(a_cnt, b_cnt) / max(a_cnt + b_cnt, 1)
        games.append(_make_game(rnd, reg, a, b, winner, p, sim_pct, name_map, seed_map))
        return winner

    region_champs: dict[str, int] = {}
    for region in regions:
        seeds = region_seeds[region]
        advanced: dict[int, int] = {}
        for seed_num, team_ids in seeds.items():
            if len(team_ids) == 1:
                advanced[seed_num] = team_ids[0]
            else:
                advanced[seed_num] = pick(
                    team_ids[0], team_ids[1], "First Four", region,
                    f"FF|{region}|{seed_num}",
                )
        r64 = [
            pick(advanced[sa], advanced[sb], "Round of 64", region, f"R64|{region}|{i}")
            for i, (sa, sb) in enumerate(ROUND_ONE_PAIRINGS)
        ]
        r32 = [
            pick(a, b, "Round of 32", region, f"R32|{region}|{i}")
            for i, (a, b) in enumerate(zip(r64[::2], r64[1::2]))
        ]
        s16 = [
            pick(a, b, "Sweet 16", region, f"S16|{region}|{i}")
            for i, (a, b) in enumerate(zip(r32[::2], r32[1::2]))
        ]
        region_champs[region] = pick(s16[0], s16[1], "Elite 8", region, f"E8|{region}")

    finalists = []
    for idx, (ra, rb) in enumerate(semifinal_pairs[:2]):
        if ra in region_champs and rb in region_champs:
            finalists.append(pick(
                region_champs[ra], region_champs[rb],
                "Final Four", f"{ra} vs {rb}", f"FF4|{idx}",
            ))
    if len(finalists) == 2:
        pick(finalists[0], finalists[1], "National Championship", "Title", "CHAMP")
    return games


def build_upset_bracket(
    info: dict,
    upset_threshold: float = 0.35,
) -> list[dict]:
    """Build a bracket biased toward likely upsets.

    For each game, pick the underdog (higher seed number) when their
    model win probability >= *upset_threshold*.  Otherwise pick the
    favourite.  This yields an aggressive-but-plausible upset bracket.
    """
    prob_cache = info["prob_cache"]
    regions = info["regions"]
    region_seeds = info["region_seeds"]
    name_map = info["team_name_map"]
    seed_map = info["team_seed_map"]
    semifinal_pairs = info["semifinal_pairs"]
    games: list[dict] = []

    def pick(a: int, b: int, rnd: str, reg: str) -> int:
        p_a = _get_prob(prob_cache, a, b)
        p_b = 1.0 - p_a
        seed_a = seed_map.get(a, 16)
        seed_b = seed_map.get(b, 16)

        if seed_a < seed_b:
            # a is favourite (lower seed), b is underdog
            if p_b >= upset_threshold:
                winner, prob = b, p_b
            else:
                winner, prob = a, p_a
        elif seed_b < seed_a:
            # b is favourite, a is underdog
            if p_a >= upset_threshold:
                winner, prob = a, p_a
            else:
                winner, prob = b, p_b
        else:
            # Same seed — pick model favourite
            if p_a >= p_b:
                winner, prob = a, p_a
            else:
                winner, prob = b, p_b

        games.append(_make_game(rnd, reg, a, b, winner, prob, None, name_map, seed_map))
        return winner

    region_champs: dict[str, int] = {}
    for region in regions:
        seeds = region_seeds[region]
        advanced: dict[int, int] = {}
        for seed_num, team_ids in seeds.items():
            if len(team_ids) == 1:
                advanced[seed_num] = team_ids[0]
            else:
                advanced[seed_num] = pick(
                    team_ids[0], team_ids[1], "First Four", region,
                )
        r64 = [
            pick(advanced[sa], advanced[sb], "Round of 64", region)
            for sa, sb in ROUND_ONE_PAIRINGS
        ]
        r32 = [
            pick(a, b, "Round of 32", region)
            for a, b in zip(r64[::2], r64[1::2])
        ]
        s16 = [
            pick(a, b, "Sweet 16", region)
            for a, b in zip(r32[::2], r32[1::2])
        ]
        region_champs[region] = pick(s16[0], s16[1], "Elite 8", region)

    finalists = []
    for ra, rb in semifinal_pairs[:2]:
        if ra in region_champs and rb in region_champs:
            finalists.append(pick(
                region_champs[ra], region_champs[rb],
                "Final Four", f"{ra} vs {rb}",
            ))
    if len(finalists) == 2:
        pick(finalists[0], finalists[1], "National Championship", "Title")
    return games


# ── PDF rendering (bracket tree) ─────────────────────────────────────
def render_bracket_pdf(
    games: list[dict],
    title: str,
    subtitle: str,
    output_path: Path,
):
    """Render a proper bracket-tree PDF in landscape."""
    from reportlab.lib import colors
    from reportlab.lib.pagesizes import LETTER
    from reportlab.pdfgen import canvas

    # Landscape
    width, height = LETTER[1], LETTER[0]
    c = canvas.Canvas(str(output_path), pagesize=(width, height))

    # Extract champion info
    champion = champ_sim = None
    for g in games:
        if g["round"] == "National Championship":
            champion = g["winner"]
            champ_sim = g.get("sim_pct")
            break
    n_upsets = sum(1 for g in games if g.get("is_upset"))

    # ── Colors ──
    C_DARK = colors.HexColor("#1a1a2e")
    C_SOFT = colors.HexColor("#888888")
    C_ACCENT = colors.HexColor("#0f4c75")
    C_GOLD = colors.HexColor("#c49000")
    C_GOLD_BG = colors.HexColor("#fff8e1")
    C_GOLD_BD = colors.HexColor("#e6b800")
    C_WIN_BG = colors.HexColor("#e8f5e9")
    C_LINE = colors.HexColor("#bbbbbb")
    C_LIGHT_LINE = colors.HexColor("#dddddd")
    C_CHAMP_BG = colors.HexColor("#fff3cd")
    C_CHAMP_BD = colors.HexColor("#d4a017")

    # ── Organize games by region and round ──
    region_order: list[str] = []
    for g in games:
        if g["region"] not in region_order and g["region"] != "Title" and "vs" not in g["region"]:
            region_order.append(g["region"])

    def region_round_games(region: str, rnd: str) -> list[dict]:
        return [g for g in games if g["region"] == region and g["round"] == rnd]

    ff_games = [g for g in games if g["round"] == "Final Four"]
    title_game = next((g for g in games if g["round"] == "National Championship"), None)

    # ── Layout constants ──
    # Landscape LETTER = 792 x 612.  Each side needs 4 round columns.
    # Budget: 2 sides + center strip must fit in 792 - 2*margins.
    MARGIN_TOP = 54
    MARGIN_BOTTOM = 22
    MARGIN_LR = 10
    SLOT_W = 74          # narrower boxes to fit everything
    SLOT_H = 12
    MATCH_H = SLOT_H * 2 + 2
    CONNECTOR_W = 8      # compact connectors
    CENTER_SLOT_W = 90   # wider boxes for FF / Championship (emphasis)
    CENTER_GAP = 30      # padding between each side's E8 column and center boxes

    bracket_top = height - MARGIN_TOP
    bracket_bottom = MARGIN_BOTTOM + 14
    bracket_h = bracket_top - bracket_bottom

    # Horizontal budget
    col_step = SLOT_W + CONNECTOR_W  # 82 per round column
    side_cols_w = 4 * SLOT_W + 3 * CONNECTOR_W  # R64..E8 = 4*74 + 3*8 = 320
    center_strip_w = CENTER_SLOT_W + 2 * CENTER_GAP  # 150
    total_w = 2 * side_cols_w + center_strip_w  # 790 -- fits in 772 usable

    # Compute actual left edge so everything is centered
    usable_w = width - 2 * MARGIN_LR  # 772
    x_offset = MARGIN_LR + (usable_w - total_w) / 2
    if x_offset < MARGIN_LR:
        x_offset = MARGIN_LR

    def _team_label(g: dict, side: str) -> str:
        return g[f"team_{side}"]

    def _winner_side(g: dict) -> str:
        if g["winner_name"] in g["team_a"]:
            return "a"
        return "b"

    def draw_slot(x: float, y: float, w: float, label: str, is_winner: bool,
                  is_upset: bool, prob_str: str, align: str = "left"):
        """Draw a single team slot box of width *w*."""
        if is_upset and is_winner:
            c.setFillColor(C_GOLD_BG)
            c.roundRect(x, y, w, SLOT_H, 1.5, fill=1, stroke=0)
            c.setStrokeColor(C_GOLD_BD)
            c.setLineWidth(0.3)
            c.roundRect(x, y, w, SLOT_H, 1.5, fill=0, stroke=1)
        elif is_winner:
            c.setFillColor(C_WIN_BG)
            c.roundRect(x, y, w, SLOT_H, 1.5, fill=1, stroke=0)
            c.setStrokeColor(C_LIGHT_LINE)
            c.setLineWidth(0.2)
            c.roundRect(x, y, w, SLOT_H, 1.5, fill=0, stroke=1)
        else:
            c.setStrokeColor(C_LIGHT_LINE)
            c.setLineWidth(0.2)
            c.roundRect(x, y, w, SLOT_H, 1.5, fill=0, stroke=1)

        text_y = y + 3
        if align == "left":
            c.setFont("Helvetica-Bold" if is_winner else "Helvetica", 5.5)
            c.setFillColor(C_GOLD if (is_upset and is_winner) else C_DARK if is_winner else C_SOFT)
            c.drawString(x + 3, text_y, label)
            if prob_str:
                c.setFont("Helvetica", 4.5)
                c.setFillColor(C_SOFT)
                c.drawRightString(x + w - 3, text_y, prob_str)
        else:
            c.setFont("Helvetica-Bold" if is_winner else "Helvetica", 5.5)
            c.setFillColor(C_GOLD if (is_upset and is_winner) else C_DARK if is_winner else C_SOFT)
            c.drawRightString(x + w - 3, text_y, label)
            if prob_str:
                c.setFont("Helvetica", 4.5)
                c.setFillColor(C_SOFT)
                c.drawString(x + 3, text_y, prob_str)

    def draw_matchup(g: dict, x: float, y_center: float, align: str = "left",
                     box_w: float | None = None) -> tuple[float, float]:
        """Draw a matchup (2 team slots). Returns (x_connector, y_connector)."""
        w = box_w or SLOT_W
        y_top = y_center + 1
        y_bot = y_center - SLOT_H - 1

        ws = _winner_side(g)
        is_upset = g.get("is_upset", False)

        prob_a = f"{g['win_prob']:.0%}" if ws == "a" else ""
        prob_b = f"{g['win_prob']:.0%}" if ws == "b" else ""
        if g.get("sim_pct") is not None:
            if ws == "a":
                prob_a += f" ({g['sim_pct']:.0%})"
            else:
                prob_b += f" ({g['sim_pct']:.0%})"

        draw_slot(x, y_top, w, _team_label(g, "a"), ws == "a", is_upset and ws == "a", prob_a, align)
        draw_slot(x, y_bot, w, _team_label(g, "b"), ws == "b", is_upset and ws == "b", prob_b, align)

        conn_y = y_center
        if align == "left":
            conn_x = x + w
        else:
            conn_x = x
        return conn_x, conn_y

    def draw_region_bracket(
        region_games: dict[str, list[dict]],
        region_name: str,
        x_start: float,
        y_top: float,
        y_bot: float,
        direction: str,
    ):
        """Draw a full regional bracket (R64 through E8)."""
        rounds = ["Round of 64", "Round of 32", "Sweet 16", "Elite 8"]
        round_labels = ["R64", "R32", "S16", "E8"]
        round_counts = [8, 4, 2, 1]

        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_ACCENT)
        if direction == "left":
            c.drawString(x_start, y_top + 6, region_name.upper())
        else:
            c.drawRightString(x_start + SLOT_W, y_top + 6, region_name.upper())

        region_h = y_top - y_bot
        prev_connectors: list[tuple[float, float]] = []

        for ri, (rnd, label, n_games) in enumerate(zip(rounds, round_labels, round_counts)):
            rnd_games = region_games.get(rnd, [])
            if not rnd_games:
                continue

            if direction == "left":
                col_x = x_start + ri * col_step
                align = "left"
            else:
                col_x = x_start - ri * col_step
                align = "right"

            if n_games == 1:
                y_centers = [y_bot + region_h / 2]
            else:
                spacing = region_h / n_games
                y_centers = [y_bot + spacing * (i + 0.5) for i in range(n_games)]

            # Round label above column
            c.setFont("Helvetica", 4)
            c.setFillColor(C_SOFT)
            c.drawCentredString(col_x + SLOT_W / 2, y_top + 1, label)

            connectors: list[tuple[float, float]] = []
            for gi, g in enumerate(rnd_games):
                conn_x, conn_y = draw_matchup(g, col_x, y_centers[gi], align)
                connectors.append((conn_x, conn_y))

            if ri < len(rounds) - 1 and len(connectors) >= 2:
                c.setStrokeColor(C_LINE)
                c.setLineWidth(0.5)
                for i in range(0, len(connectors), 2):
                    if i + 1 >= len(connectors):
                        break
                    x1, y1 = connectors[i]
                    x2, y2 = connectors[i + 1]
                    mid_y = (y1 + y2) / 2
                    if direction == "left":
                        mid_x = x1 + CONNECTOR_W / 2
                        c.line(x1, y1, mid_x, y1)
                        c.line(x1, y2, mid_x, y2)
                        c.line(mid_x, y1, mid_x, y2)
                        c.line(mid_x, mid_y, x1 + CONNECTOR_W, mid_y)
                    else:
                        mid_x = x1 - CONNECTOR_W / 2
                        c.line(x1, y1, mid_x, y1)
                        c.line(x1, y2, mid_x, y2)
                        c.line(mid_x, y1, mid_x, y2)
                        c.line(mid_x, mid_y, x1 - CONNECTOR_W, mid_y)

            prev_connectors = connectors

        if prev_connectors:
            return prev_connectors[0]
        return None

    # ── Header ──
    c.setFont("Helvetica-Bold", 13)
    c.setFillColor(C_DARK)
    c.drawCentredString(width / 2, height - 16, title)

    c.setFont("Helvetica", 6)
    c.setFillColor(C_SOFT)
    c.drawCentredString(width / 2, height - 26, subtitle)

    if champion:
        c.setFont("Helvetica-Bold", 9)
        c.setFillColor(C_GOLD)
        extra = f"  ({champ_sim:.0%} of sims)" if champ_sim is not None else ""
        c.drawCentredString(width / 2, height - 38, f"CHAMPION: {champion}{extra}")

    if n_upsets > 0:
        c.setFont("Helvetica", 5)
        c.setFillColor(C_GOLD)
        c.drawCentredString(width / 2, height - 47, f"{n_upsets} upset{'s' if n_upsets != 1 else ''} highlighted in gold")

    # ── Draw brackets ──
    # Left side: regions 0,1 flowing rightward.  Right side: regions 2,3 flowing leftward.
    # Center strip: Final Four + Championship.

    region_gap = 14
    half_h = (bracket_h - region_gap) / 2

    # Left side
    left_x = x_offset
    left_regions = region_order[:2] if len(region_order) >= 2 else region_order

    e8_connectors_left: list[tuple] = []
    for ri, region in enumerate(left_regions):
        ry_top = bracket_top - ri * (half_h + region_gap)
        ry_bot = ry_top - half_h
        rgames = {
            rnd: region_round_games(region, rnd)
            for rnd in ["Round of 64", "Round of 32", "Sweet 16", "Elite 8"]
        }
        result = draw_region_bracket(rgames, region, left_x, ry_top, ry_bot, "left")
        if result:
            e8_connectors_left.append(result)

    # Right side
    right_x = x_offset + total_w - SLOT_W  # rightmost column start for right-flowing regions
    right_regions = region_order[2:4] if len(region_order) >= 4 else []

    e8_connectors_right: list[tuple] = []
    for ri, region in enumerate(right_regions):
        ry_top = bracket_top - ri * (half_h + region_gap)
        ry_bot = ry_top - half_h
        rgames = {
            rnd: region_round_games(region, rnd)
            for rnd in ["Round of 64", "Round of 32", "Sweet 16", "Elite 8"]
        }
        result = draw_region_bracket(rgames, region, right_x, ry_top, ry_bot, "right")
        if result:
            e8_connectors_right.append(result)

    # ── Final Four & Championship in center ──
    center_x = width / 2 - CENTER_SLOT_W / 2
    center_y = bracket_top - bracket_h / 2

    # Vertical spread: FF games above and below championship
    ff_spread = 70  # generous vertical separation
    ff1_y = center_y + ff_spread
    ff2_y = center_y - ff_spread
    champ_y = center_y

    # FF labels
    c.setFont("Helvetica-Bold", 5.5)
    c.setFillColor(C_ACCENT)
    c.drawCentredString(center_x + CENTER_SLOT_W / 2, ff1_y + SLOT_H + 6, "FINAL FOUR")
    c.drawCentredString(center_x + CENTER_SLOT_W / 2, ff2_y + SLOT_H + 6, "FINAL FOUR")

    # Draw FF matchups with wider center boxes
    if len(ff_games) >= 1:
        draw_matchup(ff_games[0], center_x, ff1_y, "left", CENTER_SLOT_W)
    if len(ff_games) >= 2:
        draw_matchup(ff_games[1], center_x, ff2_y, "left", CENTER_SLOT_W)

    # E8 -> FF connector lines (left side feeds upper FF, right side feeds lower FF)
    c.setStrokeColor(C_LINE)
    c.setLineWidth(0.5)
    if len(e8_connectors_left) >= 1:
        ex, ey = e8_connectors_left[0]
        ff_top_slot = ff1_y + 1 + SLOT_H / 2  # middle of top team slot
        c.line(ex, ey, center_x, ff_top_slot)
    if len(e8_connectors_left) >= 2:
        ex, ey = e8_connectors_left[1]
        ff_bot_slot = ff1_y - SLOT_H / 2 - 1  # middle of bottom team slot
        c.line(ex, ey, center_x, ff_bot_slot)

    if len(e8_connectors_right) >= 1:
        ex, ey = e8_connectors_right[0]
        ff_top_slot = ff2_y + 1 + SLOT_H / 2
        c.line(ex, ey, center_x + CENTER_SLOT_W, ff_top_slot)
    if len(e8_connectors_right) >= 2:
        ex, ey = e8_connectors_right[1]
        ff_bot_slot = ff2_y - SLOT_H / 2 - 1
        c.line(ex, ey, center_x + CENTER_SLOT_W, ff_bot_slot)

    # Championship label + matchup
    if title_game:
        c.setFont("Helvetica-Bold", 7)
        c.setFillColor(C_ACCENT)
        c.drawCentredString(center_x + CENTER_SLOT_W / 2, champ_y + SLOT_H + 8, "CHAMPIONSHIP")
        draw_matchup(title_game, center_x, champ_y, "left", CENTER_SLOT_W)

        # FF -> Championship connectors: bracket-style lines on the right side
        if len(ff_games) >= 2:
            c.setStrokeColor(C_LINE)
            c.setLineWidth(0.5)
            bend_x = center_x + CENTER_SLOT_W + 8
            c.line(center_x + CENTER_SLOT_W, ff1_y, bend_x, ff1_y)
            c.line(center_x + CENTER_SLOT_W, ff2_y, bend_x, ff2_y)
            c.line(bend_x, ff1_y, bend_x, ff2_y)
            c.line(bend_x, champ_y, center_x + CENTER_SLOT_W, champ_y)

        # Champion trophy icon (small gold circle below championship)
        trophy_y = champ_y - SLOT_H - 16
        c.setFillColor(C_CHAMP_BG)
        c.setStrokeColor(C_CHAMP_BD)
        c.setLineWidth(0.5)
        c.roundRect(center_x + 10, trophy_y, CENTER_SLOT_W - 20, 14, 3, fill=1, stroke=1)
        c.setFont("Helvetica-Bold", 6)
        c.setFillColor(C_GOLD)
        c.drawCentredString(center_x + CENTER_SLOT_W / 2, trophy_y + 4, f"CHAMPION: {champion}")

    # ── Footer ──
    c.setFont("Helvetica", 4.5)
    c.setFillColor(C_SOFT)
    c.drawCentredString(
        width / 2, 8,
        f"Generated from {N_SIMS:,} Monte Carlo simulations | NCAA Men's Basketball Tournament 2026"
    )

    c.save()
    print(f"  Written: {output_path}")


# ── Main ─────────────────────────────────────────────────────────────
def main():
    print("=" * 60)
    print("  NCAA Bracket -- 1M Monte Carlo -> 3 Most Likely Brackets")
    print("=" * 60)

    features_path = nc.NCAAB_CURRENT_TEAM_FEATURES_CSV
    meta_path = nc.NCAAB_CURRENT_META_JSON

    if not features_path.exists() or not meta_path.exists():
        print("ERROR: Missing projection data. Run the projection pipeline first.")
        sys.exit(1)

    projected = pd.read_csv(features_path)
    projected = projected[projected["region"].notna()].reset_index(drop=True)
    with open(meta_path) as f:
        meta = json.load(f)

    print(f"Loaded {len(projected)} tournament teams\n")

    champ_slot_wins, champ_counts, info = run_simulations(projected, meta, n_sims=N_SIMS)
    print()

    top3 = sorted(champ_counts.items(), key=lambda x: -x[1])[:3]
    name_map = info["team_name_map"]
    seed_map = info["team_seed_map"]

    # ── Bracket 1: Aggressive (but plausible) upsets ──────────────────
    print("\nBuilding upset bracket (threshold >= 35% model prob) ...")
    games_upset = build_upset_bracket(info, upset_threshold=0.35)
    n_upsets_u = sum(1 for g in games_upset if g.get("is_upset"))
    champ_g = next((g for g in games_upset if g["round"] == "National Championship"), None)
    champ_label = champ_g["winner"] if champ_g else "?"
    print(f"  Upset bracket champion: {champ_label}  ({n_upsets_u} upsets)")

    render_bracket_pdf(
        games_upset,
        "Upset Bracket",
        f"Every underdog with >= 35% model win probability wins | {n_upsets_u} upsets",
        OUTPUT_DIR / "bracket_1.pdf",
    )

    # ── Brackets 2 & 3: Arizona (#2) and Michigan (#3) most-likely paths
    print("\nBuilding most-likely-path brackets for #2 and #3 champions ...")
    for rank, (champ_id, count) in [(2, top3[1]), (3, top3[2])]:
        champ_name = name_map.get(champ_id, "?")
        champ_seed = seed_map.get(champ_id, "?")
        pct = count / N_SIMS * 100

        print(f"\n  #{rank}: ({champ_seed}) {champ_name} -- {pct:.2f}% ({count:,} sims)")

        slot_wins = champ_slot_wins[champ_id]
        games = build_most_likely_bracket(slot_wins, count, info)

        n_upsets = sum(1 for g in games if g.get("is_upset"))
        print(f"       {n_upsets} upsets in most likely path")

        title = f"Most Likely Bracket #{rank}"
        subtitle = (
            f"Most probable path when ({champ_seed}) {champ_name} wins it all "
            f"-- {pct:.2f}% of {N_SIMS:,} simulations"
        )

        render_bracket_pdf(games, title, subtitle, OUTPUT_DIR / f"bracket_{rank}.pdf")

    print(f"\nAll 3 PDFs saved to {OUTPUT_DIR}/")

    # Also open them
    import subprocess
    for i in range(1, 4):
        subprocess.Popen(["open", str(OUTPUT_DIR / f"bracket_{i}.pdf")])


if __name__ == "__main__":
    main()
