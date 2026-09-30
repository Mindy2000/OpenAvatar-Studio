# OpenAvatar Studio

[GitHub repository](https://github.com/Mindy2000/OpenAvatar-Studio)

[中文](README.md) · [User guide](docs/GUIDE_EN.md) · [Privacy and data](docs/PRIVACY_EN.md)

OpenAvatar Studio is a locally running avatar creation and management tool. Build persona, memory, voice, visual identity, and editable worlds from your own or explicitly authorized materials, or from original fictional settings. Connect your own model services to interact with avatars.

The current version is **0.1.0-rc.3 release candidate**, intended for local evaluation and development. The source contains no demo avatars, personal databases, API keys, or local model weights. A fresh installation starts with an empty avatar list. Cloud features require your own accounts and may incur costs.

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
- Streaming text chat; transcription, voice cloning, images, and asynchronous video depend on configured services.
- North/Atlas realtime video calls with LiveKit connectivity.
- Visual approval, continuity asset sets, scene profiles, and video keyframe review.
- Avatar package v3 import/export with v1/v2 compatibility and separate conversation, audio, image, video, and call-history controls.
- Chinese/English UI resources, separate avatar language, and world-region settings.

## Data and current limits

The standard launchers bind only to loopback. Normal credential fields use the operating system credential store; publishing source does not require personal runtime data. Avatar packages may still contain sensitive information. Export filtering is not anonymization.

An already selected and authorized cloud OCR connection runs during image upload. Local model connections accept only loopback addresses and reject redirects. Budgets use estimates and are not hard limits on provider bills. Read the [privacy guide](docs/PRIVACY_EN.md) before use.

## Documentation

| Task | Document |
|---|---|
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
