"""Every locale-key pattern templates build dynamically (`t(prefix + value)`)
must resolve for every value the driving enum can take — in every language.

`t()` on a miss returns the key itself (app/templating.py's `template_translator`),
so a template calling `t('role.label.' + role.value)` for a value nobody added a
translation for shows the raw key text ("role.label.superadmin") to an admin.
That happened in production: /admin/users listed `role.label.superadmin` in the
role select and the users table because only `role.label.admin` and
`role.label.case_manager` existed. This test enumerates every such dynamic
pattern found by grepping `app/templates/**/*.html` for `t('prefix' + value)` /
`t('prefix' ~ value)` against a closed, enumerable set of values (a Python enum
or an equivalent fixed list) and fails on any locale missing a key — including
the current tree, for `role.label.superadmin`.

Patterns NOT covered here have a documented reason:
  - `audit.detail.` + k and `audit.detail.via.` + v (admin/_audit.html): k/v are
    free-form audit-log detail keys/values, not a closed enum, and the
    `_value`/`translated` macros already fall back to the raw value on a miss
    (`label == key` check) — no raw key ever reaches the page.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

import pytest

from app.models.report import ReportStatus
from app.models.user import AdminRole
from app.services.audit import ALL_ACTIONS

_LOCALES = Path(__file__).resolve().parent.parent / "app" / "locales"
_LANGS = ("en", "de", "fr", "es", "pt-br")

# (locale-key prefix, values, template — for the assertion message).
# status.progress.*.desc: status.html only reaches this dynamic lookup for a
# status NOT in ('in_review', 'pending_feedback') — those two show a fixed
# 'status.progress.acknowledged.desc' key instead (see status.html).
_DYNAMIC_KEY_PATTERNS: tuple[tuple[str, tuple[str, ...], str], ...] = (
    ("role.label.", tuple(r.value for r in AdminRole), "admin/users.html etc."),
    ("status.label.", tuple(s.value for s in ReportStatus), "status.html etc."),
    ("audit.action.", tuple(ALL_ACTIONS), "admin/_audit.html"),
    (
        "status.progress.",
        tuple(s.value for s in ReportStatus if s.value not in ("in_review", "pending_feedback")),
        "status.html (progress description)",
    ),
)


def _locale(lang: str) -> dict[str, str]:
    return json.loads((_LOCALES / f"{lang}.json").read_text(encoding="utf-8"))


@pytest.mark.parametrize("lang", _LANGS)
def test_every_dynamic_locale_key_exists(lang: str) -> None:
    strings = _locale(lang)
    missing = []
    for prefix, values, template in _DYNAMIC_KEY_PATTERNS:
        for value in values:
            suffix = ".desc" if prefix == "status.progress." else ""
            key = f"{prefix}{value}{suffix}"
            if key not in strings:
                missing.append(f"{key} (built by {template})")
    assert not missing, (lang, missing)


def test_every_locale_file_is_a_supported_language() -> None:
    """A new locale reaches the code's lists and the site's count (PR #126: the home page
    still said "4 languages")."""
    from app.i18n import _SUPPORTED

    files = {p.stem for p in _LOCALES.glob("*.json")}
    assert files == set(_LANGS) == _SUPPORTED
    docs = _LOCALES.parents[1] / "docs"
    assert f"{len(files)} languages:" in (docs / "en" / "index.html").read_text(encoding="utf-8")
    assert f"{len(files)} Sprachen:" in (docs / "de" / "index.html").read_text(encoding="utf-8")


# Each locale's name in the site's English and German prose. A new locale must add its names here.
_LANGUAGE_NAMES = {
    "en": ("English", "Englisch"),
    "de": ("German", "Deutsch"),
    "fr": ("French", "Französisch"),
    "es": ("Spanish", "Spanisch"),
    "pt-br": ("Brazilian Portuguese", "Portugiesisch"),
}

# Every passage of the site that lists the interface languages: (page, sentence pattern, how many).
_LANGUAGE_LISTS = [
    ("en/index.html", r"The interface is in (.*?)\.", 2),  # FAQ and its FAQPage JSON-LD
    ("en/index.html", r"\d+ languages: (.*?)</td>", 1),
    ("de/index.html", r"Die Oberfläche gibt es auf (.*?)\.", 2),
    ("de/index.html", r"\d+ Sprachen: (.*?)</td>", 1),
    ("en/contribute/index.html", r"The app speaks (.*?)\.", 1),
    ("de/mitmachen/index.html", r"Die App spricht (.*?)\.", 1),
]


def test_every_site_language_list_names_every_locale() -> None:
    """The count row was guarded; the lists beside it were not, and the Contribute pages kept
    naming four languages after Spanish arrived."""
    from app.i18n import _SUPPORTED

    assert set(_LANGUAGE_NAMES) == _SUPPORTED
    docs = _LOCALES.parents[1] / "docs"
    stale = []
    for name, pattern, count in _LANGUAGE_LISTS:
        lists = re.findall(pattern, (docs / name).read_text(encoding="utf-8"))
        assert len(lists) == count, (name, pattern, lists)
        german = name.startswith("de/")
        for listed in lists:
            stale += [
                (name, n[german]) for n in _LANGUAGE_NAMES.values() if n[german] not in listed
            ]
    assert not stale, stale
