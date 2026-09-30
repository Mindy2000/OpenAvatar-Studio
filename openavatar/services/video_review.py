from __future__ import annotations

import base64
import json
import mimetypes
import re
import time
from pathlib import Path
from typing import Any

from openavatar.config import Settings
from openavatar.db import Database
from openavatar.providers import OpenAICompatibleClient, ProviderError, load_provider_key
from openavatar.services.provider_hub import provider_key_name, record_provider_usage, route_candidates


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/jpeg"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _parse_json(value: str) -> dict[str, Any]:
    text = value.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    try:
        result = json.loads(text)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", text, re.DOTALL)
        result = json.loads(match.group(0)) if match else {}
    return result if isinstance(result, dict) else {}


def review_video_frames(
    db: Database,
    settings: Settings,
    *,
    avatar_id: str,
    contract: dict[str, Any],
    keyframes: list[dict[str, Any]],
) -> dict[str, Any]:
    frame_paths = [settings.data_dir / str(item.get("local_path") or "") for item in keyframes]
    frame_paths = [path for path in frame_paths if path.is_file()][:3]
    if not frame_paths:
        return {"available": False, "sendable": False, "manual_review": True, "reason": "没有可审核的关键帧，不能自动放行"}
    reference_paths: list[Path] = []
    for item in contract.get("references", []):
        raw = str(item.get("local_path") or "")
        path = settings.data_dir / raw if raw else None
        if path and path.is_file() and path not in reference_paths:
            reference_paths.append(path)
        if len(reference_paths) >= 4:
            break
    prompt = {
        "task": "比较参考图与视频关键帧，检查人物、服装、物品、场景结构和画面稳定性。",
        "expected_invariants": contract.get("invariants", [])[:20],
        "forbidden_changes": contract.get("negative_constraints", [])[:20],
        "output": {
            "identity_stability": "0-10",
            "wardrobe_consistency": "0-10",
            "prop_consistency": "0-10",
            "scene_consistency": "0-10",
            "artifact_penalty": "0-10，越高越差",
            "sendable": "boolean",
            "reason": "简短中文原因",
        },
    }
    content: list[dict[str, Any]] = [{"type": "text", "text": json.dumps(prompt, ensure_ascii=False)}]
    for path in reference_paths:
        content.extend([
            {"type": "text", "text": "批准的参考图"},
            {"type": "image_url", "image_url": {"url": _data_url(path)}},
        ])
    for path in frame_paths:
        content.extend([
            {"type": "text", "text": "待验收的视频关键帧"},
            {"type": "image_url", "image_url": {"url": _data_url(path)}},
        ])
    errors = []
    for connection, model, _config in route_candidates(db, "vision", avatar_id):
        if not model:
            continue
        connection_id = str(connection["id"])
        started = time.perf_counter()
        try:
            client = OpenAICompatibleClient(
                str(connection["base_url"]),
                model,
                load_provider_key(provider_key_name(connection_id)),
                timeout=180,
                api_key_required=str(connection.get("provider_kind")) != "local",
            )
            raw = client.chat(
                [
                    {"role": "system", "content": "你是数字人视频连续性质检员，只输出严格 JSON。"},
                    {"role": "user", "content": content},
                ],
                json_mode=True,
            )
            result = _parse_json(raw)
            scores = [float(result.get(key, 0) or 0) for key in ("identity_stability", "wardrobe_consistency", "prop_consistency", "scene_consistency")]
            artifact_penalty = float(result.get("artifact_penalty", 0) or 0)
            score = round(max(0.0, min(100.0, sum(scores) / 4 * 10 - artifact_penalty * 2)))
            sendable = bool(result.get("sendable")) and score >= 60 and artifact_penalty < 7
            review = {**result, "available": True, "sendable": sendable, "score": score, "provider": connection_id, "model": model}
            record_provider_usage(db, avatar_id, connection_id, model, "vision", "ok", latency_ms=(time.perf_counter() - started) * 1000)
            return review
        except (ProviderError, OSError, ValueError, json.JSONDecodeError) as exc:
            errors.append(str(exc))
            record_provider_usage(db, avatar_id, connection_id, model, "vision", "failed", latency_ms=(time.perf_counter() - started) * 1000, metadata={"error": str(exc)[:500]})
    return {"available": False, "sendable": False, "manual_review": True, "reason": "未配置可用的视觉审核路由，需要人工确认", "errors": errors[:3]}
