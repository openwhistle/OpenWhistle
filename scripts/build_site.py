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
import datetime
import html
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from types import ModuleType
from urllib.parse import unquote, urljoin, urlsplit

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
# A table scrolls inside its own box (.table-scroll), so a wide one never widens a phone page.
MARKDOWN.add_render_rule(
    "table_open", lambda *_: '<div class="table-scroll"><table class="env-table">\n'
)
MARKDOWN.add_render_rule("table_close", lambda *_: "</table></div>\n")


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
    try:
        return yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as error:
        raise BuildError(f"{path.name}: not valid YAML: {error}") from error


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


def _load_script(name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module  # @dataclass looks its module up here
    spec.loader.exec_module(module)
    return module


def _changelog() -> str:
    changelog = _load_script("render_changelog")
    source = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    return changelog.render_content(*changelog.parse(source))


# generator name -> (function, the file its output comes from)
GENERATORS: dict[str, tuple[Callable[[], str], Path]] = {
    "changelog": (_changelog, ROOT / "CHANGELOG.md")
}


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
            if body.strip():
                raise BuildError(f"{rel}: a generated page has a body, which would be dropped")
            content = GENERATORS[meta["generated"]][0]()
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


def language_roots(site: dict) -> set[str]:
    return {f"/{lang}/" for lang in site["languages"]}


def hreflang(page: Page, site: dict) -> list[tuple[str, str]]:
    """The <link rel=alternate> set, shared by the head and the sitemap."""
    if len(page.alternates) < 2:
        return []
    base = site["base_url"]
    links = [(lang, base + url) for lang, url in sorted(page.alternates.items())]
    if page.url in language_roots(site):
        links.append(("x-default", base + "/"))  # "/" chooses the language
    elif site["default_language"] in page.alternates:
        links.append(("x-default", base + page.alternates[site["default_language"]]))
    return links


def nav_context(
    page: Page, nav: dict, by_key: dict[str, dict[str, Page]], site: dict, t: dict
) -> dict:
    roots = language_roots(site)

    def items(section: str) -> list[dict]:
        out = []
        for entry in nav.get(section, []):
            group = by_key[entry["page"]]
            # A page that exists only in the default language is linked there.
            target = group.get(page.lang) or group[site["default_language"]]
            fragment = entry.get("fragment")
            current = not fragment and (
                page.url == target.url
                or (target.url not in roots and page.url.startswith(target.url))
            )
            out.append({
                "label": lookup(t, entry["label"]),
                "href": target.url + (f"#{fragment}" if fragment else ""),
                "current": current,
            })
        return out

    languages = [
        {
            "lang": lang,
            "name": spec["name"],
            "href": page.alternates.get(lang, f"/{lang}/"),
        }
        for lang, spec in site["languages"].items()
        if lang != page.lang
    ]
    return {"primary": items("primary"), "footer": items("footer"), "languages": languages}


def check_nav(nav: dict, pages: list[Page], site: dict) -> None:
    keys = {str(p.meta["translation_key"]) for p in pages}
    named: set[str] = set()
    for section in ("primary", "footer"):
        for entry in nav.get(section, []):
            if entry["page"] not in keys:
                raise BuildError(
                    f"_data/nav.yml: {section} names {entry['page']!r}, which no page has"
                )
            named.add(entry["page"])
    targets = {p.url for p in pages if p.meta["translation_key"] in named}
    prefixes = targets - language_roots(site)
    for page in pages:
        if page.meta.get("noindex") or page.url in targets:
            continue
        if not any(page.url.startswith(prefix) for prefix in prefixes):
            raise BuildError(f"{page.source}: no entry of _data/nav.yml leads to {page.url}")


def environment(src: Path) -> Environment:
    return Environment(
        loader=FileSystemLoader([src / "_layouts", src / "_includes"]),
        autoescape=True,
        undefined=StrictUndefined,
        keep_trailing_newline=True,
    )


def render_page(
    env: Environment, page: Page, data: dict, by_key: dict[str, dict[str, Page]]
) -> str:
    site, t = data["site"], data["i18n"][page.lang]
    return env.get_template("base.html").render(
        page=page,
        site=site,
        t=t,
        locale=site["languages"][page.lang]["locale"],
        alternate_locales=[
            site["languages"][lang]["locale"] for lang in page.alternates if lang != page.lang
        ],
        hreflang=hreflang(page, site),
        nav=nav_context(page, data["nav"], by_key, site, t),
    )


class _Refs(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.ids: set[str] = set()
        self.refs: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        a = {k: v for k, v in attrs if v is not None}
        if "id" in a:
            self.ids.add(a["id"])
        if tag == "a" and "name" in a:
            self.ids.add(a["name"])
        self.refs += [a[k] for k in ("href", "src") if k in a]
        if "srcset" in a:
            self.refs += [part.split()[0] for part in a["srcset"].split(",") if part.strip()]


def check_links(out: Path, host: str) -> None:
    parsed: dict[Path, _Refs] = {}
    for file in sorted(out.rglob("*.html")):
        parser = _Refs()
        parser.feed(file.read_text(encoding="utf-8"))
        parsed[file] = parser
    errors = []
    for file, parser in parsed.items():
        here = "/" + file.relative_to(out).as_posix()
        for ref in parser.refs:
            parts = urlsplit(urljoin(here, ref))
            if parts.scheme and parts.scheme not in ("http", "https"):
                continue
            if parts.netloc and parts.netloc.lower() != host.lower():
                continue
            # / is the language choice: a stub on Pages, nginx from P4
            if parts.path in ("/", "/index.html"):
                continue
            target = out / unquote(parts.path).lstrip("/")
            if parts.path.endswith("/"):
                target = target / "index.html"
            try:
                target.resolve().relative_to(out.resolve())
            except ValueError:
                errors.append(
                    f"{here}: {ref} -> traversal outside output at {parts.path}"
                )
                continue
            if not target.is_file():
                errors.append(f"{here}: {ref} -> nothing at {parts.path}")
            elif (
                parts.fragment
                and target in parsed
                and unquote(parts.fragment) not in parsed[target].ids
            ):
                errors.append(
                    f"{here}: {ref} -> {parts.path} "
                    f"has no id {unquote(parts.fragment)!r}"
                )
    if errors:
        raise BuildError("broken internal links:\n  " + "\n  ".join(errors))


def check_redirects(redirects: dict, pages: list[Page]) -> None:
    urls = {page.url for page in pages}
    for old, new in redirects.items():
        if new not in urls:
            raise BuildError(f"_data/redirects.yml: {old} -> {new}, which is no page")
        if old in urls:
            raise BuildError(f"_data/redirects.yml: {old} is a page itself")


STUB = """<!DOCTYPE html>
<html lang="en">
<meta charset="utf-8">
<title>Moved</title>
<meta name="robots" content="noindex">
<link rel="canonical" href="{absolute}">
<script>location.replace({target}+location.hash)</script>
<meta http-equiv="refresh" content="0; url={href}">
<p><a href="{href}">{href}</a></p>
"""


def write_stubs(
    out: Path, redirects: dict, site: dict, sources: dict[str, Path] | None = None
) -> None:
    """GitHub Pages cannot send a 301; until P5 a stub stands in for each one.

    The script keeps the #fragment, which a meta refresh would drop. "/" is a
    stub to the default language on Pages; from P4 on nginx negotiates it.
    An old URL that is not HTML (e.g. /hinschg_reference.md) cannot run a
    script, so it keeps serving what it served: the body of the new page's
    source, front matter stripped. `sources` maps a page URL to that file.
    """
    stubs = {"/": f"/{site['default_language']}/", **redirects}
    written: dict[Path, str] = {}
    for old, new in stubs.items():
        if not old.endswith(("/", ".html")):
            source = (sources or {}).get(new)
            if source is None:
                raise BuildError(f"_data/redirects.yml: {old} -> {new}, a page with no source")
            dest = out / unquote(old).lstrip("/")
            if dest.exists():
                raise BuildError(
                    f"_data/redirects.yml: {old} would overwrite {dest.relative_to(out)}"
                )
            dest.parent.mkdir(parents=True, exist_ok=True)
            text = source.read_text(encoding="utf-8")
            dest.write_text(split_front_matter(source, text)[1], encoding="utf-8")
            continue
        dest = output_file(out, old)
        if written.get(dest) == new:
            continue  # /blog/ and /blog/index.html are one file, so one stub
        if dest.exists():
            raise BuildError(
                f"_data/redirects.yml: the stub for {old} would overwrite {dest.relative_to(out)}"
            )
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(
            STUB.format(
                absolute=html.escape(site["base_url"] + new),
                target=json.dumps(new).replace("</", "<\\/"),
                href=html.escape(new),
            ),
            encoding="utf-8",
        )
        written[dest] = new


def _git(*args: str) -> str:
    # fixed git argv; the path comes from the repository itself
    run = subprocess.run(  # noqa: S603
        ["git", *args],  # noqa: S607
        cwd=ROOT, capture_output=True, text=True, check=True,
    )
    return run.stdout.strip()


def lastmod(path: Path) -> str:
    today = datetime.datetime.now(datetime.UTC).date().isoformat()
    try:
        rel = str(path.resolve().relative_to(ROOT))
    except ValueError:
        return today  # a source tree outside the repository, e.g. a test fixture
    # %ct, not %cs: %cs is the committer's own zone, CI's "today" is UTC
    stamp = _git("log", "-1", "--format=%ct", "--", rel)
    committed = ""
    if stamp:
        committed = datetime.datetime.fromtimestamp(int(stamp), datetime.UTC).date().isoformat()
    return committed if committed and not _git("status", "--porcelain", "--", rel) else today


def write_sitemap(out: Path, src: Path, pages: list[Page], site: dict) -> None:
    entries = []
    for page in sorted(pages, key=lambda p: p.url):
        if page.meta.get("noindex"):
            continue
        generator = page.meta.get("generated")
        source = GENERATORS[generator][1] if generator else src / page.source
        lines = [f"    <loc>{html.escape(site['base_url'] + page.url)}</loc>"]
        lines += [
            f'    <xhtml:link rel="alternate" hreflang="{lang}" href="{html.escape(href)}"/>'
            for lang, href in hreflang(page, site)
        ]
        lines.append(f"    <lastmod>{lastmod(source)}</lastmod>")
        entries.append("  <url>\n" + "\n".join(lines) + "\n  </url>")
    (out / "sitemap.xml").write_text(
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"\n'
        '        xmlns:xhtml="http://www.w3.org/1999/xhtml">\n'
        + "\n".join(entries)
        + "\n</urlset>\n",
        encoding="utf-8",
    )


def _refuse_dangerous_out(src: Path, out: Path) -> None:
    """build() empties `out`; it must never be the sources, above them, or inside them."""
    out, src = out.resolve(), src.resolve()
    if out.is_relative_to(src) or src.is_relative_to(out):  # equal counts as both
        raise BuildError(f"--out {out} would overwrite the sources in {src}")
    if out.is_relative_to(ROOT) or ROOT.is_relative_to(out):
        if not out.is_relative_to(ROOT / "_site"):
            raise BuildError(f"--out {out} is inside the repository; only _site/ may be emptied")
    elif out.is_dir() and any(out.iterdir()) and not (out / "sitemap.xml").is_file():
        raise BuildError(f"--out {out} is not empty and not a previous build (no sitemap.xml)")


def build(src: Path, out: Path, *, redirect_stubs: bool = False) -> list[Page]:
    _refuse_dangerous_out(src, out)
    data = load_data(src)
    site = data["site"]
    pages = load_pages(src, site)
    check_nav(data["nav"], pages, site)
    check_redirects(data["redirects"], pages)

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
    by_key: dict[str, dict[str, Page]] = {}
    for page in pages:
        by_key.setdefault(str(page.meta["translation_key"]), {})[page.lang] = page
    for page in pages:
        dest = output_file(out, page.url)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_text(render_page(env, page, data, by_key), encoding="utf-8")
    write_sitemap(out, src, pages, site)
    # Before the stubs: a link to an old URL must fail even where a stub would catch it.
    check_links(out, urlsplit(site["base_url"]).netloc)
    if redirect_stubs:
        write_stubs(out, data["redirects"], site, {p.url: src / p.source for p in pages})
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
