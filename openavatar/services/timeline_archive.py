from __future__ import annotations

import json
import re
import sqlite3
import time
from pathlib import Path
from typing import Any
from uuid import uuid4

from openavatar.db import Database
from openavatar.services.memory_intelligence import (
    deactivate_merged_memories, exclude_chat_message_context, exclude_memory_chat_context,
    rebuild_memory_graph, related_merged_memory_ids,
)


def _now() -> int:
    return int(time.time())


def _day(timestamp: int) -> str:
    return time.strftime("%Y-%m-%d", time.localtime(timestamp))


def _is_preview(kind: str) -> bool:
    return kind == "preview"


def _message_filter(kind: str) -> str:
    return "channel='preview'" if _is_preview(kind) else "channel<>'preview'"


def _active_branch(connection: sqlite3.Connection, avatar_id: str, timeline_kind: str) -> str:
    row = connection.execute(
        "SELECT id FROM chat_timeline_branches WHERE avatar_id=? AND timeline_kind=? AND status='active'",
        (avatar_id, timeline_kind),
    ).fetchone()
    if row:
        return str(row["id"])
    branch_id = uuid4().hex
    now = _now()
    connection.execute(
        """INSERT INTO chat_timeline_branches
           (id,avatar_id,timeline_kind,status,label,created_at,updated_at)
           VALUES (?,?,?,'active',?,?,?)""",
        (branch_id, avatar_id, timeline_kind, "当前时间线" if timeline_kind == "official" else "当前预览时间线", now, now),
    )
    return branch_id


def _rows(connection: sqlite3.Connection, sql: str, params: tuple[Any, ...]) -> list[dict[str, Any]]:
    return [dict(row) for row in connection.execute(sql, params).fetchall()]


def _snapshot(connection: sqlite3.Connection, avatar_id: str, timeline_kind: str) -> dict[str, Any]:
    messages = _rows(
        connection,
        f"SELECT * FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)} ORDER BY id",
        (avatar_id,),
    )
    message_ids = [int(row["id"]) for row in messages]
    placeholders = ",".join("?" for _ in message_ids)
    decisions = _rows(
        connection,
        f"SELECT * FROM decision_explanations WHERE avatar_id=? AND message_id IN ({placeholders}) ORDER BY id" if message_ids else
        "SELECT * FROM decision_explanations WHERE avatar_id=? AND 0 ORDER BY id",
        (avatar_id, *message_ids) if message_ids else (avatar_id,),
    )
    memories = _rows(
        connection,
        "SELECT * FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat' AND timeline_kind=? ORDER BY id",
        (avatar_id, timeline_kind),
    )
    runtime_ids = {row["id"] for row in memories}
    derived_ids = related_merged_memory_ids(connection, avatar_id, runtime_ids) - runtime_ids
    derived_memories = []
    for memory_id in sorted(derived_ids):
        row = connection.execute("SELECT * FROM memories WHERE avatar_id=? AND id=? AND origin_kind<>'runtime_chat'", (avatar_id, memory_id)).fetchone()
        if row:
            derived_memories.append(dict(row))
    revision_id = connection.execute("SELECT COALESCE(MAX(id),0) FROM memory_revisions WHERE avatar_id=?", (avatar_id,)).fetchone()[0]
    world_events = _rows(
        connection,
        f"SELECT * FROM world_events WHERE avatar_id=? AND source_message_id IN ({placeholders}) ORDER BY id" if message_ids else
        "SELECT * FROM world_events WHERE avatar_id=? AND 0 ORDER BY id",
        (avatar_id, *message_ids) if message_ids else (avatar_id,),
    )
    calls: list[dict[str, Any]] = []
    turns: list[dict[str, Any]] = []
    if timeline_kind == "official":
        calls = _rows(connection, "SELECT * FROM realtime_call_sessions WHERE avatar_id=? ORDER BY id", (avatar_id,))
        turns = _rows(connection, "SELECT * FROM realtime_call_turns WHERE avatar_id=? ORDER BY id", (avatar_id,))
    return {
        "version": 2,
        "timeline_kind": timeline_kind,
        "messages": messages,
        "decision_explanations": decisions,
        "runtime_memories": memories,
        "derived_memories": derived_memories,
        "memory_revision_id": revision_id,
        "world_events": world_events,
        "call_sessions": calls,
        "call_turns": turns,
    }


def _insert_rows(connection: sqlite3.Connection, table: str, rows: list[dict[str, Any]]) -> None:
    if not rows:
        return
    columns = list(rows[0])
    connection.executemany(
        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({','.join('?' for _ in columns)})",
        [[row.get(column) for column in columns] for row in rows],
    )


def _replace_with_snapshot(connection: sqlite3.Connection, avatar_id: str, timeline_kind: str, snapshot: dict[str, Any]) -> None:
    current_ids = [
        int(row[0]) for row in connection.execute(
            f"SELECT id FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)}", (avatar_id,)
        ).fetchall()
    ]
    # A branch may contain copies of chat notes merged into an independent memory.
    # Retire those copies while replacing the branch, then restore its saved copies.
    runtime_ids = {row[0] for row in connection.execute(
        "SELECT id FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat' AND timeline_kind=?", (avatar_id, timeline_kind),
    )}
    current_related_ids = related_merged_memory_ids(connection, avatar_id, runtime_ids)
    target_derived_ids = {row["id"] for row in snapshot.get("derived_memories", [])}
    # If this branch introduced a merge into an independent fact, returning to a
    # branch predating that merge must keep the independent, pre-merge content.
    baseline_before_merge = {}
    for revision in connection.execute("SELECT memory_id,note,before_json FROM memory_revisions WHERE avatar_id=? AND action='merge' ORDER BY id", (avatar_id,)):
        memory_id = revision["memory_id"]
        if memory_id not in current_related_ids - runtime_ids - target_derived_ids or memory_id in baseline_before_merge:
            continue
        match = re.fullmatch(r"合并 duplicate #(\d+)", revision["note"])
        if not match or int(match.group(1)) not in current_related_ids:
            continue
        try:
            before = json.loads(revision["before_json"])
        except (ValueError, TypeError):
            continue
        if isinstance(before, dict) and before.get("id") == memory_id and before.get("avatar_id") == avatar_id and before.get("origin_kind") != "runtime_chat":
            baseline_before_merge[memory_id] = before
    deactivate_merged_memories(connection, avatar_id, runtime_ids, _now(), "切换时间线，停用当前聊天派生记忆", action="timeline_source_removed")
    if current_ids:
        placeholders = ",".join("?" for _ in current_ids)
        connection.execute(
            f"DELETE FROM decision_explanations WHERE avatar_id=? AND message_id IN ({placeholders})",
            (avatar_id, *current_ids),
        )
        connection.execute(
            f"DELETE FROM world_events WHERE avatar_id=? AND source_message_id IN ({placeholders})",
            (avatar_id, *current_ids),
        )
    connection.execute(
        "DELETE FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat' AND timeline_kind=?",
        (avatar_id, timeline_kind),
    )
    connection.execute(f"DELETE FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)}", (avatar_id,))
    if timeline_kind == "official":
        connection.execute("DELETE FROM realtime_call_turns WHERE avatar_id=?", (avatar_id,))
        connection.execute("DELETE FROM realtime_call_sessions WHERE avatar_id=?", (avatar_id,))
    _insert_rows(connection, "messages", snapshot.get("messages", []))
    _insert_rows(connection, "decision_explanations", snapshot.get("decision_explanations", []))
    _insert_rows(connection, "memories", snapshot.get("runtime_memories", []))
    restored_ids = {row["id"] for row in snapshot.get("runtime_memories", [])}
    for row in [*baseline_before_merge.values(), *snapshot.get("derived_memories", [])]:
        if row.get("avatar_id") != avatar_id or row.get("origin_kind") == "runtime_chat":
            continue
        current = connection.execute("SELECT id FROM memories WHERE id=? AND avatar_id=?", (row["id"], avatar_id)).fetchone()
        if current:
            columns = [key for key in row if key not in {"id", "avatar_id"}]
            connection.execute(f"UPDATE memories SET {','.join(key + '=?' for key in columns)} WHERE id=? AND avatar_id=?", (*[row[key] for key in columns], row["id"], avatar_id))
        else:
            _insert_rows(connection, "memories", [row])
        restored_ids.add(row["id"])
    # Explicit corrections/stops made after a snapshot remain valid after restoring
    # it. Branch housekeeping revisions are deliberately excluded from this replay.
    revisions = connection.execute(
        "SELECT memory_id,action,after_json,note FROM memory_revisions WHERE avatar_id=? AND id>? "
        "AND action IN ('remember','correct','forget','edit','approve','downgrade','reject','source_changed') ORDER BY id",
        (avatar_id, snapshot.get("memory_revision_id", 0)),
    ).fetchall()
    for revision in revisions:
        if revision["action"] in {"correct", "forget"}:
            match = re.fullmatch(r"用户在聊天消息 #(\d+) 中确认", revision["note"])
            if match:
                # Stop-use is also valid for messages never saved as a note.
                exclude_chat_message_context(connection, avatar_id, int(match.group(1)))
        memory_id = revision["memory_id"]
        if memory_id not in restored_ids:
            continue
        try:
            after = json.loads(revision["after_json"])
        except (ValueError, TypeError):
            continue
        if not isinstance(after, dict) or not after:
            continue
        columns = [key for key in ("speaker", "content", "kind", "is_avatar", "confidence") if key in after]
        if not columns:
            continue
        before = connection.execute("SELECT content FROM memories WHERE id=? AND avatar_id=?", (memory_id, avatar_id)).fetchone()
        connection.execute(f"UPDATE memories SET {','.join(key + '=?' for key in columns)} WHERE id=? AND avatar_id=?", (*[after[key] for key in columns], memory_id, avatar_id))
        if revision["action"] in {"correct", "forget", "reject", "source_changed"} or after.get("confidence", 1) <= 0 or after.get("content", before["content"]) != before["content"]:
            exclude_memory_chat_context(connection, avatar_id, {memory_id})
    _insert_rows(connection, "world_events", snapshot.get("world_events", []))
    if timeline_kind == "official":
        _insert_rows(connection, "realtime_call_sessions", snapshot.get("call_sessions", []))
        _insert_rows(connection, "realtime_call_turns", snapshot.get("call_turns", []))


def search_records(
    db: Database,
    avatar_id: str,
    *,
    query: str = "",
    layer: str = "all",
    day: str = "",
    timeline_kind: str = "official",
    limit: int = 200,
) -> dict[str, Any]:
    query = query.strip().lower()
    items: list[dict[str, Any]] = []
    if layer in {"all", "historical"}:
        rows = db.all(
            """SELECT m.id,m.speaker,m.content,m.kind,m.is_avatar,m.created_at,m.origin_kind,
                      c.corrected_speaker,c.corrected_content,c.note
               FROM memories m LEFT JOIN historical_memory_corrections c ON c.memory_id=m.id
               WHERE m.avatar_id=? AND m.origin_kind<>'runtime_chat' ORDER BY m.id DESC""",
            (avatar_id,),
        )
        for row in rows:
            content = str(row.get("corrected_content") or row["content"])
            speaker = str(row.get("corrected_speaker") or row["speaker"])
            item_day = _day(int(row["created_at"]))
            if query and query not in f"{speaker} {content} {row['kind']}".lower():
                continue
            if day and day != item_day:
                continue
            items.append({
                "record_id": f"historical:{row['id']}", "id": row["id"], "layer": "historical",
                "read_only": True, "day": item_day, "speaker": speaker, "content": content,
                "original_content": row["content"], "kind": row["kind"],
                "corrected": bool(row.get("corrected_content") or row.get("corrected_speaker")),
                "correction_note": row.get("note") or "", "created_at": row["created_at"],
            })
    if layer in {"all", "runtime"}:
        rows = db.all(
            f"SELECT * FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)} AND channel<>'voice_call' ORDER BY id DESC",
            (avatar_id,),
        )
        for row in rows:
            item_day = _day(int(row["created_at"]))
            speaker = "我" if row["role"] == "user" else "数字人" if row["role"] == "assistant" else "系统"
            if query and query not in f"{speaker} {row['content']} {row['channel']}".lower():
                continue
            if day and day != item_day:
                continue
            items.append({
                "record_id": f"runtime:{row['id']}", "id": row["id"], "layer": "runtime",
                "read_only": False, "day": item_day, "speaker": speaker, "role": row["role"],
                "content": row["content"], "channel": row["channel"], "media_url": row.get("media_url", ""),
                "media_type": row.get("media_type", ""), "created_at": row["created_at"],
            })
    items.sort(key=lambda item: (int(item["created_at"]), int(item["id"])), reverse=True)
    return {"items": items[: min(max(limit, 1), 1000)], "total": len(items), "timeline_kind": timeline_kind}


def correct_historical_memory(db: Database, avatar_id: str, memory_id: int, payload: dict[str, Any]) -> dict[str, Any]:
    memory = db.one("SELECT * FROM memories WHERE id=? AND avatar_id=? AND origin_kind<>'runtime_chat'", (memory_id, avatar_id))
    if not memory:
        raise KeyError("永久历史记录不存在")
    now = _now()
    db.execute(
        """INSERT INTO historical_memory_corrections
           (memory_id,avatar_id,corrected_speaker,corrected_content,note,created_at,updated_at)
           VALUES(?,?,?,?,?,?,?) ON CONFLICT(memory_id) DO UPDATE SET
           corrected_speaker=excluded.corrected_speaker,corrected_content=excluded.corrected_content,
           note=excluded.note,updated_at=excluded.updated_at""",
        (memory_id, avatar_id, str(payload.get("speaker") or "")[:200], str(payload.get("content") or "")[:100000], str(payload.get("note") or "")[:1000], now, now),
    )
    return {"ok": True, "memory_id": memory_id, "raw_record_preserved": True}


def overview(db: Database, avatar_id: str, timeline_kind: str = "official") -> dict[str, Any]:
    with db.transaction() as connection:
        active = _active_branch(connection, avatar_id, timeline_kind)
    branches = db.all(
        "SELECT * FROM chat_timeline_branches WHERE avatar_id=? AND timeline_kind=? ORDER BY updated_at DESC",
        (avatar_id, timeline_kind),
    )
    for row in branches:
        row["impact"] = json.loads(row.pop("impact_json", "{}"))
        row.pop("snapshot_json", None)
    historical_count = int(db.one("SELECT COUNT(*) count FROM memories WHERE avatar_id=? AND origin_kind<>'runtime_chat'", (avatar_id,))["count"])
    runtime_count = int(db.one(f"SELECT COUNT(*) count FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)}", (avatar_id,))["count"])
    candidate_count = int(db.one("SELECT COUNT(*) count FROM timeline_media_candidates WHERE avatar_id=? AND status='available'", (avatar_id,))["count"])
    return {"active_branch_id": active, "historical_count": historical_count, "runtime_count": runtime_count, "candidate_count": candidate_count, "branches": branches, "timeline_kind": timeline_kind}


def preview_change(db: Database, avatar_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    timeline_kind = str(payload.get("timeline_kind") or "official")
    action = str(payload.get("action") or "")
    message_id = int(payload.get("message_id") or 0)
    replacement = str(payload.get("replacement_text") or "").strip()
    if timeline_kind not in {"official", "preview"} or action not in {"edit", "delete"}:
        raise ValueError("时间线修改参数不合法")
    if action == "edit" and not replacement:
        raise ValueError("修改后的内容不能为空")
    target = db.one(
        f"SELECT * FROM messages WHERE id=? AND avatar_id=? AND {_message_filter(timeline_kind)}",
        (message_id, avatar_id),
    )
    if not target:
        raise KeyError("当前时间线中没有这条消息")
    comparator = ">" if action == "edit" else ">="
    affected = int(db.one(
        f"SELECT COUNT(*) count FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)} AND id {comparator} ?",
        (avatar_id, message_id),
    )["count"])
    media_count = int(db.one(
        f"SELECT COUNT(*) count FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)} AND id {comparator} ? AND media_url<>''",
        (avatar_id, message_id),
    )["count"])
    impact = {
        "affected_messages": affected, "media_candidates": media_count,
        "historical_changed": 0, "independent_world_changed": 0,
        "cutoff_day": _day(int(target["created_at"])), "timeline_kind": timeline_kind,
    }
    token = uuid4().hex
    now = _now()
    with db.transaction() as connection:
        connection.execute("DELETE FROM chat_change_previews WHERE expires_at<?", (now,))
        connection.execute(
            """INSERT INTO chat_change_previews
               (token,avatar_id,timeline_kind,action,message_id,replacement_text,impact_json,expires_at,created_at)
               VALUES(?,?,?,?,?,?,?,?,?)""",
            (token, avatar_id, timeline_kind, action, message_id, replacement, json.dumps(impact, ensure_ascii=False), now + 900, now),
        )
    return {"ok": True, "preview_token": token, "impact": impact, "expires_in_seconds": 900}


def apply_change(db: Database, avatar_id: str, preview_token: str) -> dict[str, Any]:
    now = _now()
    with db.transaction() as connection:
        preview = connection.execute(
            "SELECT * FROM chat_change_previews WHERE token=? AND avatar_id=? AND expires_at>=?",
            (preview_token, avatar_id, now),
        ).fetchone()
        if not preview:
            raise ValueError("确认已过期，请重新查看影响范围")
        timeline_kind = str(preview["timeline_kind"])
        target = connection.execute(
            f"SELECT * FROM messages WHERE id=? AND avatar_id=? AND {_message_filter(timeline_kind)}",
            (preview["message_id"], avatar_id),
        ).fetchone()
        if not target:
            raise KeyError("目标消息已经不在当前时间线")
        active = _active_branch(connection, avatar_id, timeline_kind)
        frozen = uuid4().hex
        snapshot = _snapshot(connection, avatar_id, timeline_kind)
        impact = json.loads(preview["impact_json"])
        connection.execute(
            """INSERT INTO chat_timeline_branches
               (id,avatar_id,timeline_kind,parent_id,status,label,mutation_action,selected_message_id,snapshot_json,impact_json,created_at,updated_at)
               VALUES(?,?,?,?,?,?,?,?,?,?,?,?)""",
            (frozen, avatar_id, timeline_kind, active, "frozen", f"封存于 {_day(now)}", preview["action"], preview["message_id"], json.dumps(snapshot, ensure_ascii=False), preview["impact_json"], now, now),
        )
        comparator = ">" if preview["action"] == "edit" else ">="
        removed = _rows(
            connection,
            f"SELECT * FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)} AND id {comparator} ? ORDER BY id",
            (avatar_id, preview["message_id"]),
        )
        removed_ids = [int(row["id"]) for row in removed]
        for row in removed:
            media_url = str(row.get("media_url") or "")
            if not media_url:
                continue
            media_type = str(row.get("media_type") or "")
            automatic = row["role"] == "assistant" and not media_type.startswith("audio")
            connection.execute(
                """INSERT OR IGNORE INTO timeline_media_candidates
                   (avatar_id,branch_id,message_id,media_url,media_type,origin_role,reuse_policy,status,created_at,updated_at)
                   VALUES(?,?,?,?,?,?,?,'available',?,?)""",
                (avatar_id, frozen, row["id"], media_url, media_type, row["role"], "automatic" if automatic else "permission_required", now, now),
            )
        causal_ids = list(removed_ids)
        if preview["action"] == "edit":
            causal_ids.append(int(preview["message_id"]))
        if causal_ids:
            causal_ids = list(dict.fromkeys(causal_ids))
            placeholders = ",".join("?" for _ in causal_ids)
            source_ids = {row[0] for row in connection.execute(
                f"SELECT id FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat' AND source_message_id IN ({placeholders})", (avatar_id, *causal_ids),
            )}
            deactivate_merged_memories(connection, avatar_id, source_ids, now, "聊天时间线已回退，派生合并记忆同时停用", action="timeline_source_removed")
            connection.execute(f"DELETE FROM decision_explanations WHERE avatar_id=? AND message_id IN ({placeholders})", (avatar_id, *causal_ids))
            connection.execute(f"DELETE FROM memories WHERE avatar_id=? AND origin_kind='runtime_chat' AND source_message_id IN ({placeholders})", (avatar_id, *causal_ids))
            connection.execute(f"DELETE FROM world_events WHERE avatar_id=? AND source_message_id IN ({placeholders})", (avatar_id, *causal_ids))
        connection.execute(
            f"DELETE FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)} AND id {comparator} ?",
            (avatar_id, preview["message_id"]),
        )
        if preview["action"] == "edit":
            connection.execute("UPDATE messages SET content=? WHERE id=? AND avatar_id=?", (preview["replacement_text"], preview["message_id"], avatar_id))
        if timeline_kind == "official":
            call_ids = [int(row[0]) for row in connection.execute("SELECT id FROM realtime_call_sessions WHERE avatar_id=? AND started_at>=?", (avatar_id, target["created_at"])).fetchall()]
            if call_ids:
                placeholders = ",".join("?" for _ in call_ids)
                connection.execute(f"DELETE FROM realtime_call_turns WHERE avatar_id=? AND call_session_id IN ({placeholders})", (avatar_id, *call_ids))
                connection.execute(f"DELETE FROM realtime_call_sessions WHERE avatar_id=? AND id IN ({placeholders})", (avatar_id, *call_ids))
        connection.execute("DELETE FROM chat_change_previews WHERE token=?", (preview_token,))
        connection.execute("UPDATE chat_timeline_branches SET updated_at=? WHERE id=?", (now, active))
        remaining = int(connection.execute(f"SELECT COUNT(*) FROM messages WHERE avatar_id=? AND {_message_filter(timeline_kind)}", (avatar_id,)).fetchone()[0])
    rebuild_memory_graph(db, avatar_id)
    return {"ok": True, "active_branch_id": active, "frozen_branch_id": frozen, "remaining_messages": remaining, "impact": impact}


def restore_branch(db: Database, avatar_id: str, branch_id: str) -> dict[str, Any]:
    now = _now()
    with db.transaction() as connection:
        target = connection.execute(
            "SELECT * FROM chat_timeline_branches WHERE id=? AND avatar_id=? AND status='frozen'",
            (branch_id, avatar_id),
        ).fetchone()
        if not target:
            raise KeyError("封存时间线不存在")
        timeline_kind = str(target["timeline_kind"])
        active = _active_branch(connection, avatar_id, timeline_kind)
        current = _snapshot(connection, avatar_id, timeline_kind)
        connection.execute(
            "UPDATE chat_timeline_branches SET status='frozen',label=?,snapshot_json=?,updated_at=? WHERE id=?",
            ("恢复时换出的时间线", json.dumps(current, ensure_ascii=False), now, active),
        )
        _replace_with_snapshot(connection, avatar_id, timeline_kind, json.loads(target["snapshot_json"] or "{}"))
        connection.execute(
            "UPDATE chat_timeline_branches SET status='active',label=?,snapshot_json='{}',updated_at=? WHERE id=?",
            ("当前时间线" if timeline_kind == "official" else "当前预览时间线", now, branch_id),
        )
    rebuild_memory_graph(db, avatar_id)
    return {"ok": True, "active_branch_id": branch_id, "frozen_branch_id": active, "swapped": True}


def _backup_database(db: Database) -> str:
    backup_dir = db.path.parent / "backups"
    backup_dir.mkdir(parents=True, exist_ok=True)
    target = backup_dir / f"openavatar-before-timeline-delete-{time.strftime('%Y%m%d-%H%M%S')}.sqlite"
    with sqlite3.connect(db.path) as source, sqlite3.connect(target) as destination:
        source.backup(destination)
    return str(target)


def delete_branch(db: Database, avatar_id: str, branch_id: str) -> dict[str, Any]:
    row = db.one("SELECT id FROM chat_timeline_branches WHERE id=? AND avatar_id=? AND status='frozen'", (branch_id, avatar_id))
    if not row:
        raise KeyError("只能永久删除封存时间线")
    backup = _backup_database(db)
    db.execute("DELETE FROM chat_timeline_branches WHERE id=? AND avatar_id=? AND status='frozen'", (branch_id, avatar_id))
    return {"ok": True, "deleted_branch_id": branch_id, "backup_path": backup}


def list_candidates(db: Database, avatar_id: str) -> list[dict[str, Any]]:
    rows = db.all("SELECT * FROM timeline_media_candidates WHERE avatar_id=? ORDER BY updated_at DESC", (avatar_id,))
    for row in rows:
        row["metadata"] = json.loads(row.pop("metadata_json", "{}"))
    return rows


def update_candidate(db: Database, avatar_id: str, candidate_id: int, status: str, confirmed: bool) -> dict[str, Any]:
    if status not in {"available", "approved", "rejected", "used"}:
        raise ValueError("候选媒体状态不合法")
    row = db.one("SELECT * FROM timeline_media_candidates WHERE id=? AND avatar_id=?", (candidate_id, avatar_id))
    if not row:
        raise KeyError("候选媒体不存在")
    if row["reuse_policy"] == "permission_required" and status in {"approved", "used"} and not confirmed:
        raise ValueError("用户上传内容和语音必须明确确认后才能再次使用")
    db.execute("UPDATE timeline_media_candidates SET status=?,updated_at=? WHERE id=?", (status, _now(), candidate_id))
    return {"ok": True, "candidate_id": candidate_id, "status": status}
