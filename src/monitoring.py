"""
monitoring.py - Lightweight alert and health tracking for the app and scripts.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

import config


ALERT_COLUMNS = ["created_at", "severity", "code", "message", "context", "details"]


# Suppress duplicate alerts: same code won't fire more than once per cooldown window
ALERT_COOLDOWN_MINUTES: dict[str, int] = {
    "sportsbook_fetch_failed": 30,
    "odds_stale": 60,
    "model_not_loaded": 60,
}
_DEFAULT_COOLDOWN_MINUTES = 10


def emit_alert(
    code: str,
    message: str,
    severity: str = "warning",
    context: str = "",
    details: dict | None = None,
    alert_path: str = config.ALERTS_CSV,
) -> None:
    fpath = Path(alert_path)
    fpath.parent.mkdir(parents=True, exist_ok=True)

    now = pd.Timestamp.now(tz="UTC")
    cooldown = ALERT_COOLDOWN_MINUTES.get(code, _DEFAULT_COOLDOWN_MINUTES)

    if fpath.exists():
        try:
            existing = pd.read_csv(fpath)
            existing["created_at"] = pd.to_datetime(existing["created_at"], errors="coerce", utc=True)
            recent_same = existing[
                (existing["code"] == code) &
                (existing["created_at"] >= now - pd.Timedelta(minutes=cooldown))
            ]
            if not recent_same.empty:
                return  # suppress duplicate within cooldown window
        except Exception:
            existing = pd.DataFrame(columns=ALERT_COLUMNS)
    else:
        existing = pd.DataFrame(columns=ALERT_COLUMNS)

    row = {
        "created_at": now.isoformat(),
        "severity": severity,
        "code": code,
        "message": message,
        "context": context,
        "details": json.dumps(details or {}, sort_keys=True),
    }

    combined = pd.concat([existing, pd.DataFrame([row])], ignore_index=True)
    combined = combined.tail(1000)
    combined.to_csv(fpath, index=False)


def load_alerts(alert_path: str = config.ALERTS_CSV) -> pd.DataFrame:
    path = Path(alert_path)
    if not path.exists():
        return pd.DataFrame(columns=ALERT_COLUMNS)

    df = pd.read_csv(path)
    if "created_at" in df.columns:
        df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce", utc=True)
    return df.sort_values("created_at", ascending=False).reset_index(drop=True)


def recent_alerts(hours: int = 24, alert_path: str = config.ALERTS_CSV) -> pd.DataFrame:
    alerts = load_alerts(alert_path)
    if alerts.empty or "created_at" not in alerts.columns:
        return alerts

    cutoff = pd.Timestamp.now(tz="UTC") - pd.Timedelta(hours=hours)
    return alerts[alerts["created_at"] >= cutoff].reset_index(drop=True)
