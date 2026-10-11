"""Explicit, local memory controls for individual chat messages."""
from __future__ import annotations

import json
import time
from typing import Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openavatar.application import ApplicationContext
from openavatar.services.memory_intelligence import rebuild_memory_graph, merged_memory_ids
from openavatar.services.persona_core import build_persona_core


class ChatMemoryAction(BaseModel):
    action: Literal["remember", "correct", "forget"]
    content: str = Field(default="", max_length=1000)
    preview_mode: bool = False
    confirmed: bool = False


def create_chat_memory_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db

    def source(avatar_id: str, message_id: int, preview_mode: bool):
        context.chat.require_avatar(avatar_id)
        row = db.one("SELECT * FROM messages WHERE avatar_id=? AND id=?", (avatar_id, message_id))
        if not row or (row["channel"] == "preview") != preview_mode or row["channel"] == "voice_call":
            raise HTTPException(404, "找不到当前对话中的这条消息")
        if row["role"] not in {"user", "assistant"} or row["message_kind"] not in {"text", "audio"}:
            raise HTTPException(400, "请选择文字或已有转写的语音消息")
        if row["message_kind"] == "audio" and row["content"].startswith("[语音]"):
            raise HTTPException(400, "这条语音没有可用文字，请先补充文字")
        return row

    def merged_dependents(avatar_id: str, memory_id: int):
        reached = merged_memory_ids(db, avatar_id, {memory_id})
        return [row for parent in sorted(reached - {memory_id}) if (row := db.one(
            "SELECT * FROM memories WHERE avatar_id=? AND id=? AND confidence>0 AND kind NOT IN ('rejected','merged_duplicate')",
            (avatar_id, parent)))]

    def state(avatar_id: str, message_id: int, preview_mode: bool):
        row = source(avatar_id, message_id, preview_mode)
        memory = db.one(
            "SELECT id,content,confidence,kind FROM memories WHERE avatar_id=? "
            "AND origin_kind='runtime_chat' AND source_message_id=? ORDER BY id DESC LIMIT 1",
            (avatar_id, message_id),
        )
        active = bool(memory and memory["confidence"] > 0 and memory["kind"] not in {"rejected", "merged_duplicate"})
        return {"message_id": message_id, "original_content": row["content"], "remembered": active,
                "context_excluded": bool(row["context_excluded"]),
                "memory": memory, "merged_dependents": len(merged_dependents(avatar_id, memory["id"])) if memory else 0, "cloud_calls": 0}

    @router.get("/api/avatars/{avatar_id}/messages/{message_id}/memory")
    def get_memory(avatar_id: str, message_id: int, preview_mode: bool = False):
        return state(avatar_id, message_id, preview_mode)

    @router.post("/api/avatars/{avatar_id}/messages/{message_id}/memory")
    def change_memory(avatar_id: str, message_id: int, payload: ChatMemoryAction):
        row = source(avatar_id, message_id, payload.preview_mode)
        if not payload.confirmed:
            raise HTTPException(400, "请确认要保存或停用的记忆内容")
        content = payload.content.strip()
        if payload.action != "forget" and not content:
            raise HTTPException(400, "请填写要记住的内容")
        now = int(time.time())
        linked = db.one("SELECT id FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat' AND source_message_id=? ORDER BY id DESC LIMIT 1", (avatar_id, message_id))
        derived = merged_dependents(avatar_id, linked["id"]) if linked else []
        with db.transaction() as connection:
            previous = connection.execute(
                "SELECT * FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat' "
                "AND source_message_id=? ORDER BY id DESC LIMIT 1", (avatar_id, message_id),
            ).fetchone()
            before = dict(previous) if previous else {}
            if payload.action == "forget":
                # Retain an audit trail, but stop retrieving every note tied to this source.
                connection.execute(
                    "UPDATE memories SET confidence=0,kind='rejected' WHERE avatar_id=? "
                    "AND origin_kind='runtime_chat' AND source_message_id=?", (avatar_id, message_id),
                )
                memory_id = before.get("id", 0)
            elif previous:
                memory_id = previous["id"]
                connection.execute("UPDATE memories SET content=?,kind='chat_note',confidence=1 WHERE id=?",
                                   (content, memory_id))
            else:
                cursor = connection.execute(
                    "INSERT INTO memories(avatar_id,speaker,content,kind,is_avatar,confidence,created_at,"
                    "origin_kind,source_message_id,timeline_kind) VALUES(?,?,?,'chat_note',0,1,?,'runtime_chat',?,?)",
                    (avatar_id, "用户确认", content, now, message_id, "preview" if payload.preview_mode else "official"),
                )
                memory_id = cursor.lastrowid
            # A merged copy must not keep the old fact alive after its source changes.
            for parent in derived:
                connection.execute("UPDATE memories SET confidence=0,kind='rejected' WHERE id=? AND avatar_id=?", (parent["id"], avatar_id))
                after = {**parent, "confidence": 0, "kind": "rejected"}
                connection.execute("INSERT INTO memory_revisions(avatar_id,memory_id,before_json,after_json,action,note,created_at) VALUES(?,?,?,?,?,?,?)",
                                   (avatar_id, parent["id"], json.dumps(parent, ensure_ascii=False), json.dumps(after, ensure_ascii=False),
                                    "source_changed", f"聊天来源 #{message_id} 已修改或停用，合并记忆同时停用", now))
            if payload.action in {"correct", "forget"}:
                # Avoid reintroducing the old fact through its original message or same-turn echo.
                connection.execute("UPDATE messages SET context_excluded=1 WHERE avatar_id=? AND id=?",
                                   (avatar_id, message_id))
                if row["turn_id"]:
                    connection.execute("UPDATE messages SET context_excluded=1 WHERE avatar_id=? AND turn_id=?",
                                       (avatar_id, row["turn_id"]))
            after_row = connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone()
            connection.execute(
                "INSERT INTO memory_revisions(avatar_id,memory_id,before_json,after_json,action,note,created_at) "
                "VALUES(?,?,?,?,?,?,?)",
                (avatar_id, memory_id, json.dumps(before, ensure_ascii=False),
                 json.dumps(dict(after_row) if after_row else {}, ensure_ascii=False), payload.action,
                 f"用户在聊天消息 #{message_id} 中确认", now),
            )
        rebuild_memory_graph(db, avatar_id)
        build_persona_core(db, avatar_id)
        return state(avatar_id, message_id, payload.preview_mode)

    return router
