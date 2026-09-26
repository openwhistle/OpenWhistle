# Documentation standards from easywall — plan

Adopt all thirteen easywall documentation standards (user decision, 2026-09-26).
Source of each: `../easywall` — `CONTRIBUTING.md` "Documentation", `CLAUDE.md`
rules table, `scripts/prose-check.mjs`, `scripts/render-diagrams.mjs`,
`docs/_diagrams/README.md`, `docs-tech/i18n-review.md`, the `TestEvery*` and
`TestScreenshots*` guard tests.

Integration branch: `docs/standards` from `main`. Each lane works in its own
worktree off that branch; the controller merges.

## Rulings

- **Prose scope** (3): the user documentation — `docs/docs.html`,
  `docs/roadmap.html`, `docs/security/*.md`, `docs/hinschg_reference.md`.
  Landing pages and the German blog are marketing and articles, as easywall's
  landing page is outside `docs/_docs`. Cost if wrong: a later branch extends
  the scope list.
- **Tooling is Python** where easywall uses node, except rendering Mermaid
  (needs mermaid-cli, a local-only step). Every *check* runs in pytest, so CI
  needs no node for it.
- **Themed figures**: every diagram and screenshot exists as `-light` and
  `-dark`; the page shows the one matching `data-theme` via CSS, not
  `<picture>` (easywall's reason: the media query reports the OS, the toggle
  sets the attribute).
- **Only lane B edits `docs/docs.html` prose.** Lane F may add one nav item to
  every page; the controller resolves that merge.

## Lanes

| Lane | Standards | Delivers | Phase |
| --- | --- | --- | --- |
| A | 2, 3, 6, 7, 12, 13 | `CONTRIBUTING.md`; `tests/test_docs_prose.py` (≤ 30 words per sentence, average < 18); `tests/test_every_page_is_documented.py` (from the FastAPI router); `docs-tech/i18n-review.md`; CLAUDE.md pointer; docs-tech pages without dependency version numbers | 1 |
| C | 4 | `docs/_diagrams/*.mmd`, `scripts/render_diagrams.mjs`, `docs/img/diagrams/*-{light,dark}.svg` with `data-source-digest`; staleness and palette tests | 1 |
| D | 5 | `scripts/take_screenshots.py` against the review stack; `docs/img/screens/*-{light,dark}.png`; tests: every screenshot referenced, viewport above the admin two-column breakpoint | 1 |
| E | 10 | `tests/e2e/test_docs_behaviour.py`: theme toggle persists, mobile nav opens, scroll-spy marks the current section | 1 |
| F | 11 | `scripts/render_changelog.py` → `docs/changelog.html`; tests: the page matches `CHANGELOG.md`, every version has a link definition; nav item on every page | 1 |
| B | 3, 4, 5, 7 applied | `docs.html` (and the other scoped pages) rewritten to pass lane A's tests; diagrams and screenshots embedded; every route documented | 2 |

Already in place (1, 8, 9): `test_the_technical_docs_are_not_published`,
`test_every_setting_has_a_row_in_the_docs_env_table`, the nav and version tests.

## Done when

Full suite, e2e, markdownlint and codespell green; Chrome check of every website
page (Full HD, both themes; 390 px with Playwright); one PR, merged, branch
deleted.
