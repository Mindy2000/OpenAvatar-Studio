from __future__ import annotations

import asyncio
import json
import secrets
import time

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from openavatar.db import Database
from openavatar.local_model import LocalModelError
from openavatar.providers import ProviderError
from openavatar.runtime import RunRegistry
from openavatar.services.call_policy import (
    CallLimit, CallLimits, CallPolicy, SentenceSegments, call_cost,
    maximum_call_speech_cost, preflight_call_voice, refresh_call_voice,
    select_call_chat, select_call_voice, synthesize_call_segment,
)
from openavatar.services.chat_runtime import ChatService
from openavatar.services.http_security import LOCAL_HOSTS, same_origin
from openavatar.services.provider_hub import assert_allowed, record_provider_usage


class CallSpeechRequest(BaseModel):
    token: str = Field(min_length=16, max_length=100)
    run_id: str = Field(min_length=1, max_length=100)
    segment_id: int = Field(ge=0, le=2)


def create_call_router(*, db: Database, runs: RunRegistry, chat: ChatService) -> APIRouter:
    router = APIRouter()
    # Local desktop sessions are intentionally ephemeral. Reconnecting creates a
    # fresh call with explicit limits; an old token can never resume spending.
    sessions: dict[int, dict] = {}

    @router.post("/api/avatars/{avatar_id}/calls/{call_id}/speech")
    async def call_speech(avatar_id: str, call_id: int, payload: CallSpeechRequest, request: Request) -> FileResponse:
        session = sessions.get(call_id)
        if not session or session["avatar_id"] != avatar_id or not secrets.compare_digest(payload.token, session["token"]):
            raise HTTPException(404, "通话不存在或已结束")
        policy = session["policy"]
        if session["run_id"] != payload.run_id:
            raise HTTPException(409, "该回复已被打断")
        segment = session["segments"].get(payload.segment_id)
        if not segment or segment["state"] != "pending" or any(
            item["state"] != "ready" for index, item in session["segments"].items() if index < payload.segment_id
        ):
            raise HTTPException(409, "语音片段不存在、顺序错误或已请求；不会重复合成")
        row = None
        cost = 0.0
        started = time.perf_counter()
        # Claim before the first await. A duplicate concurrent POST cannot spend.
        segment["state"] = "claimed"
        try:
            policy.check()
            if session["voice_plan"] is None:
                session["voice_plan"] = select_call_voice(db, avatar_id)
            plan = session["voice_plan"]
            refresh_call_voice(db, plan)
            row = plan["row"]
            cost = call_cost(row, "tts", input_units=len(segment["text"]))
            assert_allowed(db, row, "tts", upcoming_cost=cost)
            policy.reserve(cost)
            segment["reserved"] = True
            await session["usage"]()
            policy.check()
            if session["run_id"] != payload.run_id:
                raise HTTPException(409, "该回复已被打断，忽略旧语音")
            target = chat.settings.avatars_dir / avatar_id / "generated" / "audio" / f"call-{call_id}-{payload.run_id}-{payload.segment_id}.mp3"
            media_type = await asyncio.to_thread(synthesize_call_segment, plan, segment["text"], target)
            policy.check()
            if session["run_id"] != payload.run_id or await request.is_disconnected():
                raise HTTPException(409, "该回复已被打断，忽略旧语音")
            segment["state"] = "ready"
            return FileResponse(target, media_type=media_type, filename=target.name)
        except CallLimit as exc:
            if policy.active and session["run_id"] == payload.run_id:
                await session["terminate"](exc.reason, str(exc))
            raise HTTPException(409, str(exc)) from exc
        except (ProviderError, LocalModelError, OSError) as exc:
            if not policy.active or session["run_id"] != payload.run_id:
                raise HTTPException(409, "该回复已被打断，忽略旧语音") from exc
            await session["terminate"]("speech_failed", f"声音生成失败，通话已停止：{exc}")
            raise HTTPException(502, str(exc)) from exc
        finally:
            if row and segment.get("reserved"):
                record_provider_usage(db, avatar_id, str(row["id"]), session["voice_plan"]["model"], "tts",
                    "ok" if segment["state"] == "ready" else "interrupted_or_failed",
                    latency_ms=(time.perf_counter() - started) * 1000, estimated_cost=cost,
                    metadata={"call_id": call_id, "run_id": payload.run_id, "segment_id": payload.segment_id, "estimate_reserved": True})
            if segment["state"] != "ready":
                segment["state"] = "failed"

    @router.websocket("/ws/avatars/{avatar_id}/call")
    async def realtime_voice_gateway(websocket: WebSocket, avatar_id: str) -> None:
        host = (websocket.url.hostname or "").lower()
        if host not in LOCAL_HOSTS or not same_origin(websocket.headers.get("origin"), str(websocket.url)):
            await websocket.close(code=4403)
            return
        await websocket.accept()
        try:
            limits = CallLimits.parse(websocket.query_params.get("max_minutes", 10), websocket.query_params.get("estimated_budget_cny", 5))
            await asyncio.to_thread(chat.require_avatar, avatar_id)
            voice_mode = websocket.query_params.get("voice", "false").lower() in {"true", "1"}
            voice_plan = await asyncio.to_thread(preflight_call_voice, db, avatar_id) if voice_mode else None
            policy = CallPolicy(limits)
            if voice_plan:
                policy.check_estimate(maximum_call_speech_cost(voice_plan))
        except (HTTPException, ProviderError) as exc:
            await websocket.send_json({"type": "call.error", "error": str(exc.detail if isinstance(exc, HTTPException) else exc), "fatal": True})
            await websocket.close(code=4400)
            return
        metadata = {"protocol": "openavatar.realtime-call.v3", "transport": "websocket", "input": "text", "voice": voice_mode, **policy.snapshot()}
        call_id = db.execute(
            "INSERT INTO realtime_call_sessions(avatar_id,status,provider,started_at,metadata_json) VALUES(?,?,?,?,?)",
            (avatar_id, "active", "openavatar-websocket", int(time.time()), json.dumps(metadata, ensure_ascii=False)),
        )
        call_started_at = int(time.time())
        current_task: asyncio.Task | None = None
        send_lock = asyncio.Lock()
        session = {"avatar_id": avatar_id, "token": secrets.token_urlsafe(24), "policy": policy,
                   "run_id": "", "segments": {}, "voice_plan": voice_plan}
        sessions[call_id] = session

        async def send(event: dict) -> None:
            async with send_lock:
                await websocket.send_json(event)

        async def usage() -> None:
            if policy.active:
                await send({"type": "call.usage", **policy.snapshot()})

        async def terminate(reason: str, message: str) -> None:
            if not policy.active:
                return
            policy.active, policy.reason = False, reason
            if session["run_id"]:
                runs.cancel(session["run_id"], avatar_id)
            session["run_id"] = ""
            if current_task and current_task is not asyncio.current_task():
                current_task.cancel()
            try:
                await send({"type": "call.ended", "reason": reason, "message": message, **policy.snapshot()})
                await websocket.close(code=1000)
            except (RuntimeError, WebSocketDisconnect):
                pass

        session.update(usage=usage, terminate=terminate)

        async def watchdog() -> None:
            try:
                while policy.active:
                    await asyncio.sleep(min(1, max(.01, policy.snapshot()["remaining_seconds"])))
                    policy.check()
                    await usage()
            except CallLimit as exc:
                await terminate(exc.reason, str(exc))
            except (RuntimeError, WebSocketDisconnect):
                pass

        async def answer(text: str, run_id: str, cancelled) -> None:
            started = time.perf_counter()
            parts: list[str] = []
            first_text_ms = 0
            splitter = SentenceSegments()
            row, cost, reserved = None, 0.0, False
            result_status = "interrupted_or_failed"

            async def emit_segments(values: list[str]) -> None:
                for value in values:
                    if not policy.active or cancelled.is_set() or session["run_id"] != run_id:
                        return
                    index = len(session["segments"])
                    session["segments"][index] = {"text": value, "state": "pending"}
                    await send({"type": "assistant.segment", "run_id": run_id, "segment_id": index, "text": value})

            try:
                policy.check()
                prepared = await asyncio.to_thread(chat.prepare, avatar_id, text, False)
                prepared["channel"] = "voice_call"
                client, row, cost = select_call_chat(prepared)
                speech_plan = session["voice_plan"]
                if speech_plan:
                    refresh_call_voice(db, speech_plan)
                speech_cost = maximum_call_speech_cost(speech_plan) if speech_plan else 0
                policy.check_estimate(cost + speech_cost)
                same_connection = bool(row and speech_plan and str(row["id"]) == str(speech_plan["row"]["id"]))
                if row:
                    assert_allowed(db, row, "chat", upcoming_cost=cost + (speech_cost if same_connection else 0))
                if speech_plan:
                    assert_allowed(db, speech_plan["row"], "tts", upcoming_cost=speech_cost + (cost if same_connection else 0))
                policy.reserve(cost)
                reserved = True
                if cost:
                    await usage()
                stream_method = getattr(client, "stream_chat", None)
                # Construct and consume the iterator in the worker: legacy
                # nonstreaming providers must not block the deadline watchdog.
                def chunks():
                    if callable(stream_method):
                        yield from stream_method(prepared["messages"])
                    else:
                        yield client.chat(prepared["messages"])
                iterator, sentinel = iter(chunks()), object()
                while not cancelled.is_set():
                    chunk = await asyncio.to_thread(next, iterator, sentinel)
                    policy.check()
                    if cancelled.is_set() or session["run_id"] != run_id:
                        return
                    if chunk is sentinel:
                        break
                    remaining = 80 - sum(len(part) for part in parts)
                    value = str(chunk)[:remaining]
                    if not value:
                        continue
                    if not parts:
                        first_text_ms = round((time.perf_counter() - started) * 1000)
                    parts.append(value)
                    await send({"type": "assistant.delta", "run_id": run_id, "text": value})
                    await emit_segments(splitter.push(value))
                    if len(value) >= remaining:
                        break
                if cancelled.is_set():
                    return
                reply = "".join(parts).strip()
                if not reply:
                    raise ProviderError("模型没有返回文本")
                await emit_segments(splitter.push("", final=True))
                llm_ms = round((time.perf_counter() - started) * 1000)
                # SQLite persistence is short and synchronous so interruption
                # cannot leave a background persist running after cancellation.
                result = chat.persist(avatar_id, text, prepared, reply, llm_ms)
                db.execute(
                    "INSERT INTO realtime_call_turns(avatar_id,call_session_id,user_transcript,assistant_text,llm_latency_ms,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (avatar_id, call_id, text, reply, llm_ms, json.dumps({"run_id": run_id, "first_text_ms": first_text_ms}), int(time.time())),
                )
                result_status = "ok"
                await send({"type": "assistant.done", "run_id": run_id, "reply": reply,
                            "first_text_ms": first_text_ms, "llm_ms": llm_ms, "turn_id": result["turn_id"], "segments": splitter.count})
            except CallLimit as exc:
                await terminate(exc.reason, str(exc))
            except (HTTPException, LocalModelError, ProviderError, OSError) as exc:
                detail = exc.detail if isinstance(exc, HTTPException) else str(exc)
                await terminate("reply_failed", f"通话已停止：{detail}")
            except asyncio.CancelledError:
                if policy.active:
                    try:
                        await send({"type": "assistant.interrupted", "run_id": run_id})
                    except (RuntimeError, WebSocketDisconnect):
                        pass
                raise
            finally:
                if row and reserved:
                    record_provider_usage(db, avatar_id, str(row["id"]), client.model, "chat", result_status,
                        latency_ms=(time.perf_counter() - started) * 1000, estimated_cost=cost,
                        metadata={"call_id": call_id, "run_id": run_id, "estimate_reserved": True})
                runs.finish(run_id)

        await send({"type": "call.started", "call_id": call_id, "token": session["token"],
                    "protocol": "openavatar.realtime-call.v3", "input": "text", **policy.snapshot()})
        timer = asyncio.create_task(watchdog())
        try:
            while policy.active:
                message = await websocket.receive()
                if message.get("type") == "websocket.disconnect":
                    break
                policy.check()
                if message.get("bytes") is not None:
                    await send({"type": "call.error", "error": "此接口不接收原始音频；请使用页面的浏览器语音识别模式或发送 user.text", "fatal": False})
                    continue
                try:
                    body = json.loads(message.get("text") or "")
                except json.JSONDecodeError:
                    await send({"type": "call.error", "error": "消息必须是 JSON", "fatal": False})
                    continue
                if not isinstance(body, dict):
                    await send({"type": "call.error", "error": "消息必须是 JSON 对象", "fatal": False})
                    continue
                event_type = str(body.get("type") or "")
                if event_type in {"user.text", "call.interrupt"}:
                    text = str(body.get("text") or "").strip()[:4000]
                    if event_type == "user.text" and not text:
                        continue
                    if session["run_id"]:
                        runs.cancel(session["run_id"], avatar_id)
                    session["run_id"] = ""
                    session["segments"] = {}
                    if current_task:
                        current_task.cancel()
                        await asyncio.gather(current_task, return_exceptions=True)
                    if event_type == "user.text":
                        run_id, cancel_event = runs.start(avatar_id, "realtime-call")
                        session["run_id"] = run_id
                        await send({"type": "user.committed", "run_id": run_id, "text": text,
                                    "client_turn_id": str(body.get("client_turn_id") or "")[:100]})
                        current_task = asyncio.create_task(answer(text, run_id, cancel_event))
                elif event_type == "call.played":
                    if body.get("run_id") == session["run_id"] and policy.estimated_reserved_cny >= limits.estimated_budget_cny:
                        await terminate("budget_limit", "已达到本次估算额度，通话已结束。")
                elif event_type == "call.end":
                    break
                elif event_type == "ping":
                    await send({"type": "pong", "timestamp": time.time()})
        except CallLimit as exc:
            await terminate(exc.reason, str(exc))
        except (WebSocketDisconnect, RuntimeError):
            pass
        finally:
            policy.active = False
            sessions.pop(call_id, None)
            timer.cancel()
            if session["run_id"]:
                runs.cancel(session["run_id"], avatar_id)
            session["run_id"] = ""
            if current_task:
                current_task.cancel()
                await asyncio.gather(current_task, return_exceptions=True)
            await asyncio.gather(timer, return_exceptions=True)
            metadata.update(policy.snapshot(), end_reason=policy.reason)
            db.execute("UPDATE realtime_call_sessions SET status='completed',ended_at=?,metadata_json=? WHERE id=?",
                       (int(time.time()), json.dumps(metadata, ensure_ascii=False), call_id))
            duration = max(0, int(time.time()) - call_started_at)
            db.execute("INSERT INTO messages(avatar_id,role,content,channel,created_at,message_kind,attachment_json) VALUES(?,?,?,?,?,?,?)",
                (avatar_id, "system", f"语音通话 {duration // 60:02d}:{duration % 60:02d}", "chat", int(time.time()), "call",
                 json.dumps({"duration": duration, "call_id": call_id, "estimated_reserved_cny": policy.estimated_reserved_cny, "end_reason": policy.reason})))

    return router
