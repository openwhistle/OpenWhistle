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
    "2026-10-09T10:00:03+00:00 /foo-index.html 200 -",
    "2026-10-09T10:00:04+00:00 /en/style.jpg 200 -",
    "2026-10-09T10:00:05+00:00 /nope/ 404 -",
    "2026-10-09T10:00:06+00:00 /blog/ 301 -",
    "not a counter line",
]


def test_pages_are_html_answers_only_and_referrers_skip_dashes() -> None:
    pages, refs = S.count(LINES)
    assert pages == {"/en/": 3, "/foo-index.html": 1}
    assert refs == {"www.google.com": 1}


def test_the_cli_prints_most_frequent_first(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    cli_lines = [
        "2026-10-09T10:00:00+00:00 /blog/ 200 example.com",
        "2026-10-09T10:00:01+00:00 /en/ 200 www.google.com",
        "2026-10-09T10:00:02+00:00 /en/ 200 www.google.com",
        "2026-10-09T10:00:03+00:00 /en/ 200 -",
    ]
    monkeypatch.setattr(sys, "stdin", io.StringIO("\n".join(cli_lines)))
    assert S.main() == 0
    out = capsys.readouterr().out
    # Within pages: /en/ (3) before /blog/ (1)
    assert out.index("/en/") < out.index("/blog/")
    # Within referrers: www.google.com (2) before example.com (1)
    assert out.index("www.google.com") < out.index("example.com")
