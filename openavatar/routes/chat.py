from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter
from fastapi.responses import StreamingResponse

from openavatar.schemas import ChatRequest
from openavatar.services.chat_runtime import ChatService


def create_chat_router(service: ChatService) -> APIRouter:
    router = APIRouter()

    @router.post("/api/avatars/{avatar_id}/chat")
    def chat(avatar_id: str, payload: ChatRequest) -> dict[str, Any]:
        return service.reply(avatar_id, payload.message, payload.preview_mode)

    @router.post("/api/avatars/{avatar_id}/chat/stream")
    def stream_chat(avatar_id: str, payload: ChatRequest) -> StreamingResponse:
        run_id, events = service.stream(avatar_id, payload.message, payload.preview_mode)

        def encode():
            for event in events:
                yield json.dumps(event, ensure_ascii=False) + "\n"

        return StreamingResponse(
            encode(),
            media_type="application/x-ndjson",
            headers={"X-Run-Id": run_id, "Cache-Control": "no-store"},
        )

    return router
