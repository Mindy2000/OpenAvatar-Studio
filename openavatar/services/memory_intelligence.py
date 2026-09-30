from __future__ import annotations

import json
import re
import time
from collections import Counter, defaultdict
from typing import Any

from openavatar.db import Database


STOPWORDS = {"这个", "那个", "我们", "你们", "他们", "自己", "今天", "时候", "因为", "所以", "但是", "然后", "一个", "什么"}


def _tokens(text: str) -> list[str]:
    return [
        item
        for item in re.findall(r"[\w\u4e00-\u9fff]{2,}", text.lower())
        if item not in STOPWORDS and not item.isdigit()
    ][:80]


def rebuild_memory_graph(db: Database, avatar_id: str, limit: int = 500) -> dict[str, Any]:
    rows = db.all("SELECT id,speaker,content,kind,is_avatar,confidence,created_at FROM memories WHERE avatar_id=? ORDER BY id DESC LIMIT ?", (avatar_id, min(max(limit, 20), 5000)))
    now = int(time.time())
    counter: Counter[str] = Counter()
    co: defaultdict[tuple[str, str], int] = defaultdict(int)
    for row in rows:
        unique = list(dict.fromkeys(_tokens(str(row["content"]))))[:12]
        counter.update(unique)
        for index, left in enumerate(unique):
            for right in unique[index + 1:]:
                a, b = sorted((left, right))
                co[(a, b)] += 1
    with db.transaction() as connection:
        connection.execute("DELETE FROM memory_graph_nodes WHERE avatar_id=?", (avatar_id,))
        connection.execute("DELETE FROM memory_graph_edges WHERE avatar_id=?", (avatar_id,))
        for token, count in counter.most_common(80):
            connection.execute(
                "INSERT INTO memory_graph_nodes(avatar_id,node_key,label,node_type,weight,evidence_count,metadata_json,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                (avatar_id, token, token, "concept", min(1.0, count / max(1, len(rows))), count, json.dumps({"source": "memory_rebuild"}, ensure_ascii=False), now),
            )
        for (left, right), count in sorted(co.items(), key=lambda item: item[1], reverse=True)[:160]:
            connection.execute(
                "INSERT INTO memory_graph_edges(avatar_id,source_key,target_key,relation,weight,evidence_count,updated_at) VALUES(?,?,?,?,?,?,?)",
                (avatar_id, left, right, "co_occurs", min(1.0, count / max(1, len(rows))), count, now),
            )
    return memory_graph(db, avatar_id)


def memory_graph(db: Database, avatar_id: str, limit: int = 80) -> dict[str, Any]:
    nodes = db.all(
        "SELECT id,node_key,label,node_type,weight,evidence_count,metadata_json,updated_at FROM memory_graph_nodes WHERE avatar_id=? ORDER BY weight DESC,id DESC LIMIT ?",
        (avatar_id, min(max(limit, 1), 300)),
    )
    edges = db.all(
        "SELECT id,source_key,target_key,relation,weight,evidence_count,updated_at FROM memory_graph_edges WHERE avatar_id=? ORDER BY weight DESC,id DESC LIMIT ?",
        (avatar_id, min(max(limit * 2, 1), 600)),
    )
    for row in nodes:
        row["metadata"] = json.loads(row.pop("metadata_json", "{}"))
    return {"nodes": nodes, "edges": edges}


def revise_memory(db: Database, avatar_id: str, memory_id: int, patch: dict[str, Any], *, action: str = "edit", note: str = "") -> dict[str, Any]:
    row = db.one("SELECT * FROM memories WHERE id=? AND avatar_id=?", (memory_id, avatar_id))
    if not row:
        raise KeyError("记忆不存在")
    before = dict(row)
    fields = []
    params: list[Any] = []
    allowed = {"speaker", "content", "kind", "is_avatar", "confidence"}
    for key in allowed:
        if key in patch:
            fields.append(f"{key}=?")
            value = patch[key]
            if key == "is_avatar":
                value = int(bool(value))
            if key == "confidence":
                value = min(max(float(value), 0), 1)
            params.append(value)
    if fields:
        params.append(memory_id)
        db.execute(f"UPDATE memories SET {', '.join(fields)} WHERE id=?", tuple(params))
    after = db.one("SELECT * FROM memories WHERE id=?", (memory_id,)) or {}
    db.execute(
        "INSERT INTO memory_revisions(avatar_id,memory_id,before_json,after_json,action,note,created_at) VALUES(?,?,?,?,?,?,?)",
        (avatar_id, memory_id, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), action[:80], note[:1000], int(time.time())),
    )
    return after


def review_memory(db: Database, avatar_id: str, memory_id: int, action: str, note: str = "") -> dict[str, Any]:
    if action == "approve":
        return revise_memory(db, avatar_id, memory_id, {"confidence": 1.0}, action="approve", note=note)
    if action == "downgrade":
        return revise_memory(db, avatar_id, memory_id, {"confidence": 0.35}, action="downgrade", note=note)
    if action == "reject":
        return revise_memory(db, avatar_id, memory_id, {"confidence": 0.0, "kind": "rejected"}, action="reject", note=note)
    raise ValueError("记忆审核动作不合法")


def merge_memories(db: Database, avatar_id: str, primary_id: int, duplicate_id: int) -> dict[str, Any]:
    primary = db.one("SELECT * FROM memories WHERE id=? AND avatar_id=?", (primary_id, avatar_id))
    duplicate = db.one("SELECT * FROM memories WHERE id=? AND avatar_id=?", (duplicate_id, avatar_id))
    if not primary or not duplicate:
        raise KeyError("记忆不存在")
    merged = f"{primary['content']}\n{duplicate['content']}"
    revise_memory(db, avatar_id, primary_id, {"content": merged[:100000], "confidence": max(float(primary["confidence"]), float(duplicate["confidence"]))}, action="merge", note=f"合并 duplicate #{duplicate_id}")
    revise_memory(db, avatar_id, duplicate_id, {"kind": "merged_duplicate", "confidence": 0.0}, action="merged_duplicate", note=f"合并到 #{primary_id}")
    return dict(db.one("SELECT * FROM memories WHERE id=?", (primary_id,)))


def sleep_consolidation(db: Database, avatar_id: str, limit: int = 120) -> dict[str, Any]:
    rows = db.all("SELECT * FROM memories WHERE avatar_id=? AND confidence>0 ORDER BY id DESC LIMIT ?", (avatar_id, min(max(limit, 20), 1000)))
    buckets: defaultdict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        tokens = _tokens(str(row["content"]))
        key = tokens[0] if tokens else str(row["kind"])
        buckets[key].append(row)
    now = int(time.time())
    created = 0
    for key, items in buckets.items():
        if len(items) < 3:
            continue
        content = "；".join(str(item["content"]).strip().replace("\n", " ")[:80] for item in items[:6])
        db.execute(
            "INSERT INTO memories(avatar_id,speaker,content,kind,is_avatar,confidence,created_at) VALUES(?,?,?,?,?,?,?)",
            (avatar_id, "system", f"整理主题「{key}」：{content}", "consolidated_summary", 0, 0.72, now),
        )
        created += 1
    if created:
        rebuild_memory_graph(db, avatar_id, limit)
    return {"created": created, "source_count": len(rows), "graph": memory_graph(db, avatar_id, 40)}


def memory_revisions(db: Database, avatar_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.all(
        "SELECT id,memory_id,before_json,after_json,action,note,created_at FROM memory_revisions WHERE avatar_id=? ORDER BY id DESC LIMIT ?",
        (avatar_id, min(max(limit, 1), 500)),
    )
    for row in rows:
        row["before"] = json.loads(row.pop("before_json", "{}"))
        row["after"] = json.loads(row.pop("after_json", "{}"))
    return rows
