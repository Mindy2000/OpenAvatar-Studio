from __future__ import annotations

from openavatar import __version__
from openavatar.migrations import LATEST_SCHEMA_VERSION
from openavatar.routes._shared import *


def create_system_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db
    selected = context.settings
    runs = context.runs
    chat_service = context.chat

    @router.get("/api/ready")
    def ready() -> dict[str, Any]:
        # Startup readiness must not wait for optional model/provider connections.
        return {"ok": True, "service": "openavatar-studio", "version": __version__}

    @router.get("/api/health")
    def health() -> dict[str, Any]:
        config = provider_config(db, selected)
        client = model_client(db, selected)
        return {
            "ok": True,
            "version": __version__,
            "development_state": "local_workspace_only",
            "runtime_mode": public_runtime_mode(config.mode),
            "connection_type": config.mode,
            "provider_name": config.provider_name,
            "provider_available": client.available(),
            "model": client.model,
            "cloud_data_consent": config.cloud_data_consent,
            "schema_version": LATEST_SCHEMA_VERSION,
            "database_integrity": db.integrity_check()["ok"],
            "active_runs": len(runs.snapshot()),
        }

    @router.get("/api/onboarding")
    def get_onboarding() -> dict[str, Any]:
        return {
            "completed": bool(db.setting("onboarding_completed", False)),
            "style": "steps_with_inline_hints",
            "recommendation": "第一次打开用步骤卡建立全局理解，进入系统后用轻量提示标出关键位置。",
        }

    @router.get("/api/notifications")
    def notifications(after_id: int = 0, limit: int = 30) -> list[dict[str, Any]]:
        return db.all(
            "SELECT id,avatar_id,kind,title,body,action_url,read_at,created_at FROM user_notifications WHERE id>? ORDER BY id LIMIT ?",
            (max(0, after_id), min(max(limit, 1), 100)),
        )

    @router.post("/api/notifications/{notification_id}/read")
    def read_notification(notification_id: int) -> dict[str, Any]:
        db.execute("UPDATE user_notifications SET read_at=? WHERE id=?", (int(time.time()), notification_id))
        return {"read": True, "id": notification_id}

    @router.get("/api/i18n/{language}")
    def i18n(language: str) -> dict[str, Any]:
        locale = "en-US" if language == "en-US" else "zh-CN"
        path = Path(__file__).parent.parent / "i18n" / f"{locale}.json"
        return {
            "language": locale,
            "messages": json.loads(path.read_text(encoding="utf-8")),
            "selected": current_interface_language(db),
        }

    @router.get("/api/world-options")
    def get_world_options() -> dict[str, Any]:
        return world_options()

    @router.put("/api/settings/interface-language")
    def set_interface_language(payload: InterfaceLanguageUpdate) -> dict[str, Any]:
        db.set_setting("interface_language", payload.language)
        return {"language": current_interface_language(db)}

    @router.put("/api/onboarding")
    def set_onboarding(payload: OnboardingState) -> dict[str, Any]:
        db.set_setting("onboarding_completed", bool(payload.completed))
        return get_onboarding()

    @router.get("/api/diagnostics")
    def diagnostics() -> dict[str, Any]:
        config = provider_config(db, selected)
        client = model_client(db, selected)
        provider_status = {
            "provider_name": config.provider_name,
            "model": client.model,
            "provider_available": client.available(),
        }
        return system_diagnostics(db, selected, provider_status)

    @router.get("/api/settings/model")
    def get_model_settings() -> dict[str, Any]:
        current = db.setting("model", {})
        selected_connection = selected_model_connection_id(db)
        return {
            "mode": str(current.get("mode", "local")),
            "provider_name": str(current.get("provider_name", "openrouter")),
            "ollama_url": str(current.get("ollama_url", selected.ollama_url)),
            "ollama_model": str(current.get("ollama_model", selected.ollama_model)),
            "base_url": str(current.get("base_url", "https://openrouter.ai/api/v1")),
            "model": str(current.get("model", "openrouter/auto")),
            "cloud_data_consent": bool(current.get("cloud_data_consent", False)),
            "has_api_key": bool(load_api_key()),
            "selected_connection_id": selected_connection,
        }

    @router.put("/api/settings/model")
    def set_model_settings(payload: ModelSettings) -> dict[str, Any]:
        if payload.mode == "cloud" and not payload.cloud_data_consent:
            raise HTTPException(400, "请先确认：云端模型会接收完成任务所需的资料片段")
        try:
            if payload.mode == "cloud":
                normalize_openai_base_url(payload.base_url)
                if payload.clear_api_key:
                    delete_api_key()
                if payload.api_key.strip():
                    store_api_key(payload.api_key.strip())
                if not load_api_key():
                    raise ProviderError("云端模式需要填写自己的 API Key")
            config_to_save = payload.model_dump(exclude={"api_key", "clear_api_key"})
            db.set_setting("model", config_to_save)
            client = model_client(db, selected)
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc
        return {
            "saved": True,
            "available": client.available(),
            "mode": payload.mode,
            "has_api_key": bool(load_api_key()),
            "selected_connection_id": selected_model_connection_id(db),
        }

    @router.get("/api/model-connections")
    def get_model_connections() -> dict[str, Any]:
        rows = db.all("SELECT * FROM model_connections ORDER BY updated_at DESC")
        return {
            "selected_connection_id": selected_model_connection_id(db),
            "connections": [public_model_connection(row) for row in rows],
            "presets": [
                {"connection_type": "cloud_openai", "label": "云端 OpenAI 兼容 API", "base_url": "https://openrouter.ai/api/v1", "model": "openrouter/auto", "requires_key": True},
                {"connection_type": "local_openai", "label": "本地 OpenAI 兼容服务", "base_url": "http://127.0.0.1:1234/v1", "model": "local-model", "requires_key": False},
                {"connection_type": "ollama", "label": "Ollama", "base_url": "http://127.0.0.1:11434", "model": "qwen3:8b", "requires_key": False},
                {"connection_type": "custom_local_adapter", "label": "自定义本地适配器", "base_url": "http://127.0.0.1:8000/v1", "model": "local-model", "requires_key": False},
            ],
        }

    @router.post("/api/model-connections", status_code=201)
    def create_model_connection(payload: ModelConnectionPayload) -> dict[str, Any]:
        return upsert_model_connection(db, payload)

    @router.put("/api/model-connections/{connection_id}")
    def update_model_connection(connection_id: str, payload: ModelConnectionPayload) -> dict[str, Any]:
        if not model_connection_row(db, connection_id):
            raise HTTPException(404, "模型连接不存在")
        return upsert_model_connection(db, payload, connection_id)

    @router.delete("/api/model-connections/{connection_id}")
    def delete_model_connection(connection_id: str) -> dict[str, Any]:
        row = model_connection_row(db, connection_id)
        if not row:
            raise HTTPException(404, "模型连接不存在")
        delete_provider_key(scoped_provider_key_name("model_connection", connection_id))
        db.execute("UPDATE avatar_model_settings SET connection_id='', mode='inherit', updated_at=? WHERE connection_id=?", (int(time.time()), connection_id))
        db.execute("DELETE FROM model_connections WHERE id=?", (connection_id,))
        if selected_model_connection_id(db) == connection_id:
            next_row = db.one("SELECT id FROM model_connections ORDER BY updated_at DESC LIMIT 1")
            db.set_setting("selected_model_connection_id", str(next_row["id"]) if next_row else "")
        return {"deleted": True, "selected_connection_id": selected_model_connection_id(db)}

    @router.post("/api/model-connections/{connection_id}/select")
    def select_model_connection(connection_id: str) -> dict[str, Any]:
        row = model_connection_row(db, connection_id)
        if not row:
            raise HTTPException(404, "模型连接不存在")
        db.set_setting("selected_model_connection_id", connection_id)
        return {"selected_connection_id": connection_id, "connection": public_model_connection(row)}

    @router.post("/api/model-connections/test")
    def test_model_connection(payload: ModelConnectionTestPayload) -> dict[str, Any]:
        try:
            checked = validate_model_connection_payload(payload, payload.connection_id)
            client = build_provider(checked["config"])
            available = bool(client.probe()) if hasattr(client, "probe") else bool(client.available())
            message = "连接测试成功，模型服务可以访问。" if available else "模型服务当前不可访问。"
            tested_at = int(time.time())
            if payload.connection_id:
                db.execute(
                    "UPDATE model_connections SET last_test_status=?,last_test_message=?,last_tested_at=?,updated_at=? WHERE id=?",
                    ("ok" if available else "failed", message, tested_at, tested_at, payload.connection_id),
                )
            return {"ok": bool(available), "message": message, "tested_at": tested_at}
        except (ProviderError, LocalModelError) as exc:
            tested_at = int(time.time())
            if payload.connection_id:
                db.execute(
                    "UPDATE model_connections SET last_test_status=?,last_test_message=?,last_tested_at=?,updated_at=? WHERE id=?",
                    ("failed", str(exc), tested_at, tested_at, payload.connection_id),
                )
            return {"ok": False, "message": str(exc), "tested_at": tested_at}

    @router.get("/api/ocr-connections")
    def get_ocr_connections() -> dict[str, Any]:
        rows = db.all("SELECT * FROM ocr_connections ORDER BY updated_at DESC")
        selected_ocr = str(db.setting("selected_ocr_connection_id", "") or "")
        return {
            "selected_ocr_connection_id": selected_ocr,
            "detected": detect_local_ocr(),
            "connections": [public_ocr_connection(row) for row in rows],
            "presets": [
                {"connection_type": "local_command", "label": "本地命令 OCR", "command_template": "tesseract {image} stdout -l chi_sim+eng", "data_location": "local"},
                {"connection_type": "local_http", "label": "本地 HTTP OCR", "base_url": "http://127.0.0.1:8866/ocr", "data_location": "local"},
                {"connection_type": "cloud_api", "label": "云端 OCR API", "base_url": "https://api.example.com/ocr", "data_location": "cloud"},
            ],
        }

    @router.post("/api/ocr-connections", status_code=201)
    def create_ocr_connection(payload: OcrConnectionPayload) -> dict[str, Any]:
        try:
            return upsert_ocr_connection(db, payload.model_dump())
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.put("/api/ocr-connections/{connection_id}")
    def update_ocr_connection(connection_id: str, payload: OcrConnectionPayload) -> dict[str, Any]:
        if not db.one("SELECT * FROM ocr_connections WHERE id=?", (connection_id,)):
            raise HTTPException(404, "OCR 连接不存在")
        try:
            return upsert_ocr_connection(db, payload.model_dump(), connection_id)
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.delete("/api/ocr-connections/{connection_id}")
    def delete_ocr_connection(connection_id: str) -> dict[str, Any]:
        if not db.one("SELECT * FROM ocr_connections WHERE id=?", (connection_id,)):
            raise HTTPException(404, "OCR 连接不存在")
        delete_provider_key(ocr_provider_key(connection_id))
        db.execute("DELETE FROM ocr_connections WHERE id=?", (connection_id,))
        if str(db.setting("selected_ocr_connection_id", "") or "") == connection_id:
            next_row = db.one("SELECT id FROM ocr_connections WHERE enabled=1 ORDER BY updated_at DESC LIMIT 1")
            db.set_setting("selected_ocr_connection_id", str(next_row["id"]) if next_row else "")
        return {"deleted": True, "selected_ocr_connection_id": str(db.setting("selected_ocr_connection_id", "") or "")}

    @router.post("/api/ocr-connections/{connection_id}/select")
    def select_ocr_connection(connection_id: str) -> dict[str, Any]:
        row = db.one("SELECT * FROM ocr_connections WHERE id=?", (connection_id,))
        if not row:
            raise HTTPException(404, "OCR 连接不存在")
        db.set_setting("selected_ocr_connection_id", connection_id)
        return {"selected_ocr_connection_id": connection_id, "connection": public_ocr_connection(row)}

    @router.post("/api/ocr-connections/test")
    def test_ocr_connection(payload: OcrConnectionTestPayload) -> dict[str, Any]:
        try:
            validate_ocr_payload(payload.model_dump(), payload.connection_id)
            message = "OCR 配置格式正确。上传截图时会按这个连接处理。"
            if payload.connection_id:
                db.execute("UPDATE ocr_connections SET last_test_status=?,last_test_message=?,updated_at=? WHERE id=?", ("ok", message, int(time.time()), payload.connection_id))
            return {"ok": True, "message": message}
        except (ProviderError, LocalModelError) as exc:
            if payload.connection_id:
                db.execute("UPDATE ocr_connections SET last_test_status=?,last_test_message=?,updated_at=? WHERE id=?", ("failed", str(exc), int(time.time()), payload.connection_id))
            return {"ok": False, "message": str(exc)}

    @router.get("/api/capabilities")
    def capabilities() -> dict[str, Any]:
        model_config = provider_config(db, selected)
        return capability_report(db, model_config, model_client(db, selected))

    @router.get("/api/settings/cloud-services")
    def get_cloud_service_settings() -> dict[str, Any]:
        current = db.setting("cloud_services", {})
        north_settings = video_call_settings(db)
        return {
            "provider": "aliyun",
            "has_aliyun_api_key": bool(load_provider_key("aliyun")),
            "video_call_provider": "north",
            "has_north_api_key": bool(load_provider_key("north")),
            "voice_clone_model": str(current.get("voice_clone_model", "qwen-voice-enrollment")),
            "voice_target_model": str(current.get("voice_target_model", "qwen3-tts-vc-2026-01-22")),
            "voice_tts_model": str(current.get("voice_tts_model", "qwen3-tts-vc-2026-01-22")),
            "image_reference_model": str(current.get("image_reference_model", "qwen-image-2.0-pro")),
            "video_model": str(current.get("video_model", "wan2.7-i2v-2026-04-25")),
            "north_api_url": north_settings["north_api_url"],
            "north_face_url": north_settings["north_face_url"],
            "north_idle_timeout": north_settings["north_idle_timeout"],
            "north_price_per_second": north_settings["north_price_per_second"],
            "video_call_enabled": north_settings["video_call_enabled"],
            "scene_background_enabled": north_settings["scene_background_enabled"],
            "camera_flip_enabled": north_settings["camera_flip_enabled"],
            "vision_feedback_enabled": north_settings["vision_feedback_enabled"],
            "smart_interrupt_enabled": north_settings["smart_interrupt_enabled"],
            "cloud_data_consent": bool(current.get("cloud_data_consent", False)),
        }

    @router.put("/api/settings/cloud-services")
    def set_cloud_service_settings(payload: CloudServiceSettings) -> dict[str, Any]:
        if not payload.cloud_data_consent:
            raise HTTPException(400, "请先确认：声音和参考照会发送给选定的云端服务商")
        try:
            if payload.clear_aliyun_api_key:
                delete_provider_key("aliyun")
            if payload.aliyun_api_key.strip():
                store_provider_key("aliyun", payload.aliyun_api_key.strip())
            if payload.clear_north_api_key:
                delete_provider_key("north")
            if payload.north_api_key.strip():
                store_provider_key("north", payload.north_api_key.strip())
            if not load_provider_key("aliyun") and not load_provider_key("north"):
                raise ProviderError("请至少填写阿里云百炼 API Key 或 North/Atlas API Key")
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc
        db.set_setting("cloud_services", payload.model_dump(exclude={"aliyun_api_key", "clear_aliyun_api_key", "north_api_key", "clear_north_api_key"}))
        return {"saved": True, "provider": "aliyun+north", "has_aliyun_api_key": bool(load_provider_key("aliyun")), "has_north_api_key": bool(load_provider_key("north"))}

    @router.get("/api/settings/model-routes")
    def get_model_routes() -> list[dict[str, Any]]:
        return list_routes(db)

    @router.put("/api/settings/model-routes/{role}")
    def set_model_route(role: str, payload: ModelRouteUpdate) -> dict[str, Any]:
        try:
            values = payload.model_dump()
            values["role"] = role
            return update_route(db, values)
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/voice/development-voices")
    def development_voices() -> list[dict[str, Any]]:
        return list_development_voices()

    @router.get("/api/templates/character")
    def character_templates() -> dict[str, str]:
        return template_payload()

    return router
