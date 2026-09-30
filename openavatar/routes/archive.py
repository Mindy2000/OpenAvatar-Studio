from __future__ import annotations

from openavatar.routes._shared import *
from openavatar.services.minimax import MiniMaxClient, MiniMaxError, write_audio_result
from openavatar.services.provider_hub import estimate_provider_cost, provider_key_name, record_provider_usage, route_candidates


def create_archive_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db
    selected = context.settings
    runs = context.runs
    chat_service = context.chat

    @router.get("/api/avatars/{avatar_id}/persona")
    def get_persona(avatar_id: str) -> dict[str, Any]:
        return chat_service.get_persona(avatar_id)

    @router.put("/api/avatars/{avatar_id}/persona")
    def update_persona(avatar_id: str, payload: PersonaUpdate) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        db.execute(
            "UPDATE persona_profiles SET summary=?,traits_json=?,speaking_style=?,boundaries=?,updated_at=? WHERE avatar_id=?",
            (payload.summary, json.dumps(payload.traits, ensure_ascii=False), payload.speaking_style, payload.boundaries, int(time.time()), avatar_id),
        )
        return get_persona(avatar_id)

    @router.get("/api/avatars/{avatar_id}/messages")
    def get_messages(avatar_id: str, limit: int = 100, timeline_kind: str = "official") -> list[dict[str, Any]]:
        return chat_service.get_messages(avatar_id, limit, timeline_kind)

    @router.get("/api/avatars/{avatar_id}/history")
    def avatar_history(
        avatar_id: str,
        q: str = "",
        layer: str = "all",
        day: str = "",
        timeline_kind: str = "official",
        limit: int = 200,
    ) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        if layer not in {"all", "historical", "runtime"} or timeline_kind not in {"official", "preview"}:
            raise HTTPException(400, "聊天记录筛选参数不合法")
        return search_records(db, avatar_id, query=q, layer=layer, day=day, timeline_kind=timeline_kind, limit=limit)

    @router.put("/api/avatars/{avatar_id}/history/{memory_id}/correction")
    def correct_avatar_history(avatar_id: str, memory_id: int, payload: HistoricalCorrectionPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return correct_historical_memory(db, avatar_id, memory_id, payload.model_dump())
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/api/avatars/{avatar_id}/timeline")
    def avatar_timeline(avatar_id: str, timeline_kind: str = "official") -> dict[str, Any]:
        require_avatar(db, avatar_id)
        if timeline_kind not in {"official", "preview"}:
            raise HTTPException(400, "时间线类型不合法")
        return timeline_overview(db, avatar_id, timeline_kind)

    @router.post("/api/avatars/{avatar_id}/timeline/preview-change")
    def preview_avatar_timeline_change(avatar_id: str, payload: TimelineChangePreviewPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return preview_timeline_change(db, avatar_id, payload.model_dump())
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/timeline/apply-change")
    def apply_avatar_timeline_change(avatar_id: str, payload: TimelineApplyPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return apply_timeline_change(db, avatar_id, payload.preview_token)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/timeline/restore")
    def restore_avatar_timeline(avatar_id: str, payload: TimelineBranchPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return restore_timeline_branch(db, avatar_id, payload.branch_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/timeline/delete-branch")
    def permanently_delete_avatar_timeline(avatar_id: str, payload: TimelineBranchPayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return delete_timeline_branch(db, avatar_id, payload.branch_id)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc

    @router.get("/api/avatars/{avatar_id}/timeline/media-candidates")
    def avatar_timeline_media_candidates(avatar_id: str) -> list[dict[str, Any]]:
        require_avatar(db, avatar_id)
        return list_timeline_candidates(db, avatar_id)

    @router.put("/api/avatars/{avatar_id}/timeline/media-candidates/{candidate_id}")
    def update_avatar_timeline_media_candidate(avatar_id: str, candidate_id: int, payload: TimelineCandidatePayload) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        try:
            return update_timeline_candidate(db, avatar_id, candidate_id, payload.status, payload.confirmed)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/speech")
    def synthesize_avatar_speech(avatar_id: str, payload: SpeechRequest) -> FileResponse:
        require_avatar(db, avatar_id)
        if not payload.confirm_billable_call:
            raise HTTPException(400, "生成复刻语音会调用云端 API 并可能产生费用，请明确确认")
        profile = db.one(
            "SELECT * FROM provider_assets WHERE avatar_id=? AND kind='voice' AND active=1 ORDER BY id DESC LIMIT 1",
            (avatar_id,),
        )
        if not profile or not profile.get("external_id"):
            raise HTTPException(400, "该数字人还没有完成声音复刻")
        candidates = route_candidates(db, "tts", avatar_id)
        if candidates:
            errors = []
            for connection, model, route_config in candidates:
                connection_id = str(connection["id"])
                if str(connection["provider_kind"]) == "aliyun":
                    target = selected.avatars_dir / avatar_id / "generated" / "audio" / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.mp3"
                    started = time.perf_counter()
                    try:
                        result = AliyunAvatarClient(load_provider_key(provider_key_name(connection_id))).synthesize(payload.text, voice_id=str(profile["external_id"]), model=model or "qwen3-tts-vc-2026-01-22")
                        urls = extract_urls(result.get("output", {}))
                        if not urls:
                            raise AliyunError("语音接口没有返回可下载的音频")
                        media_type = download_provider_asset(urls[0], target, max_bytes=30 * 1024 * 1024)
                        record_provider_usage(db, avatar_id, connection_id, model, "tts", "ok", latency_ms=(time.perf_counter() - started) * 1000)
                        return FileResponse(target, media_type=media_type or "audio/mpeg", filename=target.name)
                    except AliyunError as exc:
                        errors.append(f"{connection['display_name']}：{exc}")
                        continue
                if str(connection["provider_kind"]) != "minimax":
                    errors.append(f"{connection['display_name']} 的 TTS 适配器尚不可用")
                    continue
                target = selected.avatars_dir / avatar_id / "generated" / "audio" / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.mp3"
                started = time.perf_counter()
                try:
                    config = json.loads(connection.get("config_json") or "{}")
                    client = MiniMaxClient(
                        load_provider_key(provider_key_name(connection_id)), str(connection["base_url"]),
                        endpoints=config.get("endpoints", {}),
                    )
                    result = client.synthesize(payload.text, voice_id=str(profile["external_id"]), model=model or "speech-2.8-hd", config=route_config)
                    media_type = write_audio_result(result, target)
                    record_provider_usage(db, avatar_id, connection_id, model, "tts", "ok", latency_ms=(time.perf_counter() - started) * 1000, estimated_cost=estimate_provider_cost(connection, "tts", input_units=len(payload.text)))
                    return FileResponse(target, media_type=media_type, filename=target.name)
                except (MiniMaxError, OSError) as exc:
                    errors.append(f"{connection['display_name']}：{exc}")
                    record_provider_usage(db, avatar_id, connection_id, model, "tts", "failed", latency_ms=(time.perf_counter() - started) * 1000, metadata={"error": str(exc)[:500]})
            raise HTTPException(502, "；".join(errors) or "没有可用的语音合成服务")
        cloud = db.setting("cloud_services", {})
        if not bool(cloud.get("cloud_data_consent", False)):
            raise HTTPException(400, "尚未允许将待合成文字发送给云端服务商")
        try:
            result = AliyunAvatarClient(load_provider_key("aliyun")).synthesize(
                payload.text,
                voice_id=str(profile["external_id"]),
                model=str(cloud.get("voice_tts_model", "qwen3-tts-vc-2026-01-22")),
            )
            urls = extract_urls(result.get("output", {}))
            if not urls:
                raise AliyunError("语音接口没有返回可下载的音频")
            target = selected.avatars_dir / avatar_id / "generated" / "audio" / f"{int(time.time())}-{uuid.uuid4().hex[:8]}.mp3"
            media_type = download_provider_asset(urls[0], target, max_bytes=30 * 1024 * 1024)
            return FileResponse(target, media_type=media_type or "audio/mpeg", filename=target.name)
        except AliyunError as exc:
            raise HTTPException(502, str(exc)) from exc

    @router.get("/api/avatars/{avatar_id}/generated/{kind}/{filename}")
    def get_generated_asset(avatar_id: str, kind: Literal["audio", "images", "video"], filename: str) -> FileResponse:
        require_avatar(db, avatar_id)
        safe = safe_filename(filename)
        if safe != filename:
            raise HTTPException(400, "生成素材名称不合法")
        base = (selected.avatars_dir / avatar_id / "generated" / kind).resolve()
        target = (base / safe).resolve()
        if target.parent != base or not target.is_file():
            raise HTTPException(404, "生成素材不存在")
        return FileResponse(target)

    @router.post("/api/avatars/{avatar_id}/export")
    def export(avatar_id: str, include_conversations: bool = True, include_audio: bool = True, include_images: bool = True, include_video: bool | None = None, include_call_history: bool = True) -> FileResponse:
        require_avatar(db, avatar_id)
        path = export_avatar(
            db,
            selected.avatars_dir,
            selected.exports_dir,
            avatar_id,
            include_conversations=include_conversations,
            include_audio=include_audio,
            include_images=include_images,
            include_video=include_images if include_video is None else include_video,
            include_call_history=include_call_history,
        )
        return FileResponse(path, filename=path.name, media_type="application/zip")

    @router.post("/api/packages/inspect")
    async def inspect_package(request: Request) -> dict[str, Any]:
        body = await request.body()
        if not body:
            raise HTTPException(400, "请先选择人物包文件")
        if len(body) > 1024 * 1024 * 1024:
            raise HTTPException(413, "人物包超过 1GB 限制")
        selected.exports_dir.mkdir(parents=True, exist_ok=True)
        temporary = selected.exports_dir / f"inspect-{uuid.uuid4().hex}.zip"
        temporary.write_bytes(body)
        try:
            return inspect_avatar_package(temporary)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            temporary.unlink(missing_ok=True)

    @router.post("/api/packages/import", status_code=201)
    async def import_package(request: Request) -> dict[str, Any]:
        if request.headers.get("X-Rights-Confirmed", "").lower() != "true":
            raise HTTPException(400, "导入前必须确认拥有人物包及其中资料的使用权")
        filename = safe_filename(unquote(request.headers.get("X-File-Name", "avatar.openavatar.zip")))
        if not filename.endswith((".zip", ".openavatar.zip")):
            raise HTTPException(415, "请选择 OpenAvatar 人物包")
        temporary = selected.exports_dir / f"import-{uuid.uuid4().hex}.zip"
        await save_upload(request, temporary, min(selected.max_upload_bytes * 10, 1024 * 1024 * 1024))
        try:
            result = import_avatar_package(db, selected.avatars_dir, temporary)
        except (ValueError, zipfile.BadZipFile) as exc:
            raise HTTPException(400, str(exc)) from exc
        finally:
            temporary.unlink(missing_ok=True)
        return result

    @router.delete("/api/avatars/{avatar_id}")
    def delete_avatar(avatar_id: str, confirmation: str) -> dict[str, bool]:
        avatar = require_avatar(db, avatar_id)
        if confirmation != str(avatar["name"]):
            raise HTTPException(400, "确认文本必须与数字人名称完全一致")
        db.execute("DELETE FROM avatars WHERE id=?", (avatar_id,))
        delete_avatar_files(selected.avatars_dir, avatar_id)
        return {"deleted": True}

    return router
