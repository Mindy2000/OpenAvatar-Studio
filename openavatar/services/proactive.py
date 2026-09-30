from __future__ import annotations

import json
import time
from typing import Any

from openavatar.db import Database


DEFAULT_RULES = {
    "daily_max": 2,
    "allowed_windows": [{"start": "09:00", "end": "22:30"}],
    "quiet_hours": {"start": "23:00", "end": "08:30"},
    "topic_scope": ["近况", "关心", "延续上次话题"],
    "use_long_term_memory": True,
    "allow_world_event_advancement": False,
    "tone": "自然、简短、有边界感",
    "cooldown_after_user_reply_minutes": 120,
}


def _minute_of_day(value: str) -> int | None:
    try:
        hour, minute = value.split(":", 1)
        hour_value, minute_value = int(hour), int(minute)
        if 0 <= hour_value <= 23 and 0 <= minute_value <= 59:
            return hour_value * 60 + minute_value
    except (AttributeError, TypeError, ValueError):
        pass
    return None


def _inside_window(now_minute: int, start: object, end: object) -> bool:
    start_minute = _minute_of_day(str(start or ""))
    end_minute = _minute_of_day(str(end or ""))
    if start_minute is None or end_minute is None:
        return False
    if start_minute <= end_minute:
        return start_minute <= now_minute < end_minute
    return now_minute >= start_minute or now_minute < end_minute


def proactive_time_allowed(rules: dict[str, Any], timestamp: int | None = None) -> bool:
    local = time.localtime(timestamp or time.time())
    now_minute = local.tm_hour * 60 + local.tm_min
    quiet = rules.get("quiet_hours") if isinstance(rules.get("quiet_hours"), dict) else {}
    if _inside_window(now_minute, quiet.get("start"), quiet.get("end")):
        return False
    windows = rules.get("allowed_windows") if isinstance(rules.get("allowed_windows"), list) else []
    return not windows or any(
        isinstance(window, dict) and _inside_window(now_minute, window.get("start"), window.get("end"))
        for window in windows
    )


def ensure_proactive_rules(db: Database, avatar_id: str) -> None:
    now = int(time.time())
    db.execute(
        """
        INSERT OR IGNORE INTO proactive_rules
        (avatar_id,daily_max,allowed_windows_json,quiet_hours_json,topic_scope_json,
         use_long_term_memory,allow_world_event_advancement,tone,cooldown_after_user_reply_minutes,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        """,
        (
            avatar_id,
            DEFAULT_RULES["daily_max"],
            json.dumps(DEFAULT_RULES["allowed_windows"], ensure_ascii=False),
            json.dumps(DEFAULT_RULES["quiet_hours"], ensure_ascii=False),
            json.dumps(DEFAULT_RULES["topic_scope"], ensure_ascii=False),
            1,
            0,
            DEFAULT_RULES["tone"],
            DEFAULT_RULES["cooldown_after_user_reply_minutes"],
            now,
        ),
    )


def get_proactive_rules(db: Database, avatar_id: str) -> dict[str, Any]:
    ensure_proactive_rules(db, avatar_id)
    row = db.one("SELECT * FROM proactive_rules WHERE avatar_id=?", (avatar_id,)) or {}
    return {
        "daily_max": int(row.get("daily_max") or DEFAULT_RULES["daily_max"]),
        "allowed_windows": json.loads(str(row.get("allowed_windows_json") or "[]")),
        "quiet_hours": json.loads(str(row.get("quiet_hours_json") or "{}")),
        "topic_scope": json.loads(str(row.get("topic_scope_json") or "[]")),
        "use_long_term_memory": bool(row.get("use_long_term_memory", True)),
        "allow_world_event_advancement": bool(row.get("allow_world_event_advancement", False)),
        "tone": str(row.get("tone") or DEFAULT_RULES["tone"]),
        "cooldown_after_user_reply_minutes": int(row.get("cooldown_after_user_reply_minutes") or DEFAULT_RULES["cooldown_after_user_reply_minutes"]),
        "updated_at": int(row.get("updated_at") or 0),
    }


def update_proactive_rules(db: Database, avatar_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    ensure_proactive_rules(db, avatar_id)
    allowed_windows = payload.get("allowed_windows")
    if not isinstance(allowed_windows, list):
        allowed_windows = DEFAULT_RULES["allowed_windows"]
    quiet_hours = payload.get("quiet_hours")
    if not isinstance(quiet_hours, dict):
        quiet_hours = DEFAULT_RULES["quiet_hours"]
    topic_scope = payload.get("topic_scope")
    if not isinstance(topic_scope, list):
        topic_scope = DEFAULT_RULES["topic_scope"]
    now = int(time.time())
    db.execute(
        """
        UPDATE proactive_rules SET
          daily_max=?,
          allowed_windows_json=?,
          quiet_hours_json=?,
          topic_scope_json=?,
          use_long_term_memory=?,
          allow_world_event_advancement=?,
          tone=?,
          cooldown_after_user_reply_minutes=?,
          updated_at=?
        WHERE avatar_id=?
        """,
        (
            min(max(int(payload.get("daily_max") or 2), 0), 24),
            json.dumps(allowed_windows[:8], ensure_ascii=False),
            json.dumps(quiet_hours, ensure_ascii=False),
            json.dumps([str(item)[:80] for item in topic_scope[:20]], ensure_ascii=False),
            int(bool(payload.get("use_long_term_memory", True))),
            int(bool(payload.get("allow_world_event_advancement", False))),
            str(payload.get("tone") or DEFAULT_RULES["tone"])[:500],
            min(max(int(payload.get("cooldown_after_user_reply_minutes") or 120), 15), 10080),
            now,
            avatar_id,
        ),
    )
    return get_proactive_rules(db, avatar_id)
