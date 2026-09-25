"""v1.6.0 Task 19: Tor onion address for reporters on a watched network.

Onion-Location header (skipped for /static/ and when already on the onion
service itself), ONION_LOCATION config validation, and the submit-page note.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from httpx import AsyncClient

from app.config import Settings, settings

ROOT = Path(__file__).parents[1]
ONION = "http://" + "a" * 56 + ".onion"


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
    address again — the Host header reveals they are already there."""
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/status", headers={"Host": "a" * 56 + ".onion"})
    assert "onion-location" not in resp.headers


async def test_onion_location_header_still_sent_for_a_normal_host(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "onion_location", ONION)
    resp = await client.get("/status", headers={"Host": "example.com"})
    assert resp.headers["onion-location"] == f"{ONION}/status"


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
