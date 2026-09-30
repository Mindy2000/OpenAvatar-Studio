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
- Dependency installation needs network access. Offline operation thereafter depends on actual model, OCR, media, and SDK configuration.

## Packages and deletion

Exports separately control conversations, audio, images, video, and call history. Disabling conversations also excludes chat decision transcripts, memory revisions, graphs, and cached persona cores. Persona summaries, world facts, manual input, and other derivatives may still contain personal information. Images may contain conversation text. Filtering is not anonymization: inspect before sharing.

Packages migrate avatar content, do not copy the OS credential store, and are not full database backups. Import uses local preflight and rights confirmation. A manifest declaring no API keys does not prove every text passage has been scanned.

Deleting an avatar removes current records and its asset directory. It does **not** remove previous exports, database backups, copies in other directories, provider-held materials, or service credentials in the OS credential store. Purging an archived timeline creates a backup first, which may retain old content.

The UI's “permanently delete all local materials” prompt should be read with these boundaries; it does not mean all copies disappear. Review backups, exports, and provider retention when complete deletion is needed.

## Logs and materials

Image metadata removal is best effort and does not cover every format. Custom OCR commands run as argument lists without a shell; configure only trusted programs.

Diagnostics, chat explanations, usage records, and logs can contain paths, user input, or provider errors. Review private content before sharing. Dedicated keys are isolated, but arbitrary provider error text is not guaranteed to be redacted.

Provider retention, training, deletion, and billing depend on the services you choose. The project supplies no official cloud API and does not automatically revoke material already retained by third parties.
