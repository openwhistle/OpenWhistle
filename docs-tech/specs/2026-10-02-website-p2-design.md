# Website P2: diagrams and design

Type: explanation + scope. Source: the brainstorming session of 2026-10-02, which refines P2 of
`2026-10-01-website-redesign-design.md` (D10–D12). Every decision below was taken with the maintainer.

## Outcome

The site and the app look like one product. Every diagram in the repository is a draw.io SVG in style C,
light and dark, and Mermaid exists nowhere. The logo is K3 in both the site and the app; the design tokens exist
once and match DESIGN.md.

## Decisions

| # | Decision | Why |
| --- | --- | --- |
| P2-1 | Two PRs: **P2a** diagrams, **P2b** logo, CSS, fonts, DESIGN.md, release 2.1.1 | The diagrams go live sooner; each PR stays reviewable |
| P2-2 | Only the maintainer's assistant edits diagram sources, as XML; no draw.io GUI library | Maintainer's answer. Allows role names instead of hex in the sources |
| P2-3 | Style C: filled cards on `surface`, ink arrows, decision as an outlined diamond, Start and Submit filled `accent`, result filled `ink` | Chosen by the maintainer from three variants rendered with the pinned CLI |
| P2-4 | Style C uses the accent twice per diagram; DESIGN.md records it as an exception to "one accent per screen" | Maintainer's choice; an unrecorded exception reads as a rule breach in the next review |
| P2-5 | Dark-theme nodes sit on `surface-2`, not `surface` | `#131315` on `#08080a` barely separates in the probe |
| P2-6 | An edge label never touches a line; a test measures it | All three probe variants had "yes" on the arrow; the maintainer: a gross production defect |
| P2-7 | The home page's HTML reporting flow (two columns of steps) is replaced by a diagram, EN and DE | Maintainer's choice; alt text and caption carry the content |
| P2-8 | Mermaid is removed **everywhere**, including `docs-tech/` | Maintainer's choice |
| P2-9 | K3 reaches the app as patch release **2.1.1**, together with P2b | Site and app switch logos at the same time |
| P2-10 | `color-scheme: only light` / `dark` per `data-theme`, in site and app | Chrome's Auto Dark Mode recolours every page that does not declare dark support; `light` without `only` does not opt out ([Chrome](https://developer.chrome.com/blog/auto-dark-theme)). The site declares nothing today |

## P2a: diagrams

### Pipeline

```text
docs/_diagrams/<name>[.de].drawio        docs-tech/_diagrams/<name>.drawio
                 └────────────────┬───────────────────┘
           scripts/render_diagrams.py
             1. roles → style C (one table), tokens → light | dark values (DESIGN.md front matter)
             2. podman|docker run rlespinasse/drawio-desktop-headless:<tag>@sha256:…
                -x -f svg --theme light --embed-svg-fonts false
             3. inject Sora 400/700 as a data:font/woff2 subset of the glyphs used (fonttools + brotli)
             4. write the stamp
                                  ▼
       docs/img/diagrams/<name>[.de]-{light,dark}.svg     docs-tech/img/diagrams/<name>-{light,dark}.svg
       (committed; CI needs no draw.io)
```

- **Sources** are draw.io XML. A cell carries a role, never a colour: `style="ow:step"`, `ow:start`, `ow:end`,
  `ow:decision`, `ow:result`, `ow:edge`, plus `ow:lifeline`/`ow:message` for the one sequence diagram. The role
  table in `render_diagrams.py` is style C; changing a look means changing one row.
- **Roles, not hex:** the light palette has `#ffffff` for `canvas`, `surface-2` and `accent-ink`, each with a
  different dark value, so a hex-to-hex map is ambiguous.
- **`--theme light` on every export:** the CLI default `auto` writes `light-dark()`, which inside an `<img>`
  follows the operating system, not the site's toggle.
- **Decision nodes** use `perimeter=rhombusPerimeter` and explicit ports; without it, edges run through the label.
- **Edge labels** carry an `<mxPoint as="offset">` that puts them beside the line.
- **Line breaks by hand** (`&#xa;`), `html=0`, no `whiteSpace=wrap`: `wrap` forces `foreignObject` (P0).
- **Language:** a diagram embedded in a German page has a `.de` source with German labels. Docs diagrams are
  English only (D8).
- **Image pin:** `tag@sha256` in `render_diagrams.py`, updated by a Renovate regex manager. A bump makes every stamp
  stale, so the PR stays red until re-rendered (the axe-core pattern).

### Embedding

| Where | How |
| --- | --- |
| Published site | Two `<img loading="lazy">` (`diagram-light`/`diagram-dark`) chosen by `[data-theme]`, as today |
| `docs-tech/` on GitHub | `<picture>` with `<source media="(prefers-color-scheme: dark)">`, GitHub's documented way; `.markdownlint.json` MD033 allows `picture`, `source`, `img` |

### Diagrams

| Source | Used in | Replaces |
| --- | --- | --- |
| `architecture`, `architecture.de` | docs, `free-internal-reporting-channel`, `interne-meldestelle-kostenlos` | `architecture.mmd` (the German post shows English labels today) |
| `submission-flow` | docs | `submission-flow.mmd` |
| `case-lifecycle` | docs | `case-lifecycle.mmd`; statuses equal `ReportStatus` (test) |
| `admin-login` | docs | `admin-login.mmd` |
| `home-flow`, `home-flow.de` | `/en/`, `/de/` | the HTML `flows-grid` |
| `release-gates` | `docs-tech/release.md` | Mermaid block; `tests/test_local_review.py` reads the new source |
| 3 diagrams | `docs-tech/plans/2026-09-24-v1.6-hardening.md` | Mermaid blocks |
| 2 diagrams, one a sequence | `docs-tech/specs/2026-09-24-v1.6-hardening-design.md` | Mermaid blocks |
| 4 diagrams | `docs-tech/specs/2026-10-01-website-redesign-design.md` | Mermaid blocks |

### Removed

`docs/_diagrams/*.mmd`, `scripts/render_diagrams.mjs`, the mermaid-cli pin and every instruction naming it:
`docs/_diagrams/README.md` (rewritten for draw.io; it moves to `docs-tech/diagrams.md`, being maintainer
documentation), `CONTRIBUTING.md` § Documentation ("Diagrams are Mermaid"). CHANGELOG history stays as written.

### Guards (`tests/test_diagrams.py`, each through the mutation audit)

| Guard | Catches |
| --- | --- |
| Stamp = hash(source + role table + palette + image digest) in every SVG | Changed source or style without a re-render |
| Every edge label's box clear of every edge segment and every node, measured in the SVG with Sora's metrics | "yes" on the arrow |
| Every text line fits its node with padding (Sora metrics) | Clipping: headless draw.io measures with a fallback font |
| Colours of each SVG ⊆ the palette of its theme; dark SVG uses no light-only value | A missed role, a stale palette |
| No `light-dark()`, `foreignObject`, `<script>`, `href`/`url()` to anything but `data:` | Wrong export flags, external requests |
| An image embedded in a `lang="de"` page is a `.de` diagram | English labels on German pages |
| No fenced Mermaid block (a line starting with ```` ```mermaid ````), no `.mmd`, no mermaid-cli reference in any tracked file except CHANGELOG | Mermaid coming back |
| Every diagram is embedded where the table above says (`test_docs_figures.py` extended to `docs-tech/`) | An orphaned or missing SVG |

### Also in P2a

`docs-tech/release.md` gains the Pages check from the P1 outage: `gh api repos/openwhistle/openwhistle/pages`
→ `build_type: workflow`, until P5 removes Pages.

## P2b: logo, CSS, fonts, DESIGN.md, release 2.1.1

Facts measured on 2026-10-02:

- the colour tokens are defined 24 times across 12 site sheets;
- the site names them differently (`--bg-base`) from the app (`--canvas`) and from DESIGN.md (`canvas`);
- `home.css` and `home-de.css` differ in 17 of 1063 lines;
- the site uses Sora 300–700, the app 400–700.

Order: 1 → 2 → 3 → 4 and 5 → 6 → 7. Step 1 is a pure refactor, so the pixel comparison isolates it; every later
change is meant to be visible.

| Step | Design | Proof |
| --- | --- | --- |
| 1 · CSS consolidated | `tokens.css` (tokens once, DESIGN.md names), `base.css` (reset, type, nav, footer, buttons, prose; absorbs `layout.css`), page types `home` (EN = DE), `docs`, `post` (steps, checklist, comparison and mobile tables as components), `page` (blog index, changelog, compare, roadmap, 404). 18 files → about 6 | Playwright screenshots of every built page, before and after, both themes, 1920 and 390 px, pixel-identical |
| 2 · `color-scheme` | `[data-theme=light] { color-scheme: only light }`, `[data-theme=dark] { color-scheme: dark }` in site and app | Test on the built CSS and `app/static/css/site.css` |
| 3 · K3 | One geometry: `M7,3 H17 A4,4 0 0 1 21,7 V13 A4,4 0 0 1 17,17 H11.5 L7,20.8 V17 A4,4 0 0 1 3,13 V7 A4,4 0 0 1 7,3 Z M10.60,11.81 A3.5,3.5 0 1 1 13.40,11.81 L14.50,15.4 H9.50 Z` (evenodd, `viewBox 0 0 24 24`), ink. Inline in `app/templates/base.html` and `docs/_includes/nav.html`; `favicon.svg` (site and app) switches ink by its own `@media (prefers-color-scheme)`. ICO, 32 px PNG, 180 px apple-touch and `github-avatar.png`: ink mark on a white tile, rendered by `scripts/render_icons.py` with Playwright Chromium. `brand.logo_url` stays | Test: the path is identical in every copy (easywall's one-geometry test); raster sizes |
| 4 · Tokens are the truth | Values in `tokens.css` = DESIGN.md front matter; app tokens = the same values through a mapping table (the app CSS keeps its names); no custom property defined outside `tokens.css` | Tests |
| 5 · Fonts | `build_site.py` subsets Sora and JetBrains Mono at build with fonttools: the glyphs of the built site plus ASCII and Latin-1 (search input). Preload Sora 400 and 600. The app keeps the full files from `docs/fonts/` | Test: every glyph of every page is in its weight's subset |
| 6 · DESIGN.md | § Brand rewritten for K3 (the emerald "wax seal" was never built); the rules of the redesign spec § Design; new § Diagrams (style C, the accent exception, labels beside lines, roles not hex); `color-scheme` per theme | Review |
| 7 · Release 2.1.1 | App: K3, favicon set, `color-scheme`. CHANGELOG, version string, mutation audit, Chrome check of app and site at Full HD in **dark and light**, zero open scanning alerts, tag, published images verified | `docs-tech/release.md` |

Outside the repository, for the maintainer: upload `github-avatar.png` as the avatar of the GitHub organisation,
Docker Hub and quay.io by hand; the plan does not script it.

## Out of P2

OG images, the home-page rewrite and every content page belong to P3; the page budget and headers belong to P4.
P2a puts `home-flow` into today's home page so the diagram is embedded and tested from the start; P3 keeps it.
