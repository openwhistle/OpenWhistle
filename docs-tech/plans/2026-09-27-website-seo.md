# Website: standards, SEO and backlinks — plan

Goal (maintainer, 2026-09-27): the whole website follows the documentation
standards (`CONTRIBUTING.md`), is correct against the code, and ranks for
"open source whistleblower tool", "free whistleblowing software",
"kostenloses Hinweisgebersystem", "Whistleblower Tool kostenlos" and
"Hinweisgebersystem Open Source". Backlinks are part of it.

## Competition (web search, 2026-09-27)

| Project | What it is | Where it is listed |
| --- | --- | --- |
| GlobaLeaks | AGPL-3.0, Python; the reference open source platform | #1 for the English keywords; awesome-selfhosted, AlternativeTo, PrivacyTools.io, ownware.io, EU OSOR |
| opensource-hinweisgeberportal.de | managed service built on GlobaLeaks (splice) | strong on German keywords, one landing page per keyword |
| SecureDrop, Hush Line | journalism; hosted tip line | English queries |
| OpenWhistle | | #3 for "kostenloses Hinweisgebersystem open source"; on none of the lists above |

## Rulings

- **Comparisons state verifiable facts only**, each with its source and date:
  licence, language, hosting model, HinSchG deadline tracking, languages. No
  claim about a competitor's quality (UWG §6 for the German pages; honesty for
  all). GlobaLeaks is named as the mature reference it is.
- **Prose limits extend to the landing pages and the blog**, in both
  languages: readability is a ranking signal, and the reader is the same one.
- **File ownership**: lane S owns every `<head>`, `sitemap.xml`, `robots.txt`
  and the SEO guard tests; lanes EN and DE own page bodies and new pages
  (whose heads follow the existing pattern; lane S's tests hold them).
- **Outward-facing steps** (directory submissions, pull requests to lists) are
  prepared as texts, not sent: the maintainer submits or approves each.

## Lanes

| Lane | Delivers |
| --- | --- |
| S | keyword map per page; titles, descriptions, canonical, hreflang + x-default, OG/Twitter, JSON-LD (SoftwareApplication, Organization, BreadcrumbList, FAQPage = visible FAQ, Article with dates) on every page; sitemap with lastmod; `tests/test_seo.py`; backlink kit in `docs-tech/seo-marketing.md` |
| EN | `index.html` body rewritten to the standards and the keywords; new page `open-source-whistleblowing-software.html` (honest comparison with GlobaLeaks, SecureDrop, Hush Line) |
| DE | `de/index.html` body; blog articles corrected to 2.0.x and 2026; comparison article updated (GlobaLeaks, managed GlobaLeaks services); new article on the free-HinSchG-channel query |

## Done when

All guard tests green, Chrome check of every page (both themes, Full HD;
390 px with Playwright), one PR, merged, branch deleted.
