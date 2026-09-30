# Security policy

[中文](SECURITY.md)

Maintenance currently targets release candidate 0.1.0; no long-term support series is promised. This is a personal local application, not a public multi-user service. See [Privacy](docs/PRIVACY_EN.md) for known boundaries and limitations.

## Private reporting

GitHub private vulnerability reporting is enabled for this repository. Use the [private reporting form](https://github.com/Mindy2000/OpenAvatar-Studio/security/advisories/new) or select **Report a vulnerability** under Security. Reports are private to the reporting/authorized maintenance participants, not visible as ordinary public issues or comments.

If the entry is unavailable, do not post exploit details, real keys, databases, or avatar packages publicly. You may open a non-sensitive issue asking for a private reporting channel.

Include version, platform, impact, reproduction with fictional data, and expected behavior. Ordinary feature requests and non-security bugs may use public issues.

See [GitHub's private reporting guide](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-privately).

## Handling materials

Do not attach real chats, photos, recordings, complete logs, credential-store exports, or credential-bearing URLs. Dedicated key fields use the OS credential store; arbitrary metadata/user content is not universally redacted. Revoke or rotate exposed credentials with their provider.

Changes to local-address checks, cloud OCR, export/deletion boundaries, or billable task flows must update both privacy guides and include targeted validation.
