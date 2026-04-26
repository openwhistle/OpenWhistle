# OpenWhistle

> Open source whistleblower reporting platform — compliant with HinSchG and EU Directive 2019/1937

[![CI](https://img.shields.io/github/actions/workflow/status/openwhistle/OpenWhistle/ci.yml?label=CI)](https://github.com/openwhistle/OpenWhistle/actions/workflows/ci.yml)
[![Docker](https://img.shields.io/github/actions/workflow/status/openwhistle/OpenWhistle/docker-publish.yml?label=Docker)](https://github.com/openwhistle/OpenWhistle/actions/workflows/docker-publish.yml)
[![License](https://img.shields.io/badge/license-GPL--3.0-blue)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.14-blue)](https://python.org)
[![PostgreSQL](https://img.shields.io/badge/postgresql-18-blue)](https://postgresql.org)

> [!WARNING]
> OpenWhistle is currently in early development (alpha). Do not use in production.

## Overview

OpenWhistle provides a secure internal reporting channel as required by:

- **German law:** Hinweisgeberschutzgesetz (HinSchG), in force since 2 July 2023
- **EU directive:** Directive (EU) 2019/1937 of the European Parliament

Any company with 50 or more employees and all public authorities are legally required to
provide an internal reporting channel. OpenWhistle provides a self-hosted, open source
solution — free of charge.

## Key Features

- **Full anonymity:** No IP addresses logged — not by the application, not by nginx
- **Two-factor whistleblower access:** Case number + secret UUID4 PIN (bruteforce-protected)
- **Bidirectional communication:** Required by HinSchG §17 — whistleblower can reply
- **HinSchG SLA tracking:** 7-day acknowledgement and 3-month feedback deadlines
- **Mandatory MFA:** TOTP (Google Authenticator) for all admin accounts
- **OIDC support:** Optional SSO via any OpenID Connect provider
- **File attachments:** Whistleblowers can attach evidence files (PDF, images, Word, Excel, CSV,
  TXT — up to 10 MB each, 5 per report)
- **DSGVO compliant:** All resources self-hosted, no external CDN calls, hard deletion support
- **Setup wizard:** First-run admin account creation with TOTP setup
- **IP leakage detection:** Warning when upstream proxies forward IP headers
- **Multi-registry Docker:** Published to ghcr.io, Docker Hub, and quay.io

## Technical Stack

| Component | Technology |
|---|---|
| Language | Python 3.14 |
| Framework | FastAPI 0.136 |
| Database | PostgreSQL 18 (via SQLAlchemy 2.0 async) |
| Cache / Sessions | Redis 8 |
| Auth | pyotp (TOTP), authlib 1.7+ (OIDC) |
| Templates | Jinja2 (server-side rendering) |
| Reverse Proxy | nginx (IP logging disabled) |

## Live Demo

A live demo is available at **<https://demo.openwhistle.net>**

| Role | Username | Password | TOTP Code |
|---|---|---|---|
| Admin | `demo` | `demo` | `000000` |

Demo case numbers and PINs are shown after logging in to the demo admin account.

The demo resets automatically every hour.

## Container Images

Pre-built multi-arch images (linux/amd64, linux/arm64) are published to three registries:

```bash
# GitHub Container Registry (primary)
docker pull ghcr.io/openwhistle/openwhistle:latest

# Docker Hub
docker pull openwhistle/openwhistle:latest

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

## How to Install

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

### Behind a Reverse Proxy

**Critical for anonymity:** Disable access logging and strip IP headers.

#### nginx

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

#### Cloudflare

1. Enable "Remove visitor IPs from logs" in the Cloudflare dashboard
2. Do **not** use "Restore visitor IP" — it adds `CF-Connecting-IP`
3. OpenWhistle will warn you in the admin dashboard if IP headers are detected

#### Traefik

```yaml
middlewares:
  strip-ip-headers:
    headers:
      customRequestHeaders:
        X-Forwarded-For: ""
        X-Real-IP: ""
        True-Client-IP: ""
```

## Environment Variables

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

## Development

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

# Inside a running Docker container
docker exec -it <container_name> python scripts/reset_admin_password.py --username admin
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

### Project Structure

```text
app/
├── main.py          # App factory, startup migration check
├── config.py        # pydantic-settings configuration
├── database.py      # Async SQLAlchemy setup
├── middleware.py     # Security headers, IP detection warning
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

## Legal Reference

OpenWhistle is designed to comply with:

- [Hinweisgeberschutzgesetz (HinSchG)](https://www.gesetze-im-internet.de/hinschg/) — German implementation
- [EU Directive 2019/1937](https://eur-lex.europa.eu/legal-content/en/TXT/?uri=CELEX%3A32019L1937)
- [DSGVO / GDPR](https://gdpr-info.eu/)

See [`docs/hinschg_reference.md`](docs/hinschg_reference.md) for a summary of relevant paragraphs.

> **Disclaimer:** OpenWhistle is a technical tool. Operators are responsible for ensuring
> their deployment meets all applicable legal requirements in their jurisdiction.

## License

OpenWhistle is released under the [GNU General Public License v3.0](LICENSE).

## Contributing

Contributions are welcome. Please open an issue before submitting a pull request.

## Donate

OpenWhistle is developed in free time. If you find it useful, consider supporting the project.

[![GitHub Sponsors](https://img.shields.io/github/sponsors/jpylypiw?label=Sponsor)](https://github.com/sponsors/jpylypiw)
