from __future__ import annotations

import json
import time
import uuid
from collections.abc import Callable, Iterator
from typing import Any

from fastapi import HTTPException

from openavatar.config import Settings
from openavatar.db import Database
from openavatar.events import EventStore
from openavatar.local_model import LocalModelError
from openavatar.providers import ChatProvider, ProviderConfig, ProviderError
from openavatar.runtime import Metrics, RunRegistry
from openavatar.services.persona import relevant_memories, style_signature
from openavatar.services.persona_core import current_persona_core, record_decision, record_usage
from openavatar.services.world_regions import avatar_language_profile


class ChatService:
    def __init__(
        self,
        *,
        db: Database,
        settings: Settings,
        metrics: Metrics,
        runs: RunRegistry,
        events: EventStore,
        readiness: Callable[[Database, str], dict[str, Any]],
        model_client_factory: Callable[[Database, Settings, str], ChatProvider],
        provider_config_factory: Callable[[Database, Settings, str], ProviderConfig],
        unavailable_message: Callable[[ProviderConfig], str],
        public_runtime_mode: Callable[[str], str],
    ) -> None:
        self.db = db
        self.settings = settings
        self.metrics = metrics
        self.runs = runs
        self.events = events
        self.readiness = readiness
        self.model_client_factory = model_client_factory
        self.provider_config_factory = provider_config_factory
        self.unavailable_message = unavailable_message
        self.public_runtime_mode = public_runtime_mode

    def require_avatar(self, avatar_id: str) -> dict[str, Any]:
        row = self.db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,))
        if not row:
            raise HTTPException(404, "数字人不存在")
        return row

    def get_persona(self, avatar_id: str) -> dict[str, Any]:
        self.require_avatar(avatar_id)
        row = self.db.one("SELECT * FROM persona_profiles WHERE avatar_id=?", (avatar_id,)) or {}
        row["traits"] = json.loads(row.pop("traits_json", "[]"))
        return row

    def get_messages(self, avatar_id: str, limit: int = 100, timeline_kind: str = "official") -> list[dict[str, Any]]:
        self.require_avatar(avatar_id)
        if timeline_kind not in {"official", "preview"}:
            raise HTTPException(400, "时间线类型不合法")
        safe_limit = min(max(limit, 1), 500)
        channel_filter = "channel='preview'" if timeline_kind == "preview" else "channel<>'preview'"
        return list(reversed(self.db.all(
            f"SELECT id,role,content,channel,created_at FROM messages WHERE avatar_id=? AND {channel_filter} ORDER BY id DESC LIMIT ?",
            (avatar_id, safe_limit),
        )))

    def prepare(self, avatar_id: str, message: str, preview_mode: bool = False) -> dict[str, Any]:
        avatar = self.require_avatar(avatar_id)
        readiness = self.readiness(self.db, avatar_id)
        if not readiness["can_start_official"] and not preview_mode:
            raise HTTPException(409, "必须项未完成，暂时不能正式使用；可以在预览测试模式中试聊。")
        persona_core = current_persona_core(self.db, avatar_id)
        persona = persona_core["core"].get("persona", self.get_persona(avatar_id))
        history = self.get_messages(avatar_id, 20, "preview" if preview_mode else "official")
        memory_rows = self.db.all(
            """SELECT COALESCE(NULLIF(c.corrected_speaker,''),m.speaker) speaker,
                      COALESCE(NULLIF(c.corrected_content,''),m.content) content,m.is_avatar
               FROM memories m LEFT JOIN historical_memory_corrections c ON c.memory_id=m.id
               WHERE m.avatar_id=? ORDER BY m.id DESC LIMIT 1000""",
            (avatar_id,),
        )
        memories = relevant_memories(memory_rows, message)
        signature = style_signature(memory_rows)
        style_examples = [row for row in memories if row.get("is_avatar")][:8]
        world_context = "\n".join(
            f"- {item['key']}: {json.dumps(item['value'], ensure_ascii=False)}"
            for item in persona_core["core"].get("world_context", [])[:80]
        )
        feedback_context = "\n".join(
            f"- {item['dimension']} / {item['signal']}: {item['rule_text']}"
            for item in persona_core["core"].get("feedback_rules", [])[:12]
            if item.get("active")
        )
        language_context = persona_core["core"].get("language_profile", avatar_language_profile(avatar))
        language_instruction = language_context.get("language_label", {}).get("instruction", "主要使用自然中文表达。")
        region_rules = language_context.get("world_region_rules", {})
        route_note = "当前是预览测试模式，回答应保守，并指出哪些能力还未正式完成。" if preview_mode and not readiness["can_start_official"] else "当前处于正式使用模式。"
        system = (
            f"你是数字人{avatar['name']}，与用户的关系是{avatar['relationship']}。\n"
            f"{route_note}\n"
            f"数字人语言策略：{language_instruction} 回复模式：{language_context.get('response_mode_label', {}).get('name_zh', '')}。\n"
            f"世界地区：{region_rules.get('name_zh', '')}；世界类型：{language_context.get('world_type', '')}。聊天中的节日、职业、作息、称呼和社会规则应符合这个世界地区。\n"
            f"人格：{persona.get('summary', '')}\n特征：{'、'.join(persona.get('traits', []))}\n"
            f"表达方式：{persona.get('speaking_style', '')}\n边界：{persona.get('boundaries', '')}\n"
            "只能使用提供的记忆，不要把推测冒充事实。你是AI数字人，不得用于冒充真人或欺诈。\n"
            f"原始表达风格指纹：{json.dumps(signature, ensure_ascii=False)}。只学习长度、问句率、碎片感和分条方式，不照搬样例事实。\n"
            f"里世界和运行事实：\n{world_context}\n"
            f"用户反馈形成的回复规则：\n{feedback_context}\n"
            "相似的人物原型表达样例：\n" + "\n".join(f"- {row['content']}" for row in style_examples) + "\n"
            "相关记忆：\n" + "\n".join(f"{row['speaker']}: {row['content']}" for row in memories)
        )
        messages = [{"role": "system", "content": system}]
        messages.extend({"role": row["role"], "content": row["content"]} for row in history if row["role"] in {"user", "assistant"})
        messages.append({"role": "user", "content": message})
        client = self.model_client_factory(self.db, self.settings, avatar_id)
        config = self.provider_config_factory(self.db, self.settings, avatar_id)
        if not client.available():
            raise HTTPException(503, self.unavailable_message(config))
        return {
            "readiness": readiness,
            "persona_core": persona_core,
            "messages": messages,
            "memories": memories,
            "client": client,
            "config": config,
            "channel": "preview" if preview_mode and not readiness["can_start_official"] else "chat",
        }

    def persist(self, avatar_id: str, message: str, prepared: dict[str, Any], reply: str, latency_ms: int) -> dict[str, Any]:
        now = int(time.time())
        channel = str(prepared["channel"])
        turn_id = uuid.uuid4().hex
        user_message_id = self.db.execute(
            "INSERT INTO messages(avatar_id,role,content,channel,created_at,turn_id) VALUES(?,?,?,?,?,?)",
            (avatar_id, "user", message, channel, now, turn_id),
        )
        assistant_message_id = self.db.execute(
            "INSERT INTO messages(avatar_id,role,content,channel,created_at,turn_id) VALUES(?,?,?,?,?,?)",
            (avatar_id, "assistant", reply, channel, int(time.time()), turn_id),
        )
        config = prepared["config"]
        client = prepared["client"]
        record_usage(
            self.db, avatar_id, provider=config.provider_name, model=client.model, role="chat",
            operation="chat", status="ok", latency_ms=latency_ms,
            metadata={"preview_mode": channel == "preview"},
        )
        record_decision(
            self.db, avatar_id, message_id=assistant_message_id, decision_kind="chat_reply",
            input_summary=message, output_summary=reply,
            metadata={
                "user_message_id": user_message_id,
                "memory_count": len(prepared["memories"]),
                "persona_core_digest": prepared["persona_core"]["digest"],
                "latency_ms": latency_ms,
            },
        )
        self.events.append(
            avatar_id, "chat.completed",
            {"turn_id": turn_id, "latency_ms": latency_ms, "preview_mode": channel == "preview"},
            aggregate_type="chat_turn", aggregate_id=turn_id,
            idempotency_key=f"chat.completed:{turn_id}",
        )
        return {
            "reply": reply,
            "model": client.model,
            "runtime_mode": self.public_runtime_mode(config.mode),
            "connection_type": config.mode,
            "data_sent_to_provider": config.mode in {"cloud", "cloud_openai"},
            "preview_mode": channel == "preview",
            "readiness": prepared["readiness"],
            "turn_id": turn_id,
        }

    def reply(self, avatar_id: str, message: str, preview_mode: bool = False) -> dict[str, Any]:
        prepared = self.prepare(avatar_id, message, preview_mode)
        client = prepared["client"]
        started = time.perf_counter()
        try:
            reply = client.chat(prepared["messages"])
        except (LocalModelError, ProviderError) as exc:
            config = prepared["config"]
            latency_ms = round((time.perf_counter() - started) * 1000)
            record_usage(
                self.db, avatar_id, provider=config.provider_name, model=client.model, role="chat",
                operation="chat", status="failed", latency_ms=latency_ms, metadata={"error": str(exc)},
            )
            raise HTTPException(502, f"{config.provider_name} 调用失败：{exc}") from exc
        latency_ms = round((time.perf_counter() - started) * 1000)
        self.metrics.observe("chat.total_ms", latency_ms)
        return self.persist(avatar_id, message, prepared, reply, latency_ms)

    def stream(self, avatar_id: str, message: str, preview_mode: bool = False) -> tuple[str, Iterator[dict[str, Any]]]:
        prepared = self.prepare(avatar_id, message, preview_mode)
        client = prepared["client"]
        run_id, cancelled = self.runs.start(avatar_id, "chat")

        def generate() -> Iterator[dict[str, Any]]:
            started = time.perf_counter()
            parts: list[str] = []
            first_chunk_ms = 0
            yield {"type": "start", "run_id": run_id, "model": client.model}
            try:
                stream_method = getattr(client, "stream_chat", None)
                chunks = stream_method(prepared["messages"]) if callable(stream_method) else [client.chat(prepared["messages"])]
                for chunk in chunks:
                    if cancelled.is_set():
                        self.metrics.increment("chat.cancelled")
                        self.events.append(avatar_id, "chat.cancelled", {"run_id": run_id}, aggregate_type="chat_run", aggregate_id=run_id)
                        yield {"type": "cancelled", "run_id": run_id}
                        return
                    text = str(chunk)
                    if not text:
                        continue
                    if not parts:
                        first_chunk_ms = round((time.perf_counter() - started) * 1000)
                        self.metrics.observe("chat.first_text_ms", first_chunk_ms)
                    parts.append(text)
                    yield {"type": "delta", "run_id": run_id, "text": text}
                reply = "".join(parts).strip()
                if not reply:
                    raise ProviderError("模型没有返回文本")
                latency_ms = round((time.perf_counter() - started) * 1000)
                result = self.persist(avatar_id, message, prepared, reply, latency_ms)
                self.metrics.observe("chat.total_ms", latency_ms)
                yield {"type": "done", "run_id": run_id, "first_text_ms": first_chunk_ms, **result}
            except (LocalModelError, ProviderError) as exc:
                config = prepared["config"]
                latency_ms = round((time.perf_counter() - started) * 1000)
                record_usage(
                    self.db, avatar_id, provider=config.provider_name, model=client.model, role="chat",
                    operation="chat_stream", status="failed", latency_ms=latency_ms, metadata={"error": str(exc)},
                )
                self.metrics.increment("chat.stream.failure")
                yield {"type": "error", "run_id": run_id, "error": str(exc)}
            finally:
                self.runs.finish(run_id)

        return run_id, generate()
