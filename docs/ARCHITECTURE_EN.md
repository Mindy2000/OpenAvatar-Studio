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
| `i18n/` | Chinese/English resources; some dynamic text remains in scripts |

## Data and timelines

`imports`, `evidence`, and non-`runtime_chat` memories form imported history. `historical_memory_corrections` overlays corrections. `messages` stores runtime conversations, while `chat_timeline_branches` tracks active/archived official and preview branches. `source_message_id` associations limit changes to attributable memory and world effects.

Migration and pre-restore backups use SQLite backup facilities. Packages include only protocol-listed transferable data and cannot replace database backups; full branch and historical-correction tables are not exported. See the [package protocol](OPENAVATAR_PACKAGE_EN.md).

## Providers and media

`provider_connections` and `capability_routes` store providers, capabilities, consent, budgets, and routes. Connection IDs map dedicated keys to the OS store. Legacy `model_connections` and cloud settings remain supported. Avatar routes can override global choices; candidate providers support fallback.

MiniMax, Aliyun, and OpenRouter differ in capabilities. Video adapters consume continuity reference contracts rather than a universal fixed primary/fallback order. Background workers poll/download results, FFmpeg extracts keyframes, and review determines retry or manual acceptance. Keyframes never automatically become canonical identity references.

North/Atlas creates/releases sessions. The browser loads LiveKit from a CDN and subscribes to avatar tracks; cloned TTS can be published to the room. Separately, `/ws/avatars/{id}/call` handles text input and streaming text output; binary realtime ASR is not integrated.

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
