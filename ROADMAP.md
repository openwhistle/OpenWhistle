# OpenWhistle Roadmap

This document tracks planned features, improvements, and long-term goals.
Items are grouped by release milestone. Priorities can shift based on community
feedback — open an issue to discuss anything here.

---

## v0.3.0 — Multi-User Admin & Custom Categories ✓ Released 2026-04-26

> All items shipped. See [CHANGELOG.md](CHANGELOG.md#030--2026-04-26) for details.

### Admin & Case Management

- [x] **Multiple admin users with roles** — `ADMIN` and `CASE_MANAGER` roles;
  `require_role()` FastAPI dependency factory; role shown in dashboard nav
- [x] **Case assignment** — assign reports to any active admin; "My Cases" filter
  on dashboard; assignee column in reports table
- [x] **Custom report categories** — DB-driven `ReportCategory` model replaces
  hard-coded enum; full management UI at `/admin/categories`
- [x] **Case linking** — `CaseLink` model with UUID normalization constraint;
  link/unlink from report detail page
- [x] **4-eyes principle for hard deletion** — request/confirm by two different
  admins; same-admin confirm returns HTTP 409
- [x] **Internal notes** — `AdminNote` model; never shown to the whistleblower
- [x] **Report status workflow** — `received → in_review → pending_feedback →
  closed`; `STATUS_TRANSITIONS` enforces valid transitions server-side

### Audit Log

- [x] **Immutable audit log** — 18 `AuditAction` constants; every admin action
  recorded with timestamp and username; required for HinSchG §12 Abs. 3
- [x] **Audit log export** — CSV download from `/admin/audit-log`; filterable
  by action and report ID

### Export & Reporting

- [x] **PDF export** — full case export at `/admin/reports/{id}/export.pdf`
  via fpdf2 (pure Python, no system packages); includes SLA compliance section
- [x] **Dashboard statistics** — `/admin/stats` with SLA compliance rate,
  status distribution bars, and category breakdown

---

## v0.4.0 — Whistleblower UX & Multi-Step Form ✓ Released 2026-04-26

> All items shipped. See [CHANGELOG.md](CHANGELOG.md#040--2026-04-26) for details.

### Whistleblower Experience

- [x] **Multi-step submission form** — 5–6 step guided wizard (mode → location →
  category → description → attachments → review); Redis session stores partial
  state with 2-hour TTL; back/next navigation; progress indicator
- [x] **Anonymous vs. confidential mode** — whistleblower chooses at step 1;
  confidential data (name, contact, secure email) stored encrypted with Fernet;
  decrypted only on the assigned admin's report detail view
- [x] **Multi-location / branch selection** — `Location` model; selector shown
  only when active locations exist; full admin management at `/admin/locations`;
  location filter on admin dashboard
- [x] **Optional secure contact method** — whistleblower may provide an anonymous
  e-mail; admin reply triggers a brief notification (no report content); address
  stored encrypted, never logged
- [x] **Deadline display for whistleblower** — status page shows 7-day
  acknowledgement deadline and 3-month feedback deadline with days remaining

### Accessibility & Internationalisation

- [x] **Full German i18n** — all 388 translation keys present in `de.json`;
  all user-facing text routed through the translation system
- [x] **Third language (French)** — `app/locales/fr.json` with 388 keys;
  language picker in nav bar shows English / Deutsch / Français
- [x] **WCAG 2.1 AA audit** — skip-to-content link; `aria-label` on all nav
  elements; `aria-current="page"`; `aria-live` regions; `role="alert"` on
  errors; `aria-required`; `aria-describedby`; visible focus indicators

---

## v0.5.0 — Notifications, Integrations & Reliability ✓ Released 2026-04-26

> All items shipped. See [CHANGELOG.md](CHANGELOG.md#050--2026-04-26) for details.

### Notifications

- [x] **Follow-up / reminder system** — APScheduler fires every 30 min; Redis
  dedup keys prevent duplicate notifications; `REMINDER_ENABLED`,
  `REMINDER_ACK_WARN_DAYS`, `REMINDER_FEEDBACK_WARN_DAYS` env vars
- [x] **Whistleblower reply notification** — optional secure-contact email
  triggered when admin posts a reply (shipped in v0.4.0)
- [x] **Slack / Teams webhook** — `NOTIFY_WEBHOOK_TYPE` selects Block Kit
  (Slack) or Adaptive Card v1.4 (Teams) payload

### Integrations

- [x] **S3-compatible attachment storage** — `STORAGE_BACKEND=s3` with
  `S3_*` env vars; boto3 wrapped in `asyncio.to_thread`; backward-compatible
  DB migration makes `attachments.data` nullable
- [x] **LDAP / Active Directory login** — `LDAP_ENABLED=true`; two-phase
  bind via `ldap3`; auto-provisions `AdminUser` on first login

### Reliability & Operations

- [x] **Health-check endpoint v2** — DB + Redis connectivity in `/health`;
  HTTP 200/503 with `{"status":"ok"|"degraded","components":{...}}`
- [x] **Structured JSON logging** — `LOG_LEVEL` / `LOG_FORMAT` env vars;
  `python-json-logger` formatter; all uvicorn loggers reconfigured
- [x] **Helm chart** — `charts/openwhistle/` with 8 templates; all v0.5.0
  values exposed; liveness/readiness probes; HPA + Ingress support
- [x] **Ansible role** — `ansible/roles/openwhistle/`; Docker CE + Compose
  install; systemd unit; Certbot TLS; Jinja2 nginx config

---

## v1.0.0 — Production-Ready & Compliance-Complete ✓ Released 2026-04-27

> All items shipped. See [CHANGELOG.md](CHANGELOG.md#100--2026-04-27) for details.

### Security & Privacy

- [x] **Encrypted report storage** — envelope encryption at-rest; per-report DEK
  wrapped with HKDF-SHA256 MEK derived from `SECRET_KEY`; Fernet AES-256;
  admin UI transparently decrypts; pre-encryption rows backward-compatible
- [x] **Data-retention policy** — `RETENTION_ENABLED=true` + `RETENTION_DAYS`
  (default 1095 = 3 years); daily job at 03:00 UTC; GDPR Art. 5(1)(e) + HinSchG
  §12 Abs. 3; immutable `report.auto_deleted` audit log entries; admin page at
  `/admin/retention`

### Multi-Tenancy

- [x] **Multi-tenancy** — `MULTI_TENANCY_ENABLED=true`; `Organisation` model
  (id, name, slug, branding JSON); `org_id` FK on all data tables; superadmin
  role manages organisations at `/admin/organisations`; default org auto-created
  at setup
- [x] **Superadmin role** — `superadmin` > `admin` > `case_manager` hierarchy;
  `require_superadmin` guards org management; existing admin permissions unchanged

### Compliance Tools

- [x] **Telephone reporting channel guide** — `/admin/telephone-channel`;
  HinSchG §16 checklist, internal hotline vs. ombudsman options, §10 recording
  prohibition notice, legal references

### Completed (previously planned)

- [x] **SOC 2 / ISO 27001 documentation** — security policy template and DPA
  template available in `docs/security/`

---

## v1.1.0 — Complete Test Coverage & Quality Assurance ✓ Released 2026-04-28

> All items shipped. See [CHANGELOG.md](CHANGELOG.md#110--2026-04-28) for details.

> Goal: fill every gap left by the unit/integration/HTTP-level suite.
> All existing tests use `httpx.AsyncClient` against a real DB — they prove
> the API works but never open a browser, never touch JavaScript, and never
> exercise real user journeys end-to-end. This milestone adds the missing
> layers: Playwright E2E, automated accessibility, performance baseline,
> and API contract validation.

### E2E Tests — Playwright (Python)

Test infrastructure:
- `playwright` + `pytest-playwright` + `pytest-base-url` added to dev deps
- New `tests/e2e/` directory; separate `pytest` markers (`e2e`)
- CI job `e2e` starts the full Docker Compose stack (app + db + redis) with
  demo seed data and runs the suite against `http://localhost:8000`
- `conftest.py` provides: `base_url`, `admin_page` fixture (logs in, completes
  MFA with demo TOTP secret), `whistleblower_page` fixture (fresh browser context)
- Chromium headless is the primary target; Firefox smoke-test via second CI job
- All E2E tests tagged `@pytest.mark.e2e` and excluded from the unit/integration
  run; coverage threshold `--cov-fail-under=90` remains on the non-E2E suite

Critical user journeys to cover:

- [x] **Setup wizard E2E** — fresh DB; load `/setup`; fill username/password;
  verify QR code is rendered; enter TOTP from `pyotp`; assert redirect to login
- [x] **Admin login E2E** — enter credentials; submit; reach MFA page; enter TOTP;
  assert dashboard renders with case count; assert session cookie is set
- [x] **Whistleblower full submission — anonymous mode** — navigate to `/submit`;
  proceed through all 6 steps (mode → skip location → category → description →
  skip attachment → review); submit; assert success page shows case number and PIN
- [x] **Whistleblower full submission — confidential mode** — same as above but
  enter name and contact at step 1; assert encrypted fields visible to admin
- [x] **Whistleblower full submission — with file attachment** — upload a PDF at
  the attachment step; assert filename appears on review page; assert attachment
  downloadable by admin
- [x] **Whistleblower status page** — enter case number + PIN from previous test;
  assert status badge, 7-day and 3-month deadline counters visible
- [x] **Admin case acknowledgement** — open report detail; click Acknowledge;
  assert status changes to `in_review`; assert 7-day badge disappears
- [x] **Admin reply + whistleblower reads reply** — admin posts a reply; open
  whistleblower status page; assert reply text appears in thread
- [x] **Admin status transitions** — cycle `in_review → pending_feedback → closed`;
  assert each transition reflected in dashboard badge; assert invalid transition
  (e.g. `closed → in_review`) is blocked with an error message
- [x] **4-eyes deletion E2E** — admin A requests deletion; assert pending-delete
  badge; admin A tries to confirm — assert 409 error message; admin B confirms —
  assert report gone from dashboard
- [x] **Language switcher E2E** — click DE in nav; assert page title contains
  German text; click FR; assert French; click EN; assert English; assert
  selection persists on page reload (cookie/localStorage)
- [x] **PDF download E2E** — click export PDF button; assert download response
  is `application/pdf` with non-empty body; no ciphertext visible in PDF text
- [x] **Session expiry warning E2E** — mock session close to near-expiry;
  assert warning banner appears; click extend; assert banner disappears
- [x] **Admin user management E2E** — create new `case_manager` user; login as
  that user; assert no access to `/admin/users` or `/admin/categories`
- [x] **Category management E2E** — create a category; deactivate it; assert it
  no longer appears in the whistleblower submission form
- [x] **Location management E2E** — create a location; assert it appears at
  submission step 2 (location selector shown only when active locations exist)
- [x] **Retention admin page E2E** — navigate to `/admin/retention`; assert
  current settings visible; assert save action returns success flash

### Accessibility Tests (axe-core via Playwright)

- [x] **axe-core integration** — axe-core injected via `page.add_script_tag`;
  `run_axe(page, axe_source)` helper filters to `critical`/`serious` violations;
  skips gracefully when CDN unavailable
- [x] **Axe: submit form pages** — run on every step of the multi-step wizard
  (6 steps × 2 modes); zero critical/serious violations
- [x] **Axe: status page** — run on whistleblower status page with an open report
- [x] **Axe: admin dashboard** — run on `/admin/dashboard` with demo data loaded
- [x] **Axe: admin report detail** — run on `/admin/reports/{id}` with messages,
  notes, and attachments present
- [x] **Axe: login and MFA pages** — run on `/admin/login` and `/admin/login/mfa`
- [x] **Axe: language variants** — run axe on DE and FR versions of submit and
  status page; verify no new violations introduced by translated content
- [x] **Keyboard navigation smoke-test** — verify skip-link, tab order through
  form steps, and modal dialogs are keyboard-accessible in Playwright

### Performance Baseline (Locust)

- [x] **Locust installed as dev dependency**; `tests/perf/locustfile.py` with
  three user classes: `WhistleblowerUser`, `AdminUser`, `StatusChecker`
- [x] **Whistleblower submission load** — 50 concurrent users; each completes the
  full 6-step form submission; target: p95 < 800 ms per step, p99 < 2 s end-to-end
- [x] **Admin dashboard load** — 20 concurrent admin sessions polling the
  dashboard; target: p95 < 300 ms
- [x] **Status page load** — 100 concurrent requests to `/status` with valid
  credentials; target: p95 < 200 ms
- [x] **Performance CI job** — `.github/workflows/perf.yml`; manual dispatch;
  runs `locust --headless` in Docker Compose; uploads HTML + CSV artifacts
- [x] **Baseline documented** — `docs/performance-baseline.md` records SLO
  thresholds; future regressions measured against this

### API Contract Tests

- [x] **OpenAPI schema export** — `tests/test_openapi_contract.py` fetches
  `/openapi.json` and validates it is a valid OpenAPI 3.x document; asserts
  all expected operation IDs are present; catches accidental route renames
- [x] **Response schema validation** — asserts admin routes require auth (7
  routes tested for 3xx redirect on unauthenticated requests); validates
  response body structure for key endpoints
- [x] **Breaking-change detection** — `tests/fixtures/openapi_snapshot.json`
  persisted on first run; subsequent runs assert no paths removed; additions
  are allowed without failure

---

## v1.2.0 — Test Quality & CI Hardening

> Goal: close the gaps identified in the v1.1.0 test quality review.
> All items are improvements to the test infrastructure — no user-facing
> behaviour changes are planned for this milestone.

### E2E & Browser Coverage

- [ ] **Firefox smoke-test** — run the critical-path E2E subset (login,
  submission, status, session expiry) against Firefox via a second
  `pytest-playwright` job in `e2e.yml`; ensures no browser-specific regressions
- [ ] **Isolate reply tests from demo seed data** — `test_admin_reply_appears_in_thread`
  currently mutates the shared demo report `OW-DEMO-00002`; refactor to create a
  throwaway report (same pattern as `test_four_eyes_deletion.py`) so subsequent
  tests are not affected by leftover reply messages
- [ ] **Replace silent skips with explicit failures** — tests that `pytest.skip`
  when critical demo data is missing (e.g., `OW-DEMO-00002 not found`) should
  `pytest.fail` instead, so a broken demo seed surfaces as a test failure rather
  than a misleading "skipped" result

### Accessibility

- [ ] **Deduplicate axe-core injection** — `run_axe` and `run_axe_warnings` each
  call `page.add_script_tag`; the second call is a no-op but adds noise; refactor
  `_check_axe` to inject once and run both filter passes in a single `page.evaluate`
  call
- [ ] **Promote color-contrast to blocking** — fix the remaining `color-contrast`
  CSS violations flagged as "serious" by axe-core (footer link text, secondary
  badge text) and promote the check from warning to CI-blocking

### Performance

- [ ] **Automatic performance regression gate** — add a `--csv` output pass to
  the Locust run and a post-run Python script that reads the CSV and exits non-zero
  if p95 exceeds the SLO thresholds from `docs/performance-baseline.md`; wire
  into `perf.yml` so the workflow fails on regression
- [ ] **Complete wizard flow in `WhistleblowerUser`** — the Locust user class
  currently issues a simplified POST; replace with a full 6-step session
  (mode → category → description → review → submit) to measure realistic
  end-to-end latency including Redis session reads

### API Contract & Unit Tests

- [ ] **Remove version-string unit test** — `test_app_version_current` in
  `tests/test_v100.py` breaks at every release and provides no safety net;
  remove it; the version is already exercised by the `/health` endpoint test
  which asserts the response body contains a valid semver string
- [ ] **OpenAPI contract via FastAPI `test_client`** — OpenAPI is disabled in
  production (`openapi_url=None`) but can be enabled in the test app factory;
  add a `conftest.py` fixture that creates a second `TestClient` with OpenAPI
  enabled and assert all expected route `operationId`s are present, catching
  accidental route renames without exposing the schema in production

---

## v1.3.0 — Privacy Hardening & Attachment Security

> Uploaded files can carry EXIF and document metadata that inadvertently
> identifies the whistleblower (GPS coordinates, author names, printer serial
> numbers). Malware inside attachments is a real attack surface for internal
> case-management staff. This milestone closes those gaps and adds key-escrow
> encryption for organisations that need to recover data under legal compulsion
> without storing the main encryption key on the server.

### Attachment Privacy & Security

- [ ] **Metadata stripping on upload** — strip all EXIF, XMP, IPTC, and Office
  document metadata (author, device, GPS, revision history) from every uploaded
  file before storage; use `exiftool` or `python-exiftool` wrapped in
  `asyncio.to_thread`; original file is discarded, only the stripped version is
  stored; no metadata ever reaches the admin or is stored in the database
- [ ] **Virus scanning of attachments** — integrate ClamAV (open-source) as an
  optional scanning backend (`CLAMAV_ENABLED=true`, `CLAMAV_HOST`, `CLAMAV_PORT`);
  files are scanned before storage; infected files are rejected with a clear
  error message; scan result recorded in the attachment audit log; falls back
  to accept-without-scan when ClamAV is unavailable (configurable behaviour)
- [ ] **File type allowlist enforcement** — server-side MIME-type validation
  (not just extension check) using `python-magic`; configurable allowlist via
  `ALLOWED_MIME_TYPES` env var; rejects executables, scripts, and archive
  formats by default

### Encryption Key Control

- [ ] **Bring Your Own Key (BYOK) / key escrow** — optional mode where the
  operator provides a separate `ENCRYPTION_KEY` env var to wrap the MEK instead
  of deriving it from `SECRET_KEY`; documented pattern for operators who want
  the encryption key stored outside the deployment environment (e.g., in a
  hardware security module or a separate secrets manager); no SaaS provider
  (including the operator's own Docker host) can decrypt reports without the
  external key; `BYOK_ENABLED=true` env var activates key rotation warnings in
  the admin UI

### Access Control

- [ ] **IP allowlist for admin routes** — `ADMIN_IP_ALLOWLIST` env var accepts
  CIDR notation (`192.168.1.0/24,10.0.0.0/8`); requests from outside the list
  receive 403; empty/unset means no restriction (backward-compatible default);
  implemented as FastAPI middleware before route resolution; respects
  `TRUSTED_PROXY_DEPTH` for correct IP extraction behind load balancers

---

## v1.4.0 — Advanced Case Management

> Features derived from Hintbox, Formalize/WBS, and whistle.law competitive
> analysis. These address workflows that compliance officers and case managers
> in larger organizations consistently need but are missing from OpenWhistle.

### Case Handling Workflow

- [ ] **Case redaction** — admin can redact (replace with `[REDACTED]`) any
  text passage in a report description or message before sharing the case with
  an external party; redaction is recorded in the audit log; original content
  is preserved in an encrypted redaction-log visible only to superadmin
- [ ] **Case anonymization / pseudonymization** — one-click action to replace
  all personal identifiers in a case with placeholders (name → `[Person A]`,
  etc.); designed for sharing with external auditors or regulatory bodies;
  creates a copy of the case content — does not overwrite the original
- [ ] **Per-case internal task management** — tasks (description, assignee,
  due date, status: open / in progress / done) attached to a specific report;
  visible only to the admin team; deadline for tasks tracked separately from
  the HinSchG statutory deadlines; `AdminTask` model with `report_id`,
  `assigned_to_id`, `due_date`, `completed_at`
- [ ] **Case-level access control** — ability to restrict specific cases to a
  named subset of admin users (in addition to global role-based access);
  useful for particularly sensitive reports where need-to-know should be
  limited; `CaseRestriction` model linking `report_id` to a set of allowed
  `admin_user_id`s; users outside the set see the case number in the dashboard
  but cannot open the detail view

### External Collaboration

- [ ] **External advisor access** — scoped, time-limited guest accounts for
  external parties (law firms, auditors, external ombudspersons); `ExternalAdvisor`
  model with `email`, `access_token` (GUID), `expires_at`, `allowed_report_ids[]`;
  access via a separate URL (`/advisor/{token}`) without a full admin login;
  activity logged in the audit trail; advisor can read case content and post
  internal notes but cannot change status or delete; access revocable instantly
- [ ] **Communication templates** — pre-defined message templates that admins
  can insert when replying to whistleblowers or sending notifications; templates
  stored per organization (multi-tenant aware); helps maintain consistent,
  legally reviewed language across case handlers; `MessageTemplate` model with
  `title`, `body_de`, `body_en`, `body_fr`

### Reporting & Transparency

- [ ] **Transparency report generation** — one-click annual compliance report
  (PDF + JSON) showing: total reports received, reports by category, reports by
  status at year-end, average processing time, SLA compliance rate, percentage
  closed within statutory deadlines; required by HinSchG §12 Abs. 3 for
  internal documentation; downloadable from `/admin/stats`
- [ ] **Whistleblower sees handler department** — the status page shows the
  department/category label of the case handler team (not the handler's name);
  provides transparency without de-anonymizing internal staff; configurable
  per-organization (`SHOW_HANDLER_DEPARTMENT=true`)

---

## v1.5.0 — Multi-Channel Intake & Integration Hooks

> Operators increasingly need to receive reports through channels beyond the web
> form, and connect OpenWhistle to existing compliance tooling (SIEM, GRC
> platforms, ticketing systems) without granting those systems access to sensitive
> case content. This release adds intake flexibility and privacy-safe integration
> points.

### Additional Submission Channels

- [ ] **Email intake channel** — inbound email forwarded to a configured mailbox
  (`INTAKE_EMAIL_ADDRESS`) is parsed by a background job and converted to a
  pending report; attachments are extracted and stored; a case number + PIN is
  sent back to the sender only if the sender provided a return address (anonymous
  senders receive no reply); admin can configure per-organization intake addresses
  in multi-tenant deployments; uses `aiosmtplib` or IMAP polling
- [ ] **Voice recording channel** — whistleblowers can record a voice message
  directly in the browser (Web Audio API, MediaRecorder) and submit it as an
  attachment; stored as an `.ogg` or `.webm` file; admins can play it back in
  the case detail view; optional **voice-pitch shifting** (configurable via
  `VOICE_DISTORTION_ENABLED=true`) applies a simple frequency shift to prevent
  speaker identification while keeping the content intelligible; processing done
  server-side via `ffmpeg`

### Integration Hooks

- [ ] **Admin management API** — scoped REST API for administrative operations
  that contain no sensitive report content: user management (create/disable
  accounts), category and location management, system health; JWT Bearer token
  authentication with scoped API keys (`api_keys` table: `key_hash`, `scopes[]`,
  `expires_at`); API keys managed from the admin settings page; OpenAPI spec at
  `/api/v1/openapi.json`; rate-limited per key; designed to allow GRC/ITSM tools
  to provision OpenWhistle without admin UI access — **no case content, no
  whistleblower-identifying data exposed via API**
- [ ] **Aggregate statistics API** — read-only endpoint returning anonymised
  counts (reports per period, per category, per status); suitable for feeding
  compliance dashboards; no individual case data
- [ ] **Outbound webhooks** — push notifications for case lifecycle events
  (`report.created`, `report.status_changed`, `report.reply_added`,
  `report.deleted`); payload contains only event type, case number, new status,
  and timestamp — no message content, no attachments, no metadata that could
  identify the whistleblower; configurable per event type; signed JSON envelope
  (HMAC-SHA256 in `X-OpenWhistle-Signature`); retried up to 3× with exponential
  back-off; delivery log in admin UI; `WebhookEndpoint` model with `url`,
  `secret`, `enabled_events[]`, `last_delivery_at`, `last_status_code`
- [ ] **Zapier / n8n integration guide** — `docs/integrations/` with documented
  examples connecting OpenWhistle webhooks to Zapier, n8n, and Make; no code
  changes required; purely documentation but significantly increases integration
  reach for non-technical operators

---

## v1.6.0 — Compliance Expansion (LkSG, KWG, CSRD)

> German compliance obligations extend beyond HinSchG. Companies in scope for
> the Lieferkettengesetz (LkSG, since 2023) require a separate supply-chain
> reporting channel; financial institutions need a KWG-compliant pathway; listed
> companies increasingly face CSRD disclosure requirements that reference internal
> reporting systems. These are add-on modules that don't change the core
> whistleblower flow.

### Supply Chain Due Diligence (LkSG)

- [ ] **LkSG reporting channel** — dedicated submission form variant for supply
  chain violations (§2 LkSG violation categories pre-configured as categories:
  forced labour, child labour, environmental violations, discrimination,
  excessive working hours, etc.); separate from the HinSchG channel; reports
  routed to a configurable LkSG case manager role; LkSG-specific deadline
  tracking (§12 LkSG: receipt confirmed within 7 days; decision within 3 months;
  extension to 6 months documented); `LKSG_ENABLED=true` env var activates the
  module
- [ ] **LkSG transparency report** — structured annual report template as required
  by §12 Abs. 4 LkSG (public disclosure of complaints received, investigations
  conducted, measures taken); downloadable PDF; `LKSG_TRANSPARENCY_YEAR` config

### Financial Sector (KWG / MaRisk)

- [ ] **KWG / MaRisk whistleblowing channel** — separate category set pre-configured
  for banking-regulatory violations (§25a KWG, MaRisk AT 8.5: reporting channel
  for employees to report risk management violations, fraud, AML breaches);
  routed to Compliance/Audit role; `KWG_ENABLED=true` env var; dedicated section
  in the admin nav

### Sustainability Reporting (CSRD)

- [ ] **CSRD / ESG grievance channel** — intake form for ESG-related reports
  (environmental impact, human rights, social violations) as required by the
  Corporate Sustainability Reporting Directive (CSRD) for large companies from
  2025; categorised by ESRS topic; routes to ESG officer role;
  `CSRD_ENABLED=true` env var

### Compliance Documentation

- [ ] **ISO 37002 alignment documentation** — `docs/iso37002.md` mapping every
  ISO 37002:2021 clause to the corresponding OpenWhistle feature or config
  option; provides operators with a ready-made compliance justification for
  auditors; updated per release
- [ ] **30-language support** — extend i18n from 3 (EN, DE, FR) to 30 languages
  covering all official EU languages (ES, IT, PL, NL, PT, SV, DA, FI, CS, SK,
  HU, RO, BG, HR, SL, ET, LV, LT, MT, GA, EL, and formal/informal variants for
  DE/AT/CH); machine-translated initial pass reviewed by native speakers via
  community contributions; all translation files in `app/locales/{lang}.json`
  following the existing 388-key schema

---

## SEO & Marketing (ongoing, all versions)

> Goal: rank for "Whistleblower Tool kostenlos", "Whistleblower Tool Open Source",
> "Meldestelle HinSchG kostenlos", "interne Meldestelle Software" and equivalents
> in other EU languages. The `openwhistle.net` domain has been registered for
> ~1 year, which gives a head start on domain authority.

### Technical SEO

- [x] **GitHub Pages website overhaul** — `docs/index.html` is a full landing
  page with hero section, feature comparison table (vs. paid tools), FAQ,
  installation guide, and a "live demo" CTA
- [x] **Structured data (JSON-LD)** — `SoftwareApplication` and `FAQPage`
  schema markup on the landing page; `Article` and `HowTo` schema on blog posts
- [x] **German-language landing page** — `docs/de/index.html` with fully German
  content targeting HinSchG-specific long-tail keywords (`interne Meldestelle
  HinSchG`, `Hinweisgebersystem kostenlos`, `Meldestelle Software Open Source`)
- [x] **Open Graph & Twitter Card meta tags** — `og:title`, `og:description`,
  `og:image` on `index.html`, `de/index.html`, and all blog articles
- [x] **Sitemap** — `docs/sitemap.xml` updated with all pages including
  `de/`, `blog/`, and all blog articles; `robots.txt` already present
- [x] **Canonical URLs** — `<link rel="canonical">` on all pages;
  CNAME file sets `openwhistle.net` as the canonical domain for GitHub Pages
- [x] **hreflang alternate links** — `en`/`de` alternate links in `index.html`
  and `de/index.html` sitemap entries for language-based ranking

### Content SEO

- [x] **Blog / news section** — `docs/blog/` with three articles:
  - `hinschg-compliance-leitfaden.html` — HinSchG compliance guide (10 min read)
  - `whistleblower-software-vergleich.html` — comparison vs. EQS, BKMS, WhistlePort
  - `interne-meldestelle-einrichten.html` — step-by-step installation guide
- [ ] **Additional "vs. competitors" pages** — dedicated comparison pages
  targeting navigational searches ("OpenWhistle vs. EQS", etc.)
- [ ] **Keyword research & tracking** — document target keywords, current
  rankings, and monthly search volume in a spreadsheet; track progress
- [ ] **Backlink outreach** — submit to open-source directories (AlternativeTo,
  SourceForge, LibreHunt), legal-tech directories, and HinSchG resource lists
  maintained by German law firms and compliance associations
- [x] **GitHub README keywords** — README contains keywords `whistleblower`,
  `HinSchG`, `Hinweisgeberschutz`, `Meldestelle`, `compliance`, `open-source`
  that GitHub search indexes; alpha warning removed for v1.0.0

### Community & Distribution

- [ ] **Producthunt launch** — prepare a Product Hunt launch post; coordinate
  with the community for upvotes on launch day
- [ ] **Hacker News "Show HN"** — post once v1.0 is reached
- [ ] **German compliance / legal community** — share in DACH-focused compliance
  Slack/Discord servers, LinkedIn groups for compliance officers and legal teams
- [ ] **"Powered by OpenWhistle" badge** — optional badge operators can put on
  their reporting portal, linking back to openwhistle.net (backlink building)

---

## Completed

- [x] Whistleblower report submission with category and description (v0.1.0)
- [x] Two-factor whistleblower access: case number + UUID4 PIN (v0.1.0)
- [x] Bidirectional communication thread (v0.1.0)
- [x] First-run setup wizard with TOTP enrollment (v0.1.0)
- [x] Mandatory TOTP MFA for all admin accounts (v0.1.0)
- [x] Optional OIDC login (v0.1.0)
- [x] HinSchG SLA tracking: 7-day and 3-month deadlines (v0.1.0)
- [x] Full IP anonymity: no logging anywhere in the stack (v0.1.0)
- [x] Redis-based brute-force protection without IP tracking (v0.1.0)
- [x] Hard deletion of reports (GDPR Art. 17) (v0.1.0)
- [x] Demo mode with seed data (v0.1.0)
- [x] Security headers, CSP, HSTS (v0.1.0)
- [x] Multi-registry Docker publishing (ghcr.io, Docker Hub, quay.io) (v0.1.0)
- [x] Image signing with Cosign (v0.1.0)
- [x] Admin session expiry warning with one-click extend (v0.2.0)
- [x] Admin dashboard pagination, sorting, and status filtering (v0.2.0)
- [x] File attachments for evidence (v0.2.0)
- [x] Email and webhook notifications on new report (v0.2.0)
- [x] CSRF Double-Submit Cookie on all POST endpoints (v0.2.0)
- [x] Password reset management script (v0.2.0)
- [x] Company branding (colours, logo) via environment variables (v0.2.0)
- [x] Complete UI redesign (v0.2.0)
- [x] GitHub Pages website (v0.2.0)
- [x] Edge Docker tag for every main-branch push (v0.2.0)
- [x] Case number uses MAX to prevent reuse after deletion (v0.2.1)
- [x] 10 CodeQL code scanning alerts resolved (v0.2.0 + v0.2.1)
- [x] Multiple admin users with roles (ADMIN / CASE_MANAGER) (v0.3.0)
- [x] Case assignment with "My Cases" dashboard filter (v0.3.0)
- [x] Custom DB-driven report categories (v0.3.0)
- [x] Case linking between related reports (v0.3.0)
- [x] 4-eyes principle for hard deletion (v0.3.0)
- [x] Internal admin notes (never shown to whistleblower) (v0.3.0)
- [x] Status workflow: received → in_review → pending_feedback → closed (v0.3.0)
- [x] Immutable audit log with 18 action types + CSV export (v0.3.0)
- [x] PDF export of full case report (v0.3.0)
- [x] Dashboard statistics with SLA compliance rate (v0.3.0)
- [x] Multi-step submission wizard with Redis session state (v0.4.0)
- [x] Anonymous vs. confidential submission mode with Fernet encryption (v0.4.0)
- [x] Multi-location / branch selection for whistleblower submissions (v0.4.0)
- [x] Optional encrypted secure contact email for reply notifications (v0.4.0)
- [x] HinSchG deadline display (7-day + 3-month) on whistleblower status page (v0.4.0)
- [x] Full German i18n (388 keys) and French language addition (v0.4.0)
- [x] WCAG 2.1 AA accessibility pass: ARIA, focus indicators, skip link (v0.4.0)
- [x] Health-check endpoint v2: DB + Redis components in /health (v0.5.0)
- [x] Structured JSON logging via LOG_LEVEL / LOG_FORMAT env vars (v0.5.0)
- [x] Slack / Teams webhook payload formatters (v0.5.0)
- [x] SLA reminder system with APScheduler + Redis dedup (v0.5.0)
- [x] S3-compatible attachment storage backend (v0.5.0)
- [x] LDAP / Active Directory login for admin accounts (v0.5.0)
- [x] Official Helm chart for Kubernetes deployments (v0.5.0)
- [x] Official Ansible role for bare-metal / VM deployments (v0.5.0)
