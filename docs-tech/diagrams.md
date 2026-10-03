# Diagrams

How-to for the maintainer, with its lookup tables. Every diagram is a draw.io XML source rendered to a committed light
and dark SVG; CI checks the SVGs and never runs draw.io.

| Source | Rendered to | Shown by |
| --- | --- | --- |
| `docs/_diagrams/<name>.drawio`, German pages `<name>.de.drawio` | `docs/img/diagrams/<name>-{light,dark}.svg` | two `<img>`; `base.css` picks one from `data-theme`, the site's toggle |
| `docs-tech/_diagrams/<name>.drawio` | `docs-tech/img/diagrams/<name>-{light,dark}.svg` | `<picture>` with `prefers-color-scheme`: GitHub has no toggle |

## Add or change a diagram

1. Write the source. Copy `docs/_diagrams/submission-flow.drawio`: one `mxCell` per element, ids that are words.
2. Give every cell a role as its style, then only layout overrides: `style="ow:edge;exitX=1;exitY=0.5"`.
   A colour in a source is refused.
3. `uv run python scripts/render_diagrams.py <name>`. Needs podman or docker; exit 0 means legible.
4. Look at both SVGs on a dark and a light background.
5. `uv run pytest tests/test_diagrams.py --no-cov`, then commit the source and both SVGs together.

## Roles

| Role | Draws |
| --- | --- |
| `ow:start`, `ow:end` | emerald pill: where a flow begins and ends |
| `ow:step` | filled card |
| `ow:result` | ink card: the one thing the reader keeps (case number + PIN) |
| `ow:decision` | outlined diamond with explicit ports |
| `ow:store` | database cylinder |
| `ow:note` | dashed note: a deadline, a rule |
| `ow:group`, `ow:lane` | box or swimlane that holds other cells |
| `ow:lifeline`, `ow:message` | sequence diagram |
| `ow:edge`, `ow:edge-optional` | arrow, solid or dashed |

A role, not a hex: `#ffffff` is canvas, surface-2 and accent-ink in light, each with its own dark value, so a
colour map would be ambiguous. Colours live in DESIGN.md's front matter; the renderer reads them. Style C was
chosen by the maintainer from three rendered variants; its two accents (start and end) are an exception DESIGN.md
records under "One accent, mostly withheld".

## Rules the tests hold

| Rule | Why |
| --- | --- |
| An edge label has `<mxPoint as="offset" …/>` beside its line | "yes" on the arrow is a production defect; `problems()` measures it |
| A decision uses explicit `exitX/exitY` ports | Without them edges start inside the diamond and cross its label |
| Line breaks by hand (`&#xa;`); no `fontFamily`, `html` or `whiteSpace` in a source | The geometry measures Sora as plain SVG text; `wrap` exports `foreignObject`, which an `<img>` does not render reliably. The renderer refuses all three |
| Only glyphs Sora has: no `→`, `✓` | A fallback font breaks the measured layout |
| A German page shows `.de` diagrams, an English page none | `test_pages_show_diagrams_in_their_own_language` |
| `--theme light` on every export | `auto` writes `light-dark()`, which follows the OS, not the site's toggle |
| Commit both SVGs with their source | `data-ow-stamp` hashes source, theme, roles, palette, image, fonts and both scripts: any change makes the SVG stale |
| Renovate moves tag and digest of the draw.io image together | Every stamp goes stale; the PR stays red until re-rendered |
| A site diagram renders at ≥ 0.85 of its width at 1280–1920 px | A narrow column shrinks 13 px labels below 11 px; `tests/e2e/test_docs_diagrams.py` measures it |
