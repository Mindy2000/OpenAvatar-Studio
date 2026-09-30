from __future__ import annotations

import base64
import json
import mimetypes
import os
import ssl
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from openavatar.services.aliyun import AliyunAvatarClient, AliyunError, download_provider_asset, extract_urls


OPENROUTER_VIDEOS_URL = "https://openrouter.ai/api/v1/videos"
OPENROUTER_VIDEO_MODELS = {
    "lite": "google/veo-3.1-lite",
    "fast": "google/veo-3.1-fast",
    "final": "google/veo-3.1",
}
VIDEO_COMPLETE = {"completed", "succeeded", "success"}
VIDEO_FAILED = {"failed", "cancelled", "canceled", "expired"}


class VideoGenerationError(RuntimeError):
    pass


class _SafeVideoRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urljoin(req.full_url, newurl)
        parsed = urllib.parse.urlparse(target)
        if parsed.scheme != "https":
            raise VideoGenerationError("视频下载重定向必须使用 HTTPS")
        redirected = super().redirect_request(req, fp, code, msg, headers, target)
        original_host = (urllib.parse.urlparse(req.full_url).hostname or "").lower()
        if redirected and (parsed.hostname or "").lower() != original_host:
            redirected.remove_header("Authorization")
        return redirected


class _NoAuthenticatedRedirectHandler(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise VideoGenerationError("视频服务的认证请求不允许重定向")


@dataclass(frozen=True)
class VideoGenerationSettings:
    provider: str
    openrouter_api_key: str = ""
    aliyun_api_key: str = ""
    aliyun_model: str = "wan2.7-i2v-2026-04-25"
    openrouter_model: str = OPENROUTER_VIDEO_MODELS["fast"]
    tier: str = "fast"
    duration: int = 8
    resolution: str = "720p"
    aspect_ratio: str = "9:16"
    fallback_provider: str = "aliyun"
    generate_audio: bool = False
    reference_images: tuple[str, ...] = ()
    last_frame: str = ""


def _ssl_context() -> ssl.SSLContext:
    system_bundle = "/etc/ssl/cert.pem"
    return ssl.create_default_context(cafile=system_bundle if os.path.isfile(system_bundle) else None)


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "image/png"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _compact_error(value: Any) -> str:
    if isinstance(value, dict):
        detail = value.get("error") or value.get("message") or value.get("detail") or value
        if isinstance(detail, dict):
            detail = detail.get("message") or detail.get("code") or detail
        return str(detail)[:800]
    return str(value)[:800]


def _json_request(method: str, url: str, headers: dict[str, str], payload: dict[str, Any] | None = None, *, timeout: int = 90) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        opener = urllib.request.build_opener(_NoAuthenticatedRedirectHandler(), urllib.request.HTTPSHandler(context=_ssl_context()))
        with opener.open(request, timeout=timeout) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        raw = exc.read().decode("utf-8", errors="replace")
        try:
            detail: Any = json.loads(raw)
        except json.JSONDecodeError:
            detail = raw
        raise VideoGenerationError(f"视频接口返回 {exc.code}：{_compact_error(detail)}") from exc
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise VideoGenerationError(f"视频接口调用失败：{exc}") from exc


def select_video_tier(prompt: str) -> str:
    text = (prompt or "").lower()
    if any(token in text for token in ("final", "4k", "高质量", "正式", "复杂", "成片", "镜头运动")):
        return "final"
    if len(text) > 90 or any(token in text for token in ("走路", "转身", "跟拍", "校园", "城市", "街道")):
        return "fast"
    return "lite"


def build_first_frame(face_path: Path | None, face_url: str = "") -> str:
    if face_url.strip().startswith("https://"):
        return face_url.strip()
    if face_path and face_path.is_file():
        return _data_url(face_path)
    return ""


def start_video_generation(settings: VideoGenerationSettings, *, prompt: str, first_frame: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    provider = (settings.provider or "openrouter").lower()
    if provider == "openrouter":
        try:
            return start_openrouter_video(settings, prompt=prompt, first_frame=first_frame, metadata=metadata)
        except VideoGenerationError:
            if settings.fallback_provider.lower() != "aliyun" or not settings.aliyun_api_key:
                raise
    return start_aliyun_video(settings, prompt=prompt, first_frame=first_frame, metadata=metadata)


def start_openrouter_video(settings: VideoGenerationSettings, *, prompt: str, first_frame: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if not settings.openrouter_api_key:
        raise VideoGenerationError("尚未配置 OpenRouter 视频 API Key")
    if first_frame and not first_frame.startswith("https://"):
        raise VideoGenerationError("OpenRouter 首尾帧模式需要服务商可直接读取的 HTTPS 图片地址；可切换 MiniMax/阿里百炼使用本地素材")
    references = [value for value in settings.reference_images if value.startswith("https://")][:8]
    if not first_frame and not references:
        raise VideoGenerationError("OpenRouter 视频生成需要 HTTPS 首帧或可公开读取的参考图片")
    payload = {
        "model": settings.openrouter_model,
        "prompt": prompt[:4000],
        "duration": max(4, min(int(settings.duration or 8), 12)),
        "resolution": settings.resolution or ("1080p" if settings.tier == "final" else "720p"),
        "aspect_ratio": settings.aspect_ratio or "9:16",
        "generate_audio": bool(settings.generate_audio),
        "provider": {"allow_fallbacks": True},
    }
    if first_frame:
        payload["frame_images"] = [{"type": "image_url", "image_url": {"url": first_frame}, "frame_type": "first_frame"}]
        if settings.last_frame.startswith("https://"):
            payload["frame_images"].append({"type": "image_url", "image_url": {"url": settings.last_frame}, "frame_type": "last_frame"})
    else:
        payload["input_references"] = [{"type": "image_url", "image_url": {"url": value}} for value in references]
    result = _json_request(
        "POST",
        OPENROUTER_VIDEOS_URL,
        {"Authorization": f"Bearer {settings.openrouter_api_key}", "Content-Type": "application/json"},
        payload,
    )
    task_id = str(result.get("id") or result.get("generation_id") or "").strip()
    if not task_id:
        raise VideoGenerationError("OpenRouter 视频接口没有返回任务 ID")
    return {
        "ok": True,
        "provider": "openrouter",
        "task_id": task_id,
        "status": str(result.get("status") or "PENDING").upper(),
        "model": settings.openrouter_model,
        "polling_url": str(result.get("polling_url") or ""),
        "metadata": {"tier": settings.tier, "duration": payload["duration"], "resolution": payload["resolution"], "aspect_ratio": payload["aspect_ratio"], **(metadata or {})},
    }


def start_aliyun_video(settings: VideoGenerationSettings, *, prompt: str, first_frame: str, metadata: dict[str, Any] | None = None) -> dict[str, Any]:
    if not settings.aliyun_api_key:
        raise VideoGenerationError("尚未配置阿里云百炼 API Key")
    references = [value for value in settings.reference_images if value.startswith(("https://", "data:image/"))][:5]
    if not first_frame.startswith(("https://", "data:image/")) and not references:
        raise VideoGenerationError("阿里 WAN 视频生成需要首帧或参考图片。")
    try:
        result = AliyunAvatarClient(settings.aliyun_api_key).start_video(
            first_frame,
            prompt=prompt,
            model=settings.aliyun_model,
            reference_images=references,
            last_frame_url=settings.last_frame,
            generate_audio=settings.generate_audio,
        )
    except AliyunError as exc:
        raise VideoGenerationError(str(exc)) from exc
    output = result.get("output") if isinstance(result.get("output"), dict) else {}
    task_id = str(output.get("task_id") or "").strip()
    if not task_id:
        raise VideoGenerationError("阿里 WAN 视频接口没有返回 task_id")
    return {
        "ok": True,
        "provider": "aliyun",
        "task_id": task_id,
        "status": str(output.get("task_status") or "PENDING").upper(),
        "model": settings.aliyun_model,
        "polling_url": "",
        "metadata": {"tier": settings.tier, "reference_count": len(references), "generate_audio": settings.generate_audio, **(metadata or {})},
    }


def poll_video_generation(settings: VideoGenerationSettings, *, provider: str, task_id: str, polling_url: str = "") -> dict[str, Any]:
    provider = (provider or "").lower()
    if provider == "openrouter":
        if not settings.openrouter_api_key:
            raise VideoGenerationError("尚未配置 OpenRouter 视频 API Key")
        url = polling_url or f"{OPENROUTER_VIDEOS_URL}/{urllib.parse.quote(task_id)}"
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "openrouter.ai":
            raise VideoGenerationError("OpenRouter 返回了不受信任的任务查询地址")
        result = _json_request("GET", url, {"Authorization": f"Bearer {settings.openrouter_api_key}"}, timeout=60)
        status = str(result.get("status") or result.get("state") or "PENDING").lower()
    else:
        if not settings.aliyun_api_key:
            raise VideoGenerationError("尚未配置阿里云百炼 API Key")
        try:
            result = AliyunAvatarClient(settings.aliyun_api_key).poll_task(task_id)
        except AliyunError as exc:
            raise VideoGenerationError(str(exc)) from exc
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        status = str(output.get("task_status") or output.get("status") or "PENDING").lower()
    unsigned_urls = result.get("unsigned_urls") if isinstance(result.get("unsigned_urls"), list) else []
    videos = [str(url) for url in unsigned_urls if str(url).startswith("https://")]
    if provider != "openrouter":
        urls = [url for url in extract_urls(result) if url.startswith("https://")]
        videos = [url for url in urls if any(ext in url.lower().split("?", 1)[0] for ext in (".mp4", ".webm", ".mov"))]
    if status in VIDEO_COMPLETE:
        if videos:
            return {"ok": True, "done": True, "status": status.upper(), "remote_url": videos[0], "requires_auth": False, "raw": result}
        if provider == "openrouter":
            remote_url = f"{OPENROUTER_VIDEOS_URL}/{urllib.parse.quote(task_id)}/content?index=0"
            return {"ok": True, "done": True, "status": status.upper(), "remote_url": remote_url, "requires_auth": True, "raw": result}
        raise VideoGenerationError("阿里云百炼任务已完成，但没有返回有效视频地址")
    if status in VIDEO_FAILED:
        raise VideoGenerationError(_compact_error(result))
    return {"ok": True, "done": False, "status": status.upper(), "raw": result}


def download_video_result(remote_url: str, target: Path, *, api_key: str = "") -> str:
    parsed = urllib.parse.urlparse(remote_url)
    if parsed.scheme != "https":
        raise VideoGenerationError("视频下载地址必须使用 HTTPS")
    headers = {"Authorization": f"Bearer {api_key}"} if api_key and parsed.hostname == "openrouter.ai" else {}
    request = urllib.request.Request(remote_url, headers=headers)
    target.parent.mkdir(parents=True, exist_ok=True)
    try:
        opener = urllib.request.build_opener(_SafeVideoRedirectHandler(), urllib.request.HTTPSHandler(context=_ssl_context()))
        with opener.open(request, timeout=180) as response:
            if urllib.parse.urlparse(response.geturl()).scheme != "https":
                raise VideoGenerationError("视频下载地址必须使用 HTTPS")
            media_type = str(response.headers.get_content_type() or "application/octet-stream")
            if not media_type.startswith("video/"):
                raise VideoGenerationError("服务商返回的内容不是视频")
            with target.open("wb") as handle:
                total = 0
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > 500 * 1024 * 1024:
                        raise VideoGenerationError("视频结果超过 500MB 限制")
                    handle.write(chunk)
        return media_type
    except (OSError, urllib.error.URLError, VideoGenerationError) as exc:
        target.unlink(missing_ok=True)
        if isinstance(exc, VideoGenerationError):
            raise
        raise VideoGenerationError(f"视频结果下载失败：{exc}") from exc
