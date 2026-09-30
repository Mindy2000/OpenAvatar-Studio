from __future__ import annotations

import time
import uuid
from typing import Any

from fastapi import APIRouter, HTTPException

from openavatar.config import Settings
from openavatar.db import Database
from openavatar.events import EventStore
from openavatar.runtime import Metrics, RunRegistry
from openavatar.services.importers import safe_filename


def create_runtime_router(
    *,
    db: Database,
    settings: Settings,
    metrics: Metrics,
    runs: RunRegistry,
    events: EventStore,
) -> APIRouter:
    router = APIRouter()

    @router.post("/api/runtime/runs/{run_id}/cancel")
    def cancel_run(run_id: str, avatar_id: str = "") -> dict[str, Any]:
        return {"ok": True, "cancelled": runs.cancel(run_id, avatar_id), "run_id": run_id}

    @router.get("/api/runtime/metrics")
    def runtime_metrics() -> dict[str, Any]:
        return {"metrics": metrics.snapshot(), "active_runs": runs.snapshot(), "database": db.integrity_check()}

    @router.get("/api/avatars/{avatar_id}/runtime/events")
    def runtime_events(avatar_id: str, limit: int = 100) -> dict[str, Any]:
        if not db.one("SELECT id FROM avatars WHERE id=?", (avatar_id,)):
            raise HTTPException(404, "数字人不存在")
        return {"items": events.list(avatar_id, limit)}

    @router.post("/api/system/backup")
    def create_database_backup() -> dict[str, Any]:
        target = db.backup(
            settings.data_dir
            / "backups"
            / f"openavatar-{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:8]}.sqlite"
        )
        return {"ok": True, "filename": target.name, "integrity": db.integrity_check()}

    @router.get("/api/system/backups")
    def list_database_backups() -> dict[str, Any]:
        folder = settings.data_dir / "backups"
        items = [
            {"filename": path.name, "size_bytes": path.stat().st_size, "modified_at": int(path.stat().st_mtime)}
            for path in sorted(folder.glob("openavatar-*.sqlite"), key=lambda item: item.stat().st_mtime, reverse=True)
            if path.is_file()
        ] if folder.is_dir() else []
        return {"items": items[:100]}

    @router.post("/api/system/backups/{filename}/restore")
    def restore_database_backup(filename: str, confirmation: str = "") -> dict[str, Any]:
        if confirmation != "RESTORE OPENAVATAR DATABASE":
            raise HTTPException(400, "恢复确认文本不正确")
        safe = safe_filename(filename)
        if safe != filename or not safe.endswith(".sqlite"):
            raise HTTPException(400, "备份文件名不合法")
        folder = (settings.data_dir / "backups").resolve()
        source = (folder / safe).resolve()
        if source.parent != folder:
            raise HTTPException(400, "备份路径不合法")
        try:
            safety = db.restore(source)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {"ok": True, "restored": safe, "safety_backup": safety.name, "integrity": db.integrity_check()}

    return router
