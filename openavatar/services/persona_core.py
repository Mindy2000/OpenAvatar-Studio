from __future__ import annotations

import hashlib
import json
import time
from typing import Any

from openavatar.db import Database
from openavatar.services.memory_intelligence import memory_graph
from openavatar.services.persona import style_signature
from openavatar.services.world_regions import avatar_language_profile


def _digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def _safe_json(value: Any, fallback: Any) -> Any:
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def feedback_rules(db: Database, avatar_id: str) -> list[dict[str, Any]]:
    return db.all(
        "SELECT id,dimension,signal,rule_text,weight,active,created_at,updated_at FROM persona_feedback_rules WHERE avatar_id=? ORDER BY active DESC,id DESC LIMIT 100",
        (avatar_id,),
    )


def record_feedback_rule(db: Database, avatar_id: str, *, dimension: str, signal: str, rule_text: str, weight: float = 0.5) -> dict[str, Any]:
    now = int(time.time())
    rule_id = db.execute(
        "INSERT INTO persona_feedback_rules(avatar_id,dimension,signal,rule_text,weight,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
        (avatar_id, dimension[:80], signal[:80], rule_text[:1000], min(max(float(weight), 0), 1), 1, now, now),
    )
    return dict(db.one("SELECT * FROM persona_feedback_rules WHERE id=?", (rule_id,)))


def build_persona_core(db: Database, avatar_id: str) -> dict[str, Any]:
    avatar = db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,))
    if not avatar:
        raise KeyError("数字人不存在")
    persona = db.one("SELECT * FROM persona_profiles WHERE avatar_id=?", (avatar_id,)) or {}
    memories = db.all("SELECT speaker,content,is_avatar,kind,confidence FROM memories WHERE avatar_id=? AND confidence>0 ORDER BY id DESC LIMIT 800", (avatar_id,))
    world = db.all("SELECT fact_key,fact_value_json,reality_kind,mutability FROM world_facts WHERE avatar_id=? AND active=1 ORDER BY fact_key LIMIT 120", (avatar_id,))
    visual = db.one("SELECT * FROM visual_assets WHERE avatar_id=? AND status='canonical' ORDER BY id DESC LIMIT 1", (avatar_id,)) or {}
    visual_set = db.one("SELECT * FROM visual_asset_sets WHERE avatar_id=? AND set_type='identity' AND status IN ('canonical','approved') ORDER BY CASE status WHEN 'canonical' THEN 0 ELSE 1 END,updated_at DESC LIMIT 1", (avatar_id,)) or {}
    voice = db.one("SELECT * FROM voice_profiles WHERE avatar_id=? AND active=1 ORDER BY id DESC LIMIT 1", (avatar_id,)) or {}
    graph = memory_graph(db, avatar_id, 30)
    language_profile = avatar_language_profile(avatar)
    core = {
        "identity": {
            "id": avatar_id,
            "name": avatar["name"],
            "route": "fictional" if avatar["subject_kind"] == "fictional" else "real",
            "relationship": avatar["relationship"],
            "purpose": avatar["purpose"],
        },
        "persona": {
            "summary": persona.get("summary", ""),
            "traits": json.loads(str(persona.get("traits_json") or "[]")),
            "speaking_style": persona.get("speaking_style", ""),
            "boundaries": persona.get("boundaries", ""),
        },
        "style_signature": style_signature(memories),
        "language_profile": language_profile,
        "memory_graph": {
            "top_nodes": graph["nodes"][:12],
            "top_edges": graph["edges"][:12],
        },
        "world_context": [
            {
                "key": row["fact_key"],
                "value": json.loads(str(row["fact_value_json"])),
                "reality_kind": row["reality_kind"],
                "mutability": row["mutability"],
            }
            for row in world
        ],
        "visual_identity": {
            "status": visual_set.get("status", visual.get("status", "")),
            "label": visual_set.get("label", visual.get("label", "")),
            "asset_kind": visual.get("asset_kind", ""),
            "set_id": visual_set.get("id", ""),
            "invariants": _safe_json(visual_set.get("invariants_json", "[]"), []),
        },
        "voice_identity": {
            "provider": voice.get("provider", ""),
            "voice_name": voice.get("voice_name", ""),
            "profile_kind": voice.get("profile_kind", ""),
        },
        "feedback_rules": feedback_rules(db, avatar_id),
        "policy": {
            "do_not_invent_unsupported_facts": True,
            "locked_world_facts_require_approval": True,
            "preview_mode_until_required_complete": True,
        },
    }
    digest = _digest(core)
    now = int(time.time())
    db.execute(
        """
        INSERT INTO persona_core_profiles(avatar_id,core_json,source_digest,created_at,updated_at)
        VALUES(?,?,?,?,?)
        ON CONFLICT(avatar_id) DO UPDATE SET
          core_json=excluded.core_json,
          source_digest=excluded.source_digest,
          updated_at=excluded.updated_at
        """,
        (avatar_id, json.dumps(core, ensure_ascii=False), digest, now, now),
    )
    return {"digest": digest, "core": core, "updated_at": now}


def current_persona_core(db: Database, avatar_id: str) -> dict[str, Any]:
    row = db.one("SELECT core_json,source_digest,updated_at FROM persona_core_profiles WHERE avatar_id=?", (avatar_id,))
    if not row:
        return build_persona_core(db, avatar_id)
    return {"digest": row["source_digest"], "core": json.loads(str(row["core_json"])), "updated_at": row["updated_at"]}


def record_decision(
    db: Database,
    avatar_id: str,
    *,
    message_id: int = 0,
    decision_kind: str,
    input_summary: str,
    output_summary: str,
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    row_id = db.execute(
        "INSERT INTO decision_explanations(avatar_id,message_id,decision_kind,input_summary,output_summary,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
        (avatar_id, message_id, decision_kind[:80], input_summary[:1000], output_summary[:1000], json.dumps(metadata or {}, ensure_ascii=False), int(time.time())),
    )
    row = dict(db.one("SELECT * FROM decision_explanations WHERE id=?", (row_id,)))
    row["metadata"] = json.loads(row.pop("metadata_json", "{}"))
    return row


def decision_explanations(db: Database, avatar_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT id,message_id,decision_kind,input_summary,output_summary,metadata_json,created_at FROM decision_explanations WHERE avatar_id=? ORDER BY id DESC LIMIT ?",
        (avatar_id, min(max(limit, 1), 300)),
    )
    for row in rows:
        row["metadata"] = json.loads(row.pop("metadata_json", "{}"))
    return rows


def record_usage(db: Database, avatar_id: str, *, provider: str, model: str, role: str, operation: str, status: str = "ok", latency_ms: int = 0, metadata: dict[str, Any] | None = None) -> None:
    db.execute(
        "INSERT INTO usage_events(avatar_id,provider,model,role,operation,status,latency_ms,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (avatar_id, provider[:80], model[:200], role[:80], operation[:80], status[:50], max(0, int(latency_ms)), json.dumps(metadata or {}, ensure_ascii=False), int(time.time())),
    )


def usage_events(db: Database, avatar_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT id,provider,model,role,operation,status,latency_ms,estimated_cost,metadata_json,created_at FROM usage_events WHERE avatar_id=? ORDER BY id DESC LIMIT ?",
        (avatar_id, min(max(limit, 1), 500)),
    )
    for row in rows:
        row["metadata"] = json.loads(row.pop("metadata_json", "{}"))
    return rows
