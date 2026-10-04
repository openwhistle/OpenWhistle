"""The one-pager split (spec P3-2, P3-3): nothing lost, nothing twice, every old link lands."""

from __future__ import annotations

import re
from collections import Counter
from pathlib import Path

import yaml

from tests.built_site import built, docs_pages, page

ROOT = Path(__file__).parents[1]
ANCHORS = yaml.safe_load((ROOT / "docs/_data/docs_anchors.yml").read_text(encoding="utf-8"))

# Every id the one-pager /en/docs/ had on 2026-10-04 (git show 7572621:docs/en/docs/index.html),
# main-content excepted: a bookmark or a blog post may point at any of them.
OLD_IDS = """
overview overview-h2 requirements requirements-h2 container-images container-images-h2
installation installation-h2 deployment-privacy deployment-privacy-h2 outbound-requests
counting-installations redis-sizing behind-proxy selinux onion-address helm configuration
configuration-h2 notifications sla-reminders retention multi-tenancy ldap s3-storage attachments
attachments-h2 virus-scanning first-run first-run-h2 admin-guide admin-guide-h2 admin-login
own-account lost-access whistleblower-guide wb-guide-h2 security security-h2 oidc-integration
demo-mode demo-mode-h2 upgrading upgrading-h2 upgrading-2-0 key-rotation key-rotation-h2
""".split()

# Every <h3> of the one-pager. Each is now a heading (h1–h3) on exactly one docs page.
OLD_H3 = [
    "Key design principles",
    "Supported platforms",
    "Current version",
    "Registries",
    "Image tags",
    "Image signatures",
    "Step 1 — Clone the repository",
    "Step 2 — Configure environment",
    "Step 3 — Start services",
    "Step 4 — Run the setup wizard",
    "Every request that leaves the host",
    "Counting installations",
    "Redis sizing",
    "Behind a TLS-terminating proxy",
    "SELinux hosts",
    "Offering an onion address",
    "Kubernetes (Helm)",
    "Notifications",
    "SLA Reminders",
    "Data retention (GDPR / HinSchG)",
    "Multi-tenancy",
    "LDAP / Active Directory login",
    "S3-compatible attachment storage",
    "Scanning uploads for viruses",
    "Limits and allowed types",
    "Access control",
    "Privacy and deletion",
    "Wizard steps",
    "Signing in",
    "Dashboard overview",
    "Roles",
    "Your account",
    "Lost password or authenticator",
    "Managing reports",
    "Audit log",
    "Categories and locations",
    "Dashboard statistics",
    "System & updates",
    "HinSchG deadline tracking",
    "Telephone reporting channel guide",
    "Submitting a report",
    "Checking report status",
    "What is stored about when you acted",
    "Security recommendations for whistleblowers",
    "The four anonymity layers",
    "Rate limiting without IP tracking",
    "Security headers",
    "Onion listener trust boundary",
    "OIDC integration",
    "Enabling demo mode",
    "Demo mode behaviour",
    "Standard upgrade procedure",
    "Before upgrading",
    "Upgrading to 2.0.0 with Docker Compose",
    "Rollback",
]


def _headings(html: str) -> list[str]:
    main = html.split('class="docs-article">', 1)[1].split("</article>", 1)[0]
    return [
        re.sub(r"<[^>]+>", "", h).replace("&amp;", "&").strip()
        for h in re.findall(r"<h[1-3][^>]*>(.*?)</h[1-3]>", main, re.S)
    ]


def test_every_old_id_is_mapped() -> None:
    assert sorted(ANCHORS) == sorted(OLD_IDS)


def test_every_mapped_target_exists() -> None:
    for old, target in ANCHORS.items():
        url, _, fragment = target.partition("#")
        html = page(url)
        if fragment:
            assert f'id="{fragment}"' in html, (old, target)


# An old section whose page carries a new id for it: the section id -> the id on its page.
_RENAMED = {"deployment-privacy": "outbound-requests", "wb-guide": "whistleblower-guide"}


def test_every_old_id_lands_on_the_content_it_named() -> None:
    """Not merely on some page: the target carries the old id, or its section's (an old
    `<section>`'s `-h2` heading id), so a bookmark to #helm cannot land on the start page."""
    for old, target in ANCHORS.items():
        url, _, fragment = target.partition("#")
        named = fragment or _RENAMED.get(old.removesuffix("-h2"), old.removesuffix("-h2"))
        assert f'id="{named}"' in page(url), (old, target)


def test_every_old_h3_is_a_heading_on_exactly_one_page() -> None:
    seen = Counter(h for url in docs_pages() for h in set(_headings(page(url))))
    wrong = {h: seen[h] for h in OLD_H3 if seen[h] != 1}
    assert not wrong, wrong


def test_every_docs_h2_has_a_unique_id() -> None:
    for url in docs_pages():
        h2 = re.findall(r"<h2\b([^>]*)>", page(url))
        ids = [re.search(r'\bid="([^"]+)"', a).group(1) for a in h2 if 'id="' in a]
        assert len(ids) == len(h2) and len(set(ids)) == len(ids), (url, h2)


def test_no_docs_page_skips_a_heading_level() -> None:
    """h1 -> h3 hides the h3 from "On this page" and from a screen reader's outline."""
    skips = []
    for url in docs_pages():
        main = page(url).split('class="docs-article">', 1)[1].split("</article>", 1)[0]
        levels = [int(n) for n in re.findall(r"<h([1-6])\b", main)]
        skips += [(url, a, b) for a, b in zip(levels, levels[1:], strict=False) if b > a + 1]
    assert not skips, skips


def test_the_one_pager_is_gone() -> None:
    start = page("/en/docs/")
    assert 'id="installation"' not in start and 'class="docs-section"' not in start
    assert len(docs_pages()) >= 33, docs_pages()


def test_no_page_links_a_one_pager_anchor() -> None:
    """The anchor script is a safety net for bookmarks; our own pages link the new page."""
    stale = re.compile(r'href="(?:https://openwhistle\.net)?/en/docs/#')
    hits = [
        p.relative_to(built()).as_posix()
        for p in built().rglob("*.html")
        if stale.search(p.read_text())
    ]
    assert not hits, hits
