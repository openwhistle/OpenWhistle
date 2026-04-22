# Changelog

All notable changes to OpenWhistle are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added

- CSRF protection using Double-Submit Cookie pattern (`app/csrf.py`):
  all admin forms and the setup wizard now require a matching `ow_csrf` cookie + hidden field
- OIDC Authorization Code Flow (`app/services/oidc.py`):
  admins can log in via any OpenID Connect provider when `OIDC_ENABLED=true`
- OIDC state stored in Redis with 5-minute TTL to prevent replay attacks
- SSO button on admin login page (shown only when `OIDC_ENABLED=true`)
- GitHub Pages website deployed from `docs/` directory
- HinSchG reference document at `docs/hinschg_reference.md`

## [0.1.0] — 2026-04-21

### Added

- Complete rewrite from C# ASP.NET Core to Python 3.14 / FastAPI
- Whistleblower report submission with category and description
- Two-factor whistleblower access: case number (OW-YYYY-NNNNN) + UUID4 secret PIN
- Bidirectional communication thread between whistleblower and reporting office (HinSchG §17)
- First-run setup wizard for admin account creation with TOTP enrollment
- Mandatory TOTP (RFC 6238) MFA for all administrator accounts
- Optional OIDC login for administrators (authlib 1.7+)
- HinSchG SLA tracking: 7-day acknowledgement deadline (§17 Abs. 1) and 3-month feedback deadline (§17 Abs. 2)
- IP anonymity: nginx configured with `access_log off`, application never reads or stores IP addresses
- IP leakage detection: admin dashboard warning when upstream proxies forward IP headers
- Redis-based bruteforce protection with no IP tracking (session-token-based rate limiting)
- Hard deletion of reports (DSGVO Art. 17 right to erasure)
- Demo mode with seed data (`DEMO_MODE=true`)
- Automatic database migration check on every startup (alembic upgrade head)
- DSGVO-compliant: all fonts and static assets self-hosted (Spectral, Source Serif 4, JetBrains Mono)
- Light / dark mode with localStorage persistence and CSS media query fallback
- Security headers: CSP, HSTS, X-Frame-Options, Referrer-Policy, Permissions-Policy
- Multi-registry Docker publishing: ghcr.io, Docker Hub, quay.io
- Image signing with Cosign
- GitHub Actions CI: mypy --strict, ruff, pytest with coverage, docker build
- HinSchG reference document (`docs/hinschg_reference.md`)
- PostgreSQL 18 + Redis 8 support

### Technical Decisions

- **Python 3.14** over Go/Rust: team familiarity with Python; mypy --strict provides compile-like type safety guarantees in CI
- **FastAPI** for async performance and Pydantic validation
- **SQLAlchemy 2.0 async** for type-safe database access
- **Authlib 1.7.0+** required due to CVE-2026-28498 in earlier versions
- **SSR with Jinja2** over SPA: simpler security model, no client-side secrets, works without JavaScript
- **Session tokens in Redis** for instant revocation without database lookups
- **Rate limiting by session token** (not IP) to maintain full anonymity
- **alembic upgrade head** on every startup to guarantee migration consistency

[Unreleased]: https://github.com/openwhistle/OpenWhistle/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/openwhistle/OpenWhistle/releases/tag/v0.1.0
