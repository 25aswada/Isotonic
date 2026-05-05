"""
server.py — FastAPI backend for Isotonic.
Run:  uvicorn server:app --reload --port 8000
Open: http://localhost:8000
"""
from __future__ import annotations
import asyncio, json, logging, math, os, re, subprocess, sys, threading, time
from collections import deque
from datetime import datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import requests
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
from PIL import Image, UnidentifiedImageError

ROOT = Path(__file__).parent
os.chdir(ROOT)
sys.path.insert(0, str(ROOT))
import config

FRONTEND_DIST = ROOT / "frontend" / "dist"

logger = logging.getLogger("server")
logging.basicConfig(level=logging.INFO, format="%(levelname)s  %(name)s  %(message)s")

app = FastAPI(title="Isotonic", docs_url="/docs")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_MODEL: tuple = (None, None, None)
_NCAAB_MODEL: Any = None
_API_CACHE: dict[tuple[Any, ...], dict[str, Any]] = {}
_API_CACHE_LOCK = threading.Lock()
_PROB_HISTORY: dict[str, list[dict]] = {}   # game_id -> [{ts, model_home, model_away, market_home, market_away, home_score, away_score, period, clock}]
_PROB_HISTORY_LOCK = threading.Lock()
_PROB_HISTORY_MAX = 3600                     # ~5h at 5s intervals
_MODEL_READY_CACHE: dict[str, Any] = {"mtime_ns": None, "df": None}
_MODEL_READY_CACHE_LOCK = threading.Lock()
_NBA_TODAY_FEATURES_LAST_GOOD: dict[str, Any] = {"df": pd.DataFrame(), "updated_at": None}
_NBA_TODAY_FEATURES_LAST_GOOD_LOCK = threading.Lock()

_UPDATE_JOB: dict[str, Any] = {"status": "idle", "log": [], "started_at": None, "finished_at": None}
_UPDATE_JOB_LOCK = threading.Lock()

LIVE_CACHE_TTL_SECONDS   = 3     # tighten live refresh so score/clock/play text update faster
PICKS_CACHE_TTL_SECONDS  = 120   # picks change rarely; refresh every ~90s in bg thread
STATIC_CACHE_TTL_SECONDS = 300   # summary / teams / bracket rarely change
NCAAB_LOGO_CACHE_TTL_SECONDS = 86400
NCAAB_LOGO_FILE_CACHE_DIR = ROOT / "data" / "ncaab" / "logo_cache"
NCAAB_LOGO_REQ_VERSION_HINTS = ("202603120",)

_NCAAB_LOGO_ALIAS_KEYS = {
    "uconn": "connecticut",
    "ncsu": "ncstate",
    "unc": "northcarolina",
    "uncw": "uncwilmington",
    "gmu": "georgemason",
    "okst": "oklahomast",
    "okstate": "oklahomast",
    "sfa": "stephenfaustin",
    "stjohns": "stjohns",
    "olemiss": "olemiss",
    "how": "howard",
    "wich": "wichitast",
    "usa": "southalabama",
    "stmn": "stthomasmn",
    "uci": "ucirvine",
    "gonz": "gonzaga",
    "tlsa": "tulsa",
}

@app.on_event("startup")
def _startup():
    global _MODEL, _NCAAB_MODEL
    try:
        from src.model import load_model
        _MODEL = load_model()
        logger.info("NBA model loaded OK")
    except Exception as e:
        logger.warning("NBA model not loaded: %s", e)
    try:
        from src.ncaab_model import load_model as load_ncaab_model
        _NCAAB_MODEL = load_ncaab_model()
        logger.info("NCAAB model loaded OK")
    except Exception as e:
        logger.warning("NCAAB model not loaded: %s", e)
    # Kick off background cache warmer and pre-warm in a daemon thread so the
    # server is responsive immediately — first-ever requests are still fast.
    threading.Thread(target=_bg_cache_warmer, daemon=True, name="bg-cache-warmer").start()
    threading.Thread(target=_bg_nightly_refresh, daemon=True, name="bg-nightly-refresh").start()
    try:
        from src.auto_paper_trader import start_auto_bet_loop
        start_auto_bet_loop()
    except Exception as e:
        logger.warning("Auto-bet loop not started: %s", e)

def _bg_nightly_refresh():
    """
    Background daemon that re-pulls the current season's game logs once per day
    at ~6am local time, then rebuilds model_ready.csv and clears the API cache.
    This keeps team records / standings current without a full retrain.
    """
    import time as _time
    REFRESH_HOUR = 6  # 6am local time

    def _do_refresh():
        logger.info("[nightly] Starting current-season data refresh...")
        import config as _cfg
        cur_season = _cfg.SEASONS[-1]
        for _fname in [f"game_logs_{cur_season}.csv", f"advanced_stats_{cur_season}.csv"]:
            _p = ROOT / "data" / "raw" / _fname
            if _p.exists():
                try:
                    os.remove(_p)
                    logger.info("[nightly] Removed stale cache: %s", _fname)
                except Exception as e:
                    logger.warning("[nightly] Could not remove %s: %s", _fname, e)

        out = subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "build_dataset.py")],
            capture_output=True, text=True, cwd=str(ROOT),
        )
        if out.returncode == 0:
            logger.info("[nightly] Dataset refresh complete.")
            with _API_CACHE_LOCK:
                _API_CACHE.clear()
            logger.info("[nightly] API cache cleared.")
        else:
            logger.warning("[nightly] Dataset refresh failed:\n%s", out.stdout[-2000:] + out.stderr[-2000:])

    last_refresh_date = None
    while True:
        now = datetime.now()
        today = now.date()
        if now.hour >= REFRESH_HOUR and last_refresh_date != today:
            last_refresh_date = today
            try:
                _do_refresh()
            except Exception as e:
                logger.warning("[nightly] Unhandled error: %s", e)
        _time.sleep(300)  # check every 5 min


def _bg_cache_warmer():
    """
    Background daemon that keeps the expensive endpoints warm.
    Runs immediately on startup (pre-warm) then loops every BG_REFRESH_SECONDS.
    Users always get a cached response; the slow external API calls happen here,
    not on their request.
    """
    import time as _time
    BG_LIVE_INTERVAL   = 5    # re-fetch live scores every 5 s for real-time chart
    BG_PICKS_INTERVAL  = 90   # re-fetch picks every 90 s
    last_live  = 0.0
    last_picks = 0.0

    def _warm_live():
        _force_cache_update(("api_live",), LIVE_CACHE_TTL_SECONDS, _fetch_live_payload)

    def _warm_ncaab_live():
        from src.ncaab_live_scores import fetch_ncaab_live_games
        _force_cache_update(("api_ncaab_live",), LIVE_CACHE_TTL_SECONDS, fetch_ncaab_live_games)

    def _warm_nba_matchup_inputs():
        from scripts.daily_predictions import get_todays_features
        from src.odds_collection import get_all_market_odds

        _force_cache_update(("nba_today_features",), PICKS_CACHE_TTL_SECONDS, get_todays_features)
        _force_cache_update(
            ("nba_market_odds",),
            PICKS_CACHE_TTL_SECONDS,
            lambda: get_all_market_odds(record_snapshot=False, snapshot_context="bg_warm_matchup"),
        )

    def _warm_picks():
        from src.predict import predict_batch, generate_recommendation_table
        def _run():
            features = _get_shared_nba_today_features()
            if features.empty:
                return {"date": str(__import__("datetime").datetime.utcnow().date()),
                        "games_analyzed": 0, "bets_found": 0, "avg_edge": 0,
                        "odds_sources": [], "picks": []}
            predictions = predict_batch(features)
            try:
                from src.injuries import apply_live_availability_adjustments
                predictions = apply_live_availability_adjustments(predictions)
            except Exception: pass
            odds_df = pd.DataFrame()
            sources = []
            try:
                odds_df = _get_shared_nba_market_odds()
                if not odds_df.empty:
                    if "kalshi_home_prob" in odds_df and odds_df["kalshi_home_prob"].notna().any(): sources.append("kalshi")
            except Exception: pass
            recs = generate_recommendation_table(predictions, odds_df if not odds_df.empty else None, edge_threshold=0.03)
            records = _df_to_records(recs)
            for r in records:
                r["game_story"] = _game_story(r)
            bets = [r for r in records if r.get("bet")]
            edges = [r["best_edge"] for r in records if r.get("best_edge") is not None]
            return {"date": str(__import__("datetime").datetime.utcnow().date()),
                    "games_analyzed": len(records), "bets_found": len(bets),
                    "avg_edge": round(float(np.mean(edges)) if edges else 0, 4),
                    "odds_sources": sources, "picks": records}
        _force_cache_update(("api_picks", 0.03), PICKS_CACHE_TTL_SECONDS, _run)

    def _warm_ncaab_picks():
        from src.ncaab_odds import get_all_ncaab_market_odds
        from src.ncaab_predict import predict_market_games, generate_market_recommendation_table
        def _run():
            odds_df = get_all_ncaab_market_odds()
            if odds_df.empty: return {"picks": [], "available": True}
            predictions = predict_market_games(odds_df)
            if predictions.empty: return {"picks": [], "available": True}
            recs = generate_market_recommendation_table(predictions, odds_df, edge_threshold=0.03)
            return {"picks": _df_to_records(recs), "available": True}
        _force_cache_update(("api_ncaab_picks", 0.03), PICKS_CACHE_TTL_SECONDS, _run)

    # Pre-warm everything on startup
    logger.info("BG warmer: pre-warming caches...")
    _warm_nba_matchup_inputs()
    _warm_live()
    _warm_ncaab_live()
    _warm_picks()
    _warm_ncaab_picks()
    last_live  = _time.monotonic()
    last_picks = _time.monotonic()
    logger.info("BG warmer: pre-warm complete.")

    while True:
        _time.sleep(5)
        now = _time.monotonic()
        if now - last_live >= BG_LIVE_INTERVAL:
            _warm_live()
            _warm_ncaab_live()
            last_live = now
        if now - last_picks >= BG_PICKS_INTERVAL:
            _warm_nba_matchup_inputs()
            _warm_picks()
            _warm_ncaab_picks()
            last_picks = now

# ── JSON helpers ─────────────────────────────────────────────────────────────
def _clean(v):
    if v is None: return None
    if isinstance(v, float):
        return None if (math.isnan(v) or math.isinf(v)) else round(v, 6)
    if isinstance(v, (np.floating,)):
        f = float(v)
        return None if (math.isnan(f) or math.isinf(f)) else round(f, 6)
    if isinstance(v, (np.integer,)):  return int(v)
    if isinstance(v, (np.bool_,)):    return bool(v)
    from datetime import date as _date, datetime as _dt
    if isinstance(v, _dt): return v.isoformat()
    if isinstance(v, _date): return v.isoformat()
    try:
        import pandas as _pd
        if _pd.isna(v): return None
        if isinstance(v, _pd.Timestamp): return v.isoformat()
    except Exception: pass
    if isinstance(v, dict):           return {k: _clean(vv) for k, vv in v.items()}
    if isinstance(v, list):           return [_clean(i) for i in v]
    return v

def _df_to_records(df):
    if df is None or df.empty: return []
    df2 = df.where(pd.notna(df), None)
    return [_clean(r) for r in df2.to_dict(orient="records")]


def _anchor_elo_history(history: list[dict[str, Any]], current_elo: Any) -> list[dict[str, Any]]:
    if not history:
        return history
    target = pd.to_numeric(pd.Series([current_elo]), errors="coerce").iloc[0]
    last = pd.to_numeric(pd.Series([history[-1].get("elo")]), errors="coerce").iloc[0]
    if pd.isna(target) or pd.isna(last):
        return history
    delta = float(target) - float(last)
    if abs(delta) < 0.05:
        return history
    anchored: list[dict[str, Any]] = []
    for entry in history:
        elo_value = pd.to_numeric(pd.Series([entry.get("elo")]), errors="coerce").iloc[0]
        if pd.isna(elo_value):
            anchored.append(dict(entry))
            continue
        anchored.append({
            **entry,
            "elo": round(float(elo_value) + delta, 1),
        })
    return anchored


# ── Matchup narrative builder ──────────────────────────────────────────
def _build_matchup_narrative(
    team_a: str, team_b: str,
    stats_a: dict, stats_b: dict,
    prob_a: float, prob_b: float,
    form_a: list | None = None, form_b: list | None = None,
    h2h_summary: dict | None = None,
    league: str = "nba",
) -> str:
    """Generate an analytical narrative explaining why the model favors one side.

    The goal is to read like a sports analyst's pre-game breakdown, not a stat
    sheet.  We identify the *story* of the matchup — what each team does well,
    where the mismatch lives, and what the underdog needs to do to win — then
    weave the numbers in as supporting evidence rather than leading with them.
    """

    def sf(d: dict, k: str, default: float = 0.0) -> float:
        v = d.get(k)
        if v is None:
            return default
        try:
            return float(v)
        except (TypeError, ValueError):
            return default

    fav, dog = (team_a, team_b) if prob_a >= prob_b else (team_b, team_a)
    fs, ds   = (stats_a, stats_b) if prob_a >= prob_b else (stats_b, stats_a)
    fp = max(prob_a, prob_b)

    # ── Pull every number we might reference ──
    fn,  dn  = sf(fs, "net_rtg"), sf(ds, "net_rtg")
    fo,  do_ = sf(fs, "off_rtg", 105), sf(ds, "off_rtg", 105)
    fd,  dd  = sf(fs, "def_rtg", 110), sf(ds, "def_rtg", 110)
    fe,  de  = sf(fs, "elo", 1500), sf(ds, "elo", 1500)
    fpace, dpace = sf(fs, "pace"), sf(ds, "pace")

    # Form data
    fav_form_wins, dog_form_wins = 0, 0
    fav_form_n, dog_form_n = 0, 0
    fav_avg_pts, dog_avg_pts = 0.0, 0.0
    fav_avg_opp, dog_avg_opp = 0.0, 0.0
    if form_a and form_b:
        ff = form_a if prob_a >= prob_b else form_b
        df_ = form_b if prob_a >= prob_b else form_a
        recent_f, recent_d = ff[-5:], df_[-5:]
        fav_form_n, dog_form_n = len(recent_f), len(recent_d)
        fav_form_wins = sum(1 for g in recent_f if g.get("win"))
        dog_form_wins = sum(1 for g in recent_d if g.get("win"))
        fav_avg_pts = sum(float(g.get("pts") or 0) for g in recent_f) / max(fav_form_n, 1)
        fav_avg_opp = sum(float(g.get("opp_pts") or 0) for g in recent_f) / max(fav_form_n, 1)
        dog_avg_pts = sum(float(g.get("pts") or 0) for g in recent_d) / max(dog_form_n, 1)
        dog_avg_opp = sum(float(g.get("opp_pts") or 0) for g in recent_d) / max(dog_form_n, 1)

    # NCAAB-specific
    fl10 = sf(fs, "last10_win_pct")
    dl10 = sf(ds, "last10_win_pct")
    flm  = sf(fs, "last10_margin")
    dlm  = sf(ds, "last10_margin")
    fsos = sf(fs, "sos")
    dsos = sf(ds, "sos")
    fseed = str(fs.get("seed") or "")
    dseed = str(ds.get("seed") or "")

    # H2H
    h2h_fav_w, h2h_dog_w, h2h_n = 0, 0, 0
    if h2h_summary:
        h2h_fav_w = h2h_summary.get("a_wins", 0) if prob_a >= prob_b else h2h_summary.get("b_wins", 0)
        h2h_dog_w = h2h_summary.get("b_wins", 0) if prob_a >= prob_b else h2h_summary.get("a_wins", 0)
        h2h_n = h2h_summary.get("games_played", 0)

    # ── Classify the matchup shape ──
    net_gap   = fn - dn
    off_gap   = fo - do_
    def_gap   = dd - fd          # positive = fav is better (lower def_rtg)
    elo_gap   = fe - de
    pace_gap  = fpace - dpace

    # Which side of the ball drives the favorite?
    off_story = abs(off_gap) > abs(def_gap) and off_gap > 2
    def_story = abs(def_gap) > abs(off_gap) and def_gap > 2
    both_story = off_gap > 2 and def_gap > 2

    # ── Build the narrative ──
    paragraphs: list[str] = []

    # --- Opening: frame the matchup shape ---
    if fp > 0.62:
        if both_story:
            paragraphs.append(
                f"This one is {fav}'s game to lose. They're better on both ends of the floor "
                f"and the model reflects that with a {fp*100:.0f}% win probability."
            )
        elif off_story:
            paragraphs.append(
                f"The model sees {fav} as the clear favorite at {fp*100:.0f}%, "
                f"and the case starts with their offense."
            )
        elif def_story:
            paragraphs.append(
                f"{fav} enters this matchup as a {fp*100:.0f}% favorite, "
                f"built largely on a defensive identity that {dog} will struggle to crack."
            )
        else:
            paragraphs.append(
                f"The model likes {fav} at {fp*100:.0f}% here — not because of one dominant trait, "
                f"but because they're simply a more complete team across the board."
            )
    elif fp > 0.54:
        paragraphs.append(
            f"This is a competitive matchup, but the model tilts toward {fav} at {fp*100:.0f}%. "
            f"The margin is slim, and the reasons are worth understanding."
        )
    else:
        paragraphs.append(
            f"Don't let the {fp*100:.0f}-{(1-fp)*100:.0f} line fool you — this is essentially a pick'em. "
            f"The model gives {fav} the slightest of nods, and here's why."
        )

    # --- Middle: the "why" — weave offense, defense, context together ---
    body_parts: list[str] = []

    if both_story:
        body_parts.append(
            f"On offense, {fav} creates high-quality looks at a rate of {fo:.1f} points "
            f"per 100 possessions — that's {off_gap:.1f} more than {dog}'s {do_:.1f}. "
            f"Then they flip the script on the other end, holding opponents to just {fd:.1f} "
            f"per 100 while {dog} gives up {dd:.1f}. When you're winning on both sides of "
            f"the ball like that, the net rating gap ({fn:+.1f} vs {dn:+.1f}) almost tells "
            f"the story by itself."
        )
    elif off_story:
        body_parts.append(
            f"{fav} scores at an elite clip — {fo:.1f} per 100 possessions, "
            f"compared to {dog}'s {do_:.1f}. That gap shows up in the flow of the game: "
            f"{fav} gets into their sets more efficiently, converts at a higher rate, "
            f"and puts constant pressure on the defense to keep up."
        )
        if def_gap > 0.5:
            body_parts.append(
                f"They're also not giving much back on the other end ({fd:.1f} def rating "
                f"vs {dd:.1f}), which means {dog} can't simply outscore them in a shootout."
            )
        elif def_gap < -1.5:
            body_parts.append(
                f"Where it gets interesting is defense — {dog} is actually the tighter unit "
                f"there ({dd:.1f} vs {fd:.1f}). If they can slow the pace and force {fav} "
                f"into tougher shots, this game gets closer than the headline number suggests."
            )
    elif def_story:
        body_parts.append(
            f"{fav}'s calling card is defense. They surrender just {fd:.1f} points per 100 "
            f"possessions while {dog} allows {dd:.1f} — that's a gap that shows up as extra "
            f"stops, transition chances, and demoralising runs in the second half."
        )
        if off_gap < -1.5:
            body_parts.append(
                f"Offensively, {dog} actually has a slight edge ({do_:.1f} vs {fo:.1f}), "
                f"which is why this isn't a blowout line. The question is whether {dog}'s "
                f"shot-making can overcome {fav}'s ability to take them out of rhythm."
            )
    else:
        # Balanced / small-edge matchup
        if net_gap > 2:
            body_parts.append(
                f"There's no single area where {fav} dominates, but they're a tick better "
                f"almost everywhere — offense ({fo:.1f} vs {do_:.1f}), defense ({fd:.1f} "
                f"vs {dd:.1f}), and the accumulated edge shows up in a net rating of "
                f"{fn:+.1f} compared to {dog}'s {dn:+.1f}."
            )
        else:
            body_parts.append(
                f"The efficiency profiles are nearly mirror images — {fav} at {fn:+.1f} "
                f"net rating, {dog} at {dn:+.1f}. The model's lean comes from subtler "
                f"signals in the matchup data rather than a glaring talent gap."
            )

    # Elo context (weave in, don't list)
    if elo_gap > 60:
        body_parts.append(
            f"Season-long Elo backs this up convincingly — {fav} sits at {fe:.0f} "
            f"while {dog} is at {de:.0f}, a gap that reflects months of accumulated results, "
            f"not just a recent hot streak."
        )
    elif abs(elo_gap) < 15 and fp > 0.55:
        body_parts.append(
            f"What's notable is that Elo actually has these two nearly level ({fe:.0f} vs "
            f"{de:.0f}), so the model's confidence isn't coming from raw résumé — it's "
            f"reading something in the specific matchup dynamics."
        )

    # Pace / tempo framing
    if abs(pace_gap) > 3 and fpace > 0 and dpace > 0:
        faster = fav if pace_gap > 0 else dog
        slower = dog if pace_gap > 0 else fav
        body_parts.append(
            f"Tempo could be a factor too — {faster} plays at a {max(fpace, dpace):.1f} pace "
            f"while {slower} prefers to grind at {min(fpace, dpace):.1f}. Whoever dictates "
            f"the speed of play has an advantage."
        )

    paragraphs.append(" ".join(body_parts))

    # --- Form / momentum ---
    form_parts: list[str] = []
    if league == "ncaab":
        if fl10 > 0 and dl10 > 0:
            if fl10 - dl10 > 0.2:
                form_parts.append(
                    f"{fav} is peaking at the right time, winning {fl10*100:.0f}% of their "
                    f"last ten by an average of {flm:+.1f} points. {dog} has cooled off to "
                    f"{dl10*100:.0f}% with a margin of {dlm:+.1f} — that kind of trend matters "
                    f"this deep into the season."
                )
            elif dl10 - fl10 > 0.15:
                form_parts.append(
                    f"Recent form is the one counterargument for {dog} — they've won "
                    f"{dl10*100:.0f}% of their last ten ({dlm:+.1f} margin) while {fav} "
                    f"has been a less convincing {fl10*100:.0f}% ({flm:+.1f}). If that "
                    f"momentum carries over, this could be tighter than expected."
                )
    elif fav_form_n >= 3 and dog_form_n >= 3:
        if fav_form_wins >= 4 and dog_form_wins <= 2:
            form_parts.append(
                f"The momentum story is clear: {fav} is {fav_form_wins}-{fav_form_n-fav_form_wins} "
                f"over their last five, averaging {fav_avg_pts:.0f} points while giving up "
                f"{fav_avg_opp:.0f}. {dog} is limping in at {dog_form_wins}-{dog_form_n-dog_form_wins}, "
                f"scoring {dog_avg_pts:.0f} and allowing {dog_avg_opp:.0f}. "
                f"Confidence and rhythm matter, and {fav} has both right now."
            )
        elif dog_form_wins >= 4 and fav_form_wins <= 2:
            form_parts.append(
                f"Here's the wrinkle: {dog} is actually rolling, going "
                f"{dog_form_wins}-{dog_form_n-dog_form_wins} recently and averaging "
                f"{dog_avg_pts:.0f} points, while {fav} has stumbled to "
                f"{fav_form_wins}-{fav_form_n-fav_form_wins}. Season-long numbers "
                f"favor {fav}, but form like that can carry a team past a paper disadvantage."
            )
        elif fav_form_wins >= 4:
            form_parts.append(
                f"{fav} brings real momentum into this one — {fav_form_wins}-{fav_form_n-fav_form_wins} "
                f"over their last five, averaging {fav_avg_pts:.0f} points on "
                f"{fav_avg_opp:.0f} allowed. They're playing with confidence."
            )
    if form_parts:
        paragraphs.append(" ".join(form_parts))

    # --- H2H & closing ---
    closing_parts: list[str] = []
    if h2h_n >= 3:
        if h2h_dog_w > h2h_fav_w:
            closing_parts.append(
                f"One thing working in {dog}'s favor: they've won {h2h_dog_w} of the last "
                f"{h2h_n} meetings between these two. Season stats say {fav}, but there's "
                f"something about this particular matchup that {dog} seems to figure out."
            )
        elif h2h_fav_w > h2h_dog_w + 1:
            closing_parts.append(
                f"{fav} also has history on their side, taking {h2h_fav_w} of the last "
                f"{h2h_n} head-to-head meetings. When these teams see each other, "
                f"the pattern holds."
            )

    # SOS context (NCAAB)
    if league == "ncaab" and abs(fsos - dsos) > 2:
        if fsos > dsos:
            closing_parts.append(
                f"It's also worth noting that {fav}'s numbers came against a tougher "
                f"schedule — their strength of schedule rates {fsos:.1f} vs {dog}'s {dsos:.1f}. "
                f"That means {fav}'s metrics are battle-tested, not stat-padded."
            )
        else:
            closing_parts.append(
                f"One caveat: {dog} played the harder schedule ({dsos:.1f} SOS vs {fsos:.1f}). "
                f"Their numbers don't look as shiny, but they were earned against tougher competition."
            )

    # Final "bottom line"
    if fp > 0.62:
        closing_parts.append(
            f"Bottom line: {fav} is the better team and should win this game. "
            f"For {dog} to pull it off, they'll need to play above their season standard "
            f"and hope {fav} has an off night."
        )
    elif fp > 0.54:
        closing_parts.append(
            f"Bottom line: {fav} has the edge, but this is the kind of game that "
            f"could easily go either way. A couple of key runs or a hot shooting quarter "
            f"could flip the script."
        )
    else:
        closing_parts.append(
            f"Bottom line: flip a coin. The model sees a hair of daylight for {fav}, "
            f"but this game will be decided by who plays better on the night, not who "
            f"has the better résumé."
        )

    if closing_parts:
        paragraphs.append(" ".join(closing_parts))

    return "\n\n".join(paragraphs)

def _ok(data):
    return JSONResponse(content=_clean(data))


def _cached_call(key: tuple[Any, ...], ttl_seconds: int, builder):
    """Return a cached value for a short TTL, serving stale on transient builder errors."""
    now = time.monotonic()
    stale_entry = None
    with _API_CACHE_LOCK:
        cached = _API_CACHE.get(key)
        if cached and cached["expires_at"] > now:
            return cached["value"]
        stale_entry = cached

    try:
        value = builder()
    except Exception:
        if stale_entry is not None:
            logger.warning("Serving stale cache for %s after refresh failure", key)
            return stale_entry["value"]
        raise

    expires_at = time.monotonic() + ttl_seconds
    with _API_CACHE_LOCK:
        _API_CACHE[key] = {
            "value": value,
            "expires_at": expires_at,
        }
    return value

def _force_cache_update(key: tuple, ttl_seconds: int, builder):
    """Like _cached_call but always rebuilds, ignoring existing TTL.
    Used by the background warmer so the cache never expires between refreshes."""
    try:
        value = builder()
    except Exception as e:
        logger.debug("force cache update failed for %s: %s", key, e)
        return
    expires_at = time.monotonic() + ttl_seconds
    with _API_CACHE_LOCK:
        _API_CACHE[key] = {"value": value, "expires_at": expires_at}


def _load_model_ready_df() -> pd.DataFrame:
    """Load model_ready.csv once per file version instead of on every request."""
    path = ROOT / config.MODEL_READY_CSV
    mtime_ns = path.stat().st_mtime_ns

    with _MODEL_READY_CACHE_LOCK:
        cached_df = _MODEL_READY_CACHE.get("df")
        if cached_df is not None and _MODEL_READY_CACHE.get("mtime_ns") == mtime_ns:
            return cached_df

    df = pd.read_csv(path)
    if "game_date" in df.columns:
        df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")

    with _MODEL_READY_CACHE_LOCK:
        _MODEL_READY_CACHE["df"] = df
        _MODEL_READY_CACHE["mtime_ns"] = mtime_ns
    return df


def _get_shared_nba_today_features() -> pd.DataFrame:
    from scripts.daily_predictions import get_todays_features

    features = _cached_call(("nba_today_features",), PICKS_CACHE_TTL_SECONDS, get_todays_features)
    if isinstance(features, pd.DataFrame) and not features.empty:
        with _NBA_TODAY_FEATURES_LAST_GOOD_LOCK:
            _NBA_TODAY_FEATURES_LAST_GOOD["df"] = features.copy()
            _NBA_TODAY_FEATURES_LAST_GOOD["updated_at"] = datetime.now(timezone.utc)
        return features

    with _NBA_TODAY_FEATURES_LAST_GOOD_LOCK:
        fallback = _NBA_TODAY_FEATURES_LAST_GOOD.get("df")
        if isinstance(fallback, pd.DataFrame) and not fallback.empty:
            return fallback.copy()
    return features


def _get_shared_nba_market_odds() -> pd.DataFrame:
    from src.odds_collection import get_all_market_odds

    return _cached_call(
        ("nba_market_odds",),
        PICKS_CACHE_TTL_SECONDS,
        lambda: get_all_market_odds(record_snapshot=False, snapshot_context="api_matchup_shared"),
    )


def _build_system_health_payload():
    model_loaded = _MODEL[0] is not None
    trained_at = None
    try:
        p = ROOT / "models" / "calibrated_model.joblib"
        if p.exists():
            trained_at = datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc).isoformat()
    except Exception:
        pass

    snap_age = snap_stale = None
    latest_snap = None
    try:
        snap = pd.read_csv(ROOT / config.MARKET_SNAPSHOTS_CSV)
        if "snapshot_at" in snap.columns:
            latest = pd.to_datetime(snap["snapshot_at"]).max()
            latest_snap = str(latest)
            age = (datetime.now(timezone.utc) - latest.tz_localize("UTC")).total_seconds()
            snap_age = int(age)
            snap_stale = age > config.MARKET_SNAPSHOT_TTL_SECONDS
    except Exception:
        pass

    paper_count = 0
    try:
        paper_count = len(pd.read_csv(ROOT / config.PAPER_TRADES_CSV))
    except Exception:
        pass

    alerts_24h = 0
    try:
        adf = pd.read_csv(ROOT / config.ALERTS_CSV)
        if "created_at" in adf.columns:
            cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=24)
            alerts_24h = int((pd.to_datetime(adf["created_at"], utc=True) > cutoff).sum())
    except Exception:
        pass

    return {
        "model_loaded": model_loaded,
        "ncaab_model_loaded": _NCAAB_MODEL is not None,
        "model_trained_at": trained_at,
        "latest_snapshot_at": latest_snap,
        "snapshot_age_seconds": snap_age,
        "snapshot_stale": snap_stale,
        "paper_trades_count": paper_count,
        "alerts_24h": alerts_24h,
    }


def _build_nba_picks_payload(edge_threshold: float = 0.03):
    from src.predict import generate_recommendation_table, predict_batch

    features = _get_shared_nba_today_features()
    if features.empty:
        return {
            "date": str(datetime.now(timezone.utc).date()),
            "games_analyzed": 0,
            "bets_found": 0,
            "avg_edge": 0,
            "odds_sources": [],
            "picks": [],
        }

    predictions = predict_batch(features)
    try:
        from src.injuries import apply_live_availability_adjustments

        predictions = apply_live_availability_adjustments(predictions)
    except Exception:
        pass

    odds_df = pd.DataFrame()
    sources = []
    try:
        odds_df = _get_shared_nba_market_odds()
        if not odds_df.empty:
            if "kalshi_home_prob" in odds_df and odds_df["kalshi_home_prob"].notna().any():
                sources.append("kalshi")
    except Exception:
        pass

    recs = generate_recommendation_table(
        predictions,
        odds_df if not odds_df.empty else None,
        edge_threshold=edge_threshold,
    )
    records = _df_to_records(recs)
    for r in records:
        r["game_story"] = _game_story(r)
    bets = [r for r in records if r.get("bet")]
    edges = [r["best_edge"] for r in records if r.get("best_edge") is not None]
    return {
        "date": str(datetime.now(timezone.utc).date()),
        "games_analyzed": len(records),
        "bets_found": len(bets),
        "avg_edge": round(float(np.mean(edges)) if edges else 0, 4),
        "odds_sources": sources,
        "picks": records,
    }

TEAM_COLORS = {
    "ATL":"#E03A3E","BOS":"#00C45A","BKN":"#BBBBBB","CHA":"#8B7FD4",
    "CHI":"#E8475F","CLE":"#FDBB30","DAL":"#4B9CD3","DEN":"#4FA8D5",
    "DET":"#E03A3E","GSW":"#4B90D9","HOU":"#E8475F","IND":"#FDBB30",
    "LAC":"#E03A3E","LAL":"#9B72CF","MEM":"#7B9FC4","MIA":"#F9A01B",
    "MIL":"#00C45A","MIN":"#4B90D9","NOP":"#4B90D9","NYK":"#F58426",
    "OKC":"#44AADD","ORL":"#3399DD","PHI":"#3A8FD4","PHX":"#8B7FD4",
    "POR":"#E03A3E","SAC":"#9966CC","SAS":"#CCCCCC","TOR":"#E8475F",
    "UTA":"#3A8FD4","WAS":"#E03A3E",
}
NBA_TEAMS = list(getattr(config, "NBA_TEAMS", list(TEAM_COLORS.keys())))


def _current_nba_season_label(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    start_year = current.year if current.month >= 7 else current.year - 1
    return f"{start_year}-{str(start_year + 1)[-2:]}"

def _game_story(row):
    bullets = []
    elo_diff = row.get("elo_diff") or 0
    if abs(elo_diff) >= 20:
        fav = row.get("home_team") if elo_diff > 0 else row.get("away_team")
        bullets.append(f"{fav} has the stronger Elo rating ({abs(elo_diff):.0f} pts).")
    rest = (row.get("home_rest_days") or 0) - (row.get("away_rest_days") or 0)
    if abs(rest) >= 1:
        fresher = row.get("home_team") if rest > 0 else row.get("away_team")
        bullets.append(f"{fresher} has a rest edge of {abs(rest):.0f} day(s).")
    return bullets[:3]


def _frontend_index_html() -> str:
    index_path = FRONTEND_DIST / "index.html"
    if index_path.exists():
        return index_path.read_text()
    return """
    <!DOCTYPE html>
    <html lang="en">
      <head>
        <meta charset="utf-8" />
        <meta name="viewport" content="width=device-width, initial-scale=1" />
        <title>Isotonic</title>
        <style>
          body { font-family: ui-sans-serif, system-ui, sans-serif; background:#07080c; color:#f4f6fb; margin:0; display:grid; place-items:center; min-height:100vh; }
          .card { max-width: 640px; padding: 32px; border:1px solid rgba(255,255,255,.12); border-radius: 20px; background: rgba(255,255,255,.04); }
          code { color:#b8c6ff; }
        </style>
      </head>
      <body>
        <div class="card">
          <h1>Frontend build not found</h1>
          <p>Build the React app with <code>cd frontend && npm install && npm run build</code>, then reload the server.</p>
        </div>
      </body>
    </html>
    """

# ── Routes ────────────────────────────────────────────────────────────────────
@app.get("/", response_class=HTMLResponse)
async def index():
    return _frontend_index_html()

# ── Today\'s Picks ─────────────────────────────────────────────────────────
@app.get("/api/picks")
async def get_picks(edge_threshold: float = 0.03):
    try:
        cache_key = ("api_picks", round(float(edge_threshold), 4))
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _cached_call(
                cache_key,
                PICKS_CACHE_TTL_SECONDS,
                lambda: _build_nba_picks_payload(edge_threshold),
            ),
        )
        return _ok(data)
    except Exception as e:
        logger.exception("Error in /api/picks"); raise HTTPException(500, detail=str(e))

# ── Live Games ────────────────────────────────────────────────────────────────
def _nudge_coinflip(groups: dict) -> dict:
    """When the model outputs 50/50, lean toward whichever side the market favors."""
    for section in ("in_progress", "upcoming", "final"):
        for g in groups.get(section, []):
            hp = g.get("pregame_home_prob") or g.get("home_win_prob")
            if hp is not None and abs(float(hp) - 0.5) < 0.005:
                kalshi_h = g.get("kalshi_home_prob")
                if kalshi_h is not None and abs(float(kalshi_h) - 0.5) > 0.005:
                    market_favors_home = float(kalshi_h) > 0.5
                else:
                    market_favors_home = True
                h_val = 0.51 if market_favors_home else 0.49
                a_val = 0.49 if market_favors_home else 0.51
                # Nudge all probability fields so the UI picks it up
                for hk in ("pregame_home_prob", "home_win_prob", "live_home_prob"):
                    if g.get(hk) is not None and abs(float(g[hk]) - 0.5) < 0.005:
                        g[hk] = h_val
                for ak in ("pregame_away_prob", "away_win_prob", "live_away_prob"):
                    if g.get(ak) is not None and abs(float(g[ak]) - 0.5) < 0.005:
                        g[ak] = a_val
                # Fix tied predicted scores
                ps_h = g.get("pred_home_score")
                ps_a = g.get("pred_away_score")
                if ps_h is not None and ps_a is not None and ps_h == ps_a:
                    if market_favors_home:
                        g["pred_home_score"] = ps_h + 1
                    else:
                        g["pred_away_score"] = ps_a + 1
    return groups


def _record_prob_snapshots(payload: dict):
    """Append a probability snapshot for each in-progress game."""
    ts = datetime.now(timezone.utc).isoformat()
    with _PROB_HISTORY_LOCK:
        for g in payload.get("in_progress", []):
            gid = str(g.get("game_id") or "")
            if not gid:
                continue
            snap = {
                "ts": ts,
                "model_home": g.get("live_home_prob") or g.get("home_win_prob"),
                "model_away": g.get("live_away_prob") or g.get("away_win_prob"),
                "market_home": g.get("kalshi_home_prob"),
                "market_away": g.get("kalshi_away_prob"),
                "home_score": g.get("home_score", 0),
                "away_score": g.get("away_score", 0),
                "period": g.get("period_label") or g.get("period"),
                "clock": g.get("clock_display") or g.get("clock"),
            }
            history = _PROB_HISTORY.setdefault(gid, [])
            history.append(snap)
            if len(history) > _PROB_HISTORY_MAX:
                _PROB_HISTORY[gid] = history[-_PROB_HISTORY_MAX:]


def _fetch_live_payload():
    from src.live_model import fetch_live_games, enrich_with_market_odds
    from src.live_play_feed import get_latest_play
    elo_ratings, pregame_probs = {}, {}
    try:
        elo_df = pd.read_csv(ROOT / config.ELO_CSV)
        h = elo_df[["home_team","home_elo","game_date"]].rename(columns={"home_team":"team","home_elo":"elo"})
        a = elo_df[["away_team","away_elo","game_date"]].rename(columns={"away_team":"team","away_elo":"elo"})
        elo_ratings = pd.concat([h, a]).sort_values("game_date").groupby("team")["elo"].last().to_dict()
    except Exception: pass
    try:
        from src.predict import predict_batch
        from src.injuries import apply_live_availability_adjustments
        f = _get_shared_nba_today_features()
        if not f.empty:
            p = predict_batch(f); p = apply_live_availability_adjustments(p)
            for _, row in p.iterrows():
                pregame_probs[(row["home_team"], row["away_team"])] = float(row["home_win_prob"])
    except Exception: pass
    # Build predicted scores for each upcoming/pregame game
    pred_scores: dict = {}
    try:
        from src.score_model import predict_nba_score
        f = _get_shared_nba_today_features()
        if not f.empty:
            for _, row in f.iterrows():
                ht = row.get("home_team"); at = row.get("away_team")
                if not ht or not at:
                    continue
                snap_home = {c[5:]: row[c] for c in row.index if c.startswith("home_") and c != "home_team"}
                snap_away = {c[5:]: row[c] for c in row.index if c.startswith("away_") and c != "away_team"}
                _sc = predict_nba_score(snap_home, snap_away)
                if _sc:
                    ph = float(pregame_probs.get((ht, at), 0.5))
                    pa = 1.0 - ph
                    total = _sc[0] + _sc[1]
                    spread_b = 6.0 * math.log(max(pa, 0.01) / max(ph, 0.01))
                    pred_scores[(ht, at)] = (round((total - spread_b) / 2), round((total + spread_b) / 2))
    except Exception:
        pass

    live_df = fetch_live_games(elo_ratings=elo_ratings, pregame_probs=pregame_probs)
    try:
        from src.data_collection import get_todays_games
        todays_games = get_todays_games()
        if not todays_games.empty:
            existing_keys = set()
            if not live_df.empty:
                existing_keys = {
                    (str(row.get("home_team") or ""), str(row.get("away_team") or ""))
                    for row in live_df.to_dict("records")
                }

            missing_rows: list[dict[str, Any]] = []
            for game in todays_games.to_dict("records"):
                key = (str(game.get("home_team") or ""), str(game.get("away_team") or ""))
                if key in existing_keys:
                    continue

                home_team = key[0]
                away_team = key[1]
                pregame_prob = pregame_probs.get((home_team, away_team)) if pregame_probs else None
                missing_rows.append({
                    "pregame_home_prob": round(float(pregame_prob), 4) if pregame_prob is not None else None,
                    "game_id": str(game.get("game_id") or ""),
                    "home_team": home_team,
                    "away_team": away_team,
                    "home_score": 0,
                    "away_score": 0,
                    "period": 0,
                    "clock": "",
                    "seconds_remaining": float(48 * 60),
                    "game_status": int(game.get("game_status") or 1),
                    "game_status_text": str(game.get("game_status_text") or ""),
                    "home_elo": float(elo_ratings.get(home_team, config.ELO_BASE)),
                    "away_elo": float(elo_ratings.get(away_team, config.ELO_BASE)),
                    "live_home_prob": round(float(pregame_prob), 4) if pregame_prob is not None else 0.5,
                    "live_away_prob": round(float(1.0 - pregame_prob), 4) if pregame_prob is not None else 0.5,
                    "tipoff_utc": game.get("tipoff_utc"),
                })

            if missing_rows:
                live_df = pd.concat([live_df, pd.DataFrame(missing_rows)], ignore_index=True)
    except Exception:
        pass
    if not live_df.empty:
        try:
            odds_df = _get_shared_nba_market_odds()
            live_df = enrich_with_market_odds(live_df, odds_df)
        except Exception: pass
        # Attach predicted scores
        if pred_scores:
            live_df["pred_home_score"] = live_df.apply(
                lambda r: pred_scores.get((r["home_team"], r["away_team"]), (None, None))[0], axis=1)
            live_df["pred_away_score"] = live_df.apply(
                lambda r: pred_scores.get((r["home_team"], r["away_team"]), (None, None))[1], axis=1)
    def _group(df, status):
        if df.empty or "game_status" not in df.columns: return []
        sub = df[df["game_status"] == status].copy()
        records = _df_to_records(sub)
        for r in records:
            cr = r.get("clock","") or ""
            m = re.match(r"PT(\d+)M([\d.]+)S", cr)
            r["clock_display"] = f"{int(m.group(1))}:{int(float(m.group(2))):02d}" if m else cr
            p = r.get("period",0) or 0
            r["period_label"] = f"OT{p-4}" if p > 4 else (f"Q{p}" if p else "")
            if status == 2:
                play = get_latest_play("nba", r.get("game_id"))
                if play:
                    r["latest_play"] = _clean(play)
        return records
    result = {"fetched_at": datetime.now(timezone.utc).isoformat(),
              "in_progress": _group(live_df, 2), "upcoming": _group(live_df, 1), "final": _group(live_df, 3)}
    result = _nudge_coinflip(result)
    _record_prob_snapshots(result)
    return result

@app.get("/api/live")
async def get_live():
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _cached_call(("api_live",), LIVE_CACHE_TTL_SECONDS, _fetch_live_payload),
        )
        return _ok(data)
    except Exception as e:
        logger.exception("Error in /api/live"); raise HTTPException(500, detail=str(e))

@app.get("/api/live/stream")
async def live_stream(request: Request):
    async def gen():
        while True:
            if await request.is_disconnected(): break
            try:
                data = await asyncio.get_event_loop().run_in_executor(
                    None,
                    lambda: _cached_call(("api_live",), LIVE_CACHE_TTL_SECONDS, _fetch_live_payload),
                )
                yield f"event: games\ndata: {json.dumps(_clean(data))}\n\n"
            except Exception as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
            yield f"event: heartbeat\ndata: {json.dumps({'ts': datetime.now(timezone.utc).isoformat()})}\n\n"
            await asyncio.sleep(config.LIVE_POLL_SECONDS)
    return StreamingResponse(gen(), media_type="text/event-stream",
                             headers={"Cache-Control":"no-cache","X-Accel-Buffering":"no"})


@app.get("/api/live/game/{game_id}")
async def live_game_detail(game_id: str):
    """Return current game data + probability history for a single game."""
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _cached_call(("api_live",), LIVE_CACHE_TTL_SECONDS, _fetch_live_payload),
        )
    except Exception as e:
        raise HTTPException(500, detail=str(e))
    game = None
    for bucket in ("in_progress", "upcoming", "final"):
        for g in data.get(bucket, []):
            if str(g.get("game_id")) == game_id:
                game = g
                break
        if game:
            break
    if not game:
        raise HTTPException(404, detail="Game not found")
    with _PROB_HISTORY_LOCK:
        history = list(_PROB_HISTORY.get(game_id, []))
    return _ok({"game": _clean(game), "history": history})


@app.get("/api/ncaab/live/game/{game_id}")
async def ncaab_live_game_detail(game_id: str):
    """Return current NCAAB game data + probability history."""
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _cached_call(("api_ncaab_live",), LIVE_CACHE_TTL_SECONDS, _fetch_ncaab_live_payload),
        )
        data = _nudge_coinflip(data)
    except Exception as e:
        raise HTTPException(500, detail=str(e))
    game = None
    for bucket in ("in_progress", "upcoming", "final"):
        for g in data.get(bucket, []):
            if str(g.get("game_id")) == game_id:
                game = g
                break
        if game:
            break
    if not game:
        raise HTTPException(404, detail="Game not found")
    with _PROB_HISTORY_LOCK:
        history = list(_PROB_HISTORY.get(game_id, []))
    return _ok({"game": _clean(game), "history": history})


# ── Matchup Lab ───────────────────────────────────────────────────────────────
@app.get("/api/matchup/teams")
async def matchup_teams():
    return _ok({"teams": sorted(NBA_TEAMS)})

@app.get("/api/matchup")
async def get_matchup(team_a: str = "BOS", team_b: str = "LAL"):
    def _run():
        ta, tb = team_a.upper(), team_b.upper()
        df = _load_model_ready_df()
        team_a_games = df[(df["home_team"] == ta) | (df["away_team"] == ta)].sort_values("game_date")
        team_b_games = df[(df["home_team"] == tb) | (df["away_team"] == tb)].sort_values("game_date")

        def _snap(team_games, team):
            home = team_games[team_games["home_team"] == team]
            away = team_games[team_games["away_team"] == team]
            if home.empty and away.empty:
                return {}
            if home.empty:
                row, prefix = away.iloc[-1], "away_"
            elif away.empty:
                row, prefix = home.iloc[-1], "home_"
            else:
                lh, la = home.iloc[-1], away.iloc[-1]
                row, prefix = (lh, "home_") if lh["game_date"] >= la["game_date"] else (la, "away_")
            snap = {}
            for col in row.index:
                key = col[len(prefix):] if col.startswith(prefix) else col
                snap[key] = row[col]
            return {k: _clean(v) for k, v in snap.items() if isinstance(v, (int, float, type(None), np.floating, np.integer))}

        snap_a, snap_b = _snap(team_a_games, ta), _snap(team_b_games, tb)
        elo_a = float(snap_a.get("elo") or 1500)
        elo_b = float(snap_b.get("elo") or 1500)
        pred_a = 1 / (1 + 10 ** (-(elo_a - elo_b) / 400))
        prediction_source = "elo_fallback"
        try:
            if _MODEL[0] is not None:
                from src.predict import predict_batch
                from src.injuries import apply_live_availability_adjustments

                todays = _get_shared_nba_today_features()
                if not todays.empty:
                    exact = todays[(todays["away_team"] == ta) & (todays["home_team"] == tb)]
                    if not exact.empty:
                        matchup_pred = predict_batch(exact.head(1))
                        matchup_pred = apply_live_availability_adjustments(matchup_pred)
                        pred_a = float(matchup_pred.iloc[0]["away_win_prob"])
                        prediction_source = "full_model"
        except Exception: pass
        market_odds = {}
        try:
            odds_df = _get_shared_nba_market_odds()
            if not odds_df.empty:
                mask = (((odds_df["away_team"]==ta) & (odds_df["home_team"]==tb)) |
                        ((odds_df["away_team"]==tb) & (odds_df["home_team"]==ta)))
                match = odds_df[mask]
                if not match.empty:
                    r = match.iloc[0]; flip = r["away_team"] == tb
                    market_odds = {
                        "kalshi_a_prob":      _clean(r.get("kalshi_away_prob" if not flip else "kalshi_home_prob")),
                        "kalshi_b_prob":      _clean(r.get("kalshi_home_prob" if not flip else "kalshi_away_prob")),
                    }
        except Exception: pass
        def _form(team_games, team):
            games = team_games.tail(10)
            out = []
            for _, row in games.iterrows():
                ih = row["home_team"] == team
                pts = row.get("home_pts" if ih else "away_pts"); opp = row.get("away_pts" if ih else "home_pts")
                win = int(row.get("home_win",0)) if ih else int(1 - row.get("home_win",0))
                out.append({"game_date": str(row["game_date"])[:10], "win": win,
                            "pts": _clean(pts), "opp_pts": _clean(opp)})
            return out
        h2h_df = df[(((df["home_team"]==ta)&(df["away_team"]==tb))|
                     ((df["home_team"]==tb)&(df["away_team"]==ta)))].sort_values("game_date").tail(10)
        h2h = []
        for _, row in h2h_df.iterrows():
            winner = row["home_team"] if row.get("home_win",0)==1 else row["away_team"]
            h2h.append({"game_date":str(row["game_date"])[:10],"home_team":row["home_team"],
                        "away_team":row["away_team"],"home_pts":_clean(row.get("home_pts")),
                        "away_pts":_clean(row.get("away_pts")),"winner":winner})
        def _elo_hist(team_games, team):
            h = team_games[team_games["home_team"] == team][["game_date","home_elo"]].rename(columns={"home_elo":"elo"})
            a = team_games[team_games["away_team"] == team][["game_date","away_elo"]].rename(columns={"away_elo":"elo"})
            combined = pd.concat([h, a]).sort_values("game_date").tail(82)
            return [{"game_date":str(r["game_date"])[:10],"elo":_clean(r["elo"])} for _,r in combined.iterrows()]
        fav = ta if pred_a >= 0.5 else tb
        fav_p = pred_a if pred_a >= 0.5 else (1 - pred_a)
        conf = "Strong" if fav_p >= 0.65 else "Moderate" if fav_p >= 0.55 else "Slight"
        # Predicted score: ML regression model, constrained so winner matches win probability
        try:
            from src.score_model import predict_nba_score
            _sc = predict_nba_score(snap_a, snap_b)
            if _sc:
                _pa = float(pred_a)
                _pb = 1.0 - _pa
                _total = _sc[0] + _sc[1]
                # Spread derived from win probability (6 pt/logit unit for NBA)
                _spread_b = 6.0 * math.log(max(_pb, 0.01) / max(_pa, 0.01))
                pred_score_a = round((_total - _spread_b) / 2)
                pred_score_b = round((_total + _spread_b) / 2)
            else:
                pred_score_a, pred_score_b = None, None
        except Exception:
            pred_score_a, pred_score_b = None, None
        form_a_out = _form(team_a_games, ta)
        form_b_out = _form(team_b_games, tb)
        h2h_summ = {"a_wins":sum(1 for g in h2h if g["winner"]==ta),
                     "b_wins":sum(1 for g in h2h if g["winner"]==tb),"games_played":len(h2h)}
        narrative = _build_matchup_narrative(
            ta, tb, snap_a, snap_b, pred_a, 1 - pred_a,
            form_a=form_a_out, form_b=form_b_out,
            h2h_summary=h2h_summ, league="nba",
        )
        return {"team_a":ta,"team_b":tb,"pred_prob_a":round(pred_a,4),"pred_prob_b":round(1-pred_a,4),
                "favorite":fav,"favorite_prob":round(fav_p,4),"confidence_label":conf,
                "prediction_source": prediction_source,
                "pred_score_a": pred_score_a, "pred_score_b": pred_score_b,
                "narrative": narrative,
                "market_odds":market_odds,"stats_a":snap_a,"stats_b":snap_b,
                "form_a":form_a_out,"form_b":form_b_out,"h2h":h2h,
                "h2h_summary":h2h_summ,
                "elo_history_a":_elo_hist(team_a_games, ta),"elo_history_b":_elo_hist(team_b_games, tb)}
    try:
        cache_key = ("api_matchup", team_a.upper(), team_b.upper())
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _cached_call(cache_key, 300, _run)
        )
        return _ok(data)
    except Exception as e:
        logger.exception("Error in /api/matchup"); raise HTTPException(500, detail=str(e))

# ── Paper Trader ─────────────────────────────────────────────────────────────
def _build_results_from_game_logs() -> pd.DataFrame:
    """Build a reliable results DataFrame from raw game logs (final scores only)."""
    from src.data_collection import parse_game_logs_to_matchups
    import glob as _glob
    log_files = sorted(_glob.glob(str(ROOT / "data" / "raw" / "game_logs_*.csv")))
    if not log_files:
        return pd.read_csv(ROOT / config.MODEL_READY_CSV)
    parts = []
    for f in log_files:
        try:
            parts.append(pd.read_csv(f, low_memory=False))
        except Exception:
            pass
    if not parts:
        return pd.read_csv(ROOT / config.MODEL_READY_CSV)
    raw = pd.concat(parts, ignore_index=True)
    results = parse_game_logs_to_matchups(raw)
    # Drop rows with partial/live scores (real NBA games always finish above 60 pts)
    results = results[
        pd.to_numeric(results["home_pts"], errors="coerce").fillna(0) >= 60
    ]
    return results


def _load_trades_with_sync():
    from src.paper_trading import load_paper_trades, sync_paper_trades_with_results
    try:
        results_df = _build_results_from_game_logs()
        return sync_paper_trades_with_results(results_df)
    except Exception:
        return load_paper_trades()


def _load_combo_trades_with_sync():
    from src.nba_combos import load_combo_trades, sync_combo_trades_with_results
    try:
        results_df = _build_results_from_game_logs()
        return sync_combo_trades_with_results(results_df)
    except Exception:
        return load_combo_trades()


def _parse_source_list(sources: Any) -> list[str]:
    allowed_sources = {"kalshi"}
    if isinstance(sources, str):
        parsed = [part.strip().lower() for part in sources.split(",") if part.strip()]
        filtered = [part for part in parsed if part in allowed_sources]
        return filtered or ["kalshi"]
    if isinstance(sources, list):
        parsed = [str(part).strip().lower() for part in sources if str(part).strip()]
        filtered = [part for part in parsed if part in allowed_sources]
        return filtered or ["kalshi"]
    return ["kalshi"]


def _ensure_candidate_ids(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df
    candidates = df.copy()
    if "candidate_id" not in candidates.columns:
        if "trade_id" in candidates.columns:
            candidates["candidate_id"] = candidates["trade_id"].astype(str)
        else:
            candidates["candidate_id"] = candidates.index.astype(str)
    return candidates


def _build_nba_paper_candidates_df(edge_threshold: float = 0.03, sources: Any = "kalshi") -> pd.DataFrame:
    from scripts.daily_predictions import get_todays_features
    from src.odds_collection import get_all_market_odds
    from src.paper_trading import build_paper_trade_candidates, compute_live_paper_bankroll, load_paper_trades
    from src.predict import generate_recommendation_table, predict_batch

    trades = load_paper_trades()
    bankroll = compute_live_paper_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
    features = get_todays_features()
    if features.empty:
        return pd.DataFrame()

    predictions = predict_batch(features)
    try:
        from src.injuries import apply_live_availability_adjustments

        predictions = apply_live_availability_adjustments(predictions)
    except Exception:
        pass

    odds_df = get_all_market_odds(snapshot_context="api_candidates")
    recs = generate_recommendation_table(predictions, odds_df, edge_threshold=edge_threshold)
    candidates = build_paper_trade_candidates(
        recs,
        bankroll=bankroll["available_cash"],
        edge_threshold=edge_threshold,
        sources=_parse_source_list(sources),
    )
    return _ensure_candidate_ids(candidates)


def _build_ncaab_paper_candidates_df(edge_threshold: float = 0.03, sources: Any = "kalshi") -> pd.DataFrame:
    from src.ncaab_odds import get_all_ncaab_market_odds
    from src.ncaab_availability import apply_ncaab_availability_adjustments
    from src.ncaab_paper_trading import build_ncaab_paper_trade_candidates, compute_ncaab_paper_bankroll, load_ncaab_paper_trades
    from src.ncaab_predict import generate_market_recommendation_table, predict_market_games

    trades = load_ncaab_paper_trades()
    bankroll = compute_ncaab_paper_bankroll(trades)
    odds_df = get_all_ncaab_market_odds()
    if odds_df.empty:
        return pd.DataFrame()

    predictions = predict_market_games(odds_df)
    predictions = apply_ncaab_availability_adjustments(
        predictions,
        team_a_col="home_team",
        team_b_col="away_team",
        prob_a_col="home_win_prob",
        prob_b_col="away_win_prob",
        prefix_a="home",
        prefix_b="away",
    )
    recs = generate_market_recommendation_table(predictions, odds_df, edge_threshold=edge_threshold)
    candidates = build_ncaab_paper_trade_candidates(
        recs,
        bankroll=bankroll["available_cash"],
        edge_threshold=edge_threshold,
        sources=_parse_source_list(sources),
    )
    return _ensure_candidate_ids(candidates)

@app.get("/api/paper-trader/state")
async def paper_state():
    def _run():
        from src.paper_trading import compute_live_paper_bankroll
        trades = _load_trades_with_sync()
        bankroll = compute_live_paper_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
        status = trades["status"].fillna("open") if not trades.empty and "status" in trades.columns else pd.Series(dtype=str)
        return {"bankroll": {k:_clean(v) for k,v in bankroll.items()},
                "open_count": int((status=="open").sum()),
                "settled_count": int((status=="settled").sum())}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e: raise HTTPException(500, detail=str(e))

@app.get("/api/paper-trader/candidates")
async def paper_candidates(edge_threshold: float = 0.03, sources: str = "kalshi"):
    def _run():
        candidates = _build_nba_paper_candidates_df(edge_threshold=edge_threshold, sources=sources)
        return {"candidates": _df_to_records(candidates)}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/paper-trader/candidates"); raise HTTPException(500, detail=str(e))

@app.post("/api/paper-trader/log-trades")
async def log_trades(edge_threshold: float = 0.03, sources: str = "kalshi"):
    def _run():
        from src.paper_trading import append_paper_trades

        candidates = _build_nba_paper_candidates_df(edge_threshold=edge_threshold, sources=sources)
        if candidates.empty: return {"logged": 0, "message": "No candidates meet threshold"}
        append_paper_trades(candidates)
        return {"logged": len(candidates), "message": f"Logged {len(candidates)} trades"}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/paper-trader/log-trades"); raise HTTPException(500, detail=str(e))


@app.post("/api/paper-trader/custom-trade")
async def custom_paper_trade(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    
    home_team = str(payload.get("home_team", "")).strip()
    away_team = str(payload.get("away_team", "")).strip()
    selected_team = str(payload.get("selected_team", "")).strip()
    custom_stake = float(payload.get("custom_stake", 0))
    market_source = str(payload.get("market_source", "kalshi")).strip()
    
    if not all([home_team, away_team, selected_team]):
        raise HTTPException(400, detail="home_team, away_team, and selected_team are required")
    if custom_stake <= 0:
        raise HTTPException(400, detail="custom_stake must be > 0")
    if selected_team not in [home_team, away_team]:
        raise HTTPException(400, detail="selected_team must be either home_team or away_team")
    if market_source not in ["kalshi", "polymarket"]:
        raise HTTPException(400, detail="market_source must be 'kalshi' or 'polymarket'")
    
    def _run():
        from src.paper_trading import append_paper_trades, build_custom_paper_trade, compute_live_paper_bankroll, load_paper_trades
        trades = load_paper_trades()
        bankroll = compute_live_paper_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
        
        custom_trade = build_custom_paper_trade(
            home_team=home_team,
            away_team=away_team,
            selected_team=selected_team,
            custom_stake=custom_stake,
            market_source=market_source,
            bankroll_snapshot=bankroll["available_cash"],
        )
        
        if custom_trade is None:
            raise HTTPException(400, detail="Unable to build custom trade - market data may be unavailable")
        
        custom_df = pd.DataFrame([custom_trade])
        append_paper_trades(custom_df)
        
        return {
            "logged": 1,
            "message": f"Custom trade placed: ${float(custom_trade.get('stake') or 0):.2f} on {selected_team}",
            "trade_id": custom_trade.get("trade_id"),
            "trade": _clean(custom_trade),
        }
    
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/paper-trader/custom-trade"); raise HTTPException(500, detail=str(e))


@app.post("/api/paper-trader/manual-preview")
async def paper_trade_preview(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    home_team = str(payload.get("home_team", "")).strip()
    away_team = str(payload.get("away_team", "")).strip()
    selected_team = str(payload.get("selected_team", "")).strip()
    custom_stake = float(payload.get("custom_stake", 0))
    market_source = str(payload.get("market_source", "kalshi")).strip()

    if not all([home_team, away_team, selected_team]):
        raise HTTPException(400, detail="home_team, away_team, and selected_team are required")
    if custom_stake <= 0:
        raise HTTPException(400, detail="custom_stake must be > 0")

    def _run():
        from src.paper_trading import build_custom_paper_trade, compute_live_paper_bankroll, load_paper_trades
        trades = load_paper_trades()
        bankroll = compute_live_paper_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
        trade = build_custom_paper_trade(
            home_team=home_team,
            away_team=away_team,
            selected_team=selected_team,
            custom_stake=custom_stake,
            market_source=market_source,
            bankroll_snapshot=bankroll["available_cash"],
        )
        if trade is None:
            raise HTTPException(400, detail="Unable to price manual trade")
        return {"trade": _clean(trade)}

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /api/paper-trader/manual-preview"); raise HTTPException(500, detail=str(e))


@app.post("/api/paper-trader/trades")
async def trade_candidates(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    candidate_ids = [str(item) for item in payload.get("candidate_ids", []) if str(item).strip()]
    if not candidate_ids:
        raise HTTPException(400, detail="candidate_ids are required")

    edge_threshold = float(payload.get("edge_threshold", 0.03))
    sources = payload.get("sources", "kalshi")

    def _run():
        from src.paper_trading import append_paper_trades

        candidates = _build_nba_paper_candidates_df(edge_threshold=edge_threshold, sources=sources)
        if candidates.empty:
            return {"logged": 0, "message": "No candidates are currently eligible", "trade_ids": []}

        selected = candidates[candidates["candidate_id"].astype(str).isin(candidate_ids)].copy()
        if selected.empty:
            return {"logged": 0, "message": "No matching candidates are currently eligible", "trade_ids": []}

        append_paper_trades(selected)
        trade_ids = [str(value) for value in selected["trade_id"].tolist()] if "trade_id" in selected.columns else []
        return {"logged": len(selected), "message": f"Logged {len(selected)} trade{'s' if len(selected) != 1 else ''}", "trade_ids": trade_ids}

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/paper-trader/trades"); raise HTTPException(500, detail=str(e))


@app.get("/api/combo-trader/state")
async def combo_state():
    def _run():
        from src.nba_combos import compute_combo_bankroll

        trades = _load_combo_trades_with_sync()
        bankroll = compute_combo_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
        status = trades["status"].fillna("open") if not trades.empty and "status" in trades.columns else pd.Series(dtype=str)
        return {
            "bankroll": {k: _clean(v) for k, v in bankroll.items()},
            "open_count": int((status == "open").sum()),
            "settled_count": int((status == "settled").sum()),
        }

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/api/combo-trader/board")
async def combo_board():
    def _run():
        from src.nba_combos import get_combo_board

        return get_combo_board()

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/combo-trader/board"); raise HTTPException(500, detail=str(e))


@app.get("/api/combo-trader/collection/{collection_ticker}")
async def combo_collection(collection_ticker: str):
    def _run():
        from src.nba_combos import get_collection_detail

        detail = get_collection_detail(collection_ticker)
        if detail is None:
            raise HTTPException(404, detail="Combo collection not found")
        return detail

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /api/combo-trader/collection"); raise HTTPException(500, detail=str(e))


@app.get("/api/player-props/calculate")
async def player_props_calculate(
    player: str,
    stat: str,
    threshold: float,
    home_team: str | None = None,
    away_team: str | None = None,
):
    if not str(player).strip():
        raise HTTPException(400, detail="player is required")
    if not str(stat).strip():
        raise HTTPException(400, detail="stat is required")
    if threshold < 0:
        raise HTTPException(400, detail="threshold must be >= 0")

    def _run():
        from src.player_props import estimate_player_prop

        estimate = estimate_player_prop(
            player_name=player,
            stat=stat,
            threshold=threshold,
            home_team=home_team,
            away_team=away_team,
        )
        if estimate is None:
            raise HTTPException(404, detail="Unable to estimate player prop")
        return estimate

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /api/player-props/calculate"); raise HTTPException(500, detail=str(e))


@app.get("/api/combo-trader/candidates")
async def combo_candidates():
    def _run():
        from src.nba_combos import build_best_combo_candidates, compute_combo_bankroll

        trades = _load_combo_trades_with_sync()
        bankroll = compute_combo_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
        candidates = build_best_combo_candidates(bankroll=bankroll["available_cash"])
        return {"candidates": _df_to_records(candidates)}

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/combo-trader/candidates"); raise HTTPException(500, detail=str(e))


@app.post("/api/combo-trader/manual-preview")
async def combo_manual_preview(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    collection_ticker = str(payload.get("collection_ticker", "")).strip()
    market_tickers = [str(item).strip() for item in payload.get("market_tickers", []) if str(item).strip()]
    custom_stake = float(payload.get("custom_stake", 0))

    if not collection_ticker:
        raise HTTPException(400, detail="collection_ticker is required")
    if custom_stake <= 0:
        raise HTTPException(400, detail="custom_stake must be > 0")

    def _run():
        from src.nba_combos import build_combo_trade, compute_combo_bankroll

        trades = _load_combo_trades_with_sync()
        bankroll = compute_combo_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
        trade = build_combo_trade(
            collection_ticker=collection_ticker,
            market_tickers=market_tickers,
            custom_stake=custom_stake,
            bankroll_snapshot=bankroll["available_cash"],
        )
        if trade is None:
            raise HTTPException(400, detail="Unable to price combo")
        return {"trade": _clean(trade)}

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /api/combo-trader/manual-preview"); raise HTTPException(500, detail=str(e))


@app.post("/api/combo-trader/custom-trade")
async def combo_custom_trade(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    collection_ticker = str(payload.get("collection_ticker", "")).strip()
    market_tickers = [str(item).strip() for item in payload.get("market_tickers", []) if str(item).strip()]
    custom_stake = float(payload.get("custom_stake", 0))

    if not collection_ticker:
        raise HTTPException(400, detail="collection_ticker is required")
    if custom_stake <= 0:
        raise HTTPException(400, detail="custom_stake must be > 0")

    def _run():
        from src.nba_combos import append_combo_trades, build_combo_trade, compute_combo_bankroll

        trades = _load_combo_trades_with_sync()
        bankroll = compute_combo_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
        trade = build_combo_trade(
            collection_ticker=collection_ticker,
            market_tickers=market_tickers,
            custom_stake=custom_stake,
            bankroll_snapshot=bankroll["available_cash"],
        )
        if trade is None:
            raise HTTPException(400, detail="Unable to build combo")
        append_combo_trades(pd.DataFrame([trade]))
        return {
            "logged": 1,
            "message": f"Combo logged: {trade.get('combo_label', 'Combo')}",
            "trade_id": trade.get("trade_id"),
            "trade": _clean(trade),
        }

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /api/combo-trader/custom-trade"); raise HTTPException(500, detail=str(e))


@app.post("/api/combo-trader/trades")
async def combo_trade_candidates(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    candidate_ids = [str(item).strip() for item in payload.get("candidate_ids", []) if str(item).strip()]
    if not candidate_ids:
        raise HTTPException(400, detail="candidate_ids are required")

    def _run():
        from src.nba_combos import append_combo_trades, build_best_combo_candidates, compute_combo_bankroll

        trades = _load_combo_trades_with_sync()
        bankroll = compute_combo_bankroll(trades, starting_bankroll=config.PAPER_BANKROLL_START)
        candidates = build_best_combo_candidates(bankroll=bankroll["available_cash"])
        if candidates.empty:
            return {"logged": 0, "message": "No combo candidates are currently eligible", "trade_ids": []}
        selected = candidates[candidates["candidate_id"].astype(str).isin(candidate_ids)].copy()
        if selected.empty:
            return {"logged": 0, "message": "No matching combo candidates are currently eligible", "trade_ids": []}
        append_combo_trades(selected)
        trade_ids = [str(value) for value in selected["trade_id"].tolist()] if "trade_id" in selected.columns else []
        return {"logged": len(selected), "message": f"Logged {len(selected)} combo{'s' if len(selected) != 1 else ''}", "trade_ids": trade_ids}

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/combo-trader/trades"); raise HTTPException(500, detail=str(e))


@app.get("/api/combo-trader/positions")
async def combo_positions():
    def _run():
        trades = _load_combo_trades_with_sync()
        if trades.empty:
            return {"positions": [], "open": [], "settled": []}
        trades = trades.sort_values("placed_at", ascending=False) if "placed_at" in trades.columns else trades
        status = trades["status"].fillna("open") if "status" in trades.columns else pd.Series("open", index=trades.index)
        open_positions = trades.loc[status == "open"].copy()
        settled_positions = trades.loc[status == "settled"].copy()
        return {
            "positions": _df_to_records(trades),
            "open": _df_to_records(open_positions),
            "settled": _df_to_records(settled_positions),
        }

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/combo-trader/positions"); raise HTTPException(500, detail=str(e))

@app.get("/api/paper-trader/open-positions")
async def open_positions():
    def _run():
        from src.paper_trading import mark_open_trades_to_market
        trades = _load_trades_with_sync()
        try:
            from src.odds_collection import get_all_market_odds
            odds_df = get_all_market_odds(snapshot_context="api_open")
            trades = mark_open_trades_to_market(trades, odds_df)
        except Exception: pass
        if trades.empty or "status" not in trades.columns: return {"positions": []}
        open_t = trades[trades["status"].fillna("open")=="open"]
        return {"positions": _df_to_records(open_t)}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e: raise HTTPException(500, detail=str(e))


@app.delete("/api/paper-trader/trade/{trade_id}")
async def delete_paper_trade(trade_id: str):
    try:
        from src.paper_trading import delete_paper_trade as _delete
        removed = _delete(trade_id)
        if not removed:
            raise HTTPException(404, detail="Trade not found")
        return {"ok": True, "trade_id": trade_id}
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error deleting trade"); raise HTTPException(500, detail=str(e))

@app.get("/api/paper-trader/auto-bet-status")
async def auto_bet_status():
    """Current state of the background auto-bet polling loop."""
    try:
        from src.auto_paper_trader import get_auto_trade_status
        return _ok(get_auto_trade_status())
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/api/paper-trader/auto-trade")
async def auto_trade_status():
    try:
        from src.auto_paper_trader import get_auto_trade_status
        return _ok(get_auto_trade_status())
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.post("/api/paper-trader/auto-trade")
async def auto_trade_control(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    action = str(payload.get("action", "")).strip().lower()
    if action not in {"arm", "pause", "run_dry_cycle"}:
        raise HTTPException(400, detail="action must be one of arm, pause, run_dry_cycle")

    try:
        from src.auto_paper_trader import update_auto_trade
        return _ok(update_auto_trade(action))
    except Exception as e:
        raise HTTPException(500, detail=str(e))

@app.get("/api/paper-trader/settled-positions")
async def settled_positions():
    def _run():
        trades = _load_trades_with_sync()
        if trades.empty or "status" not in trades.columns: return {"positions": []}
        settled = trades[trades["status"].fillna("open")=="settled"].sort_values("game_date", ascending=False)
        return {"positions": _df_to_records(settled)}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e: raise HTTPException(500, detail=str(e))

# ── Model Accuracy ────────────────────────────────────────────────────────────
@app.get("/api/accuracy")
async def get_accuracy():
    def _run():
        from src.evaluate import compute_metrics, calibration_data, run_backtest
        from src.model import load_model, prepare_xy, temporal_split
        try:
            model, feature_cols, medians = load_model()
        except Exception:
            return {"error": "model_not_trained"}
        df = pd.read_csv(ROOT / config.MODEL_READY_CSV)
        _, val_df, test_df = temporal_split(df)
        eval_df = pd.concat([val_df, test_df]) if not val_df.empty else test_df
        if eval_df.empty: return {"error": "no_eval_data"}
        fc = [c for c in feature_cols if c in eval_df.columns]
        X, y = prepare_xy(eval_df, fc, fill_values=medians)
        y_pred = np.clip(model.predict_proba(X)[:, 1], 1e-7, 1 - 1e-7)
        metrics = compute_metrics(y, y_pred)
        cal = calibration_data(y, y_pred)
        backtest = run_backtest(eval_df, y_pred, config.EDGE_THRESHOLDS)
        fi = []
        try:
            from src.evaluate import plot_feature_importance
            fi_df = plot_feature_importance(model, fc, top_n=20)
            fi = _df_to_records(fi_df)
        except Exception: pass
        recent = []
        try:
            rec = pd.read_csv(ROOT / config.PREDICTION_LOG).sort_values("game_date", ascending=False).head(20)
            recent = _df_to_records(rec)
        except Exception: pass
        bt_out = {str(k): {kk: _clean(vv) for kk, vv in v.items()} for k, v in backtest.items()}
        return {"metrics": {k:_clean(v) for k,v in metrics.items()},
                "calibration": _df_to_records(cal), "backtest": bt_out,
                "feature_importance": fi, "recent_predictions": recent}
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _cached_call(("api_accuracy",), 600, _run)
        )
        return _ok(data)
    except Exception as e:
        logger.exception("Error in /api/accuracy"); raise HTTPException(500, detail=str(e))

# ── Team Explorer ─────────────────────────────────────────────────────────────
@app.get("/api/team-explorer/teams")
async def explorer_teams():
    return _ok({"teams": sorted(NBA_TEAMS)})

@app.get("/api/team-explorer/{team}")
async def explorer_team(team: str):
    def _run():
        t = team.upper()
        df = pd.read_csv(ROOT / config.MODEL_READY_CSV)
        df["game_date"] = pd.to_datetime(df["game_date"], errors="coerce")
        df["season"] = df["season"].astype(str)
        current_season = _current_nba_season_label()
        season_df = df[df["season"] == current_season].copy()
        if season_df.empty:
            available_seasons = sorted(df["season"].dropna().unique())
            current_season = available_seasons[-1] if available_seasons else current_season
            season_df = df[df["season"] == current_season].copy()
        team_df = season_df[
            (season_df["home_team"] == t) | (season_df["away_team"] == t)
        ].sort_values("game_date")
        if team_df.empty: return {"team": t, "error": "no_data"}
        wins = losses = 0
        for _, row in team_df.iterrows():
            ih = row["home_team"] == t; w = int(row.get("home_win",0))
            if ih:
                if w: wins += 1
                else: losses += 1
            else:
                if not w: wins += 1
                else: losses += 1
        he = season_df[season_df["home_team"]==t][["game_date","home_elo"]].rename(columns={"home_elo":"elo"})
        ae = season_df[season_df["away_team"]==t][["game_date","away_elo"]].rename(columns={"away_elo":"elo"})
        elo_hist = pd.concat([he, ae]).sort_values("game_date")
        cur_elo = float(elo_hist["elo"].iloc[-1]) if not elo_hist.empty else 1500.0
        elo_series = [{"game_date":str(r["game_date"])[:10],"elo":_clean(r["elo"])} for _,r in elo_hist.tail(82).iterrows()]
        form = []
        for _, row in team_df.tail(30).iterrows():
            ih = row["home_team"] == t
            p = row.get("home_roll_10_pts" if ih else "away_roll_10_pts",
                        row.get("roll_10_pts"))
            o = row.get("home_roll_10_opp_pts" if ih else "away_roll_10_opp_pts",
                        row.get("roll_10_opp_pts"))
            form.append({"game_date":str(row["game_date"])[:10],"roll_10_pts":_clean(p),"roll_10_opp_pts":_clean(o)})
        return {"team":t,"current_elo":round(cur_elo,1),"record_season":current_season,
                "season_record":{"wins":wins,"losses":losses},
                "win_pct":round(wins/max(wins+losses,1),3),"elo_history":elo_series,"rolling_form":form}
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _cached_call(("api_team_explorer", team.upper()), 300, _run)
        )
        return _ok(data)
    except Exception as e: raise HTTPException(500, detail=str(e))

# ── Bet Tracker ───────────────────────────────────────────────────────────────
@app.get("/api/bet-tracker")
async def bet_tracker():
    def _run():
        trades = _load_trades_with_sync()
        if trades.empty: return {"summary":{}, "cumulative_pnl":[], "bets":[]}
        status = trades["status"].fillna("open") if "status" in trades.columns else pd.Series("open", index=trades.index)
        settled = trades[status=="settled"]
        s_count = len(settled); wins = int(settled["win"].sum()) if "win" in settled.columns and not settled.empty else 0
        win_rate = wins/s_count if s_count > 0 else None
        flat_roi = (settled["pnl"].sum()/settled["stake"].sum()
                    if "pnl" in settled.columns and "stake" in settled.columns
                       and not settled.empty and settled["stake"].sum() > 0 else None)
        sorted_s = settled.sort_values("game_date") if not settled.empty else settled
        cum = []
        if not sorted_s.empty and "pnl" in sorted_s.columns:
            for date, val in zip(sorted_s["game_date"], sorted_s["pnl"].cumsum()):
                cum.append({"game_date":str(date)[:10],"cumulative":_clean(val)})
        return {"summary":{"total_bets":len(trades),"settled_count":s_count,"wins":wins,
                            "losses":s_count-wins,"win_rate":_clean(win_rate),"flat_roi":_clean(flat_roi)},
                "cumulative_pnl":cum,"bets":_df_to_records(sorted_s.tail(100) if not sorted_s.empty else pd.DataFrame())}
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None, lambda: _cached_call(("api_bet_tracker",), 120, _run)
        )
        return _ok(data)
    except Exception as e: raise HTTPException(500, detail=str(e))

# ── NCAAB ─────────────────────────────────────────────────────────────────────
def _ncaab_ok():
    import ncaab_config as nc
    return nc.NCAAB_MODEL_READY_CSV.exists() and nc.NCAAB_CURRENT_TEAM_FEATURES_CSV.exists()


def _build_ncaab_summary_payload():
    if not _ncaab_ok():
        return {"available": False, "reason": "Run scripts/update_ncaab_current.py first"}
    import json as _j
    import ncaab_config as nc

    metrics = _j.loads(nc.NCAAB_METRICS_JSON.read_text()) if nc.NCAAB_METRICS_JSON.exists() else {}
    meta = _j.loads(nc.NCAAB_CURRENT_META_JSON.read_text()) if nc.NCAAB_CURRENT_META_JSON.exists() else {}
    return {"available": True, "metrics": {k: _clean(v) for k, v in metrics.items()}, "meta": meta}


def _build_ncaab_picks_payload(edge_threshold: float = 0.03):
    if not _ncaab_ok():
        return {"picks": [], "available": False}
    try:
        from src.ncaab_odds import get_all_ncaab_market_odds
        from src.ncaab_predict import generate_market_recommendation_table, predict_market_games

        odds_df = get_all_ncaab_market_odds()
        if odds_df.empty:
            return {"picks": [], "available": True}
        predictions = predict_market_games(odds_df)
        if predictions.empty:
            return {"picks": [], "available": True}
        try:
            from src.ncaab_availability import apply_ncaab_availability_adjustments

            predictions = apply_ncaab_availability_adjustments(
                predictions,
                team_a_col="home_team",
                team_b_col="away_team",
                prob_a_col="home_win_prob",
                prob_b_col="away_win_prob",
                prefix_a="home",
                prefix_b="away",
            )
        except Exception as exc:
            logger.warning("NCAA live availability adjustment skipped for picks: %s", exc)
        recs = generate_market_recommendation_table(predictions, odds_df, edge_threshold=edge_threshold)
        return {"picks": _df_to_records(recs), "available": True}
    except Exception as e:
        return {"picks": [], "available": True, "error": str(e)}


def _fetch_ncaab_live_payload():
    from src.ncaab_live_scores import fetch_ncaab_live_games

    data = fetch_ncaab_live_games()
    if isinstance(data, dict) and "fetched_at" not in data:
        data["fetched_at"] = datetime.now(timezone.utc).isoformat()
    if isinstance(data, dict):
        _record_prob_snapshots(data)
    return data


def _normalize_team_key(value: str | None) -> str:
    return re.sub(r"[^a-z0-9]+", "", str(value or "").lower())


def _ncaab_school_url_lookup() -> dict[str, str]:
    import ncaab_config as nc

    lookup: dict[str, str] = {}
    feature_paths = [
        getattr(nc, "NCAAB_CURRENT_ALL_TEAM_FEATURES_CSV", None),
        nc.NCAAB_CURRENT_TEAM_FEATURES_CSV,
    ]

    for path in feature_paths:
        if not path or not Path(path).exists():
            continue

        team_features = pd.read_csv(path)
        candidate_columns = [column for column in ("TeamName", "ProjectionName", "entry_text", "school_url") if column in team_features.columns]
        if "school_url" not in candidate_columns:
            continue

        for row in team_features[candidate_columns].to_dict(orient="records"):
            school_url = str(row.get("school_url") or "").strip()
            if not school_url:
                continue
            for field in ("TeamName", "ProjectionName", "entry_text"):
                team_name = str(row.get(field) or "").strip()
                if not team_name:
                    continue
                lookup[_normalize_team_key(team_name)] = school_url

    for alias_key, canonical_key in _NCAAB_LOGO_ALIAS_KEYS.items():
        school_url = lookup.get(canonical_key)
        if school_url and alias_key not in lookup:
            lookup[alias_key] = school_url

    return lookup


def _resolve_ncaab_logo_url(team: str) -> str | None:
    key = _normalize_team_key(team)
    if not key:
        return None

    school_url = _ncaab_school_url_lookup().get(key)
    if not school_url:
        return None

    slug_match = re.search(r"/schools/([^/]+)/men/(\d{4})\.html", school_url)
    if slug_match:
        school_slug, season = slug_match.groups()
        req_versions: list[str] = []
        today = datetime.now(timezone.utc).date()
        for offset in range(0, 14):
            req_versions.append(f"{(today - timedelta(days=offset)).strftime('%Y%m%d')}0")
        req_versions.extend(NCAAB_LOGO_REQ_VERSION_HINTS)

        seen_versions: set[str] = set()
        for req_version in req_versions:
            if req_version in seen_versions:
                continue
            seen_versions.add(req_version)
            direct_url = f"https://cdn.ssref.net/req/{req_version}/tlogo/ncaa/{school_slug}-{season}.png"
            try:
                response = requests.get(
                    direct_url,
                    timeout=10,
                    headers={"User-Agent": "Mozilla/5.0"},
                )
                content_type = str(response.headers.get("content-type") or "").lower()
                if response.ok and content_type.startswith("image/") and len(response.content) > 256:
                    return direct_url
            except Exception:
                pass

    try:
        response = requests.get(
            school_url,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("NCAA logo page lookup failed for %s: %s", team, exc)
        return None

    html = response.text
    match = re.search(r"https://cdn\.ssref\.net/req/\d+/tlogo/ncaa/[^\"']+\.(?:png|svg)", html, re.IGNORECASE)
    if match:
        return match.group(0)

    match = re.search(r"/req/\d+/tlogo/ncaa/[^\"']+\.(?:png|svg)", html, re.IGNORECASE)
    if match:
        return f"https://cdn.ssref.net{match.group(0)}"

    logger.warning("No NCAA logo asset found for %s at %s", team, school_url)
    return None


def _pixel_is_edge_background(pixel: tuple[int, int, int, int], cutoff: int = 235) -> bool:
    r, g, b, a = pixel
    return a > 0 and r >= cutoff and g >= cutoff and b >= cutoff


def _strip_white_logo_background(raw_bytes: bytes) -> bytes:
    try:
        image = Image.open(BytesIO(raw_bytes))
    except UnidentifiedImageError:
        return raw_bytes

    rgba = image.convert("RGBA")
    width, height = rgba.size
    if width == 0 or height == 0:
        return raw_bytes

    pixels = rgba.load()
    seen = bytearray(width * height)
    queue: deque[tuple[int, int]] = deque()

    def enqueue(x: int, y: int) -> None:
        idx = (y * width) + x
        if seen[idx]:
            return
        if not _pixel_is_edge_background(pixels[x, y]):
            return
        seen[idx] = 1
        queue.append((x, y))

    for x in range(width):
        enqueue(x, 0)
        enqueue(x, height - 1)
    for y in range(height):
        enqueue(0, y)
        enqueue(width - 1, y)

    while queue:
        x, y = queue.popleft()
        r, g, b, _ = pixels[x, y]
        pixels[x, y] = (r, g, b, 0)

        if x > 0:
            enqueue(x - 1, y)
        if x + 1 < width:
            enqueue(x + 1, y)
        if y > 0:
            enqueue(x, y - 1)
        if y + 1 < height:
            enqueue(x, y + 1)

    output = BytesIO()
    rgba.save(output, format="PNG")
    return output.getvalue()


def _build_ncaab_logo_asset(team: str) -> tuple[bytes, str]:
    cache_path = NCAAB_LOGO_FILE_CACHE_DIR / f"{_normalize_team_key(team)}.png"
    if cache_path.exists() and cache_path.stat().st_size > 0:
        return cache_path.read_bytes(), "image/png"

    url = _resolve_ncaab_logo_url(team)
    if not url:
        raise HTTPException(404, detail=f"No logo found for {team}")

    try:
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "Mozilla/5.0"},
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("NCAA logo fetch failed for %s: %s", team, exc)
        raise HTTPException(502, detail=f"Could not fetch logo for {team}") from exc

    content_type = str(response.headers.get("content-type") or "").lower()
    if "svg" in content_type or url.lower().endswith(".svg"):
        return response.content, "image/svg+xml"

    cleaned = _strip_white_logo_background(response.content)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_bytes(cleaned)
    return cleaned, "image/png"

@app.get("/api/ncaab/summary")
async def ncaab_summary():
    data = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _cached_call(("api_ncaab_summary",), STATIC_CACHE_TTL_SECONDS, _build_ncaab_summary_payload),
    )
    return _ok(data)

@app.get("/api/ncaab/picks")
async def ncaab_picks(edge_threshold: float = 0.03):
    cache_key = ("api_ncaab_picks", round(float(edge_threshold), 4))
    data = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _cached_call(
            cache_key,
            PICKS_CACHE_TTL_SECONDS,
            lambda: _build_ncaab_picks_payload(edge_threshold),
        ),
    )
    return _ok(data)

@app.get("/api/ncaab/bracket")
async def ncaab_bracket():
    def _run():
        import ncaab_config as nc
        if not nc.NCAAB_CURRENT_PROJECTED_BRACKET_CSV.exists(): return {"bracket":[],"available":False}

        def _recent_completed_results() -> list[dict[str, Any]]:
            import requests

            url = "https://site.api.espn.com/apis/site/v2/sports/basketball/mens-college-basketball/scoreboard"
            today_et = pd.Timestamp.now(tz="America/New_York").normalize()
            results: list[dict[str, Any]] = []

            for days_back in range(4):
                date_value = (today_et - pd.Timedelta(days=days_back)).strftime("%Y%m%d")
                try:
                    response = requests.get(
                        url,
                        params={"groups": 50, "limit": 200, "dates": date_value},
                        timeout=20,
                        headers={"User-Agent": "Mozilla/5.0"},
                    )
                    response.raise_for_status()
                    payload = response.json()
                except Exception:
                    continue

                for event in payload.get("events", []) or []:
                    competition = (event.get("competitions") or [{}])[0]
                    status_type = ((competition.get("status") or {}).get("type") or {})
                    if not status_type.get("completed"):
                        continue

                    competitors = competition.get("competitors") or []
                    if len(competitors) < 2:
                        continue

                    home = next((c for c in competitors if c.get("homeAway") == "home"), competitors[0])
                    away = next((c for c in competitors if c.get("homeAway") == "away"), competitors[1])
                    home_team = ((home.get("team") or {}).get("displayName") or "").strip()
                    away_team = ((away.get("team") or {}).get("displayName") or "").strip()
                    if not home_team or not away_team:
                        continue

                    try:
                        home_score = int(str(home.get("score") or "0"))
                        away_score = int(str(away.get("score") or "0"))
                    except Exception:
                        home_score = 0
                        away_score = 0

                    winner = home_team if home_score > away_score else away_team
                    results.append({
                        "date": date_value,
                        "home_team": home_team,
                        "away_team": away_team,
                        "home_score": home_score,
                        "away_score": away_score,
                        "winner_name": winner,
                    })

            return results

        result: dict = {"bracket":_df_to_records(pd.read_csv(nc.NCAAB_CURRENT_PROJECTED_BRACKET_CSV)),"available":True}
        adv_path = nc.NCAAB_PROCESSED_DIR / "advancement_probabilities.csv"
        if adv_path.exists():
            result["advancement"] = _df_to_records(pd.read_csv(adv_path))
        result["results"] = _recent_completed_results()
        return result
    return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))

@app.get("/api/ncaab/teams")
async def ncaab_teams():
    def _run():
        import ncaab_config as nc
        if not nc.NCAAB_CURRENT_TEAM_FEATURES_CSV.exists(): return {"teams":[],"available":False}
        return {"teams":_df_to_records(pd.read_csv(nc.NCAAB_CURRENT_TEAM_FEATURES_CSV)),"available":True}
    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _cached_call(("api_ncaab_teams",), STATIC_CACHE_TTL_SECONDS, _run)
    )
    return _ok(data)


@app.get("/api/ncaab/team-explorer/teams")
async def ncaab_explorer_teams():
    def _run():
        import ncaab_config as nc
        if not nc.NCAAB_CURRENT_TEAM_FEATURES_CSV.exists():
            return {"teams": []}
        df = pd.read_csv(nc.NCAAB_CURRENT_TEAM_FEATURES_CSV)
        name_col = "TeamName" if "TeamName" in df.columns else "team_name"
        teams = sorted(df[name_col].dropna().astype(str).drop_duplicates().tolist())
        return {"teams": teams}

    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _cached_call(("api_ncaab_team_explorer_teams",), STATIC_CACHE_TTL_SECONDS, _run)
    )
    return _ok(data)


@app.get("/api/ncaab/team-explorer/{team}")
async def ncaab_explorer_team(team: str):
    def _run():
        import ncaab_config as nc
        from src.ncaab_live import fetch_team_game_log

        if not nc.NCAAB_CURRENT_TEAM_FEATURES_CSV.exists():
            return {"team": team, "error": "no_data"}

        df = pd.read_csv(nc.NCAAB_CURRENT_TEAM_FEATURES_CSV)
        name_col = "TeamName" if "TeamName" in df.columns else "team_name"

        match = df[df[name_col].astype(str).str.lower() == team.lower()]
        if match.empty:
            match = df[df[name_col].astype(str).str.lower().str.contains(team.lower(), na=False)]
        if match.empty:
            return {"team": team, "error": "no_data"}

        row = match.iloc[0]
        team_name = str(row[name_col])
        season = str(int(pd.to_numeric(pd.Series([row.get("Season")]), errors="coerce").fillna(2026).iloc[0]))
        current_elo = float(pd.to_numeric(pd.Series([row.get("elo")]), errors="coerce").fillna(1500.0).iloc[0])
        wins = int(pd.to_numeric(pd.Series([row.get("wins")]), errors="coerce").fillna(0).iloc[0])
        losses = int(pd.to_numeric(pd.Series([row.get("losses")]), errors="coerce").fillna(0).iloc[0])

        gamelog_url = str(row.get("gamelog_url", "") or "")
        team_candidates = df[name_col].dropna().astype(str).drop_duplicates().tolist()
        game_log = fetch_team_game_log(team_name, gamelog_url, team_candidates) if gamelog_url else pd.DataFrame()

        elo_history: list[dict[str, Any]] = []
        rolling_form: list[dict[str, Any]] = []
        if not game_log.empty:
            ratings: dict[str, float] = {}
            for game in game_log.sort_values("date").itertuples(index=False):
                if pd.isna(game.win):
                    continue
                opp_name = str(game.OppTeamName or "")
                if not opp_name:
                    continue
                team_rating = ratings.get(team_name, 1500.0)
                opp_rating = ratings.get(opp_name, 1500.0)
                loc = str(game.game_location or "")
                team_effective = team_rating + (70.0 if loc == "" else 0.0)
                opp_effective = opp_rating + (70.0 if loc == "@" else 0.0)
                expected_team = 1.0 / (1.0 + 10.0 ** ((opp_effective - team_effective) / 400.0))
                team_score = float(game.team_score)
                opp_score = float(game.opp_score)
                margin = max(abs(team_score - opp_score), 1.0)
                multiplier = np.log(margin + 1.0) * (2.2 / ((abs(team_rating - opp_rating) * 0.001) + 2.2))
                delta = 20.0 * multiplier * (float(game.win) - expected_team)
                team_rating = team_rating + delta
                opp_rating = opp_rating - delta
                ratings[team_name] = team_rating
                ratings[opp_name] = opp_rating
                elo_history.append({"game_date": str(pd.Timestamp(game.date).date()), "elo": round(float(team_rating), 1)})

            rolling = game_log.sort_values("date").copy()
            rolling["roll_10_pts"] = rolling["team_score"].rolling(10, min_periods=1).mean()
            rolling["roll_10_opp_pts"] = rolling["opp_score"].rolling(10, min_periods=1).mean()
            rolling_form = [
                {
                    "game_date": str(pd.Timestamp(item.date).date()),
                    "roll_10_pts": _clean(item.roll_10_pts),
                    "roll_10_opp_pts": _clean(item.roll_10_opp_pts),
                }
                for item in rolling.tail(30).itertuples(index=False)
            ]

        elo_history = _anchor_elo_history(elo_history[-82:], current_elo)

        return {
            "team": team_name,
            "current_elo": round(current_elo, 1),
            "record_season": season,
            "season_record": {"wins": wins, "losses": losses},
            "win_pct": _clean(row.get("win_pct")),
            "elo_history": elo_history,
            "rolling_form": rolling_form,
            "seed": row.get("Seed") or row.get("seed_num"),
            "net_rtg": _clean(row.get("net_rtg")),
            "avg_margin": _clean(row.get("avg_margin")),
            "off_rtg": _clean(row.get("off_rtg")),
            "def_rtg": _clean(row.get("def_rtg")),
            "last10_win_pct": _clean(row.get("last10_win_pct")),
            "last10_margin": _clean(row.get("last10_margin")),
            "median_rank": _clean(row.get("median_rank")),
            "best_rank": _clean(row.get("best_rank")),
        }

    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _cached_call(("api_ncaab_team_explorer", str(team).lower()), 300, _run)
    )
    return _ok(data)


@app.get("/api/ncaab/team-logo")
async def ncaab_team_logo(team: str):
    if not team.strip():
        raise HTTPException(400, detail="team is required")

    key = _normalize_team_key(team)
    content, media_type = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: _cached_call(
            ("api_ncaab_team_logo", key),
            NCAAB_LOGO_CACHE_TTL_SECONDS,
            lambda: _build_ncaab_logo_asset(team),
        ),
    )
    return Response(content=content, media_type=media_type)

@app.get("/api/ncaab/odds")
async def ncaab_odds():
    def _run():
        from src.ncaab_odds import get_all_ncaab_market_odds
        odds = get_all_ncaab_market_odds(record_snapshot=True)
        if odds.empty: return {"odds":[],"count":0}
        return {"odds":_df_to_records(odds),"count":len(odds)}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e: raise HTTPException(500, detail=str(e))

@app.get("/api/ncaab/paper-trader/state")
async def ncaab_paper_state():
    def _run():
        from src.ncaab_paper_trading import load_ncaab_paper_trades, compute_ncaab_paper_bankroll
        trades = load_ncaab_paper_trades()
        bankroll = compute_ncaab_paper_bankroll(trades)
        status = trades["status"].fillna("open") if not trades.empty and "status" in trades.columns else pd.Series(dtype=str)
        return {"bankroll": {k:_clean(v) for k,v in bankroll.items()},
                "open_count": int((status=="open").sum()),
                "settled_count": int((status=="settled").sum())}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e: raise HTTPException(500, detail=str(e))

@app.get("/api/ncaab/paper-trader/candidates")
async def ncaab_paper_candidates(edge_threshold: float = 0.03, sources: str = "kalshi"):
    def _run():
        candidates = _build_ncaab_paper_candidates_df(edge_threshold=edge_threshold, sources=sources)
        return {"candidates": _df_to_records(candidates)}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/ncaab/paper-trader/candidates"); raise HTTPException(500, detail=str(e))

@app.post("/api/ncaab/paper-trader/log-trades")
async def ncaab_log_trades(edge_threshold: float = 0.03, sources: str = "kalshi"):
    def _run():
        from src.ncaab_paper_trading import append_ncaab_paper_trades, load_ncaab_paper_trades

        trades = load_ncaab_paper_trades()
        candidates = _build_ncaab_paper_candidates_df(edge_threshold=edge_threshold, sources=sources)
        if candidates.empty: return {"logged": 0, "message": "No trades meet threshold"}
        existing_ids = set(trades["trade_id"].astype(str).tolist()) if not trades.empty and "trade_id" in trades.columns else set()
        new_trades = candidates[~candidates["trade_id"].astype(str).isin(existing_ids)].copy()
        if new_trades.empty: return {"logged": 0, "message": "All candidates already logged"}
        append_ncaab_paper_trades(new_trades)
        return {"logged": len(new_trades), "message": f"Logged {len(new_trades)} NCAAB paper trades"}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error logging NCAAB trades"); raise HTTPException(500, detail=str(e))

@app.post("/api/ncaab/paper-trader/custom-trade")
async def ncaab_custom_paper_trade(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}
    
    home_team = str(payload.get("home_team", "")).strip()
    away_team = str(payload.get("away_team", "")).strip()
    selected_team = str(payload.get("selected_team", "")).strip()
    custom_stake = float(payload.get("custom_stake", 0))
    market_source = str(payload.get("market_source", "kalshi")).strip()
    
    if not all([home_team, away_team, selected_team]):
        raise HTTPException(400, detail="home_team, away_team, and selected_team are required")
    if custom_stake <= 0:
        raise HTTPException(400, detail="custom_stake must be > 0")
    if selected_team not in [home_team, away_team]:
        raise HTTPException(400, detail="selected_team must be either home_team or away_team")
    if market_source not in ["kalshi"]:
        raise HTTPException(400, detail="market_source must be 'kalshi' for NCAAB")
    
    def _run():
        from src.ncaab_paper_trading import append_ncaab_paper_trades, build_custom_ncaab_paper_trade, compute_ncaab_paper_bankroll, load_ncaab_paper_trades
        trades = load_ncaab_paper_trades()
        bankroll = compute_ncaab_paper_bankroll(trades)
        
        custom_trade = build_custom_ncaab_paper_trade(
            home_team=home_team,
            away_team=away_team,
            selected_team=selected_team,
            custom_stake=custom_stake,
            market_source=market_source,
            bankroll_snapshot=bankroll["available_cash"],
        )
        
        if custom_trade is None:
            raise HTTPException(400, detail="Unable to build custom trade - market data may be unavailable")
        
        custom_df = pd.DataFrame([custom_trade])
        append_ncaab_paper_trades(custom_df)
        
        return {
            "logged": 1,
            "message": f"Custom trade placed: ${float(custom_trade.get('stake') or 0):.2f} on {selected_team}",
            "trade_id": custom_trade.get("trade_id"),
            "trade": _clean(custom_trade),
        }
    
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/ncaab/paper-trader/custom-trade"); raise HTTPException(500, detail=str(e))


@app.post("/api/ncaab/paper-trader/manual-preview")
async def ncaab_manual_trade_preview(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    home_team = str(payload.get("home_team", "")).strip()
    away_team = str(payload.get("away_team", "")).strip()
    selected_team = str(payload.get("selected_team", "")).strip()
    custom_stake = float(payload.get("custom_stake", 0))
    market_source = str(payload.get("market_source", "kalshi")).strip()

    if not all([home_team, away_team, selected_team]):
        raise HTTPException(400, detail="home_team, away_team, and selected_team are required")
    if custom_stake <= 0:
        raise HTTPException(400, detail="custom_stake must be > 0")

    def _run():
        from src.ncaab_paper_trading import build_custom_ncaab_paper_trade, compute_ncaab_paper_bankroll, load_ncaab_paper_trades
        trades = load_ncaab_paper_trades()
        bankroll = compute_ncaab_paper_bankroll(trades)
        trade = build_custom_ncaab_paper_trade(
            home_team=home_team,
            away_team=away_team,
            selected_team=selected_team,
            custom_stake=custom_stake,
            market_source=market_source,
            bankroll_snapshot=bankroll["available_cash"],
        )
        if trade is None:
            raise HTTPException(400, detail="Unable to price manual trade")
        return {"trade": _clean(trade)}

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except HTTPException:
        raise
    except Exception as e:
        logger.exception("Error in /api/ncaab/paper-trader/manual-preview"); raise HTTPException(500, detail=str(e))


@app.post("/api/ncaab/paper-trader/trades")
async def ncaab_trade_candidates(request: Request):
    try:
        payload = await request.json()
    except Exception:
        payload = {}

    candidate_ids = [str(item) for item in payload.get("candidate_ids", []) if str(item).strip()]
    if not candidate_ids:
        raise HTTPException(400, detail="candidate_ids are required")

    edge_threshold = float(payload.get("edge_threshold", 0.03))
    sources = payload.get("sources", "kalshi")

    def _run():
        from src.ncaab_paper_trading import append_ncaab_paper_trades, load_ncaab_paper_trades

        trades = load_ncaab_paper_trades()
        candidates = _build_ncaab_paper_candidates_df(edge_threshold=edge_threshold, sources=sources)
        if candidates.empty:
            return {"logged": 0, "message": "No candidates are currently eligible", "trade_ids": []}

        selected = candidates[candidates["candidate_id"].astype(str).isin(candidate_ids)].copy()
        if selected.empty:
            return {"logged": 0, "message": "No matching candidates are currently eligible", "trade_ids": []}

        existing_ids = set(trades["trade_id"].astype(str).tolist()) if not trades.empty and "trade_id" in trades.columns else set()
        selected = selected[~selected["trade_id"].astype(str).isin(existing_ids)].copy()
        if selected.empty:
            return {"logged": 0, "message": "Selected trades were already logged", "trade_ids": []}

        append_ncaab_paper_trades(selected)
        trade_ids = [str(value) for value in selected["trade_id"].tolist()] if "trade_id" in selected.columns else []
        return {"logged": len(selected), "message": f"Logged {len(selected)} trade{'s' if len(selected) != 1 else ''}", "trade_ids": trade_ids}

    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        logger.exception("Error in /api/ncaab/paper-trader/trades"); raise HTTPException(500, detail=str(e))

@app.get("/api/ncaab/paper-trader/auto-trade")
async def ncaab_auto_trade_status():
    return _ok({
        "available": False,
        "enabled": False,
        "mode": "dry-run",
        "min_edge": None,
        "sources": [],
        "poll_seconds": None,
        "active_hours": None,
        "last_run": None,
        "next_run": None,
        "games_checked": 0,
        "new_bets_placed": 0,
        "last_error": None,
        "last_message": None,
        "is_running": False,
        "reason": "Auto trade unavailable for NCAA",
    })

@app.get("/api/ncaab/paper-trader/positions")
async def ncaab_paper_positions():
    def _run():
        from src.ncaab_odds import get_all_ncaab_market_odds
        from src.ncaab_paper_trading import load_ncaab_paper_trades, mark_open_ncaab_trades_to_market
        trades = load_ncaab_paper_trades()
        if trades.empty: return {"open":[],"settled":[]}
        try:
            odds = get_all_ncaab_market_odds(record_snapshot=False)
            trades = mark_open_ncaab_trades_to_market(trades, odds)
        except Exception:
            pass
        open_t = trades[trades.get("status","open")=="open"] if "status" in trades.columns else trades
        settled = trades[trades.get("status","")=="settled"] if "status" in trades.columns else pd.DataFrame()
        return {"open":_df_to_records(open_t),"settled":_df_to_records(settled)}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e: raise HTTPException(500, detail=str(e))


# ── NCAAB Live / Matchup / Accuracy / Bet Tracker ────────────────────────────

@app.get("/api/ncaab/live")
async def ncaab_live():
    try:
        data = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: _cached_call(("api_ncaab_live",), LIVE_CACHE_TTL_SECONDS, _fetch_ncaab_live_payload),
        )
        data = _nudge_coinflip(data)
        return _ok(data)
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/api/ncaab/matchup")
async def ncaab_matchup(team_a: str = "", team_b: str = ""):
    def _run():
        import ncaab_config as nc
        from src.ncaab_live import (
            CURRENT_ELO_HOME_EDGE,
            CURRENT_ELO_K,
            fetch_team_game_log,
        )
        if not nc.NCAAB_CURRENT_TEAM_FEATURES_CSV.exists():
            raise ValueError("Team features not built yet")
        if not str(team_a).strip() or not str(team_b).strip():
            raise ValueError("Choose two teams")
        if str(team_a).strip().lower() == str(team_b).strip().lower():
            raise ValueError("Choose two different teams")
        tf = pd.read_csv(nc.NCAAB_CURRENT_TEAM_FEATURES_CSV)
        name_col = "TeamName" if "TeamName" in tf.columns else "team_name"
        id_col   = "TeamID"   if "TeamID"   in tf.columns else "team_id"

        def find_team(name):
            m = tf[tf[name_col].str.lower() == name.lower()]
            if m.empty:
                m = tf[tf[name_col].str.lower().str.contains(name.lower(), na=False)]
            return m.iloc[0] if not m.empty else None

        ra, rb = find_team(team_a), find_team(team_b)
        if ra is None or rb is None:
            raise ValueError(f"Team not found: {team_a if ra is None else team_b}")
        if int(ra[id_col]) == int(rb[id_col]):
            raise ValueError("Choose two different teams")

        from src.ncaab_predict import predict_matchup, load_current_team_features
        season = int(tf["Season"].max()) if "Season" in tf.columns else 2026
        feat = load_current_team_features()
        result = predict_matchup(season, int(ra[id_col]), int(rb[id_col]), team_features=feat)

        # Build stat comparison rows from team_features csv
        def stats(row):
            wins  = row.get("wins") or (int(row.get("g", 0) or 0) * float(row.get("win_pct", 0) or 0))
            losses = row.get("losses") or (int(row.get("g", 0) or 0) - wins)
            return {
                "name": str(row[name_col]),
                "seed": str(row.get("Seed", "")) or str(row.get("seed_num", "")),
                "wins": _clean(wins),
                "losses": _clean(losses),
                "elo": _clean(row.get("elo")),
                "win_pct": _clean(row.get("win_pct")),
                "net_rtg": _clean(row.get("net_rtg")),
                "off_rtg": _clean(row.get("off_rtg")),
                "def_rtg": _clean(row.get("def_rtg")),
                "avg_margin": _clean(row.get("avg_margin")),
                "srs": _clean(row.get("srs")),
                "sos": _clean(row.get("sos")),
                "last10_win_pct": _clean(row.get("last10_win_pct")),
                "last10_margin": _clean(row.get("last10_margin")),
                "efg": _clean(row.get("efg")),
                "avg_score_for": _clean(row.get("avg_score_for")),
                "avg_score_against": _clean(row.get("avg_score_against")),
                "pace": _clean(row.get("pace")),
                "fg3_rate": _clean(row.get("fg3_rate")),
                "ft_pct": _clean(row.get("ft_pct")),
                "tov_rate": _clean(row.get("tov_rate")),
                "ast_rate": _clean(row.get("ast_rate")),
                "stl_rate": _clean(row.get("stl_rate")),
                "blk_rate": _clean(row.get("blk_rate")),
                "oreb_pct": _clean(row.get("oreb_pct")),
                "dreb_pct": _clean(row.get("dreb_pct")),
                "opp_efg": _clean(row.get("opp_efg")),
                "opp_tov_rate": _clean(row.get("opp_tov_rate")),
                "median_rank": _clean(row.get("median_rank")),
                "best_rank": _clean(row.get("best_rank")),
                "std_margin": _clean(row.get("std_margin")),
            }

        def form_from_gamelog(row) -> list[dict]:
            """Extract last-10-games form from fetched game log."""
            gamelog_url = str(row.get("gamelog_url", "") or "")
            team_name = str(row[name_col])
            if not gamelog_url:
                return []
            team_candidates = tf[name_col].dropna().astype(str).drop_duplicates().tolist()
            game_log = fetch_team_game_log(team_name, gamelog_url, team_candidates)
            if game_log.empty:
                return []
            recent = game_log.sort_values("date").tail(10)
            out = []
            for g in recent.itertuples(index=False):
                if pd.isna(getattr(g, "win", None)):
                    continue
                out.append({
                    "game_date": pd.Timestamp(g.date).date().isoformat() if not pd.isna(g.date) else None,
                    "win": int(g.win),
                    "pts": _clean(getattr(g, "team_score", None)),
                    "opp_pts": _clean(getattr(g, "opp_score", None)),
                    "opponent": str(getattr(g, "OppTeamName", "") or ""),
                })
            return out

        def elo_history(row) -> list[dict[str, float | str | None]]:
            gamelog_url = str(row.get("gamelog_url", "") or "")
            team_name = str(row[name_col])
            if not gamelog_url:
                return []

            team_candidates = tf[name_col].dropna().astype(str).drop_duplicates().tolist()
            game_log = fetch_team_game_log(team_name, gamelog_url, team_candidates)
            if game_log.empty:
                return []

            ratings: dict[str, float] = {}
            history: list[dict[str, float | str | None]] = []
            for game in game_log.sort_values("date").itertuples(index=False):
                if pd.isna(game.win):
                    continue
                opp_name = str(game.OppTeamName or "")
                if not opp_name:
                    continue

                team_rating = ratings.get(team_name, 1500.0)
                opp_rating = ratings.get(opp_name, 1500.0)
                loc = str(game.game_location or "")
                team_effective = team_rating + (CURRENT_ELO_HOME_EDGE if loc == "" else 0.0)
                opp_effective = opp_rating + (CURRENT_ELO_HOME_EDGE if loc == "@" else 0.0)
                expected_team = 1.0 / (1.0 + 10.0 ** ((opp_effective - team_effective) / 400.0))

                team_score = float(game.team_score)
                opp_score = float(game.opp_score)
                margin = max(abs(team_score - opp_score), 1.0)
                multiplier = np.log(margin + 1.0) * (2.2 / ((abs(team_rating - opp_rating) * 0.001) + 2.2))
                delta = CURRENT_ELO_K * multiplier * (float(game.win) - expected_team)

                team_rating = team_rating + delta
                opp_rating = opp_rating - delta
                ratings[team_name] = team_rating
                ratings[opp_name] = opp_rating
                history.append(
                    {
                        "game_date": pd.Timestamp(game.date).date().isoformat(),
                        "elo": round(float(team_rating), 1),
                    }
                )

            return _anchor_elo_history(history[-82:], row.get("elo"))

        pa = float(result["team_a_win_prob"])
        pb = float(result["team_b_win_prob"])
        pa_raw = float(result.get("team_a_win_prob_model", pa))
        pb_raw = float(result.get("team_b_win_prob_model", pb))
        team_a_seed_edge = float(result.get("team_a_seed_edge", 0.0))
        team_b_seed_edge = float(result.get("team_b_seed_edge", 0.0))
        conf = abs(pa - pb)
        if conf < 0.005:
            fav = "Even"
            conf_label = "Coin flip"
        else:
            fav = result["team_a_name"] if pa > pb else result["team_b_name"]
            conf_label = "Strong" if conf > 0.2 else "Moderate" if conf > 0.1 else "Slight"
        # Predicted score: ML regression model, constrained so winner matches win probability
        try:
            from src.score_model import predict_ncaa_score
            _sc = predict_ncaa_score(ra.to_dict() if hasattr(ra, "to_dict") else dict(ra),
                                     rb.to_dict() if hasattr(rb, "to_dict") else dict(rb))
            if _sc:
                _total = _sc[0] + _sc[1]
                # Spread derived from win probability (10.5 pt/logit unit for NCAA)
                _spread_b = 10.5 * math.log(max(pb, 0.01) / max(pa, 0.01))
                pred_score_a = round((_total - _spread_b) / 2)
                pred_score_b = round((_total + _spread_b) / 2)
            else:
                pred_score_a, pred_score_b = None, None
        except Exception:
            pred_score_a, pred_score_b = None, None
        try:
            from src.ncaab_availability import apply_ncaab_availability_adjustments

            adjusted_probs = apply_ncaab_availability_adjustments(
                pd.DataFrame(
                    [
                        {
                            "team_a": result["team_a_name"],
                            "team_b": result["team_b_name"],
                            "team_a_win_prob": pa,
                            "team_b_win_prob": pb,
                            "team_a_win_prob_model": pa_raw,
                            "team_b_win_prob_model": pb_raw,
                        }
                    ]
                ),
                team_a_col="team_a",
                team_b_col="team_b",
                prob_a_col="team_a_win_prob",
                prob_b_col="team_b_win_prob",
                prefix_a="team_a",
                prefix_b="team_b",
            ).iloc[0]
            pa = float(adjusted_probs["team_a_win_prob"])
            pb = float(adjusted_probs["team_b_win_prob"])
            team_a_penalty = float(adjusted_probs.get("team_a_availability_penalty_elo", 0.0))
            team_b_penalty = float(adjusted_probs.get("team_b_availability_penalty_elo", 0.0))
            team_a_summary = str(adjusted_probs.get("team_a_availability_summary", "No major availability flags"))
            team_b_summary = str(adjusted_probs.get("team_b_availability_summary", "No major availability flags"))
        except Exception as exc:
            logger.warning("NCAA matchup availability adjustment skipped: %s", exc)
            team_a_penalty = 0.0
            team_b_penalty = 0.0
            team_a_summary = "No major availability flags"
            team_b_summary = "No major availability flags"
        stats_a_out = stats(ra)
        stats_b_out = stats(rb)
        form_a_out = form_from_gamelog(ra)
        form_b_out = form_from_gamelog(rb)
        narrative = _build_matchup_narrative(
            result["team_a_name"], result["team_b_name"],
            stats_a_out, stats_b_out, pa, pb,
            form_a=form_a_out, form_b=form_b_out,
            league="ncaab",
        )
        return {
            "team_a": result["team_a_name"],
            "team_b": result["team_b_name"],
            "team_a_win_prob": pa,
            "team_b_win_prob": pb,
            "team_a_win_prob_model": pa_raw,
            "team_b_win_prob_model": pb_raw,
            "favorite": fav,
            "confidence_label": conf_label,
            "seed_baseline_prob": result.get("seed_baseline_prob"),
            "team_a_seed_edge": team_a_seed_edge,
            "team_b_seed_edge": team_b_seed_edge,
            "pred_score_a": pred_score_a,
            "pred_score_b": pred_score_b,
            "narrative": narrative,
            "stats_a": stats_a_out,
            "stats_b": stats_b_out,
            "form_a": form_a_out,
            "form_b": form_b_out,
            "team_a_availability_penalty_elo": team_a_penalty,
            "team_b_availability_penalty_elo": team_b_penalty,
            "team_a_availability_summary": team_a_summary,
            "team_b_availability_summary": team_b_summary,
            "elo_history_a": elo_history(ra),
            "elo_history_b": elo_history(rb),
        }
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


@app.get("/api/ncaab/matchup/teams")
async def ncaab_matchup_teams():
    def _run():
        import ncaab_config as nc
        if not nc.NCAAB_CURRENT_TEAM_FEATURES_CSV.exists(): return {"teams": []}
        tf = pd.read_csv(nc.NCAAB_CURRENT_TEAM_FEATURES_CSV)
        col = "TeamName" if "TeamName" in tf.columns else "team_name"
        teams = sorted(tf[col].dropna().unique().tolist())
        return {"teams": teams}
    return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))


@app.get("/api/ncaab/accuracy")
async def ncaab_accuracy():
    def _run():
        import ncaab_config as nc
        if not nc.NCAAB_METRICS_JSON.exists():
            return {"error": "model_not_trained"}
        import json as _json
        metrics = _json.loads(nc.NCAAB_METRICS_JSON.read_text())
        return {"metrics": metrics, "available": True}
    return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))


@app.get("/api/ncaab/bet-tracker")
async def ncaab_bet_tracker():
    def _run():
        from src.ncaab_paper_trading import load_ncaab_paper_trades
        trades = load_ncaab_paper_trades()
        if trades.empty:
            return {"summary": {}, "bets": [], "cumulative_pnl": []}
        settled = trades[trades.get("status", pd.Series(["open"]*len(trades))) == "settled"] if "status" in trades.columns else trades
        bets = _df_to_records(settled.sort_values("game_date", ascending=False) if "game_date" in settled.columns else settled)
        wins = int((settled.get("win", pd.Series()) == 1).sum()) if "win" in settled.columns else 0
        losses = len(settled) - wins
        total_stake = float(settled["stake"].sum()) if "stake" in settled.columns and len(settled) else 0
        total_pnl   = float(settled["pnl"].sum())   if "pnl"   in settled.columns and len(settled) else 0
        # Cumulative P/L over time
        cum_data = []
        if "pnl" in settled.columns and "game_date" in settled.columns:
            s = settled.sort_values("game_date")
            cum = 0.0
            for _, row in s.iterrows():
                cum += float(row.get("pnl") or 0)
                cum_data.append({"game_date": str(row["game_date"])[:10], "cumulative": round(cum, 2)})
        return {
            "summary": {
                "wins": wins, "losses": losses,
                "win_rate": wins / len(settled) if len(settled) else None,
                "flat_roi": total_pnl / total_stake if total_stake else None,
                "total_bets": len(settled),
            },
            "bets": bets,
            "cumulative_pnl": cum_data,
        }
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e:
        raise HTTPException(500, detail=str(e))


# ── Overview ──────────────────────────────────────────────────────────────────
@app.get("/api/overview")
async def overview(league: str = "nba"):
    league_key = str(league).strip().lower()
    if league_key not in {"nba", "ncaab"}:
        raise HTTPException(400, detail="league must be 'nba' or 'ncaab'")

    def _pick_sort_key(pick: dict[str, Any]) -> tuple[float, float]:
        return (
            float(pick.get("best_edge") or pick.get("edge") or 0),
            float(pick.get("kelly") or pick.get("kelly_pct") or 0),
        )

    def _live_sort_key(game: dict[str, Any]) -> tuple[float, str]:
        return (
            float(abs(game.get("live_home_edge") or game.get("live_away_edge") or game.get("edge") or 0)),
            str(game.get("tipoff_utc") or ""),
        )

    def _run():
        health = _build_system_health_payload()

        if league_key == "nba":
            picks = _cached_call(("api_picks", 0.03), PICKS_CACHE_TTL_SECONDS, lambda: _build_nba_picks_payload(0.03))
            live = _cached_call(("api_live",), LIVE_CACHE_TTL_SECONDS, _fetch_live_payload)
            trades = _load_trades_with_sync()
            if not trades.empty and "status" in trades.columns:
                open_positions = trades[trades["status"].fillna("open") == "open"].copy()
                settled_positions = trades[trades["status"].fillna("open") == "settled"].copy()
            else:
                open_positions = pd.DataFrame()
                settled_positions = pd.DataFrame()
            top_candidates = sorted(
                [p for p in picks.get("picks", []) if p.get("bet")] or picks.get("picks", []),
                key=_pick_sort_key,
                reverse=True,
            )
            live_games = sorted(
                [*(live.get("in_progress", []) or []), *(live.get("upcoming", []) or [])],
                key=_live_sort_key,
                reverse=True,
            )
            return {
                "league": "nba",
                "available": True,
                "generated_at": datetime.now(timezone.utc).isoformat(),
                "bets_found": picks.get("bets_found", 0),
                "avg_edge": picks.get("avg_edge", 0),
                "live_count": len((live.get("in_progress", []) or [])),
                "open_positions_count": int(len(open_positions)),
                "settled_positions_count": int(len(settled_positions)),
                "top_pick": top_candidates[0] if top_candidates else None,
                "top_picks": top_candidates[:5],
                "live_games": live_games[:6],
                "open_positions": _df_to_records(
                    open_positions.sort_values("placed_at", ascending=False).head(6)
                    if not open_positions.empty and "placed_at" in open_positions.columns
                    else open_positions.head(6)
                ),
                "model_trained_at": health.get("model_trained_at"),
                "snapshot_age_seconds": health.get("snapshot_age_seconds"),
                "snapshot_stale": health.get("snapshot_stale"),
                "alerts_24h": health.get("alerts_24h", 0),
                "meta": {"date": picks.get("date")},
            }

        summary = _cached_call(("api_ncaab_summary",), STATIC_CACHE_TTL_SECONDS, _build_ncaab_summary_payload)
        picks = _cached_call(("api_ncaab_picks", 0.03), PICKS_CACHE_TTL_SECONDS, lambda: _build_ncaab_picks_payload(0.03))
        live = _cached_call(("api_ncaab_live",), LIVE_CACHE_TTL_SECONDS, _fetch_ncaab_live_payload)
        try:
            from src.ncaab_paper_trading import load_ncaab_paper_trades

            trades = load_ncaab_paper_trades()
        except Exception:
            trades = pd.DataFrame()
        if not trades.empty and "status" in trades.columns:
            open_positions = trades[trades["status"].fillna("open") == "open"].copy()
            settled_positions = trades[trades["status"].fillna("open") == "settled"].copy()
        else:
            open_positions = trades.copy()
            settled_positions = pd.DataFrame()

        top_candidates = sorted(
            [p for p in picks.get("picks", []) if p.get("bet")] or picks.get("picks", []),
            key=_pick_sort_key,
            reverse=True,
        )
        live_games = sorted(
            [*(live.get("in_progress", []) or []), *(live.get("upcoming", []) or [])],
            key=_live_sort_key,
            reverse=True,
        )
        return {
            "league": "ncaab",
            "available": bool(summary.get("available", True)),
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "bets_found": len([p for p in picks.get("picks", []) if p.get("bet")]),
            "avg_edge": round(
                float(
                    np.mean([p.get("best_edge") or p.get("edge") or 0 for p in picks.get("picks", [])])
                )
                if picks.get("picks")
                else 0,
                4,
            ),
            "live_count": len((live.get("in_progress", []) or [])),
            "open_positions_count": int(len(open_positions)),
            "settled_positions_count": int(len(settled_positions)),
            "top_pick": top_candidates[0] if top_candidates else None,
            "top_picks": top_candidates[:5],
            "live_games": live_games[:6],
            "open_positions": _df_to_records(
                open_positions.sort_values("placed_at", ascending=False).head(6)
                if not open_positions.empty and "placed_at" in open_positions.columns
                else open_positions.head(6)
            ),
            "model_trained_at": health.get("model_trained_at"),
            "snapshot_age_seconds": health.get("snapshot_age_seconds"),
            "snapshot_stale": health.get("snapshot_stale"),
            "alerts_24h": health.get("alerts_24h", 0),
            "meta": summary.get("meta", {}),
        }

    cache_key = ("api_overview", league_key)
    data = await asyncio.get_event_loop().run_in_executor(
        None, lambda: _cached_call(cache_key, 60, _run)
    )
    return _ok(data)


# ── System ────────────────────────────────────────────────────────────────────
@app.get("/ping")
async def ping():
    return {"ok": True}

@app.get("/api/system/health")
async def system_health():
    return _ok(await asyncio.get_event_loop().run_in_executor(None, _build_system_health_payload))

@app.get("/api/system/alerts")
async def system_alerts(hours: int = 24):
    def _run():
        try:
            df = pd.read_csv(ROOT / config.ALERTS_CSV)
            if "created_at" in df.columns:
                cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
                df = df[pd.to_datetime(df["created_at"], utc=True) > cutoff].sort_values("created_at", ascending=False)
            return {"alerts": _df_to_records(df.head(100))}
        except Exception: return {"alerts": []}
    return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))

@app.post("/api/system/settle-results")
async def settle_results_endpoint():
    def _run():
        out = subprocess.run([sys.executable, str(ROOT/"scripts"/"settle_results.py")],
                             capture_output=True, text=True, cwd=str(ROOT))
        return {"success": out.returncode == 0, "output": out.stdout or out.stderr}
    try:
        return _ok(await asyncio.get_event_loop().run_in_executor(None, _run))
    except Exception as e: raise HTTPException(500, detail=str(e))

# ── Update Model ─────────────────────────────────────────────────────────────

def _run_update_model_job():
    """Background thread: run build_dataset.py then train.py, streaming log lines into _UPDATE_JOB."""
    global _MODEL
    def _log(line: str):
        with _UPDATE_JOB_LOCK:
            _UPDATE_JOB["log"].append(line)
            if len(_UPDATE_JOB["log"]) > 500:
                _UPDATE_JOB["log"] = _UPDATE_JOB["log"][-500:]

    def _stream(proc, label):
        for raw in iter(proc.stdout.readline, ""):
            line = raw.rstrip()
            if line:
                _log(f"[{label}] {line}")
        proc.stdout.close()
        proc.wait()

    try:
        # Remove current-season raw cache so the re-pull gets today's games
        import config as _cfg
        _cur_season = _cfg.SEASONS[-1]  # e.g. "2025-26"
        for _fname in [f"game_logs_{_cur_season}.csv", f"advanced_stats_{_cur_season}.csv"]:
            _p = ROOT / "data" / "raw" / _fname
            if _p.exists():
                try: os.remove(_p); _log(f"[system] Removed stale cache: {_fname}")
                except Exception as _e: _log(f"[system] Could not remove {_fname}: {_e}")

        _log("[system] Starting dataset build (this may take 30-60 min)...")
        p1 = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "build_dataset.py")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(ROOT),
        )
        _stream(p1, "build")
        if p1.returncode != 0:
            _log(f"[system] build_dataset.py failed (exit {p1.returncode})")
            with _UPDATE_JOB_LOCK:
                _UPDATE_JOB["status"] = "error"
                _UPDATE_JOB["finished_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            return

        _log("[system] Dataset built. Starting model training...")
        p2 = subprocess.Popen(
            [sys.executable, str(ROOT / "scripts" / "train.py")],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, cwd=str(ROOT),
        )
        _stream(p2, "train")
        if p2.returncode != 0:
            _log(f"[system] train.py failed (exit {p2.returncode})")
            with _UPDATE_JOB_LOCK:
                _UPDATE_JOB["status"] = "error"
                _UPDATE_JOB["finished_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()
            return

        # Reload model in memory
        try:
            from src.model import load_model
            _MODEL = load_model()
            _log("[system] Model reloaded into memory.")
        except Exception as e:
            _log(f"[system] Warning: could not reload model: {e}")

        _log("[system] Update complete!")
        # Flush the API cache so stale team/accuracy data isn't served
        with _API_CACHE_LOCK:
            _API_CACHE.clear()
        _log("[system] Cache cleared.")
        with _UPDATE_JOB_LOCK:
            _UPDATE_JOB["status"] = "done"
            _UPDATE_JOB["finished_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()

    except Exception as e:
        _log(f"[system] Unexpected error: {e}")
        with _UPDATE_JOB_LOCK:
            _UPDATE_JOB["status"] = "error"
            _UPDATE_JOB["finished_at"] = __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()


@app.post("/api/system/update-model")
async def update_model_endpoint():
    with _UPDATE_JOB_LOCK:
        if _UPDATE_JOB["status"] == "running":
            return _ok({"started": False, "reason": "already_running"})
        _UPDATE_JOB["status"] = "running"
        _UPDATE_JOB["log"] = []
        _UPDATE_JOB["started_at"] = datetime.now(timezone.utc).isoformat()
        _UPDATE_JOB["finished_at"] = None
    threading.Thread(target=_run_update_model_job, daemon=True, name="update-model").start()
    return _ok({"started": True})


@app.get("/api/system/update-model/status")
async def update_model_status():
    with _UPDATE_JOB_LOCK:
        return _ok({
            "status": _UPDATE_JOB["status"],
            "log": list(_UPDATE_JOB["log"]),
            "started_at": _UPDATE_JOB["started_at"],
            "finished_at": _UPDATE_JOB["finished_at"],
        })


# ── Static / SPA ──────────────────────────────────────────────────────────────
if FRONTEND_DIST.exists():
    app.mount("/app-assets", StaticFiles(directory=str(FRONTEND_DIST)), name="app-assets")
app.mount("/static", StaticFiles(directory=str(ROOT / "static")), name="static")


@app.get("/{full_path:path}", response_class=HTMLResponse)
async def spa_fallback(full_path: str):
    if full_path.startswith(("api/", "docs", "openapi.json", "app-assets/", "static/")):
        raise HTTPException(404, detail="Not found")
    return _frontend_index_html()
