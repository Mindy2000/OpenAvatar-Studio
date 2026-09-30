# Release checklist

[中文](RELEASE_CHECKLIST.md) · [Build and release guide](README_EN.md)

## Before publishing source

- [ ] Inspect the actual file list and history for demos, personal data, keys, databases, avatar packages, and old builds.
- [ ] Keep personal avatars, exports, backups, and credentials local; ignore custom data directories too.
- [ ] Use a reviewed clean public history, not the local history containing old demos.
- [ ] Align both languages, versions, UI entry points, privacy, package protocol, and templates with implementation.
- [ ] Fix or accurately disclose known limits such as local-address validation; a documentation change is not a code fix.
- [ ] Configure and verify GitHub private reporting; do not invent contact addresses or claim inactive reporting links work.
- [ ] Complete the contributing guide's tests, lint, browser/WebSocket checks, and dependency audit.
- [ ] Confirm Apache-2.0 and third-party/material rights boundaries.

## Before publishing desktop packages

- [ ] Rebuild clean sources on each target OS/architecture; do not reuse old packages.
- [ ] Check archives for personal data, keys, private absolute paths, and unnecessary outputs.
- [ ] Include project and third-party licenses/notices; verify checksums.
- [ ] Validate native startup/shutdown, data location, credential services, and certificates.
- [ ] Create/import/export/inspect avatars and exercise required media flows from an empty database.
- [ ] Do not send real materials to unauthorized providers; use test accounts for live cloud checks.
- [ ] State OS/architecture, unsigned status, optional dependencies, validation scope, and known limits.
- [ ] Push `v*` tags only after release approval; tag workflows automatically publish Releases.
