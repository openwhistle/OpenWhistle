"""Write docs/sitemap.xml from the pages themselves.

Every docs/**/*.html page that is not noindex is listed at its own
<link rel="canonical">, with its hreflang alternates. lastmod is the date of
the last commit touching the file, or today when the file has uncommitted
changes. Run after changing any page: `uv run python scripts/render_sitemap.py`.
tests/test_seo.py checks the result against the pages.
"""

import datetime
import re
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

CANONICAL_RE = re.compile(r'<link rel="canonical" href="([^"]+)">')
ALT_RE = re.compile(r'<link rel="alternate" hreflang="([^"]+)" href="([^"]+)">')


def _git(*args: str) -> str:
    # fixed git argv; the paths come from the repository itself
    out = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return out.stdout.strip()


def lastmod(page: Path) -> str:
    rel = str(page.relative_to(ROOT))
    committed = _git("log", "-1", "--format=%cs", "--", rel)
    if not committed or _git("status", "--porcelain", "--", rel):
        return datetime.date.today().isoformat()
    return committed


def render() -> str:
    entries = []
    for page in sorted(DOCS.rglob("*.html")):
        text = page.read_text()
        if re.search(r'<meta name="robots" content="[^"]*noindex', text):
            continue
        loc = CANONICAL_RE.search(text)
        assert loc, f"{page.relative_to(ROOT)} has no canonical link"
        lines = [f"    <loc>{loc.group(1)}</loc>"]
        lines += [
            f'    <xhtml:link rel="alternate" hreflang="{lang}" href="{href}"/>'
            for lang, href in ALT_RE.findall(text)
        ]
        lines.append(f"    <lastmod>{lastmod(page)}</lastmod>")
        entries.append("  <url>\n" + "\n".join(lines) + "\n  </url>")
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        + "\n".join(entries)
        + "\n</urlset>\n"
    )


if __name__ == "__main__":
    (DOCS / "sitemap.xml").write_text(render())
    print("wrote docs/sitemap.xml")
