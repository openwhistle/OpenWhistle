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

## v0.5.0 — Notifications, Integrations & Reliability

> Target: production-grade operations

### Notifications

- [ ] **Follow-up / reminder system** — configurable automatic reminders when
  SLA deadlines approach (7-day acknowledgement, 3-month feedback); sent via
  e-mail or webhook to assigned admin
- [ ] **Whistleblower reply notification** — if the whistleblower provided a
  secure contact, notify them when the admin posts a new message
- [ ] **Slack / Teams webhook** — pre-built webhook payload formatter for Slack
  and Microsoft Teams so no custom integration work is needed by the operator

### Integrations

- [ ] **S3-compatible attachment storage** — optional external object storage
  (AWS S3, MinIO, Hetzner Object Storage) for attachments instead of database
  BLOBs; required for large-scale deployments
- [ ] **LDAP / Active Directory login** — admin accounts can authenticate via
  corporate LDAP in addition to local credentials and OIDC

### Reliability & Operations

- [ ] **Health-check endpoint v2** — expose database and Redis connectivity in
  `/health`; suitable for Kubernetes liveness and readiness probes
- [ ] **Structured JSON logging** — replace plain-text logs with structured JSON
  (timestamp, level, request ID, path) for log aggregation pipelines
- [ ] **Helm chart** — official Helm chart for Kubernetes deployments; published
  to GitHub Pages as a Helm repository
- [ ] **Ansible role** — official Ansible role for bare-metal / VM deployments
  (currently Hetzner demo uses a private playbook)

---

## v1.0.0 — Production-Ready & Compliance-Complete

> Target: stable, fully HinSchG/EU-compliant, suitable for enterprise use

- [ ] **Telephone reporting channel stub** — guidance in the admin UI for
  setting up a compliant telephone hotline (HinSchG §16 Abs. 1 Nr. 2); links
  to documentation on how to pair a phone channel with OpenWhistle case numbers
- [ ] **Encrypted report storage** — encrypt report description and messages
  at-rest using a key that is not stored in the database (envelope encryption);
  admin UI derives the decryption key from admin credentials at login time
- [ ] **Data-retention policy** — configurable automatic deletion of reports
  after a configurable period (e.g. 3 years); GDPR Art. 5 compliance;
  scheduled background task with audit log entry
- [ ] **Multi-tenancy** — single deployment serves multiple independent
  organisations (separate data namespaces, per-tenant branding, per-tenant
  admin users); primary use case: managed hosting for multiple SMEs
- [ ] **SOC 2 / ISO 27001 documentation pack** — security policy templates,
  data processing agreements (DPA), and evidence artefacts operators can use
  for their own compliance audits

---

## SEO & Marketing (ongoing, all versions)

> Goal: rank for "Whistleblower Tool kostenlos", "Whistleblower Tool Open Source",
> "Meldestelle HinSchG kostenlos", "interne Meldestelle Software" and equivalents
> in other EU languages. The `openwhistle.net` domain has been registered for
> ~1 year, which gives a head start on domain authority.

### Technical SEO

- [ ] **GitHub Pages website overhaul** — transform `docs/index.html` into a
  full landing page with: hero section, feature comparison table (vs. paid
  tools), installation guide, FAQ, and a "live demo" CTA
- [ ] **Structured data (JSON-LD)** — add `SoftwareApplication` and
  `FAQPage` schema markup to the landing page for rich snippets
- [ ] **German-language landing page** — `/de/` path on openwhistle.net with
  fully German content targeting HinSchG-specific long-tail keywords
- [ ] **Open Graph & Twitter Card meta tags** — `og:title`, `og:description`,
  `og:image` on every docs page; generate a proper `og:image` (1200×630 px)
- [ ] **Sitemap & robots.txt** — auto-generated `sitemap.xml` and `robots.txt`
  served from GitHub Pages
- [ ] **Canonical URLs** — ensure `openwhistle.net` is the canonical domain;
  redirect `www.` and any alternative hostnames

### Content SEO

- [ ] **Blog / news section** — publish articles on HinSchG compliance
  requirements, how to set up an internal reporting channel, comparisons with
  commercial tools; each article is an SEO entry point
- [ ] **"vs. competitors" pages** — dedicated comparison pages
  (e.g. "OpenWhistle vs. WhistlePort") targeting navigational searches
- [ ] **Keyword research & tracking** — document target keywords, current
  rankings, and monthly search volume in a spreadsheet; track progress
- [ ] **Backlink outreach** — submit to open-source directories (AlternativeTo,
  SourceForge, LibreHunt), legal-tech directories, and HinSchG resource lists
  maintained by German law firms and compliance associations
- [ ] **GitHub README badges & SEO** — ensure the README uses the right
  keywords that GitHub search indexes (`whistleblower`, `HinSchG`, `EU-Richtlinie`,
  `Meldestelle`, `compliance`, `open-source`)

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
