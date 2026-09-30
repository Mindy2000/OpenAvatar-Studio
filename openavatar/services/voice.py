from __future__ import annotations

import json
import time
from typing import Any

from openavatar.db import Database


DEVELOPMENT_VOICES = [
    {
        "provider": "piper",
        "voice_id": "zh_CN-xiao_ya-medium",
        "voice_name": "小雅（免费本地）",
        "profile_kind": "local_tts",
        "model": "piper-zh_CN-xiao_ya-medium",
        "license": "non-commercial",
        "note": "来自旧项目声音方案中的免费本地开发音色方向；用于联调，不代表上线默认。",
    },
    {
        "provider": "browser",
        "voice_id": "system-zh-CN",
        "voice_name": "浏览器中文系统音色",
        "profile_kind": "browser_tts",
        "model": "web-speech-api",
        "license": "system",
        "note": "可作为零成本试听音色，具体效果取决于用户设备。",
    },
    {
        "provider": "none",
        "voice_id": "",
        "voice_name": "暂不启用声音",
        "profile_kind": "none",
        "model": "",
        "license": "n/a",
        "note": "只构建文字数字人，不绑定声音。",
    },
]


def list_development_voices() -> list[dict[str, Any]]:
    return [dict(item) for item in DEVELOPMENT_VOICES]


def ensure_voice_choices(db: Database, avatar_id: str) -> None:
    existing = db.one("SELECT id FROM voice_profiles WHERE avatar_id=?", (avatar_id,))
    if existing:
        return
    now = int(time.time())
    with db.transaction() as connection:
        for index, voice in enumerate(DEVELOPMENT_VOICES):
            connection.execute(
                "INSERT INTO voice_profiles(avatar_id,provider,voice_id,voice_name,profile_kind,status,model,metadata_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    avatar_id,
                    voice["provider"],
                    voice["voice_id"],
                    voice["voice_name"],
                    voice["profile_kind"],
                    "candidate",
                    voice["model"],
                    json.dumps({"license": voice["license"], "note": voice["note"], "source_policy": "synthetic_or_builtin_only"}, ensure_ascii=False),
                    1 if index == 0 else 0,
                    now,
                ),
            )


def select_voice_profile(db: Database, avatar_id: str, profile_id: int) -> dict[str, Any]:
    row = db.one("SELECT * FROM voice_profiles WHERE id=? AND avatar_id=?", (profile_id, avatar_id))
    if not row:
        raise KeyError("声音档案不存在")
    with db.transaction() as connection:
        connection.execute("UPDATE voice_profiles SET active=0 WHERE avatar_id=?", (avatar_id,))
        connection.execute("UPDATE voice_profiles SET active=1,status='approved' WHERE id=?", (profile_id,))
    selected = db.one("SELECT * FROM voice_profiles WHERE id=?", (profile_id,))
    result = dict(selected)
    result["metadata"] = json.loads(result.pop("metadata_json", "{}"))
    result["active"] = bool(result["active"])
    return result


def create_voice_profile(db: Database, avatar_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    provider = str(payload.get("provider") or "api").strip()[:80]
    voice_id = str(payload.get("voice_id") or "").strip()[:500]
    voice_name = str(payload.get("voice_name") or "自定义声音").strip()[:200]
    profile_kind = str(payload.get("profile_kind") or "api_tts").strip()[:80]
    model = str(payload.get("model") or "").strip()[:200]
    metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
    now = int(time.time())
    profile_id = db.execute(
        "INSERT INTO voice_profiles(avatar_id,provider,voice_id,voice_name,profile_kind,status,model,metadata_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,0,?)",
        (
            avatar_id,
            provider,
            voice_id,
            voice_name,
            profile_kind,
            "candidate",
            model,
            json.dumps({"user_defined": True, **metadata}, ensure_ascii=False),
            now,
        ),
    )
    return select_voice_profile(db, avatar_id, int(profile_id)) if payload.get("active") else dict(db.one("SELECT * FROM voice_profiles WHERE id=?", (profile_id,)))
