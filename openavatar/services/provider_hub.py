from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
import uuid
from datetime import datetime
from typing import Any

from openavatar.db import Database
from openavatar.local_model import LocalModelError, local_urlopen, validate_local_url
from openavatar.providers import (
    ProviderConfig,
    ProviderError,
    delete_provider_key,
    load_provider_key,
    normalize_openai_base_url,
    scoped_provider_key_name,
    store_provider_key,
    verified_ssl_context,
)
from openavatar.schemas import CapabilityRoutePayload, ProviderConnectionPayload


CAPABILITIES = ("chat", "vision", "asr", "tts", "voice_clone", "image", "video", "realtime_video")
CONSENT_CLASS = {
    "chat": "text", "vision": "image", "asr": "audio", "tts": "text",
    "voice_clone": "voice_biometric", "image": "image", "video": "video", "realtime_video": "video",
}
PROVIDER_PRESETS: dict[str, dict[str, Any]] = {
    "minimax": {
        "label": "MiniMax（直连）", "base_url": "https://api.minimax.io/v1",
        "capabilities": ["chat", "vision", "asr", "tts", "voice_clone", "image", "video"],
        "models": {"chat": "MiniMax-M2.7", "asr": "asr-1.0", "tts": "speech-2.8-hd", "voice_clone": "speech-2.8-hd", "image": "image-01", "video": "MiniMax-H3"},
    },
    "aliyun": {
        "label": "阿里云百炼（直连）", "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "capabilities": ["chat", "vision", "tts", "voice_clone", "image", "video"],
        "models": {"chat": "qwen-plus", "vision": "qwen-vl-plus", "tts": "qwen3-tts-vc-2026-01-22", "image": "qwen-image-2.0-pro", "video": "wan2.7-i2v-2026-04-25"},
    },
    "openrouter": {
        "label": "OpenRouter", "base_url": "https://openrouter.ai/api/v1",
        "capabilities": ["chat", "vision", "video"], "models": {"chat": "openrouter/auto", "video": "google/veo-3.1-fast"},
    },
    "openai_compatible": {
        "label": "OpenAI 兼容 API", "base_url": "https://api.example.com/v1",
        "capabilities": ["chat", "vision"], "models": {},
    },
    "local": {
        "label": "本地 OpenAI 兼容服务", "base_url": "http://127.0.0.1:1234/v1",
        "capabilities": ["chat", "vision", "asr", "tts", "image"], "models": {},
    },
    "north": {
        "label": "North/Atlas", "base_url": "https://api.atlasv1.com",
        "capabilities": ["realtime_video"], "models": {},
    },
}


def _loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(value or "")
    except (TypeError, json.JSONDecodeError):
        return fallback


def provider_key_name(connection_id: str) -> str:
    return scoped_provider_key_name("provider_connection", connection_id)


def public_connection(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for source, target, fallback in (
        ("capabilities_json", "capabilities", []), ("models_json", "models", {}),
        ("config_json", "config", {}), ("consent_json", "consent", {}), ("budget_json", "budget", {}),
    ):
        result[target] = _loads(result.pop(source, None), fallback)
    result["enabled"] = bool(result.get("enabled"))
    result["has_api_key"] = bool(load_provider_key(provider_key_name(str(row["id"]))))
    return result


def connection_row(db: Database, connection_id: str) -> dict[str, Any] | None:
    return db.one("SELECT * FROM provider_connections WHERE id=?", (connection_id,))


def _validate_local_connection(base_url: str) -> None:
    try:
        validate_local_url(base_url)
    except LocalModelError as exc:
        raise ProviderError(str(exc)) from exc


def _validate_connection(payload: ProviderConnectionPayload) -> str:
    base_url = payload.base_url.strip().rstrip("/") or str(PROVIDER_PRESETS[payload.provider_kind]["base_url"])
    if payload.provider_kind != "local":
        normalize_openai_base_url(base_url)
    else:
        _validate_local_connection(base_url)
    invalid = set(payload.capabilities) - set(CAPABILITIES)
    if invalid:
        raise ProviderError(f"不支持的能力：{', '.join(sorted(invalid))}")
    return base_url


def upsert_connection(db: Database, payload: ProviderConnectionPayload, connection_id: str = "") -> dict[str, Any]:
    base_url = _validate_connection(payload)
    existing = connection_row(db, connection_id) if connection_id else None
    connection_id = str(existing["id"]) if existing else f"pc_{uuid.uuid4().hex[:12]}"
    key_name = provider_key_name(connection_id)
    if payload.clear_api_key:
        delete_provider_key(key_name)
    if payload.api_key.strip():
        store_provider_key(key_name, payload.api_key.strip())
    if payload.provider_kind != "local" and not load_provider_key(key_name):
        raise ProviderError("云端服务需要填写 API Key；Key 只保存在系统安全凭据库")
    now = int(time.time())
    db.execute(
        """INSERT INTO provider_connections
        (id,display_name,provider_kind,base_url,region,capabilities_json,models_json,config_json,consent_json,budget_json,enabled,last_test_status,last_test_message,last_tested_at,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(id) DO UPDATE SET display_name=excluded.display_name,provider_kind=excluded.provider_kind,
        base_url=excluded.base_url,region=excluded.region,capabilities_json=excluded.capabilities_json,
        models_json=excluded.models_json,config_json=excluded.config_json,consent_json=excluded.consent_json,
        budget_json=excluded.budget_json,enabled=excluded.enabled,updated_at=excluded.updated_at""",
        (connection_id, payload.display_name.strip(), payload.provider_kind, base_url, payload.region.strip(),
         json.dumps(payload.capabilities), json.dumps(payload.models), json.dumps(payload.config),
         json.dumps(payload.consent), json.dumps(payload.budget), int(payload.enabled),
         existing.get("last_test_status", "saved") if existing else "saved",
         existing.get("last_test_message", "配置已保存") if existing else "配置已保存",
         existing.get("last_tested_at", 0) if existing else 0, existing.get("created_at", now) if existing else now, now),
    )
    return public_connection(connection_row(db, connection_id) or {"id": connection_id})


def delete_connection(db: Database, connection_id: str) -> None:
    if not connection_row(db, connection_id):
        raise ProviderError("服务连接不存在")
    delete_provider_key(provider_key_name(connection_id))
    db.execute("DELETE FROM capability_routes WHERE primary_connection_id=?", (connection_id,))
    for route in db.all("SELECT * FROM capability_routes"):
        fallbacks = [item for item in _loads(route.get("fallback_connection_ids_json"), []) if item != connection_id]
        db.execute("UPDATE capability_routes SET fallback_connection_ids_json=?,updated_at=? WHERE id=?", (json.dumps(fallbacks), int(time.time()), route["id"]))
    db.execute("DELETE FROM provider_connections WHERE id=?", (connection_id,))


def public_route(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    result["fallback_connection_ids"] = _loads(result.pop("fallback_connection_ids_json", None), [])
    result["config"] = _loads(result.pop("config_json", None), {})
    return result


def upsert_route(db: Database, payload: CapabilityRoutePayload) -> dict[str, Any]:
    avatar_id = payload.avatar_id.strip() if payload.scope_type == "avatar" else ""
    ids = [payload.primary_connection_id, *payload.fallback_connection_ids]
    for connection_id in filter(None, ids):
        row = connection_row(db, connection_id)
        if not row:
            raise ProviderError(f"服务连接不存在：{connection_id}")
        if payload.capability not in _loads(row.get("capabilities_json"), []):
            raise ProviderError(f"连接 {row['display_name']} 未启用 {payload.capability} 能力")
    now = int(time.time())
    db.execute(
        """INSERT INTO capability_routes(scope_type,avatar_id,capability,primary_connection_id,fallback_connection_ids_json,model,config_json,updated_at)
        VALUES(?,?,?,?,?,?,?,?) ON CONFLICT(scope_type,avatar_id,capability) DO UPDATE SET
        primary_connection_id=excluded.primary_connection_id,fallback_connection_ids_json=excluded.fallback_connection_ids_json,
        model=excluded.model,config_json=excluded.config_json,updated_at=excluded.updated_at""",
        (payload.scope_type, avatar_id, payload.capability, payload.primary_connection_id,
         json.dumps(payload.fallback_connection_ids), payload.model.strip(), json.dumps(payload.config), now),
    )
    row = db.one("SELECT * FROM capability_routes WHERE scope_type=? AND avatar_id=? AND capability=?", (payload.scope_type, avatar_id, payload.capability))
    return public_route(row or {})


def find_route(db: Database, capability: str, avatar_id: str = "") -> dict[str, Any] | None:
    row = None
    if avatar_id:
        row = db.one("SELECT * FROM capability_routes WHERE scope_type='avatar' AND avatar_id=? AND capability=?", (avatar_id, capability))
    row = row or db.one("SELECT * FROM capability_routes WHERE scope_type='global' AND avatar_id='' AND capability=?", (capability,))
    return public_route(row) if row else None


def _spent(db: Database, connection_id: str, since: int) -> float:
    row = db.one("SELECT COALESCE(SUM(estimated_cost),0) AS total FROM usage_events WHERE provider=? AND created_at>=?", (connection_id, since))
    return float((row or {}).get("total", 0) or 0)


def assert_allowed(db: Database, row: dict[str, Any], capability: str) -> None:
    if not bool(row.get("enabled")):
        raise ProviderError("服务连接已停用")
    if row.get("provider_kind") == "local":
        _validate_local_connection(str(row["base_url"]))
    consent = _loads(row.get("consent_json"), {})
    data_class = CONSENT_CLASS[capability]
    if row.get("provider_kind") != "local" and not bool(consent.get(data_class, False)):
        raise ProviderError(f"尚未授权向该服务发送{data_class}数据")
    budget = _loads(row.get("budget_json"), {})
    now = int(time.time())
    day_start = now - (now % 86400)
    month_start = int(datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0).timestamp())
    daily, monthly = float(budget.get("daily", 0) or 0), float(budget.get("monthly", 0) or 0)
    if daily and _spent(db, str(row["id"]), day_start) >= daily:
        raise ProviderError("该服务已达到今日预算上限")
    if monthly and _spent(db, str(row["id"]), month_start) >= monthly:
        raise ProviderError("该服务已达到本月预算上限")


def route_candidates(db: Database, capability: str, avatar_id: str = "") -> list[tuple[dict[str, Any], str, dict[str, Any]]]:
    route = find_route(db, capability, avatar_id)
    if not route:
        return []
    result = []
    for connection_id in [route.get("primary_connection_id", ""), *route.get("fallback_connection_ids", [])]:
        row = connection_row(db, str(connection_id)) if connection_id else None
        if not row:
            continue
        try:
            assert_allowed(db, row, capability)
        except ProviderError:
            continue
        model = str(route.get("model") or _loads(row.get("models_json"), {}).get(capability, ""))
        result.append((row, model, route.get("config", {})))
    return result


def routed_chat_configs(db: Database, avatar_id: str = "") -> list[ProviderConfig]:
    candidates = route_candidates(db, "chat", avatar_id)
    configs = []
    for row, model, _ in candidates:
        if not model:
            continue
        kind = str(row["provider_kind"])
        configs.append(ProviderConfig(
            mode="local_openai" if kind == "local" else "cloud_openai",
            provider_name=str(row["display_name"]), base_url=str(row["base_url"]), model=model,
            api_key=load_provider_key(provider_key_name(str(row["id"]))), cloud_data_consent=kind != "local",
        ))
    return configs


def routed_chat_entries(db: Database, avatar_id: str = "") -> list[tuple[ProviderConfig, dict[str, Any]]]:
    entries = []
    for row, model, _ in route_candidates(db, "chat", avatar_id):
        if not model:
            continue
        kind = str(row["provider_kind"])
        entries.append((ProviderConfig(
            mode="local_openai" if kind == "local" else "cloud_openai",
            provider_name=str(row["display_name"]), base_url=str(row["base_url"]), model=model,
            api_key=load_provider_key(provider_key_name(str(row["id"]))), cloud_data_consent=kind != "local",
        ), row))
    return entries


def routed_chat_config(db: Database, avatar_id: str = "") -> ProviderConfig | None:
    configs = routed_chat_configs(db, avatar_id)
    return configs[0] if configs else None


def discover_models(row: dict[str, Any]) -> list[str]:
    local = row.get("provider_kind") == "local"
    if local:
        _validate_local_connection(str(row["base_url"]))
    url = str(row["base_url"]).rstrip("/") + "/models"
    key = load_provider_key(provider_key_name(str(row["id"])))
    request = urllib.request.Request(url, headers={"Authorization": f"Bearer {key}"} if key else {})
    try:
        opener = local_urlopen if local else urllib.request.urlopen
        with opener(request, timeout=15, context=verified_ssl_context()) as response:
            data = json.loads(response.read().decode("utf-8"))
        return [str(item["id"]) for item in data.get("data", []) if isinstance(item, dict) and item.get("id")]
    except (LocalModelError, OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise ProviderError(f"读取模型列表失败：{exc}") from exc


def test_connection(db: Database, connection_id: str) -> dict[str, Any]:
    row = connection_row(db, connection_id)
    if not row:
        raise ProviderError("服务连接不存在")
    try:
        if row.get("provider_kind") == "local":
            _validate_local_connection(str(row["base_url"]))
        models = discover_models(row) if any(c in _loads(row.get("capabilities_json"), []) for c in ("chat", "vision")) else []
        status, message = "ok", f"连接成功" + (f"，发现 {len(models)} 个模型" if models else "")
    except ProviderError as exc:
        status, message, models = "failed", str(exc), []
    now = int(time.time())
    db.execute("UPDATE provider_connections SET last_test_status=?,last_test_message=?,last_tested_at=?,updated_at=? WHERE id=?", (status, message, now, now, connection_id))
    return {"ok": status == "ok", "message": message, "models": models, "tested_at": now}


def record_provider_usage(db: Database, avatar_id: str, connection_id: str, model: str, capability: str, status: str, *, latency_ms: float = 0, estimated_cost: float = 0, metadata: dict[str, Any] | None = None) -> None:
    db.execute(
        "INSERT INTO usage_events(avatar_id,provider,model,role,operation,status,latency_ms,estimated_cost,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (avatar_id, connection_id, model, capability, capability, status, latency_ms, estimated_cost, json.dumps(metadata or {}), int(time.time())),
    )


def estimate_provider_cost(row: dict[str, Any], capability: str, *, input_units: int = 0, output_units: int = 0) -> float:
    config = _loads(row.get("config_json"), {})
    custom = config.get("cost_estimates") if isinstance(config.get("cost_estimates"), dict) else {}
    if capability in custom:
        return max(0.0, float(custom[capability]))
    if row.get("provider_kind") != "minimax":
        return 0.0
    if capability == "chat":
        return round((input_units / 4) * 0.3 / 1_000_000 + (output_units / 4) * 1.2 / 1_000_000, 8)
    if capability == "tts":
        return round(input_units * 0.0001, 6)
    return {"voice_clone": 1.5, "image": 0.01, "video": 0.48}.get(capability, 0.0)
