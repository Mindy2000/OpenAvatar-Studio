from __future__ import annotations

import json
import re
import sqlite3
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
    rows = db.all("SELECT id,speaker,content,kind,is_avatar,confidence,created_at FROM memories WHERE avatar_id=? AND confidence>0 AND kind NOT IN ('rejected','merged_duplicate') AND (origin_kind<>'runtime_chat' OR timeline_kind='official') ORDER BY id DESC LIMIT ?", (avatar_id, min(max(limit, 20), 5000)))
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
    with db.transaction() as connection:
        row = connection.execute("SELECT * FROM memories WHERE id=? AND avatar_id=?", (memory_id, avatar_id)).fetchone()
        if not row:
            raise KeyError("记忆不存在")
        before = dict(row)
        if fields:
            params.append(memory_id)
            connection.execute(f"UPDATE memories SET {', '.join(fields)} WHERE id=?", tuple(params))
        after = dict(connection.execute("SELECT * FROM memories WHERE id=?", (memory_id,)).fetchone())
        now = int(time.time())
        # Maintenance edits must have the same context guarantees as the chat controls.
        # Internal merge operations retain their source; they are not a correction.
        if action not in {"merge", "merged_duplicate"} and (
            after["content"] != before["content"] or after["confidence"] <= 0 or after["kind"] == "rejected"
        ):
            exclude_memory_chat_context(connection, avatar_id, {memory_id})
            deactivate_merged_memories(connection, avatar_id, {memory_id}, now, f"记忆 #{memory_id} 已修改或停用，合并记忆同时停用")
        connection.execute(
            "INSERT INTO memory_revisions(avatar_id,memory_id,before_json,after_json,action,note,created_at) VALUES(?,?,?,?,?,?,?)",
            (avatar_id, memory_id, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), action[:80], note[:1000], now),
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


def merged_memory_ids(db: Database, avatar_id: str, source_ids: set[int]) -> set[int]:
    """Follow recorded merge provenance, including inactive intermediate notes."""
    with db.transaction() as connection:
        return related_merged_memory_ids(connection, avatar_id, source_ids)


def related_merged_memory_ids(connection: sqlite3.Connection, avatar_id: str, source_ids: set[int], *, ancestors: bool = False) -> set[int]:
    edges = []
    for row in connection.execute("SELECT memory_id,note FROM memory_revisions WHERE avatar_id=? AND action='merge'", (avatar_id,)):
        match = re.fullmatch(r"合并 duplicate #(\d+)", row["note"])
        if match:
            child, parent = int(match.group(1)), row["memory_id"]
            edges.append((parent, child) if ancestors else (child, parent))
    reached = set(source_ids)
    while True:
        parents = {parent for child, parent in edges if child in reached}
        if parents <= reached:
            return reached
        reached.update(parents)


def exclude_memory_chat_context(connection: sqlite3.Connection, avatar_id: str, memory_ids: set[int]) -> None:
    """Exclude originals and same-turn echoes, also for a merged note's sources."""
    for memory_id in related_merged_memory_ids(connection, avatar_id, memory_ids, ancestors=True):
        source = connection.execute(
            "SELECT m.source_message_id FROM memories m JOIN messages s "
            "ON s.id=m.source_message_id AND s.avatar_id=m.avatar_id "
            "WHERE m.id=? AND m.avatar_id=? AND m.origin_kind='runtime_chat'", (memory_id, avatar_id),
        ).fetchone()
        if not source:
            continue
        exclude_chat_message_context(connection, avatar_id, source["source_message_id"])


def exclude_chat_message_context(connection: sqlite3.Connection, avatar_id: str, message_id: int) -> None:
    source = connection.execute("SELECT turn_id,channel FROM messages WHERE avatar_id=? AND id=?", (avatar_id, message_id)).fetchone()
    if not source:
        return
    connection.execute("UPDATE messages SET context_excluded=1 WHERE avatar_id=? AND id=?", (avatar_id, message_id))
    if source["turn_id"]:
        connection.execute("UPDATE messages SET context_excluded=1 WHERE avatar_id=? AND turn_id=? AND channel=?", (avatar_id, source["turn_id"], source["channel"]))


def deactivate_merged_memories(connection: sqlite3.Connection, avatar_id: str, source_ids: set[int], now: int, note: str, *, action: str = "source_changed") -> None:
    for memory_id in sorted(related_merged_memory_ids(connection, avatar_id, source_ids) - source_ids):
        row = connection.execute(
            "SELECT * FROM memories WHERE avatar_id=? AND id=? AND confidence>0 AND kind NOT IN ('rejected','merged_duplicate')", (avatar_id, memory_id),
        ).fetchone()
        if not row:
            continue
        before = dict(row)
        after = {**before, "confidence": 0, "kind": "rejected"}
        connection.execute("UPDATE memories SET confidence=0,kind='rejected' WHERE id=? AND avatar_id=?", (memory_id, avatar_id))
        connection.execute("INSERT INTO memory_revisions(avatar_id,memory_id,before_json,after_json,action,note,created_at) VALUES(?,?,?,?,?,?,?)",
                           (avatar_id, memory_id, json.dumps(before, ensure_ascii=False), json.dumps(after, ensure_ascii=False), action, note, now))


def merge_memories(db: Database, avatar_id: str, primary_id: int, duplicate_id: int) -> dict[str, Any]:
    if primary_id == duplicate_id:
        raise ValueError("不能将记忆与自身合并")
    primary = db.one("SELECT * FROM memories WHERE id=? AND avatar_id=?", (primary_id, avatar_id))
    duplicate = db.one("SELECT * FROM memories WHERE id=? AND avatar_id=?", (duplicate_id, avatar_id))
    if not primary or not duplicate:
        raise KeyError("记忆不存在")
    if any(row["kind"] in {"merged_duplicate", "rejected"} for row in (primary, duplicate)):
        raise ValueError("请选择两条可用记忆；已合并或拒绝的条目不能再次合并")
    preview_scopes = {row["origin_kind"] == "runtime_chat" and row["timeline_kind"] == "preview" for row in (primary, duplicate)}
    if len(preview_scopes) > 1:
        raise ValueError("预览记忆与正式记忆不能合并，请在各自时间线中修改")
    merged = f"{primary['content']}\n{duplicate['content']}"
    revise_memory(db, avatar_id, primary_id, {"content": merged[:100000], "confidence": max(float(primary["confidence"]), float(duplicate["confidence"]))}, action="merge", note=f"合并 duplicate #{duplicate_id}")
    revise_memory(db, avatar_id, duplicate_id, {"kind": "merged_duplicate", "confidence": 0.0}, action="merged_duplicate", note=f"合并到 #{primary_id}")
    return dict(db.one("SELECT * FROM memories WHERE id=?", (primary_id,)))


def sleep_consolidation(db: Database, avatar_id: str, limit: int = 120) -> dict[str, Any]:
    # Explicit chat notes keep their source so correcting/forgetting remains reliable.
    rows = db.all("SELECT * FROM memories WHERE avatar_id=? AND confidence>0 AND kind NOT IN ('rejected','merged_duplicate') AND origin_kind<>'runtime_chat' ORDER BY id DESC LIMIT ?", (avatar_id, min(max(limit, 20), 1000)))
    explicit_ids = {row["id"] for row in db.all("SELECT id FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat'", (avatar_id,))}
    protected_ids = merged_memory_ids(db, avatar_id, explicit_ids)
    rows = [row for row in rows if row["id"] not in protected_ids]
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
