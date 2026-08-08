"""Append-only event journal in SQLite.

Single `events` table; state is always rebuildable by replay. Decimal values
are stored as strings inside the JSON payload to avoid float drift.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

_SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts_utc TEXT NOT NULL,
    kind TEXT NOT NULL,
    payload TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_events_kind_ts ON events (kind, ts_utc);
"""


def _default(o: Any) -> str:
    if isinstance(o, Decimal):
        return str(o)
    if isinstance(o, datetime):
        return o.isoformat()
    raise TypeError(f"not JSON serializable: {type(o)}")


class Journal:
    def __init__(self, db_path: str | Path) -> None:
        path = Path(db_path)
        if str(db_path) != ":memory:":
            path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path))
        self._conn.executescript(_SCHEMA)
        self._conn.commit()

    def append(self, ts_utc: datetime, kind: str, payload: dict[str, Any]) -> None:
        self._conn.execute(
            "INSERT INTO events (ts_utc, kind, payload) VALUES (?, ?, ?)",
            (ts_utc.isoformat(), kind, json.dumps(payload, default=_default)),
        )
        self._conn.commit()

    def events(self, kind: str | None = None, since: datetime | None = None) -> list[dict]:
        q = "SELECT ts_utc, kind, payload FROM events"
        cond, args = [], []
        if kind:
            cond.append("kind = ?")
            args.append(kind)
        if since:
            cond.append("ts_utc >= ?")
            args.append(since.isoformat())
        if cond:
            q += " WHERE " + " AND ".join(cond)
        q += " ORDER BY id"
        rows = self._conn.execute(q, args).fetchall()
        return [{"ts_utc": r[0], "kind": r[1], **json.loads(r[2])} for r in rows]

    def last_event(self, kind: str) -> dict | None:
        row = self._conn.execute(
            "SELECT ts_utc, kind, payload FROM events WHERE kind = ? ORDER BY id DESC LIMIT 1",
            (kind,),
        ).fetchone()
        if row is None:
            return None
        return {"ts_utc": row[0], "kind": row[1], **json.loads(row[2])}

    def close(self) -> None:
        self._conn.close()


# Event kinds (documented in one place; grep-able).
SIGNAL = "signal"
INTENT = "intent"
INTENT_REJECTED = "intent_rejected"
ORDER_SUBMITTED = "order_submitted"
FILL = "fill"
TRADE_CLOSED = "trade_closed"
EQUITY = "equity"
RISK_HALT = "risk_halt"
SESSION_START = "session_start"
SESSION_END = "session_end"
NOTE = "note"
