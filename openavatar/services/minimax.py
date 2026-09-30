from __future__ import annotations

import base64
import json
import mimetypes
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path
from typing import Any

from openavatar.providers import ProviderError, normalize_openai_base_url, verified_ssl_context


class MiniMaxError(ProviderError):
    pass


def _nested_urls(value: Any) -> list[str]:
    urls: list[str] = []
    if isinstance(value, str) and value.startswith(("https://", "http://")):
        urls.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            urls.extend(_nested_urls(item))
    elif isinstance(value, list):
        for item in value:
            urls.extend(_nested_urls(item))
    return urls


class MiniMaxClient:
    """MiniMax direct API adapter. Endpoint paths can be overridden per connection."""

    DEFAULT_ENDPOINTS = {
        "tts": "/t2a_v2",
        "asr": "/speech_to_text",
        "file_upload": "/files/upload",
        "voice_clone": "/voice_clone",
        "image": "/image_generation",
        "video_create": "@root:/v2/video_generation",
        "video_query": "@root:/v2/query/video_generation/{task_id}",
    }

    def __init__(self, api_key: str, base_url: str = "https://api.minimax.io/v1", *, endpoints: dict[str, str] | None = None, timeout: int = 180):
        self.api_key = api_key.strip()
        self.base_url = normalize_openai_base_url(base_url)
        self.endpoints = {**self.DEFAULT_ENDPOINTS, **(endpoints or {})}
        self.timeout = timeout

    def available(self) -> bool:
        return bool(self.api_key and self.base_url)

    def _url(self, capability: str, query: dict[str, str] | None = None) -> str:
        path = self.endpoints[capability]
        if path.startswith("@root:"):
            parsed = urllib.parse.urlparse(self.base_url)
            url = f"{parsed.scheme}://{parsed.netloc}{path[len('@root:') :]}"
        else:
            url = path if path.startswith("https://") else f"{self.base_url}{'/' if not path.startswith('/') else ''}{path}"
        return f"{url}?{urllib.parse.urlencode(query)}" if query else url

    def _get(self, capability: str, *, path_values: dict[str, str] | None = None, query: dict[str, str] | None = None) -> dict[str, Any]:
        url = self._url(capability, query)
        for key, value in (path_values or {}).items():
            url = url.replace("{" + key + "}", urllib.parse.quote(value, safe=""))
        request = urllib.request.Request(url, headers={"Authorization": f"Bearer {self.api_key}"})
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=verified_ssl_context()) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise MiniMaxError(f"MiniMax 接口失败（HTTP {exc.code}）：{detail}") from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise MiniMaxError(f"MiniMax 接口请求失败：{exc}") from exc

    def _request(self, capability: str, payload: dict[str, Any], *, query: dict[str, str] | None = None) -> dict[str, Any]:
        if not self.api_key:
            raise MiniMaxError("尚未配置 MiniMax API Key")
        request = urllib.request.Request(
            self._url(capability, query), data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=verified_ssl_context()) as response:
                body = json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise MiniMaxError(f"MiniMax 接口失败（HTTP {exc.code}）：{detail}") from exc
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise MiniMaxError(f"MiniMax 接口请求失败：{exc}") from exc
        base_resp = body.get("base_resp") if isinstance(body, dict) else None
        if isinstance(base_resp, dict) and int(base_resp.get("status_code", 0) or 0) != 0:
            raise MiniMaxError(str(base_resp.get("status_msg") or "MiniMax 返回业务错误"))
        return body

    def _upload(self, path: Path, purpose: str = "voice_clone") -> dict[str, Any]:
        boundary = f"----openavatar{uuid.uuid4().hex}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        data = path.read_bytes()
        chunks = [
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"purpose\"\r\n\r\n{purpose}\r\n".encode(),
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{path.name}\"\r\nContent-Type: {content_type}\r\n\r\n".encode(),
            data, f"\r\n--{boundary}--\r\n".encode(),
        ]
        request = urllib.request.Request(
            self._url("file_upload"), data=b"".join(chunks),
            headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=verified_ssl_context()) as response:
                return json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise MiniMaxError(f"MiniMax 文件上传失败：{exc}") from exc

    def synthesize(self, text: str, *, voice_id: str, model: str = "speech-2.8-hd", config: dict[str, Any] | None = None) -> dict[str, Any]:
        options = config or {}
        payload = {
            "model": model, "text": text, "stream": False,
            "voice_setting": {"voice_id": voice_id, "speed": options.get("speed", 1), "vol": options.get("volume", 1), "pitch": options.get("pitch", 0)},
            "audio_setting": {"sample_rate": options.get("sample_rate", 32000), "bitrate": options.get("bitrate", 128000), "format": options.get("format", "mp3"), "channel": 1},
        }
        result = self._request("tts", payload)
        audio = ((result.get("data") or {}).get("audio") if isinstance(result.get("data"), dict) else None) or result.get("audio")
        return {"raw": result, "audio": audio, "urls": _nested_urls(result)}

    def transcribe(self, audio_path: Path, *, model: str = "", config: dict[str, Any] | None = None) -> dict[str, Any]:
        boundary = f"----openavatar{uuid.uuid4().hex}"
        fields = {"model": model or "asr-1.0", "response_format": "json", **(config or {}).get("request", {})}
        chunks: list[bytes] = []
        for key, value in fields.items():
            chunks.append(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{key}\"\r\n\r\n{value}\r\n".encode())
        content_type = mimetypes.guess_type(audio_path.name)[0] or "application/octet-stream"
        chunks.extend([
            f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"{audio_path.name}\"\r\nContent-Type: {content_type}\r\n\r\n".encode(),
            audio_path.read_bytes(), f"\r\n--{boundary}--\r\n".encode(),
        ])
        request = urllib.request.Request(self._url("asr"), data=b"".join(chunks), headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": f"multipart/form-data; boundary={boundary}"}, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=self.timeout, context=verified_ssl_context()) as response:
                result = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise MiniMaxError(f"MiniMax 语音转写失败：{exc}") from exc
        text = str(result.get("text") or (result.get("data") or {}).get("text") or "")
        return {"text": text, "file_id": "", "raw": result}

    def clone_voice(self, audio_path: Path, *, voice_id: str, model: str = "speech-2.8-hd", config: dict[str, Any] | None = None) -> dict[str, Any]:
        uploaded = self._upload(audio_path)
        file_id = str(((uploaded.get("file") or {}).get("file_id") if isinstance(uploaded.get("file"), dict) else "") or uploaded.get("file_id") or "")
        if not file_id:
            raise MiniMaxError("MiniMax 上传成功但未返回 file_id")
        payload = {"file_id": file_id, "voice_id": voice_id, "model": model, **(config or {}).get("request", {})}
        result = self._request("voice_clone", payload)
        return {"voice_id": voice_id, "file_id": file_id, "raw": result}

    def generate_image(self, prompt: str, *, model: str = "image-01", reference_urls: list[str] | None = None, config: dict[str, Any] | None = None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": model, "prompt": prompt, "response_format": "url", **(config or {}).get("request", {})}
        if reference_urls:
            payload["subject_reference"] = [{"type": "character", "image_file": url} for url in reference_urls]
        result = self._request("image", payload)
        return {"urls": _nested_urls(result), "raw": result}

    def create_video(
        self,
        prompt: str,
        *,
        model: str,
        first_frame_url: str = "",
        last_frame_url: str = "",
        reference_images: list[str] | None = None,
        reference_videos: list[str] | None = None,
        reference_audio: list[str] | None = None,
        config: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        content = [{"type": "text", "text": prompt}]
        references = {
            "reference_image": (reference_images or [])[:9],
            "reference_video": (reference_videos or [])[:3],
            "reference_audio": (reference_audio or [])[:3],
        }
        has_references = any(references.values())
        if (first_frame_url or last_frame_url) and has_references:
            raise MiniMaxError("MiniMax H3 的首帧模式与多参考模式不能同时使用")
        if first_frame_url:
            content.append({"type": "image_url", "image_url": {"url": first_frame_url}, "role": "first_frame"})
        if last_frame_url:
            content.append({"type": "image_url", "image_url": {"url": last_frame_url}, "role": "last_frame"})
        for role, values in references.items():
            media_type = {"reference_image": "image_url", "reference_video": "video_url", "reference_audio": "audio_url"}[role]
            for value in values:
                content.append({"type": media_type, media_type: {"url": value}, "role": role})
        request_options = dict((config or {}).get("request", {}))
        payload = {
            "model": model,
            "content": content,
            "resolution": request_options.pop("resolution", "768P"),
            "duration": request_options.pop("duration", 6),
            "ratio": "adaptive" if first_frame_url or last_frame_url else request_options.pop("ratio", "9:16"),
            **request_options,
        }
        result = self._request("video_create", payload)
        task_id = str(result.get("task_id") or (result.get("data") or {}).get("task_id") or "")
        if not task_id:
            raise MiniMaxError("MiniMax 视频接口未返回 task_id")
        return {
            "task_id": task_id,
            "mode": "reference" if has_references else ("first_frame" if first_frame_url else "text"),
            "reference_count": sum(len(values) for values in references.values()),
            "raw": result,
        }

    def query_video(self, task_id: str) -> dict[str, Any]:
        result = self._get("video_query", path_values={"task_id": task_id})
        task = result.get("task") if isinstance(result.get("task"), dict) else result.get("data") or result
        status = str(task.get("status") or "unknown")
        return {"status": status, "done": status.lower() in {"success", "completed", "succeeded"}, "urls": _nested_urls(result), "raw": result}


def write_audio_result(result: dict[str, Any], target: Path) -> str:
    target.parent.mkdir(parents=True, exist_ok=True)
    audio = result.get("audio")
    if isinstance(audio, str) and audio:
        try:
            target.write_bytes(bytes.fromhex(audio))
        except ValueError:
            target.write_bytes(base64.b64decode(audio))
        return "audio/mpeg"
    urls = result.get("urls") or []
    if not urls:
        raise MiniMaxError("MiniMax 语音接口没有返回音频")
    request = urllib.request.Request(str(urls[0]), headers={"User-Agent": "OpenAvatar-Studio/1"})
    with urllib.request.urlopen(request, timeout=120, context=verified_ssl_context()) as response:
        target.write_bytes(response.read(30 * 1024 * 1024 + 1))
        media_type = response.headers.get_content_type()
    if target.stat().st_size > 30 * 1024 * 1024:
        target.unlink(missing_ok=True)
        raise MiniMaxError("MiniMax 返回的音频超过 30MB 限制")
    return media_type or "audio/mpeg"
