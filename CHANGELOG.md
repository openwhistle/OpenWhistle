# Changelog

All notable changes to OpenWhistle are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] — 2026-04-28

### Added

- **Playwright E2E test suite** (`tests/e2e/`): 13 test modules covering every
  critical user journey — admin login (incl. MFA), setup wizard redirect behaviour,
  whistleblower anonymous/confidential/file-attachment submissions, status page
  with deadline display, admin workflow (acknowledge → reply → status transitions),
  4-eyes deletion flow, language switcher persistence, PDF export download,
  session expiry, user management RBAC, category and location management lifecycle
- **Automated accessibility tests** (`tests/e2e/test_accessibility.py`): axe-core
  injected into 8 pages; `run_axe` helper filters to critical/serious violations
  and fails on any finding; CDN-unavailable skips gracefully; keyboard navigation
  smoke-test (skip link, tab order, form labels)
- **Locust performance test suite** (`tests/perf/locustfile.py`): three user
  classes (`WhistleblowerUser`, `AdminUser` with TOTP login in `on_start`,
  `StatusChecker`); configurable concurrency; `tests/perf/README.md` with
  thresholds and run instructions
- **OpenAPI contract tests** (`tests/test_openapi_contract.py`): validates
  OpenAPI 3.x structure, required paths (`/health`, `/status`, `/submit`),
  admin route auth enforcement (7 routes assert 3xx for unauthenticated
  requests), and snapshot regression detection via `tests/fixtures/openapi_snapshot.json`
- **E2E CI workflow** (`.github/workflows/e2e.yml`): builds `openwhistle:e2e`
  image, starts full Docker Compose stack with `DEMO_MODE=true`, waits for
  `/health`, runs Playwright tests with Chromium headless, uploads trace on failure
- **Performance CI workflow** (`.github/workflows/perf.yml`): manual
  `workflow_dispatch` with configurable users/run-time/host; uploads HTML + CSV
  Locust artifacts
- **Performance baseline** (`docs/performance-baseline.md`): SLO thresholds
  (`/health` p95 < 50 ms, `/status` p95 < 200 ms, `/admin/dashboard` p95 < 400 ms)
  and user mix ratios for reproducible benchmarks

### Changed

- `pyproject.toml`: new `[e2e]` and `[perf]` optional dependency groups;
  `e2e` and `perf` pytest markers registered; mypy overrides for `playwright.*`
  and `locust.*`; ruff `per-file-ignores` extended to cover `tests/e2e/` and
  `tests/perf/`

## [1.0.0] — 2026-04-27

### Added

- **Envelope encryption at rest**: every new report is encrypted on write with a
  per-report Data Encryption Key (DEK) wrapped via AES-256 (Fernet); the DEK is
  encrypted with a Master Encryption Key (MEK) derived from `SECRET_KEY` using
  HKDF-SHA256; MEK is never stored; report description and all message bodies are
  encrypted; pre-encryption rows are readable without decryption (backward compat)
- **Data retention (GDPR / HinSchG)**: `RETENTION_ENABLED=true` activates a
  daily job (03:00 UTC) that permanently deletes closed reports older than
  `RETENTION_DAYS` (default 1095 = 3 years — HinSchG §12 Abs. 3 minimum); each
  deletion writes an immutable audit-log entry (`report.auto_deleted`) recording
  the case number, closure date, and legal basis
- **Multi-tenancy**: `MULTI_TENANCY_ENABLED=true` activates multi-organisation
  support; `Organisation` model with `name`, `slug`, `is_active`, and `branding`
  JSON; all reports, users, categories, locations, and audit entries carry an
  `org_id` foreign key; per-org unique constraints on category slugs and location
  codes; superadmin role manages organisations via `/admin/organisations`
- **Superadmin role**: new `superadmin` role above `admin`; `require_superadmin`
  dependency guards the organisation management endpoints; existing `admin` role
  retains all previous permissions; role added to `AdminRole` enum via
  `ALTER TYPE adminrole ADD VALUE IF NOT EXISTS 'superadmin'`
- **Telephone reporting channel guide** (`/admin/telephone-channel`): compliance
  page covering HinSchG §16 requirements, implementation options (internal hotline
  vs. external ombudsman), §10 recording prohibition, and a compliance checklist
- **Data retention admin page** (`/admin/retention`): shows current retention
  config, next scheduled run, legal basis (GDPR Art. 5/17, HinSchG §12), and
  configuration reference table
- **Organisation management page** (`/admin/organisations`): superadmin-only page
  to create and deactivate organisations (default org cannot be deactivated)

### Changed

- Report description and message content are now stored encrypted; existing
  plaintext rows are transparently decrypted on first read (backward compat via
  `decrypt_field_safe`)
- Admin report detail page and whistleblower status page now render decrypted
  content instead of raw ciphertext
- Scheduler refactored: both SLA reminders and retention cleanup share a single
  `AsyncIOScheduler` instance; previous per-feature scheduler creation eliminated
- `ReportCategory.slug` and `Location.code` unique constraints changed from global
  to per-organisation composite (`slug + org_id`, `code + org_id`)
- Nav bar in all admin templates updated with links to Telephone Channel, Retention,
  and Organisations pages

### Migrations

- **012** — Creates `organisations` table; adds `org_id` FK and `encrypted_dek`
  column to all data-bearing tables; adds `superadmin` to `adminrole` enum
- **013** — Data migration: backfills `org_id` with default org; makes `org_id`
  NOT NULL; encrypts all existing report descriptions and message bodies; makes
  `encrypted_dek` NOT NULL
- **014** — Replaces global unique constraints on `report_categories.slug` and
  `locations.code` with per-org composite unique constraints
- **015** — Reverts `admin_users.org_id` to nullable to support superadmin
  accounts (org_id = NULL means cross-organisation scope) and direct AdminUser
  creation in external tooling without a prior org lookup

## [0.5.0] — 2026-04-26

### Added

- **Health-check v2**: `/health` endpoint now queries the database (`SELECT 1`)
  and Redis (`PING`) and reports per-component status; returns HTTP 200 with
  `{"status":"ok"}` when all healthy, HTTP 503 with `{"status":"degraded"}` on
  any failure; suitable for Kubernetes liveness and readiness probes
- **Structured JSON logging**: `LOG_LEVEL` (default `INFO`) and `LOG_FORMAT`
  (`json` or `text`, default `json`) environment variables; JSON output via
  `python-json-logger`; all uvicorn loggers reconfigured uniformly at startup
- **Slack / Teams webhook formatter**: `NOTIFY_WEBHOOK_TYPE` (`generic`, `slack`,
  `teams`) selects the payload format; Slack uses Block Kit (header + fields +
  action button); Teams uses Adaptive Cards (v1.4, FactSet + OpenUrl action);
  both new-report and SLA-reminder notifications respect the setting
- **SLA reminder system**: background scheduler (`APScheduler`, interval 30 min)
  fires `send_sla_reminders()`; checks all non-closed reports for approaching
  7-day acknowledgement deadline (`REMINDER_ACK_WARN_DAYS`, default 2 days
  before expiry) and 3-month feedback deadline (`REMINDER_FEEDBACK_WARN_DAYS`,
  default 30 days before expiry); Redis dedup keys (`reminder:ack:{case}`,
  `reminder:feedback:{case}`) with 1-hour TTL prevent duplicate notifications;
  enabled with `REMINDER_ENABLED=true`
- **S3-compatible attachment storage**: `STORAGE_BACKEND=s3` routes new
  attachments to an S3-compatible bucket (AWS S3, MinIO, Hetzner Object Storage)
  via boto3 (sync calls wrapped in `asyncio.to_thread`); `S3_ENDPOINT_URL`,
  `S3_BUCKET_NAME`, `S3_ACCESS_KEY_ID`, `S3_SECRET_ACCESS_KEY`, `S3_REGION`,
  `S3_PREFIX` configure the target; existing DB-backed attachments are
  unaffected (backward-compatible migration makes `data` nullable, adds
  `storage_key VARCHAR(512)`)
- **LDAP / Active Directory login**: `LDAP_ENABLED=true` enables corporate
  directory authentication for admin accounts; two-phase bind (service account
  → user DN re-bind to verify password); `ldap3` runs synchronously in a thread
  pool; first LDAP login auto-provisions an `AdminUser` record; subsequent logins
  re-use the existing record; `TOTP` enrollment still required after first login;
  `LDAP_SERVER`, `LDAP_PORT`, `LDAP_USE_SSL`, `LDAP_BIND_DN`,
  `LDAP_BIND_PASSWORD`, `LDAP_BASE_DN`, `LDAP_USER_FILTER`,
  `LDAP_ATTR_USERNAME`, `LDAP_ATTR_EMAIL` configure the connection
- **Helm chart**: `charts/openwhistle/` — production-grade Helm chart for
  Kubernetes deployments; `Chart.yaml`, `values.yaml`, 8 templates
  (`deployment.yaml`, `service.yaml`, `ingress.yaml`, `hpa.yaml`,
  `configmap.yaml`, `secret.yaml`, `_helpers.tpl`, `NOTES.txt`); all v0.5.0
  env vars exposed as chart values; supports existing-secret pattern for
  credentials; liveness/readiness probes wire to `/health`
- **Ansible role**: `ansible/roles/openwhistle/` — official Ansible role for
  bare-metal / VM deployments (Debian/Ubuntu); installs Docker CE + Compose
  plugin; creates system user `openwhistle`; renders `.env`, `nginx.conf`, and
  `docker-compose.yml` from Jinja2 templates; installs systemd service unit;
  optionally obtains TLS certificate via Certbot with auto-renewal hook;
  `ansible/deploy.yml` example playbook; `vault.yml.example` secrets template

### Changed

- `app_version` bumped to `0.5.0`
- Admin login page shows a badge when `LDAP_ENABLED=true`
- `admin_users.password_hash` is now nullable (migration 011) — LDAP-only
  accounts have no local password
- `attachments.data` is now nullable (migration 010) — S3-backed attachments
  store only `storage_key`

### Database migrations

- `010_s3_attachment_storage.py`: makes `attachments.data` nullable; adds
  `storage_key VARCHAR(512)` column to `attachments`
- `011_ldap_auth.py`: makes `admin_users.password_hash` nullable; adds
  `ldap_username VARCHAR(255) UNIQUE` column to `admin_users`

### Dependencies added

- `python-json-logger>=3.2.0` — structured JSON log formatter
- `apscheduler>=3.11.0` — background job scheduler for SLA reminders
- `boto3>=1.38.0` — AWS S3-compatible object storage client
- `ldap3>=2.9.0` — LDAP / Active Directory authentication

### Tests

- Added `tests/test_v050.py` — 68 tests covering all new v0.5.0 features
- Fixed `conftest.py`: added `adminrole` to the enum drop list so re-runs
  don't fail with "type already exists" on migration 003
- Coverage maintained at ≥90% (90.36% with full test suite)

## [0.4.0] — 2026-04-26

### Added

- **Multi-step submission form**: single-page `/submit` replaced with a guided 5–6 step wizard
  (mode → location → category → description → attachments → review); Redis session stores
  partial state under `submission-session:{uuid}` with a 2-hour TTL; back/next navigation
  throughout; progress indicator shows current step and total; `ow-submission-session` cookie
- **Anonymous vs. confidential mode (Step 1)**: whistleblowers choose anonymous (no personal
  data) or confidential (optional name, contact info, secure email); confidential data encrypted
  with Fernet symmetric encryption derived from `SECRET_KEY`; decrypted only on the assigned
  admin's report detail view; new `SUBMISSION_MODE_ENABLED` config toggle
- **Multi-location / branch selection (Step 2, conditional)**: `Location` model with `id`,
  `name`, `code` (unique), `description`, `is_active`, `sort_order`, `created_at`; location
  selector shown only when active locations exist; admin management at `/admin/locations`
- **Confidential fields on reports**: `submission_mode` (enum), `location_id` (FK), `confidential_name`
  (encrypted text), `confidential_contact` (encrypted text), `secure_email` (encrypted text)
  added to `reports` table via migration 009; all nullable for zero-downtime deploy
- **Optional secure contact email**: whistleblower can provide an anonymous email address
  in confidential mode; when admin posts a reply, a brief notification (no report content)
  is sent; `secure_email` never appears in logs
- **HinSchG deadline display for whistleblowers**: status page shows 7-day acknowledgement
  deadline with days remaining (or confirmed date) and 3-month feedback deadline with
  days left / pending acknowledgement indicator
- **French language (fr)**: `app/locales/fr.json` with full French translations for all keys;
  `fr` added to supported languages in `app/i18n.py`; language picker in nav bar shows
  English / Deutsch / Français dropdown
- **Location filter on admin dashboard**: filter reports by location; location shown in
  report detail sidebar
- **WCAG 2.1 AA accessibility improvements**: skip-to-content link in `base.html`; `aria-label`
  on all nav elements; `aria-current="page"` on active nav links; `aria-live` regions; `role="alert"`
  on errors; `aria-required` on required fields; `aria-describedby` on hints; `sr-only` utility;
  visible focus indicators; language picker keyboard-accessible
- **New CSS components**: submit progress indicator, mode-selection cards with `:has()` focus
  handling, step-action row, review table, skip link, lang picker dropdown

### Changed

- `app_version` bumped to `0.4.0`
- Admin nav in all templates updated to include "Locations" link
- Demo seed creates two demo locations (HQ, Remote) and one confidential demo report
- PDF export includes submission mode, location, and confidential fields (secure email noted
  as "on file — not printed" for privacy)
- `add_admin_message` accepts `notify_whistleblower=True` to trigger async secure-email
  notification when a secure email is on file
- `get_reports_paginated` accepts optional `location_id` filter
- Health endpoint now returns current `app_version`

### Fixed

- Language switcher now correctly handles French (`fr`) in redirect allowlist

### Migration

- Migration `009_locations_confidential.py`: creates `locations` table, `submissionmode` enum,
  adds `location_id`, `submission_mode`, `confidential_name`, `confidential_contact`,
  `secure_email` to `reports`

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

[Unreleased]: https://github.com/openwhistle/OpenWhistle/compare/v1.1.0...HEAD
[1.1.0]: https://github.com/openwhistle/OpenWhistle/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.5.0...v1.0.0
[0.5.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/openwhistle/OpenWhistle/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/openwhistle/OpenWhistle/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/openwhistle/OpenWhistle/releases/tag/v0.1.0
