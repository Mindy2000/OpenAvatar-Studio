from __future__ import annotations

from dataclasses import dataclass, field
import json
import mimetypes
from pathlib import Path
import time
from typing import Any
import urllib.error
import urllib.request
from uuid import uuid4

from openavatar.providers import ProviderError, load_provider_key, verified_ssl_context


@dataclass
class VideoCallStartRequest:
    avatar_id: str
    call_id: int
    avatar_name: str
    user_camera_enabled: bool = False
    metadata: dict[str, Any] = field(default_factory=dict)


def _compact_error(value: Any) -> str:
    if isinstance(value, dict):
        for key in ("error", "message", "detail"):
            if value.get(key):
                return str(value.get(key))[:240]
        return json.dumps(value, ensure_ascii=False)[:240]
    return str(value or "")[:240]


def _north_api_url(settings: dict[str, Any]) -> str:
    return str(settings.get("north_api_url") or "https://api.atlasv1.com").rstrip("/")


def _north_headers(settings: dict[str, Any], *, content_type: str = "") -> dict[str, str]:
    api_key = str(settings.get("north_api_key") or load_provider_key("north")).strip()
    if not api_key:
        raise ProviderError("缺少 North/Atlas API Key")
    headers = {"Authorization": f"Bearer {api_key}"}
    if content_type:
        headers["Content-Type"] = content_type
    return headers


def _north_post_json(settings: dict[str, Any], path: str, payload: dict[str, Any], timeout: int = 30) -> tuple[int, dict[str, Any]]:
    request = urllib.request.Request(
        f"{_north_api_url(settings)}{path}",
        data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
        headers=_north_headers(settings, content_type="application/json"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=verified_ssl_context()) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body or "{}")
        except json.JSONDecodeError:
            return exc.code, {"error": body}


def _north_post_multipart(settings: dict[str, Any], path: str, fields: dict[str, str], files: dict[str, Path], timeout: int = 45) -> tuple[int, dict[str, Any]]:
    boundary = f"----openavatar-north-{uuid4().hex}"
    chunks: list[bytes] = []
    for name, value in fields.items():
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode())
        chunks.append(str(value).encode("utf-8"))
        chunks.append(b"\r\n")
    for name, path_value in files.items():
        filename = path_value.name
        media_type = mimetypes.guess_type(filename)[0] or "application/octet-stream"
        chunks.append(f"--{boundary}\r\n".encode())
        chunks.append(f'Content-Disposition: form-data; name="{name}"; filename="{filename}"\r\n'.encode())
        chunks.append(f"Content-Type: {media_type}\r\n\r\n".encode())
        chunks.append(path_value.read_bytes())
        chunks.append(b"\r\n")
    chunks.append(f"--{boundary}--\r\n".encode())
    request = urllib.request.Request(
        f"{_north_api_url(settings)}{path}",
        data=b"".join(chunks),
        headers=_north_headers(settings, content_type=f"multipart/form-data; boundary={boundary}"),
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=verified_ssl_context()) as response:
            body = response.read().decode("utf-8", errors="replace")
            return response.status, json.loads(body or "{}")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            return exc.code, json.loads(body or "{}")
        except json.JSONDecodeError:
            return exc.code, {"error": body}


def close_north_session(settings: dict[str, Any], north_session_id: str, timeout: int = 20) -> dict[str, Any]:
    if not north_session_id:
        return {"ok": True, "status": "no_remote_session"}
    request = urllib.request.Request(
        f"{_north_api_url(settings)}/v1/realtime/session/{north_session_id}",
        headers=_north_headers(settings),
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=verified_ssl_context()) as response:
            body = response.read().decode("utf-8", errors="replace")
            payload = json.loads(body or "{}")
            payload["statusCode"] = response.status
            payload["ok"] = 200 <= response.status < 300
            return payload
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        try:
            payload = json.loads(body or "{}")
        except json.JSONDecodeError:
            payload = {"error": body}
        payload["statusCode"] = exc.code
        payload["ok"] = False
        return payload


def video_call_provider_status(settings: dict[str, Any], face_path: Path | None = None) -> dict[str, Any]:
    has_key = bool(str(settings.get("north_api_key") or load_provider_key("north")).strip())
    has_face_url = bool(str(settings.get("north_face_url") or "").strip())
    has_face_file = bool(face_path and face_path.is_file())
    available = has_key and (has_face_url or has_face_file)
    reason = "North/Atlas 已配置" if available else "需要 North/Atlas API Key，并提供 HTTPS face URL 或一个 canonical/approved 本地身份图"
    return {
        "provider": "north",
        "available": available,
        "reason": reason,
        "protocolVersion": "3.0-draft",
        "transport": "livekit",
        "fixedProvider": True,
        "requiresNorthApiKey": not has_key,
        "requiresFaceReference": not (has_face_url or has_face_file),
        "supports": {
            "stateEvents": True,
            "speakText": True,
            "audioDriven": True,
            "webrtc": True,
            "livekit": True,
            "interrupt": True,
            "customFaceImage": True,
            "sceneBackground": bool(settings.get("scene_background_enabled", True)),
            "cameraFlip": bool(settings.get("camera_flip_enabled", True)),
            "visionFeedback": bool(settings.get("vision_feedback_enabled", True)),
            "smartInterrupt": bool(settings.get("smart_interrupt_enabled", True)),
        },
    }


def start_north_video_call(settings: dict[str, Any], request: VideoCallStartRequest, face_path: Path | None = None) -> dict[str, Any]:
    status = video_call_provider_status(settings, face_path)
    if not status["available"]:
        raise ProviderError(f"North 视频通话未配置：{status['reason']}")
    idle_timeout = int(settings.get("north_idle_timeout") or 300)
    budget = {
        "price_per_second": float(settings.get("north_price_per_second") or 0.00194),
        "scene_background_enabled": bool(settings.get("scene_background_enabled", True)),
        "camera_flip_enabled": bool(settings.get("camera_flip_enabled", True)),
        "vision_feedback_enabled": bool(settings.get("vision_feedback_enabled", True)),
        "smart_interrupt_enabled": bool(settings.get("smart_interrupt_enabled", True)),
    }
    face_url = str(settings.get("north_face_url") or "").strip()
    if face_url:
        code, result = _north_post_json(
            settings,
            "/v1/realtime/session",
            {"face_url": face_url, "mode": "passthrough", "idle_timeout": idle_timeout},
        )
    else:
        if not face_path:
            raise ProviderError("North 视频通话缺少可读取的身份参考图")
        code, result = _north_post_multipart(
            settings,
            "/v1/realtime/session",
            {"mode": "passthrough", "idle_timeout": str(idle_timeout)},
            {"face": face_path},
        )
    if code < 200 or code >= 300 or not isinstance(result, dict):
        raise ProviderError(f"North session 创建失败：{_compact_error(result)}")
    missing = [key for key in ("session_id", "livekit_url", "token") if not result.get(key)]
    if missing:
        raise ProviderError("North session 返回缺少 " + " / ".join(missing))
    now = time.time()
    price_per_second = budget["price_per_second"]
    return {
        "ok": True,
        "provider": "north",
        "callId": request.call_id,
        "northSessionId": str(result.get("session_id") or ""),
        "transport": "livekit",
        "streamMode": "realtime-passthrough",
        "layout": "avatar-primary",
        "avatar": {
            "kind": "north-realtime",
            "name": request.avatar_name,
            "description": "North/Atlas 实时口型头像；人格、记忆、语音、背景、翻转镜头和失败降级由 OpenAvatar Studio 调度。",
        },
        "livekit": {
            "url": str(result.get("livekit_url") or ""),
            "token": str(result.get("token") or ""),
            "room": str(result.get("room") or ""),
        },
        "renderModes": ["avatar", "scene_background", "flipped_camera", "voice_static_fallback"],
        "budget": {"pricePerSecond": price_per_second, "billing": "elapsed-only"},
        "capabilities": {
            "stateEvents": True,
            "speakText": True,
            "audioDriven": True,
            "webrtc": True,
            "livekit": True,
            "interrupt": True,
            "customFaceImage": True,
            "sceneBackground": budget["scene_background_enabled"],
            "cameraFlip": budget["camera_flip_enabled"],
            "visionFeedback": budget["vision_feedback_enabled"],
            "smartInterrupt": budget["smart_interrupt_enabled"],
            "fullBodyMotion": "asset-clip-or-async-video",
        },
        "metadata": {
            "protocol": "openavatar.video-call.north.v1",
            "north_session_id": str(result.get("session_id") or ""),
            "started_at_monotonic": now,
            "price_per_second": price_per_second,
            "settings": budget,
            "face_source": "url" if face_url else "visual_asset",
        },
    }
