# Website P3: content

Type: explanation + scope. Source: the brainstorming session of 2026-10-04. It refines P3 of
`2026-10-01-website-redesign-design.md` (sections Site structure, Legal pages, Documentation, SEO and blog). Every
decision below was taken with the maintainer.

## Outcome

The site says what OpenWhistle is, for whom, and how to check it:

- The docs are one page per task in five sections, with search.
- Compliance, security and contribution have their own pages, in English and German.
- The site has an imprint and a privacy policy that describe exactly this setup.
- Every page has its own OG image and structured data.

## Decisions

| # | Decision | Why |
| --- | --- | --- |
| P3-1 | One PR for all of P3 | Maintainer's choice |
| P3-2 | Docs pages are HTML with front matter, one directory per page (`docs/en/docs/<page>/index.html`), split from the one-pager by moving, not rewriting | Tables, code blocks and figures stay byte for byte; Markdown conversion would rebuild every one of them |
| P3-3 | `/en/docs/` becomes the docs start page; an inline script maps every former anchor of the one-pager to its new page | An anchor never reaches the server, so nginx cannot redirect it; the script gets its CSP hash in P4 like the theme script |
| P3-4 | Sponsor links go to `github.com/sponsors/jp1337` only | Maintainer's choice; the business receives GitHub Sponsors income |
| P3-5 | Mail to `info@openwhistle.net` stays on the own mail server on root01xvp | Maintainer's answer; the privacy policy names no further recipient |
| P3-6 | Retention periods in the privacy policy come from wdk-ansible: journald 30 days on the server; the log archive keeps container lines (`tier=ops`) 90 days and mail delivery lines (`tier=forensics`) 365 days; purpose: security and forensics | Read from `wdk-ansible/docs/superpowers/specs/2026-08-30-logging-pipeline-design.md` § 6 on 2026-10-04; the maintainer: Loki serves forensics only |
| P3-7 | The demo's footer links the imprint and the privacy policy, in demo mode only | Request relayed from the wdk-ansible session; the demo runs on the same server under the same operator |
| P3-8 | The FAQ stays on the home page, after the spec order | It answers real search queries |
| P3-9 | No release in P3; the demo-footer change is listed under CHANGELOG `[Unreleased]` | It is visible only in demo mode, and the demo runs `edge` |

## Structure

### Docs (English only)

| Section | Pages |
| --- | --- |
| Get started | `requirements/`, `install/` (Docker Compose steps 1–4 and the setup wizard), `first-report/` |
| How-to | `kubernetes/`, `tls-proxy/`, `selinux/`, `onion/`, `ldap/`, `oidc/`, `s3/`, `clamav/`, `notifications/`, `retention/`, `multi-tenancy/`, `upgrade/`, `rotate-key/`, `lost-authenticator/`, `demo-mode/` |
| Guides by role | `admin/` (reports, users and roles, audit log, categories and locations, statistics, deadlines, telephone channel); `whistleblower/` (submit, check status, staying safe) |
| Reference | `configuration/` (from `docs/_data/config.yml`, checked against `Settings` both ways), `images/` (tags, signatures), `roles/`, `status-workflow/`, `limits/`, `security-headers/`, `dpa-template/` |
| Explanation | `anonymity/` (four layers), `rate-limiting/`, `outbound/` (what leaves the host), `timestamps/`, `onion-trust/`, `redis-sizing/`, `install-count/` |
| Project | changelog, roadmap (exist) |

Rules:

- **Every section moves.** Every `<h3>` of today's one-pager lands on exactly one page.
- **No invented pages.** A page in the table without source text is written briefly from the app's behaviour, or is not
  created. The plan names each one.
- **The three `.md` pages are absorbed.** `security-policy` goes into the Security page, `hinschg-reference` into
  Compliance › HinSchG. `dpa-template` stays as reference and loses `noindex`.
- **The `docs` layout builds the navigation:**
  - sidebar from `nav.yml`, with groups as `<details>` and the search on top;
  - "on this page" built at build time;
  - previous/next and "Edit on GitHub".
- **Search** uses Pagefind from PyPI, run at build over the docs. Its UI is our own, small, on `pagefind.js`: the `/`
  key, a `<dialog>`, and `?highlight=`. The P0 spike showed it runs under the docs CSP.

### New pages

| EN | DE |
| --- | --- |
| `/en/compliance/`, `eu-directive/`, `hinschg/` | `/de/compliance/`, `eu-richtlinie/`, `hinschg/` |
| `/en/security/` | `/de/sicherheit/` |
| `/en/contribute/` | `/de/mitmachen/` |
| `/en/privacy/` | `/de/datenschutz/` |
| `/impressum/` (German; footer label "Legal notice (Impressum)" on English pages) | — |
| `/.well-known/security.txt` | — |

- **Nav:** Compliance · Security · Docs · Blog, the language switch, one emerald button "Try the demo". At most three
  levels.
- **Footer:** Impressum · Privacy · security.txt · GitHub · Sponsor · Contribute.
- **Redirects:** every old URL and every old docs anchor reaches a page.
- **Root redirect:** `/` by `Accept-Language` is P4 (nginx).

## Content

### Home (EN and DE, one structure)

1. One-sentence statement.
2. The emerald block with the three promises (redesign spec, Positioning):
   - anonymity you can verify instead of trust;
   - built for the corporate reporting office;
   - free and under your own control.
3. The reporting flow (`home-flow` diagram).
4. Core features: today's tables, shortened.
5. Compliance by jurisdiction: EU, HinSchG and "further jurisdictions" cards, linking to `compliance/`.
6. "Verify it": the open gap (one maintainer, no external audit), linking to `security/` and `contribute/`.
7. Demo or install.
8. FAQ (P3-8).

### Compliance

- **Overview.** The law-agnostic core (ISO 37002), and what OpenWhistle covers and what it does not. Not covered:
  - legal advice;
  - the external channel to authorities;
  - appointing the responsible persons;
  - the organisation's process.
- **EU Directive and HinSchG.** Each page has one table: requirement → feature → the docs page that shows it. The rows
  cover:
  - acknowledgement within 7 days and feedback within 3 months;
  - confidentiality;
  - documentation;
  - deletion;
  - anonymous reports.
- **Every page** says "no legal advice". Every claim links to its proof.

### Security and Contribute

- **Security:**
  - Why trust it: anonymity layers, signed images, scans, mutation audit, linking into the docs explanations.
  - Open gaps: one maintainer, no external audit, and the known limits the docs name.
  - How to report a vulnerability: `security-policy.md`, `SECURITY.md`, a private GitHub advisory, `security.txt`.
- **Contribute:** where reviews help most (crypto, anonymity layers, reveal flow), first issues, translations, and
  sponsoring (P3-4).

### Legal pages

- **Imprint.** Exactly the text in the redesign spec § Legal pages: c/o address, e-mail, no telephone.
- **Privacy policy.** German is authoritative; English is a translation. It starts from the provider text in
  `docs-tech/legal/datenschutz-provider-2026-10-01.txt` with every generator section that does not apply removed. It
  states exactly:
  - the controller, as in the imprint;
  - Hetzner Online GmbH as processor (Art. 28 GDPR);
  - server logs: time, path, status, referrer host; retention per P3-6; legal basis Art. 6 (1) f;
  - no cookies, no analytics, no external resources (self-hosted fonts);
  - the theme choice in `localStorage` (§ 25 (2) no. 2 TDDDG); search runs in the browser;
  - e-mail: own mail server, delivery logs per P3-6;
  - GitHub Sponsors as an external link: GitHub, not this site, processes any payment;
  - `demo.openwhistle.net`: same operator and server, no IP logs, data deleted every 6 hours;
  - data subject rights and the right to complain to a supervisory authority.
- **App (P3-7).** In demo mode only, the footer links `https://openwhistle.net/impressum/` and the privacy policy in the
  page's language.

## SEO

| Element | Built from | Check |
| --- | --- | --- |
| Title ≤ 60, description 120–160 characters, unique | front matter | length and uniqueness across the site |
| OG image per page | `build_site.py` with Pillow at build: 1200×630, Signal ground, page title in Sora, K3 | exists, 1200×630, `og:image` points to it |
| JSON-LD | home `SoftwareApplication` + `Organization`; blog `BlogPosting` (author, `datePublished`, `dateModified`); docs `BreadcrumbList` | valid JSON, required fields |
| Atom feeds | `/en/blog/feed.xml`, `/de/blog/feed.xml` | valid; every post listed |
| canonical, hreflang, sitemap, redirects | P1 machinery, extended to the new pages | as in P1 |
| External links | weekly workflow, stdlib script, opens an issue on failure | `workflow_dispatch` run in the PR |

## Guards

Each guard goes through `scripts/mutation_audit.py`.

| Guard | Catches |
| --- | --- |
| Docs pages and `nav.yml` match both ways | An orphaned page or a dead nav entry |
| Every former one-pager anchor resolves to a page | A broken deep link |
| Every `<h3>` of the one-pager is on exactly one docs page | Content lost or duplicated in the split |
| Configuration reference = `Settings`, both ways | An undocumented or stale setting |
| No placeholder in imprint or privacy policy | Generator text shipped |
| The privacy policy names Hetzner, the four log fields and every P3-6 period; it contains no cookie, analytics, Google or consent boilerplate | A policy that describes another site |
| The demo footer shows the legal links only in demo mode | Legal links on an operator's own installation |
| Title, description, OG image, JSON-LD and feed checks in § SEO | SEO regressions |

**Standing checks in every task** (lessons from P2b):

- axe on every page in both themes;
- forced colours;
- one theme twin per figure;
- 360 px without sideways scroll;
- the screen comparison for every pure restructure;
- each task looks at its pages in a browser, dark first.

The Chrome check of every page at Full HD and the final review close the PR.

## Out of P3

Page budget, `nginx.conf`, CSP hashes and the root `Accept-Language` redirect belong to P4. DNS, vhost and HSTS
preload belong to P5.
