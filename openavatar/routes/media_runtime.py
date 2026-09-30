from __future__ import annotations

from openavatar.routes._shared import *
import base64

from openavatar.services.minimax import MiniMaxClient, MiniMaxError
from openavatar.services.provider_hub import estimate_provider_cost, find_route, provider_key_name, record_provider_usage, route_candidates
from openavatar.services.continuity import (
    build_continuity_contract,
    continuity_prompt,
    create_continuity_run,
    finalize_video_continuity,
    get_continuity_run,
    register_key_image_candidate,
    update_continuity_run,
)


def _job_reference_paths(db: Database, settings: Settings, avatar_id: str, job: dict[str, Any]) -> list[Path]:
    result = job.get("result") or {}
    run_id = str(result.get("continuity_run_id") or "")
    if run_id:
        try:
            contract = get_continuity_run(db, avatar_id, run_id)["contract"]
            refs = continuity_reference_inputs(settings, contract, max_items=5, max_total_bytes=18 * 1024 * 1024)
            paths: list[Path] = []
            for ref in refs:
                asset_id = int(ref.get("visual_asset_id") or 0)
                asset = db.one("SELECT local_path FROM visual_assets WHERE id=? AND avatar_id=?", (asset_id, avatar_id)) if asset_id else None
                if asset and asset.get("local_path"):
                    path = (settings.data_dir / str(asset["local_path"])).resolve()
                    if path.is_file() and path not in paths:
                        paths.append(path)
            if paths:
                return paths
        except KeyError:
            pass
    items = db.all("SELECT stored_path FROM imports WHERE avatar_id=? AND category='image' ORDER BY id DESC LIMIT 3", (avatar_id,))
    return [settings.data_dir / str(item["stored_path"]) for item in reversed(items) if (settings.data_dir / str(item["stored_path"])).is_file()]


def create_media_runtime_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db
    selected = context.settings
    runs = context.runs
    chat_service = context.chat

    @router.get("/api/avatars/{avatar_id}/video-call/status")
    def avatar_video_call_status(avatar_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        settings_payload = video_call_settings(db, avatar_id)
        face_path = video_call_face_path(db, selected, avatar_id)
        status = video_call_provider_status(settings_payload, face_path)
        status["hasCanonicalOrApprovedFace"] = bool(face_path)
        status["hasFaceUrl"] = bool(settings_payload.get("north_face_url"))
        status["settings"] = settings_payload
        return status

    @router.post("/api/avatars/{avatar_id}/calls", status_code=201)
    def create_call_session(avatar_id: str, payload: CallSessionCreate) -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        now = int(time.time())
        provider = "north" if payload.mode == "video" else payload.provider
        metadata = {"protocol": "openavatar.realtime-call.v1", "mode": payload.mode, **payload.metadata}
        if payload.mode == "video":
            settings_payload = video_call_settings(db, avatar_id)
            if not settings_payload["video_call_enabled"]:
                raise HTTPException(400, "实时视频通话已关闭")
            if not payload.confirm_billable_call:
                raise HTTPException(400, "North 实时视频通话会上传身份参考图并可能产生费用，请明确确认")
            if not settings_payload["cloud_data_consent"]:
                raise HTTPException(400, "尚未允许实时视频通话所需数据发送给 North/Atlas")
            settings_payload["north_api_key"] = settings_payload.get("north_api_key") or load_provider_key("north")
            if not settings_payload.get("north_api_key"):
                raise HTTPException(400, "尚未配置 North/Atlas API Key")
        call_id = db.execute(
            "INSERT INTO realtime_call_sessions(avatar_id,status,provider,started_at,metadata_json) VALUES(?,?,?,?,?)",
            (avatar_id, "connecting" if payload.mode == "video" else "active", provider, now, json.dumps(metadata, ensure_ascii=False)),
        )
        row = dict(db.one("SELECT * FROM realtime_call_sessions WHERE id=?", (call_id,)))
        if payload.mode != "video":
            return row
        try:
            face_path = video_call_face_path(db, selected, avatar_id)
            result = start_north_video_call(
                settings_payload,
                VideoCallStartRequest(
                    avatar_id=avatar_id,
                    call_id=call_id,
                    avatar_name=str(avatar["name"]),
                    user_camera_enabled=payload.user_camera_enabled,
                    metadata=payload.metadata,
                ),
                face_path,
            )
        except ProviderError as exc:
            db.execute(
                "UPDATE realtime_call_sessions SET status='failed',ended_at=?,summary=?,metadata_json=? WHERE id=?",
                (int(time.time()), str(exc)[:1000], json.dumps({**metadata, "error": str(exc)}, ensure_ascii=False), call_id),
            )
            raise HTTPException(502, str(exc)) from exc
        updated_metadata = {**metadata, **result.get("metadata", {}), "livekit_room": result.get("livekit", {}).get("room", "")}
        db.execute(
            "UPDATE realtime_call_sessions SET status='active',metadata_json=? WHERE id=?",
            (json.dumps(updated_metadata, ensure_ascii=False), call_id),
        )
        row = dict(db.one("SELECT * FROM realtime_call_sessions WHERE id=?", (call_id,)))
        row["video_call"] = {key: value for key, value in result.items() if key != "metadata"}
        return row

    @router.post("/api/avatars/{avatar_id}/calls/{call_id}/turns", status_code=201)
    def record_call_turn(avatar_id: str, call_id: int, payload: CallTurnCreate) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        call = db.one("SELECT * FROM realtime_call_sessions WHERE id=? AND avatar_id=?", (call_id, avatar_id))
        if not call:
            raise HTTPException(404, "通话记录不存在")
        turn_id = db.execute(
            """
            INSERT INTO realtime_call_turns
            (avatar_id,call_session_id,user_transcript,assistant_text,asr_latency_ms,llm_latency_ms,tts_latency_ms,interrupted,metadata_json,created_at)
            VALUES(?,?,?,?,?,?,?,?,?,?)
            """,
            (
                avatar_id,
                call_id,
                payload.user_transcript,
                payload.assistant_text,
                payload.asr_latency_ms,
                payload.llm_latency_ms,
                payload.tts_latency_ms,
                int(payload.interrupted),
                json.dumps(payload.metadata, ensure_ascii=False),
                int(time.time()),
            ),
        )
        return dict(db.one("SELECT * FROM realtime_call_turns WHERE id=?", (turn_id,)))

    @router.post("/api/avatars/{avatar_id}/calls/{call_id}/events", status_code=201)
    def record_video_call_event(avatar_id: str, call_id: int, payload: VideoCallEventCreate) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        call = db.one("SELECT * FROM realtime_call_sessions WHERE id=? AND avatar_id=?", (call_id, avatar_id))
        if not call:
            raise HTTPException(404, "通话记录不存在")
        metadata = json.loads(call.get("metadata_json") or "{}")
        events = metadata.get("events") if isinstance(metadata.get("events"), list) else []
        events.append({"type": payload.event_type, "payload": payload.payload, "created_at": int(time.time())})
        metadata["events"] = events[-200:]
        db.execute("UPDATE realtime_call_sessions SET metadata_json=? WHERE id=?", (json.dumps(metadata, ensure_ascii=False), call_id))
        return {"recorded": True, "event_count": len(metadata["events"])}

    @router.post("/api/avatars/{avatar_id}/video-call/prepare-background")
    def prepare_video_call_background(avatar_id: str, payload: VideoCallBackgroundRequest) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        settings_payload = video_call_settings(db, avatar_id)
        if not settings_payload["scene_background_enabled"] and payload.mode == "scene":
            return {"ok": False, "reason": "scene-background-disabled"}
        world = runtime_state(db, avatar_id)
        facts = world.get("facts", [])
        place = ""
        for item in facts:
            key = str(item.get("fact_key") or "")
            if any(token in key for token in ("place", "location", "home", "city", "room")):
                place = json.dumps(item.get("value"), ensure_ascii=False)[:200]
                break
        joined = "\n".join(f"{item.get('fact_key')}: {json.dumps(item.get('value'), ensure_ascii=False)}" for item in facts[:30])
        prompt_text = (
            "为实时视频通话准备背景。只生成环境，不出现数字人本人，不覆盖当前世界地点；"
            f"用户补充：{payload.prompt or '无'}。\n当前世界事实：\n{joined[:3000]}"
        )
        metadata = {
            "asset_role": "video_call_background",
            "mode": payload.mode,
            "prompt": prompt_text,
            "world_fact_count": len(facts),
            "place": place,
        }
        return {
            "ok": True,
            "source": "world_prompt",
            "ready": True,
            "mode": payload.mode,
            "prompt": prompt_text,
            "metadata": metadata,
            "rule": "background-only; no avatar pasted into image; must match approved world facts",
        }

    @router.post("/api/avatars/{avatar_id}/video-call/flip-video")
    def prepare_video_call_flip_video(avatar_id: str, payload: VideoCallBackgroundRequest) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        settings_payload = video_call_settings(db, avatar_id)
        if not settings_payload["camera_flip_enabled"]:
            return {"ok": False, "reason": "camera-flip-disabled"}
        background = prepare_video_call_background(avatar_id, VideoCallBackgroundRequest(prompt=payload.prompt, mode="flipped"))
        job = create_job(
            db,
            avatar_id,
            "video",
            provider="video-generation",
            status="waiting_configuration",
            stage="等待提交异步视频生成任务",
            input_summary="实时视频通话翻转镜头",
        )
        job = update_job(
            db,
            job["id"],
            result={
                "asset_role": "video_call_flip_video",
                "flip_label": "翻转镜头",
                "background": background,
                "provider_scope": "openrouter-primary-aliyun-fallback",
            },
        )
        return {
            "ok": True,
            "ready": False,
            "taskId": job["id"],
            "status": job["status"],
            "flipLabel": "翻转镜头",
            "background": background,
            "note": "OpenAvatar 已记录翻转镜头任务；可在构建中心提交真实异步视频生成。",
        }

    @router.post("/api/avatars/{avatar_id}/calls/{call_id}/vision-feedback", status_code=201)
    def record_video_call_vision_feedback(avatar_id: str, call_id: int, payload: VideoCallVisionFeedback) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        call = db.one("SELECT * FROM realtime_call_sessions WHERE id=? AND avatar_id=?", (call_id, avatar_id))
        if not call:
            raise HTTPException(404, "通话记录不存在")
        now = int(time.time())
        review_id = db.execute(
            "INSERT INTO media_reviews(avatar_id,media_kind,asset_id,review_kind,status,score,findings_json,user_feedback_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                avatar_id,
                "video_call",
                call_id,
                "north_vision_feedback",
                "completed",
                80 if payload.feedback in {"clear", "good", "ok"} else 50,
                json.dumps([{"feedback": payload.feedback, "frame_summary": payload.frame_summary}], ensure_ascii=False),
                json.dumps({"comment": payload.comment}, ensure_ascii=False),
                now,
                now,
            ),
        )
        return dict(db.one("SELECT * FROM media_reviews WHERE id=?", (review_id,)))

    @router.post("/api/avatars/{avatar_id}/calls/{call_id}/end")
    def end_call_session(avatar_id: str, call_id: int) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        call = db.one("SELECT * FROM realtime_call_sessions WHERE id=? AND avatar_id=?", (call_id, avatar_id))
        if not call:
            raise HTTPException(404, "通话记录不存在")
        if call.get("status") == "ended":
            return dict(call)
        turns = db.all("SELECT user_transcript,assistant_text FROM realtime_call_turns WHERE avatar_id=? AND call_session_id=? ORDER BY id", (avatar_id, call_id))
        summary = "；".join((row["user_transcript"] or row["assistant_text"])[:80] for row in turns[:8])
        ended_at = int(time.time())
        metadata = json.loads(call.get("metadata_json") or "{}")
        close_payload = {}
        if call.get("provider") == "north" and metadata.get("north_session_id"):
            close_payload = close_north_session(video_call_settings(db, avatar_id), str(metadata.get("north_session_id")))
            duration_seconds = max(0, ended_at - int(call.get("started_at") or ended_at))
            metadata["north_close"] = close_payload
            metadata["duration_seconds"] = duration_seconds
            metadata["estimated_cost"] = round(duration_seconds * float(metadata.get("price_per_second") or 0.00194), 4)
        db.execute(
            "UPDATE realtime_call_sessions SET status='ended',ended_at=?,summary=?,metadata_json=? WHERE id=?",
            (ended_at, summary[:1000] or "实时视频通话已结束", json.dumps(metadata, ensure_ascii=False), call_id),
        )
        return dict(db.one("SELECT * FROM realtime_call_sessions WHERE id=?", (call_id,)))

    @router.post("/api/avatars/{avatar_id}/training-jobs/{job_id}/cancel")
    def cancel_training_job(avatar_id: str, job_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        job = get_job(db, job_id)
        if job["avatar_id"] != avatar_id:
            raise HTTPException(404, "构建任务不存在")
        return request_cancel(db, job_id)

    @router.post("/api/avatars/{avatar_id}/training-jobs/{job_id}/retry")
    def retry_training_job(avatar_id: str, job_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        job = get_job(db, job_id)
        if job["avatar_id"] != avatar_id:
            raise HTTPException(404, "构建任务不存在")
        try:
            return retry_job(db, job_id)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.post("/api/avatars/{avatar_id}/training-jobs/{job_id}/run")
    def run_cloud_training_job(avatar_id: str, job_id: str, payload: TrainingRun) -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        job = get_job(db, job_id)
        if job["avatar_id"] != avatar_id:
            raise HTTPException(404, "构建任务不存在")
        if job["job_type"] not in {"voice", "visual", "video"}:
            raise HTTPException(400, "该任务不需要云端构建")
        if job["status"] == "completed":
            return job
        if not payload.confirm_billable_call:
            raise HTTPException(400, "这一操作会上传素材并可能产生 API 费用，请明确确认")
        cloud = db.setting("cloud_services", {})
        job_capability = {"voice": "voice_clone", "visual": "image", "video": "video"}.get(str(job["job_type"]), "")
        if not bool(cloud.get("cloud_data_consent", False)) and not find_route(db, job_capability, avatar_id):
            raise HTTPException(400, "尚未允许声音和图片素材发送给云端服务商")
        if job["job_type"] == "video":
            current_result = job.get("result") or {}
            prompt = str((current_result.get("background") or {}).get("prompt") or current_result.get("prompt") or f"为{avatar['name']}生成一段自然的实时通话翻转镜头短视频")
            continuity_run_id = str(current_result.get("continuity_run_id") or "")
            if continuity_run_id:
                try:
                    continuity_run = get_continuity_run(db, avatar_id, continuity_run_id)
                    contract = continuity_run["contract"]
                    if not contract.get("ready_for_video"):
                        refreshed = build_continuity_contract(db, avatar_id, prompt, hints=current_result.get("continuity_hints") or {})
                        if refreshed.get("ready_for_video"):
                            contract = refreshed
                            continuity_run_id = ""
                except KeyError:
                    continuity_run_id = ""
                    contract = build_continuity_contract(db, avatar_id, prompt, hints=current_result.get("continuity_hints") or {})
            else:
                contract = build_continuity_contract(db, avatar_id, prompt, hints=current_result.get("continuity_hints") or {})
            if not continuity_run_id:
                continuity_run = create_continuity_run(db, avatar_id, job_id, prompt, contract)
                continuity_run_id = str(continuity_run["id"])
            current_result = {
                **current_result,
                "continuity_run_id": continuity_run_id,
                "continuity_contract": contract,
                "needs_key_image": not bool(contract.get("ready_for_video")),
            }
            if not contract.get("ready_for_video"):
                missing_labels = {
                    "identity": "批准的人物身份包",
                    "scene_key_image": "当前场景的关键首帧",
                    "first_frame": "可用于视频的首帧",
                }
                missing = "、".join(missing_labels.get(item, str(item)) for item in contract.get("missing", []))
                key_image_job_id = str(current_result.get("key_image_job_id") or "")
                if "scene_key_image" in contract.get("missing", []) and not key_image_job_id:
                    scene_name = "当前场景"
                    if contract.get("scene_profile_id"):
                        scene_row = db.one("SELECT display_name FROM scene_profiles WHERE id=? AND avatar_id=?", (contract["scene_profile_id"], avatar_id))
                        scene_name = str((scene_row or {}).get("display_name") or scene_name)
                    key_job = create_job(
                        db,
                        avatar_id,
                        "visual",
                        provider="continuity-key-image",
                        status="waiting_configuration",
                        stage="等待生成场景关键首帧",
                        input_summary=f"{scene_name} · 视频连续性首帧",
                    )
                    key_job = update_job(
                        db,
                        key_job["id"],
                        result={
                            "asset_role": "scene_key_image",
                            "prompt": f"为{avatar['name']}生成一张位于{scene_name}的自然生活照片，保持人物身份、服装、主要物品和场景结构一致，作为后续短视频首帧。",
                            "scene_profile_id": contract.get("scene_profile_id", ""),
                            "continuity_run_id": continuity_run_id,
                        },
                    )
                    key_image_job_id = str(key_job["id"])
                    current_result["key_image_job_id"] = key_image_job_id
                return update_job(
                    db,
                    job_id,
                    status="waiting_configuration",
                    progress=15,
                    stage=f"一致性门禁：请先准备{missing}",
                    result=current_result,
                )
            prompt = continuity_prompt(prompt, contract)
            reference_inputs = continuity_reference_inputs(selected, contract)
            routed_video = route_candidates(db, "video", avatar_id)
            routed_video_legacy = None
            if routed_video:
                errors = []
                for connection, model, route_config in routed_video:
                    connection_id = str(connection["id"])
                    if str(connection["provider_kind"]) in {"aliyun", "openrouter"}:
                        routed_video_legacy = (connection, model, route_config)
                        break
                    if str(connection["provider_kind"]) != "minimax":
                        errors.append(f"{connection['display_name']} 的视频适配器尚不可用")
                        continue
                    started_at = time.perf_counter()
                    try:
                        config = json.loads(connection.get("config_json") or "{}")
                        minimax = MiniMaxClient(load_provider_key(provider_key_name(connection_id)), str(connection["base_url"]), endpoints=config.get("endpoints", {}), timeout=300)
                        minimax_first_frame = continuity_first_frame(selected, contract, allow_data_url=True)
                        last_frame_contract = {"references": [contract.get("last_frame") or {}]}
                        minimax_last_frame = continuity_reference_inputs(selected, last_frame_contract, max_items=1)
                        minimax_last_frame_url = str(minimax_last_frame[0]["url"]) if minimax_last_frame else ""
                        minimax_references = [str(item["url"]) for item in reference_inputs]
                        use_reference_mode = str(route_config.get("mode") or "auto") == "reference" or not minimax_first_frame
                        task_id = str(current_result.get("provider_task_id") or "")
                        if task_id and job["status"] == "running":
                            polled = minimax.query_video(task_id)
                            if not polled["done"]:
                                return update_job(db, job_id, progress=50, stage=f"MiniMax 视频仍在生成：{polled['status']}", result={**current_result, "last_poll": polled})
                            if not polled["urls"]:
                                raise MiniMaxError("MiniMax 视频完成但没有返回下载地址")
                            filename = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4"
                            target = selected.avatars_dir / avatar_id / "generated" / "video" / filename
                            media_type = download_video_result(str(polled["urls"][0]), target)
                            review = finalize_video_continuity(
                                db,
                                selected,
                                avatar_id=avatar_id,
                                job_id=job_id,
                                run_id=continuity_run_id,
                                video_path=target,
                            )
                            result = {**current_result, "asset_url": f"/api/avatars/{avatar_id}/generated/video/{filename}", "remote_url": polled["urls"][0], "media_type": media_type, "continuity_review": review}
                            record_provider_usage(db, avatar_id, connection_id, model, "video", "ok", latency_ms=(time.perf_counter() - started_at) * 1000, estimated_cost=estimate_provider_cost(connection, "video"))
                            if not review["sendable"] and review.get("visual_review", {}).get("available") and int(job.get("attempt") or 0) < 1:
                                retry_prompt = f"{prompt}\n上一次视频连续性检查未通过。减少镜头运动，保持人物、服装、物品和场景结构完全稳定。"
                                retry = minimax.create_video(
                                    retry_prompt,
                                    model=model or "MiniMax-H3",
                                    first_frame_url="" if use_reference_mode else minimax_first_frame,
                                    last_frame_url="" if use_reference_mode else minimax_last_frame_url,
                                    reference_images=minimax_references if use_reference_mode else None,
                                    config=route_config,
                                )
                                db.execute("UPDATE training_jobs SET attempt=attempt+1 WHERE id=?", (job_id,))
                                update_continuity_run(db, continuity_run_id, status="resubmitted", provider=connection_id, provider_task_id=retry["task_id"])
                                return update_job(db, job_id, status="running", progress=40, stage="首版未通过，已自动提交一次稳定性重试", result={**result, "provider_task_id": retry["task_id"], "previous_candidate_url": result["asset_url"], "auto_retry": True})
                            return update_job(db, job_id, status="completed" if review["sendable"] else "needs_review", progress=100, stage="MiniMax 视频已生成并通过连续性验收" if review["sendable"] else "视频已生成，等待人工复核", result=result, error="")
                        if not claim_job(db, job_id, allowed_statuses=("waiting_configuration", "queued", "failed")):
                            raise HTTPException(409, "任务已由另一个请求提交，请刷新任务状态")
                        started = minimax.create_video(
                            prompt,
                            model=model or "MiniMax-H3",
                            first_frame_url="" if use_reference_mode else minimax_first_frame,
                            last_frame_url="" if use_reference_mode else minimax_last_frame_url,
                            reference_images=minimax_references if use_reference_mode else None,
                            config=route_config,
                        )
                        update_continuity_run(db, continuity_run_id, status="submitted", provider=connection_id, provider_task_id=started["task_id"])
                        result = {
                            **current_result, "prompt": prompt, "provider": connection_id, "model": model,
                            "provider_task_id": started["task_id"], "provider_status": "submitted",
                            "video_mode": started.get("mode", "first_frame"),
                            "reference_audit": [{key: item.get(key) for key in ("set_type", "role", "visual_asset_id", "content_bytes")} for item in reference_inputs],
                        }
                        return update_job(db, job_id, status="running", progress=35, stage="MiniMax 异步视频任务已提交", result=result)
                    except (MiniMaxError, VideoGenerationError, OSError) as exc:
                        errors.append(f"{connection['display_name']}：{exc}")
                        record_provider_usage(db, avatar_id, connection_id, model, "video", "failed", latency_ms=(time.perf_counter() - started_at) * 1000, metadata={"error": str(exc)[:500]})
                if not routed_video_legacy:
                    update_job(db, job_id, status="failed", stage="视频任务失败", error="；".join(errors))
                    raise HTTPException(502, "；".join(errors) or "没有可用的视频服务")
            if routed_video_legacy:
                video_connection, video_model, video_route_config = routed_video_legacy
                video_kind = str(video_connection["provider_kind"])
                video_key = load_provider_key(provider_key_name(str(video_connection["id"])))
                settings_payload = VideoGenerationSettings(
                    provider=video_kind,
                    openrouter_api_key=video_key if video_kind == "openrouter" else "",
                    aliyun_api_key=video_key if video_kind == "aliyun" else "",
                    openrouter_model=video_model or "google/veo-3.1-fast",
                    aliyun_model=video_model or "wan2.7-i2v-2026-04-25",
                    duration=int(video_route_config.get("duration", 8)),
                    resolution=str(video_route_config.get("resolution", "720p")),
                    aspect_ratio=str(video_route_config.get("aspect_ratio", "9:16")),
                    fallback_provider="",
                    generate_audio=bool(video_route_config.get("generate_audio", False)),
                    reference_images=tuple(str(item["url"]) for item in reference_inputs),
                    last_frame=continuity_first_frame(selected, {"first_frame": contract.get("last_frame") or {}}, allow_data_url=video_kind == "aliyun"),
                )
            else:
                base_settings = video_generation_settings(db, selected, avatar_id, prompt)
                settings_payload = VideoGenerationSettings(
                    **{**base_settings.__dict__, "reference_images": tuple(str(item["url"]) for item in reference_inputs), "last_frame": continuity_first_frame(selected, {"first_frame": contract.get("last_frame") or {}}, allow_data_url=base_settings.provider == "aliyun")}
                )
            first_frame = continuity_first_frame(
                selected,
                contract,
                allow_data_url=settings_payload.provider == "aliyun",
            )
            task_id = str(current_result.get("provider_task_id") or "")
            try:
                if task_id and job["status"] == "running":
                    polled = poll_video_generation(
                        settings_payload,
                        provider=str(current_result.get("provider") or job.get("provider") or settings_payload.provider),
                        task_id=task_id,
                        polling_url=str(current_result.get("polling_url") or ""),
                    )
                    if not polled.get("done"):
                        return update_job(db, job_id, progress=45, stage=f"视频仍在生成：{polled.get('status', 'PENDING')}", result={**current_result, "last_poll": polled})
                    filename = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.mp4"
                    target = selected.avatars_dir / avatar_id / "generated" / "video" / filename
                    media_type = download_video_result(
                        str(polled["remote_url"]),
                        target,
                        api_key=settings_payload.openrouter_api_key if polled.get("requires_auth") else "",
                    )
                    result = {
                        **current_result,
                        "asset_url": f"/api/avatars/{avatar_id}/generated/video/{filename}",
                        "remote_url": polled["remote_url"],
                        "media_type": media_type,
                        "provider_task_id": task_id,
                        "provider": current_result.get("provider") or job.get("provider") or settings_payload.provider,
                    }
                    review = finalize_video_continuity(
                        db,
                        selected,
                        avatar_id=avatar_id,
                        job_id=job_id,
                        run_id=continuity_run_id,
                        video_path=target,
                    )
                    result["continuity_review"] = review
                    if not review["sendable"] and review.get("visual_review", {}).get("available") and int(job.get("attempt") or 0) < 1:
                        retry = start_video_generation(
                            settings_payload,
                            prompt=f"{prompt}\n上一次视频连续性检查未通过。减少镜头运动，保持人物、服装、物品和场景结构完全稳定。",
                            first_frame=first_frame,
                            metadata={"avatar_id": avatar_id, "auto_retry": True},
                        )
                        db.execute("UPDATE training_jobs SET attempt=attempt+1 WHERE id=?", (job_id,))
                        update_continuity_run(db, continuity_run_id, status="resubmitted", provider=str(retry["provider"]), provider_task_id=str(retry["task_id"]))
                        return update_job(db, job_id, status="running", progress=40, stage="首版未通过，已自动提交一次稳定性重试", result={**result, "provider_task_id": retry["task_id"], "polling_url": retry.get("polling_url", ""), "previous_candidate_url": result["asset_url"], "auto_retry": True})
                    return update_job(db, job_id, status="completed" if review["sendable"] else "needs_review", progress=100, stage="异步视频已生成并通过连续性验收" if review["sendable"] else "视频已生成，等待人工复核", result=result, error="")
                if not claim_job(db, job_id, allowed_statuses=("waiting_configuration", "queued", "failed")):
                    raise HTTPException(409, "任务已由另一个请求提交，请刷新任务状态")
                started = start_video_generation(
                    settings_payload,
                    prompt=prompt,
                    first_frame=first_frame,
                    metadata={"asset_role": current_result.get("asset_role", "video_generation"), "avatar_id": avatar_id},
                )
                result = {
                    **current_result,
                    "prompt": prompt,
                    "provider": started["provider"],
                    "model": started["model"],
                    "provider_task_id": started["task_id"],
                    "polling_url": started.get("polling_url", ""),
                    "provider_status": started.get("status", "PENDING"),
                    "video_metadata": started.get("metadata", {}),
                    "reference_audit": [{key: item.get(key) for key in ("set_type", "role", "visual_asset_id", "content_bytes")} for item in reference_inputs],
                }
                update_continuity_run(db, continuity_run_id, status="submitted", provider=str(started["provider"]), provider_task_id=str(started["task_id"]))
                return update_job(
                    db,
                    job_id,
                    status="running",
                    progress=35,
                    stage=f"异步视频任务已提交：{started['provider']} · {started.get('status', 'PENDING')}",
                    result=result,
                )
            except VideoGenerationError as exc:
                update_job(db, job_id, status="failed", stage="异步视频任务失败", error=str(exc))
                raise HTTPException(502, str(exc)) from exc
        capability = "voice_clone" if job["job_type"] == "voice" else "image"
        candidates = route_candidates(db, capability, avatar_id)
        routed_aliyun = None
        if candidates:
            errors = []
            update_job(db, job_id, status="running", progress=10, stage="正在通过能力路由准备素材")
            for connection, model, route_config in candidates:
                connection_id = str(connection["id"])
                if str(connection["provider_kind"]) == "aliyun":
                    routed_aliyun = (connection, model, route_config)
                    break
                if str(connection["provider_kind"]) != "minimax":
                    errors.append(f"{connection['display_name']} 的 {capability} 适配器尚不可用")
                    continue
                started_at = time.perf_counter()
                try:
                    config = json.loads(connection.get("config_json") or "{}")
                    minimax = MiniMaxClient(load_provider_key(provider_key_name(connection_id)), str(connection["base_url"]), endpoints=config.get("endpoints", {}))
                    if job["job_type"] == "voice":
                        item = db.one("SELECT * FROM imports WHERE avatar_id=? AND category='audio' ORDER BY id DESC LIMIT 1", (avatar_id,))
                        if not item:
                            raise MiniMaxError("没有可用的声音样本")
                        sample = selected.data_dir / str(item["stored_path"])
                        voice_id = f"oa_{avatar_id[:8]}_{uuid.uuid4().hex[:6]}"[:32]
                        result = minimax.clone_voice(sample, voice_id=voice_id, model=model or "speech-2.8-hd", config=route_config)
                        db.execute("UPDATE provider_assets SET active=0 WHERE avatar_id=? AND kind='voice'", (avatar_id,))
                        db.execute(
                            "INSERT INTO provider_assets(avatar_id,kind,provider,external_id,source_import_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                            (avatar_id, "voice", connection_id, result["voice_id"], item["id"], json.dumps(result, ensure_ascii=False), int(time.time())),
                        )
                        stage = "MiniMax 声音复刻档案已创建"
                    else:
                        paths = _job_reference_paths(db, selected, avatar_id, job)
                        if not paths:
                            raise MiniMaxError("没有可用的参考照片")
                        references = []
                        for path in paths:
                            mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
                            references.append(f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}")
                        visual_prompt = str((job.get("result") or {}).get("prompt") or f"保持{avatar['name']}的面部身份特征，生成一张自然、真实的日常人物照片。")
                        generated = minimax.generate_image(
                            visual_prompt,
                            model=model or "image-01", reference_urls=references, config=route_config,
                        )
                        if not generated["urls"]:
                            raise MiniMaxError("图片接口没有返回可下载的图片")
                        filename = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.png"
                        target = selected.avatars_dir / avatar_id / "generated" / "images" / filename
                        media_type = download_provider_asset(generated["urls"][0], target, max_bytes=50 * 1024 * 1024)
                        result = {"asset_url": f"/api/avatars/{avatar_id}/generated/images/{filename}", "reference_count": len(paths), "media_type": media_type, "prompt": visual_prompt}
                        if str((job.get("result") or {}).get("asset_role") or "") == "scene_key_image":
                            linked = register_key_image_candidate(
                                db,
                                selected,
                                avatar_id=avatar_id,
                                local_path=target,
                                provider=connection_id,
                                remote_url=str(generated["urls"][0]),
                                scene_profile_id=str((job.get("result") or {}).get("scene_profile_id") or ""),
                            )
                            result.update(linked)
                        db.execute("UPDATE provider_assets SET active=0 WHERE avatar_id=? AND kind='visual'", (avatar_id,))
                        db.execute(
                            "INSERT INTO provider_assets(avatar_id,kind,provider,metadata_json,created_at) VALUES(?,?,?,?,?)",
                            (avatar_id, "visual", connection_id, json.dumps(result, ensure_ascii=False), int(time.time())),
                        )
                        stage = "MiniMax 人物参考图生成已完成"
                    record_provider_usage(db, avatar_id, connection_id, model, capability, "ok", latency_ms=(time.perf_counter() - started_at) * 1000, estimated_cost=estimate_provider_cost(connection, capability))
                    return update_job(db, job_id, status="completed", progress=100, stage=stage, result=result)
                except (MiniMaxError, AliyunError, OSError) as exc:
                    errors.append(f"{connection['display_name']}：{exc}")
                    record_provider_usage(db, avatar_id, connection_id, model, capability, "failed", latency_ms=(time.perf_counter() - started_at) * 1000, metadata={"error": str(exc)[:500]})
            if not routed_aliyun:
                update_job(db, job_id, status="failed", stage="能力路由中的云端任务失败", error="；".join(errors))
                raise HTTPException(502, "；".join(errors) or "没有可用的服务连接")
        if routed_aliyun:
            aliyun_connection, aliyun_model, _aliyun_route_config = routed_aliyun
            client = AliyunAvatarClient(load_provider_key(provider_key_name(str(aliyun_connection["id"]))))
            if capability == "voice_clone" and aliyun_model:
                cloud = {**cloud, "voice_clone_model": aliyun_model, "voice_target_model": aliyun_model}
            if capability == "image" and aliyun_model:
                cloud = {**cloud, "image_reference_model": aliyun_model}
        else:
            client = AliyunAvatarClient(load_provider_key("aliyun"))
        if not client.available():
            raise HTTPException(400, "尚未配置阿里云百炼 API Key")
        update_job(db, job_id, status="running", progress=10, stage="正在准备经授权的素材")
        try:
            if job["job_type"] == "voice":
                item = db.one("SELECT * FROM imports WHERE avatar_id=? AND category='audio' ORDER BY id DESC LIMIT 1", (avatar_id,))
                if not item:
                    raise AliyunError("没有可用的声音样本")
                sample = selected.data_dir / str(item["stored_path"])
                safe_name = re.sub(r"[^a-z0-9]", "", f"oa{avatar_id}".lower())[:12]
                result = client.clone_voice(
                    sample,
                    preferred_name=f"{safe_name}{uuid.uuid4().hex[:4]}"[:16],
                    clone_model=str(cloud.get("voice_clone_model", "qwen-voice-enrollment")),
                    target_model=str(cloud.get("voice_target_model", "qwen3-tts-vc-2026-01-22")),
                )
                db.execute("UPDATE provider_assets SET active=0 WHERE avatar_id=? AND kind='voice'", (avatar_id,))
                db.execute(
                    "INSERT INTO provider_assets(avatar_id,kind,provider,external_id,source_import_id,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (avatar_id, "voice", "aliyun", result["voice_id"], item["id"], json.dumps(result, ensure_ascii=False), int(time.time())),
                )
                stage = "声音复刻档案已创建"
            else:
                paths = _job_reference_paths(db, selected, avatar_id, job)
                if not paths:
                    raise AliyunError("没有可用的参考照片")
                visual_prompt = str((job.get("result") or {}).get("prompt") or f"保持{avatar['name']}的面部身份特征，生成一张自然、真实的日常人物照片。")
                result = client.generate_reference_image(
                    paths,
                    prompt=visual_prompt,
                    model=str(cloud.get("image_reference_model", "qwen-image-2.0-pro")),
                )
                output = result.get("output") if isinstance(result.get("output"), dict) else {}
                urls = extract_urls(output)
                if not urls:
                    raise AliyunError("参考图接口没有返回可下载的图片")
                filename = f"{int(time.time())}-{uuid.uuid4().hex[:8]}.png"
                target = selected.avatars_dir / avatar_id / "generated" / "images" / filename
                media_type = download_provider_asset(urls[0], target, max_bytes=50 * 1024 * 1024)
                local_result = {"filename": filename, "media_type": media_type, "reference_count": len(paths)}
                db.execute("UPDATE provider_assets SET active=0 WHERE avatar_id=? AND kind='visual'", (avatar_id,))
                db.execute(
                    "INSERT INTO provider_assets(avatar_id,kind,provider,metadata_json,created_at) VALUES(?,?,?,?,?)",
                    (avatar_id, "visual", "aliyun", json.dumps(local_result, ensure_ascii=False), int(time.time())),
                )
                result = {"asset_url": f"/api/avatars/{avatar_id}/generated/images/{filename}", "reference_count": len(paths), "prompt": visual_prompt}
                if str((job.get("result") or {}).get("asset_role") or "") == "scene_key_image":
                    linked = register_key_image_candidate(
                        db,
                        selected,
                        avatar_id=avatar_id,
                        local_path=target,
                        provider="aliyun",
                        remote_url=str(urls[0]),
                        scene_profile_id=str((job.get("result") or {}).get("scene_profile_id") or ""),
                    )
                    result.update(linked)
                stage = "人物参考图生成已完成"
            return update_job(db, job_id, status="completed", progress=100, stage=stage, result=result)
        except AliyunError as exc:
            update_job(db, job_id, status="failed", stage="云端任务失败", error=str(exc))
            raise HTTPException(502, str(exc)) from exc

    return router
