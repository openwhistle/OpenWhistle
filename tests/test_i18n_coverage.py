"""scripts/i18n_coverage.py: what counts as translated, and the badge it publishes."""

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).parents[1]
_spec = importlib.util.spec_from_file_location("i18n_coverage", ROOT / "scripts/i18n_coverage.py")
assert _spec and _spec.loader
cov = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(cov)

EN = {"a": "Submit your report now please", "b": "Name", "c": "Another long English sentence here"}


def test_untranslated_missing_and_empty_keys_do_not_count() -> None:
    other = {"a": "Submit your report now please", "b": "Name", "c": " "}
    assert cov.coverage(EN, other) == 100 / 3  # only the identical short term "Name"
    assert cov.coverage(EN, {}) == 0


def test_translated_keys_and_short_identical_terms_count() -> None:
    other = {"a": "Meldung jetzt abgeben", "b": "Name", "c": "Noch ein langer Satz hier"}
    assert cov.coverage(EN, other) == 100


def test_badge_shows_the_weakest_locale_rounded_down() -> None:
    b = cov.badge({"de": 100.0, "fr": 99.9})
    assert (b["message"], b["color"]) == ("99%", "yellow")
    assert cov.badge({"de": 100.0})["color"] == "brightgreen"
    assert cov.badge({"de": 80.0})["color"] == "red"


def test_every_shipped_locale_is_fully_translated(tmp_path: Path) -> None:
    result = cov.load()
    assert set(result) >= {"de", "fr", "es", "pt-br"}
    assert {k: v for k, v in result.items() if v < 100} == {}
    out = tmp_path / "i18n.json"
    out.write_text(json.dumps(cov.badge(result)))
    assert json.loads(out.read_text())["message"] == "100%"
