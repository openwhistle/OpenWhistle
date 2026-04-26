# Changelog

All notable changes to OpenWhistle are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.2.1] — 2026-04-26

### Fixed

- Case number generation now uses `MAX(case_number)` instead of `COUNT(*)`, preventing a
  previously-issued case number from being reused after a report is hard-deleted
- Test isolation: orphaned report in `test_delete_report_only_removes_matching_sessions` caused
  a `UniqueViolationError` on CI; the test now cleans up all created reports

### Security

- Resolved 4 additional CodeQL code scanning alerts:
  - `py/url-redirection` (set-language endpoint): redirect target resolved via a static
    `_NEXT_ALLOWLIST` dict, severing any taint flow from user-supplied input
  - `py/cookie-injection` (reply endpoint): session cookie always rotated to a fresh
    `secrets.token_urlsafe()` value on every reply, never derived from the inbound cookie
  - `py/clear-text-logging` ×2 (reset_admin_password.py): replaced variable-based error
    messages with explicit if-chains where every `print()` argument is a string literal,
    eliminating any data-flow path from the password variable to a logging sink

## [0.2.0] — 2026-04-26

### Added

- Admin session expiry warning: a non-intrusive banner appears 5 minutes before the session expires
  with a live countdown and a one-click "Extend Session" button that silently refreshes the JWT and
  Redis TTL without losing work (`GET /admin/session/ttl`, `POST /admin/session/refresh`)
- Admin dashboard pagination with configurable page size (10 / 25 / 50 / 100), server-side
- Admin dashboard column sorting (submitted date, case number, category, status)
- Admin dashboard status filtering with clickable stat cards
- File attachment support: whistleblowers can upload evidence files (PDF, images, Word, Excel, CSV,
  TXT — up to 10 MB each, 5 files per report); admins can download attachments from the report
  detail page
- Email and webhook notifications when a new report is submitted (`NOTIFY_EMAIL_*` and
  `NOTIFY_WEBHOOK_*` environment variables)
- CSRF Double-Submit Cookie protection extended to all whistleblower POST endpoints
  (`/submit`, `/status`, `/reply`)
- `scripts/reset_admin_password.py`: interactive CLI to reset any admin user's password without
  direct database access; supports `--list`, `--username`, `--password`; enforces password strength
  requirements; does not touch the TOTP secret
- HTML error page for form validation errors (422) instead of raw JSON API response
- Company branding: `BRAND_PRIMARY_COLOR`, `BRAND_SECONDARY_COLOR`, `BRAND_LOGO_URL` env vars allow
  organisations to customise the UI with their own colours and logo
- OIDC Authorization Code Flow: admins can log in via any OpenID Connect provider when
  `OIDC_ENABLED=true` (authlib 1.7+, state stored in Redis with 5-minute TTL)
- Docker image cleanup workflow (GHCR, Docker Hub, Quay.io — runs weekly, retains 10 most recent
  `sha-` tagged images per registry)
- `edge` Docker tag published on every push to `main` for tracking the latest unreleased state
- Complete UI redesign: "Trusted Institution" aesthetic (Sora + Nunito Sans typography, white
  navigation bar, institutional blue + teal accent palette, elevation shadows, rounded corners)
- Professional dark mode with warm blue-gray palette (`#111827`)
- Submit-page sidebar redesigned with brand-colour background and subtle radial gradient
- SSO button on admin login page (shown only when `OIDC_ENABLED=true`)
- GitHub Pages website deployed from `docs/` directory

### Fixed

- Whistleblower status-session Redis keys are now cleaned up immediately when a report is
  hard-deleted (previously persisted for up to 2 hours as orphaned entries)
- SLA "days remaining" dashboard column no longer renders a double unit (e.g. "89d Tage verbleibend")
- Session cookie deletion now passes matching security attributes (httponly, samesite, secure) so
  browsers reliably remove the cookie on logout
- Theme toggle button now inherits the correct body font instead of falling back to the system font
- Public forms no longer bypass browser `required`-attribute validation (removed `novalidate` from
  `/submit` and `/status` forms)
- Empty reply content and oversized descriptions now return 422 with server-side length enforcement
  (previously validated by HTML attribute only, bypassable via direct HTTP requests)

### Security

- All whistleblower-facing cookies now use `secure=not settings.demo_mode`
  (was hardcoded `False`, meaning cookies were sent over HTTP even in production)
- Server-side max-length validation added for report description (≤ 10 000 chars) and reply
  content (≤ 5 000 chars) — previously enforced by HTML `maxlength` attribute only
- CSRF Double-Submit Cookie pattern extended to `/status` and `/reply` whistleblower endpoints

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

- **Python 3.14** over Go/Rust: team familiarity with Python; mypy --strict provides compile-like
  type safety guarantees in CI
- **FastAPI** for async performance and Pydantic validation
- **SQLAlchemy 2.0 async** for type-safe database access
- **Authlib 1.7.0+** required due to CVE-2026-28498 in earlier versions
- **SSR with Jinja2** over SPA: simpler security model, no client-side secrets, works without JavaScript
- **Session tokens in Redis** for instant revocation without database lookups
- **Rate limiting by session token** (not IP) to maintain full anonymity
- **alembic upgrade head** on every startup to guarantee migration consistency

[Unreleased]: https://github.com/openwhistle/OpenWhistle/compare/v0.2.1...HEAD
[0.2.1]: https://github.com/openwhistle/OpenWhistle/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/openwhistle/OpenWhistle/releases/tag/v0.1.0
