# SEO and backlinks

Maintainer page, never published. What each page ranks for, what every `<head>` must carry, and every place
OpenWhistle can be listed, with the text to paste. Nothing here is submitted until the maintainer does it.

## Keyword map

One primary keyword per page; no two pages share one. The title starts with it, the description carries it.

| Page | Primary | Secondary |
| --- | --- | --- |
| `/en/` | open source whistleblower software | free whistleblowing software, open source whistleblower tool, HinSchG software |
| `/en/docs/` | self-hosted whistleblowing | whistleblowing Docker Compose, whistleblower platform configuration |
| `/en/roadmap/` | OpenWhistle roadmap | whistleblowing software roadmap |
| `/en/changelog/` | OpenWhistle changelog | OpenWhistle release notes |
| `/en/compare/` | GlobaLeaks alternative | SecureDrop alternative, open source whistleblowing software compared, Hush Line |
| `/de/` | Hinweisgebersystem Software | HinSchG Software, Hinweisgeberschutzgesetz Software, interne Meldestelle Software, Hinweisgeber Software; kostenloses Hinweisgebersystem, Hinweisgebersystem Open Source as differentiator |
| `/de/blog/` | HinSchG Blog | Hinweisgeberschutz Praxis |
| `/de/blog/hinschg-compliance-leitfaden/` | HinSchG Pflichten | interne Meldestelle Pflicht, HinSchG Fristen |
| `/de/blog/interne-meldestelle-einrichten/` | interne Meldestelle einrichten | Hinweisgebersystem Docker, interne Meldestelle Anleitung |
| `/de/blog/whistleblower-software-vergleich/` | Hinweisgebersystem Anbieter Vergleich | Hinweisgeberschutzgesetz Software Vergleich, Anbieter Hinweisgebersystem, Hinweisgebersystem Anbieter, GlobaLeaks |
| `/de/blog/hinweisgebersystem-dsgvo-eu-hosting/` | Hinweisgebersystem EU-Hosting | DSGVO-konformes Hinweisgebersystem, Hinweisgebersystem Verschlüsselung, Hinweisgebersystem mehrsprachig |
| `/de/blog/was-ist-neu-in-2-0/` | OpenWhistle 2.0 | Hinweisgebersystem Update |
| `/de/blog/interne-meldestelle-kostenlos/` | interne Meldestelle kostenlos | HinSchG Meldekanal kostenlos |
| `/de/blog/metadaten-entfernen-ohne-beweise-zu-veraendern/` | Metadaten entfernen Hinweisgebersystem | Foto Metadaten anonyme Meldung |
| `blog/en.html` and the seven English twins | the German page's primary, in English | none yet: no Search Console data for the English blog |

The blog is bilingual since 2026-09-27: every German article has an English twin (hreflang, x-default English;
`test_every_blog_page_exists_in_english_and_german`). The German URLs were kept because Pages cannot redirect with
a 301; the English slugs are the English keyword. Re-cut the English rows once Search Console shows their queries.

The comparison page's slug carries the category term, but its primary is the comparison query: `index.html`
already owns "open source whistleblower software", and two pages on one query split its ranking.

The German map was re-cut on 2026-09-27 against Search Console (below). "kostenlos" and "Open Source" carry almost
no volume: they stay in the title and description of `de/index.html` as the differentiator, not as its primary.
"interne Meldestelle Software" moved from the set-up guide to the landing page, whose intent it matches.
The EU-hosting article is its own page, not a landing section: the question queries have their own intent, and
a section would have put a second primary on `de/index.html`.

### Search Console evidence

Maintainer export, openwhistle.net, the three months up to 2026-09-27. Position before the re-cut.

| Query | Clicks | Impressions | Position | Page now targeting it |
| --- | --- | --- | --- | --- |
| openwhistle | 15 | 46 | 3.2 | brand, see below |
| open whistle | 2 | 19 | 4.2 | brand |
| hinweisgebersystem software | 0 | 540 | 25.8 | `/de/` |
| hinweisgebersystem anbieter | 0 | 315 | 18.1 | comparison article |
| anbieter hinweisgebersystem | 0 | 180 | 17.7 | comparison article |
| hinweisgeberschutzgesetz software | 0 | 135 | 20.7 | `/de/` |
| hinweisgebersystem anbieter vergleich | 0 | 131 | 18.5 | comparison article |
| hinweisgeber software | 0 | 115 | 29.1 | `/de/` |
| hinschg software | 0 | 98 | 19.4 | `/de/` |
| hinweisgeberschutzgesetz software vergleich | 0 | 60 | 15.5 | comparison article |
| whistleblowing system anbieter | 0 | 47 | 74.2 | none (English term on German pages) |
| wer bietet dsgvo-konforme hinweisgebersysteme mit eu-hosting an? | 0 | 31 | 10.2 | EU-hosting article, DE FAQ |
| welche anbieter sind auf richtlinienkonformes hosting … in der eu spezialisiert? | 0 | 29 | 9.3 | EU-hosting article |
| interne meldestelle software | 0 | 18 | 19.7 | `/de/` |
| wer bietet hinweisgebersysteme … mit sicherem hosting innerhalb der eu? | 0 | 9 | 9.4 | EU-hosting article |
| wer verkauft hinweisgeber-tools mit eingebauter verschlüsselung und dsgvo-konformität? | 0 | 6 | 9.7 | EU-hosting article, DE FAQ |
| whistleblower software open source | 0 | 6 | 13.7 | `index.html` |
| hinweisgeberschutzgesetz checkliste | 0 | 6 | 22.8 | `/de/blog/hinschg-compliance-leitfaden/` |
| beste kostenlose whistleblowing tools | 0 | 6 | 3.7 | `index.html` |
| hinweisgebersystem kostenlos | 0 | 2 | 2.0 | `/de/` |

About 1,300 impressions at positions 15-29 brought no click: page two and three. The question queries sit at 9-10 with
no click, answered by AI Overviews; each now has an answer whose first sentence can be quoted. Queries of five
impressions or fewer (English "is it open source?", "i want to host it myself") are answered by the two new
questions in the `index.html` FAQ. The portals ranking for "Hinweisgebersystem Anbieter Vergleich" are trusted.de,
OMR Reviews, die-hinweisgeber-meldestelle.de and Capterra, all in the backlink table below.

Re-check the positions in Search Console four weeks after the merge; a query that has not moved is a signal for
the page, not for more keywords.

### Brand query

"openwhistle" ranks 3.2. Above openwhistle.net stand GitHub forks and old paths (`openwhistle-dev/OpenWhistle`,
`jp1337/OpenWhistle`, `zbridges-valid8/OpenWhistle`) and unrelated products of the same name (openwhistle.pt,
openwhistle.pro, `Artaeon/openwhistle`). Maintainer actions, prepared, not run:

| Action | Command or text |
| --- | --- |
| Repository homepage field | `gh repo edit openwhistle/OpenWhistle --homepage https://openwhistle.net` |
| README first line under the title links the site | `**[openwhistle.net](https://openwhistle.net)**: free, open source whistleblowing software (HinSchG, EU 2019/1937).` |
| `jp1337/OpenWhistle` | the old path of this repository: the API redirects it to `openwhistle/OpenWhistle` (checked 2026-09-27). Never create a new repository under that name: it would break the redirect |
| `openwhistle-dev/OpenWhistle` | a separate, unrelated repository (not a fork, no admin rights; checked 2026-09-27): no action |
| `zbridges-valid8/OpenWhistle`, same-name products | a fork, and products that are not the maintainer's: no action; the homepage field and backlinks are the answer |

## The head contract

`tests/test_seo.py` holds every `docs/**/*.html` page, found by glob, so a new page is covered the day it lands.

| Rule | The incident behind it |
| --- | --- |
| One `<title>` of at most 60 characters, primary keyword first | Titles ran past 100 characters and were cut in results |
| A description of 120-160 characters, unique on the site | The English home page's description was German |
| `<html lang>` is `en` or `de`; `og:locale` matches | The English home page declared `og:locale` `de_DE` |
| Canonical = the address Pages serves the file at: `/en/`, `/de/`, `/<lang>/<page>/` | Sitemap, canonical and nav must name one URL |
| hreflang `en`/`de`/`x-default` only where a translation exists, reciprocal | The German blog index named the English home page its `en` version |
| `og:image` is `og-image.png`, 1200×630, with width, height and alt | It was a blank navy rectangle: every shared link showed an empty card |
| JSON-LD parses; no `aggregateRating` or `review` | OpenWhistle has no ratings; invented ones break Google's policy |
| `SoftwareApplication.softwareVersion` = `app_version` on both landing pages | A release that forgets it advertises the old version |
| Every article carries `BlogPosting` with `datePublished`, `dateModified`, `inLanguage` | Articles had no `dateModified`; one carried `HowTo`, which Google no longer shows |
| `FAQPage` only where the FAQ is visible, entry for entry | Held by `test_faqpage_jsonld_matches_visible_faq_one_to_one` |
| Nothing in a head loads from another host; fonts come from `docs/fonts/` | A visit must not reach a third party |
| `404.html` is `noindex`, has no canonical, links root-relative | Pages serves it at every missing path |

When a page changes:

1. A body edit to an article bumps `dateModified` and `article:modified_time`, together.
2. `scripts/build_site.py` writes `sitemap.xml`; `lastmod` from git.
3. The changelog body is built from `CHANGELOG.md`; never edit the built page.

`meta keywords` is not used: Google ignores it, Bing reads it as a spam signal.

### Head for the planned comparison page

`docs/en/compare/index.html` did not exist when this contract was written. Its head copies
`docs/en/roadmap/index.html`'s head, with:

| Field | Value |
| --- | --- |
| `<title>` | `GlobaLeaks Alternatives: Open Source Compared \| OpenWhistle` (59 characters) |
| description | 120-160 characters naming GlobaLeaks, SecureDrop and Hush Line, facts only |
| canonical, `og:url` | `https://openwhistle.net/en/compare/` |
| hreflang | none, unless a German translation exists; then en/de/x-default on both |
| JSON-LD | `BreadcrumbList` (OpenWhistle, then the page); `FAQPage` only if the page shows an FAQ |
| sitemap | `scripts/build_site.py` writes it; the test fails until the page is listed |

## Backlink targets

Status as of 2026-09-27. "Verified" means the page was fetched or found in search that day.

| Target | URL | What it needs | Status | Verified |
| --- | --- | --- | --- | --- |
| awesome-selfhosted | github.com/awesome-selfhosted/awesome-selfhosted-data | PR adding `software/openwhistle.yml`, human-written | not submitted | yes: rules, template, GlobaLeaks entry |
| AlternativeTo | alternativeto.net/software/globaleaks/about/ | account, "Suggest new application", then "alternative to" | not submitted | yes: GlobaLeaks page, 8 alternatives, OpenWhistle absent |
| PrivacyTools.io | privacytools.io/secure-whistleblower/open-source | no form; ask via r/PrivacySoftware or their social channels | not submitted | page yes; submission route not documented |
| ownware.io guide | ownware.io/guides/best-self-hosted-whistleblowing-tools | contact the site; the guide shows no route | not submitted | page yes (GlobaLeaks, SecureDrop, Whistlelink, Confida); contact no |
| SourceForge | sourceforge.net/p/forge/documentation/GitHub%20Importer/ | project via GitHub Importer, release sync | not submitted | yes: importer docs |
| SourceForge / Slashdot directory | sourceforge.net/software/vendors/ | free basic vendor listing, shared with slashdot.org/software | not submitted | yes: vendor page in search |
| G2 | sell.g2.com/create-a-profile | free profile, 3-5 days review, category "Whistleblowing" | not submitted | yes: free profile, category criteria |
| Capterra / GetApp | capterra.com/vendors/ | free vendor form; the network belongs to G2 since 2026 | not submitted | yes: vendor page; Capterra lists GlobaLeaks as free |
| OMR Reviews (DE) | omr.com/en/reviews/category/whistleblowing | free basic profile via form | not submitted | yes: category and free profile |
| trusted.de (DE) | trusted.de/beste-hinweisgebersysteme | no public listing route; contact the editors | not submitted | no: page answers 403 to the fetcher |
| die-hinweisgeber-meldestelle.de | die-hinweisgeber-meldestelle.de/vergleich/ | none: the operator is a provider comparing commercial services only | skip | yes: no open source entry, no suggestion route |
| EU OSOR | interoperable-europe.ec.europa.eu/collection/open-source-observatory-osor | EU Login account; signed-in users create news and solutions | not submitted | yes: "signed-in user can create content" |
| Product Hunt | producthunt.com | maker account, launch post | not submitted | no: not fetched |
| Hacker News Show HN | news.ycombinator.com/showhn.html | something people can try: the demo; title "Show HN: ..." | not submitted | yes: rules |
| German compliance blogs | dmk-ebusiness.de, tech-support.koeln (HinSchG articles) | a pitch to the author | not submitted | articles yes; interest unknown |

### awesome-selfhosted

Criteria checked: free licence (GPL-3.0), tagged releases, first release v0.1.0 on 2026-04-22 (older than four
months), active, installation documented. GlobaLeaks sits in **Communication - Custom Communication Systems**.

The checklist requires a *human* submission, not machine-written: write the PR description yourself. The file
is data:

```yaml
name: OpenWhistle
website_url: https://openwhistle.net/
source_code_url: https://github.com/openwhistle/OpenWhistle
description: Whistleblowing platform for internal reporting channels under EU Directive 2019/1937, with anonymous PIN access and no IP logging.
licenses:
  - GPL-3.0
platforms:
  - Python
  - Docker
tags:
  - Communication - Custom Communication Systems
demo_url: https://demo.openwhistle.net/
```

Rendered, the list line reads:

```markdown
- [OpenWhistle](https://openwhistle.net/) - Whistleblowing platform for internal reporting channels under EU Directive 2019/1937, with anonymous PIN access and no IP logging. ([Demo](https://demo.openwhistle.net/), [Source Code](https://github.com/openwhistle/OpenWhistle)) `GPL-3.0` `Python/Docker`
```

Commit message the repository asks for: `add OpenWhistle`. Facts for the PR text: one item; not in awesome-sysadmin;
first release 2026-04-22; installation at `https://openwhistle.net/en/docs/#installation`; merging takes a week or
more.

### AlternativeTo

Suggest as an alternative to GlobaLeaks (page verified). `alternativeto.net/software/eqs-integrity-line/` answers
404: find EQS and BKMS in the site search before naming them.

- **Name**: OpenWhistle
- **Licence / price**: Open Source (GPL-3.0), Free
- **Platforms**: Self-Hosted, Linux, Docker
- **Tags**: whistleblowing, anonymous-reporting, compliance, self-hosted, privacy
- **Description**:

  > OpenWhistle is a self-hosted whistleblowing platform for internal reporting channels under EU Directive
  > 2019/1937 and the German HinSchG. Reporters get a random PIN instead of an account, no layer logs IP
  > addresses, and every staff account needs multi-factor login. Case handlers see the 7-day and 3-month
  > deadlines. Runs with Docker, PostgreSQL and Redis; GPL-3.0.

### PrivacyTools.io, ownware.io, compliance blogs

> Hello, I maintain OpenWhistle (<https://openwhistle.net>), a GPL-3.0 whistleblowing platform for internal
> reporting channels under EU Directive 2019/1937. Your page on open source whistleblowing tools lists
> GlobaLeaks and SecureDrop. OpenWhistle differs in two facts: it is built around the German HinSchG
> deadlines, and it stores no IP address at any layer. Source: <https://github.com/openwhistle/OpenWhistle>,
> demo: <https://demo.openwhistle.net>. Would it fit your list?

German version for DACH blogs:

> Hallo, ich betreue OpenWhistle (<https://openwhistle.net/de/>), ein kostenloses Hinweisgebersystem unter
> GPL-3.0 für interne Meldestellen nach HinSchG. Es läuft auf dem eigenen Server, speichert keine IP-Adressen
> und zeigt die Fristen nach § 17 HinSchG. Falls Sie über Hinweisgebersysteme schreiben: Quellcode und Demo
> sind frei zugänglich.

### Directories: SourceForge, Slashdot, G2, Capterra, GetApp, OMR Reviews

One text for every profile form. Category: Whistleblowing. Pricing: free, open source. Deployment: on-premise,
self-hosted. Do not tick "cloud/SaaS": there is no hosted offering.

> OpenWhistle is a free, open source whistleblowing platform (GPL-3.0) for internal reporting channels under EU
> Directive 2019/1937 and the German HinSchG. Organisations host it themselves with Docker. Reporters submit
> without an account and return with a random PIN; no IP address is stored. Case handlers work with mandatory
> MFA, two-way messages and deadline tracking. Interface in English, German, French, Spanish and Brazilian Portuguese.

### EU OSOR news item

> **OpenWhistle 2.0: an open source internal reporting channel for the Whistleblowing Directive.**
> Directive (EU) 2019/1937 requires internal reporting channels in organisations with 50 or more employees.
> OpenWhistle is a GPL-3.0 platform that an organisation hosts itself. It stores no reporter IP address, gives
> reporters a random PIN instead of an account, and tracks the 7-day acknowledgement and 3-month feedback
> deadlines. Source code: <https://github.com/openwhistle/OpenWhistle>.

### Show HN

Title: `Show HN: OpenWhistle – self-hosted whistleblowing that stores no IP addresses`. Link the demo, not the
landing page. First comment: why it exists, what the no-IP rule costs, what is missing. Never ask anyone to
upvote: the rules forbid it.

### Product Hunt

Tagline, 60 characters at most: `Self-hosted whistleblowing, no IP logs, free under GPL-3.0`. Launch a release,
not a patch version.

## Own channels

Prepared commands, not run. On 2026-09-27 the repository had no homepage and no topics.

```bash
gh repo edit openwhistle/OpenWhistle \
  --homepage https://openwhistle.net \
  --description "Free, open source whistleblowing software for internal reporting channels (HinSchG, EU Directive 2019/1937). Self-hosted, no IP logs."
gh repo edit openwhistle/OpenWhistle \
  --add-topic whistleblowing --add-topic whistleblower --add-topic whistleblowing-software \
  --add-topic hinschg --add-topic hinweisgeberschutzgesetz --add-topic hinweisgebersystem \
  --add-topic eu-whistleblowing-directive --add-topic compliance --add-topic gdpr \
  --add-topic self-hosted --add-topic open-source --add-topic privacy --add-topic anonymity \
  --add-topic security --add-topic tor --add-topic python --add-topic fastapi \
  --add-topic docker --add-topic postgresql --add-topic redis
```

That is 20 topics, GitHub's maximum.

README badges, next to the existing ones:

```markdown
[![Website](https://img.shields.io/badge/website-openwhistle.net-0c7253)](https://openwhistle.net)
[![Live demo](https://img.shields.io/badge/demo-demo.openwhistle.net-0c7253)](https://demo.openwhistle.net)
```

Registry short description (Docker Hub `kermit1337/openwhistle`, Quay `jp1337/openwhistle`), 100 characters
at most:

```text
Self-hosted whistleblowing platform (HinSchG, EU 2019/1937). No IP logs. Docs: openwhistle.net
```

The full description on both starts with a link to `https://openwhistle.net/en/docs/#installation`, then the
image tags.

Operators who want to credit the project can add `<a href="https://openwhistle.net/">Powered by OpenWhistle</a>`
to their portal's footer. It stays opt-in: a portal that names its software tells attackers what to study.
