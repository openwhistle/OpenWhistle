"""The running website container (docs-tech/specs/2026-10-09-website-p4-design.md § Tests).

WEBSITE_URL=http://127.0.0.1:8080 WEBSITE_CONTAINER=ow-website pytest tests/website
"""

from __future__ import annotations

import gzip
import os
import re
import subprocess
import urllib.error
import urllib.request
from http.client import HTTPResponse

import pytest
import yaml

from tests.built_site import ROOT
from tests.website import require_url

BASE = os.environ.get("WEBSITE_URL", "")
pytestmark = [
    pytest.mark.website,
    pytest.mark.skipif(
        not require_url(BASE, os.environ.get("CI", "")), reason="WEBSITE_URL is not set"
    ),
]
CLI = os.environ.get("CONTAINER_CLI", "docker")
NAME = os.environ.get("WEBSITE_CONTAINER", "ow-website")
REDIRECTS = yaml.safe_load((ROOT / "docs/_data/redirects.yml").read_text())
SECURITY = {
    "strict-transport-security": "max-age=63072000; includeSubDomains; preload",
    "cross-origin-opener-policy": "same-origin",
    "cross-origin-resource-policy": "same-origin",
    "referrer-policy": "no-referrer",
    "x-content-type-options": "nosniff",
    "cache-control": "no-cache",
}


class _NoFollow(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *_a: object, **_k: object) -> None:
        return None


_OPENER = urllib.request.build_opener(_NoFollow)


def get(path: str, **headers: str) -> HTTPResponse:
    request = urllib.request.Request(BASE + path, headers=headers)  # noqa: S310
    try:
        return _OPENER.open(request, timeout=10)
    except urllib.error.HTTPError as error:
        return error  # type: ignore[return-value]  # 3xx/4xx carry status and headers


def logs() -> str:
    run = subprocess.run([CLI, "logs", NAME], capture_output=True, text=True, check=True)  # noqa: S603
    return run.stdout + run.stderr


@pytest.mark.parametrize(
    "path", ["/en/", "/de/", "/en/docs/install/", "/assets/css/base.css", "/nope/"]
)
def test_every_response_carries_the_security_headers(path: str) -> None:
    response = get(path)
    for name, value in SECURITY.items():
        assert response.headers[name] == value, (path, name)
    assert "camera=()" in response.headers["permissions-policy"]
    assert response.headers["server"] == "nginx", "server_tokens off hides the version"


def test_the_docs_alone_may_compile_wasm() -> None:
    assert "'wasm-unsafe-eval'" in get("/en/docs/").headers["content-security-policy"]
    assert "'wasm-unsafe-eval'" not in get("/en/").headers["content-security-policy"]


def test_the_search_worker_may_compile_wasm_too() -> None:
    """A worker runs under the policy of its own response, not the page's."""
    worker = get("/pagefind/pagefind-worker.js")
    assert "'wasm-unsafe-eval'" in worker.headers["content-security-policy"]


@pytest.mark.parametrize(("old", "new"), sorted(REDIRECTS.items()))
def test_every_old_url_moves_permanently(old: str, new: str) -> None:
    response = get(old)
    assert (response.status, response.headers["location"]) == (301, new)


def test_an_old_url_with_a_query_still_moves() -> None:
    old, new = next(iter(sorted(REDIRECTS.items())))
    response = get(old + "?utm_source=x")
    assert (response.status, response.headers["location"]) == (301, new)


@pytest.mark.parametrize(
    ("accept", "home"),
    [
        ("de-DE,de;q=0.9", "/de/"),
        ("DE-at", "/de/"),
        ("de", "/de/"),
        ("en-US,de;q=0.8", "/en/"),
        ("fr", "/en/"),
        ("", "/en/"),
    ],
)
def test_the_root_picks_the_language(accept: str, home: str) -> None:
    for path in ("/", "/index.html"):
        response = get(path, **({"Accept-Language": accept} if accept else {}))
        assert (response.status, response.headers["location"]) == (302, home), (path, accept)
        assert response.headers["vary"] == "Accept-Language"
        assert "set-cookie" not in response.headers


def test_a_directory_without_its_slash_moves_relatively() -> None:
    response = get("/en/docs")
    assert (response.status, response.headers["location"]) == (301, "/en/docs/")


def test_a_missing_page_is_the_404_page_with_status_404() -> None:
    response = get("/no/such/page/")
    assert response.status == 404
    assert b"Page not found" in response.read()


def test_a_revalidation_still_carries_the_headers() -> None:
    etag = get("/en/").headers["etag"]
    response = get("/en/", **{"If-None-Match": etag})
    assert response.status == 304
    assert response.headers["content-security-policy"]


def test_gzip_is_served_from_the_prebuilt_file() -> None:
    plain = get("/en/").read()
    response = get("/en/", **{"Accept-Encoding": "gzip"})
    assert response.headers["content-encoding"] == "gzip"
    assert gzip.decompress(response.read()) == plain


@pytest.mark.parametrize(
    ("path", "kind"),
    [
        ("/.well-known/security.txt", ("text/plain; charset=utf-8",)),
        ("/pagefind/pagefind.js", ("application/javascript", "text/javascript")),
    ],
)
def test_types(path: str, kind: tuple[str, ...]) -> None:
    assert get(path).headers["content-type"].startswith(kind)


def test_the_process_is_not_root() -> None:
    argv = [CLI, "exec", NAME, "id", "-u"]
    run = subprocess.run(argv, capture_output=True, text=True, check=True)  # noqa: S603
    assert run.stdout.strip() != "0"


def test_the_configuration_is_valid() -> None:
    subprocess.run([CLI, "exec", NAME, "nginx", "-t"], capture_output=True, check=True)  # noqa: S603


def test_no_log_line_carries_an_address_or_a_query() -> None:
    get(
        "/en/?email=leak%40example.org",
        **{"X-Forwarded-For": "203.0.113.9", "Referer": "https://ref.example/x?y=1"},
    )
    get("/no/such/page/", **{"X-Forwarded-For": "203.0.113.9"})
    text = logs()
    assert "203.0.113.9" not in text and "127.0.0.1" not in text and "172." not in text
    assert "leak" not in text and "email" not in text and "utm_source" not in text
    # $uri is the path after the index lookup: /en/ is logged as /en/index.html.
    assert re.search(r"^\S+ /en/index\.html 200 ref\.example$", text, re.M), text[-500:]


def test_the_referer_keeps_the_hostname_only() -> None:
    get("/en/", Referer="https://alice@intranet.acme.local:8443/x")
    text = logs()
    assert "alice" not in text and "8443" not in text
    assert re.search(r"^\S+ /en/index\.html 200 intranet\.acme\.local$", text, re.M), text[-500:]


def test_every_log_line_is_a_counter_line() -> None:
    # A $uri with a space would break the 4-field format; scripts/site_stats.py skips such lines
    # (len(parts) != 4), so the counter never miscounts and nothing needs fixing here.
    get("/en/")
    get("/50x.html")
    lines = logs().splitlines()
    assert lines
    assert all(re.fullmatch(r"\S+ \S+ \d{3} \S+", line) for line in lines), lines


def test_the_base_images_error_page_is_gone() -> None:
    assert get("/50x.html").status == 404


def test_a_directory_without_an_index_is_the_404_page() -> None:
    response = get("/assets/")
    assert response.status == 403
    assert b"Page not found" in response.read()
