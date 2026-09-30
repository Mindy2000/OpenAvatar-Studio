# Contributing

[中文](CONTRIBUTING.md) · [Architecture](docs/ARCHITECTURE_EN.md)

## Development

Use Python 3.11+. From the project directory:

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-dev.txt ruff pip-audit
.venv/bin/python -m playwright install chromium
.venv/bin/python -m pytest -q
.venv/bin/ruff check openavatar tests scripts --select E9,F63,F7,F82
.venv/bin/python scripts/run_ui_checks.py
.venv/bin/pip-audit -r requirements.txt -r requirements-dev.txt -r requirements-packaging.txt
```

On Windows replace `.venv/bin/` with `.venv\Scripts\`; use `python` to create the environment if appropriate. UI checks create their own temporary data/server and remove test avatars afterward. They do not need your personal database. Pytest also isolates its data and uses a fresh in-memory credential store for each test, without reading or changing the OS keyring. Test credentials are discarded afterward.

For manual development, run `.venv/bin/python -m uvicorn openavatar.main:app --host 127.0.0.1 --port 8767 --reload`. Set a separate `OPENAVATAR_DATA_DIR` first when you do not want to use personal data.

## Change requirements

- Never commit personal materials or keys. Tests use synthetic data, do not read real OS credentials, and do not call billable services.
- Document transferred data, costs, consent, fallback, and deletion for new integrations.
- Do not treat candidates as approved/canonical or export filters as anonymization.
- Update Chinese and English together. Keep installation/operation in the user guide and building/releasing in the release guide.
- `services/templates.py` is the current template source. Keep `docs/templates/avatar.md` and `character.yaml` identical to the API contents rather than adding independent fields.
- Check dynamic/star imports and packaging references before removing modules that appear unused.

Quality CI runs tests, browser checks, and dependency audits for PRs and main/master pushes. Desktop building is separate; a pass on one platform is not verification of every platform.

PRs should explain the problem, resulting behavior, validation, and data impact. Report vulnerabilities via [Security](SECURITY_EN.md). See [repository layout](docs/REPOSITORY_LAYOUT_EN.md) for publication boundaries.
