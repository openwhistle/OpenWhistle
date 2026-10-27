"""The admin "add" forms live in a modal <dialog> opened from the page heading,
so the list — not a second form stacked above it — is the page. Three things
must hold on every such page, or the pattern silently breaks:

  - an opener carries ``data-dialog-open="<id>"`` and a ``<dialog id="<id>"
    class="… dialog-panel …">`` answers to that exact id — a typo'd id opens a
    button that does nothing;
  - the dialog reopens itself on a server validation error (``data-dialog-autoshow``
    guarded by ``field_errors``), or the inline field error renders behind a
    closed dialog where the admin never sees it;
  - base.html ships the ``<noscript>`` fallback that reveals ``dialog.dialog-panel``
    inline as a panel and hides ``[data-dialog-open]`` — without it a browser with
    JavaScript off cannot add a row at all.

These are template-structure checks; the server side (a real 422 carrying the
reopen marker) is covered by test_coverage_gaps.test_create_user_duplicate_username_409.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

TEMPLATES = Path(__file__).parents[1] / "app" / "templates"

# (template, the dialog's id).
ADD_PAGES: tuple[tuple[str, str], ...] = (
    ("admin/users.html", "add-user-dialog"),
    ("admin/categories.html", "add-category-dialog"),
    ("admin/locations.html", "add-location-dialog"),
    ("admin/organisations.html", "add-organisation-dialog"),
)


def _html(tpl: str) -> str:
    return (TEMPLATES / tpl).read_text(encoding="utf-8")


@pytest.mark.parametrize("tpl,dialog_id", ADD_PAGES, ids=lambda v: v)
def test_opener_targets_an_existing_dialog(tpl: str, dialog_id: str) -> None:
    html = _html(tpl)
    assert f'data-dialog-open="{dialog_id}"' in html, f"{tpl}: no opener for {dialog_id}"
    assert re.search(
        rf'<dialog id="{re.escape(dialog_id)}"[^>]*\bclass="[^"]*\bdialog-panel\b', html
    ), f"{tpl}: no <dialog> with id {dialog_id} and class dialog-panel"


@pytest.mark.parametrize("tpl,dialog_id", ADD_PAGES, ids=lambda v: v)
def test_dialog_reopens_on_validation_error(tpl: str, dialog_id: str) -> None:
    # The marker is conditional on field_errors, so a clean GET keeps it closed.
    assert re.search(r"\{%\s*if field_errors\s*%\}\s*data-dialog-autoshow", _html(tpl)), (
        f"{tpl}: data-dialog-autoshow is not guarded by field_errors"
    )


@pytest.mark.parametrize("tpl,dialog_id", ADD_PAGES, ids=lambda v: v)
def test_dialog_has_a_close_control(tpl: str, dialog_id: str) -> None:
    assert "data-dialog-close" in _html(tpl), f"{tpl}: dialog has no close control"


@pytest.mark.parametrize("tpl,dialog_id", ADD_PAGES, ids=lambda v: v)
def test_dialog_is_labelled_by_its_heading(tpl: str, dialog_id: str) -> None:
    # A modal <dialog> with no accessible name is announced only as "dialog"
    # (WCAG 4.1.2); aria-labelledby must name an element that exists in the page.
    html = _html(tpl)
    m = re.search(rf'<dialog id="{re.escape(dialog_id)}"[^>]*\baria-labelledby="([^"]+)"', html)
    assert m, f"{tpl}: dialog {dialog_id} has no aria-labelledby"
    label_id = m.group(1)
    assert f'id="{label_id}"' in html, f"{tpl}: aria-labelledby points to a missing id {label_id}"


def test_base_ships_the_no_js_fallback() -> None:
    html = _html("base.html")
    assert "<noscript>" in html
    assert "dialog.dialog-panel" in html, "base.html: no-JS style does not reveal the dialog panel"
    assert "[data-dialog-open]" in html, "base.html: no-JS style does not hide the dialog opener"
    # style-src carries no 'unsafe-inline' (app/middleware.py), so an un-nonced
    # <style> is silently dropped by CSP and the fallback never applies.
    assert re.search(r"<noscript>\s*<style nonce=", html), (
        "base.html: the no-JS <style> carries no CSP nonce"
    )
