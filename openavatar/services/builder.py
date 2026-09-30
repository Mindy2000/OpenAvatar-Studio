from __future__ import annotations

import json
import re
import time
from typing import Any

from openavatar.db import Database
from openavatar.services.guided_builder import ensure_modules
from openavatar.services.readiness import completion_report
from openavatar.services.voice import ensure_voice_choices
from openavatar.services.world_model import propose_fact


REQUIRED_SECTIONS = {
    "身份": ("身份", "identity"),
    "核心性格": ("核心性格", "性格", "人格", "persona", "traits"),
    "说话风格": ("说话风格", "表达", "style", "speaking", "speaking_style"),
    "世界模型": ("世界模型", "世界", "world", "world_model"),
    "视觉身份": ("视觉身份", "外貌", "visual", "visual_identity"),
    "声音设定": ("声音设定", "声音", "voice"),
    "边界与禁止事项": ("边界", "禁止", "规则", "boundaries", "source_policy"),
}


def _safe_json(value: str, fallback: Any) -> Any:
    try:
        return json.loads(value)
    except (json.JSONDecodeError, TypeError):
        return fallback


def _section_titles(text: str) -> set[str]:
    titles = {match.group(1).strip().lower() for match in re.finditer(r"^#{1,6}\s+(.+)$", text, flags=re.M)}
    titles.update(match.group(1).strip().lower() for match in re.finditer(r"^([a-zA-Z_][\w_-]*):\s*$", text, flags=re.M))
    return titles


def _has_any(titles: set[str], keywords: tuple[str, ...]) -> bool:
    return any(any(keyword.lower() in title for keyword in keywords) for title in titles)


def checks_for_fictional_source(text: str) -> list[dict[str, Any]]:
    titles = _section_titles(text)
    checks: list[dict[str, Any]] = []
    for label, keywords in REQUIRED_SECTIONS.items():
        passed = _has_any(titles, keywords)
        checks.append({
            "name": label,
            "passed": passed,
            "level": "required" if label in {"身份", "核心性格", "边界与禁止事项"} else "recommended",
            "severity": "required" if label in {"身份", "核心性格", "边界与禁止事项"} else "recommended",
            "recommendation": "" if passed else f"补充“{label}”章节，避免角色在运行时临时编造。",
        })
    lower = text.lower()
    original_markers = ("原创", "虚构", "不对应", "不复刻", "fictional", "original")
    checks.append({
        "name": "原创/非真人声明",
        "passed": any(marker in lower for marker in original_markers),
        "level": "required",
        "severity": "required",
        "recommendation": "明确写明角色完全原创，不对应、不复刻、不暗示现实特定个人。",
    })
    if re.search(r"\b(1[0-7]|[0-9])\s*岁\b", text):
        checks.append({
            "name": "未成年人风险",
            "passed": False,
            "level": "required",
            "severity": "required",
            "recommendation": "如果角色为未成年人，必须强化非性化边界和内容限制。",
        })
    else:
        checks.append({"name": "年龄边界", "passed": True, "level": "recommended", "severity": "recommended", "recommendation": ""})
    return checks


def checks_for_avatar(db: Database, avatar_id: str) -> dict[str, Any]:
    avatar = db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,))
    if not avatar:
        raise KeyError("数字人不存在")
    evidence = db.all("SELECT * FROM evidence WHERE avatar_id=? ORDER BY id", (avatar_id,))
    imports = db.all("SELECT * FROM imports WHERE avatar_id=? ORDER BY id", (avatar_id,))
    persona = db.one("SELECT * FROM persona_profiles WHERE avatar_id=?", (avatar_id,)) or {}
    subject_kind = str(avatar.get("subject_kind"))
    checks: list[dict[str, Any]] = []
    if subject_kind == "fictional":
        ensure_modules(db, avatar_id)
        source_text = "\n\n".join(
            f"## {row['title']}\n{row['content']}" for row in evidence if row["source_type"] in {"fictional_source", "guided_builder"}
        )[:120000]
        checks.extend(checks_for_fictional_source(source_text) if source_text else [{
            "name": "虚构设定文件",
            "passed": False,
            "severity": "required",
            "recommendation": "上传 avatar.md 或 character.yaml，先建立原创设定证据。",
        }])
        checks.append({
            "name": "世界事实",
            "passed": bool(db.one("SELECT id FROM world_facts WHERE avatar_id=? AND active=1", (avatar_id,))),
            "level": "recommended",
            "severity": "recommended",
            "recommendation": "运行统一 Builder，将世界设定沉淀为 world_facts。",
        })
        checks.append({
            "name": "视觉审批骨架",
            "passed": bool(db.one("SELECT id FROM visual_asset_sets WHERE avatar_id=? AND set_type='identity'", (avatar_id,))) or bool(db.one("SELECT id FROM visual_assets WHERE avatar_id=?", (avatar_id,))),
            "level": "recommended",
            "severity": "recommended",
            "recommendation": "至少登记一个视觉 identity candidate 或文字视觉设定。",
        })
        checks.append({
            "name": "声音选择",
            "passed": bool(db.one("SELECT id FROM voice_profiles WHERE avatar_id=?", (avatar_id,))),
            "level": "recommended",
            "severity": "recommended",
            "recommendation": "选择 provider 内置音色、本地 TTS、API TTS 或其他声音方式。",
        })
    else:
        categories = {row["category"] for row in imports}
        confirmed_transcript = bool(db.one("SELECT id FROM voice_transcriptions WHERE avatar_id=? AND status='confirmed'", (avatar_id,)))
        cloned_voice = bool(db.one("SELECT id FROM provider_assets WHERE avatar_id=? AND kind='voice' AND active=1", (avatar_id,)))
        canonical_visual = bool(db.one("SELECT id FROM visual_asset_sets WHERE avatar_id=? AND set_type='identity' AND status='canonical'", (avatar_id,))) or bool(db.one("SELECT id FROM visual_assets WHERE avatar_id=? AND status='canonical'", (avatar_id,)))
        checks.extend([
            {"name": "聊天记录", "passed": "conversation" in categories, "level": "recommended", "severity": "recommended", "recommendation": "导入并确认聊天记录以学习表达和关系记忆。"},
            {"name": "声音样本", "passed": "audio" in categories, "level": "required", "severity": "required", "recommendation": "真实多模态数字人需要上传清晰单人声音样本。"},
            {"name": "声音转写确认", "passed": confirmed_transcript, "level": "recommended", "severity": "recommended", "recommendation": "确认 ASR 或人工转写，让声音样本也进入表达证据。"},
            {"name": "声音复刻档案", "passed": cloned_voice, "level": "advanced", "severity": "advanced", "recommendation": "真实素材路线以声音复刻为核心；请完成复刻或登记可用声音档案。"},
            {"name": "形象素材", "passed": "image" in categories, "level": "recommended", "severity": "recommended", "recommendation": "上传授权照片或截图；照片会作为视觉素材证据。"},
            {"name": "canonical 视觉身份", "passed": canonical_visual, "level": "advanced", "severity": "advanced", "recommendation": "批准并锁定一张 canonical 视觉身份参考。"},
            {"name": "授权记录", "passed": bool(db.one("SELECT id FROM rights_grants WHERE avatar_id=?", (avatar_id,))), "level": "required", "severity": "required", "recommendation": "真实素材应记录来源、授权范围和可撤销性。"},
        ])
    checks.append({
        "name": "人格档案",
        "passed": len(str(persona.get("summary", ""))) >= 30,
        "level": "recommended",
        "severity": "recommended",
        "recommendation": "运行分析或手动补充人物摘要。",
    })
    return completion_report(db, avatar_id, checks)


def run_builder(db: Database, avatar_id: str) -> dict[str, Any]:
    avatar = db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,))
    if not avatar:
        raise KeyError("数字人不存在")
    now = int(time.time())
    evidence = db.all("SELECT * FROM evidence WHERE avatar_id=? ORDER BY id", (avatar_id,))
    fictional = str(avatar.get("subject_kind")) == "fictional"
    world_sources = [row for row in evidence if row["derived_kind"] in {"world", "source", "persona", "boundary", "guided_setting"}]
    persona = db.one("SELECT * FROM persona_profiles WHERE avatar_id=?", (avatar_id,)) or {}
    pending_world_proposals: list[tuple[str, dict[str, Any], int]] = []
    with db.transaction() as connection:
        if fictional and world_sources:
            seed_facts = [
                ("identity.display_name", avatar["name"], "fictional_canon", "approval_only"),
                ("world.time_rule", "runtime_only", "fictional_canon", "approval_only"),
                ("governance.unapproved_events_are_proposals", True, "fictional_canon", "locked"),
                ("governance.virtual_world_not_real_news", True, "fictional_canon", "locked"),
                ("persona.summary", str(persona.get("summary", "")), "fictional_canon", "approval_only"),
                ("persona.boundaries", str(persona.get("boundaries", "")), "fictional_canon", "locked"),
            ]
            for key, value, reality, mutability in seed_facts:
                connection.execute("DELETE FROM world_facts WHERE avatar_id=? AND fact_key=?", (avatar_id, key))
                connection.execute(
                    "INSERT INTO world_facts(avatar_id,fact_key,fact_value_json,reality_kind,mutability,status,confidence,active,created_at,updated_at) VALUES(?,?,?,?,?,'fact',1,1,?,?)",
                    (avatar_id, key, json.dumps(value, ensure_ascii=False), reality, mutability, now, now),
                )
            connection.execute(
                "INSERT INTO world_events(avatar_id,event_key,title,summary,event_kind,status,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
                (
                    avatar_id,
                    f"builder_seed_{now}",
                    "世界模型初始化",
                    "Builder 根据虚构设定创建第一批世界治理事实；后续事件默认先进入 proposal。",
                    "system",
                    "fact",
                    json.dumps({"source": "openavatar-builder-v1"}, ensure_ascii=False),
                    now,
                ),
            )
            for row in world_sources[:30]:
                title = str(row["title"] or row["derived_kind"] or "source").strip()
                content = str(row["content"] or "").strip()
                if not content:
                    continue
                key = "source." + re.sub(r"[^a-zA-Z0-9_\u4e00-\u9fff.-]+", "_", title).strip("_")[:80]
                pending_world_proposals.append((key, {"title": title, "content": content[:4000]}, int(row["id"])))
        if fictional and not db.one("SELECT id FROM visual_assets WHERE avatar_id=?", (avatar_id,)):
            visual_text = "\n\n".join(row["content"] for row in evidence if row["derived_kind"] in {"visual", "source"})[:20000]
            connection.execute(
                "INSERT INTO visual_assets(avatar_id,asset_kind,status,label,metadata_json,created_at) VALUES(?,?,?,?,?,?)",
                (
                    avatar_id,
                    "identity",
                    "candidate",
                    "文字视觉设定候选",
                    json.dumps({"description": visual_text, "workflow": ["draft", "candidate", "approved", "canonical", "retired"]}, ensure_ascii=False),
                    now,
                ),
            )
        if not fictional and not db.one("SELECT id FROM rights_grants WHERE avatar_id=?", (avatar_id,)):
            connection.execute(
                "INSERT INTO rights_grants(avatar_id,grant_type,subject_kind,rights_scope,data_classes_json,provider_transfer_allowed,commercial_use_allowed,revocable,note,confirmed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                (
                    avatar_id,
                    "self_attested",
                    str(avatar["subject_kind"]),
                    "local_avatar_build",
                    json.dumps(["conversation", "image", "audio"], ensure_ascii=False),
                    0,
                    0,
                    1,
                    "创建时用户确认拥有资料使用权；云端传输仍需单独确认。",
                    now,
                ),
            )
    for key, value, source_evidence_id in pending_world_proposals:
        propose_fact(
            db,
            avatar_id,
            fact_key=key,
            value=value,
            reality_kind="fictional_canon",
            mutability="approval_only",
            reason="Builder 从设定证据提取，进入人工审批队列",
            source_evidence_id=source_evidence_id,
        )
    if fictional:
        ensure_modules(db, avatar_id)
        ensure_voice_choices(db, avatar_id)
        db.execute(
            "INSERT OR IGNORE INTO world_runtime_settings(avatar_id,updated_at) VALUES(?,?)",
            (avatar_id, now),
        )
        enabled_modules = db.all("SELECT module_key,module_name,category FROM world_modules WHERE avatar_id=? AND enabled=1 ORDER BY category,id", (avatar_id,))
        for row in enabled_modules:
            propose_fact(
                db,
                avatar_id,
                fact_key=f"module.{row['module_key']}",
                value={"name": row["module_name"], "category": row["category"], "enabled": True},
                reality_kind="fictional_canon",
                mutability="approval_only" if str(row["module_key"]) in {"rules", "boundaries", "event_engine"} else "evolving",
                reason="Builder 记录用户启用的里世界模块",
            )
    report = checks_for_avatar(db, avatar_id)
    db.execute(
        "INSERT INTO build_reports(avatar_id,report_kind,status,score,checks_json,recommendations_json,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            avatar_id,
            "builder_v1",
            "completed",
            report["score"],
            json.dumps(report["checks"], ensure_ascii=False),
            json.dumps([item["recommendation"] for item in report["checks"] if item.get("recommendation")], ensure_ascii=False),
            now,
        ),
    )
    return report
