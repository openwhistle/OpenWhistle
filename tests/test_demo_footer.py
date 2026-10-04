"""In demo mode only, the footer links openwhistle.net's imprint and privacy policy (spec P3-7)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

IMPRINT = "https://openwhistle.net/impressum/"


@pytest.mark.parametrize(
    ("lang", "privacy"),
    [
        ("de", "/de/datenschutz/"),
        ("en", "/en/privacy/"),
        ("fr", "/en/privacy/"),
        ("pt-br", "/en/privacy/"),
    ],
)
async def test_demo_footer_links_imprint_and_privacy(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, lang: str, privacy: str
) -> None:
    from app.templating import templates

    monkeypatch.setitem(templates.env.globals, "is_demo", True)
    html = (await client.get("/", headers={"Accept-Language": lang})).text
    assert f'href="{IMPRINT}"' in html
    assert f'href="https://openwhistle.net{privacy}"' in html


async def test_an_operators_own_footer_links_neither(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.templating import templates

    monkeypatch.setitem(templates.env.globals, "is_demo", False)
    html = (await client.get("/")).text
    assert "openwhistle.net/impressum" not in html and "openwhistle.net/en/privacy" not in html
