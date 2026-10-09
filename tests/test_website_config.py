"""website/nginx.conf against the built site: what a text check can prove without Docker."""

from __future__ import annotations

import base64
import hashlib
import re
from pathlib import Path

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
    assert re.findall(r"^\s*access_log\s+([^;]+);", CONF, re.M) == ["/dev/stdout counter"]


def test_errors_are_logged_at_emerg_only() -> None:
    """nginx error lines carry `client: <IP>` (P4-9)."""
    levels = re.findall(r"^\s*error_log\s+([^;]+);", CONF, re.M)
    assert levels and all(level.split()[-1] == "emerg" for level in levels), levels


def test_compression_is_prebuilt_only() -> None:
    assert re.search(r"^\s*gzip_static\s+on;", CONF, re.M)
    assert not re.search(r"^\s*gzip\s+on;", CONF, re.M)
