# User guide

[中文](GUIDE.md) · [Home](../README_EN.md)

This guide describes release candidate 0.1.0. Fresh installations have no preloaded avatars. Supply your own provider accounts, models, and weights. Imports, editing, and preliminary offline persona analysis work without a model connection.

## Installation and startup

### Source installation

Install Python 3.11+, download and extract the source. On macOS open `start.command`; on Windows open `start.bat`; on Linux run `chmod +x start.sh` followed by `./start.sh`. The scripts create `.venv` and install/check dependencies. Resolve installation errors before starting the service.

The default URL is `http://127.0.0.1:8767`. Set the `PORT` environment variable to choose another port, and use that port in your browser. Closing the service terminal stops the server. Opening HTML directly only shows a static page.

See [Contributing](../CONTRIBUTING_EN.md) for development installation and tests.

### Desktop installation

If Releases provides a package matching your operating system and processor architecture, extract and run `OpenAvatar Studio.app` on macOS, `OpenAvatar Studio.exe` on Windows, or the `OpenAvatar Studio` executable on Linux.

The desktop launcher starts a local service and opens your browser; it is not an embedded-browser editor. It searches for a free port starting at 8767 and displays its URL and data directory. Exiting the launcher stops the service. Packages currently lack formal signing and may trigger unknown-publisher warnings. Verify the source before following your operating system's prompts. Build and platform verification details are in the [release guide](../packaging/README_EN.md).

### Data directories

| Installation | Default directory |
|---|---|
| Source launcher / direct server | Project `data/` |
| macOS desktop | `~/Library/Application Support/OpenAvatar Studio/` |
| Windows desktop | `%LOCALAPPDATA%/OpenAvatar Studio/` |
| Linux desktop | `$XDG_DATA_HOME/openavatar-studio/`, or `~/.local/share/openavatar-studio/` when unset |

`OPENAVATAR_DATA_DIR` overrides the directory. The database is `openavatar.sqlite`; avatar files use `avatars/`, exports use `exports/`. Source and desktop installations do not automatically merge their data. Use avatar packages to migrate, or deliberately configure a shared data location.

## First use

1. Read the onboarding guide and choose real materials or fictional settings.
2. Set identity, language, world region, and authorization.
3. Open Global AI Settings and start with the service/capability routing section.
4. Review Ability Status and Diagnostics for configuration and data destinations.
5. Follow required items and next-action suggestions in the avatar Build Center.

UI language and avatar output language are separate. Avatars support Chinese, English, mixed, and custom language choices. Regions include Mainland China, North America, Japan, Europe, and Custom. Region rules influence world runtime; they do not imply live weather or news access.

## Services and capability routing

Settings contains service/capability routes, legacy model connections, OCR, and voice/visual/video settings. The new hub supports MiniMax, Aliyun, OpenRouter, OpenAI-compatible, local, and North/Atlas connections, with per-capability primary/fallback providers and models.

Cloud consent distinguishes text, audio, voice biometrics, images, and video. Enter API keys only in dedicated credential fields, never in advanced JSON, URLs, character settings, or chat messages. Configuration and URLs are ordinary metadata, not secure credential containers.

Local services accept only `127.0.0.1`, `localhost`, or `::1`, for example `http://127.0.0.1:1234/v1`. Addresses are checked when saved and used. Local model requests bypass environment proxies and reject redirects. Previously saved remote addresses are rejected and must be corrected. See [Privacy](PRIVACY_EN.md).

Legacy connections retain support for cloud/local OpenAI-compatible APIs, Ollama, and local adapters. They use connection-test status; new capability routes do not uniformly enforce a successful test within seven days. Some media-only connection tests make no actual generation request. A successful test does not prove end-to-end media capability.

Budgets use estimated usage. Some MiniMax capabilities have defaults; other providers may record zero without custom `cost_estimates`. These budgets do not replace provider account spending limits. Consult your provider for actual billing and model availability.

## Real-material path

Create only yourself or an explicitly authorized person. Persona building needs text or chat material; audio alone cannot establish a persona. Audio supports the voice workflow, while images become visual candidates.

Chat imports accept TXT, Markdown, JSON, JSONL, CSV, and TSV. Text can use `Name: content`; common structured fields include `speaker`, `role`, `sender`, `name`, and `content`, `text`, `message`. Review speakers, exclude unwanted rows, then confirm them into evidence and memory.

PNG, JPEG, WebP, and HEIC can be stored. Metadata removal is best effort; do not assume every format has lost its EXIF/GPS data. Add text manually when OCR is unavailable. A selected cloud OCR connection is invoked during upload without another per-image confirmation; check OCR settings before uploading sensitive images.

Audio supports WAV, MP3, M4A, AAC, OGG, and FLAC. The Build Center covers sample checks, authorization, ASR/manual transcript confirmation, provider selection, cloning jobs, and voice profiles. Billable operations require UI confirmation. The default Piper entry is a development candidate, not a bundled model or complete local playback engine. Selecting a candidate does not mean cloning is complete.

## Fictional path

Use the guided Builder or import Markdown, TXT, JSON, or YAML. The parser extracts character settings; it is not a general YAML execution engine and does not run scripts.

Download Templates produces `openavatar-character-templates.txt`, containing Markdown and YAML separated by a marker. Save the desired section as a separate `.md` or `.yaml` file before filling it in and importing; do not treat the combined download as one YAML document.

The repository's [Markdown](templates/avatar.md) and [YAML](templates/character.yaml) templates match the current API, sourced from `services/templates.py`. Empty dialogue fields are for style input, not prebuilt demo avatars. Configure richer world modules through the Builder/world pages and review the extraction result after importing.

The template's `visual_identity.status: draft` denotes a character-setting draft. Registered visual asset APIs use candidate, approved, canonical, rejected, and retired, not draft.

## Building, chat, and life archives

Readiness has required, recommended, and advanced levels. Missing required items keep an avatar in preview mode. Other levels improve voice, visuals, memory, and evaluation. Offline analysis and reference-image identity preservation are not model fine-tuning.

Edit persona, boundaries, facts, and feedback rules in the studio. World runtime supports clocks, events, resources, snapshots, approval, rollback, and conflict checks. High-impact changes should be reviewed.

Text chat supports streaming and cancellation. Imported history remains separate from runtime conversations. Historical corrections overlay original records; runtime chat supports search, editing, archiving, and restoration. Editing/deleting freezes subsequent related conversations and attributable shared changes; restoration swaps timelines. Purging archived branches creates a database backup first. Preview and official timelines are distinct.

Proactive contact is off by default and only writes to the local conversation timeline while the service is running. Configure limits, hours, cooldown, and topics. It does not send SMS, email, or external-platform messages. Cloud models can incur usage charges.

## Voice, visuals, and video

Cloned speech playback needs a working provider and an activated asset. Transcripts can be provided by ASR or manually. The realtime WebSocket gateway supports text-driven streaming and interruptions. Binary audio input currently reports that realtime ASR is not configured; file transcription is not live microphone recognition.

Reference images become candidates and require approval before serving as approved/canonical identities. Organize people, clothing, objects, and scenes into continuity sets. Generated media uses applicable reference contracts; completed videos are downloaded, sampled into keyframes, and reviewed. Keyframe extraction requires FFmpeg. Without an available reviewer, manual acceptance is required.

Async video can use MiniMax, OpenRouter, or Aliyun WAN. First/multiple/last reference frames and audio depend on the selected provider/model; OpenRouter is not a fixed primary route for every task.

Realtime video uses North/Atlas. Configure a key and a canonical/approved image or HTTPS Face URL, then confirm the call. The browser loads LiveKit from a CDN, joins a remote room, and can publish cloned TTS audio to drive lip sync. Hangup requests session release; if the network fails, check remote session state and billing with the provider.

## Packages, backups, and deletion

Exports use v3; imports accept v1/v2/v3. The UI separately controls conversations, audio, images, video, and call history. Inspect locally and confirm material rights before importing. Credential fields are not transferred; provider-bound assets may require rebinding. Packages are not full database backups and do not preserve every timeline branch. See the [protocol](OPENAVATAR_PACKAGE_EN.md).

Deleting an avatar removes current records and its asset directory, not previous exports, database backups, other data directories, or provider copies. Database restore requires `RESTORE OPENAVATAR DATABASE` and makes a safety backup first. Treat packages and backups as sensitive files.

## Troubleshooting

- Static-only page: use a launcher and the actual server URL.
- Installation failure: check Python, network, and system certificates. Do not disable HTTPS verification.
- Model unavailable: check the running service, URL, model name, consent, routes, and provider quota.
- Key saving fails: check that the OS credential store is available and unlocked. Linux needs an operational Secret Service; a headless machine may not provide one.
- No OCR text: verify the optional OCR engine/language data or enter text manually.
- Missing video keyframes: check FFmpeg and the actual video file. Generation success does not imply continuity acceptance.
- Desktop package issues: try the source installation for diagnosis. Windows/Linux desktop behavior requires native-platform verification.

See [Privacy](PRIVACY_EN.md) for data boundaries and [Security](../SECURITY_EN.md) for reporting.
