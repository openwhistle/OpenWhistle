<!-- markdownlint-disable MD033 MD041 -->
<p align="center">
  <img src="app/static/favicon.svg" alt="" width="88" height="88">
</p>

<h1 align="center">OpenWhistle</h1>

<p align="center"><em>Speaking up takes courage. Staying silent shouldn't be the safer option.</em></p>

<!-- One badge service, so the set shares a shape, a typeface and a logo
     treatment. The status badges read from the workflows by file name; release,
     licence and Python read from the repository, so none of them can drift the way
     a hand-written version number could. The i18n badge reads the endpoint file
     that .github/workflows/badges.yml writes to the `badges` branch. -->
<!-- markdownlint-disable MD013 -->
<p align="center">
  <a href="https://github.com/openwhistle/OpenWhistle/actions/workflows/ci.yml"><img src="https://img.shields.io/github/actions/workflow/status/openwhistle/OpenWhistle/ci.yml?branch=main&label=ci&logo=github&logoColor=white" alt="CI"></a>
  <a href="https://github.com/openwhistle/OpenWhistle/actions/workflows/docker-publish.yml"><img src="https://img.shields.io/github/actions/workflow/status/openwhistle/OpenWhistle/docker-publish.yml?label=docker&logo=docker&logoColor=white" alt="Docker"></a>
  <a href="https://github.com/openwhistle/OpenWhistle/actions/workflows/security.yml"><img src="https://img.shields.io/github/actions/workflow/status/openwhistle/OpenWhistle/security.yml?branch=main&label=security&logo=github&logoColor=white" alt="Security"></a>
  <a href="https://codecov.io/gh/openwhistle/OpenWhistle"><img src="https://img.shields.io/codecov/c/github/openwhistle/OpenWhistle?logo=codecov&logoColor=white&label=coverage" alt="Coverage"></a>
  <a href="app/locales"><img src="https://img.shields.io/endpoint?url=https%3A%2F%2Fraw.githubusercontent.com%2Fopenwhistle%2FOpenWhistle%2Fbadges%2Fi18n.json&logo=googletranslate&logoColor=white" alt="Share of UI strings translated in every language"></a>
</p>

<p align="center">
  <a href="https://github.com/openwhistle/OpenWhistle/releases/latest"><img src="https://img.shields.io/github/v/release/openwhistle/OpenWhistle?logo=github&logoColor=white&label=release" alt="Latest release"></a>
  <a href="https://www.python.org"><img src="https://img.shields.io/python/required-version-toml?tomlFilePath=https%3A%2F%2Fraw.githubusercontent.com%2Fopenwhistle%2FOpenWhistle%2Fmain%2Fpyproject.toml&logo=python&logoColor=white&label=python" alt="Python version"></a>
  <a href="https://www.gnu.org/licenses/gpl-3.0"><img src="https://img.shields.io/github/license/openwhistle/OpenWhistle?logo=opensourceinitiative&logoColor=white&label=license&color=blue" alt="GPL-3.0"></a>
  <a href="https://hub.docker.com/r/kermit1337/openwhistle"><img src="https://img.shields.io/docker/pulls/kermit1337/openwhistle?logo=docker&logoColor=white" alt="Docker Hub pulls"></a>
  <a href="https://github.com/sponsors/jp1337"><img src="https://img.shields.io/badge/sponsor-GitHub-ea4aaa?logo=githubsponsors&logoColor=white" alt="Sponsor on GitHub"></a>
</p>

<p align="center">
  <a href="https://demo.openwhistle.net"><strong>Live demo</strong></a> ·
  <a href="https://openwhistle.net/en/docs/"><strong>Documentation</strong></a> ·
  <a href="CHANGELOG.md">Changelog</a>
</p>

A self-hosted internal reporting channel that meets the German HinSchG and EU Directive 2019/1937:
**the reporter leaves no trace — no IP address, no account, no exact time.**

Any company with 50 or more employees, and every public authority, must offer one. Free, open source, no vendor lock-in.

<picture>
  <source media="(prefers-color-scheme: dark)" srcset="https://raw.githubusercontent.com/openwhistle/website/main/docs/img/screens/admin-dashboard-dark.png">
  <img src="https://raw.githubusercontent.com/openwhistle/website/main/docs/img/screens/admin-dashboard-light.png" alt="The OpenWhistle admin dashboard: reports with their status, deadlines and category.">
</picture>
<!-- markdownlint-enable MD013 -->

## Quick start

```bash
git clone https://github.com/openwhistle/OpenWhistle.git && cd OpenWhistle
cp .env.example .env        # SECRET_KEY, ENCRYPTION_KEY: openssl rand -hex 32 each
docker compose up -d
docker compose logs app | grep "Setup token"   # then open http://localhost:4009/setup
```

Plain HTTP from another device needs `SECURE_COOKIES=false`; keep the default behind HTTPS.
Production setup, every setting, reverse proxy: **[openwhistle.net/en/docs](https://openwhistle.net/en/docs/)**.

## ✨ Features

Every one of them is documented on [openwhistle.net/en/docs](https://openwhistle.net/en/docs/).

### Reporter

- **No trace** — no IP address in any log; times the reporter causes are stored as the day only
- **Proxy warning** — a reporter whose request reached the app with an address header is told the proxy may log it
- **External reporting offices** — the page §13 Abs. 2 HinSchG requires, linked from every footer
- **Legal links** — `PRIVACY_POLICY_URL` and `LEGAL_NOTICE_URL` put your privacy notice (Art. 13 GDPR) and legal
  notice in every footer; the dashboard says when the privacy notice is missing
- **Case number + UUID4 PIN** — no account, no email; a correct pair always opens the case
- **Anonymous or confidential** — a confidential name is encrypted, shown to the case handler only on audited request
- **Submission wizard** — guided steps, Redis-backed draft encrypted with a key only in the reporter's cookie
- **Two-way messages** (HinSchG § 17) and **file attachments** with GPS, EXIF and author metadata stripped
- **Optional virus scan** — ClamAV, fail-closed
- **Tor onion address** — `ONION_LOCATION` adds the `Onion-Location` header and a note for monitored networks

### Case handling

- **HinSchG deadlines** — 7-day acknowledgement and 3-month feedback, tracked and reminded
- **Status workflow** — `received → in_review → pending_feedback → closed`, validated server-side
- **Assignment, internal notes, case linking**, search by number or content, custom categories, locations
- **PDF export** with the SLA section; dashboard statistics
- **Slack, Teams and email notices** — batched; webhooks carry counts only, e-mail the case numbers, never content
- **Telephone-channel guide** — HinSchG § 16 Abs. 3 checklist

### Accounts and security

- **Mandatory TOTP** for every admin; secrets stored encrypted
- **Roles** — `SUPERADMIN`, `ADMIN`, `CASE_MANAGER`, object-level authorization on every report
- **Database, LDAP / Active Directory or OIDC login** — PKCE, verified ID token
- **Account recovery** — own password page, authenticator reset, host script, password-spraying alarm
- **4-eyes deletion**, audit log with CSV export, data retention (default 3 years), hard deletion
- **Encryption at rest** — per-report envelope encryption, separate `ENCRYPTION_KEY` with rotation
- **Hardened HTTP** — nonce-based CSP, security headers, absolute session lifetime, TLS by default
- **Hardened containers** — read-only root, no capabilities, base images pinned by digest

### Operation

- **Web setup wizard** with one-time setup token
- **Multi-tenancy** — isolated organisations, per-organisation reporting link
- **S3-compatible attachment storage**, structured JSON logs, `/health` for Kubernetes probes
- **Helm chart, Ansible role**, multi-arch images on GHCR, Docker Hub and Quay.io
- **Update check and install count** — both opt-in; the update check sends nothing about the instance, the count a
  random ID and the version; while the count is off, the dashboard asks once per update
- **Branding page** — name, light and dark logo, brand colour with a live preview, per
  organisation; logos PNG, JPEG or WebP only (no SVG), at most 1 MB and 16 megapixels, re-encoded as
  metadata-free PNG; colours adjusted to WCAG AA in both themes; the footer is not brandable
- **Five languages** — English, German, French, Spanish, Brazilian Portuguese; WCAG 2.1 AA; light and dark
- **No external calls** — self-hosted fonts, no CDN, no tracking (GDPR)
- **No public version number** — only signed-in admins see it; `/health` and asset URLs leave it out
- **"Signal" design system** — [`DESIGN.md`](DESIGN.md)

## Container images

| Registry | Image |
| --- | --- |
| GitHub Container Registry | `ghcr.io/openwhistle/openwhistle` |
| Docker Hub | `kermit1337/openwhistle` |
| Quay.io | `quay.io/jp1337/openwhistle` |

Multi-arch (amd64, arm64). GHCR images are signed with Cosign; [verify them](https://openwhistle.net/en/docs/images/).
Every image is scanned with [grype](https://github.com/anchore/grype) before it is tagged: any fixable
vulnerability fails the build. The reviewed exceptions are in [`.grype.yaml`](.grype.yaml).

## Live demo

[demo.openwhistle.net](https://demo.openwhistle.net) — user `demo`, password `demo`, TOTP `000000`. Resets every 6 hours.

## Legal

Designed for the [HinSchG](https://www.gesetze-im-internet.de/hinschg/),
[EU Directive 2019/1937](https://eur-lex.europa.eu/legal-content/en/TXT/?uri=CELEX%3A32019L1937) and the
[GDPR](https://gdpr-info.eu/). The duties, one by one: [compliance pages](https://openwhistle.net/en/compliance/).
OpenWhistle is a tool; the operator stays responsible for the deployment.

## Contributing

Setup and review checklist: [CONTRIBUTING.md](CONTRIBUTING.md). Documentation changes go to
[openwhistle/website](https://github.com/openwhistle/website).
A vulnerability: **not** a public issue — see [SECURITY.md](SECURITY.md).

## License

GPL-3.0 — see [LICENSE](LICENSE). Developed in free time; [sponsor it](https://github.com/sponsors/jp1337) if it helps.
