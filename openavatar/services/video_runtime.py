from __future__ import annotations

import base64
import mimetypes
from pathlib import Path
from typing import Any
from openavatar.config import Settings
from openavatar.db import Database
from openavatar.providers import load_api_key, load_provider_key
from openavatar.services.model_connections import provider_config
from openavatar.services.video_generation import VideoGenerationSettings, build_first_frame, select_video_tier
from openavatar.services.provider_hub import provider_key_name, route_candidates

def video_call_settings(db: Database, avatar_id: str = "") -> dict[str, Any]:
    current = db.setting("cloud_services", {})
    routed = route_candidates(db, "realtime_video", avatar_id)
    connection = routed[0][0] if routed and routed[0][0].get("provider_kind") == "north" else None
    return {
        "provider": "north",
        "video_call_enabled": bool(current.get("video_call_enabled", True)),
        "north_api_url": str(connection.get("base_url") if connection else current.get("north_api_url", "https://api.atlasv1.com")),
        "north_api_key": load_provider_key(provider_key_name(str(connection["id"]))) if connection else load_provider_key("north"),
        "north_face_url": str(current.get("north_face_url", "")),
        "north_idle_timeout": int(current.get("north_idle_timeout", 300)),
        "north_price_per_second": float(current.get("north_price_per_second", 0.00194)),
        "scene_background_enabled": bool(current.get("scene_background_enabled", True)),
        "camera_flip_enabled": bool(current.get("camera_flip_enabled", True)),
        "vision_feedback_enabled": bool(current.get("vision_feedback_enabled", True)),
        "smart_interrupt_enabled": bool(current.get("smart_interrupt_enabled", True)),
        "cloud_data_consent": bool(connection) or bool(current.get("cloud_data_consent", False)),
    }


def video_call_face_path(db: Database, settings: Settings, avatar_id: str) -> Path | None:
    row = db.one(
        """
        SELECT local_path FROM visual_assets
        WHERE avatar_id=? AND local_path!='' AND status IN ('canonical','approved')
          AND asset_kind NOT IN ('scene_key_image','scene','background','video_keyframe')
        ORDER BY CASE status WHEN 'canonical' THEN 0 ELSE 1 END, id DESC
        LIMIT 1
        """,
        (avatar_id,),
    )
    if not row:
        return None
    base = settings.data_dir.resolve()
    target = (base / str(row["local_path"])).resolve()
    if base not in target.parents or not target.is_file():
        return None
    return target


def video_generation_settings(db: Database, settings: Settings, avatar_id: str, prompt: str = "") -> VideoGenerationSettings:
    cloud = db.setting("cloud_services", {})
    config = provider_config(db, settings, avatar_id)
    openrouter_key = ""
    if "openrouter" in (config.base_url or "").lower() or "openrouter" in (config.provider_name or "").lower():
        openrouter_key = config.api_key or load_api_key()
    openrouter_key = openrouter_key or load_provider_key("openrouter")
    tier = select_video_tier(prompt)
    default_models = {"lite": "google/veo-3.1-lite", "fast": "google/veo-3.1-fast", "final": "google/veo-3.1"}
    return VideoGenerationSettings(
        provider="openrouter" if openrouter_key else "aliyun",
        openrouter_api_key=openrouter_key,
        aliyun_api_key=load_provider_key("aliyun"),
        aliyun_model=str(cloud.get("video_model", "wan2.7-i2v-2026-04-25")),
        openrouter_model=str(cloud.get(f"openrouter_video_{tier}_model") or cloud.get("openrouter_video_model") or default_models.get(tier, "google/veo-3.1-fast")),
        tier=tier,
        resolution="1080p" if tier == "final" else "720p",
    )


def video_first_frame_for_avatar(db: Database, settings: Settings, avatar_id: str) -> str:
    call_settings = video_call_settings(db)
    return build_first_frame(video_call_face_path(db, settings, avatar_id), str(call_settings.get("north_face_url") or ""))


def continuity_reference_inputs(
    settings: Settings,
    contract: dict[str, Any],
    *,
    max_items: int = 9,
    max_total_bytes: int = 18 * 1024 * 1024,
) -> list[dict[str, Any]]:
    """Resolve the frozen contract to provider-ready references with a strict upload budget."""
    result: list[dict[str, Any]] = []
    consumed = 0
    data_root = settings.data_dir.resolve()
    priorities = {"identity": 0, "wardrobe": 1, "prop": 2, "scene": 3}
    references = sorted(
        contract.get("references") or [],
        key=lambda item: (priorities.get(str(item.get("set_type") or ""), 9), str(item.get("role") or "")),
    )
    for item in references:
        remote = str(item.get("remote_url") or "")
        url = remote if remote.startswith("https://") else ""
        size = 0
        if not url:
            raw_path = str(item.get("local_path") or "")
            if not raw_path:
                continue
            path = (data_root / raw_path).resolve()
            if data_root not in path.parents or not path.is_file():
                continue
            size = path.stat().st_size
            if consumed + size > max_total_bytes:
                continue
            mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
            url = f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"
        consumed += size
        result.append({
            "url": url,
            "set_type": str(item.get("set_type") or "reference"),
            "role": str(item.get("role") or "reference"),
            "visual_asset_id": int(item.get("visual_asset_id") or 0),
            "content_bytes": size,
        })
        if len(result) >= max_items:
            break
    return result


def continuity_first_frame(settings: Settings, contract: dict[str, Any], *, allow_data_url: bool) -> str:
    frame = contract.get("first_frame") or {}
    remote = str(frame.get("remote_url") or "")
    if remote.startswith("https://"):
        return remote
    raw_path = str(frame.get("local_path") or "")
    if not allow_data_url or not raw_path:
        return ""
    candidates = continuity_reference_inputs(settings, {"references": [frame]}, max_items=1)
    return str(candidates[0]["url"] if candidates else "")
