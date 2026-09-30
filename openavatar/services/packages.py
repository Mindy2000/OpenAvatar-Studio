from __future__ import annotations

import json
import shutil
import sqlite3
import time
import uuid
import zipfile
from pathlib import Path, PureWindowsPath

from openavatar.db import Database
from openavatar.services.world_regions import avatar_language_profile


PACKAGE_REQUIRED_FILES = ("manifest.json", "memories.json", "messages.json")
PACKAGE_OPTIONAL_FILES = (
    "evidence.json", "rights.json", "world_facts.json", "world_events.json", "world_fact_proposals.json",
    "world_modules.json", "world_runtime_settings.json", "visual_assets.json", "voice_profiles.json",
    "visual_asset_sets.json", "scene_profiles.json", "video_keyframes.json",
    "voice_transcriptions.json", "build_reports.json", "builder_answers.json", "quality_evaluations.json",
    "proactive_rules.json", "world_conflicts.json", "world_snapshots.json", "memory_revisions.json",
    "memory_graph_nodes.json", "memory_graph_edges.json", "persona_core.json", "persona_feedback_rules.json",
    "decision_explanations.json", "usage_events.json", "media_reviews.json", "voice_events.json",
    "realtime_call_sessions.json", "realtime_call_turns.json", "imports.json", "provider_assets.json",
    "language_profile.json", "world_region_profile.json",
)


def _validate_zip_members(members: list[zipfile.ZipInfo]) -> None:
    max_files = 2000
    max_uncompressed = 1024 * 1024 * 1024
    if len(members) > max_files:
        raise ValueError("人物包文件数量过多")
    if sum(item.file_size for item in members) > max_uncompressed:
        raise ValueError("人物包解压后超过 1GB 限制")
    for item in members:
        path = Path(item.filename)
        if path.is_absolute() or ".." in path.parts or "\\" in item.filename or PureWindowsPath(item.filename).drive:
            raise ValueError("人物包包含非法路径")


def _validate_manifest(manifest: object) -> None:
    if not isinstance(manifest, dict):
        raise ValueError("人物包清单必须是 JSON 对象")
    try:
        version = int(manifest.get("version", 0))
    except (TypeError, ValueError) as exc:
        raise ValueError("人物包版本无效") from exc
    if manifest.get("format") != "openavatar.package" or version not in {1, 2, 3}:
        raise ValueError("人物包格式或版本不受支持")
    for section in ("avatar", "persona"):
        if section in manifest and not isinstance(manifest[section], dict):
            raise ValueError(f"人物包 {section} 必须是 JSON 对象")


def inspect_avatar_package(archive_path: Path) -> dict:
    try:
        with zipfile.ZipFile(archive_path) as archive:
            members = archive.infolist()
            _validate_zip_members(members)
            names = {item.filename for item in members}
            missing = [name for name in PACKAGE_REQUIRED_FILES if name not in names]
            if missing:
                raise ValueError(f"人物包缺少必要文件：{', '.join(missing)}")
            manifest = json.loads(archive.read("manifest.json"))
            _validate_manifest(manifest)
            avatar = manifest.get("avatar") or {}
            persona = manifest.get("persona") or {}
            language_profile = manifest.get("language_profile") if isinstance(manifest.get("language_profile"), dict) else {}
            warnings: list[str] = []
            if manifest.get("contains_api_keys"):
                warnings.append("清单声明可能包含 API Key。OpenAvatar 不会自动导入密钥。")
            if "rights.json" not in names:
                warnings.append("人物包缺少授权记录，导入后会以本次用户确认作为本地使用授权。")
            if manifest.get("version") == 1:
                warnings.append("这是 v1 人物包，导入后会按 v2 结构补齐缺省字段。")
            return {
                "ok": True,
                "format": manifest.get("format"),
                "version": int(manifest.get("version", 0)),
                "name": str(avatar.get("name", ""))[:80],
                "subject_kind": str(avatar.get("subject_kind", "fictional")),
                "relationship": str(avatar.get("relationship", "朋友"))[:80],
                "persona_summary": str(persona.get("summary", ""))[:240],
                "language_profile": language_profile,
                "world_region": str(language_profile.get("world_region", avatar.get("world_region", ""))),
                "avatar_primary_language": str(language_profile.get("avatar_primary_language", avatar.get("avatar_primary_language", ""))),
                "contains_api_keys": bool(manifest.get("contains_api_keys", False)),
                "model_provider_portable": bool(manifest.get("model_provider_portable", False)),
                "model_connection_hint": manifest.get("model_connection_hint") if isinstance(manifest.get("model_connection_hint"), dict) else {},
                "file_count": len(members),
                "asset_count": sum(1 for item in members if item.filename.startswith("assets/") and not item.is_dir()),
                "uncompressed_bytes": sum(item.file_size for item in members),
                "included_sections": [name for name in PACKAGE_REQUIRED_FILES + PACKAGE_OPTIONAL_FILES if name in names],
                "warnings": warnings,
            }
    except (zipfile.BadZipFile, KeyError, json.JSONDecodeError) as exc:
        raise ValueError("人物包无法读取或 JSON 已损坏") from exc


def export_avatar(
    db: Database,
    avatars_dir: Path,
    exports_dir: Path,
    avatar_id: str,
    *,
    include_conversations: bool = True,
    include_audio: bool = True,
    include_images: bool = True,
    include_video: bool = True,
    include_call_history: bool = True,
) -> Path:
    avatar = db.one("SELECT * FROM avatars WHERE id=?", (avatar_id,))
    if not avatar:
        raise KeyError("数字人不存在")
    persona = db.one("SELECT * FROM persona_profiles WHERE avatar_id=?", (avatar_id,)) or {}
    memories = db.all(
        "SELECT speaker,content,kind,is_avatar,confidence,created_at FROM memories WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    evidence = db.all(
        "SELECT source_type,title,content,tags_json,derived_kind,confidence,created_at FROM evidence WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    messages = db.all(
        "SELECT role,content,channel,created_at FROM messages WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    rights = db.all(
        "SELECT grant_type,subject_kind,rights_scope,data_classes_json,provider_transfer_allowed,commercial_use_allowed,revocable,note,confirmed_at FROM rights_grants WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    world_facts = db.all(
        "SELECT fact_key,fact_value_json,reality_kind,mutability,status,confidence,active,created_at,updated_at FROM world_facts WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    world_events = db.all(
        "SELECT event_key,title,summary,event_kind,status,occurred_at,payload_json,created_at FROM world_events WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    world_fact_proposals = db.all(
        "SELECT fact_key,fact_value_json,reality_kind,mutability,status,reason,review_note,created_at,reviewed_at FROM world_fact_proposals WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    world_modules = db.all(
        "SELECT module_key,module_name,category,required,enabled,status,description,created_at,updated_at FROM world_modules WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    world_runtime_settings = db.one(
        "SELECT engine_enabled,world_clock_enabled,npc_autonomy_enabled,relationship_progression_enabled,consistency_scan_enabled,auto_minor_events,high_impact_requires_review,rollback_enabled,active_seconds,last_advanced_at,updated_at FROM world_runtime_settings WHERE avatar_id=?",
        (avatar_id,),
    ) or {}
    visual_assets = db.all(
        "SELECT asset_kind,status,label,local_path,provider,metadata_json,approved_at,created_at FROM visual_assets WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    visual_asset_sets = db.all(
        "SELECT id,set_type,semantic_key,label,status,version,invariants_json,negative_constraints_json,metadata_json,approved_at,created_at,updated_at FROM visual_asset_sets WHERE avatar_id=? ORDER BY created_at,id",
        (avatar_id,),
    )
    for asset_set in visual_asset_sets:
        asset_set["items"] = db.all(
            "SELECT role,local_path,remote_url,content_sha256,status,quality_score,metadata_json,created_at FROM visual_asset_items WHERE set_id=? ORDER BY id",
            (asset_set["id"],),
        )
    scene_profiles = db.all(
        "SELECT semantic_key,display_name,status,route,stable_features_json,negative_constraints_json,topology_json,metadata_json,approved_at,created_at,updated_at FROM scene_profiles WHERE avatar_id=? ORDER BY created_at,id",
        (avatar_id,),
    )
    video_keyframes = db.all(
        "SELECT job_id,local_path,position_ms,quality_score,status,binding_json,created_at FROM video_keyframes WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    voice_profiles = db.all(
        "SELECT provider,voice_id,voice_name,profile_kind,status,model,metadata_json,active,created_at FROM voice_profiles WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    voice_transcriptions = db.all(
        "SELECT provider,model,transcript,status,confidence,metadata_json,created_at,confirmed_at FROM voice_transcriptions WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    build_reports = db.all(
        "SELECT report_kind,status,score,checks_json,recommendations_json,created_at FROM build_reports WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    builder_answers = db.all(
        "SELECT route,question_key,question_text,answer,created_at FROM builder_answers WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    quality_evaluations = db.all(
        "SELECT evaluation_kind,status,score,checks_json,samples_json,user_feedback_json,created_at,updated_at FROM quality_evaluations WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    world_conflicts = db.all(
        "SELECT fact_key,existing_value_json,candidate_value_json,reason,status,review_note,created_at,resolved_at FROM world_conflicts WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    world_snapshots = db.all(
        "SELECT event_id,day_key,facts_json,settings_json,created_at,rolled_back_at FROM world_snapshots WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    memory_revisions = db.all(
        "SELECT memory_id,before_json,after_json,action,note,created_at FROM memory_revisions WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    memory_graph_nodes = db.all(
        "SELECT node_key,label,node_type,weight,evidence_count,metadata_json,updated_at FROM memory_graph_nodes WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    memory_graph_edges = db.all(
        "SELECT source_key,target_key,relation,weight,evidence_count,updated_at FROM memory_graph_edges WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    persona_core = db.one(
        "SELECT core_json,source_digest,created_at,updated_at FROM persona_core_profiles WHERE avatar_id=?",
        (avatar_id,),
    ) or {}
    persona_feedback = db.all(
        "SELECT dimension,signal,rule_text,weight,active,created_at,updated_at FROM persona_feedback_rules WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    decision_explanations = db.all(
        "SELECT message_id,decision_kind,input_summary,output_summary,metadata_json,created_at FROM decision_explanations WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    usage_events = db.all(
        "SELECT provider,model,role,operation,status,latency_ms,estimated_cost,metadata_json,created_at FROM usage_events WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    media_reviews = db.all(
        "SELECT media_kind,asset_id,review_kind,status,score,findings_json,user_feedback_json,created_at,updated_at FROM media_reviews WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    voice_events = db.all(
        "SELECT event_kind,transcript_id,profile_id,emotion,tone,confidence,metadata_json,created_at FROM voice_events WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    call_sessions = db.all(
        "SELECT status,provider,started_at,ended_at,summary,metadata_json FROM realtime_call_sessions WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    call_turns = db.all(
        "SELECT call_session_id,user_transcript,assistant_text,asr_latency_ms,llm_latency_ms,tts_latency_ms,interrupted,metadata_json,created_at FROM realtime_call_turns WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    imports = db.all(
        "SELECT id,category,original_name,stored_path,media_type,size_bytes,status,note,created_at FROM imports WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    provider_assets = db.all(
        "SELECT kind,provider,external_id,metadata_json,active,created_at FROM provider_assets WHERE avatar_id=? ORDER BY id",
        (avatar_id,),
    )
    proactive_rules = db.one(
        "SELECT daily_max,allowed_windows_json,quiet_hours_json,topic_scope_json,use_long_term_memory,allow_world_event_advancement,tone,cooldown_after_user_reply_minutes,updated_at FROM proactive_rules WHERE avatar_id=?",
        (avatar_id,),
    ) or {}
    model_settings = db.one(
        "SELECT mode,connection_id,provider_name,base_url,model,ollama_url,ollama_model,cloud_data_consent,updated_at FROM avatar_model_settings WHERE avatar_id=?",
        (avatar_id,),
    ) or {}
    connection_hint = {}
    if model_settings.get("connection_id"):
        connection_hint = db.one(
            "SELECT display_name,connection_type,provider_name,base_url,model,adapter_kind,cloud_data_consent,local_only,updated_at FROM model_connections WHERE id=?",
            (model_settings["connection_id"],),
        ) or {}
    if not include_conversations:
        messages = []
        # These auxiliary records can contain verbatim chat inputs and replies.
        decision_explanations = []
        memory_revisions = []
        memory_graph_nodes = []
        memory_graph_edges = []
        persona_core = {}
        memories = [row for row in memories if str(row.get("kind")) not in {"conversation", "imported"}]
        evidence = [row for row in evidence if str(row.get("source_type")) not in {"real_conversation", "real_avatar_utterances", "real_image_ocr"}]
        imports = [row for row in imports if str(row.get("category")) != "conversation"]
    if not include_audio:
        imports = [row for row in imports if str(row.get("category")) != "audio"]
        voice_transcriptions = []
        provider_assets = [row for row in provider_assets if str(row.get("kind")) != "voice"]
    if not include_images:
        imports = [row for row in imports if str(row.get("category")) != "image"]
        visual_assets = []
        visual_asset_sets = []
        scene_profiles = []
        video_keyframes = []
        media_reviews = [row for row in media_reviews if str(row.get("media_kind")) not in {"visual", "video"}]
        provider_assets = [row for row in provider_assets if str(row.get("kind")) != "visual"]
    if not include_video:
        video_keyframes = []
        provider_assets = [row for row in provider_assets if str(row.get("kind")) != "video"]
        media_reviews = [row for row in media_reviews if str(row.get("media_kind")) != "video"]
    if not include_call_history:
        call_sessions = []
        call_turns = []
    timestamp = time.strftime("%Y%m%d-%H%M%S")
    target = exports_dir / f"{avatar_id}-{timestamp}-{uuid.uuid4().hex[:8]}.openavatar.zip"
    manifest = {
        "format": "openavatar.package",
        "version": 3,
        "exported_at": int(time.time()),
        "protocol": {
            "required_files": list(PACKAGE_REQUIRED_FILES),
            "optional_files": list(PACKAGE_OPTIONAL_FILES),
            "import_requires_user_confirmation": True,
            "api_keys_are_never_exported": True,
            "model_connections_must_be_rebound_after_import": True,
        },
        "model_provider_portable": True,
        "contains_api_keys": False,
        "privacy": {
            "contains_original_assets": bool(imports),
            "contains_conversation_history": bool(messages or any(row.get("category") == "conversation" for row in imports)),
            "contains_audio_files": bool(include_audio and any(row.get("category") == "audio" for row in imports)),
            "contains_image_files": bool(include_images and any(row.get("category") == "image" for row in imports)),
            "contains_video_files": bool(include_video and any((avatars_dir / avatar_id / "generated" / "video").glob("*"))),
            "contains_call_history": bool(call_sessions or call_turns),
            "contains_voice_metadata": bool(voice_profiles or voice_transcriptions or voice_events),
            "contains_visual_metadata": bool(visual_assets or visual_asset_sets or scene_profiles or media_reviews),
            "contains_runtime_world": bool(world_facts or world_events or world_runtime_settings),
        },
        "avatar": avatar,
        "persona": persona,
        "language_profile": avatar_language_profile(avatar),
        "world_region_profile": avatar_language_profile(avatar).get("world_region_rules", {}),
        "avatar_model_settings": model_settings,
        "model_connection_hint": connection_hint,
    }
    with zipfile.ZipFile(target, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        archive.writestr("language_profile.json", json.dumps(manifest["language_profile"], ensure_ascii=False, indent=2))
        archive.writestr("world_region_profile.json", json.dumps(manifest["world_region_profile"], ensure_ascii=False, indent=2))
        archive.writestr("evidence.json", json.dumps(evidence, ensure_ascii=False, indent=2))
        archive.writestr("memories.json", json.dumps(memories, ensure_ascii=False, indent=2))
        archive.writestr("messages.json", json.dumps(messages, ensure_ascii=False, indent=2))
        archive.writestr("rights.json", json.dumps(rights, ensure_ascii=False, indent=2))
        archive.writestr("world_facts.json", json.dumps(world_facts, ensure_ascii=False, indent=2))
        archive.writestr("world_events.json", json.dumps(world_events, ensure_ascii=False, indent=2))
        archive.writestr("world_fact_proposals.json", json.dumps(world_fact_proposals, ensure_ascii=False, indent=2))
        archive.writestr("world_modules.json", json.dumps(world_modules, ensure_ascii=False, indent=2))
        archive.writestr("world_runtime_settings.json", json.dumps(world_runtime_settings, ensure_ascii=False, indent=2))
        archive.writestr("visual_assets.json", json.dumps(visual_assets, ensure_ascii=False, indent=2))
        archive.writestr("visual_asset_sets.json", json.dumps(visual_asset_sets, ensure_ascii=False, indent=2))
        archive.writestr("scene_profiles.json", json.dumps(scene_profiles, ensure_ascii=False, indent=2))
        archive.writestr("video_keyframes.json", json.dumps(video_keyframes, ensure_ascii=False, indent=2))
        archive.writestr("voice_profiles.json", json.dumps(voice_profiles, ensure_ascii=False, indent=2))
        archive.writestr("voice_transcriptions.json", json.dumps(voice_transcriptions, ensure_ascii=False, indent=2))
        archive.writestr("build_reports.json", json.dumps(build_reports, ensure_ascii=False, indent=2))
        archive.writestr("builder_answers.json", json.dumps(builder_answers, ensure_ascii=False, indent=2))
        archive.writestr("quality_evaluations.json", json.dumps(quality_evaluations, ensure_ascii=False, indent=2))
        archive.writestr("proactive_rules.json", json.dumps(proactive_rules, ensure_ascii=False, indent=2))
        archive.writestr("world_conflicts.json", json.dumps(world_conflicts, ensure_ascii=False, indent=2))
        archive.writestr("world_snapshots.json", json.dumps(world_snapshots, ensure_ascii=False, indent=2))
        archive.writestr("memory_revisions.json", json.dumps(memory_revisions, ensure_ascii=False, indent=2))
        archive.writestr("memory_graph_nodes.json", json.dumps(memory_graph_nodes, ensure_ascii=False, indent=2))
        archive.writestr("memory_graph_edges.json", json.dumps(memory_graph_edges, ensure_ascii=False, indent=2))
        archive.writestr("persona_core.json", json.dumps(persona_core, ensure_ascii=False, indent=2))
        archive.writestr("persona_feedback_rules.json", json.dumps(persona_feedback, ensure_ascii=False, indent=2))
        archive.writestr("decision_explanations.json", json.dumps(decision_explanations, ensure_ascii=False, indent=2))
        archive.writestr("usage_events.json", json.dumps(usage_events, ensure_ascii=False, indent=2))
        archive.writestr("media_reviews.json", json.dumps(media_reviews, ensure_ascii=False, indent=2))
        archive.writestr("voice_events.json", json.dumps(voice_events, ensure_ascii=False, indent=2))
        archive.writestr("realtime_call_sessions.json", json.dumps(call_sessions, ensure_ascii=False, indent=2))
        archive.writestr("realtime_call_turns.json", json.dumps(call_turns, ensure_ascii=False, indent=2))
        archive.writestr("imports.json", json.dumps(imports, ensure_ascii=False, indent=2))
        archive.writestr("provider_assets.json", json.dumps(provider_assets, ensure_ascii=False, indent=2))
        asset_root = avatars_dir / avatar_id
        included_asset_paths = {
            str(row.get("stored_path", "")).replace("\\", "/").removeprefix(f"avatars/{avatar_id}/")
            for row in imports
            if row.get("stored_path")
        }
        if asset_root.exists():
            for path in asset_root.rglob("*"):
                if path.is_file():
                    relative = path.relative_to(asset_root)
                    relative_text = str(relative).replace("\\", "/")
                    if relative.parts and relative.parts[0] == "imports" and relative_text not in included_asset_paths:
                        continue
                    if relative.parts[:2] == ("generated", "audio") and not include_audio:
                        continue
                    if relative.parts[:2] in {("generated", "images"), ("generated", "video_keyframes")} and not include_images:
                        continue
                    if relative.parts[:2] == ("generated", "video") and not include_video:
                        continue
                    archive.write(path, Path("assets") / relative)
    return target


def delete_avatar_files(avatars_dir: Path, avatar_id: str) -> None:
    target = (avatars_dir / avatar_id).resolve()
    if target.parent != avatars_dir.resolve():
        raise ValueError("非法人物目录")
    shutil.rmtree(target, ignore_errors=True)


def import_avatar_package(db: Database, avatars_dir: Path, archive_path: Path) -> dict:
    with zipfile.ZipFile(archive_path) as archive:
        members = archive.infolist()
        _validate_zip_members(members)
        try:
            manifest = json.loads(archive.read("manifest.json"))
            memories = json.loads(archive.read("memories.json"))
            messages = json.loads(archive.read("messages.json"))
            try:
                evidence = json.loads(archive.read("evidence.json"))
            except KeyError:
                evidence = []
            optional = {}
            for name in [
                "rights", "world_facts", "world_events", "world_fact_proposals", "world_modules", "world_runtime_settings",
                "visual_assets", "voice_profiles", "voice_transcriptions", "build_reports", "builder_answers", "quality_evaluations",
                "visual_asset_sets", "scene_profiles", "video_keyframes",
                "proactive_rules", "world_conflicts", "world_snapshots", "memory_revisions", "memory_graph_nodes", "memory_graph_edges",
                "persona_core", "persona_feedback_rules", "decision_explanations", "usage_events", "media_reviews", "voice_events",
                "realtime_call_sessions", "realtime_call_turns", "imports", "provider_assets",
            ]:
                try:
                    optional[name] = json.loads(archive.read(f"{name}.json"))
                except KeyError:
                    optional[name] = {} if name in {"world_runtime_settings", "proactive_rules", "persona_core"} else []
        except (KeyError, json.JSONDecodeError) as exc:
            raise ValueError("人物包缺少必要文件或 JSON 已损坏") from exc
        _validate_manifest(manifest)
        for section, rows in (("memories", memories), ("messages", messages), ("evidence", evidence)):
            if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
                raise ValueError(f"人物包 {section} 必须是 JSON 对象数组")
        avatar = manifest.get("avatar") or {}
        persona = manifest.get("persona") or {}
        language_profile = manifest.get("language_profile") if isinstance(manifest.get("language_profile"), dict) else {}
        model_settings = manifest.get("avatar_model_settings") if isinstance(manifest.get("avatar_model_settings"), dict) else {}
        connection_hint = manifest.get("model_connection_hint") if isinstance(manifest.get("model_connection_hint"), dict) else {}
        if not str(avatar.get("name", "")).strip():
            raise ValueError("人物包缺少人物名称")
        new_id = uuid.uuid4().hex[:12]
        old_id = str(avatar.get("id") or "")
        now = int(time.time())

        def remap_asset_path(value: object) -> str:
            raw = str(value or "").replace("\\", "/").lstrip("/")
            prefixes = [f"avatars/{old_id}/", f"{old_id}/"] if old_id else []
            for prefix in prefixes:
                if raw.startswith(prefix):
                    raw = raw[len(prefix):]
                    break
            path = Path(raw)
            if path.is_absolute() or ".." in path.parts:
                return ""
            return (Path("avatars") / new_id / path).as_posix()

        with db.transaction() as connection:
            connection.execute(
                    "INSERT INTO avatars(id,name,purpose,relationship,subject_kind,adult_subject,consent_confirmed,proactive_enabled,proactive_interval_minutes,usage_mode,avatar_primary_language,avatar_secondary_languages,avatar_response_mode,world_region,world_type,world_region_custom_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (
                    new_id,
                    str(avatar["name"])[:80],
                    str(avatar.get("purpose", ""))[:500],
                    str(avatar.get("relationship", "朋友"))[:80],
                    str(avatar.get("subject_kind", "fictional")) if avatar.get("subject_kind") in {"self", "authorized_person", "fictional"} else "fictional",
                    int(bool(avatar.get("adult_subject", True))),
                    1,
                    0,
                    min(max(int(avatar.get("proactive_interval_minutes", 360)), 15), 10080),
                    "preview",
                    str(avatar.get("avatar_primary_language") or language_profile.get("avatar_primary_language") or "zh-CN")[:40],
                    str(avatar.get("avatar_secondary_languages") or json.dumps(language_profile.get("avatar_secondary_languages", []), ensure_ascii=False))[:2000],
                    str(avatar.get("avatar_response_mode") or language_profile.get("avatar_response_mode") or "follow_user")[:40],
                    str(avatar.get("world_region") or language_profile.get("world_region") or "mainland_china")[:80],
                    str(avatar.get("world_type") or language_profile.get("world_type") or "realistic")[:40],
                    str(avatar.get("world_region_custom_json") or json.dumps(language_profile.get("world_region_custom", {}), ensure_ascii=False))[:100000],
                    now,
                    now,
                ),
            )
            for row in optional["imports"][:100000] if isinstance(optional["imports"], list) else []:
                if not isinstance(row, dict):
                    continue
                stored_path = remap_asset_path(row.get("stored_path"))
                if not stored_path:
                    continue
                connection.execute(
                    "INSERT INTO imports(avatar_id,category,original_name,stored_path,media_type,size_bytes,status,note,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("category", "document"))[:80],
                        str(row.get("original_name", "人物包素材"))[:255],
                        stored_path,
                        str(row.get("media_type", ""))[:120],
                        max(0, int(row.get("size_bytes", 0))),
                        str(row.get("status", "confirmed"))[:50],
                        str(row.get("note", "从人物包恢复"))[:1000],
                        int(row.get("created_at", now)),
                    ),
                )
            traits_json = persona.get("traits_json", "[]")
            if not isinstance(traits_json, str):
                traits_json = json.dumps(traits_json, ensure_ascii=False)
            connection.execute(
                "INSERT INTO persona_profiles(avatar_id,summary,traits_json,speaking_style,boundaries,source_count,updated_at) VALUES(?,?,?,?,?,?,?)",
                (
                    new_id,
                    str(persona.get("summary", ""))[:10000],
                    traits_json,
                    str(persona.get("speaking_style", ""))[:10000],
                    str(persona.get("boundaries", ""))[:10000],
                    min(max(int(persona.get("source_count", 0)), 0), 1000000),
                    now,
                ),
            )
            for row in memories[:200000] if isinstance(memories, list) else []:
                if not isinstance(row, dict) or not str(row.get("content", "")).strip():
                    continue
                connection.execute(
                    "INSERT INTO memories(avatar_id,speaker,content,kind,is_avatar,confidence,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        new_id, str(row.get("speaker", ""))[:100], str(row["content"])[:100000],
                        str(row.get("kind", "imported"))[:50], int(bool(row.get("is_avatar", False))),
                        min(max(float(row.get("confidence", 1)), 0), 1), int(row.get("created_at", now)),
                    ),
                )
            for row in evidence[:200000] if isinstance(evidence, list) else []:
                if not isinstance(row, dict) or not str(row.get("content", "")).strip():
                    continue
                tags_json = row.get("tags_json", "[]")
                if not isinstance(tags_json, str):
                    tags_json = json.dumps(tags_json, ensure_ascii=False)
                connection.execute(
                    "INSERT INTO evidence(avatar_id,source_type,title,content,tags_json,derived_kind,confidence,created_at) VALUES(?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("source_type", "package"))[:80],
                        str(row.get("title", ""))[:200],
                        str(row["content"])[:100000],
                        tags_json[:10000],
                        str(row.get("derived_kind", ""))[:80],
                        min(max(float(row.get("confidence", 1)), 0), 1),
                        int(row.get("created_at", now)),
                    ),
                )
            for row in messages[:100000] if isinstance(messages, list) else []:
                if not isinstance(row, dict) or row.get("role") not in {"user", "assistant", "system"}:
                    continue
                connection.execute(
                    "INSERT INTO messages(avatar_id,role,content,channel,created_at) VALUES(?,?,?,?,?)",
                    (new_id, row["role"], str(row.get("content", ""))[:100000], str(row.get("channel", "imported"))[:50], int(row.get("created_at", now))),
                )
            for row in optional["rights"][:10000] if isinstance(optional["rights"], list) else []:
                if not isinstance(row, dict):
                    continue
                data_classes_json = row.get("data_classes_json", "[]")
                if not isinstance(data_classes_json, str):
                    data_classes_json = json.dumps(data_classes_json, ensure_ascii=False)
                connection.execute(
                    "INSERT INTO rights_grants(avatar_id,grant_type,subject_kind,rights_scope,data_classes_json,provider_transfer_allowed,commercial_use_allowed,revocable,note,confirmed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("grant_type", "package_import"))[:80],
                        str(row.get("subject_kind", "fictional"))[:80],
                        str(row.get("rights_scope", "local_avatar_build"))[:200],
                        data_classes_json[:10000],
                        int(bool(row.get("provider_transfer_allowed", False))),
                        int(bool(row.get("commercial_use_allowed", False))),
                        int(bool(row.get("revocable", True))),
                        str(row.get("note", ""))[:1000],
                        int(row.get("confirmed_at", now)),
                    ),
                )
            for row in optional["world_facts"][:100000] if isinstance(optional["world_facts"], list) else []:
                if not isinstance(row, dict) or not str(row.get("fact_key", "")).strip():
                    continue
                connection.execute(
                    "INSERT INTO world_facts(avatar_id,fact_key,fact_value_json,reality_kind,mutability,status,confidence,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row["fact_key"])[:200],
                        str(row.get("fact_value_json", "null"))[:100000],
                        str(row.get("reality_kind", "fictional_canon"))[:80],
                        str(row.get("mutability", "evolving"))[:80],
                        str(row.get("status", "fact"))[:50],
                        min(max(float(row.get("confidence", 1)), 0), 1),
                        int(bool(row.get("active", True))),
                        int(row.get("created_at", now)),
                        int(row.get("updated_at", now)),
                    ),
                )
            for row in optional["world_modules"][:10000] if isinstance(optional["world_modules"], list) else []:
                if not isinstance(row, dict) or not str(row.get("module_key", "")).strip():
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO world_modules(avatar_id,module_key,module_name,category,required,enabled,status,description,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("module_key", ""))[:80],
                        str(row.get("module_name", ""))[:120],
                        str(row.get("category", ""))[:80],
                        int(bool(row.get("required", False))),
                        int(bool(row.get("enabled", True))),
                        str(row.get("status", "not_started"))[:50],
                        str(row.get("description", ""))[:500],
                        int(row.get("created_at", now)),
                        int(row.get("updated_at", now)),
                    ),
                )
            runtime = optional.get("world_runtime_settings") if isinstance(optional.get("world_runtime_settings"), dict) else {}
            if runtime:
                connection.execute(
                    """
                    INSERT INTO world_runtime_settings
                    (avatar_id,engine_enabled,world_clock_enabled,npc_autonomy_enabled,relationship_progression_enabled,
                     consistency_scan_enabled,auto_minor_events,high_impact_requires_review,rollback_enabled,
                     active_seconds,last_advanced_at,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        new_id,
                        int(bool(runtime.get("engine_enabled", True))),
                        int(bool(runtime.get("world_clock_enabled", True))),
                        int(bool(runtime.get("npc_autonomy_enabled", True))),
                        int(bool(runtime.get("relationship_progression_enabled", True))),
                        int(bool(runtime.get("consistency_scan_enabled", True))),
                        int(bool(runtime.get("auto_minor_events", True))),
                        int(bool(runtime.get("high_impact_requires_review", True))),
                        int(bool(runtime.get("rollback_enabled", True))),
                        int(runtime.get("active_seconds", 0)),
                        int(runtime.get("last_advanced_at", 0)),
                        int(runtime.get("updated_at", now)),
                    ),
                )
            for row in optional["world_events"][:100000] if isinstance(optional["world_events"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO world_events(avatar_id,event_key,title,summary,event_kind,status,occurred_at,payload_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("event_key", ""))[:200],
                        str(row.get("title", ""))[:200],
                        str(row.get("summary", ""))[:10000],
                        str(row.get("event_kind", "proposal"))[:80],
                        str(row.get("status", "proposal"))[:50],
                        int(row.get("occurred_at", 0)),
                        str(row.get("payload_json", "{}"))[:100000],
                        int(row.get("created_at", now)),
                    ),
                )
            for row in optional["world_fact_proposals"][:100000] if isinstance(optional["world_fact_proposals"], list) else []:
                if not isinstance(row, dict) or not str(row.get("fact_key", "")).strip():
                    continue
                connection.execute(
                    "INSERT INTO world_fact_proposals(avatar_id,fact_key,fact_value_json,reality_kind,mutability,status,reason,review_note,created_at,reviewed_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("fact_key", ""))[:200],
                        str(row.get("fact_value_json", "null"))[:100000],
                        str(row.get("reality_kind", "fictional_runtime"))[:80],
                        str(row.get("mutability", "evolving"))[:80],
                        str(row.get("status", "pending"))[:50],
                        str(row.get("reason", ""))[:1000],
                        str(row.get("review_note", ""))[:1000],
                        int(row.get("created_at", now)),
                        int(row.get("reviewed_at", 0)),
                    ),
                )
            for row in optional["visual_assets"][:100000] if isinstance(optional["visual_assets"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO visual_assets(avatar_id,asset_kind,status,label,local_path,provider,metadata_json,approved_at,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("asset_kind", "identity"))[:80],
                        str(row.get("status", "candidate"))[:50],
                        str(row.get("label", ""))[:200],
                        remap_asset_path(row.get("local_path"))[:500],
                        str(row.get("provider", ""))[:80],
                        str(row.get("metadata_json", "{}"))[:100000],
                        int(row.get("approved_at", 0)),
                        int(row.get("created_at", now)),
                    ),
                )
            for row in optional["visual_asset_sets"][:10000] if isinstance(optional["visual_asset_sets"], list) else []:
                if not isinstance(row, dict):
                    continue
                new_set_id = f"vas_{uuid.uuid4().hex[:16]}"
                connection.execute(
                    "INSERT INTO visual_asset_sets(id,avatar_id,set_type,semantic_key,label,status,version,invariants_json,negative_constraints_json,metadata_json,approved_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_set_id,
                        new_id,
                        str(row.get("set_type", "identity"))[:40],
                        str(row.get("semantic_key", "imported"))[:120],
                        str(row.get("label", ""))[:200],
                        str(row.get("status", "candidate"))[:50],
                        int(row.get("version", 1)),
                        str(row.get("invariants_json", "[]"))[:100000],
                        str(row.get("negative_constraints_json", "[]"))[:100000],
                        str(row.get("metadata_json", "{}"))[:100000],
                        int(row.get("approved_at", 0)),
                        int(row.get("created_at", now)),
                        int(row.get("updated_at", now)),
                    ),
                )
                for item in row.get("items", [])[:1000] if isinstance(row.get("items"), list) else []:
                    if not isinstance(item, dict):
                        continue
                    connection.execute(
                        "INSERT INTO visual_asset_items(set_id,role,local_path,remote_url,content_sha256,status,quality_score,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                        (
                            new_set_id,
                            str(item.get("role", "reference"))[:50],
                            remap_asset_path(item.get("local_path"))[:500],
                            str(item.get("remote_url", ""))[:4000],
                            str(item.get("content_sha256", ""))[:128],
                            str(item.get("status", "candidate"))[:50],
                            int(item.get("quality_score", 0)),
                            str(item.get("metadata_json", "{}"))[:100000],
                            int(item.get("created_at", now)),
                        ),
                    )
            for row in optional["scene_profiles"][:10000] if isinstance(optional["scene_profiles"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO scene_profiles(id,avatar_id,semantic_key,display_name,status,route,stable_features_json,negative_constraints_json,topology_json,metadata_json,approved_at,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        f"scene_{uuid.uuid4().hex[:16]}",
                        new_id,
                        str(row.get("semantic_key", "imported"))[:120],
                        str(row.get("display_name", "导入场景"))[:200],
                        str(row.get("status", "candidate"))[:50],
                        str(row.get("route", "image_bootstrap"))[:50],
                        str(row.get("stable_features_json", "[]"))[:100000],
                        str(row.get("negative_constraints_json", "[]"))[:100000],
                        str(row.get("topology_json", "{}"))[:100000],
                        str(row.get("metadata_json", "{}"))[:100000],
                        int(row.get("approved_at", 0)),
                        int(row.get("created_at", now)),
                        int(row.get("updated_at", now)),
                    ),
                )
            for row in optional["video_keyframes"][:10000] if isinstance(optional["video_keyframes"], list) else []:
                if not isinstance(row, dict) or not row.get("local_path"):
                    continue
                connection.execute(
                    "INSERT INTO video_keyframes(avatar_id,job_id,continuity_run_id,local_path,position_ms,quality_score,status,binding_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        "",
                        "",
                        remap_asset_path(row.get("local_path"))[:500],
                        int(row.get("position_ms", 0)),
                        int(row.get("quality_score", 0)),
                        str(row.get("status", "history_reference"))[:50],
                        str(row.get("binding_json", "{}"))[:100000],
                        int(row.get("created_at", now)),
                    ),
                )
            for row in optional["voice_profiles"][:10000] if isinstance(optional["voice_profiles"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO voice_profiles(avatar_id,provider,voice_id,voice_name,profile_kind,status,model,metadata_json,active,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("provider", ""))[:80],
                        str(row.get("voice_id", ""))[:500],
                        str(row.get("voice_name", ""))[:200],
                        str(row.get("profile_kind", "synthetic"))[:80],
                        str(row.get("status", "candidate"))[:50],
                        str(row.get("model", ""))[:200],
                        str(row.get("metadata_json", "{}"))[:100000],
                        int(bool(row.get("active", False)) and str(row.get("profile_kind", "")) not in {"cloned", "voice_clone"}),
                        int(row.get("created_at", now)),
                    ),
                )
            for row in optional["provider_assets"][:10000] if isinstance(optional["provider_assets"], list) else []:
                if not isinstance(row, dict):
                    continue
                metadata = row.get("metadata_json", "{}")
                if not isinstance(metadata, str):
                    metadata = json.dumps(metadata, ensure_ascii=False)
                connection.execute(
                    "INSERT INTO provider_assets(avatar_id,kind,provider,external_id,metadata_json,active,created_at) VALUES(?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("kind", "imported"))[:80],
                        str(row.get("provider", ""))[:80],
                        str(row.get("external_id", ""))[:500],
                        json.dumps({"portable": False, "rebind_required": True, "original": metadata[:10000]}, ensure_ascii=False),
                        0,
                        int(row.get("created_at", now)),
                    ),
                )
            for row in optional["voice_transcriptions"][:100000] if isinstance(optional["voice_transcriptions"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO voice_transcriptions(avatar_id,provider,model,transcript,status,confidence,metadata_json,created_at,confirmed_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("provider", "development"))[:80],
                        str(row.get("model", ""))[:200],
                        str(row.get("transcript", ""))[:100000],
                        str(row.get("status", "needs_review"))[:50],
                        min(max(float(row.get("confidence", 0)), 0), 1),
                        str(row.get("metadata_json", "{}"))[:100000],
                        int(row.get("created_at", now)),
                        int(row.get("confirmed_at", 0)),
                    ),
                )
            if model_settings and str(model_settings.get("mode", "inherit")) in {"inherit", "local", "cloud"}:
                provider_name = str(model_settings.get("provider_name", "") or connection_hint.get("provider_name", ""))[:80]
                base_url = str(model_settings.get("base_url", "") or connection_hint.get("base_url", ""))[:500]
                model_name = str(model_settings.get("model", "") or connection_hint.get("model", ""))[:200]
                connection.execute(
                    "INSERT INTO avatar_model_settings(avatar_id,mode,connection_id,provider_name,base_url,model,ollama_url,ollama_model,cloud_data_consent,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        "inherit" if model_settings.get("connection_id") else str(model_settings.get("mode", "inherit"))[:20],
                        "",
                        provider_name,
                        base_url,
                        model_name,
                        str(model_settings.get("ollama_url", ""))[:500],
                        str(model_settings.get("ollama_model", ""))[:200],
                        int(bool(model_settings.get("cloud_data_consent", False))),
                        int(model_settings.get("updated_at", now)),
                    ),
                )
            for row in optional["builder_answers"][:10000] if isinstance(optional["builder_answers"], list) else []:
                if not isinstance(row, dict) or not str(row.get("answer", "")).strip():
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO builder_answers(avatar_id,route,question_key,question_text,answer,created_at) VALUES(?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("route", "fictional_guided"))[:80],
                        str(row.get("question_key", ""))[:80],
                        str(row.get("question_text", ""))[:1000],
                        str(row.get("answer", ""))[:20000],
                        int(row.get("created_at", now)),
                    ),
                )
            for row in optional["quality_evaluations"][:10000] if isinstance(optional["quality_evaluations"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO quality_evaluations(avatar_id,evaluation_kind,status,score,checks_json,samples_json,user_feedback_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (
                        new_id,
                        str(row.get("evaluation_kind", "imported"))[:80],
                        str(row.get("status", "completed"))[:50],
                        min(max(int(row.get("score", 0) or 0), 0), 100),
                        str(row.get("checks_json", "[]"))[:100000],
                        str(row.get("samples_json", "[]"))[:100000],
                        str(row.get("user_feedback_json", "{}"))[:100000],
                        int(row.get("created_at", now)),
                        int(row.get("updated_at", now)),
                    ),
                )
            proactive = optional.get("proactive_rules") if isinstance(optional.get("proactive_rules"), dict) else {}
            if proactive:
                connection.execute(
                    """
                    INSERT INTO proactive_rules
                    (avatar_id,daily_max,allowed_windows_json,quiet_hours_json,topic_scope_json,
                     use_long_term_memory,allow_world_event_advancement,tone,cooldown_after_user_reply_minutes,updated_at)
                    VALUES(?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        new_id,
                        min(max(int(proactive.get("daily_max", 2) or 2), 0), 24),
                        str(proactive.get("allowed_windows_json", "[]"))[:20000],
                        str(proactive.get("quiet_hours_json", "{}"))[:20000],
                        str(proactive.get("topic_scope_json", "[]"))[:20000],
                        int(bool(proactive.get("use_long_term_memory", True))),
                        int(bool(proactive.get("allow_world_event_advancement", False))),
                        str(proactive.get("tone", ""))[:500],
                        min(max(int(proactive.get("cooldown_after_user_reply_minutes", 120) or 120), 15), 10080),
                        int(proactive.get("updated_at", now)),
                    ),
                )
            for row in optional["world_conflicts"][:10000] if isinstance(optional["world_conflicts"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO world_conflicts(avatar_id,fact_key,existing_value_json,candidate_value_json,reason,status,review_note,created_at,resolved_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (new_id, str(row.get("fact_key", ""))[:200], str(row.get("existing_value_json", "null"))[:100000], str(row.get("candidate_value_json", "null"))[:100000], str(row.get("reason", ""))[:1000], str(row.get("status", "open"))[:50], str(row.get("review_note", ""))[:1000], int(row.get("created_at", now)), int(row.get("resolved_at", 0))),
                )
            for row in optional["world_snapshots"][:10000] if isinstance(optional["world_snapshots"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO world_snapshots(avatar_id,event_id,day_key,facts_json,settings_json,created_at,rolled_back_at) VALUES(?,?,?,?,?,?,?)",
                    (new_id, int(row.get("event_id", 0)), str(row.get("day_key", ""))[:40], str(row.get("facts_json", "[]"))[:500000], str(row.get("settings_json", "{}"))[:100000], int(row.get("created_at", now)), int(row.get("rolled_back_at", 0))),
                )
            for row in optional["memory_revisions"][:50000] if isinstance(optional["memory_revisions"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO memory_revisions(avatar_id,memory_id,before_json,after_json,action,note,created_at) VALUES(?,?,?,?,?,?,?)",
                    (new_id, int(row.get("memory_id", 0)), str(row.get("before_json", "{}"))[:100000], str(row.get("after_json", "{}"))[:100000], str(row.get("action", ""))[:80], str(row.get("note", ""))[:1000], int(row.get("created_at", now))),
                )
            for row in optional["memory_graph_nodes"][:10000] if isinstance(optional["memory_graph_nodes"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO memory_graph_nodes(avatar_id,node_key,label,node_type,weight,evidence_count,metadata_json,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (new_id, str(row.get("node_key", ""))[:200], str(row.get("label", ""))[:200], str(row.get("node_type", "concept"))[:80], min(max(float(row.get("weight", 0.5)), 0), 1), int(row.get("evidence_count", 0)), str(row.get("metadata_json", "{}"))[:100000], int(row.get("updated_at", now))),
                )
            for row in optional["memory_graph_edges"][:20000] if isinstance(optional["memory_graph_edges"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT OR IGNORE INTO memory_graph_edges(avatar_id,source_key,target_key,relation,weight,evidence_count,updated_at) VALUES(?,?,?,?,?,?,?)",
                    (new_id, str(row.get("source_key", ""))[:200], str(row.get("target_key", ""))[:200], str(row.get("relation", "co_occurs"))[:80], min(max(float(row.get("weight", 0.5)), 0), 1), int(row.get("evidence_count", 0)), int(row.get("updated_at", now))),
                )
            persona_core = optional.get("persona_core") if isinstance(optional.get("persona_core"), dict) else {}
            if persona_core:
                connection.execute(
                    "INSERT INTO persona_core_profiles(avatar_id,core_json,source_digest,created_at,updated_at) VALUES(?,?,?,?,?)",
                    (new_id, str(persona_core.get("core_json", "{}"))[:500000], str(persona_core.get("source_digest", ""))[:100], int(persona_core.get("created_at", now)), int(persona_core.get("updated_at", now))),
                )
            for row in optional["persona_feedback_rules"][:10000] if isinstance(optional["persona_feedback_rules"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO persona_feedback_rules(avatar_id,dimension,signal,rule_text,weight,active,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                    (new_id, str(row.get("dimension", ""))[:80], str(row.get("signal", ""))[:80], str(row.get("rule_text", ""))[:1000], min(max(float(row.get("weight", 0.5)), 0), 1), int(bool(row.get("active", True))), int(row.get("created_at", now)), int(row.get("updated_at", now))),
                )
            for row in optional["decision_explanations"][:50000] if isinstance(optional["decision_explanations"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO decision_explanations(avatar_id,message_id,decision_kind,input_summary,output_summary,metadata_json,created_at) VALUES(?,?,?,?,?,?,?)",
                    (new_id, int(row.get("message_id", 0)), str(row.get("decision_kind", ""))[:80], str(row.get("input_summary", ""))[:1000], str(row.get("output_summary", ""))[:1000], str(row.get("metadata_json", "{}"))[:100000], int(row.get("created_at", now))),
                )
            for row in optional["usage_events"][:50000] if isinstance(optional["usage_events"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO usage_events(avatar_id,provider,model,role,operation,status,latency_ms,estimated_cost,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id, str(row.get("provider", ""))[:80], str(row.get("model", ""))[:200], str(row.get("role", ""))[:80], str(row.get("operation", ""))[:80], str(row.get("status", "ok"))[:50], int(row.get("latency_ms", 0)), float(row.get("estimated_cost", 0)), str(row.get("metadata_json", "{}"))[:100000], int(row.get("created_at", now))),
                )
            for row in optional["media_reviews"][:50000] if isinstance(optional["media_reviews"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO media_reviews(avatar_id,media_kind,asset_id,review_kind,status,score,findings_json,user_feedback_json,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id, str(row.get("media_kind", "visual"))[:80], int(row.get("asset_id", 0)), str(row.get("review_kind", ""))[:80], str(row.get("status", "completed"))[:50], min(max(int(row.get("score", 0)), 0), 100), str(row.get("findings_json", "[]"))[:100000], str(row.get("user_feedback_json", "{}"))[:100000], int(row.get("created_at", now)), int(row.get("updated_at", now))),
                )
            for row in optional["voice_events"][:50000] if isinstance(optional["voice_events"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO voice_events(avatar_id,event_kind,transcript_id,profile_id,emotion,tone,confidence,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?)",
                    (new_id, str(row.get("event_kind", ""))[:80], int(row.get("transcript_id", 0)), int(row.get("profile_id", 0)), str(row.get("emotion", ""))[:80], str(row.get("tone", ""))[:200], min(max(float(row.get("confidence", 0)), 0), 1), str(row.get("metadata_json", "{}"))[:100000], int(row.get("created_at", now))),
                )
            for row in optional["realtime_call_sessions"][:10000] if isinstance(optional["realtime_call_sessions"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO realtime_call_sessions(avatar_id,status,provider,started_at,ended_at,summary,metadata_json) VALUES(?,?,?,?,?,?,?)",
                    (new_id, str(row.get("status", "ended"))[:50], str(row.get("provider", ""))[:80], int(row.get("started_at", 0)), int(row.get("ended_at", 0)), str(row.get("summary", ""))[:1000], str(row.get("metadata_json", "{}"))[:100000]),
                )
            for row in optional["realtime_call_turns"][:50000] if isinstance(optional["realtime_call_turns"], list) else []:
                if not isinstance(row, dict):
                    continue
                connection.execute(
                    "INSERT INTO realtime_call_turns(avatar_id,call_session_id,user_transcript,assistant_text,asr_latency_ms,llm_latency_ms,tts_latency_ms,interrupted,metadata_json,created_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                    (new_id, int(row.get("call_session_id", 0)), str(row.get("user_transcript", ""))[:20000], str(row.get("assistant_text", ""))[:20000], int(row.get("asr_latency_ms", 0)), int(row.get("llm_latency_ms", 0)), int(row.get("tts_latency_ms", 0)), int(bool(row.get("interrupted", False))), str(row.get("metadata_json", "{}"))[:100000], int(row.get("created_at", now))),
                )
        asset_root = avatars_dir / new_id
        for item in members:
            path = Path(item.filename)
            if item.is_dir() or not path.parts or path.parts[0] != "assets":
                continue
            relative = Path(*path.parts[1:])
            destination = (asset_root / relative).resolve()
            if asset_root.resolve() not in destination.parents:
                raise ValueError("人物包素材路径非法")
            destination.parent.mkdir(parents=True, exist_ok=True)
            with archive.open(item) as source, destination.open("wb") as target:
                shutil.copyfileobj(source, target)
    return {"id": new_id, "name": str(avatar["name"]), "memories": len(memories), "messages": len(messages)}
