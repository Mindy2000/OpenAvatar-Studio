from __future__ import annotations

import json
import shutil
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from openavatar.migrations import LATEST_SCHEMA_VERSION, apply_migrations


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS avatars (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    purpose TEXT NOT NULL DEFAULT '',
    relationship TEXT NOT NULL DEFAULT '朋友',
    subject_kind TEXT NOT NULL CHECK(subject_kind IN ('self', 'authorized_person', 'fictional')),
    adult_subject INTEGER NOT NULL DEFAULT 1,
    consent_confirmed INTEGER NOT NULL DEFAULT 0,
    proactive_enabled INTEGER NOT NULL DEFAULT 0,
    proactive_interval_minutes INTEGER NOT NULL DEFAULT 360,
    usage_mode TEXT NOT NULL DEFAULT 'preview',
    avatar_primary_language TEXT NOT NULL DEFAULT 'zh-CN',
    avatar_secondary_languages TEXT NOT NULL DEFAULT '[]',
    avatar_response_mode TEXT NOT NULL DEFAULT 'follow_user',
    world_region TEXT NOT NULL DEFAULT 'mainland_china',
    world_type TEXT NOT NULL DEFAULT 'realistic',
    world_region_custom_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS persona_profiles (
    avatar_id TEXT PRIMARY KEY REFERENCES avatars(id) ON DELETE CASCADE,
    summary TEXT NOT NULL DEFAULT '',
    traits_json TEXT NOT NULL DEFAULT '[]',
    speaking_style TEXT NOT NULL DEFAULT '',
    boundaries TEXT NOT NULL DEFAULT '',
    source_count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    original_name TEXT NOT NULL,
    stored_path TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT '',
    size_bytes INTEGER NOT NULL,
    status TEXT NOT NULL DEFAULT 'stored',
    note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS evidence (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    source_import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
    source_type TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    tags_json TEXT NOT NULL DEFAULT '[]',
    derived_kind TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_evidence_avatar ON evidence(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS rights_grants (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    source_import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
    grant_type TEXT NOT NULL DEFAULT '',
    subject_kind TEXT NOT NULL DEFAULT '',
    rights_scope TEXT NOT NULL DEFAULT '',
    data_classes_json TEXT NOT NULL DEFAULT '[]',
    provider_transfer_allowed INTEGER NOT NULL DEFAULT 0,
    commercial_use_allowed INTEGER NOT NULL DEFAULT 0,
    revocable INTEGER NOT NULL DEFAULT 1,
    note TEXT NOT NULL DEFAULT '',
    confirmed_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_rights_avatar ON rights_grants(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS world_facts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,
    fact_value_json TEXT NOT NULL,
    reality_kind TEXT NOT NULL DEFAULT 'fictional_canon',
    mutability TEXT NOT NULL DEFAULT 'evolving',
    status TEXT NOT NULL DEFAULT 'fact',
    source_evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL,
    confidence REAL NOT NULL DEFAULT 1.0,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_facts_avatar ON world_facts(avatar_id, fact_key);

CREATE TABLE IF NOT EXISTS world_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    event_key TEXT NOT NULL,
    title TEXT NOT NULL,
    summary TEXT NOT NULL DEFAULT '',
    event_kind TEXT NOT NULL DEFAULT 'proposal',
    status TEXT NOT NULL DEFAULT 'proposal',
    occurred_at INTEGER NOT NULL DEFAULT 0,
    payload_json TEXT NOT NULL DEFAULT '{}',
    source_evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_world_events_avatar ON world_events(avatar_id, created_at DESC);

CREATE TABLE IF NOT EXISTS world_modules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    module_key TEXT NOT NULL,
    module_name TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    required INTEGER NOT NULL DEFAULT 0,
    enabled INTEGER NOT NULL DEFAULT 1,
    status TEXT NOT NULL DEFAULT 'not_started',
    description TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(avatar_id, module_key)
);
CREATE INDEX IF NOT EXISTS idx_world_modules_avatar ON world_modules(avatar_id, category, enabled);

CREATE TABLE IF NOT EXISTS world_runtime_settings (
    avatar_id TEXT PRIMARY KEY REFERENCES avatars(id) ON DELETE CASCADE,
    engine_enabled INTEGER NOT NULL DEFAULT 1,
    world_clock_enabled INTEGER NOT NULL DEFAULT 1,
    npc_autonomy_enabled INTEGER NOT NULL DEFAULT 1,
    relationship_progression_enabled INTEGER NOT NULL DEFAULT 1,
    consistency_scan_enabled INTEGER NOT NULL DEFAULT 1,
    auto_minor_events INTEGER NOT NULL DEFAULT 1,
    high_impact_requires_review INTEGER NOT NULL DEFAULT 1,
    rollback_enabled INTEGER NOT NULL DEFAULT 1,
    active_seconds INTEGER NOT NULL DEFAULT 0,
    last_advanced_at INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS world_conflicts (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,
    existing_value_json TEXT NOT NULL DEFAULT 'null',
    candidate_value_json TEXT NOT NULL DEFAULT 'null',
    reason TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'open',
    review_note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    resolved_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_world_conflicts_avatar ON world_conflicts(avatar_id, status, id DESC);

CREATE TABLE IF NOT EXISTS world_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    event_id INTEGER NOT NULL DEFAULT 0,
    day_key TEXT NOT NULL DEFAULT '',
    facts_json TEXT NOT NULL DEFAULT '[]',
    settings_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    rolled_back_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_world_snapshots_avatar ON world_snapshots(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS world_fact_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    fact_key TEXT NOT NULL,
    fact_value_json TEXT NOT NULL,
    reality_kind TEXT NOT NULL DEFAULT 'fictional_runtime',
    mutability TEXT NOT NULL DEFAULT 'evolving',
    status TEXT NOT NULL DEFAULT 'pending',
    source_evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL,
    reason TEXT NOT NULL DEFAULT '',
    review_note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    reviewed_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_world_fact_proposals_avatar ON world_fact_proposals(avatar_id, status, id DESC);

CREATE TABLE IF NOT EXISTS model_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    role TEXT NOT NULL UNIQUE,
    provider TEXT NOT NULL DEFAULT 'openrouter',
    primary_model TEXT NOT NULL DEFAULT '',
    fallback_models_json TEXT NOT NULL DEFAULT '[]',
    latency_class TEXT NOT NULL DEFAULT 'background',
    cost_class TEXT NOT NULL DEFAULT 'cheap',
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_routes_role ON model_routes(role);

CREATE TABLE IF NOT EXISTS visual_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    asset_kind TEXT NOT NULL DEFAULT 'identity',
    status TEXT NOT NULL DEFAULT 'candidate',
    label TEXT NOT NULL DEFAULT '',
    local_path TEXT NOT NULL DEFAULT '',
    provider TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    approved_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_visual_assets_avatar ON visual_assets(avatar_id, status, asset_kind);

CREATE TABLE IF NOT EXISTS voice_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT '',
    voice_id TEXT NOT NULL DEFAULT '',
    voice_name TEXT NOT NULL DEFAULT '',
    profile_kind TEXT NOT NULL DEFAULT 'synthetic',
    status TEXT NOT NULL DEFAULT 'candidate',
    model TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_voice_profiles_avatar ON voice_profiles(avatar_id, active, status);

CREATE TABLE IF NOT EXISTS voice_transcriptions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    source_import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
    provider TEXT NOT NULL DEFAULT 'development',
    model TEXT NOT NULL DEFAULT '',
    transcript TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'needs_review',
    confidence REAL NOT NULL DEFAULT 0.0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    confirmed_at INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_voice_transcriptions_avatar ON voice_transcriptions(avatar_id, status, id DESC);

CREATE TABLE IF NOT EXISTS build_reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    report_kind TEXT NOT NULL DEFAULT 'builder',
    status TEXT NOT NULL DEFAULT 'completed',
    score INTEGER NOT NULL DEFAULT 0,
    checks_json TEXT NOT NULL DEFAULT '[]',
    recommendations_json TEXT NOT NULL DEFAULT '[]',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_build_reports_avatar ON build_reports(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    source_import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
    speaker TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'conversation',
    is_avatar INTEGER NOT NULL DEFAULT 0,
    confidence REAL NOT NULL DEFAULT 1.0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_avatar ON memories(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS memory_revisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    memory_id INTEGER NOT NULL DEFAULT 0,
    before_json TEXT NOT NULL DEFAULT '{}',
    after_json TEXT NOT NULL DEFAULT '{}',
    action TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memory_revisions_avatar ON memory_revisions(avatar_id, memory_id, id DESC);

CREATE TABLE IF NOT EXISTS memory_graph_nodes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    node_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    node_type TEXT NOT NULL DEFAULT 'concept',
    weight REAL NOT NULL DEFAULT 0.5,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    updated_at INTEGER NOT NULL,
    UNIQUE(avatar_id, node_key)
);
CREATE INDEX IF NOT EXISTS idx_memory_graph_nodes_avatar ON memory_graph_nodes(avatar_id, weight DESC);

CREATE TABLE IF NOT EXISTS memory_graph_edges (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    source_key TEXT NOT NULL,
    target_key TEXT NOT NULL,
    relation TEXT NOT NULL DEFAULT 'co_occurs',
    weight REAL NOT NULL DEFAULT 0.5,
    evidence_count INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL,
    UNIQUE(avatar_id, source_key, target_key, relation)
);
CREATE INDEX IF NOT EXISTS idx_memory_graph_edges_avatar ON memory_graph_edges(avatar_id, weight DESC);

CREATE TABLE IF NOT EXISTS persona_core_profiles (
    avatar_id TEXT PRIMARY KEY REFERENCES avatars(id) ON DELETE CASCADE,
    core_json TEXT NOT NULL DEFAULT '{}',
    source_digest TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS persona_feedback_rules (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    dimension TEXT NOT NULL DEFAULT '',
    signal TEXT NOT NULL DEFAULT '',
    rule_text TEXT NOT NULL DEFAULT '',
    weight REAL NOT NULL DEFAULT 0.5,
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_persona_feedback_avatar ON persona_feedback_rules(avatar_id, active, id DESC);

CREATE TABLE IF NOT EXISTS decision_explanations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    message_id INTEGER NOT NULL DEFAULT 0,
    decision_kind TEXT NOT NULL DEFAULT '',
    input_summary TEXT NOT NULL DEFAULT '',
    output_summary TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_decision_explanations_avatar ON decision_explanations(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS usage_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    provider TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    role TEXT NOT NULL DEFAULT '',
    operation TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'ok',
    latency_ms INTEGER NOT NULL DEFAULT 0,
    estimated_cost REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_usage_events_avatar ON usage_events(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS media_reviews (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    media_kind TEXT NOT NULL DEFAULT 'visual',
    asset_id INTEGER NOT NULL DEFAULT 0,
    review_kind TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'pending',
    score INTEGER NOT NULL DEFAULT 0,
    findings_json TEXT NOT NULL DEFAULT '[]',
    user_feedback_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_media_reviews_avatar ON media_reviews(avatar_id, media_kind, id DESC);

CREATE TABLE IF NOT EXISTS voice_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    event_kind TEXT NOT NULL DEFAULT '',
    transcript_id INTEGER NOT NULL DEFAULT 0,
    profile_id INTEGER NOT NULL DEFAULT 0,
    emotion TEXT NOT NULL DEFAULT '',
    tone TEXT NOT NULL DEFAULT '',
    confidence REAL NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_voice_events_avatar ON voice_events(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS realtime_call_sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'draft',
    provider TEXT NOT NULL DEFAULT '',
    started_at INTEGER NOT NULL DEFAULT 0,
    ended_at INTEGER NOT NULL DEFAULT 0,
    summary TEXT NOT NULL DEFAULT '',
    metadata_json TEXT NOT NULL DEFAULT '{}'
);
CREATE INDEX IF NOT EXISTS idx_realtime_call_sessions_avatar ON realtime_call_sessions(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS realtime_call_turns (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    call_session_id INTEGER NOT NULL DEFAULT 0,
    user_transcript TEXT NOT NULL DEFAULT '',
    assistant_text TEXT NOT NULL DEFAULT '',
    asr_latency_ms INTEGER NOT NULL DEFAULT 0,
    llm_latency_ms INTEGER NOT NULL DEFAULT 0,
    tts_latency_ms INTEGER NOT NULL DEFAULT 0,
    interrupted INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_realtime_call_turns_avatar ON realtime_call_turns(avatar_id, call_session_id, id);

CREATE TABLE IF NOT EXISTS import_rows (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    import_id INTEGER NOT NULL REFERENCES imports(id) ON DELETE CASCADE,
    row_index INTEGER NOT NULL,
    speaker TEXT NOT NULL DEFAULT '',
    content TEXT NOT NULL,
    selected INTEGER NOT NULL DEFAULT 1,
    is_avatar INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    UNIQUE(import_id, row_index)
);
CREATE INDEX IF NOT EXISTS idx_import_rows_import ON import_rows(import_id, row_index);

CREATE TABLE IF NOT EXISTS training_jobs (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    job_type TEXT NOT NULL,
    provider TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'queued',
    progress INTEGER NOT NULL DEFAULT 0,
    stage TEXT NOT NULL DEFAULT '',
    input_summary TEXT NOT NULL DEFAULT '',
    result_json TEXT NOT NULL DEFAULT '{}',
    error TEXT NOT NULL DEFAULT '',
    estimated_cost REAL NOT NULL DEFAULT 0,
    actual_cost REAL NOT NULL DEFAULT 0,
    currency TEXT NOT NULL DEFAULT 'CNY',
    attempt INTEGER NOT NULL DEFAULT 0,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    started_at INTEGER,
    finished_at INTEGER
);
CREATE INDEX IF NOT EXISTS idx_training_jobs_avatar ON training_jobs(avatar_id, created_at DESC);

CREATE TABLE IF NOT EXISTS provider_assets (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    kind TEXT NOT NULL,
    provider TEXT NOT NULL,
    external_id TEXT NOT NULL DEFAULT '',
    source_import_id INTEGER REFERENCES imports(id) ON DELETE SET NULL,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    active INTEGER NOT NULL DEFAULT 1,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_provider_assets_avatar ON provider_assets(avatar_id, kind, created_at DESC);

CREATE TABLE IF NOT EXISTS messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    role TEXT NOT NULL CHECK(role IN ('user', 'assistant', 'system')),
    content TEXT NOT NULL,
    channel TEXT NOT NULL DEFAULT 'chat',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_messages_avatar ON messages(avatar_id, id DESC);

CREATE TABLE IF NOT EXISTS chat_timeline_branches (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    timeline_kind TEXT NOT NULL DEFAULT 'official',
    parent_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'frozen',
    label TEXT NOT NULL DEFAULT '',
    mutation_action TEXT NOT NULL DEFAULT '',
    selected_message_id INTEGER NOT NULL DEFAULT 0,
    snapshot_json TEXT NOT NULL DEFAULT '{}',
    impact_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_chat_timeline_active
ON chat_timeline_branches(avatar_id,timeline_kind) WHERE status='active';
CREATE INDEX IF NOT EXISTS idx_chat_timeline_avatar
ON chat_timeline_branches(avatar_id,timeline_kind,status,updated_at DESC);

CREATE TABLE IF NOT EXISTS chat_change_previews (
    token TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    timeline_kind TEXT NOT NULL DEFAULT 'official',
    action TEXT NOT NULL,
    message_id INTEGER NOT NULL,
    replacement_text TEXT NOT NULL DEFAULT '',
    impact_json TEXT NOT NULL DEFAULT '{}',
    expires_at INTEGER NOT NULL,
    created_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS historical_memory_corrections (
    memory_id INTEGER PRIMARY KEY REFERENCES memories(id) ON DELETE CASCADE,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    corrected_speaker TEXT NOT NULL DEFAULT '',
    corrected_content TEXT NOT NULL DEFAULT '',
    note TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_historical_corrections_avatar
ON historical_memory_corrections(avatar_id,updated_at DESC);

CREATE TABLE IF NOT EXISTS timeline_media_candidates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    branch_id TEXT NOT NULL REFERENCES chat_timeline_branches(id) ON DELETE CASCADE,
    message_id INTEGER NOT NULL DEFAULT 0,
    media_url TEXT NOT NULL,
    media_type TEXT NOT NULL DEFAULT '',
    origin_role TEXT NOT NULL DEFAULT '',
    reuse_policy TEXT NOT NULL DEFAULT 'permission_required',
    status TEXT NOT NULL DEFAULT 'available',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(avatar_id,branch_id,message_id,media_url)
);
CREATE INDEX IF NOT EXISTS idx_timeline_media_avatar
ON timeline_media_candidates(avatar_id,status,updated_at DESC);

CREATE TABLE IF NOT EXISTS app_settings (
    key TEXT PRIMARY KEY,
    value_json TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS model_connections (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    connection_type TEXT NOT NULL DEFAULT 'cloud_openai',
    provider_name TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    adapter_kind TEXT NOT NULL DEFAULT 'openai_compatible',
    cloud_data_consent INTEGER NOT NULL DEFAULT 0,
    local_only INTEGER NOT NULL DEFAULT 0,
    last_test_status TEXT NOT NULL DEFAULT 'untested',
    last_test_message TEXT NOT NULL DEFAULT '',
    last_tested_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_model_connections_updated ON model_connections(updated_at DESC);

CREATE TABLE IF NOT EXISTS ocr_connections (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    connection_type TEXT NOT NULL DEFAULT 'local_command',
    provider_name TEXT NOT NULL DEFAULT '',
    command_template TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    api_key_required INTEGER NOT NULL DEFAULT 0,
    cloud_data_consent INTEGER NOT NULL DEFAULT 0,
    local_only INTEGER NOT NULL DEFAULT 1,
    enabled INTEGER NOT NULL DEFAULT 1,
    last_test_status TEXT NOT NULL DEFAULT 'untested',
    last_test_message TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_ocr_connections_updated ON ocr_connections(updated_at DESC);

CREATE TABLE IF NOT EXISTS avatar_model_settings (
    avatar_id TEXT PRIMARY KEY REFERENCES avatars(id) ON DELETE CASCADE,
    mode TEXT NOT NULL DEFAULT 'inherit',
    connection_id TEXT NOT NULL DEFAULT '',
    provider_name TEXT NOT NULL DEFAULT '',
    base_url TEXT NOT NULL DEFAULT '',
    model TEXT NOT NULL DEFAULT '',
    ollama_url TEXT NOT NULL DEFAULT '',
    ollama_model TEXT NOT NULL DEFAULT '',
    cloud_data_consent INTEGER NOT NULL DEFAULT 0,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS builder_answers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    route TEXT NOT NULL DEFAULT 'fictional_guided',
    question_key TEXT NOT NULL,
    question_text TEXT NOT NULL DEFAULT '',
    answer TEXT NOT NULL,
    evidence_id INTEGER REFERENCES evidence(id) ON DELETE SET NULL,
    created_at INTEGER NOT NULL,
    UNIQUE(avatar_id, route, question_key)
);
CREATE INDEX IF NOT EXISTS idx_builder_answers_avatar ON builder_answers(avatar_id, route, id);

CREATE TABLE IF NOT EXISTS quality_evaluations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    evaluation_kind TEXT NOT NULL DEFAULT 'readiness',
    status TEXT NOT NULL DEFAULT 'draft',
    score INTEGER NOT NULL DEFAULT 0,
    checks_json TEXT NOT NULL DEFAULT '[]',
    samples_json TEXT NOT NULL DEFAULT '[]',
    user_feedback_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_quality_evaluations_avatar ON quality_evaluations(avatar_id, evaluation_kind, id DESC);

CREATE TABLE IF NOT EXISTS proactive_rules (
    avatar_id TEXT PRIMARY KEY REFERENCES avatars(id) ON DELETE CASCADE,
    daily_max INTEGER NOT NULL DEFAULT 2,
    allowed_windows_json TEXT NOT NULL DEFAULT '[]',
    quiet_hours_json TEXT NOT NULL DEFAULT '{}',
    topic_scope_json TEXT NOT NULL DEFAULT '[]',
    use_long_term_memory INTEGER NOT NULL DEFAULT 1,
    allow_world_event_advancement INTEGER NOT NULL DEFAULT 0,
    tone TEXT NOT NULL DEFAULT '自然、简短、有边界感',
    cooldown_after_user_reply_minutes INTEGER NOT NULL DEFAULT 120,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS provider_connections (
    id TEXT PRIMARY KEY,
    display_name TEXT NOT NULL,
    provider_kind TEXT NOT NULL,
    base_url TEXT NOT NULL DEFAULT '',
    region TEXT NOT NULL DEFAULT '',
    capabilities_json TEXT NOT NULL DEFAULT '[]',
    models_json TEXT NOT NULL DEFAULT '{}',
    config_json TEXT NOT NULL DEFAULT '{}',
    consent_json TEXT NOT NULL DEFAULT '{}',
    budget_json TEXT NOT NULL DEFAULT '{}',
    enabled INTEGER NOT NULL DEFAULT 1,
    last_test_status TEXT NOT NULL DEFAULT 'untested',
    last_test_message TEXT NOT NULL DEFAULT '',
    last_tested_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS capability_routes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    scope_type TEXT NOT NULL DEFAULT 'global',
    avatar_id TEXT NOT NULL DEFAULT '',
    capability TEXT NOT NULL,
    primary_connection_id TEXT NOT NULL DEFAULT '',
    fallback_connection_ids_json TEXT NOT NULL DEFAULT '[]',
    model TEXT NOT NULL DEFAULT '',
    config_json TEXT NOT NULL DEFAULT '{}',
    updated_at INTEGER NOT NULL,
    UNIQUE(scope_type, avatar_id, capability)
);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path
        self._lock = threading.RLock()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        current_version = 0
        if self.path.exists() and self.path.stat().st_size:
            valid_sqlite = True
            try:
                with sqlite3.connect(self.path) as existing:
                    existing.execute("PRAGMA schema_version").fetchone()
                    has_meta = existing.execute(
                        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='schema_meta'"
                    ).fetchone()
                    if has_meta:
                        row = existing.execute("SELECT value FROM schema_meta WHERE key='schema_version'").fetchone()
                        current_version = int(row[0]) if row else 0
            except (sqlite3.Error, ValueError):
                valid_sqlite = False
            if not valid_sqlite or current_version < LATEST_SCHEMA_VERSION:
                target_version = 4 if current_version == 0 else LATEST_SCHEMA_VERSION
                backup = self.path.with_name(f"{self.path.stem}.before-v{target_version}.backup{self.path.suffix}")
                if not backup.exists():
                    if valid_sqlite:
                        with sqlite3.connect(self.path) as source, sqlite3.connect(backup) as destination:
                            source.backup(destination)
                    else:
                        shutil.copy2(self.path, backup)
        with self.connect() as connection:
            connection.executescript(SCHEMA)
            memory_columns = {row[1] for row in connection.execute("PRAGMA table_info(memories)")}
            if "is_avatar" not in memory_columns:
                connection.execute("ALTER TABLE memories ADD COLUMN is_avatar INTEGER NOT NULL DEFAULT 0")
            memory_column_defaults = {
                "origin_kind": "TEXT NOT NULL DEFAULT 'legacy_baseline'",
                "source_message_id": "INTEGER NOT NULL DEFAULT 0",
                "timeline_kind": "TEXT NOT NULL DEFAULT 'official'",
            }
            for column, definition in memory_column_defaults.items():
                if column not in memory_columns:
                    connection.execute(f"ALTER TABLE memories ADD COLUMN {column} {definition}")
            connection.execute("UPDATE memories SET origin_kind='imported_history' WHERE source_import_id IS NOT NULL AND origin_kind='legacy_baseline'")
            message_columns = {row[1] for row in connection.execute("PRAGMA table_info(messages)")}
            message_column_defaults = {
                "turn_id": "TEXT NOT NULL DEFAULT ''",
                "media_url": "TEXT NOT NULL DEFAULT ''",
                "media_type": "TEXT NOT NULL DEFAULT ''",
            }
            for column, definition in message_column_defaults.items():
                if column not in message_columns:
                    connection.execute(f"ALTER TABLE messages ADD COLUMN {column} {definition}")
            world_event_columns = {row[1] for row in connection.execute("PRAGMA table_info(world_events)")}
            if "source_message_id" not in world_event_columns:
                connection.execute("ALTER TABLE world_events ADD COLUMN source_message_id INTEGER NOT NULL DEFAULT 0")
            avatar_columns = {row[1] for row in connection.execute("PRAGMA table_info(avatars)")}
            if "usage_mode" not in avatar_columns:
                connection.execute("ALTER TABLE avatars ADD COLUMN usage_mode TEXT NOT NULL DEFAULT 'preview'")
            avatar_column_defaults = {
                "avatar_primary_language": "TEXT NOT NULL DEFAULT 'zh-CN'",
                "avatar_secondary_languages": "TEXT NOT NULL DEFAULT '[]'",
                "avatar_response_mode": "TEXT NOT NULL DEFAULT 'follow_user'",
                "world_region": "TEXT NOT NULL DEFAULT 'mainland_china'",
                "world_type": "TEXT NOT NULL DEFAULT 'realistic'",
                "world_region_custom_json": "TEXT NOT NULL DEFAULT '{}'",
            }
            for column, definition in avatar_column_defaults.items():
                if column not in avatar_columns:
                    connection.execute(f"ALTER TABLE avatars ADD COLUMN {column} {definition}")
            avatar_model_columns = {row[1] for row in connection.execute("PRAGMA table_info(avatar_model_settings)")}
            if "connection_id" not in avatar_model_columns:
                connection.execute("ALTER TABLE avatar_model_settings ADD COLUMN connection_id TEXT NOT NULL DEFAULT ''")
            model_connection_columns = {row[1] for row in connection.execute("PRAGMA table_info(model_connections)")}
            if "last_tested_at" not in model_connection_columns:
                connection.execute("ALTER TABLE model_connections ADD COLUMN last_tested_at INTEGER NOT NULL DEFAULT 0")
            connection.execute(
                "CREATE TABLE IF NOT EXISTS schema_meta (key TEXT PRIMARY KEY, value TEXT NOT NULL, updated_at INTEGER NOT NULL)"
            )
            apply_migrations(connection, current_version)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15, check_same_thread=False)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def one(self, sql: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with self._lock, self.connect() as connection:
            row = connection.execute(sql, params).fetchone()
            return dict(row) if row else None

    def all(self, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._lock, self.connect() as connection:
            return [dict(row) for row in connection.execute(sql, params).fetchall()]

    def execute(self, sql: str, params: tuple[Any, ...] = ()) -> int:
        with self._lock, self.connect() as connection:
            cursor = connection.execute(sql, params)
            return int(cursor.lastrowid or 0)

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        with self._lock, self.connect() as connection:
            yield connection

    def setting(self, key: str, default: Any = None) -> Any:
        row = self.one("SELECT value_json FROM app_settings WHERE key=?", (key,))
        return json.loads(row["value_json"]) if row else default

    def set_setting(self, key: str, value: Any) -> None:
        now = int(time.time())
        self.execute(
            "INSERT INTO app_settings(key,value_json,updated_at) VALUES(?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET value_json=excluded.value_json, updated_at=excluded.updated_at",
            (key, json.dumps(value, ensure_ascii=False), now),
        )

    def integrity_check(self) -> dict[str, Any]:
        with self._lock, self.connect() as connection:
            rows = [str(row[0]) for row in connection.execute("PRAGMA integrity_check").fetchall()]
        return {"ok": rows == ["ok"], "results": rows[:20]}

    def backup(self, destination: Path | None = None) -> Path:
        stamp = time.strftime("%Y%m%d-%H%M%S")
        target = destination or self.path.with_name(f"{self.path.stem}.backup-{stamp}{self.path.suffix}")
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.resolve() == self.path.resolve():
            raise ValueError("备份目标不能是当前数据库")
        with self._lock, sqlite3.connect(self.path) as source, sqlite3.connect(target) as output:
            source.backup(output)
        return target

    def restore(self, source_path: Path) -> Path:
        source_path = source_path.resolve()
        if not source_path.is_file() or source_path == self.path.resolve():
            raise ValueError("恢复文件不存在或不是有效备份")
        with sqlite3.connect(source_path) as candidate:
            result = [str(row[0]) for row in candidate.execute("PRAGMA integrity_check").fetchall()]
            if result != ["ok"]:
                raise ValueError("备份数据库完整性检查未通过")
        safety = self.backup(
            self.path.with_name(f"{self.path.stem}.before-restore-{time.strftime('%Y%m%d-%H%M%S')}{self.path.suffix}")
        )
        with self._lock, sqlite3.connect(source_path) as source, sqlite3.connect(self.path) as destination:
            source.backup(destination)
        self.initialize()
        return safety
