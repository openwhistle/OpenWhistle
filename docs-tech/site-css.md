# Changing the site's CSS

How-to: change a stylesheet under `docs/assets/css/` and prove what it changed on screen.

## Which sheet

| Sheet | Holds | Linked by |
| --- | --- | --- |
| `tokens.css` | every custom property, light and dark; names follow `DESIGN.md` | every page, first |
| `fonts.css` | the self-hosted `@font-face` rules | every page |
| `base.css` | reset, nav, footer, callout, motion, forced colours | every page |
| `home.css` | the two landing pages | `css: [home]` |
| `docs.css` | the docs layout: sidebar, content type, code blocks, tables | `css: [docs]`, and the text pages |
| `post.css` | a blog post | `css: [post]` |
| `page.css` | only what the text pages (roadmap, changelog, compare, blog index, 404) add to `docs.css` | `css: [docs, page]` |

`tests/test_site_css.py` holds the table: a value is a token, a corner is a `--radius-*` token or 0, an edge
is a `box-shadow` ring, `page.css` repeats no `docs.css` selector, and no rule styles a class no page uses.

## Prove the change: `compare_site_screens.py`

```bash
uv run python scripts/compare_site_screens.py --base main
uv run python scripts/compare_site_screens.py --base main --only /en/docs/ --out /tmp/shots-docs
```

It builds `--base` and the working tree, screenshots every page light and dark at 1920 and 390 px, and
compares the pixels. Run it before every CSS commit.

| Change | Expect |
| --- | --- |
| A refactor (move, merge, delete a dead rule) | exit 0, `0 differing shot(s)` |
| A visible change | exit 1; every listed shot is one you meant, with a `diff-*.png` to look at |

- A shot listed with a size change (`a size change counts every extra pixel`) moved everything below it;
  look at the first difference, not the count.
- A capture that times out: run that page alone with `--only`.
- `--out` must be new or empty, so an old run is never read as this one.
- From a `git worktree`, call the repository's own `.venv/bin/python`: the worktree has no environment
  of its own, and `uv run` there builds one without Playwright.

Incident: P2b's `docs.css`/`page.css` merge was declared "the same" from the diff; the compare proved it
(0 of 104 shots) before the radius change, which then listed every page for the nav button alone.

## A new character in a CSS `content:` string

`scripts/build_site.py` subsets the fonts to the characters the built pages draw. It reads page text, not
CSS, so a character that only a `content:` string draws (an arrow, a bullet) must be added to
`FONT_TEXT_EXTRA`, or the browser falls back to another font for that one glyph.
`tests/test_site_fonts.py` checks the page text against the subset, not `content:` strings: this step is
yours (today: `—`, `+`, `−`).
