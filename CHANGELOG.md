# Changelog

All notable changes to OpenWhistle are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.3.0] — 2026-04-26

### Added

- **RBAC — Role-Based Access Control**: `AdminRole` enum with `admin` and `case_manager` roles;
  `require_role()` FastAPI dependency factory; role shown in dashboard nav and report detail
- **Case assignment**: admins can assign reports to any active staff member; "My Cases" filter
  tab on dashboard; assignee column in reports table
- **Status workflow overhaul**: `received → in_review → pending_feedback → closed` replaces
  the old `received → acknowledged → in_progress → closed` flow; `STATUS_TRANSITIONS` dict
  enforces valid transitions server-side; only valid next-states shown in UI
- **4-eyes deletion principle**: report deletion now requires two different admins — one requests,
  a different one confirms; same-admin confirm returns HTTP 409
- **Immutable audit log**: `AuditLog` model with 18 `AuditAction` constants; every admin action
  is recorded; exportable as CSV from `/admin/audit-log`; last 20 entries shown per report
- **Custom DB-driven categories**: `ReportCategory` model replaces hard-coded Python enum;
  category management page at `/admin/categories`; existing reports preserve category as string
- **Case linking**: `CaseLink` model with normalization constraint (smaller UUID always in
  `report_id_a`); link/unlink cases from report detail page
- **Internal notes**: `AdminNote` model — admin-only notes never shown to whistleblower;
  add notes from report detail page
- **PDF export**: full case export via `/admin/reports/{id}/export.pdf` using `fpdf2`
  (pure Python, no system packages); includes SLA compliance section per HinSchG §17
- **Admin user management**: create, deactivate, reactivate, and change roles of admin users
  at `/admin/users`; last-active-admin protection prevents lockout
- **Dashboard statistics**: `/admin/stats` page with status distribution bar charts, category
  breakdown, total count, and 7-day SLA compliance rate
- **Demo seed improvements**: case manager demo user (`case_manager`/`demo`); 4 demo reports
  covering all statuses; demo internal notes, case links, and audit entries
- **New admin navigation**: persistent links to Stats, Categories, Users, Audit Log from all
  admin pages

### Changed

- Report `category` field migrated from PostgreSQL enum to `VARCHAR(64)` — stored as plain
  string at submit time for history immutability (migration 006)
- `acknowledged_report()` now transitions to `in_review` instead of `acknowledged`
- Status labels updated throughout UI and i18n files

### Database migrations

- `003_roles_status_assignment.py` — adds `adminrole` enum, `role`/`is_active` to admin_users,
  adds `in_review`/`pending_feedback` to reportstatus enum, migrates old values, adds
  `assigned_to_id` FK to reports
- `004_audit_log.py` — creates `audit_log` table
- `005_admin_notes.py` — creates `admin_notes` table
- `006_custom_categories.py` — creates `report_categories` table, seeds 7 defaults, migrates
  `reports.category` from enum to VARCHAR
- `007_deletion_requests.py` — creates `deletion_requests` table with UNIQUE(report_id)
- `008_case_links.py` — creates `case_links` table with normalization CHECK constraint

### Tests

- Added `test_v030_services.py` — 35 service-layer tests for new features
- Added `test_v030_api.py` — 25 API-level tests for new admin endpoints
- Added `test_pdf_service.py` — PDF generation tests
- Updated existing tests to use new `ReportStatus` values (`in_review`, `pending_feedback`)

## [0.2.2] — 2026-04-26

### Changed

- Logo redesigned: new "Protected Signal" concept — navy shield with gradient depth, amber glow,
  and three-arc signal mark; consistent across app favicon, docs favicon, apple-touch-icon,
  and all inline SVG nav logos
- README trimmed to overview + quick start; full documentation lives exclusively at
  openwhistle.net/docs.html (single source of truth, no duplication)
- docs.html nav CSS aligned with index.html: SVG circle selector, border-color transition on
  theme-toggle hover, and light-mode stroke overrides for the logo

### Fixed

- Quay.io image reference corrected to `quay.io/jp1337/openwhistle` everywhere

### Tests

- Added 128 new test cases across auth, admin, reports, misc, and demo seed modules
- Coverage increased from ~75 % to 91 %
- Resolved all CI test failures caused by DEMO\_MODE=true and function-scoped event loop conflicts
- Extracted `_seed(db)` helper from `demo_seed.py` to enable direct session injection in tests

### CI / CD

- Codecov integration: added `CODECOV_TOKEN` secret and pinned `codecov-action@v5`
- GitHub org avatar (500×500) and repository social preview banner (1280×640) added under `docs/`

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
