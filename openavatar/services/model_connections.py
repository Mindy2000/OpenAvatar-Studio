from __future__ import annotations

import time
import uuid
from collections.abc import Iterator
from typing import Any
from fastapi import HTTPException
from openavatar.config import Settings
from openavatar.db import Database
from openavatar.local_model import LocalModelError, validate_local_url
from openavatar.providers import ChatProvider, ProviderConfig, ProviderError, build_provider, delete_provider_key, load_api_key, load_provider_key, normalize_openai_base_url, scoped_provider_key_name, store_provider_key
from openavatar.schemas import ModelConnectionPayload


class FailoverChatProvider:
    def __init__(self, providers: list[ChatProvider]):
        self.providers = providers
        self.model = providers[0].model

    def available(self) -> bool:
        return any(provider.available() for provider in self.providers)

    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
        errors = []
        for provider in self.providers:
            try:
                return provider.chat(messages, json_mode=json_mode)
            except (ProviderError, LocalModelError, OSError) as exc:
                errors.append(str(exc))
        raise ProviderError("所有聊天服务均不可用：" + "；".join(errors))

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        errors = []
        for provider in self.providers:
            try:
                yielded = False
                for chunk in provider.stream_chat(messages):
                    yielded = True
                    yield chunk
                return
            except (ProviderError, LocalModelError, OSError) as exc:
                if yielded:
                    raise
                errors.append(str(exc))
        raise ProviderError("所有聊天服务均不可用：" + "；".join(errors))


class MeteredChatProvider:
    def __init__(self, provider: ChatProvider, db: Database, avatar_id: str, row: dict[str, Any]):
        self.provider = provider
        self.db = db
        self.avatar_id = avatar_id
        self.row = row
        self.model = provider.model

    def available(self) -> bool:
        return self.provider.available()

    def _input_size(self, messages: list[dict[str, str]]) -> int:
        return sum(len(str(item.get("content", ""))) for item in messages)

    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
        from openavatar.services.provider_hub import estimate_provider_cost, record_provider_usage

        started = time.perf_counter()
        try:
            result = self.provider.chat(messages, json_mode=json_mode)
            cost = estimate_provider_cost(self.row, "chat", input_units=self._input_size(messages), output_units=len(result))
            record_provider_usage(self.db, self.avatar_id, str(self.row["id"]), self.model, "chat", "ok", latency_ms=(time.perf_counter() - started) * 1000, estimated_cost=cost)
            return result
        except Exception as exc:
            record_provider_usage(self.db, self.avatar_id, str(self.row["id"]), self.model, "chat", "failed", latency_ms=(time.perf_counter() - started) * 1000, metadata={"error": str(exc)[:500]})
            raise

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        from openavatar.services.provider_hub import estimate_provider_cost, record_provider_usage

        started = time.perf_counter()
        output_size = 0
        try:
            for chunk in self.provider.stream_chat(messages):
                output_size += len(chunk)
                yield chunk
            cost = estimate_provider_cost(self.row, "chat", input_units=self._input_size(messages), output_units=output_size)
            record_provider_usage(self.db, self.avatar_id, str(self.row["id"]), self.model, "chat", "ok", latency_ms=(time.perf_counter() - started) * 1000, estimated_cost=cost)
        except Exception as exc:
            record_provider_usage(self.db, self.avatar_id, str(self.row["id"]), self.model, "chat", "failed", latency_ms=(time.perf_counter() - started) * 1000, metadata={"error": str(exc)[:500]})
            raise

def avatar_model_setting(db: Database, avatar_id: str) -> dict[str, Any] | None:
    row = db.one("SELECT * FROM avatar_model_settings WHERE avatar_id=?", (avatar_id,))
    return row if row and str(row.get("mode")) != "inherit" else None


def public_model_connection(row: dict[str, Any]) -> dict[str, Any]:
    key_name = scoped_provider_key_name("model_connection", str(row["id"]))
    return {
        "id": row["id"],
        "display_name": row["display_name"],
        "connection_type": row["connection_type"],
        "provider_name": row["provider_name"],
        "base_url": row["base_url"],
        "model": row["model"],
        "adapter_kind": row["adapter_kind"],
        "cloud_data_consent": bool(row.get("cloud_data_consent", False)),
        "local_only": bool(row.get("local_only", False)),
        "has_api_key": bool(load_provider_key(key_name)),
        "last_test_status": row.get("last_test_status", "untested"),
        "last_test_message": row.get("last_test_message", ""),
        "last_tested_at": row.get("last_tested_at", 0),
        "updated_at": row.get("updated_at", 0),
    }


def selected_model_connection_id(db: Database) -> str:
    value = db.setting("selected_model_connection_id", "")
    return str(value or "")


def model_connection_row(db: Database, connection_id: str) -> dict[str, Any] | None:
    if not connection_id:
        return None
    return db.one("SELECT * FROM model_connections WHERE id=?", (connection_id,))


def connection_provider_config(row: dict[str, Any], *, api_key: str = "") -> ProviderConfig:
    connection_type = str(row.get("connection_type", "cloud_openai"))
    base_url = str(row.get("base_url", "")).strip()
    model = str(row.get("model", "")).strip()
    if not base_url:
        raise ProviderError("请填写 API 地址")
    if not model:
        raise ProviderError("请填写模型名称")
    if connection_type == "cloud_openai":
        normalize_openai_base_url(base_url)
        if not bool(row.get("cloud_data_consent", False)):
            raise ProviderError("使用云端模型前必须确认数据传输范围")
        return ProviderConfig(
            mode="cloud_openai",
            provider_name=str(row.get("provider_name", "自定义 API") or "自定义 API"),
            base_url=base_url,
            model=model,
            api_key=api_key or load_provider_key(scoped_provider_key_name("model_connection", str(row["id"]))),
            cloud_data_consent=True,
        )
    if connection_type == "ollama":
        validate_local_url(base_url)
        return ProviderConfig(mode="ollama", provider_name="Ollama", base_url=base_url, model=model)
    if connection_type == "local_openai":
        validate_local_url(base_url)
        normalize_openai_base_url(base_url)
        return ProviderConfig(
            mode="local_openai",
            provider_name=str(row.get("provider_name", "本地 OpenAI 兼容服务") or "本地 OpenAI 兼容服务"),
            base_url=base_url,
            model=model,
            api_key=api_key or load_provider_key(scoped_provider_key_name("model_connection", str(row["id"]))),
        )
    if connection_type == "custom_local_adapter":
        validate_local_url(base_url)
        adapter_kind = str(row.get("adapter_kind", "openai_compatible") or "openai_compatible")
        if adapter_kind == "openai_compatible":
            normalize_openai_base_url(base_url)
        return ProviderConfig(
            mode="custom_local_adapter",
            provider_name=str(row.get("provider_name", "自定义本地适配器") or "自定义本地适配器"),
            base_url=base_url,
            model=model,
            api_key=api_key or load_provider_key(scoped_provider_key_name("model_connection", str(row["id"]))),
            adapter_kind=adapter_kind,
        )
    raise ProviderError("不支持的模型连接类型")


def validate_model_connection_payload(payload: ModelConnectionPayload, connection_id: str = "") -> dict[str, Any]:
    row = {
        "id": connection_id or "preview",
        "display_name": payload.display_name.strip(),
        "connection_type": payload.connection_type,
        "provider_name": payload.provider_name.strip() or payload.display_name.strip(),
        "base_url": payload.base_url.strip().rstrip("/"),
        "model": payload.model.strip(),
        "adapter_kind": payload.adapter_kind,
        "cloud_data_consent": int(payload.cloud_data_consent),
        "local_only": int(payload.connection_type in {"local_openai", "ollama", "custom_local_adapter"}),
    }
    config = connection_provider_config(row, api_key=payload.api_key.strip())
    if payload.connection_type == "cloud_openai" and not payload.api_key.strip() and not connection_id:
        raise ProviderError("云端连接需要填写 API Key，保存后只进入系统安全凭据库")
    return {"row": row, "config": config}


def upsert_model_connection(db: Database, payload: ModelConnectionPayload, connection_id: str = "") -> dict[str, Any]:
    try:
        existing = model_connection_row(db, connection_id) if connection_id else None
        checked = validate_model_connection_payload(payload, connection_id or (existing or {}).get("id", ""))
        row = checked["row"]
        if existing:
            row["id"] = existing["id"]
        else:
            row["id"] = f"mc_{uuid.uuid4().hex[:12]}"
        key_name = scoped_provider_key_name("model_connection", row["id"])
        if payload.clear_api_key:
            delete_provider_key(key_name)
        if payload.api_key.strip():
            store_provider_key(key_name, payload.api_key.strip())
        if payload.connection_type == "cloud_openai" and not load_provider_key(key_name):
            raise ProviderError("云端连接需要填写 API Key")
        now = int(time.time())
        db.execute(
            """
            INSERT INTO model_connections
            (id,display_name,connection_type,provider_name,base_url,model,adapter_kind,cloud_data_consent,local_only,last_test_status,last_test_message,last_tested_at,created_at,updated_at)
            VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(id) DO UPDATE SET
              display_name=excluded.display_name,
              connection_type=excluded.connection_type,
              provider_name=excluded.provider_name,
              base_url=excluded.base_url,
              model=excluded.model,
              adapter_kind=excluded.adapter_kind,
              cloud_data_consent=excluded.cloud_data_consent,
              local_only=excluded.local_only,
              last_test_status=excluded.last_test_status,
              last_test_message=excluded.last_test_message,
              last_tested_at=excluded.last_tested_at,
              updated_at=excluded.updated_at
            """,
            (
                row["id"],
                row["display_name"],
                row["connection_type"],
                row["provider_name"],
                row["base_url"],
                row["model"],
                row["adapter_kind"],
                row["cloud_data_consent"],
                row["local_only"],
                "saved",
                "配置已保存。可以在正式使用前测试连接。",
                0,
                existing["created_at"] if existing else now,
                now,
            ),
        )
        if not selected_model_connection_id(db):
            db.set_setting("selected_model_connection_id", row["id"])
        saved = model_connection_row(db, row["id"])
        return public_model_connection(saved) if saved else row
    except (ProviderError, LocalModelError) as exc:
        raise HTTPException(400, str(exc)) from exc


def legacy_provider_config(db: Database, settings: Settings, avatar_id: str = "") -> ProviderConfig:
    avatar_config = avatar_model_setting(db, avatar_id) if avatar_id else None
    if avatar_config:
        mode = str(avatar_config.get("mode", "local"))
        if mode == "cloud":
            provider_name = str(avatar_config.get("provider_name", "custom-api") or "custom-api")
            return ProviderConfig(
                mode="cloud_openai",
                provider_name=provider_name,
                base_url=str(avatar_config.get("base_url", "")),
                model=str(avatar_config.get("model", "")),
                cloud_data_consent=bool(avatar_config.get("cloud_data_consent", False)),
                api_key=load_provider_key(scoped_provider_key_name("chat", avatar_id)),
            )
        return ProviderConfig(
            mode="ollama",
            provider_name="Ollama",
            base_url=str(avatar_config.get("ollama_url") or settings.ollama_url),
            model=str(avatar_config.get("ollama_model") or settings.ollama_model),
        )
    configured = db.setting("model", {})
    mode = str(configured.get("mode", "local"))
    if mode == "cloud":
        return ProviderConfig(
            mode="cloud_openai",
            provider_name=str(configured.get("provider_name", "openrouter")),
            base_url=str(configured.get("base_url", "https://openrouter.ai/api/v1")),
            model=str(configured.get("model", "openrouter/auto")),
            cloud_data_consent=bool(configured.get("cloud_data_consent", False)),
        )
    return ProviderConfig(
        mode="ollama",
        provider_name="Ollama",
        base_url=str(configured.get("ollama_url", settings.ollama_url)),
        model=str(configured.get("ollama_model", settings.ollama_model)),
    )


def provider_config(db: Database, settings: Settings, avatar_id: str = "") -> ProviderConfig:
    from openavatar.services.provider_hub import find_route, routed_chat_config

    routed = routed_chat_config(db, avatar_id)
    if routed:
        return routed
    if find_route(db, "chat", avatar_id):
        raise ProviderError("聊天能力路由已配置，但连接被停用、未授权或已超过预算")
    avatar_config = avatar_model_setting(db, avatar_id) if avatar_id else None
    if avatar_config and str(avatar_config.get("connection_id", "")):
        row = model_connection_row(db, str(avatar_config["connection_id"]))
        if row:
            return connection_provider_config(row)
    selected_id = selected_model_connection_id(db)
    if selected_id:
        row = model_connection_row(db, selected_id)
        if row:
            return connection_provider_config(row)
    return legacy_provider_config(db, settings, avatar_id)


def public_runtime_mode(mode: str) -> str:
    return "cloud" if mode in {"cloud", "cloud_openai"} else "local"


def unavailable_model_message(config: ProviderConfig) -> str:
    if config.mode in {"cloud", "cloud_openai"}:
        return f"{config.provider_name} 连接当前不可用。请检查 API Key、API 地址、模型名称和网络状态。"
    if config.mode == "ollama":
        return f"Ollama 连接当前不可用。请确认 {config.base_url} 正在运行，并已准备模型 {config.model}。"
    return f"{config.provider_name} 本地连接当前不可用。请确认 {config.base_url} 正在运行，并支持模型 {config.model}。"


def model_client(db: Database, settings: Settings, avatar_id: str = "") -> ChatProvider:
    try:
        from openavatar.services.provider_hub import find_route, routed_chat_entries

        routed = routed_chat_entries(db, avatar_id)
        if routed:
            providers = [MeteredChatProvider(build_provider(config), db, avatar_id, row) for config, row in routed]
            return providers[0] if len(providers) == 1 else FailoverChatProvider(providers)
        if find_route(db, "chat", avatar_id):
            raise ProviderError("聊天能力路由已配置，但连接被停用、未授权或已超过预算")
        return build_provider(provider_config(db, settings, avatar_id))
    except (LocalModelError, ProviderError) as exc:
        raise HTTPException(400, str(exc)) from exc
