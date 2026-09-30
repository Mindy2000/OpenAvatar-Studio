from __future__ import annotations

import json
import time
from typing import Any

from openavatar.db import Database


LEVELS = ("required", "recommended", "advanced")


def _count(db: Database, sql: str, params: tuple[Any, ...]) -> int:
    row = db.one(sql, params) or {"count": 0}
    return int(row.get("count") or 0)


def _check(name: str, passed: bool, level: str, recommendation: str, *, value: Any = "") -> dict[str, Any]:
    return {
        "name": name,
        "passed": bool(passed),
        "level": level,
        "severity": level,
        "value": value,
        "recommendation": "" if passed else recommendation,
    }


def _normalize_check(item: dict[str, Any]) -> dict[str, Any]:
    level = str(item.get("level") or item.get("severity") or "recommended")
    if level not in LEVELS:
        level = "recommended"
    normalized = dict(item)
    normalized["level"] = level
    normalized["severity"] = str(normalized.get("severity") or level)
    normalized["passed"] = bool(normalized.get("passed"))
    normalized.setdefault("recommendation", "")
    normalized.setdefault("name", "未命名检查")
    return normalized


def route_text(db: Database, avatar_id: str) -> dict[str, int]:
    return {
        "conversation": _count(db, "SELECT COUNT(*) AS count FROM evidence WHERE avatar_id=? AND derived_kind IN ('conversation','speaking_style')", (avatar_id,)),
        "image_ocr": _count(db, "SELECT COUNT(*) AS count FROM evidence WHERE avatar_id=? AND derived_kind='image_ocr'", (avatar_id,)),
        "fictional": _count(db, "SELECT COUNT(*) AS count FROM evidence WHERE avatar_id=? AND source_type IN ('fictional_source','guided_builder')", (avatar_id,)),
    }


def completion_report(db: Database, avatar_id: str, extra_checks: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    avatar = db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,))
    if not avatar:
        raise KeyError("数字人不存在")
    subject_kind = str(avatar["subject_kind"])
    persona = db.one("SELECT * FROM persona_profiles WHERE avatar_id=?", (avatar_id,)) or {}
    text_counts = route_text(db, avatar_id)
    audio_count = _count(db, "SELECT COUNT(*) AS count FROM imports WHERE avatar_id=? AND category='audio'", (avatar_id,))
    confirmed_transcript = _count(db, "SELECT COUNT(*) AS count FROM voice_transcriptions WHERE avatar_id=? AND status='confirmed'", (avatar_id,))
    cloned_voice = _count(db, "SELECT COUNT(*) AS count FROM provider_assets WHERE avatar_id=? AND kind='voice' AND active=1", (avatar_id,))
    image_count = _count(db, "SELECT COUNT(*) AS count FROM imports WHERE avatar_id=? AND category='image'", (avatar_id,))
    canonical_visual = _count(db, "SELECT COUNT(*) AS count FROM visual_assets WHERE avatar_id=? AND status='canonical'", (avatar_id,))
    approved_identity_sets = _count(db, "SELECT COUNT(*) AS count FROM visual_asset_sets WHERE avatar_id=? AND set_type='identity' AND status IN ('approved','canonical')", (avatar_id,))
    canonical_visual = max(canonical_visual, _count(db, "SELECT COUNT(*) AS count FROM visual_asset_sets WHERE avatar_id=? AND set_type='identity' AND status='canonical'", (avatar_id,)))
    active_voice = _count(db, "SELECT COUNT(*) AS count FROM voice_profiles WHERE avatar_id=? AND active=1", (avatar_id,))
    world_facts = _count(db, "SELECT COUNT(*) AS count FROM world_facts WHERE avatar_id=? AND active=1", (avatar_id,))
    enabled_world_modules = _count(db, "SELECT COUNT(*) AS count FROM world_modules WHERE avatar_id=? AND enabled=1", (avatar_id,))
    answered_required_modules = _count(
        db,
        """
        SELECT COUNT(*) AS count FROM world_modules wm
        WHERE wm.avatar_id=? AND wm.required=1 AND EXISTS (
          SELECT 1 FROM builder_answers ba
          WHERE ba.avatar_id=wm.avatar_id AND ba.route='fictional_guided' AND ba.question_key=wm.module_key
        )
        """,
        (avatar_id,),
    )
    required_modules = _count(db, "SELECT COUNT(*) AS count FROM world_modules WHERE avatar_id=? AND required=1", (avatar_id,))
    model_settings = db.one("SELECT * FROM avatar_model_settings WHERE avatar_id=?", (avatar_id,))
    selected_connection = str(db.setting("selected_model_connection_id", "") or "")
    effective_connection = str((model_settings or {}).get("connection_id") or selected_connection)
    connection = db.one("SELECT * FROM model_connections WHERE id=?", (effective_connection,)) if effective_connection else None
    test_fresh = bool(connection and int(connection.get("last_tested_at") or 0) >= int(time.time()) - 7 * 86400)
    has_model_choice = bool(connection and connection.get("last_test_status") == "ok" and test_fresh)
    if not effective_connection:
        has_model_choice = bool(model_settings) or bool(db.setting("model", {}))
    checks: list[dict[str, Any]] = []
    if subject_kind == "fictional":
        document_covers_required = text_counts["fictional"] >= 4 and len(str(persona.get("summary", ""))) >= 20
        effective_required_answers = required_modules if document_covers_required else answered_required_modules
        checks.extend([
            _check("身份设定", text_counts["fictional"] > 0 and len(str(avatar["name"])) > 0, "required", "用问答或文档写出角色身份。"),
            _check("核心人格", len(str(persona.get("summary", ""))) >= 20 or text_counts["fictional"] >= 2, "required", "补充性格、动机和稳定的行为方式。"),
            _check("说话方式", len(str(persona.get("speaking_style", ""))) >= 10 or text_counts["fictional"] >= 3, "required", "补充语气、回复长度、常用表达和禁用表达。"),
            _check("边界规则", len(str(persona.get("boundaries", ""))) >= 8 or text_counts["fictional"] >= 4, "required", "写清楚不可改变的设定和运行边界。"),
            _check("必须世界模块", required_modules == 0 or effective_required_answers >= required_modules, "required", "完成身份、人格、表达和边界这些必须模块。", value=f"{effective_required_answers}/{required_modules}"),
            _check("模型设置", has_model_choice, "required", "选择这个数字人的 API 或本地模型。"),
            _check("里世界概览", world_facts >= 4, "recommended", "运行 Builder，将设定沉淀为可审批世界事实。", value=world_facts),
            _check("可运行世界模块", enabled_world_modules >= 8, "recommended", "选择地点、人物、时间线、资源、事件引擎等模块。", value=enabled_world_modules),
            _check("视觉身份素材包", image_count > 0 or approved_identity_sets > 0, "recommended", "上传候选图并整理为人物身份素材包。"),
            _check("声音方案", active_voice > 0, "recommended", "选择本地音色、API 音色或暂不启用。"),
            _check("世界事件推进", _count(db, "SELECT COUNT(*) AS count FROM world_events WHERE avatar_id=?", (avatar_id,)) > 0, "advanced", "启用世界运行设置，让事件默认先进入审批。"),
            _check("canonical 视觉身份", canonical_visual > 0, "advanced", "锁定正式视觉身份参考。"),
        ])
    else:
        text_ready = text_counts["conversation"] > 0 or text_counts["image_ocr"] > 0
        checks.extend([
            _check("文本人格素材", text_ready, "required", "必须有文字或聊天记录中的至少一种；音频只能提供音色，不能单独构建人格。", value=text_counts),
            _check("声音样本", audio_count > 0, "required", "真实素材路线需要音频来构建声音。", value=audio_count),
            _check("基础身份", len(str(avatar["name"])) > 0 and len(str(avatar["relationship"])) > 0, "required", "填写名字、关系和用途。"),
            _check("模型设置", has_model_choice, "required", "为这个数字人选择 API 或本地模型。"),
            _check("人格档案", len(str(persona.get("summary", ""))) >= 30, "recommended", "运行分析或手动补充人物简介。"),
            _check("声音转写确认", confirmed_transcript > 0, "recommended", "确认音频转写，让声音素材也贡献表达样本。"),
            _check("视觉素材包", image_count > 0 or approved_identity_sets > 0, "recommended", "上传照片或截图并整理为真实视觉身份素材包。"),
            _check("声音复刻档案", cloned_voice > 0, "advanced", "完成声音复刻或登记可用声音档案。"),
            _check("canonical 视觉身份", canonical_visual > 0, "advanced", "审批并锁定真实身份视觉参考。"),
            _check("长期记忆规模", _count(db, "SELECT COUNT(*) AS count FROM memories WHERE avatar_id=?", (avatar_id,)) >= 40, "advanced", "导入更多聊天记录，提高长期记忆和表达稳定性。"),
        ])
    if extra_checks:
        checks.extend(_normalize_check(item) for item in extra_checks)
    groups = {}
    for level in LEVELS:
        items = [item for item in checks if item["level"] == level]
        passed = sum(1 for item in items if item["passed"])
        groups[level] = {
            "total": len(items),
            "passed": passed,
            "complete": passed == len(items) if items else True,
        }
    weights = {"required": 0.6, "recommended": 0.3, "advanced": 0.1}
    score = round(sum(
        (groups[level]["passed"] / groups[level]["total"] if groups[level]["total"] else 1) * weight * 100
        for level, weight in weights.items()
    ))
    required_complete = bool(groups["required"]["complete"])
    usage_mode = "official" if required_complete else "preview"
    return {
        "score": score,
        "checks": checks,
        "groups": groups,
        "ready": required_complete,
        "can_start_official": required_complete,
        "preview_allowed": True,
        "usage_mode": usage_mode,
        "route": "fictional" if subject_kind == "fictional" else "real",
        "summary": {
            "required": f"{groups['required']['passed']}/{groups['required']['total']}",
            "recommended": f"{groups['recommended']['passed']}/{groups['recommended']['total']}",
            "advanced": f"{groups['advanced']['passed']}/{groups['advanced']['total']}",
        },
    }
