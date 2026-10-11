# OpenAvatar Studio

[GitHub repository](https://github.com/Mindy2000/OpenAvatar-Studio)

[中文](README.md) · [Quick start](docs/QUICKSTART_EN.md) · [User guide](docs/GUIDE_EN.md) · [Privacy and data](docs/PRIVACY_EN.md)

OpenAvatar Studio is a locally running avatar creation and management tool. Build persona, memory, voice, visual identity, and editable worlds from your own or explicitly authorized materials, or from original fictional settings. Connect your own model services to interact with avatars.

The current version is **0.1.0-rc.5 release candidate**, intended for local evaluation and development. The source contains no demo avatars, personal databases, API keys, or local model weights. A fresh installation starts with an empty avatar list. Cloud features require your own accounts and may incur costs.

The source also includes five unreleased upgrades: first-run setup guidance, voice-call duration and estimated-budget controls, segmented speech, explicit document questions, and per-message memory controls. See [Unreleased changes](CHANGELOG.md). These new workflows have not completed live paid-service acceptance.

Source fixes dated 2026-10-12 additionally cover import review and memory provenance, packages and database restore, background jobs, proactive contact, call exit, and cost reservations. Databases migrate to schema v9 with a pre-upgrade backup; current source rejects databases above its supported version. Older binaries do not retroactively gain this protection. Checks use synthetic materials, temporary databases, and provider substitutes. They do not establish new published binaries or live cloud/hardware acceptance.

## Desktop downloads

Download and fully extract the ZIP for your device. Python is included; no separate Python installation is needed. These are unsigned preview builds.

[Download released builds](https://github.com/Mindy2000/OpenAvatar-Studio/releases) — Windows x64, Mac Apple silicon, Mac Intel and Linux x64. Select the latest published release, then the ZIP for your device. A source checkout can be newer than the available binaries.

## Run from source

Use Python 3.11 or newer. Download and extract the source, then open the project directory:

- macOS: double-click `start.command`.
- Windows: double-click `start.bat`.
- Linux: run `chmod +x start.sh`, then `./start.sh`.

The scripts create `.venv`, install dependencies, and start a local service at `http://127.0.0.1:8767` by default. Initial installation needs internet access. Do not open `openavatar/static/index.html` directly.

The desktop launcher selects a free local port and opens a browser. Desktop and source installations use different data locations; see the [user guide](docs/GUIDE_EN.md).

## Core capabilities

- Authorized real-material and original fictional creation paths, with guided questions and file import.
- Editable persona, evidence-backed memories, world facts/runtime, and conversation editing, archiving, and restoration.
- A unified service hub for capability-specific providers, models, consent, fallback routes, and estimated budgets.
- A three-step setup guide checks local configuration and opens existing settings and creation screens without calling a model. Skip it and reopen it later.
- Streaming text chat and a WeChat-style composer: the + panel groups images/video, camera, calls, files, manual locations, and favorites. Hold to record a voice note, release to send, or slide up to cancel.
- A dedicated voice-call window with interruption, mute, minimize, and hangup; calls end at configured time or estimated-budget limits, and replies play in sentence segments. Chat retains a call card rather than per-utterance bubbles.
- Mirrored selfies and chat image understanding; explicitly read and ask about TXT, MD, CSV, and text-layer PDFs. Uploads do not trigger analysis, and videos are not interpreted. Transcription, cloning, images, and asynchronous video depend on configured services.
- Remember, correct, or stop using a memory beside a text or transcribed voice message. These controls run locally and retain chat history.
- North/Atlas realtime video calls with LiveKit connectivity.
- Visual approval, continuity asset sets, scene profiles, and video keyframe review.
- Avatar package v3 import/export with v1/v2 compatibility and separate conversation, audio, image, video, and call-history controls.
- Complete Chinese/English interface switching across settings, guided creation, dialogs, diagnostics, build status, and the desktop launcher, with separate avatar language and world-region settings.

## Data and current limits

The standard launchers bind only to loopback. Normal credential fields use the operating system credential store; publishing source does not require personal runtime data. Avatar packages may still contain sensitive information. Export filtering is not anonymization.

An already selected and authorized cloud OCR connection runs during image upload. Local model connections accept only loopback addresses and reject redirects. Budgets use estimates and are not hard limits on provider bills. Read the [privacy guide](docs/PRIVACY_EN.md) before use.

## Documentation

| Task | Document |
|---|---|
| Start from an empty list, configure services, create an avatar, and send a first message | [Quick start](docs/QUICKSTART_EN.md) |
| Review release changes and boundaries | [Changelog](CHANGELOG.md) |
| Install, create avatars, configure services, troubleshoot | [User guide](docs/GUIDE_EN.md) |
| Understand storage, transfers, and deletion | [Privacy](docs/PRIVACY_EN.md) |
| Understand the code and runtime | [Architecture](docs/ARCHITECTURE_EN.md) |
| Work with avatar packages and asset states | [Package protocol](docs/OPENAVATAR_PACKAGE_EN.md) |
| Develop and validate | [Contributing](CONTRIBUTING_EN.md) |
| Build and release desktop packages | [Release guide](packaging/README_EN.md), [checklist](packaging/RELEASE_CHECKLIST_EN.md) |
| Decide what belongs in Git | [Repository layout](docs/REPOSITORY_LAYOUT_EN.md) |
| Report security issues | [Security policy](SECURITY_EN.md) |

## License

[Apache License 2.0](LICENSE). Third-party models, dependencies, and user materials retain their own licenses. Use only your own, explicitly authorized, or original fictional materials. Do not use the project for impersonation, fraud, harassment, or unauthorized identity cloning.
