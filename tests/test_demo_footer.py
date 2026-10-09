"""In demo mode only, the footer links openwhistle.net's imprint and privacy policy (spec P3-7)."""

from __future__ import annotations

from pathlib import Path

import pytest
from httpx import AsyncClient

IMPRINT = "https://openwhistle.net/impressum/"


@pytest.mark.parametrize(
    ("lang", "privacy"),
    [
        ("de", "/de/datenschutz/"),
        ("en", "/en/privacy/"),
        ("es", "/en/privacy/"),
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
    for lang in ("en", "de"):
        html = (await client.get("/", headers={"Accept-Language": lang})).text
        assert "openwhistle.net/impressum" not in html
        assert "openwhistle.net/en/privacy" not in html
        assert "openwhistle.net/de/datenschutz" not in html


def test_the_screenshot_script_hides_the_demo_legal_links() -> None:
    root = Path(__file__).resolve().parent.parent
    script = (root / "scripts" / "take_screenshots.py").read_text(encoding="utf-8")
    base = (root / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    assert base.count('class="demo-legal"') == 2
    assert ".demo-legal" in script
