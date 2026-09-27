"""The user documentation is measured, so that "a sentence over 30 words" means
the same thing to two people on two days. Ported from easywall's
scripts/prose-check.mjs; this file is the tiebreak, not the authority on style.

Two gates, per file: no prose sentence over 30 words, and an average under 18.

Scope is an exact list, not a walk of docs/. The English landing page and the
comparison page joined it with the website plan of 2026-09-27 (ruling "Prose
limits extend to the landing pages and the blog"). A later page joins by being
added to ``SCOPE``.

What is NOT prose, and why: code and pre blocks, table rows, headings,
script/style, and page chrome (nav, aside, header, footer). Those carry the
keys, paths, numbers and labels a rewrite must keep byte for byte, and
measuring them reports a limits table as one enormous sentence. Inline code
counts as one word: ``SECRET_KEY`` is one thing a reader takes in, and a rule
that punished naming a key would be a rule against being specific.

A word is a whitespace-separated token with at least one letter or digit, so a
dash or an arrow between two clauses is not a word.
"""

import re
from html.parser import HTMLParser
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]

MAX_WORDS = 30
MAX_AVERAGE = 18

SCOPE = sorted(
    [
        ROOT / "docs/docs.html",
        ROOT / "docs/index.html",
        ROOT / "docs/open-source-whistleblowing-software.html",
        ROOT / "docs/roadmap.html",
        ROOT / "docs/hinschg_reference.md",
        *(ROOT / "docs/security").glob("*.md"),
    ]
)

# ── Measuring ──────────────────────────────────────────────────────────────

# An abbreviation does not end a sentence. `etc` is deliberately absent, as in
# easywall: it ends real sentences, and mid-sentence it is followed by a
# lowercase word, which the splitter below never splits on anyway. `Art`,
# `Abs` and `Nr` are the legal citations (Art. 5 GDPR, §17 Abs. 1 HinSchG).
_ABBREVIATION = re.compile(r"\b(e\.g|i\.e|vs|cf|approx|Art|Abs|Nr)\.", re.IGNORECASE)
# A sentence ends at . ! ? (optionally closed by a quote, bracket or emphasis
# marker) followed by whitespace and something that can open a sentence. A
# version number or a path has no whitespace after its dots, so it never splits.
_SENTENCE_END = re.compile(r"(?<=[.!?])[\"')\]*]*\s+(?=[A-Z0-9(\"'`*§])")
_WORD = re.compile(r"\w")


def sentences(text: str) -> list[str]:
    text = _ABBREVIATION.sub(r"\1", " ".join(text.split()))
    return [s.strip() for s in _SENTENCE_END.split(text) if s.strip()]


def word_count(sentence: str) -> int:
    return sum(1 for token in sentence.split() if _WORD.search(token))


_BLOCKS = {"p", "li", "dd", "dt", "figcaption", "blockquote"}
_SKIP = {"script", "style", "pre", "table", "nav", "aside", "header", "footer", "head", "svg"}
_INLINE_CODE = {"code", "kbd", "samp"}


class _ProseParser(HTMLParser):
    """Collects the text of each prose block, one string per block. A nested
    block (a <p> inside an <li>) starts a new unit: three bullets are not one
    sixty-word sentence."""

    def __init__(self) -> None:
        super().__init__()
        self.blocks: list[str] = []
        self._buf: list[str] = []
        self._open: list[str] = []
        self._skip = 0
        self._code = 0

    def _flush(self) -> None:
        text = " ".join("".join(self._buf).split())
        if text:
            self.blocks.append(text)
        self._buf = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        classes = (dict(attrs).get("class") or "").split()
        if tag in _SKIP:
            self._skip += 1
        elif self._skip:
            return
        elif tag in _BLOCKS or "security-layer-desc" in classes:
            self._flush()
            self._open.append(tag)
        elif tag in _INLINE_CODE and self._open:
            if not self._code:
                self._buf.append(" CODE ")
            self._code += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP:
            self._skip = max(0, self._skip - 1)
        elif self._skip:
            return
        elif tag in _INLINE_CODE and self._code:
            self._code -= 1
        elif tag in self._open:
            # Optional end tags (an unclosed <li>) close everything above them.
            self._flush()
            del self._open[len(self._open) - 1 - self._open[::-1].index(tag) :]

    def handle_data(self, data: str) -> None:
        if self._open and not self._skip and not self._code:
            self._buf.append(data)


def html_prose(html: str) -> list[str]:
    parser = _ProseParser()
    parser.feed(html)
    parser.close()
    parser._flush()
    return parser.blocks


def _clean_md(line: str) -> str:
    line = re.sub(r"`[^`]*`", "CODE", line)
    line = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", line)
    return re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", line)


def md_prose(md: str) -> list[str]:
    """Paragraphs and list items of a Markdown page. Skipped: front matter,
    fenced code, table rows, headings, horizontal rules, raw HTML lines."""
    out: list[str] = []
    buf: list[str] = []
    fenced = front = False

    def flush() -> None:
        if buf:
            out.append(" ".join(buf))
            buf.clear()

    for i, raw in enumerate(md.splitlines()):
        line = re.sub(r"^(>\s?)+", "", raw.strip())
        if i == 0 and line == "---":
            front = True
            continue
        if front:
            front = line != "---"
            continue
        if line.startswith("```"):
            fenced = not fenced
            flush()
            continue
        if fenced:
            continue
        if not line or re.match(r"^(\||#{1,6}\s|<|-{3,}$|\*{3,}$)", line):
            flush()
            continue
        item = re.match(r"^([-*+]|\d+\.)\s+", line)
        if item:
            flush()
            line = line[item.end() :]
        buf.append(_clean_md(line))
    flush()
    return out


def measure(path: Path) -> list[int]:
    """Word count of every prose sentence on the page, in order."""
    text = path.read_text(encoding="utf-8")
    blocks = html_prose(text) if path.suffix == ".html" else md_prose(text)
    return [word_count(s) for b in blocks for s in sentences(b)]


def breaches(path: Path) -> list[str]:
    text = path.read_text(encoding="utf-8")
    blocks = html_prose(text) if path.suffix == ".html" else md_prose(text)
    return [
        f"{word_count(s)} words: {' '.join(s.split()[:12])} ..."
        for b in blocks
        for s in sentences(b)
        if word_count(s) > MAX_WORDS
    ]


# ── The gates ──────────────────────────────────────────────────────────────


def test_the_scope_exists() -> None:
    missing = [p for p in SCOPE if not p.is_file()]
    assert not missing, f"scoped page(s) gone — update SCOPE: {missing}"
    assert any(p.parent.name == "security" for p in SCOPE), "docs/security/*.md matched nothing"


@pytest.mark.parametrize("path", SCOPE, ids=lambda p: str(p.relative_to(ROOT)))
def test_no_sentence_is_over_30_words(path: Path) -> None:
    found = breaches(path)
    assert not found, (
        f"{path.relative_to(ROOT)}: {len(found)} sentence(s) over {MAX_WORDS} words\n  "
        + "\n  ".join(found)
    )


@pytest.mark.parametrize("path", SCOPE, ids=lambda p: str(p.relative_to(ROOT)))
def test_the_average_sentence_is_under_18_words(path: Path) -> None:
    counts = measure(path)
    assert counts, f"{path.relative_to(ROOT)}: no prose found — the parser lost the page"
    average = sum(counts) / len(counts)
    assert average < MAX_AVERAGE, (
        f"{path.relative_to(ROOT)}: average {average:.1f} words over {len(counts)} "
        f"sentences, want under {MAX_AVERAGE}"
    )


# ── The measuring, pinned ──────────────────────────────────────────────────


def test_the_splitter_and_counter_are_pinned() -> None:
    text = (
        "Set `SECRET_KEY` first, e.g. with openssl. Version 2.0.0 lives in docs/x.md — "
        "see Art. 5 GDPR! Is it done? Yes."
    )
    assert sentences(text) == [
        "Set `SECRET_KEY` first, e.g with openssl.",
        "Version 2.0.0 lives in docs/x.md — see Art 5 GDPR!",
        "Is it done?",
        "Yes.",
    ]
    # The dash is not a word; inline code is one.
    assert [word_count(s) for s in sentences(text)] == [6, 9, 3, 1]


def test_html_prose_skips_code_tables_headings_and_chrome() -> None:
    html = """
    <nav><p>Nav text is chrome and never counted.</p></nav>
    <h2>A heading is not prose</h2>
    <p>Run <code>docker compose up -d --build now</code> to start.</p>
    <ul><li>One item.</li><li>Another item here.</li></ul>
    <table><tr><td>A cell is not a gated sentence at all.</td></tr></table>
    <pre>not prose either</pre>
    <script>var notProse = 1;</script>
    <footer><p>Footer.</p></footer>
    """
    assert html_prose(html) == ["Run CODE to start.", "One item.", "Another item here."]


def test_md_prose_skips_front_matter_fences_tables_headings_and_html() -> None:
    md = (
        "---\ntitle: x\n---\n# Heading\n\nA paragraph that\nwraps over two lines.\n\n"
        "```\ncode block\n```\n| a | b |\n<div>raw</div>\n- An item with a [link](https://x).\n"
        "- Second `item`.\n"
    )
    assert md_prose(md) == [
        "A paragraph that wraps over two lines.",
        "An item with a link.",
        "Second CODE.",
    ]


def test_the_gates_are_red_on_a_bad_page_and_green_on_a_good_one(tmp_path: Path) -> None:
    long = " ".join(["word"] * (MAX_WORDS + 1)) + "."
    bad = tmp_path / "bad.html"
    bad.write_text(f"<p>{long} Short one.</p>")
    assert breaches(bad) == [f"{MAX_WORDS + 1} words: {' '.join(['word'] * 12)} ..."]

    good = tmp_path / "good.md"
    good.write_text(
        "# Page\n\nThe wizard creates the admin. It asks for a password.\n\n- Save the PIN.\n"
    )
    assert breaches(good) == []
    assert measure(good) == [5, 5, 3]
    assert sum(measure(good)) / len(measure(good)) < MAX_AVERAGE
