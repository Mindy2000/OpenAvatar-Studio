from __future__ import annotations

import json
import re
import time
from typing import Any

from openavatar.db import Database


KIND_WEIGHTS = {
    "conversation": 0.9,
    "speaking_style": 1.0,
    "image_ocr": 0.65,
    "audio_transcript": 0.75,
    "voice_sample": 0.4,
    "image_asset": 0.35,
}


def material_inventory(db: Database, avatar_id: str) -> dict[str, Any]:
    imports = db.all("SELECT category,status,COUNT(*) AS count,SUM(size_bytes) AS bytes FROM imports WHERE avatar_id=? GROUP BY category,status", (avatar_id,))
    evidence = db.all("SELECT derived_kind,source_type,COUNT(*) AS count FROM evidence WHERE avatar_id=? GROUP BY derived_kind,source_type", (avatar_id,))
    memories = db.one("SELECT COUNT(*) AS count FROM memories WHERE avatar_id=? AND confidence>0", (avatar_id,)) or {"count": 0}
    avatar_lines = db.one("SELECT COUNT(*) AS count FROM memories WHERE avatar_id=? AND is_avatar=1 AND confidence>0", (avatar_id,)) or {"count": 0}
    score = 0.0
    for row in evidence:
        score += KIND_WEIGHTS.get(str(row["derived_kind"]), 0.25) * int(row["count"])
    return {
        "imports": imports,
        "evidence": evidence,
        "memory_count": int(memories["count"]),
        "avatar_utterance_count": int(avatar_lines["count"]),
        "material_score": round(min(100.0, score * 8), 1),
        "has_text_persona_material": any(row["derived_kind"] in {"conversation", "speaking_style", "image_ocr"} for row in evidence),
        "has_audio": any(row["category"] == "audio" for row in imports),
        "has_visual": any(row["category"] == "image" for row in imports),
    }


def extract_profile_hints(db: Database, avatar_id: str) -> dict[str, Any]:
    rows = db.all("SELECT title,content,derived_kind,confidence FROM evidence WHERE avatar_id=? ORDER BY id DESC LIMIT 200", (avatar_id,))
    joined = "\n".join(str(row["content"]) for row in rows)[:150000]
    possible_places = sorted(set(re.findall(r"在([\u4e00-\u9fffA-Za-z0-9]{2,12})(?:住|工作|上学|见面|吃饭|聊天)", joined)))[:20]
    possible_relationships = sorted(set(re.findall(r"(朋友|同学|同事|家人|恋人|老师|学生|室友|客户|伙伴)", joined)))[:20]
    repeated_terms = {}
    for token in re.findall(r"[\w\u4e00-\u9fff]{2,}", joined):
        if len(token) <= 20:
            repeated_terms[token] = repeated_terms.get(token, 0) + 1
    terms = [item for item, _ in sorted(repeated_terms.items(), key=lambda pair: pair[1], reverse=True)[:30]]
    return {
        "places": possible_places,
        "relationships": possible_relationships,
        "frequent_terms": terms,
        "source_count": len(rows),
    }


def write_material_report(db: Database, avatar_id: str) -> dict[str, Any]:
    inventory = material_inventory(db, avatar_id)
    hints = extract_profile_hints(db, avatar_id)
    checks = [
        {"name": "文本人格素材", "passed": inventory["has_text_persona_material"], "value": inventory["has_text_persona_material"]},
        {"name": "声音素材", "passed": inventory["has_audio"], "value": inventory["has_audio"]},
        {"name": "视觉素材", "passed": inventory["has_visual"], "value": inventory["has_visual"]},
        {"name": "人物原型表达", "passed": inventory["avatar_utterance_count"] >= 20, "value": inventory["avatar_utterance_count"]},
        {"name": "长期记忆规模", "passed": inventory["memory_count"] >= 40, "value": inventory["memory_count"]},
    ]
    score = round(sum(1 for item in checks if item["passed"]) / len(checks) * 100)
    now = int(time.time())
    db.execute(
        "INSERT INTO build_reports(avatar_id,report_kind,status,score,checks_json,recommendations_json,created_at) VALUES(?,?,?,?,?,?,?)",
        (
            avatar_id,
            "real_material_inventory",
            "completed",
            score,
            json.dumps(checks, ensure_ascii=False),
            json.dumps(hints, ensure_ascii=False),
            now,
        ),
    )
    return {"score": score, "checks": checks, "inventory": inventory, "hints": hints}
