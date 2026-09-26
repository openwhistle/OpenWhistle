# SEO & Marketing (ongoing, all versions)

> Goal: rank for "Whistleblower Tool kostenlos", "Whistleblower Tool Open Source",
> "Meldestelle HinSchG kostenlos", "interne Meldestelle Software" and equivalents
> in other EU languages. The `openwhistle.net` domain has been registered for
> ~1 year, which gives a head start on domain authority.

## Technical SEO

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

## Content SEO

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

## Community & Distribution

- [ ] **Producthunt launch** — prepare a Product Hunt launch post; coordinate
  with the community for upvotes on launch day
- [ ] **Hacker News "Show HN"** — post once v1.0 is reached
- [ ] **German compliance / legal community** — share in DACH-focused compliance
  Slack/Discord servers, LinkedIn groups for compliance officers and legal teams
- [ ] **"Powered by OpenWhistle" badge** — optional badge operators can put on
  their reporting portal, linking back to openwhistle.net (backlink building)
