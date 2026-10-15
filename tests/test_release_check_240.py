"""What the Chrome check before 2.4.0 found on the rendered pages."""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
TEMPLATES = ROOT / "app/templates"
CSS = (ROOT / "app/static/css/site.css").read_text()
LOCALES = {p.name: json.loads(p.read_text()) for p in (ROOT / "app/locales").glob("*.json")}
UNITS = (
    r"Tag|Tage|Tagen|Monat|Monate|Monaten|Jahr|Jahre|Jahren|day|days|month|months|year|years"
    r"|jour|jours|mois|ans?|días?|mes|meses|años?|dias?|anos?"
)


def _rule(selector: str) -> str:
    found = re.search(r"(?m)^" + re.escape(selector) + r"\s*\{([^}]*)\}", CSS)
    assert found, selector
    return found.group(1)


def test_no_german_category_is_spelled_without_eszett() -> None:
    """The built-in categories read "Umweltverstoss" and "Datenschutzverstoss"."""
    for key, value in LOCALES["de.json"].items():
        assert "verstoss" not in value.lower(), key


@pytest.mark.asyncio
async def test_migration_019_spells_the_seeded_labels_with_eszett(throwaway_db) -> None:  # noqa: ANN001
    import os
    import subprocess

    from sqlalchemy import text

    from app.config import settings

    env = {**os.environ, "DATABASE_URL": settings.database_url}

    def alembic(*args: str) -> None:
        run = subprocess.run(["alembic", *args], capture_output=True, text=True, env=env)  # noqa: S603, S607
        assert run.returncode == 0, run.stderr

    async def label(slug: str) -> str | None:
        return await throwaway_db.scalar(
            text("SELECT label_de FROM report_categories WHERE slug = :s AND is_default"),
            {"s": slug},
        )

    assert await label("environmental") == "Umweltverstoß"
    assert await label("data_protection") == "Datenschutzverstoß"
    alembic("downgrade", "c3e9a2d5f417")
    assert await label("environmental") == "Umweltverstoss"
    # An operator's own wording survives the migration.
    await throwaway_db.execute(
        text("UPDATE report_categories SET label_de = 'Datenschutz' WHERE slug = 'data_protection'")
    )
    await throwaway_db.commit()
    alembic("upgrade", "head")
    assert await label("environmental") == "Umweltverstoß"
    assert await label("data_protection") == "Datenschutz"


def test_a_citation_or_a_period_does_not_break() -> None:
    """ "(§ 7 | HinSchG)" and "innerhalb von 7 | Tagen" broke across lines: the parts of a
    citation and a number with its unit are joined by non-breaking spaces."""
    for name, strings in LOCALES.items():
        for key, value in strings.items():
            assert not re.search(r"§ ?\d", value), (name, key)
            assert not re.search(r"(Abs\.|Nr\.) \d", value), (name, key)
            assert not re.search(r"§ \d+[a-z]?( \S+)* (HinSchG|BGB|StGB)", value), (name, key)
            assert not re.search(r"\d (" + UNITS + r")\b", value), (name, key)


@pytest.mark.parametrize("area", ["categories", "users", "locations", "organisations"])
def test_an_active_pill_starts_with_a_capital(area: str) -> None:
    for name, strings in LOCALES.items():
        for state in ("active", "inactive"):
            assert strings[f"admin.{area}.{state}"][0].isupper(), (name, area, state)


def test_every_badge_is_drawn_as_a_pill() -> None:
    """A bare `badge` had no fill and no ring: "inactive" and "never checked" were bold text."""
    for page in TEMPLATES.rglob("*.html"):
        assert 'class="badge"' not in page.read_text(), page.name


def test_the_demo_box_adds_no_second_accent() -> None:
    """The fill button was amber beside the green primary button."""
    assert "--warning" not in _rule(".demo-fill-btn") + _rule(".demo-fill-btn:hover")
    assert "letter-spacing" not in _rule(".demo-cred-code")


def test_a_stat_card_does_not_carry_state() -> None:
    """A 2 px ring and a shadow (accent in dark mode) said what the pill inside says."""
    assert "stat-card--" not in CSS
    for page in TEMPLATES.rglob("*.html"):
        assert "stat-card--" not in page.read_text(), page.name


def test_a_short_page_does_not_shift_sideways() -> None:
    rules = re.findall(r"(?m)^html\s*\{([^}]*)\}", CSS)
    assert any("scrollbar-gutter: stable;" in rule for rule in rules)
