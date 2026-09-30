from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
import uuid
from pathlib import Path
from typing import Any

from openavatar.config import Settings
from openavatar.db import Database


SET_TYPES = {"identity", "wardrobe", "prop", "scene"}
APPROVED_STATUSES = {"approved", "canonical"}
ITEM_ROLES = {
    "reference", "front", "left", "right", "back", "full_body", "detail",
    "holding", "wide", "key_frame", "first_frame", "last_frame", "history_keyframe",
}


def _loads(value: Any, fallback: Any) -> Any:
    if isinstance(value, (dict, list)):
        return value
    try:
        return json.loads(str(value or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return fallback


def _key(value: str, prefix: str) -> str:
    compact = re.sub(r"[^a-z0-9_-]+", "-", value.strip().lower()).strip("-")
    return (compact[:48] or f"{prefix}-{hashlib.sha256(value.encode('utf-8')).hexdigest()[:12]}")


def _public_set(row: dict[str, Any], items: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    result = dict(row)
    result["invariants"] = _loads(result.pop("invariants_json", "[]"), [])
    result["negative_constraints"] = _loads(result.pop("negative_constraints_json", "[]"), [])
    result["metadata"] = _loads(result.pop("metadata_json", "{}"), {})
    result["items"] = items or []
    return result


def _public_item(row: dict[str, Any], avatar_id: str = "") -> dict[str, Any]:
    result = dict(row)
    result["metadata"] = _loads(result.pop("metadata_json", "{}"), {})
    if avatar_id and result.get("visual_asset_id"):
        result["asset_url"] = f"/api/avatars/{avatar_id}/visual-assets/{result['visual_asset_id']}/file"
    else:
        result["asset_url"] = str(result.get("remote_url") or "")
    return result


def create_asset_set(
    db: Database,
    avatar_id: str,
    *,
    set_type: str,
    semantic_key: str,
    label: str,
    invariants: list[str] | None = None,
    negative_constraints: list[str] | None = None,
    status: str = "candidate",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if set_type not in SET_TYPES:
        raise ValueError("不支持的视觉资产组类型")
    semantic_key = _key(semantic_key or label, set_type)
    now = int(time.time())
    existing = db.one(
        "SELECT * FROM visual_asset_sets WHERE avatar_id=? AND set_type=? AND semantic_key=? ORDER BY version DESC LIMIT 1",
        (avatar_id, set_type, semantic_key),
    )
    if existing:
        return get_asset_set(db, avatar_id, str(existing["id"]))
    set_id = f"vas_{uuid.uuid4().hex[:16]}"
    db.execute(
        """
        INSERT INTO visual_asset_sets
        (id,avatar_id,set_type,semantic_key,label,status,version,invariants_json,negative_constraints_json,metadata_json,approved_at,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            set_id, avatar_id, set_type, semantic_key, label.strip()[:200], status, 1,
            json.dumps((invariants or [])[:30], ensure_ascii=False),
            json.dumps((negative_constraints or [])[:30], ensure_ascii=False),
            json.dumps(metadata or {}, ensure_ascii=False),
            now if status in APPROVED_STATUSES else 0, now, now,
        ),
    )
    return get_asset_set(db, avatar_id, set_id)


def add_asset_item(
    db: Database,
    avatar_id: str,
    set_id: str,
    *,
    visual_asset_id: int = 0,
    role: str = "reference",
    local_path: str = "",
    remote_url: str = "",
    status: str = "candidate",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    asset_set = db.one("SELECT * FROM visual_asset_sets WHERE id=? AND avatar_id=?", (set_id, avatar_id))
    if not asset_set:
        raise KeyError("视觉资产组不存在")
    if role not in ITEM_ROLES:
        raise ValueError("不支持的素材角色")
    content_hash = ""
    if visual_asset_id:
        asset = db.one("SELECT * FROM visual_assets WHERE id=? AND avatar_id=?", (visual_asset_id, avatar_id))
        if not asset:
            raise KeyError("视觉素材不存在")
        local_path = local_path or str(asset.get("local_path") or "")
        status = str(asset.get("status") or status)
    if local_path:
        candidate = Path(local_path)
        if not candidate.is_absolute():
            candidate = db.path.parent / candidate
        if candidate.is_file():
            content_hash = hashlib.sha256(candidate.read_bytes()).hexdigest()
    if content_hash:
        duplicate = db.one(
            "SELECT * FROM visual_asset_items WHERE set_id=? AND content_sha256=? AND role=?",
            (set_id, content_hash, role),
        )
        if duplicate:
            return _public_item(duplicate, avatar_id)
    item_id = db.execute(
        """
        INSERT INTO visual_asset_items
        (set_id,visual_asset_id,role,local_path,remote_url,content_sha256,status,quality_score,metadata_json,created_at)
        VALUES(?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(set_id,visual_asset_id,role) DO UPDATE SET
          local_path=excluded.local_path,remote_url=excluded.remote_url,status=excluded.status,metadata_json=excluded.metadata_json
        """,
        (
            set_id, visual_asset_id or None, role, local_path, remote_url, content_hash,
            status, 0, json.dumps(metadata or {}, ensure_ascii=False), int(time.time()),
        ),
    )
    row = db.one(
        "SELECT * FROM visual_asset_items WHERE id=?",
        (item_id,),
    ) or db.one(
        "SELECT * FROM visual_asset_items WHERE set_id=? AND visual_asset_id IS ? AND role=?",
        (set_id, visual_asset_id or None, role),
    )
    return _public_item(row or {}, avatar_id)


def get_asset_set(db: Database, avatar_id: str, set_id: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM visual_asset_sets WHERE id=? AND avatar_id=?", (set_id, avatar_id))
    if not row:
        raise KeyError("视觉资产组不存在")
    items = [
        _public_item(item, avatar_id)
        for item in db.all("SELECT * FROM visual_asset_items WHERE set_id=? ORDER BY id", (set_id,))
    ]
    return _public_set(row, items)


def list_asset_sets(db: Database, avatar_id: str) -> list[dict[str, Any]]:
    rows = db.all("SELECT * FROM visual_asset_sets WHERE avatar_id=? ORDER BY set_type,status DESC,updated_at DESC", (avatar_id,))
    return [get_asset_set(db, avatar_id, str(row["id"])) for row in rows]


def update_asset_set(
    db: Database,
    avatar_id: str,
    set_id: str,
    *,
    status: str | None = None,
    label: str | None = None,
    invariants: list[str] | None = None,
    negative_constraints: list[str] | None = None,
) -> dict[str, Any]:
    current = db.one("SELECT * FROM visual_asset_sets WHERE id=? AND avatar_id=?", (set_id, avatar_id))
    if not current:
        raise KeyError("视觉资产组不存在")
    next_status = status or str(current["status"])
    now = int(time.time())
    if next_status == "canonical":
        db.execute(
            "UPDATE visual_asset_sets SET status='approved',updated_at=? WHERE avatar_id=? AND set_type=? AND status='canonical' AND id<>?",
            (now, avatar_id, current["set_type"], set_id),
        )
    db.execute(
        """
        UPDATE visual_asset_sets SET status=?,label=?,invariants_json=?,negative_constraints_json=?,approved_at=?,updated_at=?
        WHERE id=? AND avatar_id=?
        """,
        (
            next_status,
            (label if label is not None else current["label"])[:200],
            json.dumps(invariants if invariants is not None else _loads(current["invariants_json"], []), ensure_ascii=False),
            json.dumps(negative_constraints if negative_constraints is not None else _loads(current["negative_constraints_json"], []), ensure_ascii=False),
            now if next_status in APPROVED_STATUSES else int(current.get("approved_at") or 0),
            now, set_id, avatar_id,
        ),
    )
    return get_asset_set(db, avatar_id, set_id)


def organize_legacy_assets(db: Database, avatar_id: str) -> dict[str, Any]:
    identity = create_asset_set(
        db, avatar_id, set_type="identity", semantic_key="default-identity", label="默认人物身份",
        invariants=["保持五官、脸型、发型和体型一致"],
        negative_constraints=["不要改变人物身份、年龄、脸型或主要发型"],
        status="candidate",
        metadata={"source": "legacy_visual_assets"},
    )
    existing_ids = {int(item.get("visual_asset_id") or 0) for item in identity["items"]}
    added = 0
    for asset in db.all("SELECT * FROM visual_assets WHERE avatar_id=? ORDER BY id", (avatar_id,)):
        if int(asset["id"]) in existing_ids:
            continue
        metadata = _loads(asset.get("metadata_json"), {})
        requested_type = str(metadata.get("set_type") or "identity")
        target = identity
        if requested_type in SET_TYPES and requested_type != "identity":
            target = create_asset_set(
                db, avatar_id, set_type=requested_type,
                semantic_key=str(metadata.get("semantic_key") or f"default-{requested_type}"),
                label=str(metadata.get("set_label") or {"wardrobe": "默认服装", "prop": "默认物品", "scene": "默认场景"}[requested_type]),
            )
        role = str(metadata.get("role") or "reference")
        if role not in ITEM_ROLES:
            role = "reference"
        add_asset_item(db, avatar_id, target["id"], visual_asset_id=int(asset["id"]), role=role)
        added += 1
    identity = get_asset_set(db, avatar_id, identity["id"])
    if identity["items"] and any(item["status"] in APPROVED_STATUSES for item in identity["items"]):
        update_asset_set(db, avatar_id, identity["id"], status="canonical" if any(item["status"] == "canonical" for item in identity["items"]) else "approved")
    return {"organized": added, "sets": list_asset_sets(db, avatar_id)}


def create_scene_profile(
    db: Database,
    avatar_id: str,
    *,
    display_name: str,
    semantic_key: str = "",
    stable_features: list[str] | None = None,
    negative_constraints: list[str] | None = None,
    topology: dict[str, Any] | None = None,
    status: str = "candidate",
    route: str = "image_bootstrap",
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    semantic_key = _key(semantic_key or display_name, "scene")
    existing = db.one("SELECT * FROM scene_profiles WHERE avatar_id=? AND semantic_key=?", (avatar_id, semantic_key))
    now = int(time.time())
    if existing:
        return public_scene(existing)
    scene_id = f"scene_{uuid.uuid4().hex[:16]}"
    db.execute(
        """
        INSERT INTO scene_profiles
        (id,avatar_id,semantic_key,display_name,status,route,stable_features_json,negative_constraints_json,topology_json,metadata_json,approved_at,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            scene_id, avatar_id, semantic_key, display_name.strip()[:200], status, route,
            json.dumps((stable_features or [])[:40], ensure_ascii=False),
            json.dumps((negative_constraints or [])[:40], ensure_ascii=False),
            json.dumps(topology or {}, ensure_ascii=False), json.dumps(metadata or {}, ensure_ascii=False),
            now if status in APPROVED_STATUSES else 0, now, now,
        ),
    )
    return public_scene(db.one("SELECT * FROM scene_profiles WHERE id=?", (scene_id,)) or {})


def public_scene(row: dict[str, Any]) -> dict[str, Any]:
    result = dict(row)
    for source, target, fallback in (
        ("stable_features_json", "stable_features", []),
        ("negative_constraints_json", "negative_constraints", []),
        ("topology_json", "topology", {}),
        ("metadata_json", "metadata", {}),
    ):
        result[target] = _loads(result.pop(source, None), fallback)
    return result


def list_scene_profiles(db: Database, avatar_id: str) -> list[dict[str, Any]]:
    return [public_scene(row) for row in db.all("SELECT * FROM scene_profiles WHERE avatar_id=? ORDER BY updated_at DESC", (avatar_id,))]


def update_scene_profile(db: Database, avatar_id: str, scene_id: str, patch: dict[str, Any]) -> dict[str, Any]:
    current = db.one("SELECT * FROM scene_profiles WHERE id=? AND avatar_id=?", (scene_id, avatar_id))
    if not current:
        raise KeyError("场景档案不存在")
    now = int(time.time())
    status = str(patch.get("status") or current["status"])
    route = str(patch.get("route") or current["route"])
    if route not in {"image_bootstrap", "image_grounded", "model_grounded"}:
        raise ValueError("场景路由不受支持")
    db.execute(
        """
        UPDATE scene_profiles SET display_name=?,status=?,route=?,stable_features_json=?,negative_constraints_json=?,topology_json=?,approved_at=?,updated_at=?
        WHERE id=? AND avatar_id=?
        """,
        (
            str(patch.get("display_name") or current["display_name"])[:200], status, route,
            json.dumps(patch.get("stable_features", _loads(current["stable_features_json"], [])), ensure_ascii=False),
            json.dumps(patch.get("negative_constraints", _loads(current["negative_constraints_json"], [])), ensure_ascii=False),
            json.dumps(patch.get("topology", _loads(current["topology_json"], {})), ensure_ascii=False),
            now if status in APPROVED_STATUSES else int(current.get("approved_at") or 0), now, scene_id, avatar_id,
        ),
    )
    return public_scene(db.one("SELECT * FROM scene_profiles WHERE id=?", (scene_id,)) or {})


def _world_place(db: Database, avatar_id: str) -> str:
    rows = db.all("SELECT fact_key,fact_value_json FROM world_facts WHERE avatar_id=? AND active=1 ORDER BY updated_at DESC LIMIT 80", (avatar_id,))
    for row in rows:
        key = str(row.get("fact_key") or "").lower()
        if any(token in key for token in ("place", "location", "home", "room", "地点", "家", "房间")):
            value = _loads(row.get("fact_value_json"), "")
            if isinstance(value, str) and value.strip() and value.strip().lower() not in {"未设定", "未知", "unknown", "unset", "none"}:
                return value.strip()[:200]
    return ""


def _select_set(sets: list[dict[str, Any]], set_type: str, prompt: str, requested: str = "") -> dict[str, Any] | None:
    candidates = [item for item in sets if item["set_type"] == set_type and item["status"] in APPROVED_STATUSES]
    if not candidates:
        return None
    text = f"{prompt} {requested}".lower()
    matched = [item for item in candidates if item["semantic_key"].lower() in text or str(item["label"]).lower() in text]
    return (matched or sorted(candidates, key=lambda item: (item["status"] == "canonical", item["updated_at"]), reverse=True))[0]


def build_continuity_contract(
    db: Database,
    avatar_id: str,
    prompt: str,
    *,
    hints: dict[str, Any] | None = None,
) -> dict[str, Any]:
    hints = hints or {}
    organize_legacy_assets(db, avatar_id)
    sets = list_asset_sets(db, avatar_id)
    identity = _select_set(sets, "identity", prompt, str(hints.get("identity") or ""))
    wardrobe = _select_set(sets, "wardrobe", prompt, str(hints.get("wardrobe") or ""))
    requested_props = hints.get("props") if isinstance(hints.get("props"), list) else []
    requested_props = [str(value).strip() for value in requested_props if str(value).strip()]
    legacy_prop = str(hints.get("prop") or "").strip()
    if legacy_prop:
        requested_props.append(legacy_prop)
    prop_candidates = [item for item in sets if item["set_type"] == "prop" and item["status"] in APPROVED_STATUSES]
    props: list[dict[str, Any]] = []
    searchable = f"{prompt} {' '.join(requested_props)}".lower()
    for item in prop_candidates:
        if item["semantic_key"].lower() in searchable or str(item["label"]).lower() in searchable:
            props.append(item)
    if not props and prop_candidates:
        props = sorted(prop_candidates, key=lambda item: (item["status"] == "canonical", item["updated_at"]), reverse=True)[:1]
    scenes = list_scene_profiles(db, avatar_id)
    requested_place = str(hints.get("scene") or hints.get("place") or "").strip()
    if not requested_place:
        world_place = _world_place(db, avatar_id)
        if world_place and world_place.lower() in prompt.lower():
            requested_place = world_place
    scene = None
    search_text = f"{prompt} {requested_place}".lower()
    for candidate in scenes:
        if candidate["semantic_key"].lower() in search_text or candidate["display_name"].lower() in search_text:
            scene = candidate
            break
    if scene is None and requested_place:
        scene = create_scene_profile(db, avatar_id, display_name=requested_place, metadata={"source": "world_or_request"})
    selected_sets = [item for item in (identity, wardrobe) if item] + props
    if scene:
        scene_set = _select_set(sets, "scene", prompt, scene["semantic_key"])
        if scene_set:
            selected_sets.append(scene_set)
            if scene["route"] == "image_bootstrap" and any(item["status"] in APPROVED_STATUSES for item in scene_set["items"]):
                scene = update_scene_profile(db, avatar_id, scene["id"], {"route": "image_grounded", "status": "approved"})
    references: list[dict[str, Any]] = []
    for asset_set in selected_sets:
        for item in asset_set["items"]:
            if item["status"] not in APPROVED_STATUSES:
                continue
            references.append({
                "set_id": asset_set["id"], "set_type": asset_set["set_type"], "semantic_key": asset_set["semantic_key"],
                "role": item["role"], "visual_asset_id": int(item.get("visual_asset_id") or 0),
                "local_path": item.get("local_path", ""), "remote_url": item.get("remote_url", ""), "asset_url": item.get("asset_url", ""),
            })
    first_frame = next(
        (item for item in references if item["set_type"] == "scene" and item["role"] in {"first_frame", "key_frame", "wide"}),
        None,
    ) or next(
        (item for item in references if item["set_type"] == "identity" and item["role"] in {"first_frame", "full_body", "reference", "front"}),
        None,
    )
    last_frame = next((item for item in references if item["role"] == "last_frame"), None)
    invariants: list[str] = []
    negatives: list[str] = []
    for asset_set in selected_sets:
        invariants.extend(str(value) for value in asset_set["invariants"])
        negatives.extend(str(value) for value in asset_set["negative_constraints"])
    if scene:
        invariants.extend(str(value) for value in scene["stable_features"])
        negatives.extend(str(value) for value in scene["negative_constraints"])
    missing = []
    if not identity:
        missing.append("identity")
    if scene and scene["route"] == "image_bootstrap":
        missing.append("scene_key_image")
    if not first_frame:
        missing.append("first_frame")
    contract = {
        "schema_version": "1.0",
        "avatar_id": avatar_id,
        "prompt": prompt,
        "identity_set_id": identity["id"] if identity else "",
        "wardrobe_set_id": wardrobe["id"] if wardrobe else "",
        "prop_set_ids": [prop["id"] for prop in props],
        "scene_profile_id": scene["id"] if scene else "",
        "scene_route": scene["route"] if scene else "unbound",
        "scene_topology": scene.get("topology", {}) if scene else {},
        "invariants": list(dict.fromkeys(invariants))[:60],
        "negative_constraints": list(dict.fromkeys(negatives))[:60],
        "references": references[:24],
        "first_frame": first_frame or {},
        "last_frame": last_frame or {},
        "storyboard": [str(value)[:500] for value in (hints.get("shots") or [])[:12] if str(value).strip()],
        "missing": list(dict.fromkeys(missing)),
        "ready_for_video": not missing,
    }
    return contract


def continuity_prompt(prompt: str, contract: dict[str, Any]) -> str:
    rules = contract.get("invariants") or []
    negatives = contract.get("negative_constraints") or []
    parts = [prompt.strip(), "连续性要求："]
    parts.extend(f"- {item}" for item in rules[:12])
    if negatives:
        parts.append("禁止变化：")
        parts.extend(f"- {item}" for item in negatives[:10])
    topology = contract.get("scene_topology") or {}
    if topology:
        parts.append("场景空间关系（镜头移动时不得颠倒）：")
        parts.append(json.dumps(topology, ensure_ascii=False, separators=(",", ":"))[:1000])
    storyboard = contract.get("storyboard") or []
    if storyboard:
        parts.append("镜头顺序（按顺序完成，不得跨镜头改变身份或物品）：")
        parts.extend(f"{index + 1}. {shot}" for index, shot in enumerate(storyboard[:12]))
    return "\n".join(parts)[:6000]


def create_continuity_run(db: Database, avatar_id: str, job_id: str, prompt: str, contract: dict[str, Any]) -> dict[str, Any]:
    run_id = f"cr_{uuid.uuid4().hex[:16]}"
    now = int(time.time())
    manifest = {"references": contract.get("references", []), "reference_count": len(contract.get("references", []))}
    first_frame = contract.get("first_frame") or {}
    db.execute(
        """
        INSERT INTO continuity_runs
        (id,avatar_id,job_id,status,prompt,scene_profile_id,first_frame_asset_id,contract_json,reference_manifest_json,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?,?,?)
        """,
        (
            run_id, avatar_id, job_id, "ready" if contract.get("ready_for_video") else "needs_key_image", prompt,
            str(contract.get("scene_profile_id") or ""), int(first_frame.get("visual_asset_id") or 0),
            json.dumps(contract, ensure_ascii=False), json.dumps(manifest, ensure_ascii=False), now, now,
        ),
    )
    return get_continuity_run(db, avatar_id, run_id)


def get_continuity_run(db: Database, avatar_id: str, run_id: str) -> dict[str, Any]:
    row = db.one("SELECT * FROM continuity_runs WHERE id=? AND avatar_id=?", (run_id, avatar_id))
    if not row:
        raise KeyError("连续性任务不存在")
    for source, target in (("contract_json", "contract"), ("reference_manifest_json", "reference_manifest"), ("review_json", "review")):
        row[target] = _loads(row.pop(source, "{}"), {})
    return row


def list_continuity_runs(db: Database, avatar_id: str, limit: int = 50) -> list[dict[str, Any]]:
    rows = db.all("SELECT id FROM continuity_runs WHERE avatar_id=? ORDER BY created_at DESC LIMIT ?", (avatar_id, min(max(limit, 1), 200)))
    return [get_continuity_run(db, avatar_id, str(row["id"])) for row in rows]


def update_continuity_run(db: Database, run_id: str, *, status: str, provider: str = "", provider_task_id: str = "", review: dict[str, Any] | None = None) -> None:
    fields = ["status=?", "updated_at=?"]
    values: list[Any] = [status, int(time.time())]
    for key, value in (("provider", provider), ("provider_task_id", provider_task_id)):
        if value:
            fields.append(f"{key}=?")
            values.append(value)
    if review is not None:
        fields.append("review_json=?")
        values.append(json.dumps(review, ensure_ascii=False))
    values.append(run_id)
    db.execute(f"UPDATE continuity_runs SET {', '.join(fields)} WHERE id=?", tuple(values))


def extract_video_keyframes(settings: Settings, db: Database, avatar_id: str, job_id: str, run_id: str, video_path: Path, contract: dict[str, Any]) -> list[dict[str, Any]]:
    if not video_path.is_file() or shutil.which("ffmpeg") is None:
        return []
    output_dir = settings.avatars_dir / avatar_id / "generated" / "video_keyframes" / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    pattern = output_dir / "frame-%02d.jpg"
    command = [
        "ffmpeg", "-y", "-i", str(video_path), "-vf", "fps=1/2,scale=720:-2", "-frames:v", "3", str(pattern),
    ]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    if completed.returncode != 0:
        return []
    rows: list[dict[str, Any]] = []
    binding = {
        "scene_profile_id": contract.get("scene_profile_id", ""),
        "identity_set_id": contract.get("identity_set_id", ""),
        "wardrobe_set_id": contract.get("wardrobe_set_id", ""),
        "prop_set_ids": contract.get("prop_set_ids", []),
    }
    extracted = sorted(output_dir.glob("frame-*.jpg"))[:3]
    largest = max((path.stat().st_size for path in extracted), default=1)
    for index, path in enumerate(extracted):
        relative = str(path.relative_to(settings.data_dir))
        size_score = min(35, round(path.stat().st_size / largest * 35))
        temporal_score = 15 if index == 1 else 10
        quality_score = 45 + size_score + temporal_score
        row_id = db.execute(
            "INSERT INTO video_keyframes(avatar_id,job_id,continuity_run_id,local_path,position_ms,quality_score,status,binding_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
            (avatar_id, job_id, run_id, relative, index * 2000, quality_score, "history_reference", json.dumps(binding, ensure_ascii=False), int(time.time())),
        )
        rows.append({"id": row_id, "local_path": relative, "position_ms": index * 2000, "quality_score": quality_score, "binding": binding})
    return rows


def finalize_video_continuity(
    db: Database,
    settings: Settings,
    *,
    avatar_id: str,
    job_id: str,
    run_id: str,
    video_path: Path,
) -> dict[str, Any]:
    run = get_continuity_run(db, avatar_id, run_id)
    frames = extract_video_keyframes(settings, db, avatar_id, job_id, run_id, video_path, run["contract"])
    from openavatar.services.video_review import review_video_frames

    visual_review = review_video_frames(db, settings, avatar_id=avatar_id, contract=run["contract"], keyframes=frames)
    if not visual_review.get("sendable", True):
        db.execute("UPDATE video_keyframes SET status='rejected' WHERE continuity_run_id=?", (run_id,))
        for frame in frames:
            frame["status"] = "rejected"
    findings = [
        {"dimension": "downloaded_video", "passed": video_path.is_file() and video_path.stat().st_size > 0, "note": "视频文件已安全下载"},
        {"dimension": "continuity_contract", "passed": bool(run["contract"].get("identity_set_id")), "note": "已冻结人物、场景、服装和物品引用"},
        {"dimension": "keyframe_feedback", "passed": bool(frames), "note": "合格关键帧已进入历史参考库" if frames else "当前环境无法抽帧，需人工复核"},
        {"dimension": "visual_continuity", "passed": bool(visual_review.get("sendable", False)), "note": str(visual_review.get("reason") or ("视觉模型验收通过" if visual_review.get("available") else "需要人工复核"))},
    ]
    score = round(sum(1 for item in findings if item["passed"]) / len(findings) * 100)
    review = {"score": score, "sendable": all(item["passed"] for item in findings[:2]) and bool(visual_review.get("sendable", False)), "manual_review": bool(visual_review.get("manual_review")), "findings": findings, "keyframes": frames, "visual_review": visual_review}
    now = int(time.time())
    db.execute(
        "INSERT INTO media_reviews(avatar_id,media_kind,asset_id,review_kind,status,score,findings_json,user_feedback_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
        (avatar_id, "video", 0, "continuity_and_artifact_review", "completed", score, json.dumps(findings, ensure_ascii=False), "{}", now, now),
    )
    update_continuity_run(db, run_id, status="approved" if review["sendable"] else "needs_review", review=review)
    return review


def list_video_keyframes(db: Database, avatar_id: str, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.all("SELECT * FROM video_keyframes WHERE avatar_id=? ORDER BY id DESC LIMIT ?", (avatar_id, min(max(limit, 1), 300)))
    for row in rows:
        row["binding"] = _loads(row.pop("binding_json", "{}"), {})
        row["asset_url"] = f"/api/avatars/{avatar_id}/video-keyframes/{row['id']}/file"
    return rows


def register_key_image_candidate(
    db: Database,
    settings: Settings,
    *,
    avatar_id: str,
    local_path: Path,
    provider: str,
    remote_url: str = "",
    scene_profile_id: str = "",
    label: str = "场景关键首帧候选",
) -> dict[str, Any]:
    relative = str(local_path.resolve().relative_to(settings.data_dir.resolve()))
    scene = db.one("SELECT * FROM scene_profiles WHERE id=? AND avatar_id=?", (scene_profile_id, avatar_id)) if scene_profile_id else None
    semantic_key = str((scene or {}).get("semantic_key") or "default-scene")
    asset_set = create_asset_set(
        db,
        avatar_id,
        set_type="scene",
        semantic_key=semantic_key,
        label=str((scene or {}).get("display_name") or label),
        status="candidate",
        metadata={"scene_profile_id": scene_profile_id, "generated_key_image": True},
    )
    now = int(time.time())
    asset_id = db.execute(
        "INSERT INTO visual_assets(avatar_id,asset_kind,status,label,local_path,provider,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?)",
        (
            avatar_id,
            "scene_key_image",
            "candidate",
            label[:200],
            relative,
            provider[:80],
            json.dumps({
                "set_type": "scene",
                "semantic_key": semantic_key,
                "continuity_set_id": asset_set["id"],
                "scene_profile_id": scene_profile_id,
                "role": "first_frame",
                "generated_key_image": True,
            }, ensure_ascii=False),
            now,
        ),
    )
    add_asset_item(
        db,
        avatar_id,
        asset_set["id"],
        visual_asset_id=asset_id,
        role="first_frame",
        remote_url=remote_url if remote_url.startswith("https://") else "",
        status="candidate",
    )
    return {"visual_asset_id": asset_id, "asset_set_id": asset_set["id"], "scene_profile_id": scene_profile_id}


def approve_linked_visual_asset(db: Database, avatar_id: str, asset_id: int, status: str) -> dict[str, Any] | None:
    asset = db.one("SELECT * FROM visual_assets WHERE id=? AND avatar_id=?", (asset_id, avatar_id))
    if not asset:
        return None
    metadata = _loads(asset.get("metadata_json"), {})
    set_id = str(metadata.get("continuity_set_id") or "")
    if not set_id:
        return None
    role = str(metadata.get("role") or "reference")
    add_asset_item(db, avatar_id, set_id, visual_asset_id=asset_id, role=role, status=status)
    updated = update_asset_set(db, avatar_id, set_id, status="canonical" if status == "canonical" else "approved")
    scene_id = str(metadata.get("scene_profile_id") or "")
    if scene_id and status in APPROVED_STATUSES:
        update_scene_profile(db, avatar_id, scene_id, {"status": "approved", "route": "image_grounded"})
    return updated
