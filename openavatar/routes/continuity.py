from __future__ import annotations

from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from openavatar.application import ApplicationContext
from openavatar.routes._shared import require_avatar
from openavatar.schemas import (
    ContinuityPlanRequest,
    SceneProfileCreate,
    SceneProfileUpdate,
    VisualAssetItemCreate,
    VisualAssetSetCreate,
    VisualAssetSetUpdate,
)
from openavatar.services.continuity import (
    add_asset_item,
    build_continuity_contract,
    create_asset_set,
    create_continuity_run,
    create_scene_profile,
    get_asset_set,
    list_asset_sets,
    list_continuity_runs,
    list_scene_profiles,
    list_video_keyframes,
    organize_legacy_assets,
    update_asset_set,
    update_scene_profile,
    update_continuity_run,
    get_continuity_run,
)


def create_continuity_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db
    settings = context.settings

    @router.get("/api/avatars/{avatar_id}/visual-asset-sets")
    def asset_sets(avatar_id: str) -> list[dict]:
        require_avatar(db, avatar_id)
        return list_asset_sets(db, avatar_id)

    @router.post("/api/avatars/{avatar_id}/visual-asset-sets", status_code=201)
    def add_set(avatar_id: str, payload: VisualAssetSetCreate) -> dict:
        require_avatar(db, avatar_id)
        try:
            return create_asset_set(db, avatar_id, **payload.model_dump())
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.patch("/api/avatars/{avatar_id}/visual-asset-sets/{set_id}")
    def patch_set(avatar_id: str, set_id: str, payload: VisualAssetSetUpdate) -> dict:
        require_avatar(db, avatar_id)
        try:
            return update_asset_set(db, avatar_id, set_id, **payload.model_dump())
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/visual-asset-sets/{set_id}/items", status_code=201)
    def add_item(avatar_id: str, set_id: str, payload: VisualAssetItemCreate) -> dict:
        require_avatar(db, avatar_id)
        try:
            return add_asset_item(db, avatar_id, set_id, **payload.model_dump())
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/visual-asset-sets/organize")
    def organize(avatar_id: str) -> dict:
        require_avatar(db, avatar_id)
        return organize_legacy_assets(db, avatar_id)

    @router.get("/api/avatars/{avatar_id}/scene-profiles")
    def scenes(avatar_id: str) -> list[dict]:
        require_avatar(db, avatar_id)
        return list_scene_profiles(db, avatar_id)

    @router.post("/api/avatars/{avatar_id}/scene-profiles", status_code=201)
    def add_scene(avatar_id: str, payload: SceneProfileCreate) -> dict:
        require_avatar(db, avatar_id)
        return create_scene_profile(db, avatar_id, **payload.model_dump())

    @router.patch("/api/avatars/{avatar_id}/scene-profiles/{scene_id}")
    def patch_scene(avatar_id: str, scene_id: str, payload: SceneProfileUpdate) -> dict:
        require_avatar(db, avatar_id)
        try:
            patch = {key: value for key, value in payload.model_dump().items() if value is not None}
            return update_scene_profile(db, avatar_id, scene_id, patch)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/continuity/plan")
    def continuity_plan(avatar_id: str, payload: ContinuityPlanRequest) -> dict:
        require_avatar(db, avatar_id)
        contract = build_continuity_contract(db, avatar_id, payload.prompt, hints=payload.hints)
        return {"contract": contract, "ready": bool(contract["ready_for_video"]), "needs_key_image": "scene_key_image" in contract["missing"] or "first_frame" in contract["missing"]}

    @router.post("/api/avatars/{avatar_id}/continuity/runs", status_code=201)
    def add_continuity_run(avatar_id: str, payload: ContinuityPlanRequest) -> dict:
        require_avatar(db, avatar_id)
        contract = build_continuity_contract(db, avatar_id, payload.prompt, hints=payload.hints)
        return create_continuity_run(db, avatar_id, "", payload.prompt, contract)

    @router.get("/api/avatars/{avatar_id}/continuity/runs")
    def continuity_runs(avatar_id: str) -> list[dict]:
        require_avatar(db, avatar_id)
        return list_continuity_runs(db, avatar_id)

    @router.post("/api/avatars/{avatar_id}/continuity/runs/{run_id}/approve")
    def approve_continuity_run(avatar_id: str, run_id: str) -> dict:
        require_avatar(db, avatar_id)
        try:
            run = get_continuity_run(db, avatar_id, run_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        review = dict(run.get("review") or {})
        review.update({"sendable": True, "manual_review": True, "manual_approved": True})
        update_continuity_run(db, run_id, status="approved", review=review)
        db.execute("UPDATE video_keyframes SET status='history_reference' WHERE continuity_run_id=?", (run_id,))
        if run.get("job_id"):
            db.execute(
                "UPDATE training_jobs SET status='completed',stage='视频已由用户人工确认',error='',finished_at=strftime('%s','now'),updated_at=strftime('%s','now') WHERE id=? AND avatar_id=?",
                (run["job_id"], avatar_id),
            )
        return get_continuity_run(db, avatar_id, run_id)

    @router.get("/api/avatars/{avatar_id}/video-keyframes")
    def keyframes(avatar_id: str) -> list[dict]:
        require_avatar(db, avatar_id)
        return list_video_keyframes(db, avatar_id)

    @router.get("/api/avatars/{avatar_id}/video-keyframes/{keyframe_id}/file")
    def keyframe_file(avatar_id: str, keyframe_id: int) -> FileResponse:
        require_avatar(db, avatar_id)
        row = db.one("SELECT local_path FROM video_keyframes WHERE id=? AND avatar_id=?", (keyframe_id, avatar_id))
        if not row:
            raise HTTPException(404, "视频关键帧不存在")
        base = settings.data_dir.resolve()
        target = (base / str(row["local_path"])).resolve()
        if base not in target.parents or not target.is_file():
            raise HTTPException(404, "视频关键帧文件不存在")
        return FileResponse(Path(target))

    return router
