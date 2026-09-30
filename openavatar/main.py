from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles

from openavatar import __version__
from openavatar.application import ApplicationContext
from openavatar.services.model_connections import (
    model_client,
    provider_config,
    public_runtime_mode,
    unavailable_model_message,
)
from openavatar.config import Settings, ensure_directories, load_settings
from openavatar.db import Database
from openavatar.events import EventStore
from openavatar.routes.archive import create_archive_router
from openavatar.routes.avatars import create_avatars_router
from openavatar.routes.calls import create_call_router
from openavatar.routes.chat import create_chat_router
from openavatar.routes.continuity import create_continuity_router
from openavatar.routes.identity import create_identity_router
from openavatar.routes.imports import create_imports_router
from openavatar.routes.intelligence import create_intelligence_router
from openavatar.routes.media_runtime import create_media_runtime_router
from openavatar.routes.providers import create_provider_router
from openavatar.routes.runtime import create_runtime_router
from openavatar.routes.system import create_system_router
from openavatar.routes.world import create_world_router
from openavatar.runtime import BackgroundSupervisor, LeaseManager, Metrics, PeriodicJob, RunRegistry
from openavatar.services.chat_runtime import ChatService
from openavatar.services.http_security import install_local_security
from openavatar.services.proactive_runtime import proactive_tick
from openavatar.services.media_jobs import poll_video_jobs
from openavatar.services.readiness import completion_report


def create_app(*, settings: Settings | None = None) -> FastAPI:
    selected = settings or load_settings()
    ensure_directories(selected)
    db = Database(selected.database_path)
    db.initialize()
    metrics = Metrics()
    runs = RunRegistry()
    events = EventStore(db)
    leases = LeaseManager(db)
    supervisor = BackgroundSupervisor(leases, metrics)
    chat_service = ChatService(
        db=db,
        settings=selected,
        metrics=metrics,
        runs=runs,
        events=events,
        readiness=completion_report,
        model_client_factory=model_client,
        provider_config_factory=provider_config,
        unavailable_message=unavailable_model_message,
        public_runtime_mode=public_runtime_mode,
    )

    def runtime_maintenance() -> None:
        now = int(time.time())
        db.execute("DELETE FROM request_metrics WHERE created_at<?", (now - 30 * 86400,))
        db.execute("DELETE FROM event_outbox WHERE status='delivered' AND delivered_at<?", (now - 7 * 86400,))

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        supervisor.start([
            PeriodicJob(
                "proactive-contact",
                60,
                lambda: proactive_tick(app, completion_report=completion_report, model_client=model_client),
                lease_seconds=90,
            ),
            PeriodicJob("runtime-maintenance", 3600, runtime_maintenance, lease_seconds=120),
            PeriodicJob("video-job-poller", 15, lambda: poll_video_jobs(db, selected), lease_seconds=30),
        ])
        try:
            yield
        finally:
            await supervisor.stop()

    app = FastAPI(title="OpenAvatar Studio", version=__version__, lifespan=lifespan)
    app.state.settings = selected
    app.state.db = db
    app.state.metrics = metrics
    app.state.runs = runs
    app.state.events = events
    install_local_security(app)

    @app.middleware("http")
    async def observe_requests(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", "")[:100] or uuid.uuid4().hex
        started = time.perf_counter()
        status_code = 500
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            metrics.increment(f"http.status.{status_code}")
            metrics.observe("http.duration_ms", duration_ms)
            try:
                db.execute(
                    "INSERT OR IGNORE INTO request_metrics(request_id,method,path,status_code,duration_ms,avatar_id,created_at) VALUES(?,?,?,?,?,?,?)",
                    (request_id, request.method, request.url.path[:500], status_code, duration_ms, "", int(time.time())),
                )
            except Exception:
                metrics.increment("http.metric_write.failure")

    context = ApplicationContext(selected, db, metrics, runs, events, chat_service)
    for router in (
        create_system_router(context),
        create_avatars_router(context),
        create_imports_router(context),
        create_world_router(context),
        create_identity_router(context),
        create_continuity_router(context),
        create_intelligence_router(context),
        create_media_runtime_router(context),
        create_provider_router(context),
        create_archive_router(context),
        create_runtime_router(db=db, settings=selected, metrics=metrics, runs=runs, events=events),
        create_chat_router(chat_service),
        create_call_router(db=db, runs=runs, chat=chat_service),
    ):
        app.include_router(router)

    static_dir = Path(__file__).parent / "static"
    app.mount("/", StaticFiles(directory=static_dir, html=True), name="static")
    return app


app = create_app()
