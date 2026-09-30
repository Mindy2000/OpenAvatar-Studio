from __future__ import annotations

import json
import time
from typing import Any

from openavatar.db import Database


REALITY_KINDS = {"real_verified", "user_confirmed", "fictional_canon", "fictional_runtime", "hybrid_derived"}
MUTABILITY_KINDS = {"locked", "approval_only", "evolving", "historical"}
PROPOSAL_ACTIONS = {"approve", "reject"}


class WorldModelError(ValueError):
    pass


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _parse_value(value: str) -> Any:
    value = value.strip()
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return value


def propose_fact(
    db: Database,
    avatar_id: str,
    *,
    fact_key: str,
    value: Any,
    reality_kind: str = "fictional_runtime",
    mutability: str = "evolving",
    reason: str = "",
    source_evidence_id: int | None = None,
) -> dict[str, Any]:
    key = fact_key.strip()[:200]
    if not key:
        raise WorldModelError("世界事实需要 fact_key")
    if reality_kind not in REALITY_KINDS:
        raise WorldModelError("reality_kind 不合法")
    if mutability not in MUTABILITY_KINDS:
        raise WorldModelError("mutability 不合法")
    existing = db.one(
        "SELECT id,mutability,fact_value_json FROM world_facts WHERE avatar_id=? AND fact_key=? AND active=1",
        (avatar_id, key),
    )
    status = "pending"
    if existing and str(existing["mutability"]) in {"locked", "approval_only"}:
        reason = reason or f"现有事实为 {existing['mutability']}，需要明确审批"
    elif mutability == "evolving":
        status = "approved"
    open_row = db.one(
        "SELECT * FROM world_fact_proposals WHERE avatar_id=? AND fact_key=? AND status='pending'",
        (avatar_id, key),
    )
    if open_row and status == "pending":
        return open_row
    now = int(time.time())
    proposal_id = db.execute(
        """
        INSERT INTO world_fact_proposals
        (avatar_id,fact_key,fact_value_json,reality_kind,mutability,status,source_evidence_id,reason,created_at)
        VALUES(?,?,?,?,?,?,?,?,?)
        """,
        (avatar_id, key, _json(value), reality_kind, mutability, status, source_evidence_id, reason[:1000], now),
    )
    if status == "approved":
        _apply_fact(db, avatar_id, key, value, reality_kind, mutability, source_evidence_id, now)
        db.execute("UPDATE world_fact_proposals SET reviewed_at=?,review_note='自动批准可演化事实' WHERE id=?", (now, proposal_id))
    return dict(db.one("SELECT * FROM world_fact_proposals WHERE id=?", (proposal_id,)))


def _apply_fact(
    db: Database,
    avatar_id: str,
    fact_key: str,
    value: Any,
    reality_kind: str,
    mutability: str,
    source_evidence_id: int | None,
    now: int,
) -> None:
    db.execute("UPDATE world_facts SET active=0,updated_at=? WHERE avatar_id=? AND fact_key=? AND active=1", (now, avatar_id, fact_key))
    db.execute(
        """
        INSERT INTO world_facts
        (avatar_id,fact_key,fact_value_json,reality_kind,mutability,status,source_evidence_id,confidence,active,created_at,updated_at)
        VALUES(?,?,?,?,?,'fact',?,1,1,?,?)
        """,
        (avatar_id, fact_key, _json(value), reality_kind, mutability, source_evidence_id, now, now),
    )


def review_proposal(db: Database, avatar_id: str, proposal_id: int, action: str, note: str = "") -> dict[str, Any]:
    if action not in PROPOSAL_ACTIONS:
        raise WorldModelError("审批动作必须是 approve 或 reject")
    row = db.one("SELECT * FROM world_fact_proposals WHERE id=? AND avatar_id=?", (proposal_id, avatar_id))
    if not row:
        raise KeyError("世界事实提案不存在")
    if str(row["status"]) != "pending":
        return _public_proposal(row)
    now = int(time.time())
    if action == "approve":
        _apply_fact(
            db,
            avatar_id,
            str(row["fact_key"]),
            json.loads(str(row["fact_value_json"])),
            str(row["reality_kind"]),
            str(row["mutability"]),
            row["source_evidence_id"],
            now,
        )
        db.execute("UPDATE world_fact_proposals SET status='approved',review_note=?,reviewed_at=? WHERE id=?", (note[:1000], now, proposal_id))
    else:
        db.execute("UPDATE world_fact_proposals SET status='rejected',review_note=?,reviewed_at=? WHERE id=?", (note[:1000], now, proposal_id))
    return _public_proposal(db.one("SELECT * FROM world_fact_proposals WHERE id=?", (proposal_id,)))


def list_proposals(db: Database, avatar_id: str, status: str = "") -> list[dict[str, Any]]:
    if status:
        rows = db.all(
            "SELECT * FROM world_fact_proposals WHERE avatar_id=? AND status=? ORDER BY id DESC LIMIT 200",
            (avatar_id, status),
        )
    else:
        rows = db.all("SELECT * FROM world_fact_proposals WHERE avatar_id=? ORDER BY id DESC LIMIT 200", (avatar_id,))
    return [_public_proposal(row) for row in rows]


def _public_proposal(row: dict[str, Any]) -> dict[str, Any]:
    item = dict(row)
    item["value"] = json.loads(item.pop("fact_value_json"))
    return item


def create_fact_from_payload(db: Database, avatar_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    return _public_proposal(
        propose_fact(
            db,
            avatar_id,
            fact_key=str(payload.get("fact_key") or ""),
            value=_parse_value(str(payload.get("value") or "")),
            reality_kind=str(payload.get("reality_kind") or "fictional_runtime"),
            mutability=str(payload.get("mutability") or "evolving"),
            reason=str(payload.get("reason") or "用户在构建中心新增"),
        )
    )
