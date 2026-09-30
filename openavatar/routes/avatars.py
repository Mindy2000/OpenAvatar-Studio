from __future__ import annotations

from openavatar.routes._shared import *


def create_avatars_router(context: ApplicationContext) -> APIRouter:
    router = APIRouter()
    db = context.db
    selected = context.settings
    runs = context.runs
    chat_service = context.chat

    @router.get("/api/avatars/{avatar_id}/guided-builder")
    def get_guided_builder(avatar_id: str) -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        if str(avatar["subject_kind"]) != "fictional":
            raise HTTPException(400, "问答式 Builder 当前用于虚构数字人")
        return guided_state(db, avatar_id)

    @router.post("/api/avatars/{avatar_id}/guided-builder/answers")
    def answer_guided_builder(avatar_id: str, payload: GuidedBuilderAnswer) -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        if str(avatar["subject_kind"]) != "fictional":
            raise HTTPException(400, "问答式 Builder 当前用于虚构数字人")
        try:
            return record_answer(db, avatar_id, payload.question_key, payload.answer)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.patch("/api/avatars/{avatar_id}/guided-builder/modules/{module_key}")
    def update_guided_module(avatar_id: str, module_key: str, payload: WorldModuleUpdate) -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        if str(avatar["subject_kind"]) != "fictional":
            raise HTTPException(400, "世界模块当前用于虚构数字人")
        try:
            return update_module(db, avatar_id, module_key, payload.enabled)
        except KeyError as exc:
            raise HTTPException(404, str(exc)) from exc
        except ValueError as exc:
            raise HTTPException(400, str(exc)) from exc

    @router.get("/api/avatars")
    def list_avatars() -> list[dict[str, Any]]:
        return [public_avatar(row) for row in db.all("SELECT * FROM avatars ORDER BY updated_at DESC")]

    @router.post("/api/avatars", status_code=201)
    def create_avatar(payload: AvatarCreate) -> dict[str, Any]:
        if payload.subject_kind == "authorized_person" and not payload.consent_confirmed:
            raise HTTPException(400, "创建他人的数字人必须确认已获得明确授权")
        avatar_id = uuid.uuid4().hex[:12]
        now = int(time.time())
        db.execute(
            "INSERT INTO avatars(id,name,purpose,relationship,subject_kind,adult_subject,consent_confirmed,avatar_primary_language,avatar_secondary_languages,avatar_response_mode,world_region,world_type,world_region_custom_json,created_at,updated_at) "
            "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (
                avatar_id, payload.name.strip(), payload.purpose.strip(), payload.relationship.strip(),
                payload.subject_kind, int(payload.adult_subject), int(payload.consent_confirmed),
                payload.avatar_primary_language,
                json.dumps(payload.avatar_secondary_languages, ensure_ascii=False),
                payload.avatar_response_mode,
                payload.world_region,
                payload.world_type,
                json.dumps(payload.world_region_custom, ensure_ascii=False),
                now, now,
            ),
        )
        db.execute("INSERT INTO persona_profiles(avatar_id,updated_at) VALUES(?,?)", (avatar_id, now))
        db.execute(
            "INSERT INTO rights_grants(avatar_id,grant_type,subject_kind,rights_scope,data_classes_json,provider_transfer_allowed,commercial_use_allowed,revocable,note,confirmed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
            (
                avatar_id,
                "creation_attestation",
                payload.subject_kind,
                "local_avatar_build",
                json.dumps(["conversation", "image", "audio", "fictional_source"], ensure_ascii=False),
                0,
                0,
                1,
                "创建时用户确认拥有资料使用权；云端传输和付费服务仍需单独确认。",
                now,
            ),
        )
        (selected.avatars_dir / avatar_id / "imports").mkdir(parents=True, exist_ok=True)
        return public_avatar(require_avatar(db, avatar_id))

    @router.get("/api/avatars/{avatar_id}")
    def get_avatar(avatar_id: str) -> dict[str, Any]:
        avatar = public_avatar(require_avatar(db, avatar_id))
        avatar["persona"] = context.chat.get_persona(avatar_id)
        avatar["imports"] = db.all(
            "SELECT id,category,original_name,media_type,size_bytes,status,note,created_at FROM imports WHERE avatar_id=? ORDER BY id DESC",
            (avatar_id,),
        )
        avatar["evidence_count"] = int(
            (db.one("SELECT COUNT(*) AS count FROM evidence WHERE avatar_id=?", (avatar_id,)) or {"count": 0})["count"]
        )
        avatar["world_fact_count"] = int(
            (db.one("SELECT COUNT(*) AS count FROM world_facts WHERE avatar_id=? AND active=1", (avatar_id,)) or {"count": 0})["count"]
        )
        avatar["readiness"] = completion_report(db, avatar_id)
        return avatar

    @router.get("/api/avatars/{avatar_id}/settings/model")
    def get_avatar_model_settings(avatar_id: str) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        own = db.one("SELECT * FROM avatar_model_settings WHERE avatar_id=?", (avatar_id,))
        effective = provider_config(db, selected, avatar_id)
        scoped_key = scoped_provider_key_name("chat", avatar_id)
        return {
            "mode": str(own.get("mode", "inherit")) if own else "inherit",
            "connection_id": str(own.get("connection_id", "")) if own else "",
            "provider_name": str(own.get("provider_name", "")) if own else "",
            "ollama_url": str(own.get("ollama_url", "")) if own else "",
            "ollama_model": str(own.get("ollama_model", "")) if own else "",
            "base_url": str(own.get("base_url", "")) if own else "",
            "model": str(own.get("model", "")) if own else "",
            "cloud_data_consent": bool(own.get("cloud_data_consent", False)) if own else False,
            "has_api_key": bool(load_provider_key(scoped_key)),
            "effective": {
                "mode": effective.mode,
                "provider_name": effective.provider_name,
                "base_url": effective.base_url,
                "model": effective.model,
                "cloud_data_consent": effective.cloud_data_consent,
                "inherited": own is None or str(own.get("mode")) == "inherit",
            },
        }

    @router.put("/api/avatars/{avatar_id}/settings/model")
    def set_avatar_model_settings(avatar_id: str, payload: AvatarModelSettings) -> dict[str, Any]:
        require_avatar(db, avatar_id)
        scoped_key = scoped_provider_key_name("chat", avatar_id)
        try:
            if payload.mode == "inherit":
                delete_provider_key(scoped_key)
                db.execute("DELETE FROM avatar_model_settings WHERE avatar_id=?", (avatar_id,))
                return get_avatar_model_settings(avatar_id)
            connection_id = payload.connection_id.strip()
            connection_row = model_connection_row(db, connection_id) if connection_id else None
            if connection_id and not connection_row:
                raise ProviderError("选择的模型连接不存在")
            if connection_row:
                connection_provider_config(connection_row)
            elif payload.mode == "cloud":
                if not payload.cloud_data_consent:
                    raise ProviderError("请先确认：该数字人的云端模型会接收完成任务所需的资料片段")
                normalize_openai_base_url(payload.base_url)
                if payload.clear_api_key:
                    delete_provider_key(scoped_key)
                if payload.api_key.strip():
                    store_provider_key(scoped_key, payload.api_key.strip())
                if not load_provider_key(scoped_key):
                    raise ProviderError("每个数字人的云端模式需要填写该数字人自己的 API Key")
            now = int(time.time())
            db.execute(
                """
                INSERT INTO avatar_model_settings
                (avatar_id,mode,connection_id,provider_name,base_url,model,ollama_url,ollama_model,cloud_data_consent,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(avatar_id) DO UPDATE SET
                  mode=excluded.mode,
                  connection_id=excluded.connection_id,
                  provider_name=excluded.provider_name,
                  base_url=excluded.base_url,
                  model=excluded.model,
                  ollama_url=excluded.ollama_url,
                  ollama_model=excluded.ollama_model,
                  cloud_data_consent=excluded.cloud_data_consent,
                  updated_at=excluded.updated_at
                """,
                (
                    avatar_id,
                    payload.mode,
                    connection_id,
                    payload.provider_name.strip(),
                    payload.base_url.strip(),
                    payload.model.strip(),
                    payload.ollama_url.strip(),
                    payload.ollama_model.strip(),
                    int(payload.cloud_data_consent),
                    now,
                ),
            )
        except ProviderError as exc:
            raise HTTPException(400, str(exc)) from exc
        return get_avatar_model_settings(avatar_id)

    @router.patch("/api/avatars/{avatar_id}")
    def update_avatar(avatar_id: str, payload: AvatarUpdate) -> dict[str, Any]:
        avatar = require_avatar(db, avatar_id)
        values = payload.model_dump(exclude_none=True)
        if values.get("proactive_enabled") and not bool(avatar["consent_confirmed"]):
            raise HTTPException(400, "启用主动联系前必须完成身份和数据授权确认")
        allowed = {
            "name", "purpose", "relationship", "consent_confirmed", "proactive_enabled", "proactive_interval_minutes",
            "avatar_primary_language", "avatar_secondary_languages", "avatar_response_mode", "world_region", "world_type", "world_region_custom",
        }
        if values:
            fields = []
            params: list[Any] = []
            for key, value in values.items():
                if key not in allowed:
                    continue
                column = "world_region_custom_json" if key == "world_region_custom" else key
                fields.append(f"{column}=?")
                if key in {"avatar_secondary_languages", "world_region_custom"}:
                    params.append(json.dumps(value, ensure_ascii=False))
                else:
                    params.append(int(value) if isinstance(value, bool) else value)
            fields.append("updated_at=?")
            params.extend([int(time.time()), avatar_id])
            db.execute(f"UPDATE avatars SET {', '.join(fields)} WHERE id=?", tuple(params))
        return public_avatar(require_avatar(db, avatar_id))

    return router

