from __future__ import annotations

import asyncio
import threading
import time
from collections import defaultdict
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any
from uuid import uuid4

from openavatar.db import Database


class RunRegistry:
    """Tracks cancellable foreground work without persisting user content."""

    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._runs: dict[str, dict[str, Any]] = {}

    def start(self, avatar_id: str, kind: str) -> tuple[str, threading.Event]:
        run_id = uuid4().hex
        cancelled = threading.Event()
        with self._lock:
            self._runs[run_id] = {
                "run_id": run_id,
                "avatar_id": avatar_id,
                "kind": kind,
                "started_at": int(time.time()),
                "cancelled": cancelled,
            }
        return run_id, cancelled

    def finish(self, run_id: str) -> None:
        with self._lock:
            self._runs.pop(run_id, None)

    def cancel(self, run_id: str, avatar_id: str = "") -> bool:
        with self._lock:
            item = self._runs.get(run_id)
            if not item or (avatar_id and item["avatar_id"] != avatar_id):
                return False
            item["cancelled"].set()
            return True

    def snapshot(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {key: value for key, value in item.items() if key != "cancelled"}
                | {"cancel_requested": item["cancelled"].is_set()}
                for item in self._runs.values()
            ]


class Metrics:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._counters: defaultdict[str, int] = defaultdict(int)
        self._samples: defaultdict[str, list[float]] = defaultdict(list)

    def increment(self, name: str, amount: int = 1) -> None:
        with self._lock:
            self._counters[name] += amount

    def observe(self, name: str, value: float) -> None:
        with self._lock:
            samples = self._samples[name]
            samples.append(float(value))
            if len(samples) > 500:
                del samples[:-500]

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            observations = {}
            for name, values in self._samples.items():
                ordered = sorted(values)
                observations[name] = {
                    "count": len(values),
                    "average": round(sum(values) / len(values), 3),
                    "p95": round(ordered[min(len(ordered) - 1, int(len(ordered) * 0.95))], 3),
                }
            return {"counters": dict(self._counters), "observations": observations}


class LeaseManager:
    def __init__(self, db: Database, owner_id: str | None = None) -> None:
        self.db = db
        self.owner_id = owner_id or uuid4().hex

    def acquire(self, key: str, ttl_seconds: int) -> bool:
        now = int(time.time())
        expires = now + max(5, ttl_seconds)
        with self.db.transaction() as connection:
            connection.execute(
                """
                INSERT INTO scheduler_leases(lease_key,owner_id,expires_at,updated_at)
                VALUES(?,?,?,?)
                ON CONFLICT(lease_key) DO UPDATE SET
                  owner_id=excluded.owner_id,expires_at=excluded.expires_at,updated_at=excluded.updated_at
                WHERE scheduler_leases.expires_at<=? OR scheduler_leases.owner_id=excluded.owner_id
                """,
                (key, self.owner_id, expires, now, now),
            )
            row = connection.execute(
                "SELECT owner_id,expires_at FROM scheduler_leases WHERE lease_key=?", (key,)
            ).fetchone()
            return bool(row and row["owner_id"] == self.owner_id and int(row["expires_at"]) == expires)

    def release_all(self) -> None:
        self.db.execute("DELETE FROM scheduler_leases WHERE owner_id=?", (self.owner_id,))


@dataclass(frozen=True)
class PeriodicJob:
    name: str
    interval_seconds: float
    callback: Callable[[], Any | Awaitable[Any]]
    lease_seconds: int = 120


class BackgroundSupervisor:
    def __init__(self, leases: LeaseManager, metrics: Metrics) -> None:
        self.leases = leases
        self.metrics = metrics
        self._tasks: list[asyncio.Task[None]] = []
        self._stop = asyncio.Event()

    def start(self, jobs: list[PeriodicJob]) -> None:
        if self._tasks:
            return
        self._stop.clear()
        self._tasks = [asyncio.create_task(self._run(job), name=f"openavatar-{job.name}") for job in jobs]

    async def stop(self) -> None:
        self._stop.set()
        for task in self._tasks:
            task.cancel()
        if self._tasks:
            await asyncio.gather(*self._tasks, return_exceptions=True)
        self._tasks.clear()
        await asyncio.to_thread(self.leases.release_all)

    async def _run(self, job: PeriodicJob) -> None:
        while not self._stop.is_set():
            try:
                acquired = await asyncio.to_thread(self.leases.acquire, job.name, job.lease_seconds)
                if acquired:
                    result = job.callback()
                    if isinstance(result, Awaitable):
                        await result
                    self.metrics.increment(f"background.{job.name}.success")
            except asyncio.CancelledError:
                raise
            except Exception:
                self.metrics.increment(f"background.{job.name}.failure")
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=max(0.1, job.interval_seconds))
            except TimeoutError:
                pass

