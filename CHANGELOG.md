# Changelog

All notable changes to OpenWhistle are documented in this file.

The format follows [Keep a Changelog](https://keepachangelog.com/en/1.0.0/).
This project uses [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Fixed

- **Pages that fit the window scrolled anyway, with the footer below the fold.** The submission
  wizard and the login and MFA screens sized themselves as the viewport minus a guessed nav and
  footer height (144 or 112 px, against a real 151 px, plus the 36 px demo banner). They now
  fill the space between nav and footer by flexbox, whatever those measure.

## [2.0.0] — 2026-09-26

A major version: the webhook payload, the Compose TLS/port
layout and the first-run setup flow all break compatibility with 1.5.x — see
Changed (breaking) below and the upgrade notes before deploying.

### Upgrade notes

- **LDAP with a private CA reads `LDAPTLS_CACERT`** (or `LDAPTLS_CACERTDIR`).
  `SSL_CERT_FILE` is ignored for LDAPS and StartTLS: point `LDAPTLS_CACERT`
  at the CA's PEM file.
- **LDAP uses python-ldap** (the OpenLDAP client) instead of ldap3, which has
  had no release since 2021.
- **LDAP and S3 are optional extras** (`ldap`, `s3`). The container image
  includes both; installing from source needs `pip install '.[ldap,s3]'` and
  `libldap2-dev libsasl2-dev`.
- **A fresh install needs the setup token.** `/setup` asks for a one-time token: set
  `SETUP_TOKEN` (32+ characters; the app refuses to start with a shorter one), or read the
  random one the app logs once at WARNING on its first start. After `MAX_LOGIN_ATTEMPTS` wrong
  tokens, `/setup` refuses every token for `LOGIN_LOCKOUT_MINUTES`. An existing installation
  is not affected.
- **Setting `ENCRYPTION_KEY` on an existing install needs `ENCRYPTION_KEY_PREVIOUS`.**
  Existing data is under `SECRET_KEY`: set `ENCRYPTION_KEY=<new>` together with
  `ENCRYPTION_KEY_PREVIOUS=<your SECRET_KEY>`, recreate the container, then run
  `scripts/rotate_encryption_key.py`. The app now refuses to start, before migrating, when
  neither key opens a stored report key or TOTP secret (also when `ENCRYPTION_KEY` is
  removed again).
- **New-report and reply notices arrive once a day** (00:00 UTC) unless
  `NOTIFICATION_BATCH_MINUTES` is set; the default was 60.
- **Admin sessions end 12 hours after login** (`SESSION_MAX_HOURS`), however often "Stay
  signed in" is used; then password and TOTP again.
- **Upgrading the Compose stack needs `git pull`**, not only `docker compose pull`: it needs
  the new `nginx/snippets/` and the `tls-init` service. A customised `nginx/nginx.conf` makes
  the pull conflict; replace it with the shipped one.
- **The Compose stack listens on 443** and only redirects on 80 (see Added). Copy your
  certificate into `nginx/certs/` (`fullchain.pem`, `privkey.pem`; no symlinks, key root-owned
  0600 or 0644): the old `./nginx/certs:/etc/nginx/certs` mount is gone. Without one, a
  self-signed certificate is served.
- **Behind an external TLS terminator** (Cloudflare, Traefik, a host nginx), point it at
  `https://…:443`, or add `docker-compose.behind-proxy.yml`, which proxies plain HTTP on 80 and
  publishes no 443. Aimed at the new port 80, the terminator loops on the redirect.
- **nginx publishes `127.0.0.1:8080`** (the onion listener). If the host already uses 8080,
  `docker compose up` fails: free the port first.
- **Back up before upgrading; the rollback changed.** The 1.5.0 image refuses the migrated
  schema. Restore the backup, or run `alembic downgrade 7d4e2b9c1a05` with the 2.0.0 image
  (`docker compose run --rm app alembic downgrade 7d4e2b9c1a05`) before pinning 1.5.0. The
  downgrade keeps the day-rounded times of migration 006: the exact times are gone by design.
- **`BRAND_SECONDARY_COLOR` is ignored** with a warning at startup; delete it from `.env`.
- **Webhooks carry counts only, never case numbers or deadlines**; update receivers that parsed
  the old fields. The SLA reminder is one webhook per scheduler run, not one per case.
  - Generic reminder: `case_number`, `deadline`, `days_left` and `timestamp` are gone;
    `ack_due`, `feedback_due` and `message` are new.
  - Generic digest: `new_reports`/`new_messages` are counts, not arrays of case numbers, plus
    `message`.
  - Slack: the `fields` block is one `text` block. Teams: the reminder's `FactSet` is a
    `TextBlock`, and the digest has one "Activity" fact instead of case numbers.
  - The reminder email is unchanged: it still carries the case number, since only your own
    admins receive it.
- **`docker-compose.prod.yml` pins the image** to `${OPENWHISTLE_VERSION:-2.0.0}` instead of
  `:latest`; set `OPENWHISTLE_VERSION` to upgrade.
- Migrations 004–006 run at start: TOTP secrets are encrypted, audit rows get their
  organisation, whistleblower times are rounded to the day (not reversible).

### Security

- **Switching the language needs the CSRF token** (`POST /set-language`), like every other
  form: another site can no longer change a visitor's language cookie.
- **Categories and locations stay inside their organisation.** With multi-tenancy on, an org
  admin saw every organisation's categories and locations and could deactivate or reactivate
  them by id; now the lists are scoped and another organisation's id answers 404. A slug or
  code is unique per organisation (a shared slug no longer caused a 500), new ones are created
  in the admin's own organisation, and deactivating or reactivating a location is audited.
  Creating a category or location commits in one transaction with its audit row.
- **The first-run setup page belonged to whoever opened it first.** `/setup` now needs a
  one-time setup token (`SETUP_TOKEN`, or a random token logged once at start), deleted when
  the first admin exists. Wrong tokens are rate-limited (`MAX_LOGIN_ATTEMPTS` per
  `LOGIN_LOCKOUT_MINUTES`, counted per instance), and an operator-set token needs 32
  characters.
- **TOTP secrets are encrypted at rest** (migration 004): a database dump no longer yields the
  second factor of every account.
- **Admin sessions have an absolute lifetime** (`SESSION_MAX_HOURS`, default 12). "Stay signed
  in" renews the token up to that limit, never past it, and the renewal needs the CSRF header.
- **A deactivated account gets neither the TOTP step nor a session**, on every login path
  (password, LDAP, OIDC, first TOTP setup).
- **An unknown role is refused with 422** when creating a user or changing a role (it used to
  create an *admin*); the role picker defaults to case manager.
- Only admins may dismiss the IP-header warning.
- **Audit entries carry their organisation** (migration 005 backfills existing rows), so an
  organisation's audit log shows its own entries and no one else's; an admin without an
  organisation sees only entries they wrote. A superadmin's action on a user, organisation,
  category or location is filed under the target's organisation, so its admins see it.
- **Containers are hardened**: read-only root file system, all capabilities dropped,
  `no-new-privileges`, base images pinned by digest, no `curl` in the image, uid 1000 to match
  the Helm chart's `securityContext` (`readOnlyRootFilesystem`, no privilege escalation).
- **LDAP refuses an empty password** (a simple bind with an empty password is an anonymous bind
  and succeeds), escapes the username in the search filter, demands a valid certificate with
  TLS 1.2 or later, and always closes its connections.
- CI runs `pip-audit` and Trivy on every pull request and weekly.

### Added

- **Per-organisation reporting link** (multi-tenancy). Each organisation's wizard is at
  `/submit/<org-slug>`: it offers only that organisation's categories and locations and files
  the report under it. `/submit` is the default organisation's; an unknown or deactivated slug
  is a 404, and there is no public list of organisations. With multi-tenancy on and
  `DEFAULT_ORG_SLUG` naming no active organisation, `/submit` answers 503 and a set-up instance
  refuses to start. The link, with a copy button, is on `/admin/organisations` and on an
  organisation admin's dashboard. With multi-tenancy off, nothing changes:
  `/submit/<default slug>` redirects to `/submit`, any other slug is a 404.
- **Tor onion address** (`ONION_LOCATION`, optional). Sends an `Onion-Location` header, so Tor
  Browser offers the switch, and shows the address on the submit page for reporters on a
  monitored network. nginx sets `X-OW-Onion` only on the onion listener and strips any
  client-sent copy; without `ONION_LOCATION` the app ignores the header.
- **Virus scan of uploads with ClamAV** (`CLAMAV_HOST`, `CLAMAV_PORT`,
  `CLAMAV_TIMEOUT_SECONDS`; optional `clamav` compose profile). Fail-closed: if `clamd` cannot
  be reached, the upload is refused, never stored unscanned.
- **Remove an attached file before submitting.** Attachments now stay attached when going
  back (see Fixed), so the attachments step has a Remove button for each file.
- **TLS by default in the shipped Compose stack.** The bundled nginx now serves HTTPS on 443 and
  redirects plain HTTP on 80 — nothing is proxied without TLS. A one-shot `tls-init` service
  generates a self-signed certificate for `TLS_HOSTNAME` (`.env`, default `localhost`) before
  nginx starts, so the stack comes up without any manual certificate step; drop your own
  `fullchain.pem`/`privkey.pem` into `nginx/certs/` and restart to use a real one instead. A
  certificate there that cannot be read, or is a symlink, stops `tls-init` with the path and
  the reason instead of falling back to self-signed.
- **`docker-compose.behind-proxy.yml`** for an install behind an external TLS terminator: nginx
  proxies plain HTTP on 80 and publishes no 443.
- **Voluntary installation count** (`TELEMETRY_ENABLED`, off by default). Only if an admin
  agrees — in the setup wizard (unchecked by default) or on `/admin/system`, no restart — one
  request a day: `GET https://telemetry.wdkro.de/v1/openwhistle/count?id=<32 hex>&v=<version>`,
  nothing else. The identifier is 16 random bytes made on the server and kept in the new
  `telemetry_state` table (migration 007); the System page shows the exact request and the
  identifier, the last success, a switch (one audit entry per change) and *Reset identifier*.
  An installation upgraded to 2.0.0 stays off until an admin switches it on. The first attempt
  waits a random part of an hour, a Redis lock lets one replica send, a failure is a debug
  line retried at the next hourly check, redirects are refused, the timeout is 10 s.
  `TELEMETRY_ENABLED=false` locks it off, `true` on; `DEMO_MODE` is never counted. The far end
  keeps timestamp, identifier and version, not the address, for 35 days. Every request the
  application can make is now listed in the docs under "Every request that leaves the host".
- **Helm `extraEnv`** sets any non-secret setting that `values.yaml` has no key for.
- **Separate, rotatable encryption key** (`ENCRYPTION_KEY`, optional). At-rest encryption is
  now rooted in `ENCRYPTION_KEY` instead of `SECRET_KEY`; unset falls back to `SECRET_KEY`
  (pre-v2.0.0 behaviour, warned at startup). `ENCRYPTION_KEY_PREVIOUS` keeps old keys readable
  during rotation, and `scripts/rotate_encryption_key.py` re-encrypts every DEK, confidential
  identity and contact, secure e-mail, TOTP secret and identity-reveal reason under the new key.
- **Maintainer tooling: local review login** (`LOCAL_REVIEW_LOGIN`, requires `DEMO_MODE=true`,
  `SECURE_COOKIES=false` and a loopback `APP_PUBLIC_URL`; set only by the
  `docker-compose.review.yml` override, never in a deployment). A one-click button on
  `/admin/login` signs a browser agent in as the seeded demo admin for the release's
  Chrome check. The route answers 404 for every method unless the flag is on, the request
  carries no proxy header and the `Host` is loopback. See `docs-tech/local-review.md`.

### Changed (breaking)

- `BRAND_SECONDARY_COLOR` is gone (see Removed); a `.env` that still sets it gets a warning.
- **Existing whistleblower times are rounded to the day** by migration 006, irreversibly (see
  Changed).
- `.doc` and `.xls` uploads are refused; their author field cannot be removed. The message tells
  the reporter to save as `.docx`/`.xlsx`.

### Privacy

- **The whistleblower's status session is no longer extended on every view**, so its remaining
  lifetime in Redis does not reveal the last visit; it ends 2 hours after login. Failed-attempt
  counters are keyed by an HMAC of the case number, not the case number itself.
- **Photos inside Word and Excel files lose their EXIF** (GPS, camera) on upload, like a photo
  uploaded on its own. **PDFs lose their comment authors and times**, the EXIF of embedded
  JPEG photos, and the file identifier that linked the upload to the original file.
- **Database errors no longer log their bound values.** Every engine (app, migrations, scripts)
  sets `hide_parameters`, so a failed query on `/status` or a reply no longer writes the case
  number or report id into the error log next to an exact time.
- **Notification digests are daily by default** (`NOTIFICATION_BATCH_MINUTES=1440`, was 60).
  Report times are stored as the day, and an hourly digest said which hour a report or reply
  arrived. Set a smaller value to hear sooner, at that precision.
- **The confidential identity is shown only to the handler, with an audited reason.** The case
  page no longer prints the reporter's name and contact: the assigned handler (for an
  unassigned case, an admin of the case's organisation) enters a 10–500 character reason, sees
  the identity once, and the reason is stored encrypted in the audit log. Every case view is
  audited too; the audit log hides views unless *Show case views* is ticked.
- **Search inside reports.** The dashboard search also finds words in descriptions and
  messages (three characters or more), decrypted in memory for that request only — no index is
  stored, the confidential name never matches, and at most the 5,000 newest cases in the
  current view are searched. The search is a POST form, so the term stays out of URLs and the
  browser history, and each word search is audited (`report.content_searched`, term encrypted,
  hit count).
- **The audit CSV export neutralises spreadsheet formulas** and writes each detail as one JSON
  cell, so a reason cannot forge extra fields.
- **Excel's own "Name:" label is removed from comment text** in `.xlsx` uploads, not only the
  comment's author field.
- **S3 objects stored before v1.5.0 are moved to keys without the filename** at start (once
  across replicas), and no log line or error message names a storage key.
- **PDF export leaves the confidential identity out** unless the handler gives an audited reason.
  The default export prints "Identity: [on file — not included]"; a new "Export PDF with identity"
  button asks for the same 10–500 character reason as the on-screen reveal and writes the same
  `IDENTITY_REVEALED` audit entry.
- **PDF export prints Latin, Greek and Cyrillic text intact.** DejaVu LGC Sans (bundled under
  `app/fonts/`) replaces fpdf2's core Helvetica, which silently turned anything outside latin-1
  into "?" — a report or message written in Polish, Greek or Cyrillic used to lose its own text in
  the printed record. CJK and right-to-left scripts are still unsupported (missing-glyph boxes).
- **A case manager's counts cover only their own cases.** The dashboard's status counts and the
  `/admin/stats` figures counted every case in the organisation, though the list showed only the
  cases assigned to them.

### Changed

- Dependencies refreshed (SQLAlchemy 2.1, uvicorn 0.54, boto3 1.43.103, ruff 0.16.9, uv 0.12.19);
  the SQLAlchemy mypy plugin, removed in 2.1, is no longer configured.
- **Helm: the Ingress rate-limits every route** like the bundled nginx (`limit-rps: "10"`,
  burst 30). Before, a Kubernetes deployment had no limit on `POST /submit` or any other
  public route. ingress-nginx answers a rejected request with 503 and keys on the peer address; the
  chart and its install notes now state that `error-log-level: crit` is required, since below
  it the controller logs each rejected reporter's IP address.
- **Times the whistleblower causes are stored and shown as the day only** (UTC): submission, the
  receipt message, whistleblower messages and attachment uploads. Migration 006 rounds existing
  rows; the exact times are gone for good (downgrade leaves the rounded values). Thread order is
  kept. Admin replies, notes, acknowledgement and closure keep their time, on screen and in the PDF.
  The 7-day acknowledgement deadline and the stats page's on-time rate now count from 00:00 UTC
  of the submission day. A same-day message keeps its place in the thread, one microsecond after
  the message before it. Demo data follows the same rule.
- The dashboard orders reports with equal submission days by id, so a page boundary is stable.
- **The dashboard has no KPI tiles**; each status filter pill carries its count, within the
  chosen location. The pills keep the location and search when switching status.
- **The case page has five panels**: Report (with its attachments), Communication thread,
  Notes, History (linked cases and the collapsed activity log) and Actions (acknowledge,
  assign, status, confidential identity, PDF export, and deletion collapsed under
  *Delete report*). The facts sit above Actions without panel chrome.

- **Website**: the German landing page and the blog are on the current design; every page
  shares one nav (collapsing below 1080 px) and one footer. The landing pages link each other
  with `hreflang`, and the German FAQ's structured data matches its visible questions.
  The unused Spectral and Source Serif fonts are removed.

### Fixed

- **A category deleted outright read differently on the PDF** (its raw slug) than on the
  pages (title-cased). One fallback now serves the templates, the stats page and the PDF.
- **Paging and sorting the dashboard dropped the location filter.** Every dashboard link now
  keeps the whole current view.
- **A case-number collision expired every object the caller held** (a full rollback), so the
  next attribute access failed with `MissingGreenlet`; each attempt now uses its own
  SAVEPOINT.
- Report creation retried on any database integrity error; it now retries only a case-number
  collision and raises any other error at once.
- Two messages posted to one case at the same moment could get the same time and an arbitrary
  order; the case row is now locked while a message's time is chosen.
- The case page's confirmation prompts, "(current)" status label and "no further transitions"
  note were English in every language; a French prompt showed `&#39;` for each apostrophe.
- **Organisations and admin-users pages were hardcoded English**, with button/badge classes
  (`btn--danger`, `badge--green`, ...) that don't exist in `site.css`. A sweep of every template
  found the same two problems on the retention, system, telephone-channel and category pages too
  (BEM-style classes that were never styled, a couple of untranslated titles and hints, a broken
  `field-error` CSS selector missing its leading dot). All now use real locale keys and the
  actual button/badge/grid class names.
- **Creating and deactivating organisations failed with a CSRF error.** The page posted
  `{{ csrf_token }}`, a context variable the route never sets, instead of
  `{{ request.state.csrf_token }}` — every real submission sent an empty token and got a 403.
- The dashboard's active filter pills all carried `aria-current="page"`, but two independent
  pill groups (status/my-cases and location) can each have an active pill at once — "page"
  implies a single current page. Filter pills now use `aria-current="true"`; pagination and
  navigation keep `"page"`.
- **The browser's own Back button broke the submission wizard halfway through** (a "Confirm Form
  Resubmission" dialog, or a stale step that rewound progress when resent). Every wizard step
  now answers its POST with a redirect to `GET /submit`, and a step that does not match the
  session's progress is ignored instead of processed. Found and fixed by Zachary Bridges; his
  #94 fix is ported into this release with him as co-author.
- **The wizard's Back button silently dropped uploaded attachments**: a file input is always
  empty on revisit, so Next from there cleared them. Files now stay attached unless new ones are
  chosen, and the attachments step lists what is already attached. Found and fixed by Zachary
  Bridges; his #94 fix is ported into this release with him as co-author.
- A description that failed validation (too short or too long) was discarded, and the step
  showed an empty field or the previous text. It now keeps what was typed (a too-long one cut at
  10,000 characters). Found and fixed by Zachary Bridges; his #94 fix is ported into this
  release with him as co-author.
- **A double final submit created two reports**: two concurrent POSTs of the review form
  (a double click with JavaScript off, e.g. Tor Browser "Safest") both read the draft before
  either deleted it, and the PIN of one report was never shown. Now the draft is claimed
  atomically, exactly one report is created, and both responses show its case number and PIN.
  A click that finds the first one still running says so and offers "Check again", never a
  receipt without a case number. The report and its attachments are committed together: a
  failure before the commit, or a worker that dies before it, gives the draft back; a commit
  whose reply was lost is looked up, never repeated. Each draft carries its report's id, so
  the database refuses a second report of the same draft whatever the timing or fault; a draft
  whose report exists is never given back, and the page then shows its case number. The race
  predates the #94 port: v1.5.0 has the same load → create → delete sequence.
- The final submit re-checks each step the way the step itself does: a location or category
  switched off, or confidential mode disabled, after the reporter chose it returns them to
  that step with a message instead of failing.
- The audit log sorted only by time, so entries with the same time could repeat or go missing
  between pages; ties are now broken by id, as the report list already does.
- **The wizard processed any posted step when `action` was neither `next` nor `back`**, so a
  crafted request could skip ahead (store a file on a fresh draft) or submit a rejected
  description. Unknown actions are now ignored, and the final submit re-checks every field
  before the report is created. The skip-ahead was already possible in v1.5.0.
- **Categories showed in English** on the dashboard, case page, stats and PDF export (the PDF
  printed the raw slug). They now use the admin's language, falling back to English, and a
  label comes only from the admin's own organisation.
- **A new admin user defaulted to `superadmin`**; the role picker now defaults to
  `case_manager`. `role.label.superadmin` had no translation and showed as the raw key.
- An icon next to text (SLA value, assignee, filename) rendered on its own line.
- Stylesheet and script URLs carried no version, and `/static/` had no `Cache-Control`, so a
  browser kept stale files after an upgrade. Links now carry `?v={app_version}`, and every
  `/static/` response is `no-cache` (the nginx snippet's conflicting `immutable` is gone).
- A long German status badge pushed the dashboard's "Ansehen" button out of view; the badge
  wraps and the action column stays pinned. The pinned header is chosen by class, so the audit
  log's last column no longer detaches from its data.
- `docs.html` and two blog articles overflowed horizontally on a phone (up to 519 px).
- The local-review login button sat flush against the demo-credentials box.
- **The PIN on the success screen was cut off.** A 36-character PIN or case number scrolled
  behind the copy button instead of fitting its box; it now wraps only after a hyphen (never
  inside a group) and is always fully visible, at every width, without scrolling.
- The review step's German label "EINREICHUNGSMODUS" overlapped its value "Anonym" (a fixed
  7rem label column, too narrow for the longest label in some locales); the review list now
  stacks each label over its value instead of sizing one column for every language.
- The description step's character counter always showed "10,000" regardless of language; a
  shared `format_count` helper (Python and JavaScript) now groups digits per locale
  ("10.000" in German and Portuguese, "10 000" in French).
- The wizard eyebrow said "CONFIDENTIAL REPORT" even in anonymous mode, clashing with
  "Anonymous" right below it; it is now a neutral "Secure report" in all four languages.
- `/admin/stats`'s two-column grid pushed "nach Kategorie" 23px below "nach Status": a
  stacking margin meant for panels in normal vertical flow was also firing inside the grid,
  on top of its own `gap`.
- A logged-in admin opening a stale `/admin/reports/<id>` got a raw JSON `{"detail":"Not
  Found"}` page. A browser request (`Accept: text/html`) to an HTML route now gets the
  styled, localised error page; an API/JSON client is unaffected.
- The "Was ist neu in 2.0" blog article was dated 25 September; the release is the 26th
  (visible date, meta tags, JSON-LD `datePublished`/`dateModified`, sitemap `lastmod`).
- **With multi-tenancy on, the wizard offered every organisation's categories and locations**,
  and every report was filed under the default organisation (since v1.4). A category or
  location of another organisation is now refused at its step and again at the final submit.
- The demo accounts belonged to no organisation, so with multi-tenancy on they saw none of the
  default organisation's demo reports; the seed now gives them the default organisation, also on
  an existing database.
- **`DEFAULT_ORG_SLUG` was ignored by setup and by the organisations page**: setup always
  created `default`, and only `default` was protected from deactivation. Both now use the
  configured slug.

### Design

- **Signal design across the app**: one admin shell with a role-aware sidebar (a case manager
  sees only the pages they may open) and a phone menu; SVG icons instead of emoji; an icon
  theme toggle; footer as a list; eyebrows only where they carry information; panel headers
  are real headings.
- **Phones**: the report form comes first, a case number or PIN never breaks across lines, and
  tables stack into labelled rows that keep their table semantics.
- The website describes 2.0 (English and German landing pages, the "Was ist neu in 2.0"
  article), serves every font it uses itself, and the roadmap moved from `ROADMAP.md` to
  [openwhistle.net/roadmap.html](https://openwhistle.net/roadmap.html).

### Process

- CI runs codespell, markdownlint and ruff over the whole repository, a runtime check of the
  nginx onion-listener trust boundary, and every GitHub Action is pinned by commit SHA.
- A test fails when a setting added since the previous release is missing from this
  changelog, or any setting from the documentation's environment table or
  `docker-compose.prod.yml` (seven were: `ACCESS_TOKEN_EXPIRE_MINUTES`, `ALGORITHM`, the four
  lockout settings and `APP_VERSION`/`APP_NAME`).
- Every new guard of this release is pinned by a mutation that turns its test red
  (`scripts/mutation_audit.py`).
- The docs pages' horizontal-overflow check ran in the light theme only; it now runs in dark
  too.

### Removed

- The PayPal link in `.github/FUNDING.yml`: the sponsor options are GitHub Sponsors and Ko-fi
  (`jp1337`), like the other projects; a test keeps personal payment handles out of the repository.
- `BRAND_SECONDARY_COLOR` — it styled nothing; Signal has one accent.

## [1.5.0] — 2026-09-24

Every finding carried forward from the 2026-09-23 audit is closed. The
guiding rule: a whistleblower can never be locked out, deanonymised by a file,
a timestamp or a Redis dump, or promised more than the software does. 124
mutations over this release's and v1.4.0's guards, all caught.

### Upgrade notes

- **Retention is on by default** (`RETENTION_ENABLED=true`): closed reports are
  deleted 1095 days after closing (HinSchG §11 Abs. 5). OpenWhistle dates from
  2026, so nothing is old enough to be deleted yet. Set `false` to opt out.
- **Notifications are batched** (`NOTIFICATION_BATCH_MINUTES=60`) and the
  generic webhook payload changed to
  `{"event": "new_activity", "new_reports": [...], "new_messages": [...]}` with
  no timestamp. Update receivers that parse the old `new_report` event. `0`
  restores immediate delivery.
- **Logout is a POST with a CSRF token**, for admins and whistleblowers; a GET
  no longer logs anyone out.
- **OIDC** now requires the provider to return an `id_token` (all compliant
  providers do); it is verified against the provider's JWKS.
- **Drafts in progress restart** after the upgrade (new encrypted draft format).
- **Redis** in `docker-compose.prod.yml` and the Ansible role now runs with
  `--maxmemory 1gb --maxmemory-policy noeviction`.
- Migration `003` encrypts existing attachment filenames and widens the column.
- New settings: `NOTIFICATION_BATCH_MINUTES`, `DRAFT_REDIS_MEMORY_PERCENT`,
  `ADMIN_FAILED_LOGIN_ALERT_THRESHOLD`, `ADMIN_FAILED_LOGIN_ALERT_WINDOW_MINUTES`,
  `LDAP_START_TLS`.

### Security

- **A whistleblower can no longer be locked out of their own case.** The status
  lockout was keyed by the 5-digit case number, so anyone could block a case by
  typing wrong PINs. Now a correct case number and PIN always open the case;
  wrong attempts are still counted and answered with a wait notice. Unknown case
  numbers take the same time as known ones (no timing oracle). The `/reply`
  fallback shares the same check instead of trusting a client-supplied token.
- **Password spraying is detected.** Failed admin passwords are counted
  instance-wide (no IP, no usernames); crossing the threshold raises one alert
  per window by email/webhook and in the audit log. MFA remains the barrier.
- **OIDC:** PKCE (S256), a verified `nonce`, and a verified `id_token`
  (signature, `iss`, `aud`, `exp`, `azp`); identity is taken from the token.
- **CSRF cookie** gets `Secure`; **logouts** are CSRF-protected POSTs.
- **Setup wizard** is atomic (advisory lock) — two first-run requests cannot
  create two admins; **migrations** are serialised across replicas.
- **One password policy** for the wizard, admin-created users and the reset
  script; passwords or PINs over 72 bytes no longer cause a 500 (bcrypt 5).
- **LDAP StartTLS** (`LDAP_START_TLS`) with certificate verification.
- `t()` marks text as HTML only for `.html` locale keys; SSO error pages no
  longer echo the provider's `error` parameter.

### Privacy

- **Attachment filenames are encrypted** with the report key (they can carry a
  name), and new S3 object keys no longer contain the filename.
- **Office files lose comment and tracked-change authors** (DOCX/XLSX), their
  thumbnails, and zip timestamps and uid/gid.
- **Submission drafts are encrypted** with a key that exists only in the
  whistleblower's cookie; a Redis dump alone reveals nothing. Draft attachments
  are capped, and refused when Redis is nearly full.
- **Notifications no longer reveal submission times** (batched digest).
- **The app never sees client addresses**: IP headers and the peer address are
  removed from every request after the proxy check.
- **Pages are not cached** (`Cache-Control: no-store`) — a shared office PC keeps
  no PIN or report page.
- **Helm ingress** turns the nginx access log off by default.

### Changed

- **Renovate replaces Dependabot**: patch updates merge themselves behind the
  required checks; minor/major, the Python runtime and security-relevant
  libraries wait for review. GitHub Actions are pinned to digests. Tests fail
  if a Renovate manager reaches nothing or a tool carries two versions.
  Renovate merges its own patch PRs (`platformAutomerge: false`), because the
  repository's "Allow auto-merge" setting is off.
- **Dashboard search by case number.** Report content is encrypted and is
  deliberately not searchable.
- **Readable audit log**: every action has a translated label; details are
  shown as text. The CSV keeps machine codes and adds a label column.
- **Copy**: sentence case; no absolute promises ("completely protected");
  plain language instead of "Two-Factor Access / UUID4"; every error says what
  happened and what to do. All user-facing strings, including upload errors,
  are translated.

### Fixed

- Errors are tied to their fields (`aria-invalid`, `aria-describedby`) on every
  form; blank admin login fields answered with a JSON 422.
- The authenticator setup page showed raw locale keys in en, de and fr.
- Creating a location was logged as `category.created`.
- Wrong copy: "no cookies" (functional cookies exist) and confidential data
  "only visible to the assigned admin" (every admin with access sees it).

## [1.4.0] — 2026-09-24

Attachments no longer identify the whistleblower, multi-tenant installs keep
organisations apart, and every page passes an automated contrast and layout
check on a phone and in both themes. Found and verified with a mutation audit
of every guard this release adds (28 of 28 caught).

**Upgrade notes:** migration `002` runs on start. The default
`BRAND_PRIMARY_COLOR` is now `#0c7253` (was `#0e7c5a`, 4.4:1 on tinted
backgrounds); installs that set their own colour are unaffected. E2E and demo
logins for the demo accounts use the static code `000000`; real TOTP codes are
single-use for every account.

### Fixed

- **Cleaned PDFs still contained their XMP metadata.** Unlinking it from the
  catalog left the stream in the file as an orphaned object; orphans are now
  removed. PDFs restricted by an owner password only are accepted and cleaned
  instead of refused.
- **Every page passes axe at impact serious and critical, in both themes.**
  Fixed: accent colour on tinted backgrounds (4.4 → 5.0:1), white on amber in
  the dark demo badges (2.3:1), dark-theme secondary text (3.9 → 4.8:1), role
  badges (2.1 and 3.9:1), footer links distinguishable only by colour, inactive
  categories and locations faded below AA, an unlabelled role selector and link
  field, scrollable tables unreachable by keyboard.
- **Six more admin pages scrolled sideways on a phone** (users, categories,
  locations, statistics, retention, system — up to 569 px), and long audit
  entries on the report view.
- **No page scrolls sideways on a phone any more.** At 390 px the navigation
  (12 items in the admin) now wraps instead of running off-screen, the
  dashboard toolbar and the report view (two columns, no breakpoint) fit the
  width. An E2E test checks `/submit`, `/status` and `/admin/login` at 390 px.
- **Confidential mode works without JavaScript** (Tor Browser "Safest"): the
  name/contact fields are shown by CSS `:has()` instead of a script.
- **The language picker works without JavaScript** and no longer misuses
  `listbox`/`option` roles: it is a native `<details>` list of forms.
- Contrast: input borders 1.25:1 → ≥ 3:1; a visible focus outline on inputs
  and on the submission-mode cards (focused and selected looked identical);
  secondary text 4.37:1 → 4.98:1 on cards; alert titles no longer dimmed.

### Changed

- **Stricter tests.** The axe checks fail on *serious* violations, not only
  *critical* ones (contrast failures used to ship green). A new UI check visits
  every public and admin page in both themes at 390 and 1440 px and fails on
  axe violations, console errors or sideways scrolling. Every guard of the
  release is mutation-tested (`scripts/mutation_audit.py`).
- **Maintainer documentation moved to `docs-tech/`** (release procedure,
  invariants, performance baseline); a test keeps it
  out of the published site.
- **Images are built once and published identically to all three
  registries.** Each platform builds on a native runner (arm64 no longer under
  QEMU) and is pushed to GHCR by digest; one multi-arch index is then written
  under every tag to GHCR, Docker Hub and Quay.io. Docker Hub and Quay now get
  the same provenance, SBOM and cosign signature as GHCR (before: separate
  unsigned builds). The job fails unless every tag and every platform manifest
  behind it is pullable. Quay.io stays best-effort with a warning.
- **Dependencies are locked in `uv.lock`.** The image, CI and the E2E/perf
  workflows install exactly the locked versions; CI fails if the lock is out
  of date. Dependabot now uses the `uv` ecosystem — the old `pip` entry only
  saw `>=` floors and had never opened a pull request.
- **The production image carries runtime dependencies only** (no pytest, mypy
  or ruff), uv is taken from its official image (0.6.0 → 0.12.18), and the
  fonts are copied from `docs/fonts` instead of downloaded unverified at build
  time.
- `python-jose` replaced by PyJWT, which drops `ecdsa` (PYSEC-2026-1325, no
  fix planned). Unused `authlib` and `aiofiles` removed; `cryptography` is now
  a declared dependency instead of an accidental transitive one.

### Security

- **Multi-tenancy: an org admin now sees and manages only their own
  organisation.** The users page, role changes, (de)activation, the
  assignment picker and target, the audit log and its CSV export, and the
  dashboard and statistics counts were unscoped; new users now join the
  creator's organisation. Single-organisation installs are unaffected.
- **`DEMO_MODE` no longer weakens a real installation.** The static TOTP
  `000000` is accepted only for the seeded demo accounts, and demo data is
  not seeded into a database that completed the setup wizard and has no demo
  account.
- **Internal admin notes are encrypted at rest** with the report's data key,
  like descriptions and messages. Existing notes are shown as stored.
- **Attachments no longer carry identifying metadata.** EXIF/GPS and camera
  data (JPEG, PNG, WebP, GIF), PDF document info and XMP, and DOCX/XLSX author
  and company properties are removed on upload — before the file reaches the
  draft store. A file that cannot be parsed for cleaning is refused instead of
  stored as-is. The upload step tells the whistleblower what is and is not
  cleaned.
- **Attachments are encrypted at rest** with the report's own data key, in
  PostgreSQL and in S3. Rows from before this release are served as stored
  (migration `002` adds `attachments.encrypted`).

## [1.3.1] — 2026-09-23

### Security

- **OIDC logins now require TOTP.** The OIDC callback issued a session directly,
  so SSO accounts skipped the mandatory second factor. All three login paths
  (local, LDAP, OIDC) now go through the same MFA step; SSO users enrol TOTP on
  their next login. Deactivated accounts are also rejected on the OIDC path.
- **LDAP first login provisions a Case Manager, not an Admin.** Any directory
  entry matching `LDAP_USER_FILTER` previously got full admin access.
- **LDAP username is escaped** before it is placed into the search filter
  (filter injection), and **LDAPS now verifies the server certificate**
  (`CERT_NONE` before). Private CAs: set `SSL_CERT_FILE`.
- **Deleting a report removes its S3 objects.** Manual deletion, 4-eyes deletion
  and the retention job only removed database rows; attachment files in the
  bucket were kept forever.
- **nginx no longer logs client IPs.** `error_log` ran at `warn`, and nginx
  prefixes rate-limit (429) and body-size (413) errors with the client address.
  It now logs at `crit` only.
- "Start over" in the submission wizard is now CSRF-protected.

### Fixed

- **Uploads over 1 MB failed behind the bundled nginx** (default
  `client_max_body_size`). Set to 55 MB (5 × 10 MB attachments).
- **Fresh production installs could not start PostgreSQL 18.** The 18 image
  refuses a volume at `/var/lib/postgresql/data` unless `PGDATA` points there;
  `docker-compose.prod.yml` and the Ansible template now set it. Existing data
  is unaffected.
- **GHCR images were unpullable** (`manifest unknown`): the weekly cleanup job
  deleted the untagged per-platform manifests that every multi-arch tag points
  to. GHCR cleanup is removed; Docker Hub and Quay.io were not affected.
- **Helm chart deployed v0.5.0 by default** — `appVersion` was never bumped. It
  now tracks the app version, enforced by a test.
- "Start over" on the review step returned 405 (GET link to a POST-only route).
- Footer text had 1.8:1 contrast on the dark footer; now 7.7:1.
- Animations now respect `prefers-reduced-motion`.
- HinSchG citations: the 3-year deletion rule is §11 Abs. 5, not §12 Abs. 3,
  and it is a deletion deadline, not a minimum retention period.

- **"Back" in the submission wizard no longer triggers validation.** The
  double-submit guard disabled the form's *first* submit button — which on every
  wizard step is "Back" — while the browser was still building the submitted
  entry list. Disabled controls are excluded from that list, so `action=back`
  never reached the server and the step was processed as a "Next", rejecting an
  empty description instead of navigating back. The guard now targets the button
  the user actually clicked and applies after the form data is collected.

## [1.3.0] — 2026-07-15

The "Signal" design system — a ground-up visual redesign that unifies the app and
the public site under one identity, plus a documented design specification.

### Added

- **`DESIGN.md`** — a canonical design system ("Signal") in the google/design.md
  format: front-matter design tokens (colour, typography, spacing, radii,
  elevation) and prose covering every component, with first-class light and dark
  themes.
- **Design token foundation** in the stylesheet: a `--space-*` spacing scale, a
  `--text-*` type scale, and shared `.anim-in` / `.delay-*` animation utilities.

### Changed

- **Full "Signal" restyle** of the application — a monochrome warm-neutral ground
  with a single emerald accent, Sora for display and body text, and JetBrains
  Mono for case numbers, PINs, timestamps and deadlines. Dark mode is now a warm
  near-black rather than a cold navy.
- **Self-hosted fonts reduced to two** (Sora + JetBrains Mono); the Docker image
  downloads exactly those, replacing the previous three-font set. The default
  `BRAND_PRIMARY_COLOR` is now emerald (`#0e7c5a`).
- **Public marketing and documentation pages** (openwhistle.net) converted from
  their separate serif/gold look onto the same Signal tokens.
- **Stylesheet and template cleanup**: consolidated duplicated components
  (`.info-banner` → `.alert`, `.env-table` → `table`, three admin grids →
  `.admin-split-grid`, inline-form wrappers → `.inline-form`), rebuilt the admin
  report page's 56 numbered one-off classes into semantic classes on the type
  scale, and unified the scattered animation-delay helpers.

### Fixed

- The intended body typeface never loaded — its `@font-face` pointed at font
  files that did not exist, so the app silently fell back to `system-ui`. A real
  self-hosted font now ships.
- Dark mode ignored the configured brand colour (the accent was hardcoded); it
  now derives from `BRAND_PRIMARY_COLOR` in both themes.
- The public report-status page's status pills were unstyled (they referenced CSS
  classes that were never defined); they now use the themed badge styles.
- Removed references to several undefined CSS custom properties.

## [1.2.1] — 2026-07-14

Follow-up hardening release resolving the remaining bug-bounty findings (#42–#46).

### Security

- CSRF protection extended to the two remaining state-changing admin POST
  endpoints (`/admin/ip-warning/dismiss`, `/admin/demo/reset`). AJAX requests
  authenticate via an `X-CSRF-Token` header (read from a `<meta>` tag, since the
  double-submit cookie is HttpOnly) (#44).
- Case numbers now use a random 5-digit suffix instead of a global sequence, so
  a new report no longer reveals aggregate cross-tenant report volume. Format is
  unchanged (`OW-YYYY-NNNNN`) and existing numbers stay valid (#42).
- Attachment uploads are now verified by magic number: the file's leading bytes
  must match its extension (PDF, JPEG, PNG, GIF, WebP, DOCX/XLSX, DOC/XLS), so a
  file cannot lie about its type (e.g. HTML bytes disguised as a `.png`). Text
  formats have no signature and are unaffected (#43).
- Reverse-proxy flood protection for the submission channel: the bundled nginx
  configs now apply a per-IP `limit_req` to dynamic endpoints. The IP is used
  only for in-memory throttling — never logged or forwarded upstream — so
  whistleblower anonymity is preserved (#46).
- Removed a dead, unreachable "this account uses Single Sign-On" login branch;
  SSO-only accounts already receive the generic "invalid credentials" error,
  which avoids leaking account existence / auth method (#46).

### Fixed

- Downloading an attachment whose S3 object is missing now returns 404 instead
  of an unhandled 500; genuine backend errors still surface as 5xx (#45).

## [1.2.0] — 2026-07-13

### Added

- **Admin System page + opt-in update check**: a new **Admin → System** page
  shows the installed version and, when `UPDATE_CHECK_ENABLED=true`, whether a
  newer release is available on GitHub. The check is **off by default**, runs as
  a daily background job (result cached in Redis, ETag-conditional), and sends no
  instance data to GitHub — only a standard request. The installed version is
  also shown in the footer.
- **File integrity check** on the Admin → System page: verifies the shipped
  application files against a SHA-256 manifest generated at Docker build time and
  reports any missing, modified, or unexpected files. Purely local (no external
  calls); detects accidental modification, incomplete deployments and corruption
  (not tamper-proof against an attacker who can also rewrite the manifest — the
  manifest's own hash is shown for optional out-of-band verification).

## [1.1.1] — 2026-07-13

Security release: four privately-reported advisories plus an internal
adversarial "bug-bounty" audit that fixed ~25 further edge-case defects. All
users of 1.1.0 should upgrade.

### Breaking

- **`SECRET_KEY` must now be at least 32 characters.** The application refuses
  to start with a shorter key. `SECRET_KEY` is the root secret for admin
  authentication and for encrypting confidential whistleblower identities, so a
  weak key undermines the platform's core protection. Generate a strong one
  with `python -c 'import secrets; print(secrets.token_urlsafe(48))'`. Note:
  rotating `SECRET_KEY` makes previously-encrypted confidential fields
  unreadable — set a strong key from the start.

### Security

- **Report deanonymization / IDOR** (GHSA-q3v3-5xf4-xjqr, High): every
  `/admin/reports/{id}*` endpoint now enforces object-level authorization. Case
  managers can only access reports assigned to them; admins are scoped to their
  own organisation (superadmins span all) when multi-tenancy is enabled. The
  dashboard list and the confidential-identity block are scoped the same way, so
  an unassigned case manager can no longer read a confidential whistleblower's
  identity.
- **Privilege escalation** (GHSA-g3xj-3929-r45h, High): the role-assignment
  endpoints now enforce privilege tiers. Only a superadmin may grant or modify
  the superadmin role, an account can no longer change its own role, and the last
  active administrator can no longer be demoted away.
- **Stored XSS** (GHSA-24hg-pf84-jj7x, High): admin usernames and organisation
  names are no longer interpolated into inline `onclick` handlers; confirmation
  prompts moved to a safe `data-confirm` attribute. Locally-created usernames are
  validated against a strict allowlist.
- **Weak / duplicated HTTP security headers** (GHSA-gh23-4h5j-cqj8, Medium):
  security headers are now emitted by a single authoritative layer (the
  application middleware); the bundled nginx template no longer re-emits them,
  removing the duplicated/conflicting `Strict-Transport-Security`,
  `X-Content-Type-Options` and `X-Frame-Options` headers. The Content-Security-
  Policy no longer uses `'unsafe-inline'`: it is now a strict, per-response
  nonce-based policy for both scripts and styles.

Reported by [@openblow](https://github.com/openblow).

### Fixed (internal bug-bounty audit)

Real defects found by an adversarial audit, each covered by a regression test
in `tests/test_bug_bounty_v111.py`:

- **Retention could delete reopened cases early**: `closed_at` was never
  refreshed when a case was reopened and re-closed, so the auto-deletion job
  could remove reports far before the statutory retention period had elapsed
  since their actual closure. It is now cleared on reopen and re-stamped on
  re-close.
- **Superadmin lockout**: a plain admin could deactivate a superadmin, and the
  last active privileged account could be deactivated/demoted, leaving no one
  able to administer the instance. Both are now blocked.
- **Attachment downloads with non-Latin-1 filenames** (CJK, Cyrillic, emoji)
  raised `UnicodeEncodeError` and 500'd — the evidence became permanently
  undownloadable. `Content-Disposition` now uses RFC 5987 encoding. PDF export
  no longer crashes on non-Latin-1 note authors either.
- **MFA brute-force**: TOTP guessing is now rate-limited, and a valid code is
  one-time-use within its window (blocks AiTM replay into a second session).
- **`acknowledge` is now idempotent** so the statutory feedback deadline cannot
  be pushed out by re-invoking it.
- **Concurrent submissions** no longer 500 on a case-number collision (retry).
- Reports can no longer be assigned to a deactivated user (orphaned cases).
- Linked-report metadata is filtered through the object-level authz check.
- SLA reminder de-duplication now covers the full warn window (was re-firing
  every ~hour for days); per-report failures are isolated.
- `SUBMISSION_MODE_ENABLED=false` now actually forces anonymous submissions,
  and confidential PII is purged from the session when switching to anonymous.
- The whistleblower PIN lockout is keyed on the case number, so it can no longer
  be bypassed by fetching a fresh anonymous session token before each guess.
- Login now runs a constant dummy password hash for unknown users (removes a
  username-enumeration timing side-channel).
- Background scheduler jobs take a Redis lock so a scaled/stateless deployment
  does not run them once per replica (duplicate audit entries / notifications).
- 4-eyes delete confirmation re-checks the request under a row lock, so a
  concurrent cancel cannot be raced into deleting a withdrawn report.
- The submission wizard rejects out-of-order steps (blocks jumping straight to
  the attachment step to stash blobs in Redis) and no longer adopts a
  client-supplied session id with no server-side state (session fixation).
- Case-insensitive duplicate-username check; empty decrypted bodies no longer
  fall back to raw ciphertext; oversized uploads are rejected without buffering
  the whole body; relinking already-linked cases returns 409 instead of 500;
  decryption failures are logged rather than silently shown as blank.

Remaining lower-severity findings are tracked in GitHub issues #42–#46.

### Changed

- All Python dependency floors raised to their current major versions (notably
  redis 8, bcrypt 5, SQLAlchemy 2.0.51, uvicorn 0.51, FastAPI 0.139, mypy 2,
  pytest 9, pytest-asyncio 1.x). GitHub Actions `actions/checkout` and
  `codecov/codecov-action` bumped to v7.

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
  reuse the existing record; `TOTP` enrollment still required after first login;
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

[Unreleased]: https://github.com/openwhistle/OpenWhistle/compare/v2.0.0...HEAD
[2.0.0]: https://github.com/openwhistle/OpenWhistle/compare/v1.5.0...v2.0.0
[1.5.0]: https://github.com/openwhistle/OpenWhistle/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/openwhistle/OpenWhistle/compare/v1.3.1...v1.4.0
[1.3.1]: https://github.com/openwhistle/OpenWhistle/compare/v1.3.0...v1.3.1
[1.3.0]: https://github.com/openwhistle/OpenWhistle/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/openwhistle/OpenWhistle/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/openwhistle/OpenWhistle/compare/v1.1.1...v1.2.0
[1.1.1]: https://github.com/openwhistle/OpenWhistle/compare/v1.1.0...v1.1.1
[1.1.0]: https://github.com/openwhistle/OpenWhistle/compare/v1.0.0...v1.1.0
[1.0.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.5.0...v1.0.0
[0.5.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.4.0...v0.5.0
[0.4.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.3.0...v0.4.0
[0.3.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.2.2...v0.3.0
[0.2.2]: https://github.com/openwhistle/OpenWhistle/compare/v0.2.1...v0.2.2
[0.2.1]: https://github.com/openwhistle/OpenWhistle/compare/v0.2.0...v0.2.1
[0.2.0]: https://github.com/openwhistle/OpenWhistle/compare/v0.1.0...v0.2.0
[0.1.0]: https://github.com/openwhistle/OpenWhistle/releases/tag/v0.1.0
