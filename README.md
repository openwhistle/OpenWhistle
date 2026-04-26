<p align="center">
  <img src="https://raw.githubusercontent.com/openwhistle/OpenWhistle/main/app/static/favicon.svg" alt="OpenWhistle Logo" width="72">
</p>

# OpenWhistle

[![CI](https://img.shields.io/github/actions/workflow/status/openwhistle/OpenWhistle/ci.yml?label=CI&logo=github)](https://github.com/openwhistle/OpenWhistle/actions/workflows/ci.yml)
[![Docker Build](https://img.shields.io/github/actions/workflow/status/openwhistle/OpenWhistle/docker-publish.yml?label=Docker&logo=docker)](https://github.com/openwhistle/OpenWhistle/actions/workflows/docker-publish.yml)
[![Coverage](https://codecov.io/gh/openwhistle/OpenWhistle/graph/badge.svg)](https://codecov.io/gh/openwhistle/OpenWhistle)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue?logo=gnu)](LICENSE)
[![Version](https://img.shields.io/github/v/release/openwhistle/OpenWhistle?logo=github)](https://github.com/openwhistle/OpenWhistle/releases)
[![Python](https://img.shields.io/badge/python-3.14-blue?logo=python&logoColor=white)](https://python.org)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.136-009688?logo=fastapi&logoColor=white)](https://fastapi.tiangolo.com)
[![PostgreSQL](https://img.shields.io/badge/postgresql-18-336791?logo=postgresql&logoColor=white)](https://postgresql.org)
[![Redis](https://img.shields.io/badge/redis-8-DC382D?logo=redis&logoColor=white)](https://redis.io)
[![Docker Pulls](https://img.shields.io/docker/pulls/kermit1337/openwhistle?logo=docker)](https://hub.docker.com/r/kermit1337/openwhistle)
[![CodeQL](https://img.shields.io/github/actions/workflow/status/openwhistle/OpenWhistle/codeql.yml?label=CodeQL&logo=github)](https://github.com/openwhistle/OpenWhistle/security/code-scanning)
[![GitHub Sponsors](https://img.shields.io/badge/sponsor-GitHub-ea4aaa?logo=github-sponsors&logoColor=white)](https://github.com/sponsors/jp1337)

> *"Speaking up takes courage. Staying silent shouldn't be the safer option."*

**A secure, self-hosted internal reporting channel — because every employee deserves protection.**

> [!WARNING]
> OpenWhistle is currently in early development (alpha). Do not use in production.

---

## Overview

OpenWhistle is a self-hosted whistleblower platform that fulfils the mandatory reporting channel
requirements under the **German Hinweisgeberschutzgesetz (HinSchG)** and **EU Directive 2019/1937**.
Any company with 50 or more employees and all public authorities are legally required to provide
an internal reporting channel. OpenWhistle provides a fully open source solution — free of charge,
zero vendor lock-in, and privacy-first by design.

🌐 **Live demo:** [demo.openwhistle.net](https://demo.openwhistle.net)
📖 **Documentation:** [openwhistle.net/docs.html](https://openwhistle.net/docs.html)

---

## Features

- **Full anonymity** — No IP addresses logged at any layer. An employee submitting from the office
  network leaves no trace.
- **Two-factor whistleblower access** — Case number + secret UUID4 PIN with brute-force protection.
  No accounts, no email — nothing to tie the report back to a person.
- **Bidirectional communication** — Required by HinSchG §17. The whistleblower can reply to admin
  messages using only their case number and PIN.
- **HinSchG SLA tracking** — Automatic 7-day acknowledgement deadline and 3-month feedback deadline
  tracking, visible in the admin dashboard.
- **Mandatory MFA** — TOTP (compatible with any authenticator app) required for every admin account.
  No exceptions, no bypass.
- **OIDC / SSO support** — Optional single sign-on via any OpenID Connect provider (Keycloak,
  Authentik, Azure AD, Google, …).
- **File attachments** — Whistleblowers can attach evidence files (PDF, images, Word, Excel, CSV,
  TXT — up to 10 MB each, 5 per report).
- **Setup wizard** — Web-based first-run wizard creates the initial admin account with TOTP setup.
  No manual database steps.
- **IP leakage detection** — The admin dashboard warns when upstream proxies forward IP headers.
- **Hard deletion** — Reports can be permanently deleted including all messages, attachments, and
  Redis session data. DSGVO-compliant.
- **DSGVO compliant** — All resources are self-hosted. No external CDN calls, no tracking.
- **Multi-registry Docker** — Published to GHCR, Docker Hub, and Quay.io on every release.

---

## Live Demo

A live demo is available at **[demo.openwhistle.net](https://demo.openwhistle.net)**

| Role | Username | Password | TOTP Code |
|---|---|---|---|
| Admin | `demo` | `demo` | `000000` |

Demo case numbers and PINs are shown after logging in to the demo admin account.
The demo resets automatically every hour.

---

## Quick Start

```bash
git clone https://github.com/openwhistle/OpenWhistle.git
cd OpenWhistle
cp .env.example .env        # Set a strong SECRET_KEY
docker compose up -d
# Open http://localhost:4009/setup to create the first admin account
```

For full installation instructions, environment variable reference, reverse proxy configuration,
and administration guide, see **[openwhistle.net/docs.html](https://openwhistle.net/docs.html)**.

---

## Container Images

Pre-built multi-arch images (linux/amd64, linux/arm64) are published to three registries:

| Registry | Image |
|---|---|
| GitHub Container Registry | `ghcr.io/openwhistle/openwhistle` |
| Docker Hub | `kermit1337/openwhistle` |
| Quay.io | `quay.io/jp1337/openwhistle` |

All GHCR images are signed with Cosign (keyless, Sigstore).

---

## Legal Reference

OpenWhistle is designed to comply with:

- [Hinweisgeberschutzgesetz (HinSchG)](https://www.gesetze-im-internet.de/hinschg/)
- [EU Directive 2019/1937](https://eur-lex.europa.eu/legal-content/en/TXT/?uri=CELEX%3A32019L1937)
- [DSGVO / GDPR](https://gdpr-info.eu/)

> **Disclaimer:** OpenWhistle is a technical tool. Operators are responsible for ensuring
> their deployment meets all applicable legal requirements in their jurisdiction.

---

## Contributing

Contributions are welcome. Please open an issue before submitting a pull request.

---

## License

OpenWhistle is released under the [GNU General Public License v3.0](LICENSE).

---

## Support

OpenWhistle is developed in free time. If you find it useful, consider supporting the project.

[![GitHub Sponsors](https://img.shields.io/github/sponsors/jp1337?label=Sponsor)](https://github.com/sponsors/jp1337)
