from __future__ import annotations

from typing import Any
from fastapi import HTTPException
from openavatar.db import Database
from openavatar.services.world_regions import avatar_language_profile

def public_avatar(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for key in ("adult_subject", "consent_confirmed", "proactive_enabled"):
        result[key] = bool(result.get(key))
    result["language_profile"] = avatar_language_profile(result)
    return result


def require_avatar(db: Database, avatar_id: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,))
    if not row:
        raise HTTPException(404, "数字人不存在")
    return row



