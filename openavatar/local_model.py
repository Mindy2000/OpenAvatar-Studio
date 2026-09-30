from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator
from urllib.parse import urlparse


class LocalModelError(RuntimeError):
    pass


def validate_local_url(base_url: str) -> None:
    try:
        if any(char.isspace() or ord(char) < 32 for char in base_url):
            raise ValueError("地址包含空白字符")
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"}:
            raise ValueError("必须使用 http 或 https")
        if parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("只允许连接本机地址")
        if parsed.username is not None or parsed.password is not None or parsed.fragment:
            raise ValueError("不允许用户名、密码或片段")
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError("端口无效")
    except ValueError as exc:
        raise LocalModelError(f"本地模型地址无效：{exc}") from exc


class _NoLocalRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise LocalModelError("本地模型服务不允许重定向，请直接配置服务地址")


def local_urlopen(request, *, timeout, context=None):
    """Keep local model requests off environment proxies and reject redirects."""
    validate_local_url(request.full_url if isinstance(request, urllib.request.Request) else request)
    opener = urllib.request.build_opener(
        urllib.request.ProxyHandler({}),
        _NoLocalRedirect(),
        urllib.request.HTTPSHandler(context=context),
    )
    return opener.open(request, timeout=timeout)


def is_local_url(base_url: str) -> bool:
    try:
        validate_local_url(base_url)
        return True
    except LocalModelError:
        return False



class OllamaClient:
    def __init__(self, base_url: str, model: str, timeout: int = 90):
        validate_local_url(base_url)
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout

    def available(self) -> bool:
        try:
            request = urllib.request.Request(f"{self.base_url}/api/tags")
            with local_urlopen(request, timeout=2) as response:
                return response.status == 200
        except (OSError, urllib.error.URLError):
            return False

    def probe(self) -> bool:
        if not self.available():
            raise LocalModelError(f"无法连接本地 Ollama：{self.base_url}")
        return True

    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
        body: dict[str, object] = {"model": self.model, "messages": messages, "stream": False}
        if json_mode:
            body["format"] = "json"
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with local_urlopen(request, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
            raise LocalModelError(f"本地 Ollama 调用失败：{exc}") from exc
        return str(payload.get("message", {}).get("content", "")).strip()

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        request = urllib.request.Request(
            f"{self.base_url}/api/chat",
            data=json.dumps({"model": self.model, "messages": messages, "stream": True}, ensure_ascii=False).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with local_urlopen(request, timeout=self.timeout) as response:
                for raw in response:
                    try:
                        payload = json.loads(raw.decode("utf-8"))
                    except json.JSONDecodeError:
                        continue
                    content = payload.get("message", {}).get("content", "")
                    if content:
                        yield str(content)
                    if payload.get("done"):
                        break
        except (OSError, urllib.error.URLError) as exc:
            raise LocalModelError(f"本地 Ollama 流式调用失败：{exc}") from exc
