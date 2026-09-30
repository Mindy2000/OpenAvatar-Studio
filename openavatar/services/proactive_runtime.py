from __future__ import annotations

import asyncio
import time
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI

from openavatar.local_model import LocalModelError
from openavatar.providers import ProviderError
from openavatar.services.proactive import get_proactive_rules, proactive_time_allowed
from openavatar.services.world_model import WorldModelError
from openavatar.services.world_runtime import advance_world


async def proactive_worker(
    app: FastAPI,
    *,
    completion_report: Callable[[Any, str], dict[str, Any]],
    model_client: Callable[[Any, Any, str], Any],
) -> None:
    while True:
        await asyncio.sleep(60)
        await proactive_tick(app, completion_report=completion_report, model_client=model_client)


async def proactive_tick(
    app: FastAPI,
    *,
    completion_report: Callable[[Any, str], dict[str, Any]],
    model_client: Callable[[Any, Any, str], Any],
) -> None:
    db = app.state.db
    now = int(time.time())
    avatars = db.all("SELECT * FROM avatars WHERE proactive_enabled=1 AND consent_confirmed=1")
    for avatar in avatars:
        if not completion_report(db, str(avatar["id"]))["can_start_official"]:
            continue
        rules = get_proactive_rules(db, str(avatar["id"]))
        if not proactive_time_allowed(rules, now):
            continue
        today_count = int((db.one(
                "SELECT COUNT(*) AS count FROM messages WHERE avatar_id=? AND channel='proactive' AND created_at>=?",
                (avatar["id"], now - 86400),
        ) or {"count": 0})["count"])
        if today_count >= int(rules["daily_max"]):
            continue
        last = db.one(
                "SELECT created_at FROM messages WHERE avatar_id=? AND channel='proactive' ORDER BY id DESC LIMIT 1",
                (avatar["id"],),
        )
        interval = int(avatar["proactive_interval_minutes"]) * 60
        if last and now - int(last["created_at"]) < interval:
            continue
        last_user = db.one(
                "SELECT created_at FROM messages WHERE avatar_id=? AND role='user' AND channel<>'preview' ORDER BY id DESC LIMIT 1",
                (avatar["id"],),
        )
        cooldown = int(rules["cooldown_after_user_reply_minutes"]) * 60
        if last_user and now - int(last_user["created_at"]) < cooldown:
            continue
        client = model_client(db, app.state.settings, str(avatar["id"]))
        if not client.available():
            continue
        persona = db.one("SELECT * FROM persona_profiles WHERE avatar_id=?", (avatar["id"],)) or {}
        memory_context = ""
        if rules["use_long_term_memory"]:
            recent_memories = db.all(
                    "SELECT content FROM memories WHERE avatar_id=? ORDER BY id DESC LIMIT 12",
                    (avatar["id"],),
            )
            memory_context = "可参考的长期记忆：" + "；".join(str(row["content"])[:120] for row in recent_memories)
        prompt = (
                f"你是{avatar['name']}。人格摘要：{persona.get('summary', '')}。"
                f"这是用户主动开启的本地主动联系功能。语气：{rules['tone']}。"
                f"主题范围：{', '.join(rules['topic_scope'])}。{memory_context}。写一条自然、简短、不虚构新事实的问候。"
        )
        try:
            content = await asyncio.to_thread(client.chat, [{"role": "user", "content": prompt}])
        except (LocalModelError, ProviderError):
            continue
        if not content:
            continue
        db.execute(
                "INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,?,?,?,?)",
                (avatar["id"], "assistant", content, "proactive", now),
        )
        if rules["allow_world_event_advancement"] and avatar["subject_kind"] == "fictional":
            try:
                advance_world(db, str(avatar["id"]), seconds=60, force_minor_event=False)
            except (ValueError, WorldModelError):
                pass
