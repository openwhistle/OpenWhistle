# Diagrams

One `.mmd` file per picture. `node scripts/render_diagrams.mjs` renders each to two
SVGs — `<name>-light.svg` and `<name>-dark.svg` — under `docs/img/diagrams/`, via
`npx @mermaid-js/mermaid-cli` pinned to an exact version, in the palette read from
`docs/assets/css/docs.css`. Both are committed; `node scripts/render_diagrams.mjs --check`
fails if a source changed without a re-render. That check, and everything else
that must hold about a committed diagram, runs as a pytest test in
`tests/test_diagrams.py` — CI needs no node at all for it.

Pre-rendered rather than shipped as mermaid.js: the runtime bundle is over 3 MB to
draw a handful of boxes, the docs site makes no third-party requests, and an SVG
cannot shift the layout after paint.

Diagrams are named files rather than fenced blocks inside a page, so a page can
reference one by a stable name, several pages can share one, and the source of a
picture is reviewable on its own in a diff.

## Rendering

```sh
node scripts/render_diagrams.mjs          # render everything
node scripts/render_diagrams.mjs --check  # fail if a diagram is missing or stale
```

Needs a local Chromium — the script looks for one under `~/.cache/ms-playwright`
first (the same cache `uv sync --extra dev`'s Playwright dependency populates),
then a few system paths, then `PLAYWRIGHT_CHROMIUM` if set. Rendering is a local,
one-time step before a commit; nothing at request time or in CI runs node.

## Embedding as a themed figure

Both variants go in the markup; CSS shows the one matching the page's
`data-theme`, the same attribute the theme toggle already sets on `<html>` (see
"Why not `<picture>`" below). The CSS lives once in `docs/assets/css/docs.css`;
screenshots use the same pattern with `doc-shot`, `shot-light` and `shot-dark`.
`tests/test_docs_figures.py` fails when a diagram or screenshot is on disk but not
embedded with both twins, or an image has no alt text.

```html
<figure class="diagram">
  <img class="diagram-light" src="img/diagrams/architecture-light.svg"
       alt="Describe what the diagram shows" loading="lazy">
  <img class="diagram-dark" src="img/diagrams/architecture-dark.svg"
       alt="Describe what the diagram shows" loading="lazy">
</figure>
```

```css
.diagram-dark { display: none; }
[data-theme="dark"] .diagram-light { display: none; }
[data-theme="dark"] .diagram-dark { display: block; }
```

The `alt` text is not optional, and both twins carry the same one. The hidden
twin is `display: none`, which takes it out of the accessibility tree, so each
theme announces exactly one picture; an empty `alt` on the dark twin would leave
dark-theme screen-reader users with none. Write what the diagram shows, not
"diagram" or the file name.

## Why not `<picture>`

A `<picture>` with `<source media="(prefers-color-scheme: dark)">` reports the
reader's **operating system**, while the site's theme is a `data-theme` attribute
set by the toggle in the nav. The two disagree as soon as anyone uses the toggle:
a reader on a dark OS who chose the light documentation would get dark diagrams
on a light page, permanently, because a matching `<source>` always wins over an
`<img src>` reassigned by script.

Two `<img>` elements sidestep the media query entirely — both variants are in the
markup and CSS picks one from `[data-theme]`, the same signal that themes
everything else on the page. `loading="lazy"` keeps the hidden variant off the
wire, since it never enters the viewport.

## Palette and fonts

Colours are the CSS custom properties from `docs/assets/css/docs.css`'s `:root` (light) and
`[data-theme="dark"]` blocks, copied into `scripts/render_diagrams.mjs`'s `THEMES`
object rather than read from the stylesheet at render time — a design change
that misses this file fails `tests/test_diagrams.py::test_palette_matches_docs_site`
immediately, where reading the stylesheet would need a rebuild to reveal
anything, and rendering is not byte-reproducible.

Diagram text uses a generic `system-ui, sans-serif` stack, not the docs site's
`Sora` — deliberately. `mermaid-cli` only appends a `-C cssFile`'s content to the
finished SVG's `<style>` *after* `mermaid.render()` has already measured and
fixed every node's box size, so a `Sora` `@font-face` supplied that way can never
be loaded in time to affect the layout it would need to affect: it renders with
boxes sized for the fallback font while showing `Sora`'s (wider) glyphs, and
labels clip. Verified by rendering a two-node diagram both ways. `system-ui`
throughout — measured and displayed in the same font — is the one combination
`mermaid-cli` renders correctly, and it references no font file and no URL at
all, so `tests/test_diagrams.py`'s check for an external reference passes
trivially. Revisit if a future `mermaid-cli` adds a pre-render style hook.

## Adding a diagram

1. Write `docs/_diagrams/<name>.mmd`. Keep it small: legible at roughly 900 px
   wide, which means short labels and few nodes — a diagram that needs a
   paragraph of labels to read is two diagrams.
2. `node scripts/render_diagrams.mjs`.
3. `uv run pytest tests/test_diagrams.py` — confirms both SVGs exist, are current,
   use only the docs palette, and carry no external reference or `<script>`.
4. Commit the `.mmd` and both SVGs together.
