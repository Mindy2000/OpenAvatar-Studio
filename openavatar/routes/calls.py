from __future__ import annotations

import asyncio
import json
import time

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect

from openavatar.db import Database
from openavatar.local_model import LocalModelError
from openavatar.providers import ProviderError
from openavatar.runtime import RunRegistry
from openavatar.services.chat_runtime import ChatService
from openavatar.services.http_security import LOCAL_HOSTS, same_origin


def create_call_router(*, db: Database, runs: RunRegistry, chat: ChatService) -> APIRouter:
    router = APIRouter()

    @router.websocket("/ws/avatars/{avatar_id}/call")
    async def realtime_voice_gateway(websocket: WebSocket, avatar_id: str) -> None:
        host = (websocket.url.hostname or "").lower()
        if host not in LOCAL_HOSTS or not same_origin(websocket.headers.get("origin"), str(websocket.url)):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        try:
            await asyncio.to_thread(chat.require_avatar, avatar_id)
        except HTTPException:
            await websocket.send_json({"type": "call.error", "error": "数字人不存在", "fatal": True})
            await websocket.close(code=4404)
            return
        call_id = db.execute(
            "INSERT INTO realtime_call_sessions(avatar_id,status,provider,started_at,metadata_json) VALUES(?,?,?,?,?)",
            (
                avatar_id,
                "active",
                "openavatar-websocket",
                int(time.time()),
                json.dumps(
                    {"protocol": "openavatar.realtime-call.v2", "transport": "websocket", "input": "text"},
                    ensure_ascii=False,
                ),
            ),
        )
        current_task: asyncio.Task[None] | None = None
        current_run_id = ""

        async def answer(text: str, run_id: str, cancelled) -> None:
            started = time.perf_counter()
            parts: list[str] = []
            first_text_ms = 0
            try:
                prepared = await asyncio.to_thread(chat.prepare, avatar_id, text, False)
                client = prepared["client"]
                stream_method = getattr(client, "stream_chat", None)
                iterator = iter(
                    stream_method(prepared["messages"])
                    if callable(stream_method)
                    else [client.chat(prepared["messages"])]
                )
                sentinel = object()
                while not cancelled.is_set():
                    chunk = await asyncio.to_thread(next, iterator, sentinel)
                    if chunk is sentinel:
                        break
                    value = str(chunk)
                    if not value:
                        continue
                    if not parts:
                        first_text_ms = round((time.perf_counter() - started) * 1000)
                    parts.append(value)
                    await websocket.send_json({"type": "assistant.delta", "run_id": run_id, "text": value})
                if cancelled.is_set():
                    await websocket.send_json({"type": "assistant.interrupted", "run_id": run_id})
                    return
                reply = "".join(parts).strip()
                if not reply:
                    raise ProviderError("模型没有返回文本")
                llm_ms = round((time.perf_counter() - started) * 1000)
                result = await asyncio.to_thread(chat.persist, avatar_id, text, prepared, reply, llm_ms)
                db.execute(
                    """INSERT INTO realtime_call_turns
                       (avatar_id,call_session_id,user_transcript,assistant_text,llm_latency_ms,metadata_json,created_at)
                       VALUES(?,?,?,?,?,?,?)""",
                    (
                        avatar_id,
                        call_id,
                        text,
                        reply,
                        llm_ms,
                        json.dumps({"run_id": run_id, "first_text_ms": first_text_ms}, ensure_ascii=False),
                        int(time.time()),
                    ),
                )
                await websocket.send_json(
                    {
                        "type": "assistant.done",
                        "run_id": run_id,
                        "reply": reply,
                        "first_text_ms": first_text_ms,
                        "llm_ms": llm_ms,
                        "turn_id": result["turn_id"],
                    }
                )
            except (HTTPException, LocalModelError, ProviderError) as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                await websocket.send_json(
                    {"type": "call.error", "run_id": run_id, "error": str(detail), "fatal": False}
                )
            finally:
                runs.finish(run_id)

        await websocket.send_json(
            {"type": "call.started", "call_id": call_id, "protocol": "openavatar.realtime-call.v2", "input": "text"}
        )
        try:
            while True:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                if message.get("bytes") is not None:
                    await websocket.send_json(
                        {"type": "call.error", "error": "尚未配置实时 ASR Provider；请发送 user.text", "fatal": False}
                    )
                    continue
                raw = message.get("text") or ""
                try:
                    body = json.loads(raw)
                except json.JSONDecodeError:
                    await websocket.send_json({"type": "call.error", "error": "消息必须是 JSON", "fatal": False})
                    continue
                if not isinstance(body, dict):
                    await websocket.send_json({"type": "call.error", "error": "消息必须是 JSON 对象", "fatal": False})
                    continue
                event_type = str(body.get("type") or "")
                if event_type == "user.text":
                    text = str(body.get("text") or "").strip()
                    if not text:
                        continue
                    if current_run_id:
                        runs.cancel(current_run_id, avatar_id)
                    if current_task:
                        await asyncio.gather(current_task, return_exceptions=True)
                    current_run_id, cancel_event = runs.start(avatar_id, "realtime-call")
                    current_task = asyncio.create_task(answer(text, current_run_id, cancel_event))
                    await websocket.send_json({"type": "user.committed", "run_id": current_run_id, "text": text})
                elif event_type == "call.interrupt" and current_run_id:
                    await asyncio.to_thread(runs.cancel, current_run_id, avatar_id)
                elif event_type == "call.end":
                    break
                elif event_type == "ping":
                    await websocket.send_json({"type": "pong", "timestamp": time.time()})
        except WebSocketDisconnect:
            pass
        finally:
            if current_run_id:
                runs.cancel(current_run_id, avatar_id)
            if current_task:
                await asyncio.gather(current_task, return_exceptions=True)
            db.execute(
                "UPDATE realtime_call_sessions SET status='completed',ended_at=? WHERE id=?",
                (int(time.time()), call_id),
            )

    return router
