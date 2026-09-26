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
from pathlib import Path

import pytest

from app.models.report import ReportStatus
from app.models.user import AdminRole
from app.services.audit import ALL_ACTIONS

_LOCALES = Path(__file__).resolve().parent.parent / "app" / "locales"
_LANGS = ("en", "de", "fr", "pt-br")

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
        tuple(
            s.value
            for s in ReportStatus
            if s.value not in ("in_review", "pending_feedback")
        ),
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
