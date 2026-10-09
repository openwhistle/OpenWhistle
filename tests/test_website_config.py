"""website/nginx.conf against the built site: what a text check can prove without Docker."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

import yaml

from tests.built_site import built, pages

ROOT = Path(__file__).parents[1]
CONF = (ROOT / "website" / "nginx.conf").read_text()
# An executable inline script: no src, no type, or a JavaScript type. JSON-LD is data, never run.
_INLINE = re.compile(
    r"<script(?![^>]*\bsrc=)(?![^>]*\btype=\"application/ld\+json\")[^>]*>(.*?)</script>", re.S
)


def _hash(body: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(body.encode()).digest()).decode() + "'"


def _csp(name: str) -> str:
    found = re.search(rf'"{name}"\s+"([^"]+)"', CONF)
    assert found, f"no {name} CSP in website/nginx.conf"
    return found.group(1)


def _needed() -> dict[str, set[str]]:
    need: dict[str, set[str]] = {"site": set(), "docs": set()}
    for path in pages():
        url = "/" + path.relative_to(built()).as_posix()
        where = "docs" if url.startswith("/en/docs/") else "site"
        need[where] |= {_hash(body) for body in _INLINE.findall(path.read_text(encoding="utf-8"))}
    return need


def test_every_inline_script_is_allowed_by_its_csp_and_nothing_else_is() -> None:
    need = _needed()
    for where in ("site", "docs"):
        allowed = set(re.findall(r"'sha256-[^']+'", _csp(where)))
        assert allowed == need[where], (
            f"{where}: allow exactly {sorted(need[where])}, not {sorted(allowed)}"
        )


def test_only_the_docs_may_compile_wasm() -> None:
    assert "'wasm-unsafe-eval'" in _csp("docs")
    assert "'wasm-unsafe-eval'" not in _csp("site")


def test_the_csp_never_relaxes() -> None:
    for where in ("site", "docs"):
        csp = _csp(where)
        assert "unsafe-inline" not in csp and "'unsafe-eval'" not in csp and "*" not in csp, where
        for rule in (
            "default-src 'none'",
            "style-src 'self'",
            "base-uri 'none'",
            "form-action 'none'",
            "frame-ancestors 'none'",
            "upgrade-insecure-requests",
        ):
            assert rule in csp, (where, rule)


def test_only_fonts_may_come_from_a_data_uri() -> None:
    """Fonts are inlined in fonts.css (before the first layout, CLS 0): font-src allows data:."""
    for where in ("site", "docs"):
        csp = _csp(where)
        assert "font-src 'self' data:;" in csp, where
        assert csp.count("data:") == 1, where


def test_the_log_holds_no_address_agent_or_query() -> None:
    fmt = re.search(r"log_format\s+counter\s+'([^']*)'", CONF)
    assert fmt and fmt.group(1) == "$time_iso8601 $uri $status $ref_host"
    for leak in (
        "$remote_addr",
        "$http_x_forwarded_for",
        "$http_user_agent",
        "$request ",
        "$request_uri",
        "$args",
        "$query_string",
        "$binary_remote_addr",
        "$realip_remote_addr",
    ):
        assert leak not in CONF, leak
    assert re.findall(r"^\s*access_log\s+([^;]+);", CONF, re.M) == [
        "/dev/stdout counter",
        "off",
    ]


def test_errors_are_logged_at_emerg_only() -> None:
    """nginx error lines carry `client: <IP>` (P4-9); main context only, before `events {`."""
    levels = re.findall(r"^\s*error_log\s+([^;]+);", CONF, re.M)
    assert levels and all(level.split()[-1] == "emerg" for level in levels), levels
    assert "error_log stderr emerg;" in CONF.split("events {")[0], (
        "error_log not in the main context"
    )


def _ref_host(referer: str) -> str:
    found = re.search(r'map \$http_referer \$ref_host \{\s*"~([^"]+)" \$rhost;', CONF)
    assert found, "no $ref_host map"
    match = re.search(found.group(1).replace("(?<rhost>", "(?P<rhost>"), referer)
    return match.group("rhost") if match else "-"


def test_the_referer_logs_a_bare_hostname_only() -> None:
    assert _ref_host("https://example.org/page?q=1") == "example.org"
    assert _ref_host("https://alice@intranet.acme.local/") == "intranet.acme.local"
    assert _ref_host("https://example.org:8443/x") == "example.org"
    assert _ref_host("https://a b c/") == "-"
    assert _ref_host("") == "-"


def test_no_location_sets_headers() -> None:
    """An add_header in a location drops every server-level add_header for that location."""
    for block in re.findall(r"location\s[^{]*\{([^}]*)\}", CONF):
        assert "add_header" not in block, block


def test_map_keys_fit_the_hash_bucket_with_headroom() -> None:
    """map_hash_bucket_size is 128; keys over 96 characters leave no room for a longer redirect."""
    keys = [str(key) for key in yaml.safe_load((ROOT / "docs/_data/redirects.yml").read_text())]
    keys += re.findall(r'^\s*"(/[^"]*)"\s+"', CONF, re.M)
    assert keys and max(map(len, keys)) <= 96, max(keys, key=len)


def test_compression_is_prebuilt_only() -> None:
    assert re.search(r"^\s*gzip_static\s+on;", CONF, re.M)
    assert not re.search(r"^\s*gzip\s+on;", CONF, re.M)


def test_a_missing_website_url_fails_in_ci_and_skips_locally() -> None:
    import pytest

    from tests.website import require_url

    assert require_url("http://x", "") and require_url("http://x", "true")
    assert not require_url("", "")
    with pytest.raises(RuntimeError):
        require_url("", "true")


def _location(head: str) -> str:
    found = re.search(rf"location\s+{head}\s*\{{((?:[^{{}}]|\{{[^}}]*\}})*)\}}", CONF)
    assert found, f"no location {head}"
    return found.group(1)


def test_the_private_fragment_is_never_fetchable_from_outside() -> None:
    block = _location(re.escape("/_private/"))
    assert re.search(r"^\s*internal;", block, re.M)
    assert "alias /usr/share/nginx/private/;" in block


def test_ssi_is_on_for_the_legal_pages_only_and_without_the_prebuilt_gzip() -> None:
    assert len(re.findall(r"^\s*ssi\s+on;", CONF, re.M)) == 1
    block = _location(re.escape("~ ^/(impressum|de/datenschutz|en/privacy)/"))
    assert re.search(r"^\s*ssi\s+on;", block, re.M)
    assert re.search(r"^\s*gzip_static\s+off;", block, re.M)


def test_the_health_check_is_not_logged() -> None:
    block = _location("=\\s+/healthz")
    assert re.search(r"^\s*access_log\s+off;", block, re.M)
    assert "return 204;" in block
    guard = re.search(
        r"if\s*\(!-f /usr/share/nginx/private/address\.html\)\s*\{\s*return 503;", block
    )
    assert guard and guard.start() < block.index("return 204;"), "no fragment, no healthy answer"


def test_subrequests_are_never_logged() -> None:
    """The include is a subrequest: logging it would add a /_private/address.html line."""
    assert not re.search(r"^\s*log_subrequest\s+on;", CONF, re.M)
