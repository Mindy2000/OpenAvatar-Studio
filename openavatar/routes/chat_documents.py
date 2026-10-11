"""Read an explicitly selected chat attachment with the current chat provider."""
from __future__ import annotations

import threading

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from openavatar.application import ApplicationContext
from openavatar.services.chat_documents import document_error, document_status, read_document


class DocumentQuestion(BaseModel):
    question: str = Field(default="", max_length=1000)
    preview_mode: bool = False
    confirm_billable_call: bool = False
    request_id: str = Field(min_length=1, max_length=80, pattern=r"^[A-Za-z0-9_-]+$")


def create_chat_documents_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    lock = threading.Lock()

    def row_for(avatar_id: str, message_id: int, preview_mode: bool):
        context.chat.require_avatar(avatar_id)
        row = context.db.one("SELECT * FROM messages WHERE avatar_id=? AND id=?", (avatar_id, message_id))
        if not row or row["role"] != "user" or row.get("message_kind") != "file" or (row["channel"] == "preview") != preview_mode:
            raise HTTPException(404, "File message does not exist in this conversation")
        return row

    @router.get("/api/avatars/{avatar_id}/messages/{message_id}/document")
    def status(avatar_id: str, message_id: int, preview_mode: bool = False):
        return document_status(context, row_for(avatar_id, message_id, preview_mode))

    @router.post("/api/avatars/{avatar_id}/messages/{message_id}/document/read")
    def read(avatar_id: str, message_id: int, payload: DocumentQuestion):
        row_for(avatar_id, message_id, payload.preview_mode)
        if not payload.confirm_billable_call:
            raise document_error("consent", 400)
        if not lock.acquire(blocking=False):
            raise document_error("busy", 409)
        try:
            return read_document(context, row_for(avatar_id, message_id, payload.preview_mode),
                                 question=payload.question, request_id=payload.request_id)
        finally:
            lock.release()

    return router
