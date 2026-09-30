# Repository and local directories

[中文](REPOSITORY_LAYOUT.md)

## Public sources

| Path | Purpose |
|---|---|
| `openavatar/` | App, routes, services, UI, language resources, desktop launcher |
| `tests/` | Isolated automated tests without personal materials |
| `scripts/` | UI checks, builds, packaging, optional legacy configuration migration |
| `docs/` | Paired user, architecture, privacy, package, layout documents and blank templates |
| `packaging/` | Paired maintainer build guides and release checklists |
| `.github/workflows/` | Quality and desktop build/release workflows |
| Root README, LICENSE, SECURITY, CONTRIBUTING | Entry points, license, reporting, contributions |
| Requirements, `pytest.ini`, launchers, `.gitignore` | Installation, tests, runtime, publication boundaries |
| `data/avatars/.gitkeep`, `data/exports/.gitkeep` | Empty directory placeholders, no personal or demo data |

## Local only

- Databases, materials, exports, backups under `data/`, and desktop OS application-data directories.
- `.env*`, OS credentials, actual environment-variable values.
- `.venv/`, caches, `.DS_Store`, `.playwright-cli/`.
- `build/`, `dist/`, `release/`, `*.spec`: regenerable artifacts.
- `output/`: screenshots, logs, check results.
- `_local/`: audit archives, retained private material, maintenance utilities.

`.gitignore` affects untracked files; it does not erase committed content or history. Inspect staged files and history before publication rather than uploading the whole folder.

Regenerable builds/caches may be removed. Databases, backups, exports, credentials, and maintenance scripts are not caches. Old packages can retain removed features, so rebuild for each release.
