from __future__ import annotations

import base64
import json
import mimetypes
import os
import ssl
import urllib.error
import urllib.request
from urllib.parse import urlparse
from pathlib import Path
from typing import Any


class AliyunError(RuntimeError):
    pass


def _ssl_context() -> ssl.SSLContext:
    system_bundle = "/etc/ssl/cert.pem"
    return ssl.create_default_context(cafile=system_bundle if os.path.isfile(system_bundle) else None)


def _data_url(path: Path) -> str:
    mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
    return f"data:{mime};base64,{base64.b64encode(path.read_bytes()).decode('ascii')}"


def _error_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("message") or value.get("Message") or value.get("code") or json.dumps(value, ensure_ascii=False))[:500]
    return str(value)[:500]


def extract_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        urls.append(value)
    elif isinstance(value, list):
        for item in value:
            urls.extend(extract_urls(item))
    elif isinstance(value, dict):
        for item in value.values():
            if isinstance(item, (str, list, dict)):
                urls.extend(extract_urls(item))
    return list(dict.fromkeys(urls))


def download_provider_asset(url: str, target: Path, *, max_bytes: int = 100 * 1024 * 1024) -> str:
    parsed = urlparse(url)
    hostname = (parsed.hostname or "").lower()
    if parsed.scheme == "http" and (hostname == "aliyuncs.com" or hostname.endswith(".aliyuncs.com")):
        url = "https://" + url[len("http://"):]
        parsed = urlparse(url)
    if parsed.scheme != "https" or not parsed.hostname:
        raise AliyunError("服务商返回了不安全的结果地址")
    request = urllib.request.Request(url, headers={"User-Agent": "OpenAvatar-Studio/0.1"})
    try:
        with urllib.request.urlopen(request, timeout=180, context=_ssl_context()) as response:
            content_type = response.headers.get("Content-Type", "application/octet-stream").split(";", 1)[0]
            target.parent.mkdir(parents=True, exist_ok=True)
            total = 0
            with target.open("wb") as handle:
                while chunk := response.read(1024 * 1024):
                    total += len(chunk)
                    if total > max_bytes:
                        raise AliyunError("服务商返回的文件超过本地大小限制")
                    handle.write(chunk)
            return content_type
    except (OSError, urllib.error.URLError) as exc:
        target.unlink(missing_ok=True)
        raise AliyunError(f"下载云端结果失败：{exc}") from exc


class AliyunAvatarClient:
    """DashScope adapter migrated from the single-person legacy project.

    It intentionally owns no paths or database state so one client can safely be
    used by many avatars. The caller decides when a potentially billable call runs.
    """

    def __init__(self, api_key: str, *, base_url: str = "https://dashscope.aliyuncs.com", timeout: int = 180):
        self.api_key = api_key.strip()
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key)

    def _request(self, method: str, path: str, payload: dict[str, Any] | None = None, *, async_call: bool = False) -> dict[str, Any]:
        if not self.api_key:
            raise AliyunError("尚未配置阿里云百炼 API Key")
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json", "X-DashScope-DataInspection": "enable"}
        if async_call:
            headers["X-DashScope-Async"] = "enable"
        data = json.dumps(payload, ensure_ascii=False).encode("utf-8") if payload is not None else None
        request = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=_ssl_context()) as response:
                result = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raw = exc.read().decode("utf-8", errors="replace")
            try:
                detail: Any = json.loads(raw)
            except json.JSONDecodeError:
                detail = raw
            raise AliyunError(f"阿里云接口返回 {exc.code}：{_error_text(detail)}") from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise AliyunError(f"阿里云接口调用失败：{exc}") from exc
        if not isinstance(result, dict):
            raise AliyunError("阿里云接口返回了无效数据")
        return result

    def clone_voice(self, sample: Path, *, preferred_name: str, clone_model: str, target_model: str) -> dict[str, Any]:
        result = self._request("POST", "/api/v1/services/audio/tts/customization", {
            "model": clone_model,
            "input": {"action": "create", "target_model": target_model, "preferred_name": preferred_name[:16], "audio": {"data": _data_url(sample)}},
        })
        output = result.get("output") if isinstance(result.get("output"), dict) else {}
        voice_id = str(output.get("voice") or output.get("voice_id") or "").strip()
        if not voice_id:
            raise AliyunError("声音复刻成功响应中没有 voice id")
        return {"voice_id": voice_id, "target_model": str(output.get("target_model") or target_model), "raw_output": output}

    def synthesize(self, text: str, *, voice_id: str, model: str) -> dict[str, Any]:
        result = self._request("POST", "/api/v1/services/aigc/multimodal-generation/generation", {
            "model": model,
            "input": {"text": text[:2000], "voice": voice_id, "language_type": "Chinese"},
            "parameters": {"audio_format": "mp3"},
        })
        return result

    def generate_reference_image(self, images: list[Path], *, prompt: str, model: str, size: str = "1024*1536") -> dict[str, Any]:
        refs = images[:3]
        if not refs:
            raise AliyunError("至少需要一张人物参考图")
        content = [{"image": _data_url(path)} for path in refs]
        content.append({"text": prompt[:800]})
        result = self._request("POST", "/api/v1/services/aigc/multimodal-generation/generation", {
            "model": model,
            "input": {"messages": [{"role": "user", "content": content}]},
            "parameters": {"size": size, "n": 1, "prompt_extend": True, "watermark": False,
                           "negative_prompt": "低质量，脸部扭曲，五官不一致，多余手指，文字，水印"},
        })
        return result

    def start_video(
        self,
        first_frame_url: str,
        *,
        prompt: str,
        model: str,
        reference_images: list[str] | None = None,
        last_frame_url: str = "",
        generate_audio: bool = False,
    ) -> dict[str, Any]:
        allowed = ("https://", "data:image/")
        media: list[dict[str, Any]] = []
        if first_frame_url.startswith(allowed):
            media.append({"type": "first_frame", "url": first_frame_url})
        if last_frame_url.startswith(allowed):
            media.append({"type": "last_frame", "url": last_frame_url})
        for value in (reference_images or [])[:5]:
            if value.startswith(allowed):
                media.append({"type": "reference_image", "url": value})
        if not media:
            raise AliyunError("视频生成需要首帧或参考图片")
        return self._request("POST", "/api/v1/services/aigc/video-generation/video-synthesis", {
            "model": model,
            "input": {
                "prompt": prompt[:800],
                "media": media,
            },
            "parameters": {"audio": bool(generate_audio)},
        }, async_call=True)

    def poll_task(self, task_id: str) -> dict[str, Any]:
        return self._request("GET", f"/api/v1/tasks/{task_id}")
