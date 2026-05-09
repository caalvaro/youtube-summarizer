# Security policy

## Supported versions

| Version | Supported |
|---|---|
| 0.1.x | ✓ |

## Reporting a vulnerability

**Do not open a public GitHub issue for security vulnerabilities.**

Please report security issues by emailing **alvarocarvalho.a@gmail.com** with the subject
line `[SECURITY] youtube-summarizer — <brief description>`. Include:

- A description of the vulnerability and its potential impact.
- Steps to reproduce or a minimal proof-of-concept.
- Any suggested mitigations if you have them.

You will receive an acknowledgement within 48 hours. We aim to release a patch within 14 days
of a confirmed vulnerability, depending on complexity.

We will credit reporters in the release notes unless you prefer to remain anonymous.

## Scope

This project handles:

- **Anthropic API keys** — stored only in `.env` (excluded from version control via
  `.gitignore`). Never log or print the key value.
- **YouTube URLs** — passed directly to `yt-dlp`; no authentication credentials are stored.
- **Local file system** — output is written to the `output/` directory only.

This project does **not** handle user authentication, payment data, or personal information
beyond what YouTube's public API exposes.
