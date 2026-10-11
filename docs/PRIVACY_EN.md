# Privacy and data boundaries

[中文](PRIVACY.md) · [User guide](GUIDE_EN.md)

OpenAvatar handles chats, voice, and likeness data. Import only your own, explicitly authorized, or original fictional materials. Source releases contain no personal avatars or credentials; runtime files are separate from public source.

## Local storage

Source installations default to project `data/`; desktop installations use OS application-data directories. `OPENAVATAR_DATA_DIR` overrides the location. Platform paths are listed in the [user guide](GUIDE_EN.md). The directory contains SQLite records, assets, generated media, exports, and backups.

Ignore rules exclude default personal-data paths, databases, avatar packages, `.env` files, and build outputs. If you choose another data location inside the source tree, check its ignore coverage. Do not upload the whole local directory or assume `.git` is clean source.

## API keys

Dedicated credential fields are sent to the local backend and stored in the OS credential store. Normal connection responses indicate whether a key exists without returning that field. Availability depends on the platform's credential service. Developers may use supported environment variables; arbitrary `.env` files are not loaded automatically.

Do not put keys into connection URLs, advanced JSON, metadata, character settings, chat, screenshots, or imported files. These are ordinary content and may be saved, displayed, or exported. The application is not a universal secret-detection or redaction tool. Packages omit dedicated credential fields, not every possible secret inside raw materials.

## Network and consent

- Standard launchers listen on `127.0.0.1`. HTTP writes and WebSockets check origins; this is not public multi-user authentication.
- Analysis and chat may send persona, selected material, recent messages, and retrieved memory to a configured service. The hub stores per-capability/data-class consent; fallback can change the recipient provider.
- MiniMax, Aliyun, OpenRouter, and other multimedia integrations receive supported text, audio, references, and video parameters. Billable media operations have UI confirmation. Once confirmed, background polling, downloads, and task retries do not prompt for every request.
- **OCR exception:** an already selected and authorized cloud OCR connection runs immediately during image upload, without another per-image prompt. Check OCR settings before uploading sensitive screenshots; local OCR or manual text are alternatives.
- **Local model connections:** the hub and legacy model connections accept only HTTP/HTTPS URLs on `127.0.0.1`, `localhost`, or `::1`. Validation applies when saving and using connections, including old configurations. Model discovery and local model calls bypass environment proxies and reject redirects. This restricts this application’s destination; a locally installed model service may independently use the network.
- A successful connection test does not prove every capability works. Some media-only tests make no generation request, and new routes do not uniformly require a recent successful test.
- Daily/monthly budgets compare estimated local usage. Some providers record zero without custom estimates, so these are not hard caps on real bills.
- North/Atlas calls send identity images or Face URLs, room metadata, and realtime tracks. The frontend loads LiveKit from a CDN. Hangup requests session release; failures may require action with the provider.
- **Browser speech input:** the microphone-to-text button in video calls uses browser SpeechRecognition, independently of configured voice providers and API keys. After explicit confirmation, the browser may send microphone audio to its own online recognition service. Availability, processing location and retention depend on the browser; offline recognition is not guaranteed. Cancel and type instead to avoid this path.
- Dependency installation needs network access. Offline operation thereafter depends on actual model, OCR, media, and SDK configuration.

## Packages and deletion

Exports separately control conversations, audio, images, video, and call history. Disabling conversations also excludes chat decision transcripts, memory revisions, graphs, and cached persona cores. Persona summaries, world facts, manual input, and other derivatives may still contain personal information. Images may contain conversation text. Filtering is not anonymization: inspect before sharing.

Packages migrate avatar content, do not copy the OS credential store, and are not full database backups. Import uses local preflight and rights confirmation. A manifest declaring no API keys does not prove every text passage has been scanned.

Deleting an avatar removes current records and its asset directory. It does **not** remove previous exports, database backups, copies in other directories, provider-held materials, or service credentials in the OS credential store. Purging an archived timeline creates a backup first, which may retain old content.

Deletion confirmation lists what remains. For complete removal, separately review backups, exports, other data directories and provider retention policies.

## Logs and materials

Image metadata removal is best effort and does not cover every format. Custom OCR commands run as argument lists without a shell; configure only trusted programs.

Diagnostics, chat explanations, usage records, and logs can contain paths, user input, or provider errors. Review private content before sharing. Dedicated keys are isolated, but arbitrary provider error text is not guaranteed to be redacted.

Provider retention, training, deletion, and billing depend on the services you choose. The project supplies no official cloud API and does not automatically revoke material already retained by third parties.

### In-process credential cache

Credentials successfully read from the OS store remain in process memory to avoid repeated authorization prompts on refresh or concurrent requests. No additional file or database copy is written. Updating or deleting a key through the app updates or clears the cache. Restart the app after changing a key directly in the OS store; the cache ends with the process.

## Data handling for the new chat features

With a configured and authorized vision route, sending a chat photo sends pixels and conversation context to the vision provider. The description and reply are saved locally; failures are not retried automatically. This is separate from builder OCR. Files, videos, and manual location cards are not automatically submitted for multimodal interpretation.

The unreleased document-question flow requires a separate Read this file action and confirmation before sending locally extracted text, the question, and current conversation context to the current chat service. Each explicit question makes at most one call, with no automatic retry or provider switch. TXT/MD/CSV are limited to 2 MB, text-layer PDFs to 10 MB and 20 pages, and extracted text to 20,000 characters. There is no OCR; excessive, encrypted, textless, or unreadable input is rejected. Chat stores the question, reply, and file source. Ordinary later chat does not automatically reattach the full document; an existing default summary may be reused.

Voice notes and browser voice calls also use SpeechRecognition, which may use the browser's online service. Recognized text is sent for model replies. The microphone-level interruption detector runs locally and releases its tracks on hangup. Hidden call bubbles are not deleted: transcripts remain local and can enter subsequent model context.

Unreleased segmented calls split each reply of up to 80 characters into at most three TTS requests using the selected voice; totals may change for services charging per request. The server checks duration and the call's estimated CNY allowance, ending at the deadline or when the next request cannot fit. Estimated reservations are neither actual debits nor hard caps on provider bills; failure or interruption does not recall submitted requests. The app does not automatically change models or voices to improve latency, or retry failed requests. This round adds no live paid-service acceptance claim.

Before a voice call, local checks cover voice, connection, consent, credential presence, estimates, and budgets without cloud probes. Each model request first checks whether chat plus up to three speech segments can fit a conservative estimate; reservations then occur per request. This is not a cap on provider bills.

After user confirmation, chat Memory controls save, correct, or deactivate linked memories locally without a model call. Correction/stopping use excludes the original message and same-turn reply from future context; deactivated memories are not retrieved. When a source has been merged into other memories, the dialog explains the impact before confirmation: changing or stopping it also deactivates those merged memories. Preview and official memories cannot be merged together; sleep consolidation skips explicit chat notes and their merged derivatives to preserve source control. Original chats, revisions, and independently saved material remain, and provider requests already sent cannot be recalled. This stops use; it is not deletion or anonymization.

The first-run guide only checks saved routes, consent, enabled state, credential presence, and estimated budgets. It does not return key values, probe cloud services, or call models. Dismissal is saved locally; the guide does not confirm avatar material rights on the user's behalf.

Fixed on 2026-10-05: main chat and history search hide voice_call transcripts while retaining call cards; local transcripts remain available to model context. Disabling call-history export excludes call cards, voice_call messages, sessions/turns, and all reply diagnostics. Legacy synthesized audio cannot distinguish calls from auditions, so all generated/audio files are also omitted. Original recordings and voice-note attachments follow the audio option. This does not delete local data or independently authored persona settings or memories.


### Voice-cloning estimate correction (2026-10-05)

The following estimate validation and pre-call budget checks apply only to voice-cloning capability routes in the unified service hub, including Aliyun connections selected through those routes. Without such a route, the legacy Aliyun connection can still be used; it does not have the same per-call CNY estimate validation or remaining-budget preflight. Prefer the unified service hub for new configurations.

The old 1.5 default did not distinguish currency. Mainland MiniMax official endpoints now default to CNY 9.90 per voice, from the [official pricing page](https://platform.minimax.cn/docs/guides/pricing-paygo). The provider charges cloning at first synthesis; the app records the estimate at successful cloning to account for it early, not as an actual debit. Audition synthesis is separate.

International endpoints, proxies, and other services require an explicit per-call CNY estimate in cost_estimates.voice_clone. Valid custom estimates take precedence; negative, nonfinite, and zero cloud-cloning estimates are rejected. Before upload, the cloning estimate must fit remaining daily/monthly budgets. An unavailable configured cloning route cannot fall back to the legacy connection. This is not an atomic reservation for concurrent requests or a guarantee about actual bills. Other capabilities retain their existing estimation limits; this change addresses voice cloning specifically.
