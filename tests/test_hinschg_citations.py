"""Every "§ N Abs. M" (and "Nr. K") the README and the interface cite must exist
in the HinSchG (the website checks its own pages). The docs once cited § 17
Abs. 3 and § 16 Abs. 7, which do not exist, and § 26 for data protection, which
is about external reporting offices. A new citation of a section missing below
fails here until someone has checked it against
https://www.gesetze-im-internet.de/hinschg/ and added its shape."""

import re
from pathlib import Path

ROOT = Path(__file__).parents[1]

# Section -> number of Absätze; per Absatz, the number of Nr. where cited.
SHAPE: dict[int, tuple[int, dict[int, int]]] = {
    2: (3, {1: 11}),
    3: (10, {8: 7}),
    7: (3, {}),
    8: (2, {}),
    9: (4, {}),
    11: (5, {}),
    12: (4, {}),
    13: (2, {}),
    14: (2, {}),
    16: (3, {}),
    17: (2, {1: 6}),
    26: (3, {}),
    40: (6, {2: 3}),
    42: (2, {}),
}

_OTHER_LAW = re.compile(
    r"\s*(?:[A-Za-z.\s\d]{0,8})?"
    r"\b(?:StGB|DSGVO|BetrVG|OWiG|BDSG|UWG|BGB|GG|AktG|GmbHG|KWG|LkSG|BPersVG|MStV|TDDDG)\b"
)
_CITE = re.compile(r"§\s?(\d+)\s?(?:Abs\.|Absatz|al\.)\s?(\d+)(?:\s?(?:Nr\.|Satz)\s?(\d+))?")


def _files() -> list[Path]:
    # CHANGELOG.md is rendered publicly at openwhistle.net/changelog, so its
    # citations are held to the same check — two 1.x entries cited a wrong section.
    return [ROOT / "README.md", ROOT / "CHANGELOG.md", *(ROOT / "app" / "locales").glob("*.json")]


_RETENTION = re.compile(r"retention|delete|deletion|aufbewahr|lösch", re.IGNORECASE)


def test_every_cited_absatz_exists() -> None:
    wrong = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for m in _CITE.finditer(text):
            section, absatz = int(m.group(1)), int(m.group(2))
            if _OTHER_LAW.match(text[m.end() : m.end() + 16]):
                continue  # § 87 BetrVG, § 201 StGB, § 30 OWiG ...
            shape = SHAPE.get(section)
            if shape is None:
                wrong.append(f"{path.relative_to(ROOT)}: {m.group(0)} (section not checked yet)")
            elif absatz > shape[0]:
                wrong.append(f"{path.relative_to(ROOT)}: {m.group(0)} (§ {section} has {shape[0]})")
            elif m.group(3) and "Nr" in m.group(0):
                limit = shape[1].get(absatz)
                if limit is None or int(m.group(3)) > limit:
                    wrong.append(f"{path.relative_to(ROOT)}: {m.group(0)} (no such Nr.)")
    assert not wrong, wrong


def test_the_retention_basis_is_para_11_not_12() -> None:
    """The three-year deletion rule is HinSchG § 11 Abs. 5 — a deletion deadline, not
    a § 12 Abs. 3 minimum (§ 12 Abs. 3 is the finance-sector rule). The existence
    check above passes a § 12 Abs. 3 cite because that Absatz exists; this couples the
    section to its subject so the pairing that shipped in two 1.x changelog entries
    cannot return."""
    wrong = []
    for path in _files():
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r"§\s?12\b", text):
            window = text[max(0, m.start() - 180) : m.end() + 60]
            if (
                _RETENTION.search(window)
                and "§11" not in window
                and "§ 11" not in window
                and not re.search(r"(?:not|nicht)\s*§\s?12", window)
            ):
                wrong.append(f"{path.relative_to(ROOT)}: …{window.strip()}…")
    assert not wrong, wrong
