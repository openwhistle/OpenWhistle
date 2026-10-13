"""Layout rules that only a real browser can measure."""

from __future__ import annotations

import pytest
from playwright.sync_api import Browser

from tests.e2e.conftest import (
    DEMO_ADMIN_PASSWORD,
    DEMO_ADMIN_TOTP_SECRET,
    DEMO_ADMIN_USERNAME,
    DEMO_CASE_PENDING,
    _admin_login,
)

pytestmark = pytest.mark.e2e


def _page(browser: Browser, base_url: str, width: int):  # type: ignore[no-untyped-def]
    ctx = browser.new_context(viewport={"width": width, "height": 900}, base_url=base_url)
    return ctx, ctx.new_page()


def test_admin_nav_links_never_wrap_on_desktop(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 1440)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    heights = page.eval_on_selector_all(
        ".admin-nav a", "els => els.map(e => e.getBoundingClientRect().height)"
    )
    assert heights and max(heights) < 48, heights
    assert page.locator(".nav").bounding_box()["height"] <= 72  # type: ignore[index]
    ctx.close()


def test_admin_menu_is_closed_on_a_phone(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 390)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    assert page.eval_on_selector("#admin-menu", "d => d.open") is False
    assert page.locator(".nav").bounding_box()["height"] <= 72  # type: ignore[index]
    page.click(".admin-menu-toggle")
    assert page.locator(".admin-nav a[href='/admin/dashboard']").is_visible()
    ctx.close()


def test_demo_banner_is_one_line_on_a_phone(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 390)
    page.goto("/submit")
    assert page.locator(".demo-banner").bounding_box()["height"] <= 56  # type: ignore[index]
    theme = page.locator("#theme-toggle").bounding_box()
    brand = page.locator(".nav-brand").bounding_box()
    assert theme and brand and abs(theme["y"] - brand["y"]) < 24  # same row as the brand
    ctx.close()


def test_the_footer_is_one_row_lower_than_the_nav(browser: Browser, base_url: str) -> None:
    """It was 87 px under a 60 px nav, with a tagline, five links and the version."""
    ctx, page = _page(browser, base_url, 1440)
    page.goto("/submit")
    nav, footer = page.evaluate(
        "['.nav', 'footer'].map(s => document.querySelector(s).getBoundingClientRect().height)"
    )
    tops = page.eval_on_selector_all(
        ".footer-links li, .footer-powered",
        "els => els.map(e => Math.round(e.getBoundingClientRect().top))",
    )
    ctx.close()
    assert footer < nav, (footer, nav)
    assert tops and max(tops) - min(tops) <= 2, tops


def test_report_form_is_on_the_first_phone_screen(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 390)
    page.goto("/submit")
    top = page.locator("form[action='/submit']").bounding_box()
    assert top and top["y"] < 600, top
    ctx.close()


def test_case_number_stays_on_one_line(browser: Browser, base_url: str) -> None:
    from tests.e2e.conftest import DEMO_CASE_PENDING

    ctx, page = _page(browser, base_url, 390)
    page.goto("/status")
    page.fill('input[name="case_number"]', DEMO_CASE_PENDING["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_PENDING["pin"])
    page.click("button.btn-primary[type='submit']")
    token = page.locator(".token").first
    box = token.bounding_box()
    line = float(token.evaluate("e => parseFloat(getComputedStyle(e).lineHeight)"))
    assert box and box["height"] < line * 1.5
    ctx.close()


def test_stats_panels_share_the_same_top(browser: Browser, base_url: str) -> None:
    """`.panel + .panel` (site.css) adds a stacking
    margin meant for panels in normal vertical flow; inside the stats page's
    two-column grid it also fired, pushing "nach Kategorie" 23px below "nach
    Status" even though the grid's own `gap` already spaces them."""
    ctx, page = _page(browser, base_url, 1440)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    page.goto(f"{base_url}/admin/stats")
    page.wait_for_load_state("networkidle")
    tops = page.eval_on_selector_all(
        ".stat-two-col > .panel", "els => els.map(e => e.getBoundingClientRect().y)"
    )
    assert len(tops) >= 2, tops
    assert max(tops) - min(tops) < 2, tops
    ctx.close()


def test_status_is_visible_in_the_phone_table(browser: Browser, base_url: str) -> None:
    ctx, page = _page(browser, base_url, 390)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    badge = page.locator(".table-stack .stack-status .badge").first.bounding_box()
    assert badge and badge["x"] + badge["width"] <= 390
    ctx.close()


@pytest.mark.parametrize("path", ["/", "/status", "/admin/login"])
def test_a_page_that_fits_does_not_scroll_with_the_demo_banner(
    browser: Browser, base_url: str, path: str
) -> None:
    """The e2e stack runs in demo mode, so the banner is on every page. On a
    screen tall enough for the content, the footer ends flush with the window:
    no scrollbar, nothing below the fold."""
    ctx = browser.new_context(viewport={"width": 1920, "height": 1400}, base_url=base_url)
    page = ctx.new_page()
    page.goto(path)
    assert page.locator(".demo-banner").is_visible()
    heights = page.evaluate(
        "[document.documentElement.scrollHeight, innerHeight,"
        " Math.round(document.querySelector('footer').getBoundingClientRect().bottom)]"
    )
    ctx.close()
    assert heights[0] == heights[1] == heights[2], heights


@pytest.mark.parametrize("width", [1280, 1920, 3440])
def test_the_wizard_shares_the_headers_frame(browser: Browser, base_url: str, width: int) -> None:
    """The promises block was a full-height column pinned to the window's left
    edge: on a 3440 px ultra-wide screen it sat 1,150 px left of the logo and
    two thirds of the screen stayed empty. Block and form now start at the
    logo and end where the footer's last item ends."""
    ctx = browser.new_context(viewport={"width": width, "height": 1000}, base_url=base_url)
    page = ctx.new_page()
    page.goto("/submit")
    edges = page.evaluate(
        "['.nav-brand', '.footer-powered', '.split-sidebar', '.split-main']"
        ".map(s => document.querySelector(s).getBoundingClientRect())"
        ".map(r => [Math.round(r.left), Math.round(r.right)])"
    )
    ctx.close()
    brand, links, sidebar, form = edges
    assert sidebar[0] == brand[0], edges
    assert form[1] == links[1], edges


def test_the_wizard_promises_fit_beside_the_form(browser: Browser, base_url: str) -> None:
    """The block sticks beside the form instead of scrolling inside itself; it
    must not be taller than the first step, or it sets the page height."""
    for lang in ("de", "en", "fr", "es", "pt-br"):
        ctx = browser.new_context(
            viewport={"width": 1920, "height": 890},
            base_url=base_url,
            extra_http_headers={"Accept-Language": lang},
        )
        page = ctx.new_page()
        page.goto("/submit")
        heights = page.evaluate("[document.documentElement.scrollHeight, innerHeight]")
        ctx.close()
        assert heights[0] == heights[1], (lang, heights)


def test_a_phone_shows_the_step_count_not_six_hyphenated_labels(
    browser: Browser, base_url: str
) -> None:
    """At 390 px six labels under six dots broke into "Mo-dus", "Katego-rie"."""
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844},
        base_url=base_url,
        extra_http_headers={"Accept-Language": "de"},
    )
    page = ctx.new_page()
    page.goto("/submit")
    labels = page.locator(".split-main .stepper-label").evaluate_all(
        "els => els.filter(e => e.offsetParent !== null).length"
    )
    count = page.locator(".split-main .stepper-text").bounding_box()
    ctx.close()
    assert labels == 0
    assert count and count["height"] > 1, count


def test_the_demo_credentials_sit_beside_the_login_form(browser: Browser, base_url: str) -> None:
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, base_url=base_url)
    page = ctx.new_page()
    page.goto("/admin/login")
    box = page.locator(".demo-credentials").bounding_box()
    form = page.locator("form[action='/admin/login']").bounding_box()
    ctx.close()
    assert box and form
    assert box["x"] >= form["x"] + form["width"], (box, form)
    assert box["y"] < form["y"] + form["height"], (box, form)


@pytest.mark.parametrize("lang", ["en", "de"])
def test_the_wizard_first_step_fits_a_full_hd_window(
    browser: Browser, base_url: str, lang: str
) -> None:
    """1920 x 890 is a Full HD screen minus the browser's own chrome. The first
    step, with the demo banner, ends flush with it: no scrollbar, footer in view."""
    ctx = browser.new_context(viewport={"width": 1920, "height": 890}, base_url=base_url)
    page = ctx.new_page()
    page.goto(f"/submit?lang={lang}")
    heights = page.evaluate("[document.documentElement.scrollHeight, innerHeight]")
    ctx.close()
    assert heights[0] == heights[1], heights


@pytest.mark.parametrize("lang", ["de", "en"])
@pytest.mark.parametrize("width", [390, 1440])
def test_status_steps_neither_touch_nor_get_cut(
    browser: Browser, base_url: str, width: int, lang: str
) -> None:
    """German has the longest step labels. They ran into one another with no
    gap ("EINGEGANGENIN PRÜFUNG…") and the last was cut: labels never wrapped,
    so the lines between them shrank to nothing and overflow: hidden clipped."""
    from tests.e2e.conftest import DEMO_CASE_RECEIVED

    ctx = browser.new_context(
        viewport={"width": width, "height": 900},
        base_url=base_url,
        extra_http_headers={"Accept-Language": lang},
    )
    page = ctx.new_page()
    page.goto("/status")
    page.fill('input[name="case_number"]', DEMO_CASE_RECEIVED["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_RECEIVED["pin"])
    page.click("button.btn-primary[type='submit']")
    boxes = page.eval_on_selector_all(
        ".stepper-label",
        "els => els.map(e => { const r = e.getBoundingClientRect(); return [r.left, r.right]; })",
    )
    stepper = page.locator(".stepper").bounding_box()
    ctx.close()
    assert len(boxes) == 4 and stepper, boxes
    for (_, right), (left, _) in zip(boxes, boxes[1:], strict=False):
        assert left - right >= 4, boxes
    assert boxes[0][0] >= stepper["x"] - 0.5, (boxes, stepper)
    assert boxes[-1][1] <= stepper["x"] + stepper["width"] + 0.5, (boxes, stepper)


def test_an_alert_draws_its_bar(browser: Browser, base_url: str) -> None:
    """The alert rules set border-color with no width: the reset's width 0 won, and no
    alert drew the semantic edge DESIGN.md promises. It is the website's 3 px callout bar."""
    ctx, page = _page(browser, base_url, 1440)
    page.goto("/submit")
    edge = page.eval_on_selector(
        ".alert-info",
        "e => [getComputedStyle(e).borderLeftWidth, getComputedStyle(e).borderLeftColor,"
        " getComputedStyle(e).backgroundColor]",
    )
    ctx.close()
    assert edge[0] == "3px", edge
    assert edge[1] != edge[2], edge  # the bar is not the tint it sits on


def test_a_panel_above_the_demo_credentials_keeps_its_gap(browser: Browser, base_url: str) -> None:
    """With the local-review panel (the release Chrome check) the credentials box sits
    between the two panels in the source, so `.panel + .panel` never matched and the
    panels touched. The local-review markup is only on that stack; this adds its panel."""
    ctx, page = _page(browser, base_url, 1440)
    page.goto("/admin/login")
    page.eval_on_selector(
        ".demo-credentials",
        "e => e.insertAdjacentHTML('beforebegin', '<div class=\"panel\" id=\"probe\">x</div>')",
    )
    gap = page.eval_on_selector(
        "#probe",  # offsets, not boxes: the panels are still sliding in
        """p => { const f = document.querySelector("form[action='/admin/login']").closest('.panel');
                  return f.offsetTop - (p.offsetTop + p.offsetHeight); }""",
    )
    ctx.close()
    assert gap >= 16, gap


def test_the_search_button_sits_beside_the_search_field(browser: Browser, base_url: str) -> None:
    """The hint lived inside the field's group, so the flex row aligned the button with
    the hint's last line, below the field."""
    ctx, page = _page(browser, base_url, 1440)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    page.goto("/admin/dashboard")
    field = page.locator("#dash-search-q").bounding_box()
    button = page.locator(".dash-search button[type='submit']").bounding_box()
    ctx.close()
    assert field and button and abs(field["y"] - button["y"]) <= 2, (field, button)


def test_a_card_spaces_its_text_and_numbers_its_steps(browser: Browser, base_url: str) -> None:
    """The reset stripped every margin and list number inside the long-form admin cards:
    headings touched their text and "How it works" lost its 1-2-3-4."""
    ctx, page = _page(browser, base_url, 1440)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    page.goto("/admin/retention")
    found = page.eval_on_selector(
        "#heading-how",
        """h => [h.nextElementSibling.getBoundingClientRect().top
                   - h.getBoundingClientRect().bottom,
                 getComputedStyle(h.parentElement.querySelector('ol')).listStyleType]""",
    )
    ctx.close()
    assert found[0] >= 8 and found[1] == "decimal", found


def test_the_telemetry_request_reads_as_a_code_block(browser: Browser, base_url: str) -> None:
    """The request sat in an inline code chip the colour of the card, its padding indenting
    only "GET"; the labels beside their values were lifted off the line."""
    ctx, page = _page(browser, base_url, 1440)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    page.goto("/admin/system")
    found = page.eval_on_selector(
        "#heading-telemetry",
        """h => {
            const card = h.parentElement, pre = card.querySelector('pre');
            const text = pre.querySelector('code').firstChild, r = document.createRange();
            const left = i => (r.setStart(text, i), r.setEnd(text, i + 1),
                               r.getBoundingClientRect().left);
            const label = card.querySelector('.detail-row .detail-label');
            return [getComputedStyle(pre).backgroundColor, getComputedStyle(card).backgroundColor,
                    left(0) - left(text.data.indexOf('User-Agent')),
                    getComputedStyle(label).marginBottom];
        }""",
    )
    ctx.close()
    assert found[0] != found[1], found
    assert abs(found[2]) < 1, found  # both lines start at the same x
    assert found[3] == "0px", found


def test_the_account_facts_get_half_the_page(browser: Browser, base_url: str) -> None:
    """In a third of the page every account fact wrapped onto two or three lines."""
    ctx, page = _page(browser, base_url, 1440)
    _admin_login(page, base_url, DEMO_ADMIN_USERNAME, DEMO_ADMIN_PASSWORD, DEMO_ADMIN_TOTP_SECRET)
    page.goto("/admin/account")
    widths = page.eval_on_selector_all(
        ".admin-split-grid > .panel", "els => els.map(e => e.getBoundingClientRect().width)"
    )
    ctx.close()
    assert len(widths) == 2 and abs(widths[0] - widths[1]) < 2, widths


@pytest.mark.parametrize("lang", ["en", "de"])
def test_a_case_reads_its_deadlines_on_one_line(browser: Browser, base_url: str, lang: str) -> None:
    """The case view shared the lookup form's 540 px column: at 1920 px "7-day
    acknowledgement (§17 I)" broke between "§17" and "I", and every deadline wrapped."""
    ctx = browser.new_context(
        viewport={"width": 1920, "height": 1080}, base_url=base_url, locale=lang
    )
    ctx.add_cookies([{"name": "ow-lang", "value": lang, "url": base_url}])
    page = ctx.new_page()
    page.goto("/status")
    page.fill('input[name="case_number"]', DEMO_CASE_PENDING["case_number"])
    page.fill('input[name="pin"]', DEMO_CASE_PENDING["pin"])
    page.click("button.btn-primary")
    lines = page.eval_on_selector_all(
        ".st-deadline-label",
        "els => els.map(e => Math.round(e.getBoundingClientRect().height"
        " / parseFloat(getComputedStyle(e).lineHeight)))",
    )
    ctx.close()
    assert lines and all(n == 1 for n in lines), lines


def test_demo_case_numbers_stay_on_one_line_on_a_phone(browser: Browser, base_url: str) -> None:
    """At 390 px a case number broke into two or three lines beside a long status badge."""
    ctx = browser.new_context(
        viewport={"width": 390, "height": 844},
        base_url=base_url,
        extra_http_headers={"Accept-Language": "de"},
    )
    page = ctx.new_page()
    page.goto("/status")
    heights = page.eval_on_selector_all(
        ".demo-cred-code", "els => els.map(e => e.getBoundingClientRect().height)"
    )
    ctx.close()
    assert heights, "no demo case numbers on /status"
    assert max(heights) < 40, heights  # one 24 px line plus padding
