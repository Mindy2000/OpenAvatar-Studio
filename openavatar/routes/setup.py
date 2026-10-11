from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query
from openavatar.application import ApplicationContext
from openavatar.services.setup import DISMISSED_KEY, setup_status


def create_setup_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()

    @router.get("/api/setup/status")
    def status(avatar_id: str = Query(default="", max_length=100)):
        try:
            return setup_status(context.db, avatar_id)
        except KeyError:
            raise HTTPException(404, "Avatar not found") from None

    @router.put("/api/setup/dismiss")
    def dismiss():
        context.db.set_setting(DISMISSED_KEY, True)
        return {"dismissed": True}

    return router
