from __future__ import annotations

from openavatar.routes._shared import *


def create_world_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db
    selected = context.settings
    runs = context.runs
    chat_service = context.chat

    @router.get("/api/avatars/{avatar_id}/world")
    def avatar_world(avatar_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        facts = db.all(
            "SELECT id,fact_key,fact_value_json,reality_kind,mutability,status,confidence,created_at,updated_at FROM world_facts WHERE avatar_id=? AND active=1 ORDER BY fact_key",
            (avatar_id,),
        )
        events = db.all(
            "SELECT id,event_key,title,summary,event_kind,status,occurred_at,payload_json,created_at FROM world_events WHERE avatar_id=? ORDER BY id DESC LIMIT 100",
            (avatar_id,),
        )
        for row in facts:
            row["value"] = json.loads(row.pop("fact_value_json"))
        for row in events:
            row["payload"] = json.loads(row.pop("payload_json", "{}"))
        return {"facts": facts, "events": events, "runtime": runtime_state(db, avatar_id)}

    @router.post("/api/avatars/{avatar_id}/world/advance")
    def advance_avatar_world(avatar_id: str, payload: WorldAdvancePayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return advance_world(db, avatar_id, seconds=payload.seconds, force_minor_event=payload.force_minor_event)

    @router.post("/api/avatars/{avatar_id}/world/rollback")
    def rollback_avatar_world(avatar_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return rollback_last_event(db, avatar_id)

    @router.post("/api/avatars/{avatar_id}/world/consistency")
    def scan_avatar_world_consistency(avatar_id: str, repair: bool = False) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return scan_consistency(db, avatar_id, repair=repair)

    @router.post("/api/avatars/{avatar_id}/world/conflicts/{conflict_id}/review")
    def review_avatar_world_conflict(avatar_id: str, conflict_id: int, payload: WorldConflictReview) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return resolve_conflict(db, avatar_id, conflict_id, payload.action, payload.note)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/avatars/{avatar_id}/world/proposals")
    def avatar_world_proposals(avatar_id: str, status: str = "") -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        return list_proposals(db, avatar_id, status)

    @router.post("/api/avatars/{avatar_id}/world/proposals", status_code=201)
    def create_world_proposal(avatar_id: str, payload: WorldFactPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return create_fact_from_payload(db, avatar_id, payload.model_dump())
        except WorldModelError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/world/proposals/{proposal_id}/review")
    def review_world_proposal(avatar_id: str, proposal_id: int, payload: WorldProposalReview) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return review_proposal(db, avatar_id, proposal_id, payload.action, payload.note)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except WorldModelError as exc:
            raise HTTPException(400, str(exc)) from exc

    return router

