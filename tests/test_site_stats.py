import importlib.util
import io
import sys
from pathlib import Path

ROOT = Path(__file__).parents[1]
spec = importlib.util.spec_from_file_location("site_stats", ROOT / "scripts" / "site_stats.py")
assert spec and spec.loader
S = importlib.util.module_from_spec(spec)
spec.loader.exec_module(S)

LINES = [
    "2026-10-09T10:00:00+00:00 /en/ 200 -",
    "2026-10-09T10:00:01+00:00 /en/ 200 www.google.com",
    "2026-10-09T10:00:01+00:00 /en/index.html 200 -",
    "2026-10-09T10:00:02+00:00 /assets/css/base.css 200 openwhistle.net",
    "2026-10-09T10:00:03+00:00 /nope/ 404 -",
    "2026-10-09T10:00:04+00:00 /blog/ 301 -",
    "not a counter line",
]


def test_pages_are_html_answers_only_and_referrers_skip_dashes() -> None:
    pages, refs = S.count(LINES)
    assert pages == {"/en/": 3}
    assert refs == {"www.google.com": 1, "openwhistle.net": 1}


def test_the_cli_prints_most_frequent_first(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(LINES)))
    assert S.main() == 0
    out = capsys.readouterr().out
    assert out.index("/en/") < out.index("www.google.com")
