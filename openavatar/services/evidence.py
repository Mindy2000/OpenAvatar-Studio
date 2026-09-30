from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any
from fastapi import HTTPException, Request

def insert_evidence(
    connection: Any,
    *,
    avatar_id: str,
    source_import_id: int | None,
    source_type: str,
    title: str,
    content: str,
    tags: list[str] | None = None,
    derived_kind: str = "",
    confidence: float = 1.0,
    created_at: int | None = None,
) -> None:
    connection.execute(
        "INSERT INTO evidence(avatar_id,source_import_id,source_type,title,content,tags_json,derived_kind,confidence,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
        (
            avatar_id,
            source_import_id,
            source_type[:80],
            title[:200],
            content[:100000],
            json.dumps(tags or [], ensure_ascii=False),
            derived_kind[:80],
            max(0.0, min(1.0, float(confidence))),
            created_at or int(time.time()),
        ),
    )


async def save_upload(request: Request, target: Path, max_bytes: int) -> int:
    size = 0
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("wb") as handle:
        async for chunk in request.stream():
            if not chunk:
                continue
            size += len(chunk)
            if size > max_bytes:
                handle.close()
                target.unlink(missing_ok=True)
                raise HTTPException(413, "文件超过本机设置的上传大小限制")
            handle.write(chunk)
    return size




