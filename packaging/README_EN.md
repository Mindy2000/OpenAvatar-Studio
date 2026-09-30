# Desktop build and release guide

[中文](README.md) · [Checklist](RELEASE_CHECKLIST_EN.md) · [User installation](../docs/GUIDE_EN.md)

This document is for maintainers. Installation, data locations, and operation are centralized in the user guide. The PyInstaller launcher starts local FastAPI and opens the system browser; there is no auto-update or app-store integration.

## Local builds

Use Python 3.11+ and build on the target operating system/processor architecture. A macOS artifact is not a Windows/Linux package.

```bash
python -m pip install -r requirements-packaging.txt
python scripts/build_desktop.py --dry-run
python scripts/build_desktop.py
python scripts/collect_release_licenses.py
python scripts/package_release.py --version v0.1.0
```

`build_desktop.py` uses `openavatar/desktop.py`, bundling static files, language resources, templates, the project LICENSE, and credential-store components. Artifacts go to `dist/`, intermediates to `build/`; `.spec` files are regenerable. `package_release.py` writes ZIP/SHA-256 files under `release/`. `--platform macos|windows|linux` selects an existing artifact type; it does not cross-compile.

Desktop data belongs in the OS application-data directory or `OPENAVATAR_DATA_DIR`, never inside the release bundle. Packages contain no personal databases, demo avatars, keys, local LLM weights, or Piper voice models. Verify FFmpeg, optional OCR engines, and Linux credential-service availability on the destination system.

## GitHub Actions

- `quality.yml`: compilation, critical lint, automated tests, browser/WebSocket checks, and dependency audit for PRs and main/master pushes.
- `build-desktop.yml`: manual runs and `v*` tags build on native macOS, Windows, and Linux runners and upload Actions artifacts.
- Manual runs only produce artifacts for review. Pushing a `v*` tag additionally creates/updates a **draft Release** and uploads archives/checksums. Rerunning a tag replaces matching files.

Tag pushes create release drafts: finish the [checklist](RELEASE_CHECKLIST_EN.md) and approve the release first. A configured matrix does not prove native-platform acceptance.

## Clean release sources

Personal data, credential stores, virtual environments, old specs/builds, and local audit reports are not source inputs. Do not archive the entire development folder. Check Git history before the first release: deleting a working-tree file does not remove old content. Keep histories containing old demos/private material local and use a reviewed clean public history.

Rebuild from clean sources instead of reusing old packages. Inspect archive contents, processor architecture, project LICENSE, bundled third-party license/notice files, and SHA-256. The project license alone does not replace third-party notices.

## Platform acceptance

Launch on each target platform and verify pages, data location, credential save/delete, import/export, shutdown, certificates, and OS credential services. Use test accounts for network features; mock tests do not establish real provider availability.

Packages currently lack formal signing. Release notes should state OS/architecture, signing status, external dependencies, and actual validation scope. Do not promise zero-configuration operation on every system. Source publication and a production desktop release have separate acceptance requirements.

The build runs `scripts/check_desktop_bundle.py` against the frozen application with disposable data, checking the homepage, empty avatar list, templates, avatar creation, export, and WebSocket. Linux uses a virtual display for the desktop window. These checks do not validate paid cloud services, code signing, or compatibility with every device.

macOS builds are separate for Apple silicon (`macos-latest` / arm64) and Intel (`macos-15-intel` / x64), with native build and startup checks. ZIPs, checksums, and Actions artifact names include architecture to prevent collisions. Intel is checked on macOS 15; this does not establish compatibility with every older macOS release.

Release archives include collected third-party notices, project LICENSE and installation instructions. Run `python scripts/collect_release_licenses.py` before packaging. macOS uses ditto and Linux preserves symbolic links; CI extracts the final ZIP and repeats the application startup checks. Tag-triggered release creation now produces a draft for final review, not an immediately public release.
