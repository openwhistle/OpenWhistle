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

## 🔍 Overview

OpenWhistle is a self-hosted whistleblower platform that fulfils the mandatory reporting channel
requirements under the **German Hinweisgeberschutzgesetz (HinSchG)** and **EU Directive 2019/1937**.
Any company with 50 or more employees and all public authorities are legally required to provide
an internal reporting channel. OpenWhistle provides a fully open source solution — free of charge,
zero vendor lock-in, and privacy-first by design.

🌐 **Live demo:** [demo.openwhistle.net](https://demo.openwhistle.net)
📖 **Documentation:** [openwhistle.net/docs.html](https://openwhistle.net/docs.html)

---

## ✨ Features

- **Full anonymity** — No IP addresses logged at any layer. An employee submitting from the office
  network leaves no trace.
- **Two-factor whistleblower access** — Case number + secret UUID4 PIN with brute-force protection.
  No accounts, no email — nothing to tie the report back to a person.
- **Multi-step submission wizard** — Guided 5–6 step form with back/next navigation and Redis-backed
  session state. Anonymous or confidential mode selectable at step 1.
- **Anonymous / confidential mode** — Anonymous leaves no personal data. Confidential encrypts
  name, contact info, and optional secure email with Fernet; only the assigned admin can decrypt.
- **Multi-location / branch selection** — Optional location selector shown when the operator has
  configured active branches or offices; full admin management UI included.
- **Bidirectional communication** — Required by HinSchG §17. The whistleblower can reply to admin
  messages using only their case number and PIN.
- **HinSchG SLA tracking** — 7-day acknowledgement and 3-month feedback deadlines with days
  remaining shown in both the admin dashboard and the whistleblower status page.
- **Role-based access control** — `ADMIN` and `CASE_MANAGER` roles. Case managers can process
  their assigned reports; only admins manage users, categories, and deletions.
- **Case assignment** — Assign reports to any active staff member; "My Cases" dashboard filter
  for case managers.
- **Status workflow** — `received → in_review → pending_feedback → closed`; only valid
  transitions allowed server-side.
- **4-eyes deletion** — Hard deletion requires two different admins (request + confirm);
  same-admin confirm returns HTTP 409. GDPR Art. 17 compliant.
- **Immutable audit log** — Every admin action recorded with timestamp and username; CSV export;
  required by HinSchG §12 Abs. 3.
- **Internal notes** — Admin-only notes on cases; never visible to the whistleblower.
- **Case linking** — Link related cases with bidirectional normalization constraint.
- **Custom categories** — DB-driven report categories; full management UI at `/admin/categories`.
- **PDF export** — Full case export including SLA compliance section (HinSchG §17).
- **Dashboard statistics** — SLA compliance rate, status distribution, category breakdown.
- **Mandatory MFA** — TOTP (compatible with any authenticator app) required for every admin account.
  No exceptions, no bypass.
- **OIDC / SSO support** — Optional single sign-on via any OpenID Connect provider (Keycloak,
  Authentik, Azure AD, Google, …).
- **File attachments** — Whistleblowers can attach evidence files (PDF, images, Word, Excel, CSV,
  TXT — up to 10 MB each, 5 per report).
- **Internationalisation** — English, German, and French UI; language picker in the nav bar;
  all 388+ translation keys present in every locale.
- **WCAG 2.1 AA** — Skip-to-content link, ARIA labels, live regions, visible focus indicators,
  and keyboard-accessible language picker.
- **Setup wizard** — Web-based first-run wizard creates the initial admin account with TOTP setup.
  No manual database steps.
- **IP leakage detection** — The admin dashboard warns when upstream proxies forward IP headers.
- **Hard deletion** — Reports can be permanently deleted including all messages, attachments, and
  Redis session data. DSGVO-compliant.
- **DSGVO compliant** — All resources are self-hosted. No external CDN calls, no tracking.
- **Multi-registry Docker** — Published to GHCR, Docker Hub, and Quay.io on every release.
- **Health-check v2** — `/health` reports database and Redis status; suitable for Kubernetes
  liveness and readiness probes.
- **Structured JSON logging** — `LOG_FORMAT=json` produces structured log output for aggregation
  pipelines; `LOG_FORMAT=text` for human-readable development output.
- **Slack / Teams webhooks** — `NOTIFY_WEBHOOK_TYPE` selects Block Kit (Slack) or Adaptive Card
  (Teams) payload formats so no custom integration work is needed.
- **SLA reminders** — Background scheduler automatically sends reminders when the 7-day and
  3-month HinSchG deadlines approach; Redis dedup keys prevent duplicate notifications.
- **S3-compatible storage** — Optional `STORAGE_BACKEND=s3` routes new attachments to any
  S3-compatible bucket (AWS, MinIO, Hetzner Object Storage) instead of PostgreSQL BLOBs.
- **LDAP / Active Directory login** — Admin accounts can authenticate via corporate LDAP;
  first login auto-provisions the user; TOTP enrollment still required.
- **Helm chart** — Official `charts/openwhistle/` Helm chart for Kubernetes deployments.
- **Ansible role** — Official `ansible/roles/openwhistle/` Ansible role for bare-metal / VM
  deployments with Docker CE, systemd unit, and optional Certbot TLS.

---

## 🎭 Live Demo

A live demo is available at **[demo.openwhistle.net](https://demo.openwhistle.net)**

| Role | Username | Password | TOTP Code |
|---|---|---|---|
| Admin | `demo` | `demo` | `000000` |

Demo case numbers and PINs are shown after logging in to the demo admin account.
The demo resets automatically every hour.

---

## 🚀 Quick Start

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

## 📦 Container Images

Pre-built multi-arch images (linux/amd64, linux/arm64) are published to three registries:

| Registry | Image |
|---|---|
| GitHub Container Registry | `ghcr.io/openwhistle/openwhistle` |
| Docker Hub | `kermit1337/openwhistle` |
| Quay.io | `quay.io/jp1337/openwhistle` |

All GHCR images are signed with Cosign (keyless, Sigstore).

---

## ⚖️ Legal Reference

OpenWhistle is designed to comply with:

- [Hinweisgeberschutzgesetz (HinSchG)](https://www.gesetze-im-internet.de/hinschg/)
- [EU Directive 2019/1937](https://eur-lex.europa.eu/legal-content/en/TXT/?uri=CELEX%3A32019L1937)
- [DSGVO / GDPR](https://gdpr-info.eu/)

> **Disclaimer:** OpenWhistle is a technical tool. Operators are responsible for ensuring
> their deployment meets all applicable legal requirements in their jurisdiction.

---

## 🤝 Contributing

Contributions are welcome. Please open an issue before submitting a pull request.

---

## 📜 License

OpenWhistle is released under the [GNU General Public License v3.0](LICENSE).

---

## 💛 Support

OpenWhistle is developed in free time. If you find it useful, consider supporting the project.

[![GitHub Sponsors](https://img.shields.io/github/sponsors/jp1337?label=Sponsor)](https://github.com/sponsors/jp1337)
