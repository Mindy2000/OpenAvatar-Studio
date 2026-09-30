from __future__ import annotations

import json
import time
from typing import Any

from openavatar.db import Database
from openavatar.services.readiness import completion_report


def blind_test_samples(db: Database, avatar_id: str) -> list[dict[str, Any]]:
    avatar = db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,))
    if not avatar:
        raise KeyError("数字人不存在")
    route = "fictional" if str(avatar["subject_kind"]) == "fictional" else "real"
    if route == "fictional":
        return [
            {
                "kind": "setting_consistency",
                "title": "设定一致性",
                "prompt": "问一个和身份/世界规则相关的问题，检查回答是否严格遵守已批准设定。",
                "expected_signal": "不临时发明未批准的经历、地点或关系。",
            },
            {
                "kind": "speaking_style",
                "title": "说话方式",
                "prompt": "让数字人用日常语气回应一个普通关心，检查是否符合设定的语气和长度。",
                "expected_signal": "表达像角色本人，不像客服或设定说明书。",
            },
            {
                "kind": "world_runtime",
                "title": "世界运行",
                "prompt": "询问今天或近期发生了什么，检查事件是否进入提案或来自已批准事实。",
                "expected_signal": "高影响事件不会自动发生；世界推进有边界。",
            },
        ]
    return [
        {
            "kind": "persona_ab",
            "title": "人格相似度",
            "prompt": "给出两个候选回复，让用户选择哪一个更像原型。",
            "expected_signal": "回复风格接近文字/聊天记录，而不是只依赖音色。",
        },
        {
            "kind": "voice_audition",
            "title": "声音试听",
            "prompt": "试听一段短句，判断声音是否像原声音。",
            "expected_signal": "声音复刻可用，但不替代人格素材。",
        },
        {
            "kind": "visual_identity",
            "title": "视觉身份",
            "prompt": "查看候选图，判断是否应批准为 canonical 真实身份参考。",
            "expected_signal": "视觉身份和真实/虚构路线标签一致。",
        },
    ]


def create_readiness_evaluation(db: Database, avatar_id: str) -> dict[str, Any]:
    report = completion_report(db, avatar_id)
    samples = blind_test_samples(db, avatar_id)
    checks = report["checks"]
    now = int(time.time())
    evaluation_id = db.execute(
        "INSERT INTO quality_evaluations(avatar_id,evaluation_kind,status,score,checks_json,samples_json,user_feedback_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            avatar_id,
            "pre_use_readiness",
            "completed",
            report["score"],
            json.dumps(checks, ensure_ascii=False),
            json.dumps(samples, ensure_ascii=False),
            json.dumps({}, ensure_ascii=False),
            now,
            now,
        ),
    )
    return {"evaluation_id": evaluation_id, "samples": samples, **report}
