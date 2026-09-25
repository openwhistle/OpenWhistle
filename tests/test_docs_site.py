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
    "docs/blog/index.html": "../roadmap.html",
    "docs/blog/hinschg-compliance-leitfaden.html": "../roadmap.html",
    "docs/blog/whistleblower-software-vergleich.html": "../roadmap.html",
    "docs/blog/interne-meldestelle-einrichten.html": "../roadmap.html",
}


def _app_version() -> tuple[int, ...]:
    config = (ROOT / "app/config.py").read_text()
    match = re.search(r'app_version:\s*str\s*=\s*"([^"]+)"', config)
    assert match, "app_version not found in app/config.py"
    return tuple(int(p) for p in match.group(1).split("."))


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
