# OpenWhistle Roadmap

This document tracks planned features, improvements, and long-term goals.
Items are grouped by release milestone. Priorities can shift based on community
feedback — open an issue to discuss anything here.

---

## v0.3.0 — Multi-User Admin & Custom Categories

> Target: first major feature release beyond compliance baseline

### Admin & Case Management

- [ ] **Multiple admin users with roles** — currently all admins are equal; add
  `ADMIN` and `CASE_MANAGER` roles so organisations can restrict who can delete
  reports or access sensitive details
- [ ] **Case assignment** — assign an incoming report to a specific admin user;
  assigned user receives a notification; dashboard shows "My cases" filter
- [ ] **Custom report categories** — admins can define their own categories via
  the admin UI (currently hardcoded enum); includes the standard set
  (financial fraud, harassment, data protection, supply chain / LkSG, etc.)
  plus free-text custom entries
- [ ] **Case linking** — link two reports submitted by the same whistleblower
  (de-duplication); linked cases are visible in each report's detail view
- [ ] **4-eyes principle for hard deletion** — a delete request by one admin
  must be confirmed by a second admin before the report is permanently removed
- [ ] **Internal notes** — admins can add private notes to a report that are
  never visible to the whistleblower
- [ ] **Report status workflow** — extend statuses: `received → in_review →
  pending_feedback → closed`; each transition logged in the audit log

### Audit Log

- [ ] **Immutable audit log** — record every admin action (status change,
  assignment, deletion request, note added, message sent) with timestamp and
  username; required for HinSchG traceability (§12 Abs. 3)
- [ ] **Audit log export** — CSV / PDF download for compliance reviews

### Export & Reporting

- [ ] **PDF export** — generate a structured PDF of a full report (all messages,
  metadata, SLA status, attachments list) for offline filing or handover to
  legal counsel
- [ ] **Dashboard statistics** — aggregate view: reports per category, average
  response time, SLA compliance rate

---

## v0.4.0 — Whistleblower UX & Multi-Step Form

> Target: match and exceed commercial tool UX

### Whistleblower Experience

- [ ] **Multi-step submission form** — break the single-page form into guided
  steps (category → details → attachments → review → confirmation); progress
  indicator; back/next navigation; server-side session keeps state between steps
- [ ] **Anonymous vs. confidential mode** — let the whistleblower choose at the
  start whether to submit anonymously or provide contact details voluntarily;
  confidential mode stores name/contact encrypted and only accessible to
  assigned admin
- [ ] **Multi-location / branch selection** — organisations with multiple sites
  can configure locations; whistleblower selects the relevant location during
  submission; admins can filter by location
- [ ] **Optional secure contact method** — whistleblower may provide an external
  anonymous e-mail (e.g. ProtonMail) for reply notifications; address is
  stored encrypted, used only to send "you have a new reply" without revealing
  report content; never logged
- [ ] **Deadline display for whistleblower** — show the HinSchG acknowledgement
  deadline (7 days) and feedback deadline (3 months) on the status page so the
  whistleblower knows when to expect a response

### Accessibility & Internationalisation

- [ ] **Full German i18n** — translate all remaining hardcoded English strings
  in templates and error responses to German; make all user-facing text go
  through the translation system
- [ ] **Third language (French or Polish)** — add a third language to broaden
  EU reach; locale picker in UI
- [ ] **WCAG 2.1 AA audit** — full accessibility pass: keyboard navigation,
  screen reader labels, colour contrast ratio ≥ 4.5:1, focus indicators

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
