#!/usr/bin/env python3
"""Every link from openwhistle.net to another host still answers.

    uv run --group site python scripts/check_external_links.py

Builds the site into a temporary directory, collects every http(s) href that
leaves openwhistle.net and GETs each once, with one retry after 5 s. Exit 1
lists the broken ones: no connection, 404, 410, 5xx. 401, 403 and 429 mean a
host that refuses robots, not a dead link: printed as unverifiable, never fatal.
Run weekly by .github/workflows/links.yml, which opens an issue on failure.
"""

from __future__ import annotations

import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parent))
import build_site  # noqa: E402

HOST = urlsplit(build_site._yaml(build_site.DOCS / "_data" / "site.yml")["base_url"]).netloc
USER_AGENT = "openwhistle-link-check (+https://openwhistle.net)"
UNVERIFIABLE = {401, 403, 429}


def collect(site: Path, host: str = HOST) -> dict[str, list[str]]:
    """External URL -> the built pages that link it (site-relative)."""
    found: dict[str, list[str]] = {}
    for page in sorted(site.rglob("*.html")):
        parser = build_site._Refs()
        parser.feed(page.read_text(encoding="utf-8"))
        for ref in parser.refs:
            parts = urlsplit(ref)
            if parts.scheme in ("http", "https") and parts.netloc.lower() != host:
                url = parts._replace(fragment="").geturl()
                pages = found.setdefault(url, [])
                if (rel := "/" + page.relative_to(site).as_posix()) not in pages:
                    pages.append(rel)
    return found


def classify(status: int | None) -> str:
    """None is no connection at all."""
    if status in UNVERIFIABLE:
        return "unverifiable"
    if status is None or status in (404, 410) or status >= 500:
        return "broken"
    return "ok"


def fetch(url: str) -> int | None:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})  # noqa: S310 — http(s) only
    try:
        with urllib.request.urlopen(request, timeout=20) as response:  # noqa: S310
            return int(response.status)
    except urllib.error.HTTPError as error:
        return error.code
    except urllib.error.URLError, TimeoutError, OSError:
        return None


def status_of(url: str) -> int | None:
    status = fetch(url)
    if classify(status) == "ok":
        return status
    time.sleep(5)
    return fetch(url)


def main() -> int:
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "site"
        build_site.build(build_site.DOCS, out)
        links = collect(out)
    broken = []
    for url, pages in sorted(links.items()):
        status = status_of(url)
        verdict = classify(status)
        line = f"{verdict}: {url} ({status or 'no connection'}) on {', '.join(pages)}"
        print(line)
        if verdict == "broken":
            broken.append(line)
    print(f"\n{len(links)} external links, {len(broken)} broken")
    if broken:
        print("\n".join(["", "Broken:", *broken]))
    return 1 if broken else 0


if __name__ == "__main__":
    sys.exit(main())
