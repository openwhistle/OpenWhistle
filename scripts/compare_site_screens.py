"""Prove a CSS change changes no pixel, or show exactly which pages it changes.

    uv run python scripts/compare_site_screens.py [BASE_REF] [--out DIR] [--only URL ...]

Builds the site of BASE_REF (default: main) in a temporary git worktree and the site of
the working tree, serves both on localhost, screenshots every page in both themes at 1920
and 390 px (full page, animations off, lazy images loaded), and compares pixel by pixel.
Exit 1 lists every differing shot with a diff image. Used by the P2b CSS work: a pure
refactor must exit 0; a visible change is reviewed shot by shot.
"""

from __future__ import annotations

import argparse
import functools
import http.server
import subprocess
import sys
import tempfile
import threading
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from PIL import Image, ImageChops
from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parents[1]
Image.MAX_IMAGE_PIXELS = None  # our own full-page screenshots, not untrusted input
SHOTS: tuple[tuple[str, int], ...] = (
    ("light", 1920),
    ("dark", 1920),
    ("light", 390),
    ("dark", 390),
)


def page_urls(site: Path) -> list[str]:
    urls = []
    for html in site.rglob("*.html"):
        rel = html.relative_to(site).as_posix()
        if rel.startswith("assets/"):
            continue
        urls.append(
            "/" + rel.removesuffix("index.html") if rel.endswith("index.html") else "/" + rel
        )
    return sorted(urls)


def same_image(a: Path, b: Path, diff: Path) -> int:
    """Changed pixels between two screenshots; a size change counts every extra pixel."""
    with Image.open(a) as fa, Image.open(b) as fb:
        ia, ib = fa.convert("RGB"), fb.convert("RGB")
    resized = ia.size != ib.size
    if resized:
        canvas = (max(ia.width, ib.width), max(ia.height, ib.height))
        pa, pb = Image.new("RGB", canvas), Image.new("RGB", canvas)
        pa.paste(ia)
        pb.paste(ib)
        ia, ib = pa, pb
    delta = ImageChops.difference(ia, ib).convert("L").point(lambda v: 255 if v else 0)
    changed = delta.histogram()[255]
    if changed == 0 and not resized:
        return 0
    delta.save(diff)
    return max(changed, 1)


def _build(src_root: Path, out: Path) -> None:
    subprocess.run(  # noqa: S603 - our own build script
        [
            sys.executable,
            str(src_root / "scripts" / "build_site.py"),
            "--src",
            str(src_root / "docs"),
            "--out",
            str(out),
        ],
        check=True,
        cwd=src_root,
    )


class _Quiet(http.server.SimpleHTTPRequestHandler):
    def log_message(self, format: str, *args: object) -> None:
        """No access log: it would bury the list of differing shots."""


@contextmanager
def _serve(site: Path) -> Iterator[str]:
    handler = functools.partial(_Quiet, directory=str(site))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_address[1]}"
    finally:
        server.shutdown()


def _shoot(page: Page, url: str, path: Path) -> None:
    page.goto(url, wait_until="load")
    page.evaluate(
        """async () => {
            document.querySelectorAll('img[loading=lazy]').forEach(i => { i.loading = 'eager'; });
            await Promise.all([...document.images].map(i => i.complete ? null
                : new Promise(r => { i.onload = i.onerror = r; })));
            await document.fonts.ready;
        }"""
    )
    page.screenshot(path=str(path), full_page=True, animations="disabled", caret="hide")


def _screens(base_url: str, urls: list[str], out: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme, width in SHOTS:
            ctx = browser.new_context(viewport={"width": width, "height": 1000}, color_scheme=theme)  # type: ignore[arg-type]
            ctx.add_init_script(f"try{{localStorage.setItem('ow-theme','{theme}')}}catch(e){{}}")
            page = ctx.new_page()
            for url in urls:
                _shoot(page, base_url + url, out / f"{_name(url)}-{theme}-{width}.png")
            ctx.close()
        browser.close()


def _name(url: str) -> str:
    return url.strip("/").replace("/", "_").removesuffix(".html") or "root"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("base", nargs="?", default="main")
    parser.add_argument("--out", type=Path)
    parser.add_argument("--only", nargs="*", default=[])
    args = parser.parse_args(argv)
    out = args.out or Path(tempfile.mkdtemp(prefix="ow-screens-"))
    with tempfile.TemporaryDirectory(prefix="ow-compare-") as tmp:
        tmp_path = Path(tmp)
        worktree = tmp_path / "base-src"
        subprocess.run(  # noqa: S603
            ["git", "worktree", "add", "--detach", str(worktree), args.base],  # noqa: S607
            check=True,
            cwd=ROOT,
        )
        try:
            _build(worktree, tmp_path / "base")
            _build(ROOT, tmp_path / "head")
        finally:
            subprocess.run(  # noqa: S603
                ["git", "worktree", "remove", "--force", str(worktree)],  # noqa: S607
                check=True,
                cwd=ROOT,
            )
        urls = sorted(set(page_urls(tmp_path / "base")) | set(page_urls(tmp_path / "head")))
        if args.only:
            urls = [u for u in urls if u in args.only]
        for side in ("base", "head"):
            (out / side).mkdir(parents=True, exist_ok=True)
            with _serve(tmp_path / side) as base_url:
                _screens(base_url, urls, out / side)
    changed = 0
    for shot in sorted((out / "head").glob("*.png")):
        before = out / "base" / shot.name
        if not before.exists():
            print(f"{shot.name}: new page")
            changed += 1
            continue
        diff = out / f"diff-{shot.name}"
        if (px := same_image(before, shot, diff)) > 0:
            print(f"{shot.name}: {px} px changed -> {diff}")
            changed += 1
    print(f"{changed} differing shot(s); screenshots in {out}")
    return 1 if changed else 0


if __name__ == "__main__":
    raise SystemExit(main())
