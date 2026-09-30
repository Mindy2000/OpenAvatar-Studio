from __future__ import annotations

from typing import Any

from fastapi import APIRouter, HTTPException

from openavatar.application import ApplicationContext
from openavatar.providers import ProviderError
from openavatar.schemas import CapabilityRoutePayload, ProviderConnectionPayload
from openavatar.services.provider_hub import (
    CAPABILITIES,
    PROVIDER_PRESETS,
    connection_row,
    delete_connection,
    discover_models,
    public_connection,
    public_route,
    test_connection,
    upsert_connection,
    upsert_route,
)


def create_provider_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db

    @router.get("/api/provider-hub")
    def provider_hub() -> dict[str, Any]:
        connections = [public_connection(row) for row in db.all("SELECT * FROM provider_connections ORDER BY updated_at DESC")]
        routes = [public_route(row) for row in db.all("SELECT * FROM capability_routes ORDER BY scope_type,avatar_id,capability")]
        usage = db.all(
            "SELECT provider,COUNT(*) AS calls,COALESCE(SUM(estimated_cost),0) AS estimated_cost,MAX(created_at) AS last_used_at "
            "FROM usage_events WHERE provider LIKE 'pc_%' GROUP BY provider"
        )
        return {"capabilities": list(CAPABILITIES), "presets": PROVIDER_PRESETS, "connections": connections, "routes": routes, "usage": usage}

    @router.post("/api/provider-connections", status_code=201)
    def create_connection(payload: ProviderConnectionPayload) -> dict[str, Any]:
        try:
            return upsert_connection(db, payload)
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/api/provider-connections/{connection_id}")
    def update_connection(connection_id: str, payload: ProviderConnectionPayload) -> dict[str, Any]:
        if not connection_row(db, connection_id):
            raise HTTPException(404, "服务连接不存在")
        try:
            return upsert_connection(db, payload, connection_id)
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete("/api/provider-connections/{connection_id}")
    def remove_connection(connection_id: str) -> dict[str, bool]:
        try:
            delete_connection(db, connection_id)
            return {"deleted": True}
        except ProviderError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/api/provider-connections/{connection_id}/test")
    def probe_connection(connection_id: str) -> dict[str, Any]:
        try:
            return test_connection(db, connection_id)
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/provider-connections/{connection_id}/models")
    def connection_models(connection_id: str) -> dict[str, Any]:
        row = connection_row(db, connection_id)
        if not row:
            raise HTTPException(404, "服务连接不存在")
        try:
            return {"models": discover_models(row)}
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/api/capability-routes")
    def save_route(payload: CapabilityRoutePayload) -> dict[str, Any]:
        try:
            return upsert_route(db, payload)
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router
