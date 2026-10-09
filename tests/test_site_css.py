"""The app's stylesheet keeps DESIGN.md's tokens, rings and transitions.

The website's sheets are checked in openwhistle/website.
"""

from __future__ import annotations

import re
from pathlib import Path

from tests.diagram_tools import renderer

ROOT = Path(__file__).resolve().parents[1]


APP_CSS = ROOT / "app" / "static" / "css" / "site.css"


def _scheme_rules(text: str) -> dict[str, str]:
    out = {}
    for selector, body in re.findall(r"([^{}]+)\{([^{}]*)\}", text):
        if m := re.search(r"color-scheme\s*:\s*([^;]+);", body):
            out[" ".join(selector.split())] = m.group(1).strip()
    return out


def test_each_theme_declares_its_own_color_scheme() -> None:
    """Chrome's Auto Dark Mode recolours a page that does not declare dark support; `light` alone
    does not opt out, `only light` does (https://developer.chrome.com/blog/auto-dark-theme)."""
    want = {'[data-theme="light"]': "only light", '[data-theme="dark"]': "dark"}
    assert _scheme_rules(APP_CSS.read_text(encoding="utf-8")) == want


def test_no_template_declares_a_color_scheme() -> None:
    """Only the two theme rules may; an inline `<style>` or include would override them."""
    decl = re.compile(r"(?<![\w-])color-scheme\s*:")
    files = [f for f in (ROOT / "app/templates").rglob("*") if f.is_file()]
    assert files
    assert [str(f) for f in files if decl.search(f.read_text(encoding="utf-8"))] == []


def _block(text: str, opener: str) -> dict[str, str]:
    """Custom properties of every rule whose whole selector is `opener`; later rules win."""
    rule = r"(?:\A|(?<=\}))(?:\s|/\*.*?\*/)*" + re.escape(opener) + r"\s*\{([^}]*)\}"
    bodies = re.findall(rule, text, flags=re.S)
    assert bodies, opener
    return {
        k: v.strip() for body in bodies for k, v in re.findall(r"(--[\w-]+)\s*:\s*([^;]+);", body)
    }


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


def test_nothing_transitions_all() -> None:
    css = APP_CSS.read_text(encoding="utf-8")
    assert not re.search(r"transition(-property)?\s*:\s*all\b", css)


# A rule's selector starts after the previous rule's `}` or after an `@media {`.
RULE = r"(?:\A|(?<=[{}]))\s*([^{}@]+?)\s*\{([^{}]*)\}"
# A 1px ring anywhere in a box-shadow list, inset or not.
RING = r"box-shadow:[^;]*?(?<![\w.-])0 0 0 1px"


def _rule_selectors(text: str) -> list[tuple[set[str], str]]:
    """Every top-level rule as (its comma-separated selectors, its body)."""
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)
    return [({s.strip() for s in head.split(",")}, body) for head, body in re.findall(RULE, text)]


def _app_rule(selector: str) -> str:
    rules = _rule_selectors(APP_CSS.read_text(encoding="utf-8"))
    return "\n".join(body for sels, body in rules if selector in sels)


def _stripped(path: Path) -> str:
    """The sheet without its forced-colours block, which draws real borders on purpose."""
    return re.sub(
        r"@media \(forced-colors: active\) \{.*?\n\}", "", path.read_text("utf-8"), flags=re.S
    )


def test_figures_are_tabular() -> None:
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
    ".pagination-page",
    ".pagination-page-current",
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


# (parent selector, child selector): inner radius = outer radius - the parent's padding.
APP_NESTED = ((".lang-picker-menu", ".lang-picker-option"),)


def test_nested_app_radii_are_concentric() -> None:
    for parent, child in APP_NESTED:
        rule = _app_rule(parent)
        outer = _length(_declared(rule, "border-radius"))
        pads = [
            _length(v)
            for k, v in re.findall(r"(padding(?:-[a-z]+)?):\s*([^;]+);", rule)
            if k in ("padding-top", "padding-bottom", "padding-left", "padding-right", "padding")
            for v in v.split()[:1]
        ]
        inner = _length(_declared(_app_rule(child), "border-radius"))
        assert pads and inner <= max(0.0, outer - min(pads)), (parent, child, inner, outer, pads)


def _declared(rule: str, prop: str) -> str:
    found = re.search(rf"(?<![-\w]){prop}:\s*([^;]+);", rule)
    assert found, prop
    return found.group(1)


# Elements that carry a ring AND another shadow (an accent bar, an elevation): the more specific
# ring rule would replace the other shadow, so the rule composes both.
COMPOSED_SHADOWS = (
    (
        '[data-theme="dark"] .panel-primary',
        ("inset 0 3px 0 var(--ink)", "0 0 0 1px var(--hairline)"),
    ),
    (".session-expiry-banner", ("0 0 0 1px var(--warning)", "0 6px 24px")),
    (
        ".session-expiry-banner.session-expiry-expired-state",
        ("0 0 0 1px var(--danger)", "0 6px 24px"),
    ),
    (".lang-picker-menu", ("0 0 0 1px var(--hairline)", "0 4px 16px")),
)


def test_a_ring_never_replaces_another_shadow() -> None:
    for selector, parts in COMPOSED_SHADOWS:
        shadow = _declared(_app_rule(selector), "box-shadow")
        for part in parts:
            assert part in shadow, (selector, part, shadow)


def _forced_colours(path: Path) -> str:
    return "\n".join(
        re.findall(r"@media \(forced-colors: active\) \{(.*?)\n\}", path.read_text("utf-8"), re.S)
    )


def _listed(block: str, selector: str) -> bool:
    plain = selector.removeprefix('[data-theme="dark"] ')
    return plain in {s.strip() for s in re.split(r"[,{}]", block)}


def test_every_ringed_app_component_has_a_forced_colours_border() -> None:
    block = _forced_colours(APP_CSS)
    ringed = {
        s
        for sels, body in _rule_selectors(_stripped(APP_CSS))
        if re.search(RING, body)
        for s in sels
        if ":" not in s.removeprefix('[data-theme="dark"] ')
    }
    missing = {s for s in ringed | set(APP_RING_COMPONENTS) if not _listed(block, s)}
    assert not missing, sorted(missing)


def test_a_hover_that_changes_the_ring_transitions_it() -> None:
    """A transition list without box-shadow makes the ring snap while the fill fades."""
    rules = _rule_selectors(_stripped(APP_CSS))
    for sels, body in rules:
        for hover in (s for s in sels if s.endswith(":hover") and "box-shadow" in body):
            base = hover.removesuffix(":hover")
            lists = [
                m.group(1)
                for bsels, bbody in rules
                if base in bsels
                for m in [re.search(r"transition(?:-property)?:\s*([^;]+);", bbody)]
                if m
            ]
            assert all("box-shadow" in x for x in lists), (base, lists)


def test_the_language_menu_sizes_to_its_longest_name() -> None:
    assert "width: max-content" in _app_rule(".lang-picker-menu")
    assert "white-space: nowrap" in _app_rule(".lang-picker-option")


def test_a_transition_property_list_names_each_property_once() -> None:
    for names in re.findall(r"transition-property:\s*([^;]+);", APP_CSS.read_text("utf-8")):
        parts = [n.strip() for n in names.split(",")]
        assert len(parts) == len(set(parts)), names
