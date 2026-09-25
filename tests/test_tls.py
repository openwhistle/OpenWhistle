"""The bundled nginx always has a certificate and never serves the app over plain HTTP."""

from __future__ import annotations

import importlib.util
import re
import stat
from pathlib import Path

from cryptography import x509

ROOT = Path(__file__).parents[1]


def _ensure():  # type: ignore[no-untyped-def]
    spec = importlib.util.spec_from_file_location("tls", ROOT / "scripts/ensure_tls_cert.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod.ensure


def test_self_signed_certificate_is_created_once(tmp_path: Path) -> None:
    ensure = _ensure()
    assert ensure(tmp_path / "none", tmp_path / "tls", "whistle.example.org") == "self-signed"
    cert = x509.load_pem_x509_certificate((tmp_path / "tls/fullchain.pem").read_bytes())
    san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName).value
    assert "whistle.example.org" in san.get_values_for_type(x509.DNSName)
    assert ensure(tmp_path / "none", tmp_path / "tls", "whistle.example.org") == "kept"


def test_operator_certificate_wins(tmp_path: Path) -> None:
    ensure = _ensure()
    src = tmp_path / "certs"
    src.mkdir()
    (src / "fullchain.pem").write_text("CERT")
    (src / "privkey.pem").write_text("KEY")
    assert ensure(src, tmp_path / "tls", "x") == "provided"
    assert (tmp_path / "tls/fullchain.pem").read_text() == "CERT"
    mode = stat.S_IMODE((tmp_path / "tls/privkey.pem").stat().st_mode)
    assert mode == 0o600, oct(mode)


def test_nginx_redirects_http_and_strips_ip_headers_on_https() -> None:
    conf = (ROOT / "nginx/nginx.conf").read_text()
    servers = re.findall(r"\n    server \{.*?\n    \}", conf, re.S)
    plain = next(s for s in servers if "listen 80;" in s)
    tls = next(s for s in servers if "listen 443 ssl" in s)
    onion = next(s for s in servers if "listen 8080;" in s)
    assert "return 301 https://$host$request_uri;" in plain
    assert "proxy_pass" not in plain

    # The IP-strip/proxy-header block lives in one shared snippet (not
    # duplicated per server block) — both the TLS and onion server blocks
    # include it, and the snippet itself carries every header.
    snippet = (ROOT / "nginx/snippets/proxy-headers.conf").read_text()
    for header in (
        "X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP", "True-Client-IP",
    ):
        assert f"proxy_set_header {header}" in snippet
        assert f"proxy_set_header {header}" not in tls, "duplicated instead of included"
        assert f"proxy_set_header {header}" not in onion, "duplicated instead of included"
    assert "include /etc/nginx/snippets/proxy-headers.conf;" in tls
    assert "include /etc/nginx/snippets/proxy-headers.conf;" in onion


def test_nginx_static_location_is_a_shared_snippet_too() -> None:
    conf = (ROOT / "nginx/nginx.conf").read_text()
    servers = re.findall(r"\n    server \{.*?\n    \}", conf, re.S)
    tls = next(s for s in servers if "listen 443 ssl" in s)
    onion = next(s for s in servers if "listen 8080;" in s)
    snippet = (ROOT / "nginx/snippets/static-location.conf").read_text()
    assert "location /static/" in snippet
    assert "location /static/" not in tls, "duplicated instead of included"
    assert "location /static/" not in onion, "duplicated instead of included"
    assert "include /etc/nginx/snippets/static-location.conf;" in tls
    assert "include /etc/nginx/snippets/static-location.conf;" in onion


def test_docker_compose_mounts_the_nginx_snippets_directory() -> None:
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    assert "./nginx/snippets:/etc/nginx/snippets:ro" in compose


def test_onion_listener_has_its_own_higher_budget_rate_limit_zone() -> None:
    """Ruling: every onion visitor arrives from 127.0.0.1 (the host's Tor
    daemon), so ow_req (per-IP) would give them all ONE shared bucket by
    coincidence; the onion listener gets its own zone, keyed on a constant
    to make that explicit, with a higher rate/burst than the per-IP zone."""
    conf = (ROOT / "nginx/nginx.conf").read_text()
    assert 'limit_req_zone "onion" zone=ow_req_onion:' in conf
    servers = re.findall(r"\n    server \{.*?\n    \}", conf, re.S)
    onion = next(s for s in servers if "listen 8080;" in s)
    tls = next(s for s in servers if "listen 443 ssl" in s)
    assert "limit_req zone=ow_req_onion" in onion
    assert "limit_req zone=ow_req " in tls  # unchanged, still per-IP
    onion_rate = int(re.search(r"ow_req_onion:\w+ rate=(\d+)r/s", conf).group(1))  # type: ignore[union-attr]
    tls_rate = int(re.search(r"\bow_req:\w+ rate=(\d+)r/s", conf).group(1))  # type: ignore[union-attr]
    assert onion_rate > tls_rate
    onion_burst = int(re.search(r"ow_req_onion burst=(\d+)", onion).group(1))  # type: ignore[union-attr]
    tls_burst = int(re.search(r"ow_req burst=(\d+)", tls).group(1))  # type: ignore[union-attr]
    assert onion_burst > tls_burst
