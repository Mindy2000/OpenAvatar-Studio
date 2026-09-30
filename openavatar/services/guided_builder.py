from __future__ import annotations

import json
import time
from typing import Any

from openavatar.db import Database
from openavatar.services.world_model import propose_fact
from openavatar.services.world_regions import avatar_language_profile


FICTIONAL_MODULES = [
    {
        "key": "identity",
        "category": "人物核心",
        "required": True,
        "description": "角色的基础身份和存在感。",
        "title": "TA 是谁？",
        "prompt": "用几句话介绍这个原创人物的名字、年龄感、身份和最核心的存在感。",
        "fact_key": "identity.guided_profile",
        "module": "人物核心",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "personality",
        "category": "人物核心",
        "required": True,
        "description": "稳定人格、动机和行为模式。",
        "title": "TA 的性格是什么样？",
        "prompt": "写 3 到 6 个性格关键词，也可以补充 TA 在亲近/陌生人面前的不同表现。",
        "fact_key": "persona.guided_personality",
        "module": "人物核心",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "speaking_style",
        "category": "人物核心",
        "required": True,
        "description": "对话时的语言节奏、情绪和禁用表达。",
        "title": "TA 怎么说话？",
        "prompt": "描述 TA 的语气、句子长短、常用表达、禁用表达，以及像不像即时聊天。",
        "fact_key": "persona.guided_speaking_style",
        "module": "表达方式",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "boundaries",
        "category": "治理",
        "required": True,
        "description": "不能被运行时随意改写的设定和边界。",
        "title": "哪些内容不能被改变？",
        "prompt": "写原创声明、非真人声明、禁止编造事实、关系边界、安全边界。",
        "fact_key": "governance.guided_boundaries",
        "module": "边界",
        "reality_kind": "fictional_canon",
        "mutability": "locked",
    },
    {
        "key": "world_overview",
        "category": "里世界",
        "required": False,
        "description": "世界类型、尺度、时代和现实/虚构程度。",
        "title": "TA 生活在哪个世界？",
        "prompt": "可以只写一小部分：世界类型、时代、城市/地区、真实或虚构程度、时间推进规则。",
        "fact_key": "world.overview",
        "module": "里世界",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "places",
        "category": "里世界",
        "required": False,
        "description": "可被场景、日程和事件引用的地点系统。",
        "title": "重要地点有哪些？",
        "prompt": "列出 TA 常出现的地点，比如家、学校、公司、店铺、城市角落。只写一个地点也可以。",
        "fact_key": "world.places.guided",
        "module": "里世界",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "cast",
        "category": "里世界",
        "required": False,
        "description": "朋友、家人、同事、对立人物和关系状态。",
        "title": "TA 身边有哪些重要人物？",
        "prompt": "列出朋友、家人、同事、恋人或对立人物。可以只写名字和关系。",
        "fact_key": "world.cast.guided",
        "module": "关系网络",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "timeline",
        "category": "里世界",
        "required": False,
        "description": "过去经历、当前状态、近期计划和未来张力。",
        "title": "有哪些过去、现在或未来事件？",
        "prompt": "写 TA 的过去经历、当前状态、近期计划。未确定的内容可以写“待定”。",
        "fact_key": "world.timeline.guided",
        "module": "时间线",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "daily_life",
        "title": "TA 的日常怎样运行？",
        "prompt": "写作息、常去地点、工作/学习节奏、休息方式，以及什么时候可能主动联系用户。",
        "fact_key": "runtime.daily_life",
        "module": "生活时钟",
        "category": "运行模拟",
        "required": False,
        "description": "支持生活时钟、可用状态和主动联系动机。",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "resources",
        "title": "TA 有哪些状态和资源？",
        "prompt": "写精力、压力、金钱、健康、社交电量、任务额度等可随事件变化的资源。",
        "fact_key": "runtime.resources",
        "module": "资源系统",
        "category": "运行模拟",
        "required": False,
        "description": "让世界不只是背景，而能随时间产生状态变化。",
        "reality_kind": "fictional_canon",
        "mutability": "evolving",
    },
    {
        "key": "organizations",
        "title": "有哪些组织、学校或职业系统？",
        "prompt": "写学校、公司、社团、阵营、项目、职位路径或任务系统。可以只写一个。",
        "fact_key": "world.organizations",
        "module": "组织系统",
        "category": "里世界",
        "required": False,
        "description": "对齐新数字人里的学业/职业/组织运行能力。",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "rules",
        "title": "这个世界有什么规则？",
        "prompt": "写自然法则、社会规则、技术水平、魔法/科幻限制、新闻和外部世界是否影响设定。",
        "fact_key": "world.rules",
        "module": "世界规则",
        "category": "里世界",
        "required": False,
        "description": "约束模型不要随手改世界底层逻辑。",
        "reality_kind": "fictional_canon",
        "mutability": "locked",
    },
    {
        "key": "event_engine",
        "title": "事件应该怎样推进？",
        "prompt": "写轻微事件、高影响事件、用户审批、事件持续时间、可回滚范围和哪些事件绝不自动发生。",
        "fact_key": "runtime.event_engine",
        "module": "事件引擎",
        "category": "运行模拟",
        "required": False,
        "description": "支持审批、排程、回滚和高影响事件保护。",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "npc_autonomy",
        "title": "配角可以自主变化到什么程度？",
        "prompt": "写配角的自主行动、晋升/淡出审批、私有记忆、和主角关系推进规则。",
        "fact_key": "runtime.npc_autonomy",
        "module": "配角自治",
        "category": "运行模拟",
        "required": False,
        "description": "让关系网络可以变动，但关键变化进入审批。",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "consistency",
        "title": "系统如何检查设定冲突？",
        "prompt": "写哪些事实是锁定的，哪些可以演化；发生冲突时是提醒、提案还是自动修复。",
        "fact_key": "governance.consistency",
        "module": "一致性检查",
        "category": "治理",
        "required": False,
        "description": "对齐事实冲突、版本和审批机制。",
        "reality_kind": "fictional_canon",
        "mutability": "locked",
    },
    {
        "key": "visual_identity",
        "category": "多模态身份",
        "required": False,
        "description": "视觉候选、审批、canonical 和禁止变化特征。",
        "title": "视觉身份是什么？",
        "prompt": "描述外貌、气质、服装方向、禁止改变的视觉特征。后续图片仍需审批。",
        "fact_key": "visual.guided_identity",
        "module": "视觉身份",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
    {
        "key": "voice",
        "category": "多模态身份",
        "required": False,
        "description": "本地音色、API 音色、虚拟语音或暂不启用。",
        "title": "声音方向是什么？",
        "prompt": "描述声线、语速、情绪表现。也可以写暂不启用、本地音色、API 音色或后续自定义。",
        "fact_key": "voice.guided_direction",
        "module": "声音身份",
        "reality_kind": "fictional_canon",
        "mutability": "approval_only",
    },
]


ENGLISH_MODULE_COPY = {
    "identity": ("Character Core", "Who are they?", "Introduce this original character's name, apparent age, identity, and essential presence in a few sentences.", "The character's basic identity and presence.", "Character Core"),
    "personality": ("Character Core", "What are they like?", "List three to six stable personality traits and, if useful, how they behave differently with close friends and strangers.", "Stable personality, motives, and behavior patterns.", "Character Core"),
    "speaking_style": ("Character Core", "How do they speak?", "Describe tone, sentence length, common and forbidden expressions, and whether the style should feel like instant messaging.", "Language rhythm, emotion, and forbidden expressions.", "Expression"),
    "boundaries": ("Governance", "What must never change?", "Define originality, non-impersonation, factual limits, relationship boundaries, and safety boundaries.", "Settings and boundaries that runtime must not rewrite.", "Boundaries"),
    "world_overview": ("Inner World", "What world do they live in?", "You may define only part of it: world type, era, city or region, realism level, and how time advances.", "World type, scale, era, and degree of realism or fiction.", "Inner World"),
    "places": ("Inner World", "Which places matter?", "List places that scenes, schedules, and events can reference, such as home, school, work, a shop, or a corner of the city. One place is enough to begin.", "A place system reusable by scenes, schedules, and events.", "Inner World"),
    "cast": ("Inner World", "Who matters around them?", "List friends, family, colleagues, partners, or rivals. Names and relationships are enough to begin.", "Friends, family, colleagues, rivals, and relationship states.", "Relationship Network"),
    "timeline": ("Inner World", "What happened before, now, and next?", "Describe past experiences, current circumstances, and near-term plans. Mark undecided details as TBD.", "Past experiences, current state, plans, and future tension.", "Timeline"),
    "daily_life": ("Runtime Simulation", "How does daily life run?", "Describe routines, recurring places, work or study rhythm, rest, and when the character may proactively contact the user.", "Supports life clock, availability, and motives for proactive contact.", "Life Clock"),
    "resources": ("Runtime Simulation", "What states and resources change?", "Define energy, stress, money, health, social battery, task capacity, or other resources that events may change.", "Makes the world stateful rather than a static backdrop.", "Resource System"),
    "organizations": ("Inner World", "Which organizations shape the world?", "Define schools, companies, clubs, factions, projects, career paths, or task systems. One organization is enough to begin.", "Academic, career, and organizational systems.", "Organization System"),
    "rules": ("Inner World", "What rules govern this world?", "Define natural laws, social rules, technology level, magic or science-fiction limits, and whether outside news affects the setting.", "Prevents the model from casually rewriting foundational logic.", "World Rules"),
    "event_engine": ("Runtime Simulation", "How should events advance?", "Define minor and high-impact events, approval rules, duration, rollback scope, and events that must never occur automatically.", "Supports approval, scheduling, rollback, and high-impact safeguards.", "Event Engine"),
    "npc_autonomy": ("Runtime Simulation", "How autonomous can supporting characters be?", "Define autonomous actions, approval for promotion or departure, private memories, and relationship progression rules.", "Lets relationships evolve while keeping major changes under approval.", "Supporting Character Autonomy"),
    "consistency": ("Governance", "How should conflicts be checked?", "Define locked and evolving facts and whether conflicts should create a warning, proposal, or automatic repair.", "Fact conflict, version, and approval rules.", "Consistency"),
    "visual_identity": ("Multimodal Identity", "What is the visual identity?", "Describe appearance, presence, clothing direction, and visual traits that must not change. Generated images still require approval.", "Visual candidates, approval, canonical identity, and invariant traits.", "Visual Identity"),
    "voice": ("Multimodal Identity", "What should the voice feel like?", "Describe vocal quality, pace, and emotional expression. You may choose no voice yet, a local voice, an API voice, or later customization.", "Local voice, API voice, synthetic voice, or disabled.", "Voice Identity"),
}


def question_map() -> dict[str, dict[str, str]]:
    return {item["key"]: item for item in FICTIONAL_MODULES}


def _avatar_context(db: Database, avatar_id: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,)) or {}
    return avatar_language_profile(row)


def _localized_item(item: dict[str, Any], context: dict[str, Any]) -> dict[str, Any]:
    copied = dict(item)
    english = context.get("avatar_primary_language") == "en-US"
    if english:
        category, title, prompt, description, module = ENGLISH_MODULE_COPY[item["key"]]
        copied.update(category=category, title=title, prompt=prompt, description=description, module=module)
    override = (context.get("world_region_rules") or {}).get("builder_prompts", {}).get(item["key"])
    if override and not english:
        copied["prompt"] = override
    region = context.get("world_region_rules") or {}
    if item["key"] == "rules":
        if english:
            copied["prompt"] += (
                f" Current world region: {region.get('name_en', 'Custom')}. Also define social rules, "
                "holidays or special dates, plausibility boundaries, and events that must not happen automatically."
            )
        else:
            copied["prompt"] = (
                f"{copied['prompt']} 当前世界场景：{region.get('name_zh', '自定义')}；"
                f"需要明确社会规则、节日/特殊日期、合理性边界和不应自动发生的事件。"
            )
    return copied


def ensure_modules(db: Database, avatar_id: str) -> None:
    now = int(time.time())
    context = _avatar_context(db, avatar_id)
    with db.transaction() as connection:
        for raw in FICTIONAL_MODULES:
            item = _localized_item(raw, context)
            connection.execute(
                """
                INSERT INTO world_modules(avatar_id,module_key,module_name,category,required,enabled,status,description,created_at,updated_at)
                VALUES(?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(avatar_id,module_key) DO UPDATE SET
                  module_name=excluded.module_name,
                  category=excluded.category,
                  required=excluded.required,
                  description=excluded.description,
                  updated_at=excluded.updated_at
                """,
                (
                    avatar_id,
                    item["key"],
                    item["module"],
                    item["category"],
                    int(bool(item["required"])),
                    1,
                    "not_started",
                    item["description"],
                    now,
                    now,
                ),
            )


def update_module(db: Database, avatar_id: str, module_key: str, enabled: bool) -> dict[str, Any]:
    ensure_modules(db, avatar_id)
    row = db.one("SELECT * FROM world_modules WHERE avatar_id=? AND module_key=?", (avatar_id, module_key))
    if not row:
        raise KeyError("未知世界模块")
    if bool(row["required"]) and not enabled:
        raise ValueError("必须模块不能关闭")
    db.execute(
        "UPDATE world_modules SET enabled=?,updated_at=? WHERE avatar_id=? AND module_key=?",
        (int(enabled), int(time.time()), avatar_id, module_key),
    )
    return guided_state(db, avatar_id)


def guided_state(db: Database, avatar_id: str) -> dict[str, Any]:
    ensure_modules(db, avatar_id)
    context = _avatar_context(db, avatar_id)
    answers = db.all(
        "SELECT question_key,answer,created_at FROM builder_answers WHERE avatar_id=? AND route='fictional_guided' ORDER BY id",
        (avatar_id,),
    )
    answered = {row["question_key"]: row for row in answers}
    module_rows = db.all("SELECT * FROM world_modules WHERE avatar_id=? ORDER BY required DESC, category, id", (avatar_id,))
    modules = {row["module_key"]: row for row in module_rows}
    questions = []
    for raw in FICTIONAL_MODULES:
        item = _localized_item(raw, context)
        module = modules.get(item["key"]) or {}
        enabled = bool(module.get("enabled", True)) or bool(item["required"])
        row = answered.get(item["key"])
        questions.append({
            "key": item["key"],
            "title": item["title"],
            "prompt": item["prompt"],
            "module": item["module"],
            "category": item["category"],
            "required": bool(item["required"]),
            "enabled": enabled,
            "description": item["description"],
            "answered": bool(row),
            "answer": str(row["answer"]) if row else "",
            "created_at": int(row["created_at"]) if row else 0,
        })
    active_questions = [item for item in questions if item["enabled"]]
    next_question = next((item for item in active_questions if not item["answered"]), None)
    progress = round(sum(1 for item in active_questions if item["answered"]) / max(1, len(active_questions)) * 100)
    return {
        "route": "fictional_guided",
        "progress": progress,
        "language_profile": context,
        "questions": questions,
        "modules": [{
            "key": row["module_key"],
            "name": row["module_name"],
            "category": row["category"],
            "required": bool(row["required"]),
            "enabled": bool(row["enabled"]),
            "status": row["status"],
            "description": row["description"],
            "answered": row["module_key"] in answered,
        } for row in module_rows],
        "next_question": next_question,
        "complete": progress == 100,
    }


def record_answer(db: Database, avatar_id: str, question_key: str, answer: str) -> dict[str, Any]:
    context = _avatar_context(db, avatar_id)
    questions = {item["key"]: _localized_item(item, context) for item in FICTIONAL_MODULES}
    item = questions.get(question_key)
    if not item:
        raise KeyError("未知 Builder 问题")
    ensure_modules(db, avatar_id)
    module = db.one("SELECT * FROM world_modules WHERE avatar_id=? AND module_key=?", (avatar_id, question_key))
    if module and not bool(module["enabled"]) and not bool(module["required"]):
        raise ValueError("这个世界模块当前未启用")
    now = int(time.time())
    content = f"## {item['title']}\n{answer.strip()}"
    evidence_id = db.execute(
        "INSERT INTO evidence(avatar_id,source_type,title,content,tags_json,derived_kind,confidence,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (
            avatar_id,
            "guided_builder",
            item["title"],
            content,
            json.dumps(["guided", item["module"]], ensure_ascii=False),
            "guided_setting",
            1.0,
            now,
        ),
    )
    db.execute(
        """
        INSERT INTO builder_answers(avatar_id,route,question_key,question_text,answer,evidence_id,created_at)
        VALUES(?,?,?,?,?,?,?)
        ON CONFLICT(avatar_id, route, question_key) DO UPDATE SET
          question_text=excluded.question_text,
          answer=excluded.answer,
          evidence_id=excluded.evidence_id,
          created_at=excluded.created_at
        """,
        (avatar_id, "fictional_guided", item["key"], item["prompt"], answer.strip(), evidence_id, now),
    )
    db.execute(
        "UPDATE world_modules SET status='answered',updated_at=? WHERE avatar_id=? AND module_key=?",
        (now, avatar_id, question_key),
    )
    propose_fact(
        db,
        avatar_id,
        fact_key=item["fact_key"],
        value={"module": item["module"], "answer": answer.strip()},
        reality_kind=item["reality_kind"],
        mutability=item["mutability"],
        reason="问答式 Builder 生成，等待用户批准进入正式设定",
        source_evidence_id=evidence_id,
    )
    return guided_state(db, avatar_id)
