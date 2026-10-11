# Architecture

[中文](ARCHITECTURE.md) · [User guide](GUIDE_EN.md)

## Runtime

FastAPI serves local HTTP APIs, streaming chat, WebSockets, and a static frontend. The desktop launcher runs the same backend and opens the system browser. SQLite stores avatars, evidence, worlds, timelines, connection metadata, and runtime records. Assets live in the data directory; dedicated credentials use the OS store.

`main.py` assembles the app, lifecycle, metrics middleware, and routes. Importing it creates the application and initializes the database, so tests/maintenance must set an isolated data directory first. The desktop launcher imports it after selecting its directory.

## Modules

| Module | Responsibility |
|---|---|
| `config.py`, `db.py`, `migrations.py` | Configuration, SQLite WAL/transactions, migrations/backups; current schema v8 |
| `application.py` | Shared application context |
| `routes/` | System, avatar, import, world, identity, continuity, intelligence, media, archive, runtime, and chat APIs |
| `routes/_shared.py` | Shared imports used by route modules; not safely removable based only on local references |
| `services/provider_hub.py`, `model_connections.py` | New capability routes and legacy model compatibility |
| `providers.py`, `local_model.py` | OpenAI-compatible, Ollama, local adapters, and credentials |
| `services/minimax.py`, `aliyun.py`, `video_generation.py`, `video_call.py` | Provider multimedia adapters and North/Atlas calls |
| `services/continuity.py`, `media_jobs.py`, `video_review.py` | Reference contracts, video polling, keyframes, and acceptance |
| `services/persona*`, `memory_intelligence.py`, `evidence.py` | Persona, evidence, memory, feedback, and Persona Core |
| `services/world_*`, `guided_builder.py`, `readiness.py` | Regions, world runtime, guided building, and readiness gates |
| `services/timeline_archive.py`, `packages.py` | Timeline management and package migration |
| `runtime.py`, `events.py` | Run IDs, cancellation, metrics, leases, Supervisor, events, and Outbox |
| `static/core.js`, `profile.js`, `settings.js` | Page foundations, studio, and settings |
| `static/imports.js`, `chat.js`, `video-call.js`, `app.js` | Imports, chat, LiveKit, and event wiring |
| `routes/chat_media.py`, `services/chat_vision.py` | Chat attachments, avatar/timeline validation, pixel-based image understanding and successful-result caching; failed image requests require a manual retry |
| `routes/calls.py`, `static/voice-call.js` | Browser recognition, text WebSocket, TTS, interruption and call records |
| `services/call_policy.py` | Unreleased: server-side time/estimated-budget limits and at most three sentence segments; no automatic call retries or model/voice switches |
| `routes/chat_documents.py`, `services/chat_documents.py`, `static/chat-documents.js` | Unreleased: explicit file questions, bounded local text extraction, confirmation, and single calls |
| `routes/chat_memory.py`, `static/chat-memory.js` | Unreleased: confirmed memory, correction/deactivation, and source-message context exclusion |
| `routes/setup.py`, `services/setup.py`, `static/onboarding.js` | Unreleased: three-step guidance, local configuration status, and saved dismissal; reuses settings and creation |
| `static/chat-composer.js`, `static/maintenance.js` | Attachment interactions, memory editing, merges and revision history |
| `i18n/` | Chinese/English UI catalogs for static text, dynamic notices, and system messages; template parameters preserve user content |

## Data and timelines

`imports`, `evidence`, and non-`runtime_chat` memories form imported history. `historical_memory_corrections` overlays corrections. `messages` stores runtime conversations, while `chat_timeline_branches` tracks active/archived official and preview branches. `source_message_id` associations limit changes to attributable memory and world effects.

Migration and pre-restore backups use SQLite backup facilities. Packages include only protocol-listed transferable data and cannot replace database backups; full branch and historical-correction tables are not exported. See the [package protocol](OPENAVATAR_PACKAGE_EN.md).

## Providers and media

`provider_connections` and `capability_routes` store providers, capabilities, consent, budgets, and routes. Connection IDs map dedicated keys to the OS store. Legacy `model_connections` and cloud settings remain supported. Avatar routes can override global choices. Candidates are filtered by enabled state, data consent and estimated budget; each consumer decides whether to try fallback candidates. Current chat image understanding uses only the first available candidate, retains the image on failure and requires a manual retry rather than silently switching providers.

Voice-cloning capability routes call `prepare_voice_clone_cost` before upload to validate the per-call CNY estimate and remaining daily/monthly budgets. A configured but unavailable cloning route does not fall back to a legacy connection. With no cloning route configured, `routes/media_runtime.py` retains a legacy Aliyun path without equivalent estimate validation or budget preflight. These checks are neither atomic reservations for concurrent calls nor hard limits on provider bills.

MiniMax, Aliyun, and OpenRouter differ in capabilities. Video adapters consume continuity reference contracts rather than a universal fixed primary/fallback order. Background workers poll/download results, FFmpeg extracts keyframes, and review determines retry or manual acceptance. Keyframes never automatically become canonical identity references.

North/Atlas creates/releases sessions. The browser loads LiveKit from a CDN and subscribes to avatar tracks; cloned TTS can be published to the room. Separately, `/ws/avatars/{id}/call` handles text input and streaming text output; binary realtime ASR is not integrated.

The unreleased call protocol uses `openavatar.realtime-call.v3`. The server tracks duration and an estimated CNY allowance, reserving estimates before each chat or speech-segment request; failures/interruption do not refund reservations. Text retains the 80-character limit, with up to two early complete-sentence segments and one remainder. The client requests TTS and plays segments in order. Each request needs the valid session token, run ID, and sequence; duplicates and stale replies are rejected, and ending/interruption discards old playback queues. Segmentation can create up to three TTS requests. Estimates are not hard billing caps, and this does not change models or voices.

Browser voice calls connect with `voice=true` and locally preflight voice configuration, consent, credentials, and estimates; the default text WebSocket mode remains compatible. Each turn checks conservative headroom for chat plus up to three TTS segments before reserving each request separately. The fixed voice connection's state, consent, prices, and budgets are reread; failed stale synthesis does not terminate a new turn.

Document questions are separate from uploads. After explicit confirmation, `chat_documents` extracts text from one attachment and makes at most one current-chat-service call, without automatic retry/failover. Limits are 2 MB for text, 10 MB/20 pages for PDFs, and 20,000 total characters. A resource-limited subprocess parses PDF text layers without OCR. Document content is reference data, not system instructions. The original stays local; chat saves questions, replies, and sources, without automatically reattaching the full text to every later chat.

Chat memory actions reuse revisions, memory graphs, and persona caches. Correction/deactivation sets `context_excluded` on the source and same-turn messages, and retrieval ignores deactivated linked memories; original messages remain. Setup uses boolean `has_key` results and existing budget rules, passing `model_ready` into the original readiness checks instead of constructing a secret-bearing model client. It performs no network probes.

## Runtime APIs

- `POST /api/avatars/{id}/chat/stream`: streaming chat.
- `POST /api/runtime/runs/{run_id}/cancel`: cancellation.
- `/ws/avatars/{id}/call`: text-driven call WebSocket.
- `GET /api/runtime/metrics`: metrics and database integrity.
- `/api/system/backup`, `/api/system/backups`: backup/list/confirmed restore operations.
- `GET /api/templates/character`: Markdown/YAML templates defined in `services/templates.py`.

The running `/docs` and `/openapi.json` provide the full API. Standard launchers bind to loopback; the project is not an authenticated public gateway.

## Current boundaries

[Privacy](PRIVACY_EN.md) documents loopback validation and local model network restrictions, automatic OCR, estimated budgets, connection tests, logs, and deletion scope. Local model requests bypass proxies and reject redirects; the other documented limitations remain unchanged.

Repository templates are synchronized copies of runtime definitions; update both together. Blank templates contain no demo avatars. See [Contributing](../CONTRIBUTING_EN.md) for documentation checks.

## New chat modules and verification boundaries (updated 2026-10-05)

chat_media.py and chat-composer.js implement attachments, locations, favorites, mirrored capture, and release-to-send voice notes. chat_vision.py validates image ownership/timeline, sends pixels, and caches descriptions and capped replies. voice-call.js combines browser recognition, the text WebSocket gateway, TTS, and local microphone/interim-result interruption. maintenance.js adds memory merges and revisions.

Call transcripts use voice_call: listings and history hide them while model preparation includes them. When call-history export is disabled, the package excludes their messages, cards, sessions/turns, reply diagnostics, and synthesized audio without reliable provenance. ChatService enforces 80 characters for ordinary and streamed replies, including preview. The previous version has Mac acceptance evidence dated 2026-10-05 for Chinese/English UI, cloud interruption/continuation, and mirrored-camera, send, and image understanding. This does not establish live paid acceptance for the unreleased segmented-call/document flows, or acceptance on other devices or providers.
