from __future__ import annotations

import sqlite3
import time


LATEST_SCHEMA_VERSION = 8


MIGRATION_5 = """
CREATE TABLE IF NOT EXISTS scheduler_leases (
    lease_key TEXT PRIMARY KEY,
    owner_id TEXT NOT NULL,
    expires_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS domain_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE,
    avatar_id TEXT NOT NULL DEFAULT '',
    aggregate_type TEXT NOT NULL,
    aggregate_id TEXT NOT NULL,
    event_type TEXT NOT NULL,
    payload_json TEXT NOT NULL DEFAULT '{}',
    idempotency_key TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_domain_event_idempotency
ON domain_events(idempotency_key) WHERE idempotency_key<>'';
CREATE INDEX IF NOT EXISTS idx_domain_events_avatar ON domain_events(avatar_id,id DESC);

CREATE TABLE IF NOT EXISTS event_outbox (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id TEXT NOT NULL UNIQUE REFERENCES domain_events(event_id) ON DELETE CASCADE,
    status TEXT NOT NULL DEFAULT 'pending',
    attempts INTEGER NOT NULL DEFAULT 0,
    available_at INTEGER NOT NULL,
    delivered_at INTEGER NOT NULL DEFAULT 0,
    last_error TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_event_outbox_ready ON event_outbox(status,available_at,id);

CREATE TABLE IF NOT EXISTS request_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    request_id TEXT NOT NULL UNIQUE,
    method TEXT NOT NULL,
    path TEXT NOT NULL,
    status_code INTEGER NOT NULL,
    duration_ms REAL NOT NULL,
    avatar_id TEXT NOT NULL DEFAULT '',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_request_metrics_created ON request_metrics(created_at DESC);
"""


MIGRATION_6 = """
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
CREATE INDEX IF NOT EXISTS idx_provider_connections_updated
ON provider_connections(updated_at DESC);

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
CREATE INDEX IF NOT EXISTS idx_capability_routes_lookup
ON capability_routes(scope_type, avatar_id, capability);
"""


MIGRATION_7 = """
CREATE TABLE IF NOT EXISTS visual_asset_sets (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    set_type TEXT NOT NULL,
    semantic_key TEXT NOT NULL,
    label TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    version INTEGER NOT NULL DEFAULT 1,
    invariants_json TEXT NOT NULL DEFAULT '[]',
    negative_constraints_json TEXT NOT NULL DEFAULT '[]',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    approved_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(avatar_id,set_type,semantic_key,version)
);
CREATE INDEX IF NOT EXISTS idx_visual_asset_sets_avatar
ON visual_asset_sets(avatar_id,set_type,status,updated_at DESC);

CREATE TABLE IF NOT EXISTS visual_asset_items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    set_id TEXT NOT NULL REFERENCES visual_asset_sets(id) ON DELETE CASCADE,
    visual_asset_id INTEGER REFERENCES visual_assets(id) ON DELETE SET NULL,
    role TEXT NOT NULL DEFAULT 'reference',
    local_path TEXT NOT NULL DEFAULT '',
    remote_url TEXT NOT NULL DEFAULT '',
    content_sha256 TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'candidate',
    quality_score INTEGER NOT NULL DEFAULT 0,
    metadata_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    UNIQUE(set_id,visual_asset_id,role)
);
CREATE INDEX IF NOT EXISTS idx_visual_asset_items_set
ON visual_asset_items(set_id,status,role,id DESC);

CREATE TABLE IF NOT EXISTS scene_profiles (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    semantic_key TEXT NOT NULL,
    display_name TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'candidate',
    route TEXT NOT NULL DEFAULT 'image_bootstrap',
    stable_features_json TEXT NOT NULL DEFAULT '[]',
    negative_constraints_json TEXT NOT NULL DEFAULT '[]',
    topology_json TEXT NOT NULL DEFAULT '{}',
    metadata_json TEXT NOT NULL DEFAULT '{}',
    approved_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL,
    UNIQUE(avatar_id,semantic_key)
);
CREATE INDEX IF NOT EXISTS idx_scene_profiles_avatar
ON scene_profiles(avatar_id,status,route,updated_at DESC);

CREATE TABLE IF NOT EXISTS continuity_runs (
    id TEXT PRIMARY KEY,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL DEFAULT '',
    status TEXT NOT NULL DEFAULT 'planned',
    prompt TEXT NOT NULL DEFAULT '',
    scene_profile_id TEXT NOT NULL DEFAULT '',
    first_frame_asset_id INTEGER NOT NULL DEFAULT 0,
    provider TEXT NOT NULL DEFAULT '',
    provider_task_id TEXT NOT NULL DEFAULT '',
    contract_json TEXT NOT NULL DEFAULT '{}',
    reference_manifest_json TEXT NOT NULL DEFAULT '{}',
    review_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL,
    updated_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_continuity_runs_avatar
ON continuity_runs(avatar_id,created_at DESC);
CREATE INDEX IF NOT EXISTS idx_continuity_runs_job
ON continuity_runs(job_id);

CREATE TABLE IF NOT EXISTS video_keyframes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL REFERENCES avatars(id) ON DELETE CASCADE,
    job_id TEXT NOT NULL DEFAULT '',
    continuity_run_id TEXT NOT NULL DEFAULT '',
    local_path TEXT NOT NULL,
    position_ms INTEGER NOT NULL DEFAULT 0,
    quality_score INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'history_reference',
    binding_json TEXT NOT NULL DEFAULT '{}',
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_video_keyframes_avatar
ON video_keyframes(avatar_id,status,created_at DESC);
"""


MIGRATION_8 = """
UPDATE visual_asset_sets
SET status='approved'
WHERE status='canonical'
  AND EXISTS (
    SELECT 1 FROM visual_asset_sets newer
    WHERE newer.avatar_id=visual_asset_sets.avatar_id
      AND newer.set_type=visual_asset_sets.set_type
      AND newer.status='canonical'
      AND (newer.updated_at>visual_asset_sets.updated_at OR (newer.updated_at=visual_asset_sets.updated_at AND newer.id>visual_asset_sets.id))
  );
CREATE UNIQUE INDEX IF NOT EXISTS idx_visual_asset_sets_one_canonical
ON visual_asset_sets(avatar_id,set_type) WHERE status='canonical';
CREATE INDEX IF NOT EXISTS idx_visual_asset_items_hash
ON visual_asset_items(content_sha256) WHERE content_sha256<>'';

ALTER TABLE training_jobs ADD COLUMN idempotency_key TEXT NOT NULL DEFAULT '';
ALTER TABLE training_jobs ADD COLUMN parent_job_id TEXT NOT NULL DEFAULT '';
ALTER TABLE training_jobs ADD COLUMN next_poll_at INTEGER NOT NULL DEFAULT 0;
ALTER TABLE training_jobs ADD COLUMN review_required INTEGER NOT NULL DEFAULT 0;
CREATE UNIQUE INDEX IF NOT EXISTS idx_training_jobs_idempotency
ON training_jobs(idempotency_key) WHERE idempotency_key<>'';
CREATE INDEX IF NOT EXISTS idx_training_jobs_poll
ON training_jobs(status,next_poll_at,updated_at) WHERE status='running';

CREATE TABLE IF NOT EXISTS user_notifications (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    avatar_id TEXT NOT NULL DEFAULT '',
    kind TEXT NOT NULL,
    title TEXT NOT NULL,
    body TEXT NOT NULL DEFAULT '',
    action_url TEXT NOT NULL DEFAULT '',
    read_at INTEGER NOT NULL DEFAULT 0,
    created_at INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_user_notifications_unread
ON user_notifications(read_at,created_at DESC);
"""


def apply_migrations(connection: sqlite3.Connection, current_version: int) -> int:
    version = current_version
    if version < 5:
        connection.executescript(MIGRATION_5)
        version = 5
    if version < 6:
        connection.executescript(MIGRATION_6)
        version = 6
    if version < 7:
        connection.executescript(MIGRATION_7)
        version = 7
    if version < 8:
        connection.executescript(MIGRATION_8)
        version = 8
    connection.execute(
        "INSERT INTO schema_meta(key,value,updated_at) VALUES('schema_version',?,?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value,updated_at=excluded.updated_at",
        (str(version), int(time.time())),
    )
    return version
