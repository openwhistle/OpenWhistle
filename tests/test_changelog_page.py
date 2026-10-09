"""CHANGELOG.md's version headings and link definitions agree with each other.

The website renders the changelog page from this file of the latest release
(openwhistle/website); this guard keeps the source itself consistent.
"""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]
CHANGELOG = ROOT / "CHANGELOG.md"
# Deliberately independent of the website renderer's HEADING_RE / LINK_DEF_RE: a

# Deliberately independent of RENDER_CHANGELOG.HEADING_RE / LINK_DEF_RE: a
# heading or link definition that the renderer's own regex fails to parse
# would otherwise pass unnoticed on both sides of that one comparison.
_HEADING_RE = re.compile(r"^## \[([^\]]+)\]", re.MULTILINE)
_LINK_DEF_RE = re.compile(r"^\[([^\]]+)\]:\s*(\S+)", re.MULTILINE)


def test_every_version_heading_has_a_link_definition_and_vice_versa() -> None:
    changelog = CHANGELOG.read_text()
    headings = _HEADING_RE.findall(changelog)
    link_defs = dict(_LINK_DEF_RE.findall(changelog))

    assert headings, "CHANGELOG.md has no `## [x.y.z]` version headings"
    seen = set()
    for name in headings:
        assert name not in seen, f"version {name} has two headings"
        seen.add(name)
        assert name in link_defs, (
            f"CHANGELOG.md: [{name}] has a heading and no link definition "
            f"(`[{name}]: https://...`) at the foot of the file"
        )

    extra = set(link_defs) - seen
    assert not extra, f"link definition(s) with no matching heading: {sorted(extra)}"

    semver_headings = [n for n in headings if re.fullmatch(r"\d+\.\d+\.\d+", n)]
    assert semver_headings, "CHANGELOG.md has no `## [x.y.z]` semantic-version headings"
    for name in semver_headings:
        url = link_defs[name]
        assert url.startswith("https://github.com/openwhistle/OpenWhistle/"), (name, url)
