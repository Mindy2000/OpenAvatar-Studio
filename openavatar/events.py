from __future__ import annotations

import json
import time
from typing import Any
from uuid import uuid4

from openavatar.db import Database


class EventStore:
    """Append-only audit log with a transactional retryable outbox."""

    def __init__(self, db: Database) -> None:
        self.db = db

    def append(
        self,
        avatar_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        aggregate_type: str = "avatar",
        aggregate_id: str = "",
        idempotency_key: str = "",
        publish: bool = False,
    ) -> str:
        now = int(time.time())
        event_id = uuid4().hex
        with self.db.transaction() as connection:
            if idempotency_key:
                existing = connection.execute(
                    "SELECT event_id FROM domain_events WHERE idempotency_key=?", (idempotency_key,)
                ).fetchone()
                if existing:
                    return str(existing["event_id"])
            connection.execute(
                """
                INSERT INTO domain_events
                (event_id,avatar_id,aggregate_type,aggregate_id,event_type,payload_json,idempotency_key,created_at)
                VALUES(?,?,?,?,?,?,?,?)
                """,
                (
                    event_id,
                    avatar_id,
                    aggregate_type[:80],
                    (aggregate_id or avatar_id)[:200],
                    event_type[:120],
                    json.dumps(payload or {}, ensure_ascii=False),
                    idempotency_key[:200],
                    now,
                ),
            )
            if publish:
                connection.execute(
                    "INSERT INTO event_outbox(event_id,status,attempts,available_at,created_at,updated_at) VALUES(?,'pending',0,?,?,?)",
                    (event_id, now, now, now),
                )
        return event_id

    def list(self, avatar_id: str, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.all(
            "SELECT * FROM domain_events WHERE avatar_id=? ORDER BY id DESC LIMIT ?",
            (avatar_id, max(1, min(500, limit))),
        )
        for row in rows:
            row["payload"] = json.loads(row.pop("payload_json", "{}"))
        return rows

    def claim(self, limit: int = 50) -> list[dict[str, Any]]:
        now = int(time.time())
        with self.db.transaction() as connection:
            connection.execute(
                "UPDATE event_outbox SET status='pending',updated_at=? WHERE status='processing' AND updated_at<?",
                (now, now - 300),
            )
            rows = connection.execute(
                """SELECT o.id outbox_id,e.* FROM event_outbox o JOIN domain_events e ON e.event_id=o.event_id
                   WHERE o.status='pending' AND o.available_at<=? ORDER BY o.id LIMIT ?""",
                (now, max(1, min(500, limit))),
            ).fetchall()
            ids = [int(row["outbox_id"]) for row in rows]
            if ids:
                marks = ",".join("?" for _ in ids)
                connection.execute(
                    f"UPDATE event_outbox SET status='processing',attempts=attempts+1,updated_at=? WHERE id IN ({marks})",
                    (now, *ids),
                )
        return [dict(row) for row in rows]

    def delivered(self, outbox_id: int) -> None:
        now = int(time.time())
        self.db.execute(
            "UPDATE event_outbox SET status='delivered',delivered_at=?,updated_at=?,last_error='' WHERE id=?",
            (now, now, outbox_id),
        )

    def failed(self, outbox_id: int, error: str) -> None:
        row = self.db.one("SELECT attempts FROM event_outbox WHERE id=?", (outbox_id,)) or {"attempts": 1}
        now = int(time.time())
        delay = min(3600, 2 ** min(10, max(1, int(row["attempts"]))))
        self.db.execute(
            "UPDATE event_outbox SET status='pending',available_at=?,updated_at=?,last_error=? WHERE id=?",
            (now + delay, now, str(error)[:1000], outbox_id),
        )

