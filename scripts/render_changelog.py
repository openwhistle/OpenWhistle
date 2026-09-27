#!/usr/bin/env python3
"""CHANGELOG.md -> docs/changelog.html.

CHANGELOG.md stays the single source at the repository root: GitHub reads it,
and so does release tooling. This renders it as one page in the site's own
design (the shell copied from docs/roadmap.html), newest release first.

    uv run python scripts/render_changelog.py           write docs/changelog.html
    uv run python scripts/render_changelog.py --check    fail if the committed
                                                          page is not what this
                                                          would write

The output is committed, like docs/roadmap.html: the site is static HTML with
no build step in CI.

CHANGELOG.md uses a small Markdown subset, and this parses exactly that:
h2 (`## [x.y.z] — date`) and h3 (`### Section`) headings, paragraphs, bullet
lists nested one level deep, **bold**, *italic*, `code`, [text](url) links,
and reference-style link definitions (`[x.y.z]: https://...`) at the foot of
the file. Nothing else is needed because nothing else appears there; see
`tests/test_changelog_page.py` for the self-test that pins this.
"""

from __future__ import annotations

import html
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "CHANGELOG.md"
OUT = ROOT / "docs" / "changelog.html"

# "## [2.0.0] — 2026-09-26" and "## [Unreleased]" (no date) both occur.
HEADING_RE = re.compile(r"^## \[([^\]]+)\](?:\s*[—-]\s*(\S+))?\s*$")
SUBHEADING_RE = re.compile(r"^### (.+)$")
LINK_DEF_RE = re.compile(r"^\[([^\]]+)\]:\s*(\S+)\s*$")


class Version:
    def __init__(self, name: str, date: str) -> None:
        self.name = name
        self.date = date
        self.lines: list[str] = []


def parse(markdown: str) -> tuple[list[Version], dict[str, str]]:
    """Split CHANGELOG.md into per-version bodies and the link definitions."""
    versions: list[Version] = []
    link_defs: dict[str, str] = {}
    current: Version | None = None
    for line in markdown.splitlines():
        link_def = LINK_DEF_RE.match(line)
        if link_def:
            link_defs[link_def.group(1)] = link_def.group(2)
            continue
        heading = HEADING_RE.match(line)
        if heading:
            current = Version(heading.group(1), heading.group(2) or "")
            versions.append(current)
            continue
        if current is not None:
            current.lines.append(line)
    return versions, link_defs


def slug(version_name: str) -> str:
    """A stable heading id: "2.0.0" -> "v2-0-0", "Unreleased" -> "unreleased"."""
    if version_name.lower() == "unreleased":
        return "unreleased"
    return "v" + version_name.replace(".", "-")


def esc(text: str) -> str:
    return html.escape(text, quote=False)


# Inline spans, applied in this order so `code` is escaped before **bold** or
# [links] could mangle punctuation inside it. Applied left-to-right over the
# escaped text with non-overlapping regex substitution.
_CODE_RE = re.compile(r"`([^`]+)`")
_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")
_BOLD_RE = re.compile(r"\*\*([^*]+)\*\*")
_ITALIC_RE = re.compile(r"(?<!\*)\*([^*]+)\*(?!\*)")


def render_inline(text: str) -> str:
    # Escape once, up front; every substitution below operates on text that
    # is already entity-escaped, so captured groups are reused verbatim —
    # escaping them again would turn "&lt;" into "&amp;lt;".
    escaped = esc(text)
    escaped = _CODE_RE.sub(lambda m: f"<code>{m.group(1)}</code>", escaped)
    escaped = _LINK_RE.sub(lambda m: f'<a href="{m.group(2)}">{m.group(1)}</a>', escaped)
    escaped = _BOLD_RE.sub(lambda m: f"<strong>{m.group(1)}</strong>", escaped)
    escaped = _ITALIC_RE.sub(lambda m: f"<em>{m.group(1)}</em>", escaped)
    return escaped


class _Item:
    """One bullet's raw markdown text plus its (at most one level of)
    nested bullets' raw markdown text — rendered to HTML only once, at the
    end, so a nested `<ul>` already built never gets escaped a second time."""

    def __init__(self, text: str) -> None:
        self.text = text
        self.nested: list[str] = []

    def render(self) -> str:
        li = render_inline(self.text)
        if self.nested:
            li += "<ul>" + "".join(f"<li>{render_inline(t)}</li>" for t in self.nested) + "</ul>"
        return f"<li>{li}</li>"


def render_body(lines: list[str]) -> str:
    """Paragraphs, one level of nested bullets, and h3 subheadings."""
    out: list[str] = []
    i = 0
    n = len(lines)
    while i < n:
        line = lines[i]
        stripped = line.strip()
        if not stripped:
            i += 1
            continue
        sub = SUBHEADING_RE.match(line)
        if sub:
            out.append(f"<h3>{render_inline(sub.group(1))}</h3>")
            i += 1
            continue
        if stripped.startswith("- "):
            items: list[_Item] = []
            while i < n and lines[i].strip():
                cur = lines[i]
                if cur.startswith("  - ") or cur.startswith("    - "):
                    items[-1].nested.append(cur.strip()[2:])
                    i += 1
                    continue
                if cur.strip().startswith("- "):
                    items.append(_Item(cur.strip()[2:]))
                    i += 1
                    continue
                # a continuation line, wrapped for width: belongs to whichever
                # item (or nested item) most recently started
                if items[-1].nested:
                    items[-1].nested[-1] += " " + cur.strip()
                else:
                    items[-1].text += " " + cur.strip()
                i += 1
            out.append("<ul>" + "".join(it.render() for it in items) + "</ul>")
            continue
        # a paragraph: gather continuation lines until a blank line, a
        # heading, or a bullet
        para = [stripped]
        i += 1
        while i < n and lines[i].strip() and not lines[i].strip().startswith("- ") \
                and not SUBHEADING_RE.match(lines[i]):
            para.append(lines[i].strip())
            i += 1
        out.append(f"<p>{render_inline(' '.join(para))}</p>")
    return "\n        ".join(out)


def compare_line(version: Version, link_defs: dict[str, str]) -> str:
    url = link_defs.get(version.name)
    if not url:
        return ""
    m = re.search(r"/compare/(.+?)\.\.\.(.+)$", url)
    if version.name.lower() == "unreleased":
        text = "See everything changed since the last release"
    elif m:
        text = f"See the code changes between {m.group(1).lstrip('v')} and {m.group(2).lstrip('v')}"
    else:
        text = "See the code as first released"
    return f'<p><a href="{esc(url)}">{text}</a></p>'


SHELL_HEAD = """<!DOCTYPE html>
<html lang="en" data-theme="light">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <!-- Apply theme before first paint to avoid flash -->
  <script>(function(){var t;try{t=localStorage.getItem('ow-theme')}catch(e){}if(!t)t=window.matchMedia('(prefers-color-scheme:dark)').matches?'dark':'light';document.documentElement.setAttribute('data-theme',t)})()</script>
  <title>Changelog: Every Release | OpenWhistle</title>
  <meta name="description" content="Every OpenWhistle release, newest first: features, fixes and security changes of the open source whistleblower platform, rendered from CHANGELOG.md.">
  <meta name="robots" content="index, follow">
  <meta name="theme-color" content="#ffffff" media="(prefers-color-scheme: light)">
  <meta name="theme-color" content="#08080a" media="(prefers-color-scheme: dark)">
  <link rel="canonical" href="https://openwhistle.net/changelog.html">
  <link rel="icon" type="image/svg+xml" href="favicon.svg">
  <link rel="icon" type="image/x-icon" href="favicon.ico">
  <link rel="apple-touch-icon" sizes="180x180" href="apple-touch-icon.png">
  <link rel="preload" href="fonts/sora-latin-400-normal.woff2" as="font" type="font/woff2" crossorigin>
  <link rel="preload" href="fonts/sora-latin-700-normal.woff2" as="font" type="font/woff2" crossorigin>

  <!-- Open Graph / Twitter -->
  <meta property="og:type" content="website">
  <meta property="og:site_name" content="OpenWhistle">
  <meta property="og:url" content="https://openwhistle.net/changelog.html">
  <meta property="og:title" content="Changelog: Every Release | OpenWhistle">
  <meta property="og:description" content="Every OpenWhistle release, newest first: features, fixes and security changes of the open source whistleblower platform, rendered from CHANGELOG.md.">
  <meta property="og:image" content="https://openwhistle.net/og-image.png">
  <meta property="og:image:width" content="1200">
  <meta property="og:image:height" content="630">
  <meta property="og:image:alt" content="OpenWhistle: secure whistleblower reporting">
  <meta property="og:locale" content="en_US">
  <meta name="twitter:card" content="summary_large_image">
  <meta name="twitter:title" content="Changelog: Every Release | OpenWhistle">
  <meta name="twitter:description" content="Every OpenWhistle release, newest first: features, fixes and security changes of the open source whistleblower platform, rendered from CHANGELOG.md.">
  <meta name="twitter:image" content="https://openwhistle.net/og-image.png">
  <meta name="twitter:image:alt" content="OpenWhistle: secure whistleblower reporting">

  <!-- Structured data -->
  <script type="application/ld+json">
  {
    "@context": "https://schema.org",
    "@type": "BreadcrumbList",
    "itemListElement": [
      {
        "@type": "ListItem",
        "position": 1,
        "name": "OpenWhistle",
        "item": "https://openwhistle.net/"
      },
      {
        "@type": "ListItem",
        "position": 2,
        "name": "Changelog",
        "item": "https://openwhistle.net/changelog.html"
      }
    ]
  }
  </script>

  <style>
    /* Self-hosted fonts — no external CDN calls */
    @font-face { font-family: 'Sora'; src: url('fonts/sora-latin-300-normal.woff2') format('woff2'); font-weight: 300; font-style: normal; font-display: swap; }
    @font-face { font-family: 'Sora'; src: url('fonts/sora-latin-400-normal.woff2') format('woff2'); font-weight: 400; font-style: normal; font-display: swap; }
    @font-face { font-family: 'Sora'; src: url('fonts/sora-latin-500-normal.woff2') format('woff2'); font-weight: 500; font-style: normal; font-display: swap; }
    @font-face { font-family: 'Sora'; src: url('fonts/sora-latin-600-normal.woff2') format('woff2'); font-weight: 600; font-style: normal; font-display: swap; }
    @font-face { font-family: 'Sora'; src: url('fonts/sora-latin-700-normal.woff2') format('woff2'); font-weight: 700; font-style: normal; font-display: swap; }
    @font-face { font-family: 'JetBrains Mono'; src: url('fonts/JetBrainsMono-Regular.woff2') format('woff2'); font-weight: 400; font-style: normal; font-display: swap; }
    @font-face { font-family: 'JetBrains Mono'; src: url('fonts/JetBrainsMono-Italic.woff2') format('woff2'); font-weight: 400; font-style: italic; font-display: swap; }
    @font-face { font-family: 'JetBrains Mono'; src: url('fonts/JetBrainsMono-Medium.woff2') format('woff2'); font-weight: 500; font-style: normal; font-display: swap; }
    @font-face { font-family: 'JetBrains Mono'; src: url('fonts/JetBrainsMono-Bold.woff2') format('woff2'); font-weight: 700; font-style: normal; font-display: swap; }
  </style>

  <style>
    /* ================================================================
       OpenWhistle Documentation — Shared + Docs-specific styles
       ================================================================ */

    :root {
      --bg-base: #ffffff;
      --bg-surface: #f6f6f5;
      --bg-raised: #efefee;
      --bg-overlay: #e9e9e8;
      --nav-bg: #ffffff;
      --footer-bg: #0a0a0b;
      --sidebar-bg: #f6f6f5;
      --text-primary: #0a0a0b;
      --text-secondary: #3d3d40;
      --text-muted: #6a6a6e;
      --border-subtle: #e6e6e4;
      --border-default: #d8d8d6;
      --border-strong: #c9c9c6;
      --accent: #0c7253;
      --accent-strong: #0b6249;
      --accent-dim: rgba(12,114,83,0.15);
      --accent-fog: rgba(12,114,83,0.08);
      --warning: #8a5a12;
      --warning-fog: rgba(138,90,18,0.08);
      --red-alert: #bf3529;
      --code-bg: #0a0a0b;
      --code-text: #e9e9e8;
      --font-display: 'Sora', system-ui, sans-serif;
      --font-body: 'Sora', system-ui, sans-serif;
      --font-mono: 'JetBrains Mono', ui-monospace, monospace;
      --space-1: 0.25rem;
      --space-2: 0.5rem;
      --space-3: 0.75rem;
      --space-4: 1rem;
      --space-5: 1.25rem;
      --space-6: 1.5rem;
      --space-8: 2rem;
      --space-10: 2.5rem;
      --space-12: 3rem;
      --space-16: 4rem;
      --max-width: 1200px;
      --sidebar-width: 260px;
      --ease-stiff: cubic-bezier(0.16, 1, 0.3, 1);
      --duration-fast: 140ms;
      --duration-mid: 280ms;
    }

    [data-theme="dark"] {
      --bg-base: #08080a;
      --bg-surface: #131315;
      --bg-raised: #1b1b1e;
      --bg-overlay: #232327;
      --nav-bg: #08080a;
      --footer-bg: #050506;
      --sidebar-bg: #131315;
      --text-primary: #fafafa;
      --text-secondary: #bcbcc0;
      --text-muted: #8e8e93;
      --border-subtle: #262629;
      --border-default: #34343a;
      --border-strong: #43434a;
      --accent: #23c088;
      --accent-strong: #1fa878;
      --accent-dim: rgba(35,192,136,0.15);
      --accent-fog: rgba(35,192,136,0.08);
      --warning: #d6a13c;
      --warning-fog: rgba(214,161,60,0.1);
      --code-bg: #050506;
      --code-text: #fafafa;
    }

    *, *::before, *::after { box-sizing: border-box; margin: 0; padding: 0; }
    html { scroll-behavior: smooth; font-size: 16px; -webkit-text-size-adjust: 100%; }
    img, svg { display: block; max-width: 100%; }
    a { color: inherit; text-decoration: none; }
    button { cursor: pointer; border: none; background: none; font: inherit; }
    ul, ol { list-style: none; }

    body {
      background: var(--bg-base);
      color: var(--text-primary);
      font-family: var(--font-body);
      font-size: 1rem;
      line-height: 1.7;
      -webkit-font-smoothing: antialiased;
      overflow-x: hidden;
      transition: background var(--duration-mid) ease, color var(--duration-mid) ease;
    }

    .skip-link {
      position: absolute;
      top: -100%;
      left: var(--space-4);
      background: var(--accent);
      color: #fff;
      padding: var(--space-2) var(--space-4);
      font-family: var(--font-mono);
      font-size: 0.75rem;
      z-index: 9999;
    }
    .skip-link:focus { top: var(--space-4); }

    /* ── Navigation ──────────────────────────────────────────────── */
    .site-nav {
      position: sticky;
      top: 0;
      z-index: 200;
      background: var(--nav-bg);
      border-bottom: 1px solid rgba(255,255,255,0.08);
      box-shadow: 0 1px 3px rgba(0,0,0,0.08);
    }
    [data-theme="light"] .site-nav { border-bottom-color: #e2e8f0; }
    [data-theme="light"] .nav-logo { color: #1e293b; }
    [data-theme="light"] .nav-logo:hover { color: #0c7253; }
    [data-theme="light"] .nav-logo svg path,
    [data-theme="light"] .nav-logo svg circle { stroke: #0c7253; }
    [data-theme="light"] .nav-links a { color: rgba(55,65,81,0.75); }
    [data-theme="light"] .nav-links a:hover { color: #1e293b; }
    [data-theme="light"] .nav-cta { color: #0c7253 !important; border-color: rgba(12,114,83,0.4) !important; }
    [data-theme="light"] .nav-cta:hover { background: rgba(12,114,83,0.08) !important; color: #0c7253 !important; }
    [data-theme="light"] .theme-toggle { border-color: #cbd5e1; color: #718096; }
    [data-theme="light"] .theme-toggle:hover { border-color: #0c7253; color: #0c7253; }
    [data-theme="light"] .nav-toggle { color: #374151; }
    .nav-inner {
      max-width: var(--max-width);
      margin: 0 auto;
      padding: 0 var(--space-8);
      height: 60px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-6);
    }
    .nav-logo {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      font-family: var(--font-display);
      font-size: 0.9rem;
      font-weight: 600;
      letter-spacing: 0.04em;
      color: #e2dcd2;
      flex-shrink: 0;
      transition: color var(--duration-fast) ease;
    }
    .nav-logo:hover { color: #fff; }
    .nav-logo svg { flex-shrink: 0; }
    .nav-logo svg path, .nav-logo svg circle { stroke: var(--accent); }
    .nav-links {
      display: flex;
      align-items: center;
      gap: var(--space-6);
    }
    .nav-links a {
      font-family: var(--font-body);
      font-size: 0.8rem;
      letter-spacing: 0.02em;
      color: rgba(226, 220, 210, 0.65);
      transition: color var(--duration-fast) ease;
      white-space: nowrap;
    }
    .nav-links a:hover { color: #e2dcd2; }
    .nav-links a.active { color: var(--accent); }
    .nav-cta {
      padding: var(--space-2) var(--space-4) !important;
      border: 1px solid rgba(12, 114, 83, 0.5) !important;
      color: var(--accent) !important;
      border-radius: 2px;
    }
    .nav-cta:hover { background: rgba(12, 114, 83, 0.15) !important; color: var(--accent-strong) !important; }
    .nav-actions { display: flex; align-items: center; gap: var(--space-4); flex-shrink: 0; }
    .theme-toggle {
      display: flex;
      align-items: center;
      justify-content: center;
      width: 34px;
      height: 34px;
      border: 1px solid rgba(255,255,255,0.12);
      border-radius: 2px;
      color: rgba(226, 220, 210, 0.65);
      transition: color var(--duration-fast) ease, border-color var(--duration-fast) ease;
    }
    .theme-toggle:hover { color: #e2dcd2; border-color: rgba(255,255,255,0.25); }
    .theme-toggle svg { width: 16px; height: 16px; }
    .icon-sun { display: none; }
    [data-theme="dark"] .icon-moon { display: none; }
    [data-theme="dark"] .icon-sun { display: block; }
    .nav-toggle {
      display: none;
      flex-direction: column;
      gap: 5px;
      padding: var(--space-2);
      color: rgba(226, 220, 210, 0.65);
    }
    .nav-toggle span { display: block; width: 20px; height: 1.5px; background: currentColor; }

    /* ── Docs layout ─────────────────────────────────────────────── */
    .docs-layout {
      display: grid;
      grid-template-columns: var(--sidebar-width) 1fr;
      min-height: calc(100vh - 60px);
      max-width: var(--max-width);
      margin: 0 auto;
    }

    /* ── Sidebar ─────────────────────────────────────────────────── */
    .docs-sidebar {
      position: sticky;
      top: 60px;
      height: calc(100vh - 60px);
      overflow-y: auto;
      background: var(--sidebar-bg);
      border-right: 1px solid var(--border-subtle);
      padding: var(--space-8) var(--space-5);
      scrollbar-width: thin;
      scrollbar-color: var(--border-default) transparent;
    }
    .docs-sidebar::-webkit-scrollbar { width: 4px; }
    .docs-sidebar::-webkit-scrollbar-thumb { background: var(--border-default); border-radius: 2px; }

    .sidebar-section {
      margin-bottom: var(--space-8);
    }
    .sidebar-section-title {
      font-family: var(--font-body);
      font-size: 0.62rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: var(--text-muted);
      margin-bottom: var(--space-3);
      padding-left: var(--space-3);
    }
    .sidebar-links {
      display: flex;
      flex-direction: column;
      gap: 1px;
    }
    .sidebar-links a {
      display: block;
      padding: var(--space-2) var(--space-3);
      font-family: var(--font-body);
      font-size: 0.82rem;
      color: var(--text-secondary);
      border-left: 2px solid transparent;
      border-radius: 0 2px 2px 0;
      transition: color var(--duration-fast) ease, background var(--duration-fast) ease, border-left-color var(--duration-fast) ease;
    }
    .sidebar-links a:hover {
      color: var(--text-primary);
      background: var(--bg-raised);
    }
    .sidebar-links a.active {
      color: var(--accent);
      background: var(--accent-fog);
      border-left-color: var(--accent);
    }

    /* ── Content ─────────────────────────────────────────────────── */
    .docs-content {
      padding: var(--space-12) var(--space-12) var(--space-16);
      min-width: 0;
    }

    .docs-breadcrumb {
      font-family: var(--font-body);
      font-size: 0.72rem;
      letter-spacing: 0.04em;
      color: var(--text-muted);
      margin-bottom: var(--space-8);
      display: flex;
      align-items: center;
      gap: var(--space-2);
    }
    .docs-breadcrumb a { color: var(--accent); transition: color var(--duration-fast) ease; }
    .docs-breadcrumb a:hover { color: var(--accent-strong); }
    .docs-breadcrumb span { color: var(--text-muted); }

    /* Content typography */
    .docs-content h1 {
      font-family: var(--font-display);
      font-size: clamp(2rem, 3.5vw, 2.8rem);
      font-weight: 700;
      letter-spacing: -0.035em;
      line-height: 1.12;
      color: var(--text-primary);
      margin-bottom: var(--space-5);
      animation: rise 0.5s var(--ease-stiff) both;
    }

    .docs-lead {
      font-size: 1.05rem;
      font-weight: 300;
      color: var(--text-secondary);
      line-height: 1.75;
      max-width: 60ch;
      margin-bottom: var(--space-10);
      border-bottom: 1px solid var(--border-subtle);
      padding-bottom: var(--space-8);
      animation: rise 0.5s var(--ease-stiff) 0.1s both;
    }

    .docs-section {
      margin-bottom: var(--space-12);
      padding-bottom: var(--space-12);
      border-bottom: 1px solid var(--border-subtle);
      scroll-margin-top: 80px;
    }
    .docs-section:last-child {
      border-bottom: none;
    }

    .docs-section h2 {
      font-family: var(--font-display);
      font-size: clamp(1.4rem, 2.5vw, 1.9rem);
      font-weight: 700;
      letter-spacing: -0.025em;
      color: var(--text-primary);
      margin-bottom: var(--space-5);
      line-height: 1.2;
    }

    .docs-section h3 {
      font-family: var(--font-display);
      font-size: 1.1rem;
      font-weight: 600;
      color: var(--text-primary);
      margin: var(--space-8) 0 var(--space-3);
    }

    .docs-section p {
      color: var(--text-secondary);
      font-size: 0.95rem;
      line-height: 1.8;
      margin-bottom: var(--space-4);
      max-width: 70ch;
    }

    .docs-section a {
      color: var(--accent);
      border-bottom: 1px solid var(--accent-dim);
      transition: all var(--duration-fast) ease;
    }
    .docs-section a:hover { border-bottom-color: var(--accent); }

    .docs-section ul, .docs-section ol {
      padding-left: var(--space-6);
      margin-bottom: var(--space-5);
    }
    .docs-section ul { list-style: disc; }
    .docs-section ol { list-style: decimal; }
    .docs-section li {
      color: var(--text-secondary);
      font-size: 0.95rem;
      line-height: 1.75;
      margin-bottom: var(--space-2);
      max-width: 68ch;
    }
    .docs-section li ul {
      margin-top: var(--space-2);
      margin-bottom: 0;
    }

    .docs-section code {
      font-family: var(--font-mono);
      font-size: 0.82em;
      background: var(--bg-raised);
      border: 1px solid var(--border-subtle);
      padding: 1px 5px;
      border-radius: 2px;
      color: var(--text-primary);
      /* A long test or setting name must wrap at 390 px, not widen the page. */
      overflow-wrap: anywhere;
    }
    [data-theme="dark"] .docs-section code {
      background: var(--bg-overlay);
    }

    /* Callout boxes */
    .callout {
      padding: var(--space-4) var(--space-6);
      margin: var(--space-6) 0;
      border-left: 3px solid;
      border-radius: 0 2px 2px 0;
    }
    .callout-note {
      background: var(--accent-fog);
      border-color: var(--accent);
    }
    .callout-warn {
      background: var(--warning-fog);
      border-color: var(--warning);
    }
    .callout-title {
      font-family: var(--font-mono);
      font-size: 0.65rem;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      margin-bottom: var(--space-2);
    }
    .callout-note .callout-title { color: var(--accent); }
    .callout-warn .callout-title { color: var(--warning); }
    .callout p {
      font-size: 0.9rem;
      color: var(--text-secondary);
      line-height: 1.7;
      max-width: none;
      margin-bottom: 0;
    }

    /* ── Footer ──────────────────────────────────────────────────── */
    .site-footer {
      background: var(--footer-bg);
      color: rgba(226, 220, 210, 0.7);
      padding: var(--space-16) var(--space-8) var(--space-8);
    }
    .footer-inner {
      max-width: var(--max-width);
      margin: 0 auto;
    }
    .footer-grid {
      display: grid;
      grid-template-columns: 1.8fr 1fr 1fr;
      gap: var(--space-12);
      margin-bottom: var(--space-12);
      padding-bottom: var(--space-10);
      border-bottom: 1px solid rgba(255,255,255,0.08);
    }
    .footer-logo {
      display: flex;
      align-items: center;
      gap: var(--space-3);
      font-family: var(--font-mono);
      font-size: 0.78rem;
      font-weight: 500;
      letter-spacing: 0.12em;
      text-transform: uppercase;
      color: #e2dcd2;
      margin-bottom: var(--space-4);
    }
    .footer-tagline {
      font-size: 0.875rem;
      font-weight: 500;
      color: rgba(226, 220, 210, 0.5);
      line-height: 1.6;
      max-width: 32ch;
    }
    .footer-col-title {
      font-family: var(--font-mono);
      font-size: 0.62rem;
      letter-spacing: 0.14em;
      text-transform: uppercase;
      color: rgba(226, 220, 210, 0.4);
      margin-bottom: var(--space-5);
    }
    .footer-links {
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }
    .footer-links a {
      font-size: 0.875rem;
      color: rgba(226, 220, 210, 0.6);
      transition: color var(--duration-fast) ease;
    }
    .footer-links a:hover { color: #e2dcd2; }
    .footer-bottom {
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-family: var(--font-mono);
      font-size: 0.65rem;
      letter-spacing: 0.06em;
      color: rgba(226, 220, 210, 0.3);
      gap: var(--space-4);
      flex-wrap: wrap;
    }
    .footer-bottom a {
      color: rgba(226, 220, 210, 0.4);
      transition: color var(--duration-fast) ease;
    }
    .footer-bottom a:hover { color: rgba(226, 220, 210, 0.7); }


    /* ── Animations ─────────────────────────────────────────────── */
    @keyframes rise {
      from { opacity: 0; transform: translateY(12px); }
      to   { opacity: 1; transform: translateY(0); }
    }

    /* ── Responsive ─────────────────────────────────────────────── */
    /* Nav collapses at 1080px, not 768px: at 1024px the full item list no
       longer fits the nav-inner row and overflows the viewport
       horizontally. */
    @media (max-width: 1080px) {
      .nav-links { display: none; }
      .nav-links.open {
        display: flex;
        flex-direction: column;
        position: absolute;
        top: 60px;
        left: 0;
        right: 0;
        background: var(--nav-bg);
        border-bottom: 1px solid rgba(255,255,255,0.08);
        padding: var(--space-5) var(--space-6);
        gap: var(--space-4);
        z-index: 201;
      }
      .nav-toggle { display: flex; }
    }

    @media (max-width: 768px) {
      .docs-layout { grid-template-columns: 1fr; }
      .docs-sidebar {
        position: static;
        height: auto;
        border-right: none;
        border-bottom: 1px solid var(--border-subtle);
      }
      .docs-content { padding: var(--space-8) var(--space-5) var(--space-12); }
      .footer-grid { grid-template-columns: 1fr; gap: var(--space-8); }
      .footer-bottom { flex-direction: column; align-items: flex-start; }
    }
  </style>
</head>
<body>
  <a href="#main-content" class="skip-link">Skip to main content</a>

  <!-- Navigation -->
  <nav class="site-nav" role="navigation" aria-label="Primary navigation">
    <div class="nav-inner">
      <a href="index.html" class="nav-logo" aria-label="OpenWhistle home">
        <svg width="22" height="26" viewBox="0 0 22 26" fill="none" aria-hidden="true">
          <path d="M11 1 L20 5 L20 14 C20 20 17 24 11 25.5 C5 24 2 20 2 14 L2 5 Z"
                stroke="#5ecb7a" stroke-width="1.5" stroke-linejoin="round" fill="none"/>
          <circle cx="11" cy="18" r="1.1" fill="#5ecb7a"/>
          <path d="M8.5,16 A3,3 0 0,1 13.5,16" stroke="#5ecb7a" stroke-width="1.5" stroke-linecap="round"/>
          <path d="M7,14.5 A5.5,5.5 0 0,1 15,14.5" stroke="#5ecb7a" stroke-width="1.2" stroke-linecap="round" opacity="0.72"/>
          <path d="M5,13 A8,8 0 0,1 17,13" stroke="#5ecb7a" stroke-width="1" stroke-linecap="round" opacity="0.42"/>
        </svg>
        OpenWhistle
      </a>

      <button class="nav-toggle" aria-controls="nav-links" aria-expanded="false" aria-label="Toggle navigation">
        <span></span><span></span><span></span>
      </button>

      <ul class="nav-links" id="nav-links" role="list">
        <li><a href="index.html#features">Features</a></li>
        <li><a href="index.html#how-it-works">How it Works</a></li>
        <li><a href="index.html#compliance">Compliance</a></li>
        <li><a href="docs.html">Documentation</a></li>
        <li><a href="roadmap.html">Roadmap</a></li>
        <li><a href="changelog.html" class="active" aria-current="page">Changelog</a></li>
        <li><a href="blog/">Blog</a></li>
        <li><a href="de/">Auf Deutsch</a></li>
        <li><a href="https://github.com/openwhistle/OpenWhistle" rel="noopener noreferrer" target="_blank">GitHub</a></li>
        <li><a href="https://demo.openwhistle.net" rel="noopener noreferrer" target="_blank" class="nav-cta">Try Demo</a></li>
      </ul>

      <div class="nav-actions">
        <button class="theme-toggle" id="theme-toggle" aria-label="Toggle dark mode">
          <svg class="icon-moon" viewBox="0 0 16 16" fill="none">
            <path d="M13.5 9.5A6 6 0 016 2a6 6 0 100 12 6 6 0 007.5-4.5z" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
          </svg>
          <svg class="icon-sun" viewBox="0 0 16 16" fill="none">
            <circle cx="8" cy="8" r="3" stroke="currentColor" stroke-width="1.3"/>
            <path d="M8 1v2M8 13v2M1 8h2M13 8h2M3.05 3.05l1.41 1.41M11.54 11.54l1.41 1.41M11.54 4.46l-1.41 1.41M4.95 11.54l-1.41 1.41" stroke="currentColor" stroke-width="1.3" stroke-linecap="round"/>
          </svg>
        </button>
      </div>
    </div>
  </nav>

  <div class="docs-layout">

    <!-- Sidebar -->
    <aside class="docs-sidebar" role="complementary" aria-label="Changelog navigation">

      <div class="sidebar-section">
        <div class="sidebar-section-title">Versions</div>
        <nav class="sidebar-links" aria-label="On this page">
"""

SHELL_TAIL = """        </nav>
      </div>

      <div class="sidebar-section">
        <div class="sidebar-section-title">Links</div>
        <nav class="sidebar-links">
          <a href="index.html">&#8592; Landing Page</a>
          <a href="docs.html">Documentation</a>
          <a href="roadmap.html">Roadmap</a>
          <a href="https://github.com/openwhistle/OpenWhistle/blob/main/CHANGELOG.md" rel="noopener noreferrer" target="_blank">CHANGELOG.md source</a>
          <a href="https://github.com/openwhistle/OpenWhistle" rel="noopener noreferrer" target="_blank">GitHub Repository</a>
        </nav>
      </div>

    </aside>

    <!-- Main content -->
    <main id="main-content" class="docs-content">

      <nav class="docs-breadcrumb" aria-label="Breadcrumb">
        <a href="index.html">OpenWhistle</a>
        <span>/</span>
        <span>Changelog</span>
      </nav>

      <h1>Changelog</h1>
      <p class="docs-lead">
        Every release, newest first. Rendered from
        <a href="https://github.com/openwhistle/OpenWhistle/blob/main/CHANGELOG.md" rel="noopener noreferrer" target="_blank">CHANGELOG.md</a>,
        the file GitHub and the release tooling read.
      </p>

"""

SHELL_FOOT = """    </main>
  </div>

  <!-- Footer -->
  <footer class="site-footer" role="contentinfo">
    <div class="footer-inner">
      <div class="footer-grid">
        <div>
          <div class="footer-logo">
            <svg width="20" height="24" viewBox="0 0 22 26" fill="none" aria-hidden="true">
              <path d="M11 1 L20 5 L20 14 C20 20 17 24 11 25.5 C5 24 2 20 2 14 L2 5 Z"
                    stroke="rgba(226,220,210,0.5)" stroke-width="1.5" stroke-linejoin="round" fill="none"/>
              <circle cx="11" cy="18" r="1.1" fill="rgba(226,220,210,0.5)"/>
              <path d="M8.5,16 A3,3 0 0,1 13.5,16" stroke="rgba(226,220,210,0.5)" stroke-width="1.5" stroke-linecap="round"/>
              <path d="M7,14.5 A5.5,5.5 0 0,1 15,14.5" stroke="rgba(226,220,210,0.5)" stroke-width="1.2" stroke-linecap="round" opacity="0.7"/>
              <path d="M5,13 A8,8 0 0,1 17,13" stroke="rgba(226,220,210,0.5)" stroke-width="1" stroke-linecap="round" opacity="0.4"/>
            </svg>
            OpenWhistle
          </div>
          <p class="footer-tagline">Protecting those who speak up.</p>
        </div>

        <nav aria-label="Footer links">
          <div class="footer-col-title">Resources</div>
          <ul class="footer-links">
            <li><a href="https://github.com/openwhistle/OpenWhistle" rel="noopener noreferrer" target="_blank">GitHub</a></li>
            <li><a href="docs.html">Documentation</a></li>
            <li><a href="changelog.html">Changelog</a></li>
            <li><a href="blog/">Blog</a></li>
            <li><a href="de/">Auf Deutsch</a></li>
            <li><a href="https://demo.openwhistle.net" rel="noopener noreferrer" target="_blank">Live Demo</a></li>
            <li><a href="https://github.com/openwhistle/OpenWhistle/issues" rel="noopener noreferrer" target="_blank">Issues</a></li>
            <li><a href="https://github.com/openwhistle/OpenWhistle/blob/main/LICENSE" rel="noopener noreferrer" target="_blank">License (GPL-3.0)</a></li>
          </ul>
        </nav>

        <div>
          <div class="footer-col-title">Legal</div>
          <p style="font-size: 0.85rem; color: rgba(226,220,210,0.45); line-height: 1.7;">
            Licensed under GPL-3.0. Built with &#10084;&#65039; for transparency.
          </p>
          <p style="font-size: 0.82rem; color: rgba(226,220,210,0.35); line-height: 1.7; margin-top: 0.75rem;">
            OpenWhistle does not provide legal advice. Please consult qualified counsel
            regarding your specific HinSchG obligations.
          </p>
        </div>
      </div>

      <div class="footer-bottom">
        <span>&copy; OpenWhistle Contributors — GNU General Public License v3.0</span>
        <a href="https://github.com/openwhistle/OpenWhistle" rel="noopener noreferrer" target="_blank">
          Contribute on GitHub &rarr;
        </a>
      </div>
    </div>
  </footer>

  <script>
    // Theme toggle — detection already handled by inline head script
    var toggle = document.getElementById('theme-toggle');
    if (toggle) {
      toggle.addEventListener('click', function() {
        var current = document.documentElement.getAttribute('data-theme');
        var next = current === 'dark' ? 'light' : 'dark';
        document.documentElement.setAttribute('data-theme', next);
        try { localStorage.setItem('ow-theme', next); } catch(e) {}
      });
    }

    // Follow system preference changes when user hasn't overridden manually
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', function(e) {
      var stored;
      try { stored = localStorage.getItem('ow-theme'); } catch(e2) {}
      if (!stored) {
        document.documentElement.setAttribute('data-theme', e.matches ? 'dark' : 'light');
      }
    });

    // Mobile nav
    var navToggle = document.querySelector('.nav-toggle');
    var navLinks = document.getElementById('nav-links');
    if (navToggle && navLinks) {
      navToggle.addEventListener('click', function() {
        var isOpen = navToggle.getAttribute('aria-expanded') === 'true';
        navToggle.setAttribute('aria-expanded', String(!isOpen));
        navLinks.classList.toggle('open', !isOpen);
      });
    }

    // Sidebar active link on scroll
    var sections = document.querySelectorAll('.docs-section[id]');
    var sidebarLinks = document.querySelectorAll('.sidebar-links a[href^="#"]');

    function updateActive() {
      var scrollY = window.scrollY + 100;
      var active = null;
      sections.forEach(function(s) {
        if (s.offsetTop <= scrollY) {
          active = s.getAttribute('id');
        }
      });
      sidebarLinks.forEach(function(a) {
        var href = a.getAttribute('href');
        if (href === '#' + active) {
          a.classList.add('active');
        } else {
          a.classList.remove('active');
        }
      });
    }

    window.addEventListener('scroll', updateActive, { passive: true });
    updateActive();
  </script>
</body>
</html>
"""


def render(versions: list[Version], link_defs: dict[str, str]) -> str:
    shown = [v for v in versions if any(line.strip() for line in v.lines)]

    nav_links = "\n".join(
        f'          <a href="#{slug(v.name)}">{esc(v.name)}</a>' for v in shown
    )

    sections = []
    for v in shown:
        date_suffix = f" — {esc(v.date)}" if v.date else ""
        body_html = render_body(v.lines)
        compare = compare_line(v, link_defs)
        sections.append(
            f'      <section class="docs-section" id="{slug(v.name)}" '
            f'aria-labelledby="{slug(v.name)}-h2">\n'
            f'        <h2 id="{slug(v.name)}-h2">{esc(v.name)}{date_suffix}</h2>\n'
            f"        {body_html}\n"
            f"        {compare}\n"
            f"      </section>\n"
        )

    return SHELL_HEAD + nav_links + "\n" + SHELL_TAIL + "\n".join(sections) + SHELL_FOOT


def main() -> int:
    check = "--check" in sys.argv
    versions, link_defs = parse(SRC.read_text())
    want = render(versions, link_defs)

    if check:
        have = OUT.read_text() if OUT.exists() else ""
        if have == want:
            print(f"docs/changelog.html is current — {len(versions)} versions")
            return 0
        print(
            "docs/changelog.html is not what CHANGELOG.md would produce.\n"
            "  Run `uv run python scripts/render_changelog.py` and commit the result.",
            file=sys.stderr,
        )
        return 1

    OUT.write_text(want)
    print(f"wrote docs/changelog.html — {len(versions)} versions")
    return 0


if __name__ == "__main__":
    sys.exit(main())
