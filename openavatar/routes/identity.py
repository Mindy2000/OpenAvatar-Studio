from __future__ import annotations

from openavatar.routes._shared import *
from openavatar.services.minimax import MiniMaxClient, MiniMaxError
from openavatar.services.provider_hub import provider_key_name, record_provider_usage, route_candidates
from openavatar.services.continuity import approve_linked_visual_asset


def create_identity_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db
    selected = context.settings
    runs = context.runs
    chat_service = context.chat

    @router.get("/api/avatars/{avatar_id}/rights")
    def avatar_rights(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        rows = db.all(
            "SELECT id,source_import_id,grant_type,subject_kind,rights_scope,data_classes_json,provider_transfer_allowed,commercial_use_allowed,revocable,note,confirmed_at FROM rights_grants WHERE avatar_id=? ORDER BY id DESC",
            (avatar_id,),
        )
        for row in rows:
            row["data_classes"] = json.loads(row.pop("data_classes_json", "[]"))
            for key in ("provider_transfer_allowed", "commercial_use_allowed", "revocable"):
                row[key] = bool(row[key])
        return rows

    @router.get("/api/avatars/{avatar_id}/visual-assets")
    def avatar_visual_assets(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        rows = db.all(
            "SELECT id,asset_kind,status,label,local_path,provider,metadata_json,approved_at,created_at FROM visual_assets WHERE avatar_id=? ORDER BY id DESC",
            (avatar_id,),
        )
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json", "{}"))
            row["asset_url"] = f"/api/avatars/{avatar_id}/visual-assets/{row['id']}/file" if row.get("local_path") else ""
        return rows

    @router.get("/api/avatars/{avatar_id}/visual-assets/{asset_id}/file")
    def visual_asset_file(avatar_id: str, asset_id: int) -> FileResponse:
        require_avatar(db, avatar_id)
        row = db.one("SELECT * FROM visual_assets WHERE id=? AND avatar_id=?", (asset_id, avatar_id))
        if not row or not row.get("local_path"):
            raise HTTPException(404, "视觉素材文件不存在")
        base = selected.data_dir.resolve()
        target = (base / str(row["local_path"])).resolve()
        if base not in target.parents or not target.is_file():
            raise HTTPException(404, "视觉素材文件不存在")
        return FileResponse(target)

    @router.patch("/api/avatars/{avatar_id}/visual-assets/{asset_id}")
    def update_visual_asset(avatar_id: str, asset_id: int, payload: VisualAssetUpdate) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        row = db.one("SELECT * FROM visual_assets WHERE id=? AND avatar_id=?", (asset_id, avatar_id))
        if not row:
            raise HTTPException(404, "视觉素材不存在")
        now = int(time.time())
        metadata = json.loads(str(row.get("metadata_json") or "{}"))
        metadata.setdefault("reviews", []).append({"status": payload.status, "note": payload.note, "reviewed_at": now})
        if payload.status == "canonical":
            db.execute(
                "UPDATE visual_assets SET status='approved' WHERE avatar_id=? AND asset_kind=? AND status='canonical'",
                (avatar_id, row["asset_kind"]),
            )
        db.execute(
            "UPDATE visual_assets SET status=?,label=?,metadata_json=?,approved_at=? WHERE id=?",
            (
                payload.status,
                (payload.label if payload.label is not None else row["label"])[:200],
                json.dumps(metadata, ensure_ascii=False),
                now if payload.status in {"approved", "canonical"} else int(row["approved_at"] or 0),
                asset_id,
            ),
        )
        updated = db.one("SELECT id,asset_kind,status,label,local_path,provider,metadata_json,approved_at,created_at FROM visual_assets WHERE id=?", (asset_id,))
        updated["metadata"] = json.loads(updated.pop("metadata_json", "{}"))
        updated["asset_url"] = f"/api/avatars/{avatar_id}/visual-assets/{asset_id}/file" if updated.get("local_path") else ""
        if payload.status in {"approved", "canonical"}:
            create_visual_review(db, avatar_id, asset_id)
            approve_linked_visual_asset(db, avatar_id, asset_id, payload.status)
        return updated

    @router.get("/api/avatars/{avatar_id}/media-reviews")
    def avatar_media_reviews(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        return media_reviews(db, avatar_id)

    @router.post("/api/avatars/{avatar_id}/visual-assets/{asset_id}/review")
    def review_visual_asset(avatar_id: str, asset_id: int) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return create_visual_review(db, avatar_id, asset_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/media-reviews/{review_id}/feedback")
    def feedback_media_review(avatar_id: str, review_id: int, payload: MediaFeedbackPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return record_media_feedback(db, avatar_id, review_id, payload.feedback, payload.comment)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/api/avatars/{avatar_id}/voice-profiles")
    def avatar_voice_profiles(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        ensure_voice_choices(db, avatar_id)
        rows = db.all(
            "SELECT id,provider,voice_id,voice_name,profile_kind,status,model,metadata_json,active,created_at FROM voice_profiles WHERE avatar_id=? ORDER BY active DESC,id DESC",
            (avatar_id,),
        )
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json", "{}"))
            row["active"] = bool(row["active"])
        return rows

    @router.post("/api/avatars/{avatar_id}/voice-profiles", status_code=201)
    def add_voice_profile(avatar_id: str, payload: VoiceProfileCreate) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        result = create_voice_profile(db, avatar_id, payload.model_dump())
        if "metadata_json" in result:
            result["metadata"] = json.loads(result.pop("metadata_json", "{}"))
            result["active"] = bool(result["active"])
        return result

    @router.post("/api/avatars/{avatar_id}/voice-profiles/{profile_id}/select")
    def set_voice_profile(avatar_id: str, profile_id: int) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return select_voice_profile(db, avatar_id, profile_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/api/avatars/{avatar_id}/voice-transcriptions")
    def avatar_voice_transcriptions(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        rows = db.all(
            "SELECT id,source_import_id,provider,model,transcript,status,confidence,metadata_json,created_at,confirmed_at FROM voice_transcriptions WHERE avatar_id=? ORDER BY id DESC LIMIT 200",
            (avatar_id,),
        )
        for row in rows:
            row["metadata"] = json.loads(row.pop("metadata_json", "{}"))
        return rows

    @router.post("/api/avatars/{avatar_id}/voice-transcriptions/{transcription_id}/run")
    def run_voice_transcription(avatar_id: str, transcription_id: int, payload: TrainingRun) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        if not payload.confirm_billable_call:
            raise HTTPException(400, "语音转写会上传音频并可能产生 API 费用，请明确确认")
        row = db.one("SELECT * FROM voice_transcriptions WHERE id=? AND avatar_id=?", (transcription_id, avatar_id))
        if not row:
            raise HTTPException(404, "语音转写记录不存在")
        imported = db.one("SELECT * FROM imports WHERE id=? AND avatar_id=?", (row["source_import_id"], avatar_id))
        if not imported:
            raise HTTPException(404, "原始音频不存在")
        audio_path = selected.data_dir / str(imported["stored_path"])
        errors = []
        for connection, model, route_config in route_candidates(db, "asr", avatar_id):
            connection_id = str(connection["id"])
            if str(connection["provider_kind"]) != "minimax":
                errors.append(f"{connection['display_name']} 的 ASR 适配器尚不可用")
                continue
            started = time.perf_counter()
            try:
                config = json.loads(connection.get("config_json") or "{}")
                result = MiniMaxClient(
                    load_provider_key(provider_key_name(connection_id)), str(connection["base_url"]), endpoints=config.get("endpoints", {})
                ).transcribe(audio_path, model=model, config=route_config)
                if not result["text"].strip():
                    raise MiniMaxError("转写接口没有返回文字")
                db.execute(
                    "UPDATE voice_transcriptions SET provider=?,model=?,transcript=?,status='needs_review',confidence=?,metadata_json=? WHERE id=?",
                    (connection_id, model, result["text"], 0.8, json.dumps({"file_id": result["file_id"]}, ensure_ascii=False), transcription_id),
                )
                record_provider_usage(db, avatar_id, connection_id, model, "asr", "ok", latency_ms=(time.perf_counter() - started) * 1000)
                return dict(db.one("SELECT * FROM voice_transcriptions WHERE id=?", (transcription_id,)))
            except (MiniMaxError, OSError) as exc:
                errors.append(f"{connection['display_name']}：{exc}")
                record_provider_usage(db, avatar_id, connection_id, model, "asr", "failed", latency_ms=(time.perf_counter() - started) * 1000, metadata={"error": str(exc)[:500]})
        if not errors:
            raise HTTPException(400, "尚未配置 ASR 能力路由")
        raise HTTPException(502, "；".join(errors))

    @router.post("/api/avatars/{avatar_id}/voice-transcriptions/{transcription_id}/confirm")
    def confirm_voice_transcription(avatar_id: str, transcription_id: int, payload: TranscriptionConfirm) -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        row = db.one("SELECT * FROM voice_transcriptions WHERE id=? AND avatar_id=?", (transcription_id, avatar_id))
        if not row:
            raise HTTPException(404, "语音转写记录不存在")
        now = int(time.time())
        speaker = payload.speaker.strip() or str(avatar["name"])
        with db.transaction() as connection:
            connection.execute(
                "UPDATE voice_transcriptions SET transcript=?,status='confirmed',confidence=1,confirmed_at=? WHERE id=?",
                (payload.transcript, now, transcription_id),
            )
            insert_evidence(
                connection,
                avatar_id=avatar_id,
                source_import_id=row["source_import_id"],
                source_type="real_audio_transcript",
                title="声音转写确认",
                content=payload.transcript,
                tags=["audio", "transcript"],
                derived_kind="audio_transcript",
                confidence=1.0,
                created_at=now,
            )
            if payload.use_as_memory:
                connection.execute(
                    "INSERT INTO memories(avatar_id,source_import_id,speaker,content,kind,is_avatar,confidence,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (avatar_id, row["source_import_id"], speaker, payload.transcript, "audio_transcript", 1, 1.0, now),
                )
            connection.execute(
                "INSERT INTO voice_events(avatar_id,event_kind,transcript_id,emotion,tone,confidence,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (avatar_id, "transcript_confirmed", transcription_id, "", "", 1.0, json.dumps({"source_import_id": row["source_import_id"]}, ensure_ascii=False), now),
            )
        rebuild_memory_graph(db, avatar_id, 500)
        return dict(db.one("SELECT * FROM voice_transcriptions WHERE id=?", (transcription_id,)))

    @router.post("/api/avatars/{avatar_id}/analyze")
    def analyze_avatar(avatar_id: str) -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        if str(avatar["subject_kind"]) != "fictional":
            text_counts = route_text(db, avatar_id)
            if text_counts["conversation"] <= 0 and text_counts["image_ocr"] <= 0:
                raise HTTPException(400, "真实素材路线必须先确认文字或聊天记录；音频只能构建音色，不能单独生成人格简介。")
        config = provider_config(db, selected, avatar_id)
        job = create_job(
            db,
            avatar_id,
            "persona",
            provider=config.provider_name,
            status="running",
            stage="正在整理人物表达样本",
        )
        update_job(db, job["id"], progress=20)
        rows = db.all("SELECT speaker,content FROM memories WHERE avatar_id=? AND is_avatar=1 ORDER BY id LIMIT 100000", (avatar_id,))
        if not rows:
            rows = db.all("SELECT speaker,content FROM memories WHERE avatar_id=? ORDER BY id LIMIT 100000", (avatar_id,))
        update_job(db, job["id"], progress=45, stage="正在提取人格和说话方式")
        profile = build_profile(rows, str(avatar["name"]), model_client(db, selected, avatar_id))
        now = int(time.time())
        db.execute(
            "UPDATE persona_profiles SET summary=?,traits_json=?,speaking_style=?,boundaries=?,source_count=?,updated_at=? WHERE avatar_id=?",
            (
                profile["summary"], json.dumps(profile["traits"], ensure_ascii=False), profile["speaking_style"],
                profile["boundaries"], profile["source_count"], now, avatar_id,
            ),
        )
        update_job(
            db,
            job["id"],
            status="completed",
            progress=100,
            stage="人格档案已生成，等待用户确认",
            result={"method": profile["method"], "source_count": profile["source_count"]},
        )
        rebuild_memory_graph(db, avatar_id, 500)
        build_persona_core(db, avatar_id)
        profile["training_job_id"] = job["id"]
        return profile

    @router.get("/api/avatars/{avatar_id}/materials/report")
    def avatar_material_report(avatar_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        return write_material_report(db, avatar_id)

    return router
