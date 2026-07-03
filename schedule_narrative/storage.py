"""
SQLite-backed persistence for parsed schedules. Replaces the in-memory
cache in api.py so an uploaded schedule survives a backend restart.

Activity round-trips through JSON via to_dict() / Activity(**dict) --
the dict's keys already match the dataclass fields one-to-one, so no
separate serialization schema is needed.
"""
from __future__ import annotations
import json
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Optional

from activity_extractor import Activity

DB_PATH = Path(os.environ.get("SCHEDULE_DB_PATH", "schedules.db"))


def _get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schedules (
            schedule_id TEXT PRIMARY KEY,
            data_date TEXT NOT NULL,
            activities TEXT NOT NULL,
            wbs_tree TEXT NOT NULL,
            created_at TEXT NOT NULL
        )
        """
    )
    return conn


def save_schedule(
    schedule_id: str,
    data_date: datetime,
    activities: list[Activity],
    wbs_tree: list[dict],
) -> None:
    with _get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO schedules (schedule_id, data_date, activities, wbs_tree, created_at) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                schedule_id,
                data_date.isoformat(),
                json.dumps([a.to_dict() for a in activities]),
                json.dumps(wbs_tree),
                datetime.utcnow().isoformat(),
            ),
        )


def load_schedule(schedule_id: str) -> Optional[dict]:
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT data_date, activities, wbs_tree FROM schedules WHERE schedule_id = ?",
            (schedule_id,),
        ).fetchone()

    if row is None:
        return None

    data_date_str, activities_json, wbs_tree_json = row
    return {
        "data_date": datetime.fromisoformat(data_date_str),
        "activities": [Activity(**d) for d in json.loads(activities_json)],
        "wbs_tree": json.loads(wbs_tree_json),
    }
