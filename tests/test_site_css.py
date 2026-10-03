"""The site's stylesheets: which exist, who owns the tokens, and what every page links."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.built_site import built, page, pages, stylesheets
from tests.diagram_tools import renderer

ROOT = Path(__file__).resolve().parents[1]
CSS = ROOT / "docs" / "assets" / "css"
ALWAYS = ["tokens.css", "fonts.css", "base.css"]
_DEFINITION = re.compile(r"(?<![\w-])(--[\w-]+)\s*:")


def _sheets(html: str) -> list[str]:
    return [p.name for p in stylesheets(html)]


def test_every_page_links_tokens_fonts_and_base_first() -> None:
    for path in pages():
        html = path.read_text(encoding="utf-8")
        assert _sheets(html)[:3] == ALWAYS, path.relative_to(built())


def test_only_tokens_css_defines_custom_properties() -> None:
    offenders = {
        sheet.name: sorted(set(_DEFINITION.findall(sheet.read_text(encoding="utf-8"))))
        for sheet in CSS.glob("*.css")
        if sheet.name != "tokens.css" and _DEFINITION.search(sheet.read_text(encoding="utf-8"))
    }
    assert not offenders, f"custom properties outside tokens.css: {offenders}"


def test_tokens_css_has_a_light_and_a_dark_block_with_the_same_colour_names() -> None:
    text = (CSS / "tokens.css").read_text(encoding="utf-8")
    light = re.search(r":root\s*\{([^}]*)\}", text)
    dark = re.search(r'\[data-theme="dark"\]\s*\{([^}]*)\}', text)
    assert light and dark
    dark_names = set(_DEFINITION.findall(dark.group(1)))
    colour_names = {
        n
        for n, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", light.group(1))
        if re.match(r"#|rgba?\(|color-mix", v.strip())
    }
    assert colour_names == dark_names, colour_names ^ dark_names


def test_tokens_css_names_the_three_font_families() -> None:
    light = re.search(r":root\s*\{([^}]*)\}", (CSS / "tokens.css").read_text(encoding="utf-8"))
    assert light
    fonts = dict(re.findall(r"(--font-[\w-]+)\s*:\s*([^;]+);", light.group(1)))
    assert fonts == {
        "--font-display": "'Sora', system-ui, sans-serif",
        "--font-body": "'Sora', system-ui, sans-serif",
        "--font-mono": "'JetBrains Mono', ui-monospace, monospace",
    }


def test_no_stylesheet_uses_an_undefined_token() -> None:
    defined = set(_DEFINITION.findall((CSS / "tokens.css").read_text(encoding="utf-8")))
    used = {
        (sheet.name, name)
        for sheet in CSS.glob("*.css")
        for name in re.findall(r"var\((--[\w-]+)", sheet.read_text(encoding="utf-8"))
    }
    missing = sorted((s, n) for s, n in used if n not in defined)
    assert not missing, missing


def test_the_retired_token_names_are_gone() -> None:
    retired = (
        "--bg-base", "--bg-surface", "--bg-raised", "--bg-overlay", "--nav-bg", "--footer-bg",
        "--text-primary", "--text-secondary", "--text-muted", "--border-subtle", "--border-default",
        "--border-strong", "--code-bg", "--code-text", "--sidebar-bg", "--red-alert",
    )  # fmt: skip
    for sheet in CSS.glob("*.css"):
        text = sheet.read_text(encoding="utf-8")
        found = [n for n in retired if re.search(re.escape(n) + r"(?![\w-])", text)]
        assert not found, (sheet.name, found)


def test_the_landing_pages_and_posts_share_one_token_sheet() -> None:
    for url in ("/en/", "/de/", "/en/docs/", "/en/changelog/"):
        assert "tokens.css" in _sheets(page(url)), url


PAGE_TYPES = {"home.css", "docs.css", "post.css", "page.css"}


def test_the_site_has_exactly_the_planned_sheets() -> None:
    assert {p.name for p in CSS.glob("*.css")} == set(ALWAYS) | PAGE_TYPES


def test_every_page_links_exactly_one_page_type_sheet() -> None:
    for path in pages():
        sheets = _sheets(path.read_text(encoding="utf-8"))
        assert len(sheets) == 4 and sheets[3] in PAGE_TYPES, (path.relative_to(built()), sheets)


APP_CSS = ROOT / "app" / "static" / "css" / "site.css"


def _scheme_rules(text: str) -> dict[str, str]:
    out = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        if m := re.search(r"color-scheme\s*:\s*([^;]+);", body):
            out[" ".join(selector.split())] = m.group(1).strip()
    return out


def test_each_theme_declares_its_own_color_scheme_in_site_and_app() -> None:
    """Chrome's Auto Dark Mode recolours a page that does not declare dark support; `light` alone
    does not opt out, `only light` does (https://developer.chrome.com/blog/auto-dark-theme)."""
    want = {'[data-theme="light"]': "only light", '[data-theme="dark"]': "dark"}
    for sheet in (CSS / "base.css", APP_CSS):
        assert _scheme_rules(sheet.read_text(encoding="utf-8")) == want, sheet


def test_no_template_declares_a_color_scheme() -> None:
    """Only the two theme rules may; an inline `<style>` or include would override them."""
    decl = re.compile(r"(?<![\w-])color-scheme\s*:")
    files = [
        f
        for d in ("app/templates", "docs/_includes", "docs/_layouts")
        for f in (ROOT / d).rglob("*")
        if f.is_file()
    ]
    assert files
    assert [str(f) for f in files if decl.search(f.read_text(encoding="utf-8"))] == []


def _rules(text: str, media: str = "") -> dict[tuple[str, str], list[str]]:
    """(media, selector) -> sorted declarations, for flat sheets with @media one level deep."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    out: dict[tuple[str, str], list[str]] = {}
    i = 0
    while (brace := text.find("{", i)) != -1:
        head = " ".join(text[i:brace].split())
        depth, end = 1, brace + 1
        while depth:
            depth += {"{": 1, "}": -1}.get(text[end], 0)
            end += 1
        body = text[brace + 1 : end - 1]
        if head.startswith("@media"):
            out.update(_rules(body, head))
        elif not head.startswith("@"):
            decls = sorted(" ".join(d.split()) for d in body.split(";") if d.strip())
            out[(media, head)] = decls
        i = end
    return out


# Selectors docs.css and page.css may style differently, each with its reason. Expected empty.
DOCS_PAGE_DIFFERENCES: set[tuple[str, str]] = set()


def test_docs_and_page_style_their_shared_selectors_alike() -> None:
    docs = _rules((CSS / "docs.css").read_text(encoding="utf-8"))
    page_ = _rules((CSS / "page.css").read_text(encoding="utf-8"))
    shared = docs.keys() & page_.keys()
    assert len(shared) > 30, sorted(shared)  # the docs layout both page types use
    drifted = sorted(k for k in shared - DOCS_PAGE_DIFFERENCES if docs[k] != page_[k])
    assert not drifted, drifted


# The same selector, styled differently in two page-type sheets, on purpose. Each entry names why.
PAGE_TYPE_DIFFERENCES = {
    # Home figures sit in grid rows that space them; docs figures sit in running text.
    ("home.css", "docs.css", ("", ".diagram, .doc-shot")),
    # docs.css: a safety net for any bare <pre>; post.css: the posts' code block itself.
    ("docs.css", "post.css", ("", "pre")),
    # One class name, two components: the blog index card (page.css), the post header (post.css).
    ("post.css", "page.css", ("", ".article-meta")),
    ("post.css", "page.css", ("", ".article-tag")),
    ("post.css", "page.css", ("", ".article-title")),
}


def test_no_selector_drifts_between_two_page_type_sheets() -> None:
    names = ["home.css", "docs.css", "post.css", "page.css"]
    sheets = {n: _rules((CSS / n).read_text(encoding="utf-8")) for n in names}
    drifted = sorted(
        (a, b, key)
        for i, a in enumerate(names)
        for b in names[i + 1 :]
        for key in sheets[a].keys() & sheets[b].keys()
        if sheets[a][key] != sheets[b][key] and (a, b, key) not in PAGE_TYPE_DIFFERENCES
    )
    assert not drifted, drifted
    stale = [
        (a, b, k)
        for a, b, k in PAGE_TYPE_DIFFERENCES
        if k not in sheets[a].keys() & sheets[b].keys()
    ]
    assert not stale, stale


_HEX = re.compile(r"#[0-9a-fA-F]{3,8}\b")
_COLOUR_FN = re.compile(r"(?<![\w-])(?:rgba?|hsla?|hwb|lab|lch|oklab|oklch|color)\(", re.I)
_WORD = re.compile(r"(?<![\w-])[a-zA-Z]+(?![\w-])")
# CSS Color 4 named colours. transparent and currentColor are not a colour of their own.
NAMED_COLOURS = frozenset(
    """aliceblue antiquewhite aqua aquamarine azure beige bisque black blanchedalmond blue
    blueviolet brown burlywood cadetblue chartreuse chocolate coral cornflowerblue cornsilk crimson
    cyan darkblue darkcyan darkgoldenrod darkgray darkgreen darkgrey darkkhaki darkmagenta
    darkolivegreen darkorange darkorchid darkred darksalmon darkseagreen darkslateblue darkslategray
    darkslategrey darkturquoise darkviolet deeppink deepskyblue dimgray dimgrey dodgerblue firebrick
    floralwhite forestgreen fuchsia gainsboro ghostwhite gold goldenrod gray green greenyellow grey
    honeydew hotpink indianred indigo ivory khaki lavender lavenderblush lawngreen lemonchiffon
    lightblue lightcoral lightcyan lightgoldenrodyellow lightgray lightgreen lightgrey lightpink
    lightsalmon lightseagreen lightskyblue lightslategray lightslategrey lightsteelblue lightyellow
    lime limegreen linen magenta maroon mediumaquamarine mediumblue mediumorchid mediumpurple
    mediumseagreen mediumslateblue mediumspringgreen mediumturquoise mediumvioletred midnightblue
    mintcream mistyrose moccasin navajowhite navy oldlace olive olivedrab orange orangered orchid
    palegoldenrod palegreen paleturquoise palevioletred papayawhip peachpuff peru pink plum
    powderblue purple rebeccapurple red rosybrown royalblue saddlebrown salmon sandybrown seagreen
    seashell sienna silver skyblue slateblue slategray slategrey snow springgreen steelblue tan teal
    thistle tomato turquoise violet wheat white whitesmoke yellow yellowgreen""".split()
)
# Illustrations of other software's chrome, not brand colour: the macOS window buttons
# of the home page's terminal mockup. Allowed in home.css only.
FOREIGN_COLOURS = {"#ff5f57", "#febc2e", "#28c840"}


def colour_literals(value: str) -> set[str]:
    """Every colour a CSS value writes itself: hex, a colour function, a named colour."""
    found = {c.lower() for c in _HEX.findall(value)}
    found |= {m.group(0).lower() for m in _COLOUR_FN.finditer(value)}
    return found | ({w.lower() for w in _WORD.findall(value)} & NAMED_COLOURS)


@pytest.mark.parametrize(
    "value",
    ["#fff", "rgb(0 0 0)", "hsl(0 0% 100%)", "oklch(70% 0.1 160)", "lab(50 0 0)", "white",
     "color-mix(in srgb, var(--accent) 50%, white)", "1px solid Black", "color(srgb 1 1 1)"],
)  # fmt: skip
def test_the_colour_scan_sees_every_kind_of_literal(value: str) -> None:
    assert colour_literals(value), value


@pytest.mark.parametrize(
    "value",
    ["var(--accent)", "transparent", "currentColor", "nowrap", "1px solid var(--hairline)",
     "color-mix(in srgb, var(--accent) 8%, transparent)", "'Sora', system-ui, sans-serif"],
)  # fmt: skip
def test_the_colour_scan_passes_tokens_and_keywords(value: str) -> None:
    assert not colour_literals(value), value


def _declarations(css: str) -> list[tuple[str, str]]:
    return re.findall(r"([\w-]+)\s*:\s*([^;{}]+)[;}]", re.sub(r"/\*.*?\*/", "", css, flags=re.S))


def _block(text: str, opener: str) -> dict[str, str]:
    """Custom properties of every rule whose whole selector is `opener`; later rules win."""
    rule = r"(?:\A|(?<=\}))(?:\s|/\*.*?\*/)*" + re.escape(opener) + r"\s*\{([^}]*)\}"
    bodies = re.findall(rule, text, flags=re.S)
    assert bodies, opener
    return {
        k: v.strip() for body in bodies for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)
    }


def test_every_colour_value_in_tokens_css_is_a_design_md_colour() -> None:
    """A token named after a DESIGN.md key carries that key's value; any other colour literal is a
    DESIGN.md colour, and everything else is derived from a token (color-mix)."""
    palette = renderer().palette()
    text = (CSS / "tokens.css").read_text(encoding="utf-8")
    for theme, opener in (("light", ":root"), ("dark", '[data-theme="dark"]')):
        for name, value in _block(text, opener).items():
            if (key := name[2:]) in palette[theme]:
                assert value.lower() == palette[theme][key], (theme, name, value)
                continue
            for literal in colour_literals(value):
                assert literal in set(palette[theme].values()), (
                    theme,
                    name,
                    literal,
                    "derive with color-mix(in srgb, var(--x) N%, transparent)",
                )


def test_no_page_sheet_writes_a_colour_literal() -> None:
    for sheet in CSS.glob("*.css"):
        if sheet.name == "tokens.css":
            continue
        values = (v for _, v in _declarations(sheet.read_text(encoding="utf-8")))
        stray = set().union(*map(colour_literals, values))
        if sheet.name == "home.css":
            stray -= FOREIGN_COLOURS
        assert not stray, (sheet.name, sorted(stray))


# App token -> DESIGN.md key. Brand-derived tokens (--brand-primary, --accent, --accent-subtle,
# --cta-bg, --cta-bg-hover) are excluded: an operator re-brands them through brand.primary_color.
APP_TOKENS = {
    "--canvas": "canvas",
    "--surface-card": "surface",
    "--bg-code": "surface",
    "--surface-dark": "inverse",
    "--ink": "ink",
    "--body-text": "body",
    "--muted": "muted",
    "--hairline": "hairline",
    "--border-strong": "hairline-strong",
    "--danger": "danger",
    "--danger-subtle": "danger-weak",
    "--danger-hover": "danger-strong",
    "--warning": "warning",
    "--warning-subtle": "warning-weak",
    "--success": "success",
    "--success-subtle": "success-weak",
    "--info": "info",
    "--info-subtle": "info-weak",
    "--on-dark": "inverse-ink",
    "--muted-on-dark": "inverse-muted",
    "--cta-text": "accent-ink",
}


def _hex6(value: str) -> str:
    v = value.strip().lower()
    return "#" + "".join(c * 2 for c in v[1:]) if re.fullmatch(r"#[0-9a-f]{3}", v) else v


def test_the_app_tokens_are_design_md_values() -> None:
    palette = renderer().palette()
    text = APP_CSS.read_text(encoding="utf-8")
    light = _block(text, ':root,\n[data-theme="light"]')
    dark = _block(text, '[data-theme="dark"]')
    for token, key in APP_TOKENS.items():
        assert _hex6(light[token]) == palette["light"][key], (token, "light", light[token])
        assert _hex6(dark.get(token, light[token])) == palette["dark"][key], (token, "dark")


_PAINT = re.compile(
    r"""(?<![\w-])(?:fill|stroke|stop-color|color|style)\s*=\s*(["'])(.*?)\1""", re.S
)


def test_no_page_paints_with_a_colour_literal() -> None:
    """Inline SVG takes currentColor and a sheet colours it: a literal skips the theme."""
    offenders = {}
    for path in pages():
        text = path.read_text(encoding="utf-8")
        found = set().union(*(colour_literals(v) for _, v in _PAINT.findall(text)))
        if found:
            offenders[str(path.relative_to(built()))] = sorted(found)
    assert not offenders, offenders


# Brand-derived app tokens -> the DESIGN.md key the default brand must produce.
BRAND_TOKENS = {
    "--accent": "accent",
    "--accent-subtle": "accent-weak",
    "--cta-bg": "accent",
    "--cta-bg-hover": "accent-strong",
}


def _head_vars(primary_color: str) -> dict[str, str]:
    """The custom properties base.html's nonce'd style block sets for this brand colour."""
    from types import SimpleNamespace

    from app.templating import templates

    source = (ROOT / "app" / "templates" / "base.html").read_text(encoding="utf-8")
    style = re.search(r"<style nonce=.*?</style>", source, flags=re.S)
    assert style
    html = templates.env.from_string(style.group(0)).render(
        request=SimpleNamespace(state=SimpleNamespace(csp_nonce="n")),
        brand={**templates.env.globals["brand"], "primary_color": primary_color},
    )
    return dict(re.findall(r"(--brand-[\w-]+)\s*:\s*([^;]+);", html))


def _resolve(value: str, scope: dict[str, str]) -> str:
    """var(--x, fallback) as the browser resolves it against these custom properties."""
    m = re.fullmatch(r"var\((--[\w-]+)(?:,(.*))?\)", value.strip(), flags=re.S)
    if not m:
        return value.strip()
    name, fallback = m.groups()
    if name in scope:
        return _resolve(scope[name], scope)
    return _resolve(fallback, scope) if fallback is not None else ""


def _app_scopes(primary_color: str) -> dict[str, dict[str, str]]:
    text = APP_CSS.read_text(encoding="utf-8")
    light = {**_block(text, ':root,\n[data-theme="light"]'), **_head_vars(primary_color)}
    return {"light": light, "dark": {**light, **_block(text, '[data-theme="dark"]')}}


def test_the_default_brand_draws_the_design_md_accent_in_both_themes() -> None:
    palette = renderer().palette()
    for theme, scope in _app_scopes("#0c7253").items():
        for token, key in BRAND_TOKENS.items():
            assert _hex6(_resolve(scope[token], scope)) == palette[theme][key], (theme, token)


def test_a_custom_brand_keeps_its_derived_accent() -> None:
    assert set(_head_vars("#7b2cbf")) == {"--brand-primary"}
    dark = _app_scopes("#7b2cbf")["dark"]
    assert _resolve(dark["--accent"], dark).startswith("color-mix(in srgb,var(--brand-primary)")


def test_headings_balance_their_lines() -> None:
    text = (CSS / "base.css").read_text(encoding="utf-8")
    assert re.search(r"h1,\s*h2,\s*h3[^{]*\{[^}]*text-wrap:\s*balance", text)


def test_nothing_transitions_all() -> None:
    for sheet in [*CSS.glob("*.css"), APP_CSS]:
        css = sheet.read_text(encoding="utf-8")
        assert not re.search(r"transition(-property)?\s*:\s*all\b", css), sheet.name


def _rule_selectors(text: str) -> list[tuple[set[str], str]]:
    """Every top-level rule as (its comma-separated selectors, its body)."""
    return [
        ({s.strip() for s in head.split(",")}, body)
        for head, body in re.findall(r"(?:\A|(?<=\}))\s*([^{}@]+?)\s*\{([^{}]*)\}", text)
    ]


def _app_rule(selector: str) -> str:
    rules = _rule_selectors(APP_CSS.read_text(encoding="utf-8"))
    return "\n".join(body for sels, body in rules if selector in sels)


def test_figures_are_tabular() -> None:
    base = (CSS / "base.css").read_text(encoding="utf-8")
    assert re.search(r"table[^{]*\{[^}]*tabular-nums", base)
    for selector in (
        "table",
        "code",
        ".mono",
        ".token",
        ".credential-display",
        ".stat-card__number",
        ".stat-card__value",
        ".guarantee-num",
        ".session-expiry-countdown",
    ):
        assert "tabular-nums" in _app_rule(selector), selector


def _stripped(path: Path) -> str:
    """The sheet without its forced-colours block, which draws real borders on purpose."""
    return re.sub(
        r"@media \(forced-colors: active\) \{.*?\n\}", "", path.read_text("utf-8"), flags=re.S
    )


def test_no_site_component_draws_a_decorative_border() -> None:
    """DESIGN.md "Rules": a decorative edge is a box-shadow ring; only structural borders
    (row separators, accent bars: border-top/bottom/left) stay."""
    for sheet in CSS.glob("*.css"):
        assert not re.search(r"(?<![-\w])border:\s*[\d.]+px solid", _stripped(sheet)), sheet.name


APP_RING_COMPONENTS = (
    ".btn",
    ".btn-secondary",
    ".panel-outline",
    '[data-theme="dark"] .panel',
    ".badge-received",
    ".mode-card",
    ".credential-display",
    ".credential-box",
    ".attachment-item",
    ".qr-wrapper",
    ".totp-secret-card",
    ".demo-credentials",
    ".session-expiry-banner",
    ".theme-toggle",
    ".lang-picker-btn",
    ".lang-picker-menu",
)


def test_no_app_component_draws_a_decorative_border() -> None:
    rules = _rule_selectors(_stripped(APP_CSS))
    for selector in APP_RING_COMPONENTS:
        for sels, body in rules:
            if selector in sels:
                assert not re.search(r"border(-width)?:\s*[\d.]+px( solid)?\b", body), selector
                assert not re.search(r"(?<![-\w])border-color:\s*(?!transparent)", body), selector


def _length(value: str) -> float:
    m = re.fullmatch(r"([\d.]+)(px|rem)", value.strip())
    assert m, value
    return float(m.group(1)) * (16 if m.group(2) == "rem" else 1)


# (parent selector, its padding, child selector): inner radius = outer radius - padding.
# The site's pairs are checked in a browser (tests/e2e/test_site_look.py).
APP_NESTED = ((".lang-picker-menu", "0.25rem", ".lang-picker-option"),)


def test_nested_app_radii_are_concentric() -> None:
    for parent, padding, child in APP_NESTED:
        outer = _length(re.search(r"border-radius:\s*([^;]+);", _app_rule(parent)).group(1))  # type: ignore[union-attr]
        inner = _length(re.search(r"border-radius:\s*([^;]+);", _app_rule(child)).group(1))  # type: ignore[union-attr]
        assert inner <= max(0.0, outer - _length(padding)), (parent, child, inner, outer)
