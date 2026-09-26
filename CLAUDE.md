# openwhistle

Das EU-Whistleblower-Gesetz (Richtlinie (EU) 2019/1937) verpflichtet Unternehmen (ab 50 Mitarbeitern) und
Behörden zur Einrichtung sicherer interner Meldekanäle, um Hinweisgeber vor Repressalien zu schützen. In Deutschland
wurde dies durch das Hinweisgeberschutzgesetz (HinSchG) umgesetzt, das seit dem 2. Juli 2023 in Kraft ist und
Repressalien verbietet.

Referenz zum Hinweisgeberschutzgesetz zum nachlesen:
<https://www.gesetze-im-internet.de/hinschg/>

OpenWhistle ist eine Plattform, wo ein Whistleblower die Möglichkeit hat eine Meldung abzugeben.

Folgende Fakten sind festgelegt:

- Die Serverseite des Programms läuft in einem Docker Container
- Die Serverseite muss immer stateless laufen
- Die Datenhaltung erfolgt in einer PostgreSQL Datenbank.
- Caches oder Sessions oder alles, was die Stateless Applikation stören könnte, soll in Redis festgehalten werden
- Die Sicherheit des Programms ist sehr wichtig, es dürfen keine Daten nach außen gelangen können
- Die Sicherheit des Whistleblowers ist sehr wichtig und seine Identität soll zu 100% geschützt sein
- Der Whistleblower bekommt nach seiner Meldung eine PIN, mit der er sich wieder einloggen kann
- Die PIN muss sicher gestaltet sein. Also z.B. eine GUID oder ähnliches, keine 4-stellige PIN, die man erraten könnte.
- Nach der Installation muss über einen Web-basierten Wizard ein Admin Account angelegt werden
- Multi Faktor Authentifizierung ist verpflichtend für alle Benutzerkonten
- Es soll der Login über Datenbank oder OIDC möglich sein
- Programmiert wird immer auf Englisch. Es gibt keine Deutschen Kommentare oder Deutsche Inhalte.
- Die README und andere Dokumentation ist ebenfalls immer auf Englisch.
- Die Software wird unter der Lizenz "GNU General Public License v3.0" veröffentlicht
- Die Versionierung erfolgt über semantische Versionierung
- Es wird für jede Version ein Changelog in der Datei "CHANGELOG.md" geschrieben
- Es soll eine Live Demo der Software unter der URL "<https://demo.openwhistle.net>" geben.
- Für die Demo sollen die Zugangsdaten Benutzername und Passwort "demo" sein.
- Die Demo wird automatisch alle 6 Stunden geleert und neu gestartet.
- Es gibt eine Website "openwhistle.net", die aktuell auf die GitHub Page weiterleitet. Zukünftig soll dort
  eine GitHub Page aus dem Repository laufen, wo Informationen über OpenWhistle stehen und auch die Dokumentation
  gehostet wird.
- Wichtig ist, dass der Whistleblower geschützt wird und sogar keine Logs über seine IP-Adresse vorhanden
  sind. So kann z.B. ein Mitarbeiter eines Unternehmens geschützt sein, der im Büro eine Nachricht verschickt.
- Das ganze Projekt wird in der Freizeit entwickelt und es kann gespendet werden.
- Es sollen unter GitHub die Sicherheitsfeatures genutzt werden, um den Code zu scannen und Dependencies zu scannen.
- Wenn du eine technische Entscheindung triffst, aktualisiere bitte immer die README.md mit aktuellen Daten
- Der Docker Container soll für jede Version immer auf der GitHub Container Registry, DockerHub und quay.io
  über einen GitHub Workflow / Action gepushed werden
- Beim erstellen von Commit Messages erwähnst du bitte nicht Claude Code
- Du hast Zugriff auf GitHub über die GitHub CLI
- Markdown Dokumente müssen nach markdownlint Vorgaben erstellt werden
- Documentation in `docs/docs.html`, `README.md`, and `docker-compose.prod.yml` must always be kept in
  sync. When adding or renaming environment variables, update ALL locations in the same commit.
- The demo at <https://demo.openwhistle.net> is live and hosted on Hetzner via
  Ansible. It runs `ghcr.io/openwhistle/openwhistle:edge` and is reset every 6 hours by a Semaphore job
  that recreates the container with a fresh pull — that reset is also the only thing that updates it
  (Watchtower does not poll).
- All HTML files in `docs/` must use self-hosted fonts from `docs/fonts/` — never Google Fonts CDN or
  any other external font CDN.
- Every finding — design, security, privacy, process, any size — is fixed in the work that found it. There is
  no "carried forward" or "out of scope" list; a finding too big for one task is split, never postponed.

## Test coverage

- Minimum test coverage is **90 %**. This is enforced via `--cov-fail-under=90` in `pyproject.toml`
  and will fail CI if coverage drops below the threshold.
- When adding new features, always add corresponding tests so coverage stays at or above 90 %.
- Run the full suite against a real PostgreSQL and Redis (e.g. two throwaway containers) with
  `uv sync --extra dev --extra ldap --extra s3` (python-ldap needs OS headers, see
  `docs-tech/dependencies.md` "Development setup") and `DATABASE_URL`/`REDIS_URL`/`SECRET_KEY`
  set, as CI does. Without a DB the DB-backed tests error and coverage undercounts. The
  production image carries no test dependencies, so tests cannot run inside it.
- Dependencies are locked in `uv.lock` (CI runs `uv lock --check`); after editing
  `pyproject.toml`, run `uv lock` and commit both.

## Release documentation checklist

Before marking a version as released (the roadmap page at `docs/roadmap.html`, CHANGELOG.md, git tag), verify ALL of the
following. These checks caught v0.3.0 and v0.4.0 gaps retroactively — run them proactively.

### `docs/docs.html`

- **Version number**: the "Current version" paragraph in the Overview section must match
  `app_version` in `app/config.py`.
- **Admin guide — status workflow**: the case status values listed in "Managing reports" must
  match the actual `ReportStatus` enum in `app/models/report.py`. Do not leave stale values
  from a previous release.
- **Admin guide — new admin UI sections**: every new `/admin/*` route (categories, locations,
  users, audit-log, stats, …) must be referenced in the admin guide with its path.
- **Admin guide — roles**: if roles changed, update the roles section.
- **Whistleblower guide — submission flow**: if the submission form steps or modes changed,
  update the numbered list in "Submitting a report".
- **Whistleblower guide — status page**: if new information appears on the status page
  (e.g. deadline display), add it to the "Checking report status" bullet list.
- **Configuration table**: every new env var in `app/config.py` must have a row in the
  `<table class="env-table">` block. Cross-check `config.py` fields against table rows.

### `docker-compose.prod.yml`

- Every new optional env var in `app/config.py` must appear as
  `VAR_NAME: "${VAR_NAME:-<default>}"` in the `app` service environment block.

### `README.md`

- Every significant user-facing feature added in the release must appear in the
  `## ✨ Features` section. One bullet per feature is enough.

### Cutting the release

Follow `docs-tech/release.md`: mutation audit of every new guard
(`scripts/mutation_audit.py`, all RED), UI check, Chrome check (every page
visually reviewed in the Claude-in-Chrome extension, `docs-tech/local-review.md`),
release PR, tag, verify the published images from outside.

## Why these rules exist

| Rule | What happened without it |
| --- | --- |
| Docs, README and compose change in the same commit as an env var | v0.3.0 and v0.4.0 shipped variables the docs did not list |
| Every new guard goes through the mutation audit | v1.4.0: removing the PDF XMP step stayed green; the XMP stream shipped as an orphaned object |
| One version string, checked by a test | 0.5.0–1.3.0: the Helm chart deployed an old image |
| Tests run against real PostgreSQL and Redis | DB-backed tests error without them and coverage undercounts |
| Fonts are self-hosted | `fonts.css` pointed at files that did not exist; the app silently used system-ui |
| No carried-forward list | v1.6 planning first deferred design and three security items to "later" |
