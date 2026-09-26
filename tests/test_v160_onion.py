"""v1.6.0 Task 19: Tor onion address for reporters on a watched network.

Onion-Location header (skipped for /static/ and when already on the onion
service itself), ONION_LOCATION config validation, and the submit-page note.
"""

from __future__ import annotations

import ast
import json
import re
from pathlib import Path

import pytest
from httpx import AsyncClient, Response

from app.config import Settings, settings

ROOT = Path(__file__).parents[1]
ONION_HOST = "a" * 56 + ".onion"
ONION = "http://" + ONION_HOST
# The nginx-asserted signal the app trusts for "this is the onion listener"
# (fix round 2) — never the client-supplied Host. See app/onion.py.
ON_ONION = {"X-OW-Onion": "1"}


# ── Onion-Location header ──────────────────────────────────────────────────


async def test_onion_location_header_points_to_the_same_page(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/status")
    assert resp.headers["onion-location"] == f"{ONION}/status"
    monkeypatch.setattr(settings, "onion_location", "")
    assert "onion-location" not in (await client.get("/status")).headers


async def test_onion_location_header_absent_for_static_assets(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/static/css/site.css")
    assert "onion-location" not in resp.headers


async def test_onion_location_header_not_sent_on_the_onion_service_itself(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A visitor already on http://<...>.onion must not be offered the same
    address again — nginx's X-OW-Onion header (set only by the 8080 server
    block) reveals they are already there. Never the client-supplied Host."""
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/status", headers=ON_ONION)
    assert "onion-location" not in resp.headers


async def test_onion_location_header_still_sent_for_a_normal_host(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/status", headers={"Host": "example.com"})
    assert resp.headers["onion-location"] == f"{ONION}/status"


async def test_onion_location_header_still_sent_when_host_is_onion_but_nginx_never_marked_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 2 (re-review Important): a client that merely SENDS
    Host: <onion> — without ever going through the onion nginx listener,
    which is the only place X-OW-Onion is set — must not be treated as
    already-on-the-onion-service. Spoofing Host alone must do nothing."""
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/status", headers={"Host": ONION_HOST})
    assert resp.headers["onion-location"] == f"{ONION}/status"


# ── Cookies (Critical fix-round-1 #1) ────────────────────────────────────────


def _set_cookie_headers(resp: Response) -> list[str]:
    return [v for k, v in resp.headers.multi_items() if k.lower() == "set-cookie"]


async def test_cookies_have_no_secure_flag_over_the_onion_listener(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A Secure cookie set over the onion listener's plain-HTTP connection can
    be silently refused by the browser, breaking the CSRF double-submit
    cookie and every reporter-facing POST it protects — the whole point of
    offering an onion address. Every Set-Cookie for this listener must drop
    Secure, whatever settings.secure_cookies says."""
    monkeypatch.setattr(settings, "onion_location", ONION)
    assert settings.secure_cookies is True
    client.headers.update(ON_ONION)
    resp = await client.get("/submit")
    cookies = _set_cookie_headers(resp)
    assert cookies, "expected at least the CSRF and submission-session cookies"
    for cookie in cookies:
        assert "Secure" not in cookie, cookie


async def test_cookies_keep_the_secure_flag_on_a_normal_host(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "onion_location", ONION)
    assert settings.secure_cookies is True
    resp = await client.get("/submit", headers={"Host": "example.com"})
    cookies = _set_cookie_headers(resp)
    assert cookies
    for cookie in cookies:
        assert "Secure" in cookie, cookie


async def test_cookies_keep_the_secure_flag_when_host_is_onion_but_nginx_never_marked_it(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fix round 2 (re-review Important, the core regression test): a client
    on the real TLS listener sending Host: <onion> — without the X-OW-Onion
    header only the onion nginx server block sets — is a spoofing attempt,
    not a genuine onion visitor, and must still get Secure cookies."""
    monkeypatch.setattr(settings, "onion_location", ONION)
    assert settings.secure_cookies is True
    resp = await client.get("/submit", headers={"Host": ONION_HOST})
    cookies = _set_cookie_headers(resp)
    assert cookies
    for cookie in cookies:
        assert "Secure" in cookie, cookie


async def test_full_submission_wizard_succeeds_over_the_onion_listener(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """End-to-end proof the CSRF double-submit cookie round-trips (GET form →
    POST with the CSRF cookie, through every wizard step) when every cookie
    on the way was set without Secure, because nginx marked this request as
    onion."""
    from conftest import wizard_submit  # noqa: PLC0415

    monkeypatch.setattr(settings, "onion_location", ONION)
    client.headers.update(ON_ONION)
    case_number, pin = await wizard_submit(client)
    assert case_number.startswith("OW-")
    assert pin


# ── HSTS (Important fix-round-1 #2) ──────────────────────────────────────────


async def test_hsts_absent_over_the_onion_listener(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """RFC 6797 §8.1: an HSTS host MUST NOT send this header over a
    connection that was not secure — the onion listener never is."""
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/status", headers=ON_ONION)
    assert "strict-transport-security" not in resp.headers


async def test_hsts_present_on_a_normal_host(client: AsyncClient) -> None:
    resp = await client.get("/status")
    assert "strict-transport-security" in resp.headers


async def test_hsts_present_when_host_is_onion_but_nginx_never_marked_it(
    client: AsyncClient,
) -> None:
    """Fix round 2: spoofing Host alone (no X-OW-Onion) must not suppress HSTS
    on a connection that genuinely is TLS."""
    resp = await client.get("/status", headers={"Host": ONION_HOST})
    assert "strict-transport-security" in resp.headers


# ── Onion trust: nginx-asserted header only, never the client Host ──────────
# (fix round 2, re-review Important)


def test_is_onion_request_trusts_only_the_exact_nginx_header(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.onion import is_onion_request

    monkeypatch.setattr(settings, "onion_location", ONION)

    assert is_onion_request([(b"x-ow-onion", b"1")]) is True
    assert is_onion_request([(b"X-OW-Onion", b"1")]) is True  # header names are case-insensitive
    assert is_onion_request([]) is False
    assert is_onion_request([(b"x-ow-onion", b"true")]) is False
    assert is_onion_request([(b"x-ow-onion", b"0")]) is False
    assert is_onion_request([(b"x-ow-onion", b"")]) is False  # nginx's clear value
    # A spoofed Host must never substitute for the header.
    assert is_onion_request([(b"host", ("a" * 56 + ".onion").encode())]) is False


def test_cookie_secure_fails_loudly_when_security_middleware_never_ran() -> None:
    """Ruling: no silent fallback — a wiring bug (SecurityMiddleware not
    registered, so request.state.is_onion was never set) must raise, not
    guess at Secure."""
    from starlette.requests import Request

    from app.onion import cookie_secure

    request = Request(scope={"type": "http", "headers": [], "state": {}})
    with pytest.raises(AttributeError):
        cookie_secure(request)


# ── Onion-Location scoped to HTML (Minor fix-round-1 #6) ────────────────────


async def test_onion_location_absent_on_json_health_endpoint(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/health")
    assert resp.headers["content-type"].startswith("application/json")
    assert "onion-location" not in resp.headers


# ── Config validation ────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "value",
    [
        "",
        "http://" + "a" * 56 + ".onion",
        "https://" + "b" * 56 + ".onion",
        "http://" + "A" * 56 + ".onion",  # RFC 4648 base32 is case-insensitive
    ],
)
def test_onion_location_accepts_valid_values(value: str) -> None:
    Settings(secret_key="x" * 32, onion_location=value)  # type: ignore[call-arg]


@pytest.mark.parametrize(
    "value",
    [
        "not-a-url",
        "http://" + "a" * 55 + ".onion",  # too short
        "http://" + "a" * 57 + ".onion",  # too long
        "http://" + "a" * 56 + ".onion/path",  # path
        "http://" + "a" * 56 + ".onion?x=1",  # query
        "http://" + "a" * 56 + ".com",  # wrong TLD
        "ftp://" + "a" * 56 + ".onion",  # wrong scheme
        "http://" + "0" * 56 + ".onion",  # '0' and '1' are not in base32
        "http://example.com",
    ],
)
def test_onion_location_refuses_invalid_values(value: str) -> None:
    with pytest.raises(ValueError, match="ONION_LOCATION"):
        Settings(secret_key="x" * 32, onion_location=value)  # type: ignore[call-arg]


# ── Submit page note ─────────────────────────────────────────────────────────


async def test_submit_page_shows_onion_note_when_configured(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/submit")
    assert resp.status_code == 200
    assert ONION in resp.text
    assert "sidebar-note" in resp.text


async def test_submit_page_hides_onion_note_when_unset(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "onion_location", "")
    resp = await client.get("/submit")
    assert resp.status_code == 200
    assert "sidebar-note" not in resp.text


# ── nginx ─────────────────────────────────────────────────────────────────────


def test_nginx_has_an_onion_entry_point_on_8080() -> None:
    conf = (ROOT / "nginx/nginx.conf").read_text()
    servers = re.findall(r"\n    server \{.*?\n    \}", conf, re.S)
    onion = next(s for s in servers if "listen 8080;" in s)
    assert "proxy_pass http://openwhistle;" in onion
    assert "ssl_certificate" not in onion  # plain HTTP; Tor already encrypts


def test_docker_compose_publishes_the_onion_port_on_localhost_only() -> None:
    compose = (ROOT / "docker-compose.prod.yml").read_text()
    assert '"127.0.0.1:8080:8080"' in compose


# ── Docs / env-var sync (same commit as the new env var) ────────────────────


def test_onion_location_env_var_is_documented_everywhere() -> None:
    for path, needle in (
        ("app/config.py", "onion_location"),
        ("docs/docs.html", "ONION_LOCATION"),
        ("README.md", "ONION_LOCATION"),
        ("docker-compose.prod.yml", 'ONION_LOCATION: "${ONION_LOCATION:-}"'),
        ("charts/openwhistle/values.yaml", "onionLocation"),
        ("charts/openwhistle/templates/configmap.yaml", "ONION_LOCATION"),
    ):
        text = (ROOT / path).read_text()
        assert needle in text, path


# ── Ansible env.j2 field parity (controller ruling, fix round 1 #8) ─────────


def _settings_field_names() -> list[str]:
    """Every app.config.Settings field name, found without importing the
    module (so this stays a static source check, not a runtime one)."""
    tree = ast.parse((ROOT / "app" / "config.py").read_text())
    names = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "Settings":
            for item in node.body:
                if isinstance(item, ast.AnnAssign) and isinstance(item.target, ast.Name):
                    names.append(item.target.id)
    return names


def test_every_config_field_appears_in_ansible_env_j2() -> None:
    """RED when a Settings field is missing from env.j2 — live (VAR={{ ... }})
    or, for one not yet wired to an Ansible variable, at least documented as
    a commented VAR=default line an operator can uncomment."""
    env_j2 = (ROOT / "ansible/roles/openwhistle/templates/env.j2").read_text()
    present = {m.group(1).lower() for m in re.finditer(r"^#?\s*([A-Z][A-Z0-9_]*)=", env_j2, re.M)}
    missing = [f for f in _settings_field_names() if f not in present]
    assert missing == []


def test_ansible_env_j2_live_vars_have_defaults() -> None:
    """Every {{ openwhistle_xxx }} template var env.j2 actually uses must be
    defined in defaults/main.yml, or a deploy with no extra vars fails."""
    env_j2 = (ROOT / "ansible/roles/openwhistle/templates/env.j2").read_text()
    used = set(re.findall(r"\{\{\s*(openwhistle_[a-z0-9_]+)\s*\}\}", env_j2))
    defaults = (ROOT / "ansible/roles/openwhistle/defaults/main.yml").read_text()
    defined = set(re.findall(r"^(openwhistle_[a-z0-9_]+):", defaults, re.M))
    assert used - defined == set()


# ── Docs: key-backup warning and rate-limit callout (Important #5, Minor #7) ─


def test_onion_howto_warns_about_the_hidden_service_private_key() -> None:
    text = (ROOT / "docs/docs.html").read_text()
    section = text.split('id="onion-address"')[1].split('id="helm"')[0]
    assert "hs_ed25519_secret_key" in section
    assert "0700" in section
    assert re.search(r"back(s|ing)? (it|the directory) up|back up", section, re.I)


def test_onion_howto_explains_the_shared_rate_limit_budget() -> None:
    text = (ROOT / "docs/docs.html").read_text()
    section = text.split('id="onion-address"')[1].split('id="helm"')[0]
    assert "127.0.0.1" in section
    assert "429" in section


def test_onion_howto_and_security_section_explain_the_x_ow_onion_trust_boundary() -> None:
    """Fix round 2 (re-review Important, ruling): both the how-to and the
    Security Architecture section must document that the app trusts nginx's
    X-OW-Onion header (never the client Host), and that this requires the
    app port to be reachable only through the shipped nginx."""
    text = (ROOT / "docs/docs.html").read_text()
    howto = text.split('id="onion-address"')[1].split('id="helm"')[0]
    assert "X-OW-Onion" in howto
    assert "reachable only through" in howto

    security = text.split('id="security"')[1]
    assert "X-OW-Onion" in security
    assert "Host" in security


# ── Locale ────────────────────────────────────────────────────────────────────


def test_onion_locale_key_present_and_translated_in_every_locale() -> None:
    locales_dir = ROOT / "app" / "locales"
    en = json.loads((locales_dir / "en.json").read_text(encoding="utf-8"))["submit.sidebar.onion"]
    for path in locales_dir.glob("*.json"):
        data = json.loads(path.read_text(encoding="utf-8"))
        assert "submit.sidebar.onion" in data, path.name
        assert data["submit.sidebar.onion"], path.name
        if path.stem != "en":
            assert data["submit.sidebar.onion"] != en, path.name
