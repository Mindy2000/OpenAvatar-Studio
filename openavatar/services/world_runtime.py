from __future__ import annotations

import json
import time
from typing import Any

from openavatar.db import Database
from openavatar.services.world_model import propose_fact
from openavatar.services.world_regions import avatar_language_profile


MINOR_EVENTS = [
    ("minor_routine_shift", "日程发生轻微变化", "今天的节奏比原计划略有调整。", {"resource.energy": -0.04, "resource.stress": 0.03}),
    ("minor_social_ping", "收到一条普通消息", "关系网络里出现了一个低影响互动。", {"resource.social_battery": -0.02}),
    ("minor_focus_gain", "完成一小段任务", "一个小任务向前推进了一点。", {"resource.energy": -0.03, "resource.stress": -0.02}),
]


def _context(db: Database, avatar_id: str) -> dict[str, Any]:
    avatar = db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,)) or {}
    return avatar_language_profile(avatar)


def _loads(raw: str, fallback: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def ensure_runtime(db: Database, avatar_id: str) -> None:
    now = int(time.time())
    context = _context(db, avatar_id)
    rules = context["world_region_rules"]
    db.execute("INSERT OR IGNORE INTO world_runtime_settings(avatar_id,updated_at) VALUES(?,?)", (avatar_id, now))
    defaults = {
        "resource.energy": 0.72,
        "resource.stress": 0.28,
        "resource.social_battery": 0.70,
        "runtime.current_activity": "未设定",
        "runtime.current_place": "未设定",
        "runtime.mood": "平静",
        "world.region": context["world_region"],
        "world.region_rules": {
            "name": rules.get("name_zh"),
            "daily_clock": rules.get("daily_clock", []),
            "social_rules": rules.get("social_rules", []),
            "holidays": rules.get("holidays", []),
        },
    }
    for key, value in defaults.items():
        if not db.one("SELECT id FROM world_facts WHERE avatar_id=? AND fact_key=? AND active=1", (avatar_id, key)):
            propose_fact(
                db,
                avatar_id,
                fact_key=key,
                value=value,
                reality_kind="fictional_runtime",
                mutability="evolving",
                reason="世界运行引擎初始化",
            )


def runtime_state(db: Database, avatar_id: str) -> dict[str, Any]:
    ensure_runtime(db, avatar_id)
    context = _context(db, avatar_id)
    settings = db.one("SELECT * FROM world_runtime_settings WHERE avatar_id=?", (avatar_id,)) or {}
    facts = db.all(
        "SELECT fact_key,fact_value_json,reality_kind,mutability,updated_at FROM world_facts WHERE avatar_id=? AND active=1 ORDER BY fact_key",
        (avatar_id,),
    )
    events = db.all(
        "SELECT id,event_key,title,summary,event_kind,status,occurred_at,payload_json,created_at FROM world_events WHERE avatar_id=? ORDER BY id DESC LIMIT 30",
        (avatar_id,),
    )
    conflicts = db.all(
        "SELECT id,fact_key,reason,status,review_note,created_at,resolved_at FROM world_conflicts WHERE avatar_id=? ORDER BY id DESC LIMIT 50",
        (avatar_id,),
    )
    for row in facts:
        row["value"] = _loads(row.pop("fact_value_json"), None)
    for row in events:
        row["payload"] = _loads(row.pop("payload_json"), {})
    return {
        "language_profile": context,
        "settings": {key: bool(value) if key.endswith("_enabled") or key in {"auto_minor_events", "high_impact_requires_review", "rollback_enabled"} else value for key, value in settings.items() if key != "avatar_id"},
        "facts": facts,
        "events": events,
        "conflicts": conflicts,
    }


def snapshot_world(db: Database, avatar_id: str, event_id: int = 0) -> int:
    ensure_runtime(db, avatar_id)
    facts = db.all("SELECT * FROM world_facts WHERE avatar_id=? AND active=1 ORDER BY fact_key", (avatar_id,))
    settings = db.one("SELECT * FROM world_runtime_settings WHERE avatar_id=?", (avatar_id,)) or {}
    now = int(time.time())
    day_key = time.strftime("%Y-%m-%d", time.localtime(now))
    snapshot_id = db.execute(
        "INSERT INTO world_snapshots(avatar_id,event_id,day_key,facts_json,settings_json,created_at) VALUES(?,?,?,?,?,?)",
        (avatar_id, event_id, day_key, json.dumps(facts, ensure_ascii=False), json.dumps(settings, ensure_ascii=False), now),
    )
    db.execute(
        "DELETE FROM world_snapshots WHERE avatar_id=? AND rolled_back_at<>0 AND id NOT IN (SELECT id FROM world_snapshots WHERE avatar_id=? ORDER BY id DESC LIMIT 200)",
        (avatar_id, avatar_id),
    )
    return snapshot_id


def advance_world(db: Database, avatar_id: str, *, seconds: int = 3600, force_minor_event: bool = False) -> dict[str, Any]:
    ensure_runtime(db, avatar_id)
    settings = db.one("SELECT * FROM world_runtime_settings WHERE avatar_id=?", (avatar_id,)) or {}
    if not bool(settings.get("engine_enabled", True)):
        return {"advanced": False, "reason": "世界运行引擎未启用", **runtime_state(db, avatar_id)}
    now = int(time.time())
    snapshot_world(db, avatar_id)
    previous_seconds = int(settings.get("active_seconds") or 0)
    active_seconds = previous_seconds + max(0, min(int(seconds), 86400 * 7))
    db.execute(
        "UPDATE world_runtime_settings SET active_seconds=?,last_advanced_at=?,updated_at=? WHERE avatar_id=?",
        (active_seconds, now, now, avatar_id),
    )
    context = _context(db, avatar_id)
    daily_clock = list(context["world_region_rules"].get("daily_clock") or ["日常活动"])
    local_minute = (active_seconds // 60) % 1440
    phase_index = min(len(daily_clock) - 1, local_minute * len(daily_clock) // 1440)
    for key, value in {
        "runtime.current_activity": str(daily_clock[phase_index]),
        "runtime.local_minute": local_minute,
        "runtime.day_index": active_seconds // 86400,
    }.items():
        propose_fact(
            db,
            avatar_id,
            fact_key=key,
            value=value,
            reality_kind="fictional_runtime",
            mutability="evolving",
            reason="世界时钟推进",
        )
    created_event: dict[str, Any] | None = None
    previous_bucket = previous_seconds // 21600
    current_bucket = active_seconds // 21600
    should_create_event = force_minor_event or (
        bool(settings.get("auto_minor_events", True)) and current_bucket > previous_bucket
    )
    if should_create_event:
        region_events = context["world_region_rules"].get("event_pool") or MINOR_EVENTS
        index = current_bucket % len(region_events)
        event_key, title, summary, effects = region_events[index]
        unique_event_key = f"{event_key}_{current_bucket}"
        existing_event = db.one(
            "SELECT * FROM world_events WHERE avatar_id=? AND event_key=?", (avatar_id, unique_event_key)
        )
        event_id = int(existing_event["id"]) if existing_event else db.execute(
            "INSERT INTO world_events(avatar_id,event_key,title,summary,event_kind,status,occurred_at,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (
                avatar_id,
                unique_event_key,
                title,
                summary,
                "minor_runtime",
                "fact",
                now,
                json.dumps({"active_seconds": active_seconds, "effects": effects, "world_region": context["world_region"]}, ensure_ascii=False),
                now,
            ),
        )
        for key, delta in ({} if existing_event else effects).items():
            row = db.one("SELECT fact_value_json FROM world_facts WHERE avatar_id=? AND fact_key=? AND active=1", (avatar_id, key))
            current = _loads(str(row["fact_value_json"]), 0.5) if row else 0.5
            try:
                value = max(0.0, min(1.0, float(current) + float(delta)))
            except (TypeError, ValueError):
                value = current
            propose_fact(db, avatar_id, fact_key=key, value=value, reality_kind="fictional_runtime", mutability="evolving", reason=f"事件 {title} 的轻微影响")
        created_event = db.one("SELECT * FROM world_events WHERE id=?", (event_id,))
    return {"advanced": True, "event": created_event, **runtime_state(db, avatar_id)}


def rollback_last_event(db: Database, avatar_id: str) -> dict[str, Any]:
    ensure_runtime(db, avatar_id)
    settings = db.one("SELECT * FROM world_runtime_settings WHERE avatar_id=?", (avatar_id,)) or {}
    if not bool(settings.get("rollback_enabled", True)):
        return {"rolled_back": False, "reason": "回滚未启用", **runtime_state(db, avatar_id)}
    snapshot = db.one("SELECT * FROM world_snapshots WHERE avatar_id=? AND rolled_back_at=0 ORDER BY id DESC LIMIT 1", (avatar_id,))
    if not snapshot:
        return {"rolled_back": False, "reason": "没有可回滚快照", **runtime_state(db, avatar_id)}
    facts = _loads(str(snapshot.get("facts_json")), [])
    saved_settings = _loads(str(snapshot.get("settings_json")), {})
    now = int(time.time())
    with db.transaction() as connection:
        connection.execute("UPDATE world_facts SET active=0,updated_at=? WHERE avatar_id=?", (now, avatar_id))
        for row in facts:
            if not isinstance(row, dict):
                continue
            connection.execute(
                "INSERT INTO world_facts(avatar_id,fact_key,fact_value_json,reality_kind,mutability,status,source_evidence_id,confidence,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)",
                (
                    avatar_id,
                    str(row.get("fact_key", ""))[:200],
                    str(row.get("fact_value_json", "null"))[:100000],
                    str(row.get("reality_kind", "fictional_runtime"))[:80],
                    str(row.get("mutability", "evolving"))[:80],
                    str(row.get("status", "fact"))[:50],
                    row.get("source_evidence_id"),
                    float(row.get("confidence", 1)),
                    int(bool(row.get("active", True))),
                    int(row.get("created_at", now)),
                    now,
                ),
            )
        if isinstance(saved_settings, dict):
            connection.execute(
                "UPDATE world_runtime_settings SET active_seconds=?,last_advanced_at=?,updated_at=? WHERE avatar_id=?",
                (int(saved_settings.get("active_seconds", 0)), int(saved_settings.get("last_advanced_at", 0)), now, avatar_id),
            )
        connection.execute("UPDATE world_snapshots SET rolled_back_at=? WHERE id=?", (now, snapshot["id"]))
    return {"rolled_back": True, "snapshot_id": snapshot["id"], **runtime_state(db, avatar_id)}


def scan_consistency(db: Database, avatar_id: str, *, repair: bool = False) -> dict[str, Any]:
    ensure_runtime(db, avatar_id)
    context = _context(db, avatar_id)
    region_rules = context["world_region_rules"]
    facts = db.all("SELECT * FROM world_facts WHERE avatar_id=? AND active=1 ORDER BY fact_key,id", (avatar_id,))
    seen: dict[str, dict[str, Any]] = {}
    conflicts: list[dict[str, Any]] = []
    now = int(time.time())
    for row in facts:
        key = str(row["fact_key"])
        value = str(row["fact_value_json"])
        if key in seen and str(seen[key]["fact_value_json"]) != value:
            conflict_id = db.execute(
                "INSERT INTO world_conflicts(avatar_id,fact_key,existing_value_json,candidate_value_json,reason,created_at) VALUES(?,?,?,?,?,?)",
                (avatar_id, key, str(seen[key]["fact_value_json"]), value, "同一 fact_key 出现不同 active 值", now),
            )
            conflicts.append(dict(db.one("SELECT * FROM world_conflicts WHERE id=?", (conflict_id,))))
            if repair and str(row["mutability"]) == "evolving":
                db.execute("UPDATE world_facts SET active=0,updated_at=? WHERE id=?", (now, row["id"]))
        else:
            seen[key] = row
    joined = " ".join(str(row.get("fact_key", "")) + " " + str(row.get("fact_value_json", "")) for row in facts)
    missing = [keyword for keyword in region_rules.get("consistency_keywords", []) if keyword and keyword not in joined]
    if missing and context["world_region"] != "custom":
        existing_region_conflict = db.one(
            "SELECT * FROM world_conflicts WHERE avatar_id=? AND fact_key=? AND status='open' ORDER BY id DESC LIMIT 1",
            (avatar_id, "world.region_consistency"),
        )
        if not existing_region_conflict:
            conflict_id = db.execute(
                "INSERT INTO world_conflicts(avatar_id,fact_key,existing_value_json,candidate_value_json,reason,created_at) VALUES(?,?,?,?,?,?)",
                (
                    avatar_id,
                    "world.region_consistency",
                    json.dumps({"world_region": context["world_region"]}, ensure_ascii=False),
                    json.dumps({"missing_region_signals": missing[:8]}, ensure_ascii=False),
                    f"当前世界场景是 {region_rules.get('name_zh')}，但设定中缺少部分地区语境信号：{', '.join(missing[:5])}",
                    now,
                ),
            )
            conflicts.append(dict(db.one("SELECT * FROM world_conflicts WHERE id=?", (conflict_id,))))
    open_count = int((db.one("SELECT COUNT(*) AS count FROM world_conflicts WHERE avatar_id=? AND status='open'", (avatar_id,)) or {"count": 0})["count"])
    return {"conflicts": conflicts, "open_count": open_count, "repaired": bool(repair), "world_region": context["world_region"]}


def resolve_conflict(db: Database, avatar_id: str, conflict_id: int, action: str, note: str = "") -> dict[str, Any]:
    row = db.one("SELECT * FROM world_conflicts WHERE id=? AND avatar_id=?", (conflict_id, avatar_id))
    if not row:
        raise KeyError("世界冲突不存在")
    if action not in {"keep_existing", "accept_candidate", "dismiss"}:
        raise ValueError("冲突处理动作不合法")
    now = int(time.time())
    if action == "accept_candidate":
        propose_fact(
            db,
            avatar_id,
            fact_key=str(row["fact_key"]),
            value=_loads(str(row["candidate_value_json"]), None),
            reality_kind="fictional_runtime",
            mutability="evolving",
            reason="用户接受冲突候选值",
        )
    db.execute(
        "UPDATE world_conflicts SET status=?,review_note=?,resolved_at=? WHERE id=?",
        (action, note[:1000], now, conflict_id),
    )
    return dict(db.one("SELECT * FROM world_conflicts WHERE id=?", (conflict_id,)))
