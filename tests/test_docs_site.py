"""The roadmap lives on the website, not in a ROADMAP.md a stranger has to
clone the repo to read. These guards keep it that way: the file stays gone,
every page's nav points at it, no version already shipped is shown as
planned, and the page never reaches out to a font CDN."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]

# Every page whose top nav must carry a "Roadmap" link, and the relative
# path from that page to docs/roadmap.html.
NAV_PAGES = {
    "docs/index.html": "roadmap.html",
    "docs/de/index.html": "../roadmap.html",
    "docs/docs.html": "roadmap.html",
    "docs/roadmap.html": "roadmap.html",
    # Every blog page, discovered — a new article cannot miss the link unnoticed.
    **{
        f"docs/blog/{p.name}": "../roadmap.html"
        for p in sorted((ROOT / "docs" / "blog").glob("*.html"))
    },
}


def _app_version() -> tuple[int, ...]:
    # Same source tests/test_v100.py::test_every_published_version_string_matches
    # reads from, rather than a second regex over app/config.py's source text.
    from app.config import settings

    return tuple(int(p) for p in settings.app_version.split("."))


def test_roadmap_md_does_not_exist() -> None:
    assert not (ROOT / "ROADMAP.md").exists(), (
        "ROADMAP.md must be gone — the roadmap lives at docs/roadmap.html now"
    )


def test_roadmap_page_exists() -> None:
    assert (ROOT / "docs/roadmap.html").is_file()


def test_every_nav_page_links_to_roadmap() -> None:
    missing = []
    for page, href in NAV_PAGES.items():
        html = (ROOT / page).read_text()
        nav_match = re.search(r'<ul class="nav-links"[^>]*>.*?</ul>', html, re.DOTALL)
        assert nav_match, f"{page}: no <ul class=\"nav-links\"> found"
        if f'href="{href}"' not in nav_match.group(0):
            missing.append(page)
    assert not missing, f"pages whose nav does not link to roadmap.html: {missing}"


def test_roadmap_has_no_released_version_as_planned_heading() -> None:
    html = (ROOT / "docs/roadmap.html").read_text()
    current = _app_version()
    headings = re.findall(r"<h2[^>]*>\s*v(\d+\.\d+\.\d+)\b", html)
    assert headings, "docs/roadmap.html has no version headings to check"
    released = [
        v for v in headings if tuple(int(p) for p in v.split(".")) <= current
    ]
    assert not released, (
        f"roadmap.html shows already-released version(s) as planned: {released} "
        f"(current app_version is {'.'.join(map(str, current))})"
    )


def test_roadmap_uses_only_self_hosted_fonts() -> None:
    html = (ROOT / "docs/roadmap.html").read_text()
    assert "fonts.googleapis.com" not in html
    assert "fonts.gstatic.com" not in html
    assert re.search(r"@font-face\s*\{[^}]*url\(['\"]?fonts/", html), (
        "docs/roadmap.html must declare its fonts from docs/fonts/, like docs/docs.html does"
    )


def test_roadmap_points_to_changelog_for_everything_released() -> None:
    html = (ROOT / "docs/roadmap.html").read_text()
    assert "CHANGELOG.md" in html


def _root_tokens_block(html: str) -> str:
    """The first top-level `:root { ... }` block (the light-mode design
    tokens), whitespace-normalised so formatting differences don't matter."""
    m = re.search(r":root\s*\{([^}]*)\}", html, re.DOTALL)
    assert m, ":root token block not found"
    return re.sub(r"\s+", " ", m.group(1)).strip()


def test_de_landing_page_shares_design_tokens_with_english() -> None:
    """Regression guard (Task X11): docs/index.html was rebuilt onto the
    "Signal" design (Sora + JetBrains Mono, ink/green tokens) while
    docs/de/index.html kept an older serif/navy design, so the two pages
    drifted apart. Pin the :root tokens and font-family variables identical
    so a future edit to one page can't silently un-sync the other."""
    en = (ROOT / "docs/index.html").read_text()
    de = (ROOT / "docs/de/index.html").read_text()
    assert _root_tokens_block(en) == _root_tokens_block(de)
    for var in ("--font-display", "--font-body", "--font-mono"):
        pattern = re.escape(var) + r":\s*([^;]+);"
        en_m, de_m = re.search(pattern, en), re.search(pattern, de)
        assert en_m and de_m, var
        assert en_m.group(1).strip() == de_m.group(1).strip(), (
            var, en_m.group(1), de_m.group(1)
        )
