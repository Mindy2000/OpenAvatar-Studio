from __future__ import annotations

import json
import re
import statistics
from collections import Counter
from typing import Any

from openavatar.local_model import LocalModelError
from openavatar.providers import ChatProvider, ProviderError


FILLERS = ("哈哈", "嘿嘿", "嗯", "啊", "啦", "嘛", "呢", "呀", "哦", "吧")


def heuristic_profile(rows: list[dict[str, Any]], avatar_name: str) -> dict[str, Any]:
    contents = [str(row.get("content", "")).strip() for row in rows if str(row.get("content", "")).strip()]
    joined = "\n".join(contents)
    average = round(sum(len(item) for item in contents) / max(1, len(contents)), 1)
    fillers = [word for word, count in Counter(word for word in FILLERS for _ in range(joined.count(word))).most_common(5) if count]
    traits = []
    if any(mark in joined for mark in ("哈哈", "笑死", "hhh")):
        traits.append("幽默、容易接住玩笑")
    if joined.count("？") + joined.count("?") > max(2, len(contents) // 5):
        traits.append("喜欢追问、对话参与感强")
    if average < 18:
        traits.append("回复简短直接")
    elif average > 55:
        traits.append("表达详细、有叙述欲")
    if not traits:
        traits.append("自然、克制，等待更多资料后再细化")
    style = f"平均每条约 {average} 个字符。"
    if fillers:
        style += " 常见口头语：" + "、".join(fillers) + "。"
    return {
        "summary": f"{avatar_name} 的本地初步档案，由 {len(contents)} 条可读资料归纳。资料不足之处不主动编造。",
        "traits": traits,
        "speaking_style": style,
        "boundaries": "不冒充真人进行欺诈；不声称拥有资料中没有的共同经历；不使用未获授权的身份、声音或肖像。",
        "source_count": len(contents),
        "method": "local_heuristic",
    }


def build_profile(rows: list[dict[str, Any]], avatar_name: str, client: ChatProvider | None) -> dict[str, Any]:
    fallback = heuristic_profile(rows, avatar_name)
    if not client or not client.available() or not rows:
        return fallback
    sample = "\n".join(f"{row.get('speaker', '')}: {row.get('content', '')}" for row in rows[:400])[:30000]
    prompt = f"""你是本地运行的人格资料整理器。只根据给定材料分析数字人“{avatar_name}”，不要编造事实。
返回严格 JSON，字段为 summary（字符串）、traits（字符串数组）、speaking_style（字符串）、boundaries（字符串）。
材料：
{sample}
"""
    try:
        raw = client.chat([{"role": "user", "content": prompt}], json_mode=True)
        parsed = json.loads(raw)
        return {
            "summary": str(parsed.get("summary", fallback["summary"])),
            "traits": [str(item) for item in parsed.get("traits", fallback["traits"])][:12],
            "speaking_style": str(parsed.get("speaking_style", fallback["speaking_style"])),
            "boundaries": str(parsed.get("boundaries", fallback["boundaries"])),
            "source_count": len(rows),
            "method": "model_assisted",
        }
    except (LocalModelError, ProviderError, json.JSONDecodeError, TypeError):
        return fallback


def relevant_memories(rows: list[dict[str, Any]], query: str, limit: int = 12) -> list[dict[str, Any]]:
    tokens = set(re.findall(r"[\w\u4e00-\u9fff]{2,}", query.lower()))
    scored = []
    for row in rows:
        content = str(row.get("content", ""))
        score = sum(1 for token in tokens if token in content.lower())
        if score:
            scored.append((score, row))
    return [row for _, row in sorted(scored, key=lambda item: item[0], reverse=True)[:limit]] or rows[:limit]


def style_signature(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Measure response shape from authorized avatar utterances.

    Migrated from the legacy project's per-person style sampler. This learns
    length, punctuation and fragmentation, never facts from the examples.
    """
    texts = [str(row.get("content", "")).strip() for row in rows if row.get("is_avatar") and str(row.get("content", "")).strip()]
    texts = [text for text in texts if 1 < len(text) <= 200]
    if not texts:
        return {"sample_count": 0, "median_chars": 12, "short_rate": 0.55, "question_rate": 0.25, "fragment_rate": 0.2}
    lengths = [len(text.replace("\n", "")) for text in texts]
    return {
        "sample_count": len(texts),
        "median_chars": max(2, min(80, round(statistics.median(lengths)))),
        "short_rate": round(sum(length <= 12 for length in lengths) / len(lengths), 2),
        "question_rate": round(sum("?" in text or "？" in text for text in texts) / len(texts), 2),
        "fragment_rate": round(sum(not re.search(r"[。！？!?]$", text) for text in texts) / len(texts), 2),
    }
