"""Per-call estimates and sentence boundaries; never a provider billing guarantee."""
from __future__ import annotations

import math
import re
import time
import json
from dataclasses import dataclass, field
from typing import Callable
from pathlib import Path

from openavatar.providers import ProviderError, load_provider_key
from openavatar.services.provider_hub import assert_allowed, connection_row, estimate_provider_cost, route_candidates, provider_key_name


class CallLimit(ProviderError):
    def __init__(self, reason: str, message: str):
        super().__init__(message)
        self.reason = reason


@dataclass(frozen=True)
class CallLimits:
    max_minutes: float = 10
    estimated_budget_cny: float = 5

    @classmethod
    def parse(cls, minutes=10, budget=5) -> "CallLimits":
        try:
            duration, amount = float(minutes), float(budget)
        except (TypeError, ValueError):
            raise ProviderError("通话时长和本次估算额度必须是数字") from None
        if isinstance(minutes, bool) or not math.isfinite(duration) or not 1 <= duration <= 120:
            raise ProviderError("通话时长须在1至120分钟之间")
        if isinstance(budget, bool) or not math.isfinite(amount) or not 0.01 <= amount <= 1000:
            raise ProviderError("本次估算额度须在0.01至1000元之间")
        return cls(duration, amount)


@dataclass
class CallPolicy:
    limits: CallLimits
    clock: Callable[[], float] = time.monotonic
    started: float = field(init=False)
    estimated_reserved_cny: float = 0
    active: bool = True
    reason: str = "user_ended"

    def __post_init__(self):
        self.started = self.clock()

    def check(self) -> None:
        if not self.active:
            raise CallLimit(self.reason, "通话已结束")
        if self.clock() - self.started >= self.limits.max_minutes * 60:
            raise CallLimit("time_limit", "已达到设定时长，本次通话结束。")

    def check_estimate(self, amount: float) -> None:
        self.check()
        if not math.isfinite(amount) or amount < 0:
            raise ProviderError("通话费用估算无效")
        if self.estimated_reserved_cny + amount > self.limits.estimated_budget_cny + 1e-10:
            raise CallLimit("budget_limit", "本次剩余估算额度不足以发起下一请求，通话已结束。")

    def reserve(self, amount: float) -> None:
        self.check_estimate(amount)
        # A failed or interrupted request may still be billed. Never release a
        # reservation merely because its response did not reach the browser.
        self.estimated_reserved_cny = round(self.estimated_reserved_cny + amount, 10)

    def snapshot(self) -> dict:
        remaining = max(0, self.limits.max_minutes * 60 - (self.clock() - self.started))
        return {
            "max_minutes": self.limits.max_minutes,
            "estimated_budget_cny": self.limits.estimated_budget_cny,
            "estimated_reserved_cny": self.estimated_reserved_cny,
            "remaining_seconds": round(remaining, 1),
            "budget_warning": self.estimated_reserved_cny >= self.limits.estimated_budget_cny * .8,
            "time_warning": remaining <= min(60, self.limits.max_minutes * 12),
        }


def call_cost(row: dict, capability: str, *, input_units: int, output_units: int = 0) -> float:
    """Unknown cloud prices must not silently disable a per-call budget."""
    cost = estimate_provider_cost(row, capability, input_units=input_units, output_units=output_units)
    if cost <= 0 and row.get("provider_kind") != "local":
        raise ProviderError(f"请先在服务连接的高级配置中填写 {capability} 的人民币单次估价，再使用语音通话")
    return cost


class SentenceSegments:
    """Emit at most two early complete sentences, then one remaining segment."""
    def __init__(self):
        self.buffer = ""
        self.characters = 0
        self.count = 0

    def push(self, text: str, *, final: bool = False) -> list[str]:
        text = text[:max(0, 80 - self.characters)]
        self.characters += len(text)
        self.buffer += text
        result = []
        while self.count < 2:
            # A streaming chunk is not a sentence boundary: "1." can be
            # followed by "5". Only the final flush can trust end-of-buffer.
            period = r"\.(?=\s|$)" if final else r"\.(?=\s)"
            boundary = re.search(r"[。！？!?；;\n]|" + period, self.buffer)
            if not boundary:
                break
            value, self.buffer = self.buffer[:boundary.end()], self.buffer[boundary.end():]
            if value.strip():
                result.append(value)
                self.count += 1
        if final and self.buffer.strip() and self.count < 3:
            result.append(self.buffer)
            self.count += 1
            self.buffer = ""
        return result


def select_call_chat(prepared: dict) -> tuple:
    """Use one configured model, with no automatic retry/failover in calls."""
    from openavatar.services.model_connections import FailoverChatProvider, MeteredChatProvider

    client = prepared["client"]
    if isinstance(client, FailoverChatProvider):
        client = client.providers[0]
    row = client.row if isinstance(client, MeteredChatProvider) else None
    if row:
        cost = call_cost(row, "chat", input_units=sum(len(str(m.get("content", ""))) for m in prepared["messages"]), output_units=80)
        # The call reserves and records one conservative estimate itself, even
        # if an interrupted generator never reaches its normal accounting code.
        return client.provider, row, cost
    if prepared["config"].mode in {"cloud", "cloud_openai"}:
        raise ProviderError("请先在服务连接中配置聊天能力路由和人民币估价，再使用语音通话")
    return client, None, 0.0


def select_call_voice(db, avatar_id: str) -> dict:
    selected = db.one("SELECT * FROM voice_profiles WHERE avatar_id=? AND active=1 ORDER BY id DESC LIMIT 1", (avatar_id,))
    if selected and selected["profile_kind"] == "none":
        raise ProviderError("当前人物已关闭声音")
    if selected and selected["status"] != "approved":
        raise ProviderError("请先批准当前人物的音色")
    builtin = bool(selected and selected["provider"] == "minimax" and selected["profile_kind"] == "builtin_tts")
    profile = {"external_id": selected["voice_id"], "provider": "minimax"} if builtin else db.one(
        "SELECT * FROM provider_assets WHERE avatar_id=? AND kind='voice' AND active=1 ORDER BY id DESC LIMIT 1", (avatar_id,))
    if not profile or not profile.get("external_id"):
        raise ProviderError("请先选择音色或完成声音复刻")
    candidates = route_candidates(db, "tts", avatar_id)
    if not candidates:
        raise ProviderError("请先配置已授权且未超预算的语音合成路由")
    row, model, config = candidates[0]
    owner = str(profile["provider"])
    # Modern clone assets belong to a specific connection/account. Older
    # records only stored the provider kind; presets are vendor-wide voices.
    matches = str(row["id"]) == owner if owner not in {"minimax", "aliyun"} else row["provider_kind"] == owner
    if row["provider_kind"] not in {"minimax", "aliyun"} or not matches:
        raise ProviderError("语音合成路由与当前音色不匹配，请检查设置；通话不会自动换声")
    model = model or ("speech-2.8-hd" if row["provider_kind"] == "minimax" else "qwen3-tts-vc-2026-01-22")
    return {"row": row, "model": model, "config": config, "voice_id": str(profile["external_id"])}


def maximum_call_speech_cost(plan: dict) -> float:
    """80 total characters in up to three requests (including per-call prices)."""
    row = plan["row"]
    return max(sum(call_cost(row, "tts", input_units=size) for size in sizes)
               for sizes in ((80,), (1, 79), (1, 1, 78)))


def refresh_call_voice(db, plan: dict) -> None:
    """Re-read consent, prices and budgets without rerouting or changing voice."""
    row = connection_row(db, str(plan["row"]["id"]))
    if not row:
        raise ProviderError("当前语音连接已删除，请重新配置后再开始通话")
    if any(row.get(key) != plan["row"].get(key) for key in ("provider_kind", "base_url")):
        raise ProviderError("当前语音连接地址或类型已改变，请重新开始通话")
    plan["row"] = row


def preflight_call_voice(db, avatar_id: str) -> dict:
    """Only local configuration/credentials checks, never a provider request."""
    plan = select_call_voice(db, avatar_id)
    assert_allowed(db, plan["row"], "tts", upcoming_cost=maximum_call_speech_cost(plan))
    if not load_provider_key(provider_key_name(str(plan["row"]["id"]))):
        raise ProviderError("语音合成连接尚未保存 API Key，请先完成配置")
    return plan


def synthesize_call_segment(plan: dict, text: str, target: Path) -> str:
    """Exactly one synthesis attempt with the preselected connection and voice."""
    from openavatar.services.aliyun import AliyunAvatarClient, extract_urls, download_provider_asset
    from openavatar.services.minimax import MiniMaxClient, write_audio_result

    row = plan["row"]
    key = load_provider_key(provider_key_name(str(row["id"])))
    if row["provider_kind"] == "minimax":
        config = json.loads(row.get("config_json") or "{}")
        client = MiniMaxClient(key, str(row["base_url"]), endpoints=config.get("endpoints", {}))
        result = client.synthesize(text, voice_id=plan["voice_id"], model=plan["model"], config=plan["config"])
        return write_audio_result(result, target)
    result = AliyunAvatarClient(key).synthesize(text, voice_id=plan["voice_id"], model=plan["model"])
    urls = extract_urls(result.get("output", {}))
    if not urls:
        raise ProviderError("语音接口没有返回可下载的音频")
    return download_provider_asset(urls[0], target, max_bytes=30 * 1024 * 1024) or "audio/mpeg"
