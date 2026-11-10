"""SQLite-backed durable queue with atomic claims, fencing tokens and leases.

Lease expiry makes abandoned work eligible for another worker. External side
 effects cannot be made exactly-once; callers must make stages idempotent.
"""
from __future__ import annotations

import random
import time
import uuid
from dataclasses import dataclass


@dataclass(frozen=True)
class WorkItem:
    id: int
    video_id: str
    stage: str
    token: str
    attempts: int


class WorkQueue:
    def __init__(self, db):
        self.db = db

    def enqueue(self, video_id: str, stage: str = "pipeline", max_attempts: int = 3,
                batch_id: str | None = None, retry_failed: bool = False) -> None:
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        now = time.time()
        with self.db.connect() as conn:
            # A running item must never be reset by a concurrent discovery.
            conn.execute(
                """INSERT INTO work_items(video_id,stage,status,attempts,max_attempts,
                   available_at,updated_at,batch_id) VALUES (?,?,'pending',0,?,?,?,?)
                   ON CONFLICT(video_id,stage) DO UPDATE SET
                     status=CASE
                       WHEN work_items.status='failed' AND NOT ? THEN 'failed'
                       WHEN work_items.status IN ('running','pending') THEN work_items.status
                       ELSE 'pending' END,
                     attempts=CASE
                       WHEN work_items.status='completed' OR (work_items.status='failed' AND ?) THEN 0
                       ELSE work_items.attempts END,
                     available_at=CASE
                       WHEN work_items.status IN ('running','pending') THEN work_items.available_at
                       ELSE excluded.available_at END,
                     max_attempts=excluded.max_attempts,
                     updated_at=excluded.updated_at,
                     batch_id=CASE WHEN work_items.status='running' THEN work_items.batch_id ELSE excluded.batch_id END""",
                (video_id, stage, max_attempts, now, now, batch_id, int(retry_failed), int(retry_failed)),
            )

    def claim(self, stage: str = "pipeline", lease_seconds: int = 600,
              batch_id: str | None = None) -> WorkItem | None:
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        now = time.time()
        token = uuid.uuid4().hex
        with self.db.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            # Exhausted leases become terminal rather than blocking the queue forever.
            conn.execute("""UPDATE work_items SET status='failed',lease_token=NULL,lease_until=NULL,
                last_error='Lease expired at retry limit',updated_at=?
                WHERE status='running' AND lease_until<? AND attempts>=max_attempts""", (now, now))
            query = """SELECT id,video_id,stage,attempts FROM work_items
                WHERE stage=? AND attempts < max_attempts
                AND ((status='pending' AND available_at<=?)
                     OR (status='running' AND lease_until<?))"""
            params: list = [stage, now, now]
            if batch_id is not None:
                query += " AND batch_id=?"
                params.append(batch_id)
            query += " ORDER BY available_at,id LIMIT 1"
            row = conn.execute(query, params).fetchone()
            if row is None:
                return None
            conn.execute(
                """UPDATE work_items SET status='running', attempts=attempts+1,
                   lease_token=?,lease_until=?,updated_at=? WHERE id=?""",
                (token, now + lease_seconds, now, row['id']),
            )
            return WorkItem(row['id'], row['video_id'], row['stage'], token, row['attempts'] + 1)

    def renew(self, item: WorkItem, lease_seconds: int = 600) -> bool:
        now = time.time()
        with self.db.connect() as conn:
            cur = conn.execute(
                """UPDATE work_items SET lease_until=?,updated_at=? WHERE id=?
                   AND status='running' AND lease_token=? AND lease_until>?""",
                (now + lease_seconds, now, item.id, item.token, now),
            )
            return cur.rowcount == 1

    def finish(self, item: WorkItem) -> bool:
        with self.db.connect() as conn:
            cur = conn.execute(
                """UPDATE work_items SET status='completed',lease_until=NULL,
                   lease_token=NULL,updated_at=? WHERE id=? AND status='running'
                   AND lease_token=? AND lease_until>?""",
                (time.time(), item.id, item.token, time.time()),
            )
            return cur.rowcount == 1

    def fail(self, item: WorkItem, error: Exception | str, backoff_base: float = 5.0) -> str:
        """Reschedule with jitter; dead-letter after configured max attempts."""
        now = time.time()
        with self.db.connect() as conn:
            row = conn.execute(
                "SELECT attempts,max_attempts FROM work_items WHERE id=? AND lease_token=? AND status='running' AND lease_until>?",
                (item.id, item.token, now),
            ).fetchone()
            if row is None:
                return 'lost-lease'
            terminal = row['attempts'] >= row['max_attempts']
            status = 'failed' if terminal else 'pending'
            delay = min(3600.0, backoff_base * (2 ** min(row['attempts'] - 1, 10)))
            delay *= random.uniform(0.8, 1.2)
            conn.execute(
                """UPDATE work_items SET status=?,available_at=?,last_error=?,
                   lease_until=NULL,lease_token=NULL,updated_at=? WHERE id=? AND lease_token=?""",
                (status, now if terminal else now + delay, str(error)[:2000], now, item.id, item.token),
            )
            return status

    def summary(self, batch_id: str | None = None) -> dict[str, int]:
        with self.db.connect() as conn:
            if batch_id is None:
                rows = conn.execute("SELECT status,COUNT(*) n FROM work_items GROUP BY status")
            else:
                rows = conn.execute(
                    "SELECT status,COUNT(*) n FROM work_items WHERE batch_id=? GROUP BY status",
                    (batch_id,),
                )
            return {row['status']: row['n'] for row in rows}
