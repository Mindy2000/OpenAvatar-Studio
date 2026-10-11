# User guide

[中文](GUIDE.md) · [Quick start](QUICKSTART_EN.md) · [Home](../README_EN.md)

This guide describes release candidate 0.1.0. Fresh installations have no preloaded avatars. Supply your own provider accounts, models, and weights. Imports, editing, and preliminary offline persona analysis work without a model connection.

First-run setup, call limits and segmented speech, document questions, and chat memory controls are unreleased source upgrades; see the [changelog](../CHANGELOG.md). The instructions and boundaries below do not establish live paid-service acceptance for those upgrades.

## Installation and startup

When a chat capability route is configured in the provider hub, the creation wizard uses it directly without requiring a legacy model connection. Build readiness also checks the route's consent, enabled state, credentials, and budget.

Guided persona analysis uses the latest answers for enabled modules. Superseded answers remain historical evidence and are not fed back into the analysis.

### Source installation

Install Python 3.11+, download and extract the source. On macOS open `start.command`; on Windows open `start.bat`; on Linux run `chmod +x start.sh` followed by `./start.sh`. The scripts create `.venv` and install/check dependencies. Resolve installation errors before starting the service.

The default URL is `http://127.0.0.1:8767`. Set the `PORT` environment variable to choose another port, and use that port in your browser. Closing the service terminal stops the server. Opening HTML directly only shows a static page.

See [Contributing](../CONTRIBUTING_EN.md) for development installation and tests.

### Desktop installation

Download a package matching your operating system and processor architecture from [Releases](https://github.com/Mindy2000/OpenAvatar-Studio/releases). Desktop packages include Python; no separate Python installation is needed. Fully extract and run `OpenAvatar Studio.app` on macOS, `OpenAvatar Studio.exe` on Windows, or the `OpenAvatar Studio` executable on Linux.

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

1. On an empty database without existing configuration, first launch shows three steps: configure Chat → optionally add Voice/Images → complete an avatar and chat.
2. Configure opens the existing service hub. After saving a connection, choose its service and model for the capability. Closing settings returns to the guide; you can also refresh its status manually.
3. Voice and images are optional. Avatar creation still collects identity, language, region, and material rights; the guide does not fill in or bypass consent.
4. Complete required items in Build Center before chatting. Existing users are not forced into the guide. Dismissal is saved, and the top-bar entry reopens it.

The guide checks saved routes, enabled state, models, consent, credential presence, and estimated budgets locally. It does not probe cloud services or call a model. Locally configured does not verify provider balance, model access, or an actual reply; use Ability Status and Diagnostics for further troubleshooting.

UI language and avatar output language are separate. Avatars support Chinese, English, mixed, and custom language choices. Regions include Mainland China, North America, Japan, Europe, and Custom. Region rules influence world runtime; they do not imply live weather or news access.

Change the interface language in Global AI Settings to update pages, guided questions, buttons, dialogs, diagnostics, and task notices. The desktop launcher follows the saved preference too. Unsaved form entries are preserved. Avatar names, materials, chats, imported documents, and custom world content stay in their original language; configure the avatar language separately for English replies. Raw technical responses from external providers may remain in the provider’s language.

## Services and capability routing

Settings contains service/capability routes, legacy model connections, OCR, and voice/visual/video settings. The new hub supports MiniMax, Aliyun, OpenRouter, OpenAI-compatible, local, and North/Atlas connections, with per-capability primary/fallback providers and models.

Cloud consent distinguishes text, audio, voice biometrics, images, and video. Enter API keys only in dedicated credential fields, never in advanced JSON, URLs, character settings, or chat messages. Configuration and URLs are ordinary metadata, not secure credential containers.

Local services accept only `127.0.0.1`, `localhost`, or `::1`, for example `http://127.0.0.1:1234/v1`. Addresses are checked when saved and used. Local model requests bypass environment proxies and reject redirects. Previously saved remote addresses are rejected and must be corrected. See [Privacy](PRIVACY_EN.md).

Legacy connections retain support for cloud/local OpenAI-compatible APIs, Ollama, and local adapters. They use connection-test status; new capability routes do not uniformly enforce a successful test within seven days. Some media-only connection tests make no actual generation request. A successful test does not prove end-to-end media capability.

Unified routes reserve daily/monthly estimates before dispatch. Failed or interrupted attempts retain reservations with unknown settlement. A configured budget without a reliable estimate for that capability blocks calls; an unbudgeted unknown price is not free. Provider billing and model availability remain authoritative. Legacy paths and independent OCR do not necessarily share this budget mechanism. Inactive legacy task-model routes are no longer editable; configure capability routes in the service hub.

## Real-material path

Create only yourself or an explicitly authorized person. Persona building needs text or chat material; audio alone cannot establish a persona. Audio supports the voice workflow, while images become visual candidates.

Chat imports accept TXT, Markdown, JSON, JSONL, CSV, and TSV. Text can use `Name: content`; common structured fields include `speaker`, `role`, `sender`, `name`, and `content`, `text`, `message`. Review speakers and exclude unwanted rows; Previous/Next pages preserve selections. Confirmation imports only reviewed, checked rows. Unviewed rows do not automatically become evidence or memory.

PNG, JPEG, WebP, and HEIC can be stored. Metadata removal is best effort; do not assume every format has lost its EXIF/GPS data. Add text manually when OCR is unavailable. A selected cloud OCR connection is invoked during upload without another per-image confirmation; check OCR settings before uploading sensitive images.

Audio supports WAV, MP3, M4A, AAC, OGG, and FLAC. The Build Center covers sample checks, authorization, ASR/manual transcript confirmation, provider selection, cloning jobs, and voice profiles. Billable operations require UI confirmation. The default Piper entry is a development candidate, not a bundled model or complete local playback engine. Selecting a candidate does not mean cloning is complete.

## Fictional path

Use the guided Builder or import Markdown, TXT, JSON, or YAML. The parser extracts character settings; it is not a general YAML execution engine and does not run scripts.

Download Templates produces `openavatar-character-templates.txt`, containing Markdown and YAML separated by a marker. Save the desired section as a separate `.md` or `.yaml` file before filling it in and importing; do not treat the combined download as one YAML document.

The repository's [Markdown](templates/avatar.md) and [YAML](templates/character.yaml) templates match the current API, sourced from `services/templates.py`. Empty dialogue fields are for style input, not prebuilt demo avatars. Configure richer world modules through the Builder/world pages and review the extraction result after importing.

The template's `visual_identity.status: draft` denotes a character-setting draft. Registered visual asset APIs use candidate, approved, canonical, rejected, and retired, not draft.

## Building, chat, and life archives

Readiness has required, recommended, and advanced levels. Missing required items keep an avatar in preview mode. Other levels improve voice, visuals, memory, and evaluation. Offline analysis and reference-image identity preservation are not model fine-tuning.

Edit persona, boundaries, facts, and feedback rules in the studio. World runtime supports clocks, events, resources, snapshots, approval, rollback, and conflict checks. High-impact changes should be reviewed. A different value for an already-pending fact requires approving or rejecting the earlier proposal first. Rollback retires subsequent runtime events, and advancing again reapplies their effects. Later chats read current persona and world settings.

Text chat supports streaming and cancellation. Imported history remains separate from runtime conversations. Historical corrections overlay original records; runtime chat supports search, editing, archiving, and restoration. Editing/deleting freezes subsequent related conversations and attributable shared changes; restoration swaps timelines. Purging archived branches creates a database backup first. Preview and official timelines are distinct.

Proactive contact is off by default and only writes to the local conversation timeline while the service is running. Configure limits, hours, cooldown, and topics. It does not send SMS, email, or external-platform messages. Cloud models can incur usage charges. Enablement and rules save together. Failed attempts count toward intervals and rolling 24-hour limits; three consecutive failures pause contact. Check the connection and save settings to resume without clearing consumed attempts. Disabling or changing rules discards stale pending greetings.

## Voice, visuals, and video

To use speech without cloning, select a MiniMax preset voice in the build center. Configure a MiniMax TTS route with text consent first, then play a chat reply and confirm the charge. Selecting a preset makes no cloud call and incurs no cloning fee; synthesis is still billed by the provider. Presets do not count as completed voice cloning.

Cloned speech playback needs a working provider and an activated asset. Transcripts can be provided by ASR or manually. The realtime WebSocket gateway supports text-driven streaming and interruptions. Binary audio input currently reports that realtime ASR is not configured; file transcription is not live microphone recognition.

Reference images become candidates and require approval before serving as approved/canonical identities. Organize people, clothing, objects, and scenes into continuity sets. Generated media uses applicable reference contracts; completed videos are downloaded, sampled into keyframes, and reviewed. A job cannot be submitted twice concurrently. Cancelling submitted work may still incur provider charges, but late results are not activated. Failed review requires manual action rather than automatic paid regeneration; missing review frames cannot count as a pass. Keyframe extraction requires FFmpeg. Without an available reviewer, manual acceptance is required.

Async video can use MiniMax, OpenRouter, or Aliyun WAN. First/multiple/last reference frames and audio depend on the selected provider/model; OpenRouter is not a fixed primary route for every task.

Realtime video uses North/Atlas. Configure a key and a canonical/approved image or HTTPS Face URL, then confirm the call. The browser loads LiveKit from a CDN, joins a remote room, and can publish cloned TTS audio to drive lip sync. Hangup or leaving the page stops local cameras/microphones first, then requests remote release. Late session creation triggers a compensating release. Failed release can be retried; check remote state and billing with the provider.

The video-call microphone input button uses browser speech recognition, independently of your configured voice API key. It asks for confirmation before starting because the browser may use an online recognition service. Review the transcript before sending; if unsupported or unwanted, type instead. This is separate from the unfinished binary-audio ASR path in the application WebSocket gateway.

## Packages, backups, and deletion

Exports use v3; imports accept v1/v2/v3. The UI separately controls conversations, audio, images, video, and call history. Inspect locally and confirm material rights before importing. Credential fields are not transferred; provider-bound assets may require rebinding. Packages are not full database backups and do not preserve every timeline branch. See the [protocol](OPENAVATAR_PACKAGE_EN.md).

Deleting an avatar removes current records and its asset directory, not previous exports, database backups, other data directories, or provider copies. Database restore requires `RESTORE OPENAVATAR DATABASE`. It checks OpenAvatar structure and validates/migrates a temporary copy before replacement; invalid backups leave current data intact. The pre-restore safety copy appears in the same list and can be restored to undo the operation. Schema v9 upgrades also create a backup. Current source rejects databases above its supported version; do not open an upgraded database with an older application that lacks this protection. Treat packages and backups as sensitive files.

Ordinary reply playback permits one pending synthesis request/player, preventing overlapping clicks. This is not a permanent speech cache; a separate confirmed replay may synthesize and incur cost again.

## Troubleshooting

- Static-only page: use a launcher and the actual server URL.
- Installation failure: check Python, network, and system certificates. Do not disable HTTPS verification.
- Model unavailable: check the running service, URL, model name, consent, routes, and provider quota.
- Key saving fails: check that the OS credential store is available and unlocked. Linux needs an operational Secret Service; a headless machine may not provide one.
- No OCR text: verify the optional OCR engine/language data or enter text manually.
- Missing video keyframes: check FFmpeg and the actual video file. Generation success does not imply continuity acceptance.
- Desktop package issues: try the source installation for diagnosis. Windows/Linux desktop behavior requires native-platform verification.

See [Privacy](PRIVACY_EN.md) for data boundaries and [Security](../SECURITY_EN.md) for reporting.

### Data maintenance

Settings & Export → Data maintenance provides memory editing and approval, world conflict checks and resolution, and database backups and restore. Proposing a conflict candidate sends it to fact approval rather than approving it immediately. Database restore affects all avatars in the current data directory and first creates a safety backup; it does not replace media files or system credentials. In an image import review, add or correct image text before confirming it. Already confirmed text must be revised through memories.

## Chat composer and browser voice calls

The + panel offers images/video, camera, calls, files, manual locations, and favorites. Calls branch into voice and video. Hold to record, release to send, or slide upward to cancel; recordings shorter than 0.5 seconds are discarded and the maximum is 60 seconds. Without recognized text, only the recording is saved. Voice-note replies are capped at 80 characters. Camera preview and capture are mirrored by default, with an option to disable mirroring.

Chat image understanding is separate from imported-image OCR. With an authorized vision route, sending a photo requests an image-based reply; older photos have an explicit action. Results are cached only while their source and complete reply are unchanged, active and on the valid timeline. Editing, rollback or deactivation clears stale caches; failures require manual retry. File uploads are stored for display; supported text files require an explicit Read this file action before questions. Videos are not automatically interpreted. Chat attachments do not automatically become persona-building materials.

Start a browser voice call from + → Calls → Voice. Before starting, set its duration (1–120 minutes, default 10) and estimated CNY allowance (0.01–1,000, default 5). The microphone starts after Start call. The new flow no longer has a fixed three-turn limit: it warns near limits and ends at the deadline or when the remaining allowance cannot cover the next request. The allowance covers chat and speech synthesis estimates, not a hard cap on provider bills. Unknown cloud prices require an explicit valid estimate. Failed or interrupted requests may still be billed, so their estimated reservations are not refunded.

Before starting, local checks verify that voice is enabled, the voice matches its connection, consent and a saved key exist, and estimates/budgets are valid; they make no cloud test request. Before each model reply, a conservative feasibility check covers chat plus up to three speech segments. Estimates are reserved separately only as requests start, avoiding double reservation. The selected voice connection's enabled state, consent, and budget are rechecked during the call without automatically changing its voice or connection.

Replies remain limited to 80 characters and use the configured chat model and selected voice. Completed sentences can begin synthesis/playback early, with at most three speech segments per reply. This may mean up to three TTS requests and different totals for providers charging per request; faster playback is not guaranteed under every network condition. Segments play in order; interruption cancels old playback and queued segments. Failures do not automatically retry or switch providers.

Mute, speech interruption, manual interruption, minimize, and hangup are supported. Browser recognition sends text to the call gateway. A separate local microphone-level monitor stops playback early; headphones are recommended. Speaker echo, noise, and other devices need their own checks. Switching browser tabs does not end the call. Closing or reloading the page, switching avatars, or leaving the in-app chat page ends it.

The call window has no per-utterance captions. Fixed on 2026-10-05: main chat and history search hide voice_call transcripts while retaining call cards; local transcripts remain available to model context. Disabling call-history export excludes call cards, voice_call messages, sessions/turns, and all reply diagnostics. Legacy synthesized audio cannot distinguish calls from auditions, so all generated/audio files are also omitted. Original recordings and voice-note attachments follow the audio option. This does not delete local data or independently authored persona settings or memories.

Proactive greetings use local time, an 80-character cap, and instructions not to invent weather, location, or activities; these instructions do not guarantee every response. Memory maintenance supports checked merges and revision history. Imported usage events marked imported_history do not count against current connection budgets.


Ordinary text and voice-note replies enforce an 80-character limit including punctuation, consistently across streamed output and persistence. The previous version has Mac acceptance evidence for its English interface, full cloud interruption/continuation, and mirrored-camera, send, and image-understanding flow. That evidence does not establish live paid-service acceptance for this round's segmented calls, limits, or document questions, nor acceptance on other devices or every provider.

### Explicit document questions

1. Send a TXT, MD, CSV, or text-layer PDF through + → Files, then click Read this file beside its card.
2. Enter a question, or leave it blank for a summary. Confirm sending extracted text, the question, and current conversation context to the current chat service, then send.
3. Review the reply of up to 80 characters and its file-source button. Ask follow-up questions explicitly in the file dialog; ordinary chat does not automatically attach the full document again.

Text files are limited to 2 MB; PDFs to 10 MB and 20 pages; all extracted text to 20,000 characters. Oversized files are rejected and must be split. Only PDF text layers are read: there is no OCR, and images or pages without text are not considered read. Encrypted, damaged, or timed-out PDFs are rejected. Each explicit question makes at most one current-chat-service call, with no automatic retry or provider switch. A successful default summary for the same file can be reused. Files do not automatically become persona settings, memories, or world facts.

Summary caches are reused only while the complete, unchanged question/answer pair remains active on the current timeline. After editing, rollback, or deactivation, explicitly confirm a new summary; the discarded answer is not reused.

### Manage memory beside a message

Click Memory beside a text or transcribed voice message, review/edit the content, then choose Remember this, Correct and remember, or Stop using this. After user confirmation these actions run locally without a model call and retain revision records.

Correction or stopping use excludes the original message and same-turn reply from future context. Stopping use also deactivates linked memories; corrected memory remains available. If the chat note has been merged into another memory, the dialog warns beforehand that changing or stopping the source also deactivates memories containing it. Original chat history stays visible. This does not delete history or independently saved material, or recall requests already sent to providers. Preview and official memories cannot be merged together. Sleep consolidation skips explicitly saved chat notes and their merged derivatives, preserving source-based correction and deactivation.

Editing or rejecting chat-source memories in Data Maintenance also excludes their source context and deactivates merged derivatives. If a pending document question is rolled back, edited, deactivated, or its avatar is deleted, a late reply is not inserted back into chat. Requests already sent may still incur charges.

Restoring an archived timeline does not undo explicit memory corrections or deactivations made after it was archived. Rolling back chat also deactivates merged memories that contain the removed sources. Reapproval in Data Maintenance restores a usable memory kind; merged duplicates cannot be independently reactivated. Persona analysis, chat and proactive greetings use effective corrected sources; preview notes do not enter the official persona. Sleep consolidation deduplicates identical sources, retires old summaries after source correction, and uses corrected text on the next consolidation.

### Capability boundaries for this round (unreleased)

| Capability | Entry | Calls and limits |
|---|---|---|
| First-run guidance | Top-bar guide / first empty launch | Local checks only; no service test or model call |
| Call duration and estimated allowance | Before starting a voice call | Server checks estimates before requests; no hard cap on actual bills |
| Segmented call speech | Normal voice-call replies | Same model/voice, at most three TTS calls per reply; distinct from recorded voice notes |
| Document questions | Read this file on a file card | At most one chat call after confirmation; size/page/character limits and no OCR |
| Chat memory controls | Memory beside a message | Confirmed local save/correction/deactivation; history and separate material remain |
| Paged review and persona sources | Import review / persona analysis or editing | Only reviewed, checked rows are accepted; official persona excludes preview/deactivated notes and uses historical corrections |
| Maintenance and world rollback | Maintenance dialog / world page | Older-memory editing, reapproval, summary deduplication and event rollback; cannot recall data already sent to providers |
| Packages and database restore | Settings & Export | Local corrupt-package, source-mapping and restore-undo checks; database copies do not include assets/credentials |
| Proactive contact | Proactive settings | Failed attempts count toward rolling 24-hour limits; three consecutive failures pause contact; local chat only |
| Media jobs and costs | Service hub / Build Center | Routed calls atomically reserve estimates; cancelled late results are not activated; remote billing/cancellation remains provider-controlled |

The 2026-10-12 fixes are checked with synthetic materials, temporary databases, loopback protocol servers, frontend controllers and browser flows. These checks do not extend earlier live API, camera/microphone or other-platform acceptance, and do not include separately listed experience upgrades.


### Cost estimates and usage records (2026-10-12)

Unified capability routes check enabled state, consent and estimates before dispatch, atomically reserving daily/monthly estimated budgets. Concurrent requests share reserved amounts. Each request settles once using the estimate frozen at dispatch; later price edits do not change old records. Complete normal chat adjusts its estimate using returned characters. Failure, interruption or early truncation retains the conservative reservation with unknown settlement. Polling an existing video task does not charge another local generation estimate. Estimates are not actual debits or hard caps on provider bills.

A daily/monthly budget without a reliable estimate blocks calls. Set a per-call CNY amount for the capability in advanced `cost_estimates`. Unknown prices without a configured budget can proceed but are recorded as unknown, not free. Some MiniMax capabilities retain code defaults; these are not promises of current provider pricing.

Voice cloning still requires a valid per-call CNY estimate. The code default for Mainland MiniMax official endpoints is CNY 9.90 per voice; international endpoints, proxies and other services cannot inherit it. Valid custom values take precedence, and cloud cloning rejects zero, negative and nonfinite values. Cloning and audition synthesis are accounted separately. An unavailable configured route does not silently use an older account; voice ownership must match its account.

Unified-budget guarantees do not cover legacy paths without the corresponding capability route (including legacy model, Aliyun and North configurations), or independently configured OCR. Prefer the unified service hub for new setups; legacy use still needs provider-side limits. Cancellation prevents subsequent local handling/activation, not guaranteed remote cancellation or refunds. This round adds no successful live-service acceptance claim.
