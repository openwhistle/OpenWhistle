"""Share of en.json keys each other locale really translates, as a shields.io endpoint badge.

    python3 scripts/i18n_coverage.py                 # print the table
    python3 scripts/i18n_coverage.py --badge FILE    # also write the endpoint JSON

A key counts as translated when it is present, non-empty and differs from the English
string; an identical string counts only for a term of at most three words (Name, Actions).
Key parity itself is enforced by tests/test_locales.py.
"""

import argparse
import json
from pathlib import Path

LOCALES = Path(__file__).resolve().parent.parent / "app" / "locales"
TERM_MAX_WORDS = 3


def coverage(en: dict[str, str], other: dict[str, str]) -> float:
    done = 0
    for key, source in en.items():
        value = other.get(key, "")
        if value.strip() and (value != source or len(source.split()) <= TERM_MAX_WORDS):
            done += 1
    return 100 * done / len(en)


def load(directory: Path = LOCALES) -> dict[str, float]:
    en = json.loads((directory / "en.json").read_text(encoding="utf-8"))
    return {
        p.stem: coverage(en, json.loads(p.read_text(encoding="utf-8")))
        for p in sorted(directory.glob("*.json"))
        if p.stem != "en"
    }


def badge(per_locale: dict[str, float]) -> dict[str, object]:
    low = min(per_locale.values())  # the weakest language, not an average that hides it
    return {
        "schemaVersion": 1,
        "label": "i18n",
        "message": f"{int(low)}%",  # floor: 99.9 must not read as 100
        "color": "brightgreen" if low >= 100 else "yellow" if low >= 90 else "red",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--badge", type=Path)
    args = parser.parse_args()
    result = load()
    for lang, pct in result.items():
        print(f"{lang:6} {pct:6.2f} %")
    if args.badge:
        args.badge.write_text(json.dumps(badge(result)) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
