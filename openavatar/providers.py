from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from dataclasses import dataclass
from collections.abc import Iterator
from typing import Protocol
from urllib.parse import urlparse

import keyring
from keyring.errors import KeyringError

from openavatar.local_model import LocalModelError, OllamaClient, local_urlopen, validate_local_url


KEYRING_SERVICE = "OpenAvatar Studio"
KEYRING_ACCOUNT = "chat-provider-api-key"
KEYRING_ACCOUNTS = {
    "chat": KEYRING_ACCOUNT,
    "aliyun": "aliyun-dashscope-api-key",
    "kimi": "kimi-api-key",
    "north": "north-atlas-api-key",
}


class ChatProvider(Protocol):
    model: str

    def available(self) -> bool: ...
    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str: ...
    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]: ...


class ProviderError(RuntimeError):
    pass


def verified_ssl_context() -> ssl.SSLContext:
    system_bundle = "/etc/ssl/cert.pem"
    return ssl.create_default_context(cafile=system_bundle if os.path.isfile(system_bundle) else None)


@dataclass(frozen=True)
class ProviderConfig:
    mode: str = "local"
    provider_name: str = "ollama"
    base_url: str = "http://127.0.0.1:11434"
    model: str = "qwen3:8b"
    cloud_data_consent: bool = False
    api_key: str = ""
    adapter_kind: str = "openai_compatible"


def normalize_openai_base_url(value: str) -> str:
    url = value.strip().rstrip("/")
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ProviderError("API 地址格式不正确")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1"} and parsed.scheme != "https":
        raise ProviderError("远程 API 必须使用 HTTPS")
    if url.endswith("/chat/completions"):
        return url[: -len("/chat/completions")]
    return url


def store_api_key(value: str) -> None:
    store_provider_key("chat", value)


def scoped_provider_key_name(provider: str, scope: str = "") -> str:
    provider = provider.strip().lower()
    if not scope:
        return provider
    return f"{provider}:{scope.strip()}"


def store_provider_key(provider: str, value: str) -> None:
    account = KEYRING_ACCOUNTS.get(provider) or f"provider-api-key:{provider}"
    try:
        keyring.set_password(KEYRING_SERVICE, account, value)
    except KeyringError as exc:
        raise ProviderError(f"无法写入系统安全凭据库：{exc}") from exc


def load_api_key() -> str:
    env_value = os.getenv("OPENAVATAR_API_KEY", "").strip()
    if env_value:
        return env_value
    try:
        return load_provider_key("chat")
    except KeyringError:
        return ""


def delete_api_key() -> None:
    delete_provider_key("chat")


def load_provider_key(provider: str) -> str:
    env_names = {"chat": "OPENAVATAR_API_KEY", "aliyun": "OPENAVATAR_ALIYUN_API_KEY", "kimi": "OPENAVATAR_KIMI_API_KEY", "north": "NORTH_API_KEY"}
    env_value = os.getenv(env_names.get(provider, ""), "").strip() if env_names.get(provider) else ""
    if env_value:
        return env_value
    account = KEYRING_ACCOUNTS.get(provider) or f"provider-api-key:{provider}"
    try:
        return keyring.get_password(KEYRING_SERVICE, account) or ""
    except KeyringError:
        return ""


def delete_provider_key(provider: str) -> None:
    account = KEYRING_ACCOUNTS.get(provider) or f"provider-api-key:{provider}"
    try:
        if keyring.get_password(KEYRING_SERVICE, account):
            keyring.delete_password(KEYRING_SERVICE, account)
    except KeyringError as exc:
        raise ProviderError(f"无法从系统安全凭据库删除 API Key：{exc}") from exc


class OpenAICompatibleClient:
    def __init__(self, base_url: str, model: str, api_key: str = "", timeout: int = 120, *, api_key_required: bool = True):
        self.base_url = normalize_openai_base_url(base_url)
        self.model = model
        self.api_key = api_key
        self.timeout = timeout
        self.api_key_required = api_key_required

    def _open(self, request, *, timeout, context):
        if not self.api_key_required:
            return local_urlopen(request, timeout=timeout, context=context)
        return urllib.request.urlopen(request, timeout=timeout, context=context)

    def available(self) -> bool:
        return bool(self.base_url and self.model and (self.api_key or not self.api_key_required))

    def probe(self) -> bool:
        if self.api_key_required and not self.api_key:
            raise ProviderError("尚未配置 API Key")
        request = urllib.request.Request(
            f"{self.base_url}/models",
            headers=({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}),
        )
        try:
            with self._open(request, timeout=min(self.timeout, 15), context=verified_ssl_context()) as response:
                return 200 <= response.status < 300
        except urllib.error.HTTPError as exc:
            raise ProviderError(f"模型连接测试失败（HTTP {exc.code}）") from exc
        except (OSError, urllib.error.URLError) as exc:
            raise ProviderError(f"模型连接测试失败：{exc}") from exc

    def chat(self, messages: list[dict[str, str]], *, json_mode: bool = False) -> str:
        if self.api_key_required and not self.api_key:
            raise ProviderError("尚未配置 API Key")
        payload: dict[str, object] = {"model": self.model, "messages": messages, "stream": False}
        if json_mode:
            payload["response_format"] = {"type": "json_object"}
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {}) | {"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._open(request, timeout=self.timeout, context=verified_ssl_context()) as response:
                body = json.loads(response.read().decode("utf-8"))
            return str(body["choices"][0]["message"]["content"]).strip()
        except (OSError, urllib.error.URLError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise ProviderError(f"模型 API 调用失败：{exc}") from exc

    def stream_chat(self, messages: list[dict[str, str]]) -> Iterator[str]:
        if self.api_key_required and not self.api_key:
            raise ProviderError("尚未配置 API Key")
        payload = {"model": self.model, "messages": messages, "stream": True}
        request = urllib.request.Request(
            f"{self.base_url}/chat/completions",
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            headers=({"Authorization": f"Bearer {self.api_key}"} if self.api_key else {})
            | {"Content-Type": "application/json", "Accept": "text/event-stream"},
            method="POST",
        )
        try:
            with self._open(request, timeout=self.timeout, context=verified_ssl_context()) as response:
                for raw in response:
                    line = raw.decode("utf-8", errors="replace").strip()
                    if not line or line.startswith(":"):
                        continue
                    if line.startswith("data:"):
                        line = line[5:].strip()
                    if line == "[DONE]":
                        break
                    try:
                        item = json.loads(line)
                        content = item.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    except (json.JSONDecodeError, IndexError, AttributeError, TypeError):
                        continue
                    if content:
                        yield str(content)
        except (OSError, urllib.error.URLError) as exc:
            raise ProviderError(f"模型流式调用失败：{exc}") from exc


def build_provider(config: ProviderConfig) -> ChatProvider:
    if config.mode in {"local", "ollama"}:
        return OllamaClient(config.base_url, config.model)
    if config.mode == "local_openai":
        validate_local_url(config.base_url)
        return OpenAICompatibleClient(config.base_url, config.model, config.api_key, api_key_required=False)
    if config.mode == "custom_local_adapter":
        validate_local_url(config.base_url)
        if config.adapter_kind == "ollama":
            return OllamaClient(config.base_url, config.model)
        return OpenAICompatibleClient(config.base_url, config.model, config.api_key, api_key_required=False)
    if config.mode in {"cloud", "cloud_openai"}:
        if not config.cloud_data_consent:
            raise ProviderError("使用云端模型前必须确认数据传输范围")
        return OpenAICompatibleClient(config.base_url, config.model, config.api_key or load_api_key())
    raise ProviderError("不支持的模型运行模式")
