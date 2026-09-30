from __future__ import annotations

import json
import time
from typing import Any

from openavatar.db import Database


def create_visual_review(db: Database, avatar_id: str, asset_id: int) -> dict[str, Any]:
    asset = db.one("SELECT * FROM visual_assets WHERE id=? AND avatar_id=?", (asset_id, avatar_id))
    if not asset:
        raise KeyError("视觉素材不存在")
    metadata = json.loads(str(asset.get("metadata_json") or "{}"))
    findings = [
        {"dimension": "route_label", "passed": bool(asset.get("asset_kind")), "note": f"视觉身份类型：{asset.get('asset_kind')}"},
        {"dimension": "approval_state", "passed": asset.get("status") in {"candidate", "approved", "canonical", "rejected", "retired"}, "note": f"当前状态：{asset.get('status')}"},
        {"dimension": "canonical_guard", "passed": asset.get("status") != "canonical" or bool(asset.get("approved_at")), "note": "canonical 需要审批时间记录"},
        {"dimension": "source_trace", "passed": bool(metadata.get("source_import_id") or asset.get("provider")), "note": "保留来源或 provider 线索"},
    ]
    score = round(sum(1 for item in findings if item["passed"]) / len(findings) * 100)
    now = int(time.time())
    review_id = db.execute(
        "INSERT INTO media_reviews(avatar_id,media_kind,asset_id,review_kind,status,score,findings_json,user_feedback_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (avatar_id, "visual", asset_id, "identity_consistency", "completed", score, json.dumps(findings, ensure_ascii=False), json.dumps({}, ensure_ascii=False), now, now),
    )
    return media_review(db, avatar_id, review_id)


def media_review(db: Database, avatar_id: str, review_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM media_reviews WHERE id=? AND avatar_id=?", (review_id, avatar_id))
    if not row:
        raise KeyError("媒体评审不存在")
    row["findings"] = json.loads(row.pop("findings_json", "[]"))
    row["user_feedback"] = json.loads(row.pop("user_feedback_json", "{}"))
    return row


def media_reviews(db: Database, avatar_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT id,media_kind,asset_id,review_kind,status,score,findings_json,user_feedback_json,created_at,updated_at FROM media_reviews WHERE avatar_id=? ORDER BY id DESC LIMIT ?",
        (avatar_id, min(max(limit, 1), 300)),
    )
    for row in rows:
        row["findings"] = json.loads(row.pop("findings_json", "[]"))
        row["user_feedback"] = json.loads(row.pop("user_feedback_json", "{}"))
    return rows


def record_media_feedback(db: Database, avatar_id: str, review_id: int, feedback: str, comment: str = "") -> dict[str, Any]:
    row = db.one("SELECT * FROM media_reviews WHERE id=? AND avatar_id=?", (review_id, avatar_id))
    if not row:
        raise KeyError("媒体评审不存在")
    payload = json.loads(str(row.get("user_feedback_json") or "{}"))
    payload.setdefault("items", []).append({"feedback": feedback[:80], "comment": comment[:1000], "created_at": int(time.time())})
    db.execute(
        "UPDATE media_reviews SET user_feedback_json=?,updated_at=? WHERE id=?",
        (json.dumps(payload, ensure_ascii=False), int(time.time()), review_id),
    )
    return media_review(db, avatar_id, review_id)
