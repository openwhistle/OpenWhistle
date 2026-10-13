"""§13 Abs. 2 HinSchG: the internal reporting office names the external ones."""

from __future__ import annotations

import pytest
from httpx import AsyncClient

OFFICES = (
    "https://www.bundesjustizamt.de/DE/MeldestelledesBundes/MeldestelledesBundes_node.html",
    "https://www.bafin.de/DE/die-bafin/whistleblower/whistleblower_node",
    "https://www.bundeskartellamt.de/DE/Aufgaben/Kartelle/Verteiler_Hinweise/Hinweise_Verst%C3%B6%C3%9Fe_node.html",
    "https://anti-fraud.ec.europa.eu/olaf-and-you/report-fraud_en",
)


@pytest.mark.parametrize(
    ("lang", "title"),
    [
        ("en", "External reporting offices"),
        ("de", "Externe Meldestellen"),
        ("es", "Canales de denuncia externos"),
        ("fr", "Canaux de signalement externes"),
        ("pt-br", "Canais de denúncia externos"),
    ],
)
async def test_the_page_names_every_external_office(
    client: AsyncClient, lang: str, title: str
) -> None:
    response = await client.get("/external-reporting", headers={"Accept-Language": lang})
    assert response.status_code == 200
    assert f"<h1>{title}</h1>" in response.text
    for url in OFFICES:
        assert f'href="{url}" rel="noopener noreferrer"' in response.text
    assert "§\u00a020 HinSchG" in response.text  # the federal states' own offices


async def test_the_status_page_links_it(client: AsyncClient) -> None:
    html = (await client.get("/status")).text
    assert '<p class="st-external"><a href="/external-reporting">' in html


async def test_the_submit_sidebar_links_it(client: AsyncClient) -> None:
    html = (await client.get("/submit")).text
    sidebar = html[html.index('<aside class="split-sidebar"') : html.index("</aside>")]
    assert 'href="/external-reporting"' in sidebar
