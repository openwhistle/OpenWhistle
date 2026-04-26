<p align="center">
  <img src="https://raw.githubusercontent.com/openwhistle/OpenWhistle/main/app/static/favicon.svg" alt="OpenWhistle Logo" width="80" height="80">
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
requirements under:

- **German law:** Hinweisgeberschutzgesetz (HinSchG), in force since 2 July 2023
- **EU directive:** Directive (EU) 2019/1937 of the European Parliament

Any company with 50 or more employees and all public authorities are legally required to provide
an internal reporting channel. OpenWhistle provides a fully open source solution — free of charge,
zero vendor lock-in, and privacy-first by design.

🌐 **Live demo:** [demo.openwhistle.net](https://demo.openwhistle.net)
📖 **Documentation:** [openwhistle.net](https://openwhistle.net)

---

## ✨ Features

- **Full anonymity** — No IP addresses logged, not by the application and not by nginx. An employee
  submitting from the office network leaves no trace.
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
- **IP leakage detection** — The admin dashboard warns when upstream proxies forward IP headers,
  helping operators catch misconfigured anonymity setups before they become a problem.
- **Hard deletion** — Reports can be permanently deleted including all messages, attachments, and
  Redis session data. DSGVO-compliant.
- **DSGVO compliant** — All resources are self-hosted. No external CDN calls, no tracking, no
  third-party services.
- **Multi-registry Docker** — Published to GHCR, Docker Hub, and Quay.io on every release.

---

## 🎭 Live Demo

A live demo is available at **[demo.openwhistle.net](https://demo.openwhistle.net)**

| Role | Username | Password | TOTP Code |
|---|---|---|---|
| Admin | `demo` | `demo` | `000000` |

Demo case numbers and PINs are shown after logging in to the demo admin account.
The demo resets automatically every hour.

---

## 🛠️ Tech Stack

| Component | Technology |
|---|---|
| Language | Python 3.14 |
| Framework | FastAPI 0.136 |
| Database | PostgreSQL 18 (via SQLAlchemy 2.0 async) |
| Cache / Sessions | Redis 8 |
| Auth | pyotp (TOTP), authlib 1.7+ (OIDC) |
| Templates | Jinja2 (server-side rendering) |
| Reverse Proxy | nginx (IP logging disabled) |

---

## 📦 Container Images

Pre-built multi-arch images (linux/amd64, linux/arm64) are published to three registries:

| Registry | Image |
|---|---|
| GitHub Container Registry | `ghcr.io/openwhistle/openwhistle` |
| Docker Hub | `kermit1337/openwhistle` |
| Quay.io | `quay.io/openwhistle/openwhistle` |

```bash
# GitHub Container Registry (primary)
docker pull ghcr.io/openwhistle/openwhistle:latest

# Docker Hub
docker pull kermit1337/openwhistle:latest

# Quay.io
docker pull quay.io/openwhistle/openwhistle:latest
```

| Tag | Updated when | Use for |
|---|---|---|
| `latest` | Release tag (`v*.*.*`) | Production |
| `1.2.3` / `1.2` / `1` | Release tag | Pinned version |
| `edge` | Every push to `main` | Testing latest dev build |
| `sha-abc1234` | Every push | Exact reproducible build |

All GHCR images are signed with Cosign (keyless, Sigstore).

---

## 🚀 Quick Start

### Prerequisites

- Docker and Docker Compose
- A PostgreSQL 18 database
- A Redis 8 instance

### Docker Compose (recommended)

```bash
# 1. Clone the repository
git clone https://github.com/openwhistle/OpenWhistle.git
cd OpenWhistle

# 2. Create your environment file
cp .env.example .env
# Edit .env and set a strong SECRET_KEY

# 3. Start the stack
docker compose up -d

# 4. Open http://localhost:4009/setup in your browser
#    to create the first admin account
```

---

## 🔒 Behind a Reverse Proxy

**Critical for anonymity:** Disable access logging and strip IP headers.

### nginx

```nginx
server {
    # Disable access logging — required for anonymity
    access_log off;
    log_not_found off;

    # Strip ALL IP-forwarding headers
    proxy_set_header X-Forwarded-For     "";
    proxy_set_header X-Real-IP           "";
    proxy_set_header Forwarded           "";
    proxy_set_header CF-Connecting-IP    "";

    location / {
        proxy_pass http://localhost:4009/;
    }
}
```

### Cloudflare

1. Enable "Remove visitor IPs from logs" in the Cloudflare dashboard
2. Do **not** use "Restore visitor IP" — it adds `CF-Connecting-IP`
3. OpenWhistle will warn you in the admin dashboard if IP headers are detected

### Traefik

```yaml
middlewares:
  strip-ip-headers:
    headers:
      customRequestHeaders:
        X-Forwarded-For: ""
        X-Real-IP: ""
        True-Client-IP: ""
```

---

## ⚙️ Environment Variables

| Variable | Required | Default | Description |
|---|---|---|---|
| `APP_NAME` | No | `OpenWhistle` | Display name used in the application UI |
| `SECRET_KEY` | Yes | — | Long random string for JWT signing |
| `DATABASE_URL` | Yes | — | `postgresql+asyncpg://user:pass@host:5432/db` |
| `REDIS_URL` | Yes | — | `redis://host:6379/0` |
| `DEMO_MODE` | No | `false` | Enable demo mode (seeds test data) |
| `OIDC_ENABLED` | No | `false` | Enable OIDC login |
| `OIDC_CLIENT_ID` | No | — | OIDC client ID |
| `OIDC_CLIENT_SECRET` | No | — | OIDC client secret |
| `OIDC_SERVER_METADATA_URL` | No | — | OIDC provider discovery URL |
| `OIDC_REDIRECT_URI` | No | — | OAuth 2.0 callback URL (e.g. `https://yourdomain.com/admin/oidc/callback`) |
| `BRAND_PRIMARY_COLOR` | No | `#0f4c81` | Primary brand colour (hex) — used for buttons, accents, links |
| `BRAND_SECONDARY_COLOR` | No | `#b07230` | Secondary/accent colour (hex) — used for highlights |
| `BRAND_LOGO_URL` | No | — | URL to a company logo (shown in navbar instead of default icon) |
| `APP_PUBLIC_URL` | No | `http://localhost` | Public base URL — used to build dashboard links in notifications |
| `NOTIFY_EMAIL_ENABLED` | No | `false` | Send an email when a new report is submitted |
| `NOTIFY_EMAIL_TO` | No | — | Comma-separated recipient addresses (e.g. `admin@example.com`) |
| `NOTIFY_EMAIL_FROM` | No | `openwhistle@localhost` | Sender address for notification emails |
| `NOTIFY_SMTP_HOST` | No | `localhost` | SMTP server hostname |
| `NOTIFY_SMTP_PORT` | No | `587` | SMTP server port (587 = STARTTLS, 465 = SMTPS) |
| `NOTIFY_SMTP_USER` | No | — | SMTP authentication username (optional) |
| `NOTIFY_SMTP_PASSWORD` | No | — | SMTP authentication password (optional) |
| `NOTIFY_SMTP_TLS` | No | `true` | Use STARTTLS (`true`) — set to `false` when using port 465 SMTPS |
| `NOTIFY_SMTP_SSL` | No | `false` | Use SMTPS direct TLS (port 465) |
| `NOTIFY_WEBHOOK_ENABLED` | No | `false` | POST a JSON event to a webhook URL when a report is submitted |
| `NOTIFY_WEBHOOK_URL` | No | — | Target URL for webhook POST requests |
| `NOTIFY_WEBHOOK_SECRET` | No | — | HMAC-SHA256 signing secret; if set, requests carry `X-OpenWhistle-Signature: sha256=…` |

---

## 🧑‍💻 Development

### Setup

```bash
# Install uv (fast Python package manager)
pip install uv

# Install dependencies
uv pip install -e ".[dev]"

# Copy env file
cp .env.example .env
# Set SECRET_KEY in .env

# Start PostgreSQL and Redis
docker compose up db redis -d

# Run migrations
alembic upgrade head

# Start development server
uvicorn app.main:app --reload
```

### Management Scripts

```bash
# List all admin users
python scripts/reset_admin_password.py --list

# Reset a password interactively (prompts twice, masked)
python scripts/reset_admin_password.py --username admin

# Reset non-interactively (CI / automation)
python scripts/reset_admin_password.py --username admin --password "NewPass123!"
```

The script validates password strength (≥ 12 chars, upper + lower + digit) and does not touch
the user's TOTP secret, so the authenticator app continues to work after a password reset.

### Running Tests

```bash
# Type checking
mypy app/ --strict

# Linting
ruff check app/ tests/

# Tests with coverage
pytest --cov=app --cov-report=term-missing
```

---

## 🏗️ Project Structure

```text
app/
├── main.py          # App factory, startup migration check
├── config.py        # pydantic-settings configuration
├── database.py      # Async SQLAlchemy setup
├── middleware.py    # Security headers, IP detection warning
├── api/             # FastAPI routers (reports, auth, admin, wizard)
├── models/          # SQLAlchemy ORM models
├── schemas/         # Pydantic I/O schemas
├── services/        # Business logic (pin, mfa, rate_limit, auth, report)
├── templates/       # Jinja2 HTML templates
└── static/          # Self-hosted CSS, JS, fonts
migrations/          # Alembic database migrations
nginx/               # nginx config with IP logging disabled
docs/                # HinSchG reference and documentation
```

---

## ⚖️ Legal Reference

OpenWhistle is designed to comply with:

- [Hinweisgeberschutzgesetz (HinSchG)](https://www.gesetze-im-internet.de/hinschg/) — German implementation
- [EU Directive 2019/1937](https://eur-lex.europa.eu/legal-content/en/TXT/?uri=CELEX%3A32019L1937)
- [DSGVO / GDPR](https://gdpr-info.eu/)

See [`docs/hinschg_reference.md`](docs/hinschg_reference.md) for a summary of relevant paragraphs.

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
