# Avatar package protocol v3

[中文](OPENAVATAR_PACKAGE.md) · [User guide](GUIDE_EN.md)

The extension is `.openavatar.zip`. Current exports use `format: openavatar.package`, `version: 3`; imports accept v1, v2, and v3. Implementation: `openavatar/services/packages.py`.

Packages migrate avatar content, do not copy the OS credential store, and are not complete database snapshots. Use database backups for full database recovery.

## Structure

Preflight requires `manifest.json`, `memories.json`, and `messages.json`. Other sections are optional. Current exports generally write their JSON files even when privacy filters empty their content.

| Files | Contents |
|---|---|
| `manifest.json` | Version, timestamp, avatar/persona, language/region, legacy model settings/hints, protocol, privacy declarations |
| `language_profile.json`, `world_region_profile.json` | Avatar language and region rules, not the user's UI language |
| `memories.json`, `messages.json`, `evidence.json`, `rights.json` | Memory, conversations, evidence, rights |
| `world_facts.json`, `world_events.json`, `world_fact_proposals.json` | World facts, events, proposals |
| `world_modules.json`, `world_runtime_settings.json`, `world_conflicts.json`, `world_snapshots.json` | Modules, settings, conflicts, snapshots |
| `memory_revisions.json`, `memory_graph_nodes.json`, `memory_graph_edges.json` | Revisions and graphs |
| `persona_core.json`, `persona_feedback_rules.json` | Cached persona core and feedback |
| `visual_assets.json`, `visual_asset_sets.json`, `scene_profiles.json`, `video_keyframes.json` | Visual records, continuity sets, scenes, keyframes |
| `voice_profiles.json`, `voice_transcriptions.json`, `voice_events.json` | Voice profiles, transcripts, events |
| `media_reviews.json`, `build_reports.json`, `builder_answers.json`, `quality_evaluations.json` | Reviews, building, answers, evaluation |
| `proactive_rules.json`, `decision_explanations.json`, `usage_events.json` | Proactive rules, decisions, usage |
| `realtime_call_sessions.json`, `realtime_call_turns.json` | Call sessions and turns |
| `imports.json`, `provider_assets.json` | Import metadata and external assets |
| `assets/` | Imported/generated avatar files filtered by export options |

New service-hub connections and capability routes are not migrated as a ready-to-use credential environment. `model_connection_hint` contains legacy connection metadata, not dedicated key fields.

## Export options

| Disabled option | Current behavior |
|---|---|
| Conversations | Empty runtime messages; filter conversation/imported memories, related evidence, and chat source files; empty decisions, revisions, graphs, and cached persona core |
| Audio | Exclude imported/generated audio files, transcripts, and voice provider assets; some voice-profile metadata remains |
| Images | Exclude images and keyframe files; empty visual records, sets, scenes, keyframes, and related visual/video reviews |
| Video | Exclude generated video files, keyframe records, video assets/reviews; the independent image option still affects keyframe files |
| Call history | Empty realtime sessions/turns; does not replace the conversation option |

API parameters are `include_conversations`, `include_audio`, `include_images`, `include_video`, and `include_call_history`. The UI sends all five. For older clients omitting `include_video`, it follows the image option.

These filters do not anonymize content. Summaries, world facts, user-entered secrets, and text inside images can remain. See [Privacy](PRIVACY_EN.md). A no-keys manifest declaration is not a full-content secret scan.

## Import and compatibility

- Local preflight checks format, version, required files, paths, member count, and expanded size, and displays content/model hints.
- Maximum 2,000 members and 1 GiB total expanded size. Upload size for import is `min(MAX_UPLOAD_MB × 10, 1024)` MiB, normally 500 MiB; ordinary material uploads default to 50 MiB.
- Absolute paths, parent traversal, backslashes, and Windows drive forms are rejected. Required JSON types are validated.
- After rights confirmation, import creates a new avatar ID and remaps paths. Dedicated API keys are not imported.
- Provider-bound assets require checking/rebinding; retaining an external ID does not grant access under a new account.
- Missing v1/v2 sections receive implementation defaults. An older v1 warning may still mention v2; current exports remain v3.

Packages do not export the complete `chat_timeline_branches` and `historical_memory_corrections` tables. They cannot guarantee restoration of every archived branch, display correction, or internal ID relationship. Back up the database and asset directory for precise local-state preservation.

## States

Registered visual asset APIs accept `candidate`, `approved`, `canonical`, `rejected`, and `retired`. `draft` in blank character templates refers to a settings draft, not a writable registered-asset state. Candidates must not serve as canonical identity references before approval.

Readiness levels are `required`, `recommended`, and `advanced`. World reality kinds include `real_verified`, `user_confirmed`, `fictional_canon`, `fictional_runtime`, and `hybrid_derived`; mutability includes `locked`, `approval_only`, `evolving`, and `historical`.
