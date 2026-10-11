"""Local-only first-run checks. No model clients or network probes are created."""
from __future__ import annotations

import json
import time
from typing import Any, Callable

from openavatar.db import Database
from openavatar.local_model import LocalModelError, validate_local_url
from openavatar.providers import ProviderError, load_provider_key, normalize_openai_base_url, scoped_provider_key_name
from openavatar.services.provider_hub import CONSENT_CLASS, assert_allowed, find_route, provider_key_name
from openavatar.services.readiness import completion_report


DISMISSED_KEY = "setup_guide_dismissed_v1"
CAPABILITIES = ("chat", "tts", "vision")


def has_key(account: str) -> bool:
    """Keep credential values inside the existing credential boundary."""
    return bool(load_provider_key(account))


def _json(value: Any, default: Any) -> Any:
    try:
        parsed = json.loads(value or "null") if isinstance(value, str) else value
    except (TypeError, ValueError):
        return default
    return parsed if isinstance(parsed, type(default)) else default


def _key_issue(account: str, check: Callable[[str], bool]) -> list[str]:
    try:
        return [] if check(account) else ["credentials_missing"]
    except Exception:
        # Backend exceptions can contain paths/account details. Do not expose them.
        return ["credentials_unavailable"]


def _candidate(db: Database, row: dict[str, Any], route: dict[str, Any], capability: str, check: Callable[[str], bool]) -> dict[str, Any]:
    issues: list[str] = []
    local = row.get("provider_kind") == "local"
    if not row.get("enabled"):
        issues.append("connection_disabled")
    if capability not in _json(row.get("capabilities_json"), []):
        issues.append("capability_disabled")
    if not local and not _json(row.get("consent_json"), {}).get(CONSENT_CLASS[capability]):
        issues.append("consent_missing")
    model = str(route.get("model") or _json(row.get("models_json"), {}).get(capability) or "").strip()
    if capability == "tts":
        model = model or {"minimax": "speech-2.8-hd", "aliyun": "qwen3-tts-vc-2026-01-22"}.get(str(row.get("provider_kind")), "")
        if row.get("provider_kind") not in {"minimax", "aliyun"}:
            issues.append("adapter_unsupported")
    if not model:
        issues.append("model_missing")
    try:
        if local:
            validate_local_url(str(row.get("base_url") or ""))
        else:
            normalize_openai_base_url(str(row.get("base_url") or ""))
    except (ProviderError, LocalModelError, ValueError):
        issues.append("address_invalid")
    if not local:
        issues.extend(_key_issue(provider_key_name(str(row["id"])), check))
    # Reuse the runtime consent/budget rules; this does not reserve or spend funds.
    eligible = True
    try:
        assert_allowed(db, row, capability)
    except ProviderError as exc:
        eligible = False
        if "预算" in str(exc):
            issues.append("budget_exhausted")
        elif not issues:
            issues.append("connection_unavailable")
    except (TypeError, ValueError, OverflowError):
        eligible = False
        issues.append("budget_invalid")
    return {"connection_id": row["id"], "display_name": row["display_name"],
            "model": model, "ready": not issues, "issues": issues, "route_eligible": eligible}


def _legacy_chat(db: Database, avatar_id: str, check: Callable[[str], bool]) -> dict[str, Any] | None:
    settings = db.one("SELECT * FROM avatar_model_settings WHERE avatar_id=?", (avatar_id,)) if avatar_id else None
    connection_id = str((settings or {}).get("connection_id") or db.setting("selected_model_connection_id", "") or "")
    row = db.one("SELECT * FROM model_connections WHERE id=?", (connection_id,)) if connection_id else None
    if not row:
        return None
    issues = []
    cloud = row.get("connection_type") == "cloud_openai"
    if not row.get("model"):
        issues.append("model_missing")
    if cloud:
        if not row.get("cloud_data_consent"):
            issues.append("consent_missing")
        issues.extend(_key_issue(scoped_provider_key_name("model_connection", connection_id), check))
    try:
        if cloud:
            normalize_openai_base_url(str(row.get("base_url") or ""))
        else:
            validate_local_url(str(row.get("base_url") or ""))
    except (ProviderError, LocalModelError, ValueError):
        issues.append("address_invalid")
    if row.get("last_test_status") != "ok" or int(row.get("last_tested_at") or 0) < time.time() - 7 * 86400:
        issues.append("legacy_test_required")
    return {"capability": "chat", "ready": not issues, "source": "legacy", "scope": "avatar" if settings and settings.get("connection_id") else "global",
            "connection_id": connection_id, "display_name": row["display_name"], "model": row.get("model", ""),
            "issues": issues, "candidates": []}


def capability_status(db: Database, capability: str, avatar_id: str = "", *, key_check: Callable[[str], bool] | None = None) -> dict[str, Any]:
    check = key_check or has_key
    route = find_route(db, capability, avatar_id)
    if not route:
        legacy = _legacy_chat(db, avatar_id, check) if capability == "chat" else None
        return legacy or {"capability": capability, "ready": False, "source": "hub", "scope": "global",
                          "connection_id": "", "issues": ["route_missing"], "candidates": []}
    candidates = []
    ids = list(dict.fromkeys(filter(None, [route.get("primary_connection_id"), *route.get("fallback_connection_ids", [])])))
    for connection_id in ids:
        row = db.one("SELECT * FROM provider_connections WHERE id=?", (connection_id,))
        candidates.append(_candidate(db, row, route, capability, check) if row else {
            "connection_id": connection_id, "display_name": "", "model": "", "ready": False, "issues": ["connection_missing"]})
    # Vision and calls deliberately consume the first eligible route; a missing
    # key/model there cannot be hidden by advertising a later fallback as ready.
    criterion = "ready" if capability == "chat" else "route_eligible"
    selected = next((item for item in candidates if item.get(criterion)), None)
    selected = selected or (candidates[0] if candidates else None)
    return {"capability": capability, "ready": bool(selected and selected["ready"]), "source": "hub",
            "scope": route.get("scope_type", "global"), "connection_id": selected["connection_id"] if selected else "",
            "display_name": selected.get("display_name", "") if selected else "", "model": selected.get("model", "") if selected else "",
            "using_fallback": bool(selected and ids and selected["connection_id"] != ids[0]),
            "issues": selected["issues"] if selected else ["connection_missing"], "candidates": candidates}


def setup_status(db: Database, avatar_id: str = "", *, key_check: Callable[[str], bool] | None = None) -> dict[str, Any]:
    avatars = db.all("SELECT id,name FROM avatars ORDER BY updated_at DESC,id")
    avatar = next((row for row in avatars if row["id"] == avatar_id), None) if avatar_id else (avatars[0] if avatars else None)
    if avatar_id and avatar is None:
        raise KeyError("avatar_not_found")
    selected_id = str(avatar["id"]) if avatar else ""
    statuses = {capability: capability_status(db, capability, selected_id, key_check=key_check) for capability in CAPABILITIES}
    required = None
    if avatar:
        report = completion_report(db, selected_id, model_ready=statuses["chat"]["ready"])
        required = {"ready": report["can_start_official"], "summary": report["summary"]["required"],
                    "missing": [{"name": item["name"], "recommendation": item["recommendation"]}
                                for item in report["checks"] if item["level"] == "required" and not item["passed"]]}
    configured = any(db.one(f"SELECT 1 AS present FROM {table} LIMIT 1") for table in ("provider_connections", "model_connections", "capability_routes", "ocr_connections", "imports"))
    configured = configured or bool(db.setting("model", {})) or bool(db.setting("cloud_services", {}))
    dismissed = bool(db.setting(DISMISSED_KEY, False))
    return {"version": 1, "dismissed": dismissed,
            "auto_show": not (dismissed or avatars or configured or db.setting("onboarding_completed", False)),
            "capabilities": statuses, "avatar": avatar, "avatar_count": len(avatars), "required": required,
            "check_mode": "local_configuration_only"}
