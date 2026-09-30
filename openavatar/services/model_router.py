from __future__ import annotations

import json
import time
from dataclasses import asdict, dataclass
from typing import Any

from openavatar.db import Database


@dataclass(frozen=True)
class ModelRoute:
    role: str
    provider: str
    primary_model: str
    fallback_models: tuple[str, ...]
    latency_class: str
    cost_class: str


DEFAULT_ROUTES: dict[str, ModelRoute] = {
    "chat": ModelRoute("chat", "openrouter", "openrouter/auto", ("deepseek/deepseek-chat",), "interactive", "cheap"),
    "persona_builder": ModelRoute("persona_builder", "openrouter", "deepseek/deepseek-chat", ("openrouter/auto",), "background", "cheap"),
    "world_builder": ModelRoute("world_builder", "openrouter", "deepseek/deepseek-chat", ("openrouter/auto",), "background", "cheap"),
    "judge": ModelRoute("judge", "openrouter", "deepseek/deepseek-chat", ("openrouter/auto",), "background", "cheap"),
    "visual_review": ModelRoute("visual_review", "openrouter", "qwen/qwen3-vl-plus", ("openrouter/auto",), "review", "cheap"),
    "asr_batch": ModelRoute("asr_batch", "development", "manual-or-provider-asr", ("qwen3-asr-flash",), "background", "cheap"),
    "tts": ModelRoute("tts", "development", "piper-zh_CN-xiao_ya-medium", ("provider-builtin",), "interactive", "free_or_cheap"),
}


def _fallbacks(value: str) -> tuple[str, ...]:
    try:
        raw = json.loads(value)
    except json.JSONDecodeError:
        raw = []
    if not isinstance(raw, list):
        return ()
    return tuple(str(item).strip() for item in raw if str(item).strip())


def ensure_default_routes(db: Database) -> None:
    now = int(time.time())
    with db.transaction() as connection:
        for route in DEFAULT_ROUTES.values():
            connection.execute(
                """
                INSERT OR IGNORE INTO model_routes
                (role,provider,primary_model,fallback_models_json,latency_class,cost_class,updated_at)
                VALUES(?,?,?,?,?,?,?)
                """,
                (
                    route.role,
                    route.provider,
                    route.primary_model,
                    json.dumps(list(route.fallback_models), ensure_ascii=False),
                    route.latency_class,
                    route.cost_class,
                    now,
                ),
            )


def list_routes(db: Database) -> list[dict[str, Any]]:
    ensure_default_routes(db)
    rows = db.all("SELECT role,provider,primary_model,fallback_models_json,latency_class,cost_class,updated_at FROM model_routes ORDER BY role")
    result = []
    for row in rows:
        item = dict(row)
        item["fallback_models"] = list(_fallbacks(item.pop("fallback_models_json", "[]")))
        result.append(item)
    return result


def route_for(db: Database, role: str) -> ModelRoute:
    ensure_default_routes(db)
    row = db.one("SELECT * FROM model_routes WHERE role=?", (role,))
    if not row:
        default = DEFAULT_ROUTES.get(role)
        if default:
            return default
        raise KeyError(f"未知模型任务：{role}")
    return ModelRoute(
        role=str(row["role"]),
        provider=str(row["provider"]),
        primary_model=str(row["primary_model"]),
        fallback_models=_fallbacks(str(row["fallback_models_json"])),
        latency_class=str(row["latency_class"]),
        cost_class=str(row["cost_class"]),
    )


def update_route(db: Database, payload: dict[str, Any]) -> dict[str, Any]:
    role = str(payload.get("role") or "").strip()
    if role not in DEFAULT_ROUTES:
        raise ValueError("只能修改系统已知的模型任务")
    provider = str(payload.get("provider") or DEFAULT_ROUTES[role].provider).strip()[:80]
    primary = str(payload.get("primary_model") or "").strip()[:200]
    fallbacks = payload.get("fallback_models")
    if isinstance(fallbacks, str):
        fallback_items = [item.strip() for item in fallbacks.split(",") if item.strip()]
    elif isinstance(fallbacks, list):
        fallback_items = [str(item).strip() for item in fallbacks if str(item).strip()]
    else:
        fallback_items = list(DEFAULT_ROUTES[role].fallback_models)
    if not primary:
        primary = DEFAULT_ROUTES[role].primary_model
    now = int(time.time())
    db.execute(
        """
        INSERT INTO model_routes(role,provider,primary_model,fallback_models_json,latency_class,cost_class,updated_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(role) DO UPDATE SET
          provider=excluded.provider,
          primary_model=excluded.primary_model,
          fallback_models_json=excluded.fallback_models_json,
          latency_class=excluded.latency_class,
          cost_class=excluded.cost_class,
          updated_at=excluded.updated_at
        """,
        (
            role,
            provider,
            primary,
            json.dumps(fallback_items[:10], ensure_ascii=False),
            str(payload.get("latency_class") or DEFAULT_ROUTES[role].latency_class)[:40],
            str(payload.get("cost_class") or DEFAULT_ROUTES[role].cost_class)[:40],
            now,
        ),
    )
    return asdict(route_for(db, role))
