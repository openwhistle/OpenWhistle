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
    assert "return 301 https://$host$request_uri;" in plain
    assert "proxy_pass" not in plain
    for header in (
        "X-Forwarded-For", "X-Real-IP", "Forwarded", "CF-Connecting-IP", "True-Client-IP",
    ):
        assert f"proxy_set_header {header}" in tls
