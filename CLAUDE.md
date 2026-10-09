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
- The website <https://openwhistle.net> (information about OpenWhistle and the published user documentation)
  lives in its own repository, [openwhistle/website](https://github.com/openwhistle/website), and builds from
  the latest release tag of this repository.
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
- `CONTRIBUTING.md`, section "Documentation", is binding for every documentation change.
- **Drift rule.** A user-facing change here (an env var or setting, a route, a case status, anything in the
  interface) gets a pull request in openwhistle/website in the same piece of work, linked from this
  repository's pull request. The website's weekly build turns red when its documentation no longer matches
  the latest release.
- `README.md`, `docker-compose.prod.yml`, the Helm chart and `ansible/roles/openwhistle/templates/env.j2`
  change in the same commit as the env var they list.
- The demo at <https://demo.openwhistle.net> is live and hosted on Hetzner via
  Ansible. It runs `ghcr.io/openwhistle/openwhistle:edge` and is reset every 6 hours by a Semaphore job
  that recreates the container with a fresh pull — that reset is also the only thing that updates it
  (Watchtower does not poll).
- The app's fonts are self-hosted in `app/static/fonts/` with their OFL licences — never Google Fonts CDN or
  any other external font CDN.
- Every finding — design, security, privacy, process, any size — is fixed in the work that found it. There is
  no "carried forward" or "out of scope" list; a finding too big for one task is split, never postponed.

## Test coverage

- Minimum test coverage is **90 %**. This is enforced via `--cov-fail-under=90` in `pyproject.toml`
  and will fail CI if coverage drops below the threshold.
- When adding new features, always add corresponding tests so coverage stays at or above 90 %.
- Run the full suite against a real PostgreSQL and Redis (e.g. two throwaway containers) with
  `uv sync --extra dev --extra ldap --extra s3 --group diagrams` (python-ldap needs OS headers, see
  `docs-tech/dependencies.md` "Development setup") and `DATABASE_URL`/`REDIS_URL`/`SECRET_KEY`
  set, as CI does. Without a DB the DB-backed tests error and coverage undercounts. The
  production image carries no test dependencies, so tests cannot run inside it.
- Dependencies are locked in `uv.lock` (CI runs `uv lock --check`); after editing
  `pyproject.toml`, run `uv lock` and commit both.

## Release documentation checklist

Before marking a version as released (CHANGELOG.md, git tag), verify ALL of the following. These checks caught
v0.3.0 and v0.4.0 gaps retroactively — run them proactively.

### The documentation (openwhistle/website)

The release's documentation — version, roadmap, status workflow, admin routes, roles, the
whistleblower guide and the configuration reference — is the drift rule's pull request in
openwhistle/website. Its build checks version, settings, statuses and routes against this release's tag.

### `docker-compose.prod.yml`

- Every new optional env var in `app/config.py` must appear as
  `VAR_NAME: "${VAR_NAME:-<default>}"` in the `app` service environment block.

### `README.md`

- Every significant user-facing feature added in the release must appear in the
  `## ✨ Features` section. One bullet per feature is enough.

### Cutting the release

Follow `docs-tech/release.md`: mutation audit of every new guard
(`scripts/mutation_audit.py`, all RED), UI check, Chrome check (every app page
visually reviewed in the Claude-in-Chrome extension, `docs-tech/local-review.md`),
release PR, tag, verify the published app images from outside. The website and its
image are released from openwhistle/website.

## Why these rules exist

| Rule | What happened without it |
| --- | --- |
| README and compose change with an env var; the docs in a linked website PR | v0.3.0 and v0.4.0 shipped variables the docs did not list |
| Every new guard goes through the mutation audit | v1.4.0: removing the PDF XMP step stayed green; the XMP stream shipped as an orphaned object |
| One version string, checked by a test | 0.5.0–1.3.0: the Helm chart deployed an old image |
| Tests run against real PostgreSQL and Redis | DB-backed tests error without them and coverage undercounts |
| Fonts are self-hosted | `fonts.css` pointed at files that did not exist; the app silently used system-ui |
| No carried-forward list | v1.6 planning first deferred design and three security items to "later" |
