#!/usr/bin/env python3
"""docs/ -> _site/: the build of openwhistle.net.

    uv run --group site python scripts/build_site.py                  write _site/
    uv run --group site python scripts/build_site.py --redirect-stubs plus HTML
                                                                      stubs for
                                                                      GitHub Pages

The rules, each pinned by tests/test_build_site.py:

- a path with a part starting with "_" never reaches the output;
- a .md or .html file is a page and opens with YAML front matter;
- every other file is copied byte for byte;
- docs/<dir>/<name>.<ext> is served at /<dir>/<name>/, index.<ext> at /<dir>/;
- a page's language is its first path segment when that is a language in
  _data/site.yml, otherwise its front matter `lang`;
- a body is HTML (or Markdown rendered to HTML) and is never evaluated as Jinja;
- every internal link and fragment resolves, or the build fails.
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from pathlib import Path
from urllib.parse import unquote

import yaml
from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markdown_it import MarkdownIt

ROOT = Path(__file__).resolve().parents[1]
DOCS = ROOT / "docs"

PAGE_KEYS = {
    "title", "description", "translation_key", "lang", "css", "js", "og_type",
    "published", "modified", "section", "jsonld", "noindex", "generated",
}
REQUIRED_KEYS = {"title", "description", "translation_key"}
_FRONT_MATTER = re.compile(r"\A---\n(?:(.*?)\n)?---(?:\n|\Z)", re.DOTALL)
MARKDOWN = MarkdownIt("commonmark", {"html": True}).enable("table")


class BuildError(Exception):
    """A source the build refuses. The message names the file and the rule."""


@dataclass
class Page:
    source: Path  # relative to the source root
    url: str  # site-absolute, e.g. "/en/docs/"
    lang: str
    meta: dict
    content: str  # HTML between the navigation and the footer
    alternates: dict[str, str] = field(default_factory=dict)  # language -> url


def url_for(rel: Path) -> str:
    if rel.as_posix() == "404.html":
        return "/404.html"
    parts = list(rel.with_suffix("").parts)
    if parts[-1] == "index":
        parts.pop()
    return "/" + "".join(f"{part}/" for part in parts)


def output_file(out: Path, url: str) -> Path:
    path = out / unquote(url).lstrip("/")
    return path if url.endswith(".html") else path / "index.html"


def split_front_matter(rel: Path, text: str) -> tuple[dict, str]:
    if not text.startswith("---\n"):
        raise BuildError(f"{rel}: a page must open with '---' front matter")
    closed = _FRONT_MATTER.match(text)
    if not closed:
        raise BuildError(f"{rel}: the front matter is never closed with '---'")
    try:
        meta = yaml.safe_load(closed.group(1) or "") or {}
    except yaml.YAMLError as error:
        raise BuildError(f"{rel}: front matter is not valid YAML: {error}") from error
    if not isinstance(meta, dict):
        raise BuildError(f"{rel}: front matter must be a mapping")
    return meta, text[closed.end() :]


def _flatten(tree: dict, prefix: str = "") -> Iterator[str]:
    for key, value in tree.items():
        if isinstance(value, dict):
            yield from _flatten(value, f"{prefix}{key}.")
        else:
            yield prefix + key


def lookup(tree: dict, dotted: str) -> str:
    for part in dotted.split("."):
        tree = tree[part]
    return str(tree)


def _yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def load_data(src: Path) -> dict:
    data = src / "_data"
    site = _yaml(data / "site.yml")
    # One version string: the app's. A footer that typed it by hand would go stale.
    site["version"] = re.search(
        r'app_version: str = "([^"]+)"', (ROOT / "app" / "config.py").read_text(encoding="utf-8")
    ).group(1)
    i18n = {lang: _yaml(data / "i18n" / f"{lang}.yml") for lang in site["languages"]}
    want = set(_flatten(i18n[site["default_language"]]))
    for lang, strings in i18n.items():
        have = set(_flatten(strings))
        if have != want:
            raise BuildError(
                f"_data/i18n/{lang}.yml: missing {sorted(want - have)}, extra {sorted(have - want)}"
            )
    return {
        "site": site,
        "i18n": i18n,
        "nav": _yaml(data / "nav.yml"),
        "redirects": _yaml(data / "redirects.yml"),
    }


GENERATORS: dict[str, Callable[[], str]] = {}


def _is_skipped(rel: Path) -> bool:
    return any(part.startswith("_") for part in rel.parts)


def load_pages(src: Path, site: dict) -> list[Page]:
    pages: list[Page] = []
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src)
        if _is_skipped(rel) or path.suffix not in {".md", ".html"}:
            continue
        meta, body = split_front_matter(rel, path.read_text(encoding="utf-8"))
        if unknown := set(meta) - PAGE_KEYS:
            raise BuildError(f"{rel}: unknown front matter {sorted(unknown)}")
        if missing := REQUIRED_KEYS - set(meta):
            raise BuildError(f"{rel}: front matter lacks {sorted(missing)}")
        in_language_dir = len(rel.parts) > 1 and rel.parts[0] in site["languages"]
        lang = rel.parts[0] if in_language_dir else meta.get("lang")
        if lang not in site["languages"]:
            raise BuildError(f"{rel}: no language; put it under /<lang>/ or set `lang`")
        if "generated" in meta:
            if meta["generated"] not in GENERATORS:
                raise BuildError(f"{rel}: unknown generator {meta['generated']!r}")
            content = GENERATORS[meta["generated"]]()
        else:
            content = MARKDOWN.render(body) if path.suffix == ".md" else body
        for key in ("css", "js", "jsonld"):
            meta.setdefault(key, [])
        pages.append(Page(rel, url_for(rel), lang, meta, content))

    seen: dict[str, Page] = {}
    for page in pages:
        if page.url in seen:
            raise BuildError(f"{page.source} and {seen[page.url].source} are both {page.url}")
        seen[page.url] = page

    groups: dict[str, dict[str, Page]] = {}
    for page in pages:
        group = groups.setdefault(str(page.meta["translation_key"]), {})
        if page.lang in group:
            raise BuildError(
                f"{page.source} and {group[page.lang].source}: translation_key "
                f"{page.meta['translation_key']!r} twice in {page.lang}"
            )
        group[page.lang] = page
    for group in groups.values():
        for page in group.values():
            page.alternates = {lang: other.url for lang, other in group.items()}
    return pages


def environment(src: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader([src / "_layouts", src / "_includes"]),
        autoescape=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def render_page(env: Environment, page: Page, data: dict) -> str:
    return env.get_template("base.html").render(
        page=page, site=data["site"], t=data["i18n"][page.lang]
    )


def _refuse_dangerous_out(src: Path, out: Path) -> None:
    """build() empties `out`; it must never be the sources, above them, or inside them."""
    out, src = out.resolve(), src.resolve()
    if out == src or out in src.parents or src in out.parents:
        raise BuildError(f"--out {out} would overwrite the sources in {src}")


def build(src: Path, out: Path, *, redirect_stubs: bool = False) -> list[Page]:
    _refuse_dangerous_out(src, out)
    data = load_data(src)
    site = data["site"]
    pages = load_pages(src, site)

    if out.is_file():
        raise BuildError(f"--out {out} is a file")
    if out.exists():
        shutil.rmtree(out)
    for path in sorted(p for p in src.rglob("*") if p.is_file()):
        rel = path.relative_to(src)
        if not _is_skipped(rel) and path.suffix not in {".md", ".html"}:
            (out / rel).parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, out / rel)

    env = environment(src)
    for page in pages:
        dest = output_file(out, page.url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_page(env, page, data), encoding="utf-8")
    return pages


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build openwhistle.net from docs/.")
    parser.add_argument("--src", type=Path, default=DOCS)
    parser.add_argument("--out", type=Path, default=ROOT / "_site")
    parser.add_argument("--redirect-stubs", action="store_true", help="HTML stubs for GitHub Pages")
    args = parser.parse_args(argv)
    try:
        pages = build(args.src, args.out, redirect_stubs=args.redirect_stubs)
    except BuildError as error:
        print(f"build failed: {error}", file=sys.stderr)
        return 1
    print(f"wrote {len(pages)} pages to {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
