from __future__ import annotations

import json
import time
import uuid
from typing import Any

from openavatar.db import Database


VALID_JOB_TYPES = {"persona", "memory", "voice", "visual", "video", "evaluation"}
TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


def create_job(
    db: Database,
    avatar_id: str,
    job_type: str,
    *,
    provider: str = "",
    status: str = "queued",
    stage: str = "等待开始",
    input_summary: str = "",
    estimated_cost: float = 0,
    currency: str = "CNY",
) -> dict[str, Any]:
    if job_type not in VALID_JOB_TYPES:
        raise ValueError(f"不支持的训练任务类型：{job_type}")
    job_id = uuid.uuid4().hex
    now = int(time.time())
    db.execute(
        "INSERT INTO training_jobs(id,avatar_id,job_type,provider,status,progress,stage,input_summary,estimated_cost,currency,created_at,updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?)",
        (job_id, avatar_id, job_type, provider, status, 0, stage, input_summary, estimated_cost, currency, now, now),
    )
    return get_job(db, job_id)


def get_job(db: Database, job_id: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM training_jobs WHERE id=?", (job_id,))
    if not row:
        raise KeyError("训练任务不存在")
    row["result"] = json.loads(row.pop("result_json", "{}"))
    row["cancel_requested"] = bool(row["cancel_requested"])
    return row


def list_jobs(db: Database, avatar_id: str) -> list[dict[str, Any]]:
    rows = db.all("SELECT * FROM training_jobs WHERE avatar_id=? ORDER BY created_at DESC", (avatar_id,))
    for row in rows:
        row["result"] = json.loads(row.pop("result_json", "{}"))
        row["cancel_requested"] = bool(row["cancel_requested"])
    return rows


def update_job(
    db: Database,
    job_id: str,
    *,
    status: str | None = None,
    progress: int | None = None,
    stage: str | None = None,
    result: dict[str, Any] | None = None,
    error: str | None = None,
    actual_cost: float | None = None,
) -> dict[str, Any]:
    current = get_job(db, job_id)
    now = int(time.time())
    fields = ["updated_at=?"]
    params: list[Any] = [now]
    values = {
        "status": status,
        "progress": min(max(progress, 0), 100) if progress is not None else None,
        "stage": stage,
        "result_json": json.dumps(result, ensure_ascii=False) if result is not None else None,
        "error": error,
        "actual_cost": actual_cost,
    }
    for key, value in values.items():
        if value is not None:
            fields.append(f"{key}=?")
            params.append(value)
    if status == "running" and not current.get("started_at"):
        fields.append("started_at=?")
        params.append(now)
    if status in TERMINAL_STATUSES:
        fields.append("finished_at=?")
        params.append(now)
    params.append(job_id)
    db.execute(f"UPDATE training_jobs SET {', '.join(fields)} WHERE id=?", tuple(params))
    return get_job(db, job_id)


def claim_job(db: Database, job_id: str, *, allowed_statuses: tuple[str, ...]) -> bool:
    if not allowed_statuses:
        return False
    placeholders = ",".join("?" for _ in allowed_statuses)
    now = int(time.time())
    with db.transaction() as connection:
        cursor = connection.execute(
            f"UPDATE training_jobs SET status='submitting',stage='正在安全提交任务',started_at=COALESCE(started_at,?),updated_at=? "
            f"WHERE id=? AND status IN ({placeholders})",
            (now, now, job_id, *allowed_statuses),
        )
        return cursor.rowcount == 1


def request_cancel(db: Database, job_id: str) -> dict[str, Any]:
    current = get_job(db, job_id)
    if current["status"] in TERMINAL_STATUSES:
        return current
    db.execute("UPDATE training_jobs SET cancel_requested=1,stage='正在取消',updated_at=? WHERE id=?", (int(time.time()), job_id))
    return get_job(db, job_id)


def retry_job(db: Database, job_id: str) -> dict[str, Any]:
    current = get_job(db, job_id)
    if current["status"] not in {"failed", "cancelled"}:
        raise ValueError("只有失败或取消的任务可以重试")
    now = int(time.time())
    db.execute(
        "UPDATE training_jobs SET status='queued',progress=0,stage='等待重试',error='',result_json='{}',cancel_requested=0,attempt=attempt+1,updated_at=?,started_at=NULL,finished_at=NULL WHERE id=?",
        (now, job_id),
    )
    return get_job(db, job_id)
