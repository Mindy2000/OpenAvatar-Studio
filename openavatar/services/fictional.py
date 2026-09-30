from __future__ import annotations

import json
import re
from typing import Any


FICTIONAL_EXTENSIONS = {".md", ".markdown", ".txt", ".json", ".yaml", ".yml"}


def _clean(value: object, limit: int = 10000) -> str:
    return str(value or "").strip()[:limit]


def _listify(value: object) -> list[str]:
    if isinstance(value, list):
        return [_clean(item, 500) for item in value if _clean(item)]
    if isinstance(value, str):
        return [line.strip("-* \t") for line in value.splitlines() if line.strip("-* \t")]
    return []


def _json_profile(payload: dict[str, Any], avatar_name: str) -> dict[str, Any]:
    persona = payload.get("persona") if isinstance(payload.get("persona"), dict) else payload
    style = payload.get("style") if isinstance(payload.get("style"), dict) else {}
    world = payload.get("world") if isinstance(payload.get("world"), dict) else {}
    visual = payload.get("visual") if isinstance(payload.get("visual"), dict) else {}
    voice = payload.get("voice") if isinstance(payload.get("voice"), dict) else {}
    name = _clean(persona.get("name") or payload.get("name") or avatar_name, 80)
    traits = _listify(persona.get("traits") or persona.get("personality") or payload.get("traits"))[:12]
    summary = _clean(
        persona.get("summary")
        or persona.get("identity")
        or payload.get("summary")
        or f"{name} 是由设定文件创建的原创虚构数字人。"
    )
    speaking_style = _clean(style.get("speaking_style") or style.get("summary") or payload.get("speaking_style"))
    boundaries = _clean(persona.get("boundaries") or payload.get("boundaries") or persona.get("rules"))
    evidence = []
    for title, value, kind in [
        ("人格设定", persona, "persona"),
        ("说话风格", style, "style"),
        ("世界设定", world, "world"),
        ("视觉设定", visual, "visual"),
        ("声音设定", voice, "voice"),
    ]:
        if value:
            evidence.append({"title": title, "content": json.dumps(value, ensure_ascii=False, indent=2), "kind": kind})
    return {
        "name": name,
        "summary": summary,
        "traits": traits or ["原创虚构人物，等待继续细化"],
        "speaking_style": speaking_style or "使用自然、稳定且符合设定的表达方式；资料不足时不临时编造。",
        "boundaries": boundaries or "这是原创虚构人物，不对应、不复刻也不暗示任何现实中的特定个人；不把未设定事实冒充既有经历。",
        "evidence": evidence,
    }


def _markdown_sections(text: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {"全文": []}
    current = "全文"
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        match = re.match(r"^#{1,6}\s+(.+)$", line)
        if match:
            current = match.group(1).strip()
            sections.setdefault(current, [])
            continue
        sections.setdefault(current, []).append(line)
    return sections


def _section_text(sections: dict[str, list[str]], keywords: tuple[str, ...]) -> str:
    values = []
    for title, lines in sections.items():
        haystack = title.lower()
        if any(keyword.lower() in haystack for keyword in keywords):
            values.extend(lines)
    return "\n".join(values).strip()


def _bullets(text: str, limit: int = 12) -> list[str]:
    items = []
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith(("- ", "* ")):
            items.append(line[2:].strip())
        elif re.match(r"^\d+[.)、]\s+", line):
            items.append(re.sub(r"^\d+[.)、]\s+", "", line).strip())
        if len(items) >= limit:
            break
    return [item for item in items if item]


def parse_fictional_source(text: str, avatar_name: str, filename: str = "") -> dict[str, Any]:
    stripped = text.strip()
    if not stripped:
        raise ValueError("设定文件为空")
    if filename.lower().endswith(".json") or stripped.startswith("{"):
        payload = json.loads(stripped)
        if not isinstance(payload, dict):
            raise ValueError("JSON 设定文件必须是对象")
        return _json_profile(payload, avatar_name)

    sections = _markdown_sections(stripped)
    identity = _section_text(sections, ("身份", "identity", "基本", "profile", "角色"))
    personality = _section_text(sections, ("性格", "人格", "personality", "traits", "核心"))
    style = _section_text(sections, ("风格", "说话", "表达", "style", "口吻"))
    boundaries = _section_text(sections, ("边界", "规则", "禁止", "不变", "安全", "boundary", "rules"))
    world = _section_text(sections, ("世界", "生活", "背景", "world", "canon"))
    summary_source = identity or next(("\n".join(lines) for title, lines in sections.items() if lines), "")
    traits = _bullets(personality)[:12]
    if not traits and personality:
        traits = [line.strip("-* \t") for line in personality.splitlines()[:6] if line.strip("-* \t")]
    evidence = []
    for title, content, kind in [
        ("身份设定", identity, "persona"),
        ("核心性格", personality, "persona"),
        ("说话风格", style, "style"),
        ("世界背景", world, "world"),
        ("边界规则", boundaries, "boundary"),
    ]:
        if content:
            evidence.append({"title": title, "content": content, "kind": kind})
    if not evidence:
        evidence.append({"title": "设定全文", "content": stripped[:30000], "kind": "source"})
    return {
        "name": avatar_name,
        "summary": (summary_source or f"{avatar_name} 是由设定文件创建的原创虚构数字人。")[:4000],
        "traits": traits or ["原创虚构人物，等待继续细化"],
        "speaking_style": (style or "使用自然、稳定且符合设定的表达方式；资料不足时不临时编造。")[:4000],
        "boundaries": (boundaries or "这是原创虚构人物，不对应、不复刻也不暗示任何现实中的特定个人；不把未设定事实冒充既有经历。")[:4000],
        "evidence": evidence,
    }
