#!/usr/bin/env python3
"""CHANGELOG.md -> the body of /en/changelog/.

GitHub and the release tooling read CHANGELOG.md at the repository root. This
renders it as one page in the site's own design (the shell copied from the
roadmap page), newest release first.

Imported by scripts/build_site.py; CHANGELOG.md stays the single source.

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
        while (
            i < n
            and lines[i].strip()
            and not lines[i].strip().startswith("- ")
            and not SUBHEADING_RE.match(lines[i])
        ):
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


CONTENT_HEAD = """

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
          <a href="/en/">&#8592; Landing Page</a>
          <a href="/en/docs/">Documentation</a>
          <a href="/en/roadmap/">Roadmap</a>
          <a href="https://github.com/openwhistle/OpenWhistle/blob/main/CHANGELOG.md" rel="noopener noreferrer" target="_blank">CHANGELOG.md source</a>
          <a href="https://github.com/openwhistle/OpenWhistle" rel="noopener noreferrer" target="_blank">GitHub Repository</a>
        </nav>
      </div>

    </aside>

    <!-- Main content -->
    <main id="main-content" class="docs-content">

      <nav class="docs-breadcrumb" aria-label="Breadcrumb">
        <a href="/en/">OpenWhistle</a>
        <span>/</span>
{crumb}
      </nav>

      <h1>{title}</h1>
      <p class="docs-lead">
        {lead} Rendered from
        <a href="https://github.com/openwhistle/OpenWhistle/blob/main/CHANGELOG.md" rel="noopener noreferrer" target="_blank">CHANGELOG.md</a>,
        the file GitHub and the release tooling read.
      </p>

"""

CONTENT_FOOT = """    </main>
  </div>

  <!-- Footer -->
  """


# Releases on /en/changelog/ besides the unreleased section: a count, not a version rule, so a
# new release never pushes the page over the 100 KB first-view budget by itself.
NEWEST = 5


def render_content(
    versions: list[Version], link_defs: dict[str, str], *, older: bool = False
) -> str:
    """The page body between the site navigation and the footer; the layout adds the rest.

    Two pages, because one page of every release is 43 KB of HTML and the first view of a
    page stays within 100 KB: /en/changelog/ holds what is not yet released and the NEWEST
    releases, /en/changelog/older/ the rest.
    """
    shown = [v for v in versions if any(line.strip() for line in v.lines)]
    released = [v for v in shown if v.name.lower() != "unreleased"]
    on_main = {v.name for v in released[:NEWEST]}
    shown = [v for v in shown if (v.name in on_main or v.name.lower() == "unreleased") != older]
    oldest_shown = released[NEWEST - 1].name if len(released) >= NEWEST else ""

    nav_links = "\n".join(f'          <a href="#{slug(v.name)}">{esc(v.name)}</a>' for v in shown)

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

    if older:
        crumb = (
            '        <a href="/en/changelog/">Changelog</a>\n        <span>/</span>\n'
            "        <span>Older releases</span>"
        )
        title = "Older releases"
        lead = (
            f"Every release before {oldest_shown}, newest first. "
            '<a href="/en/changelog/">Back to the current releases</a>.'
        )
    else:
        crumb = "        <span>Changelog</span>"
        title = "Changelog"
        lead = (
            f"The unreleased changes and the newest {NEWEST} releases. "
            'Before that: <a href="/en/changelog/older/">older releases</a>.'
        )
    shell_tail = (
        SHELL_TAIL.replace("{title}", title).replace("{lead}", lead).replace("{crumb}", crumb)
    )
    return CONTENT_HEAD + nav_links + "\n" + shell_tail + "\n".join(sections) + CONTENT_FOOT
