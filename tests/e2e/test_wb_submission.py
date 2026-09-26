"""E2E tests for the whistleblower submission wizard.

The wizard has up to 6 steps (with location step conditional):
  Step 1: Mode selection (anonymous / confidential)
  Step 2: Location (only shown if locations exist)
  Step 3: Category selection
  Step 4: Description
  Step 5: Attachments (optional)
  Step 6: Review / confirm

Navigation: each step has a "Next" button (button[type="submit"][name="action"][value="next"]).
"""

from __future__ import annotations

import io
import re

import pytest
from playwright.sync_api import Browser, Page, expect

pytestmark = pytest.mark.e2e

_NEXT_BTN = 'button[type="submit"][name="action"][value="next"]'
_BACK_BTN = 'button[type="submit"][name="action"][value="back"]'
_CASE_RE = re.compile(r"OW-[A-Z0-9]{4}-\d{5}")


def _advance_step(page: Page) -> None:
    """Click the Next/Submit button on the current wizard step."""
    page.click(_NEXT_BTN)
    page.wait_for_load_state("networkidle")


def _skip_location_if_present(page: Page) -> None:
    """If the location step (step 2) is shown, skip it by clicking Next without selecting."""
    # Check if we are on the location step by looking for location_id select
    if page.locator('select[name="location_id"]').count() > 0:
        _advance_step(page)


def _go_through_wizard_to_category(page: Page) -> None:
    """Navigate through step 1 (mode already set) and optional step 2 to reach category step."""
    _skip_location_if_present(page)


def _click_expect_redirect(page: Page, selector: str) -> None:
    """Click a wizard nav button and assert the POST is answered with a redirect.

    Every step transition must go through Post/Redirect/Get: the POST to
    /submit returns a 303 to /submit, and a GET renders the step. If a step
    ever renders straight from the POST's 200 response again, a native
    browser Back to that page forces the browser to either replay the POST
    (the "Confirm Form Resubmission" dialog) or serve a stale snapshot —
    this is the regression this whole test file guards against.
    """
    with page.expect_response(
        lambda r: r.request.method == "POST" and r.url.endswith("/submit")
    ) as resp_info:
        page.click(selector)
    assert resp_info.value.status == 303, (
        f"Expected the wizard POST to redirect (303), got {resp_info.value.status}. "
        "A step that renders directly from a POST breaks the native browser Back button."
    )
    page.wait_for_load_state("networkidle")


def _fill_mode_step(page: Page) -> None:
    page.locator('label[for="mode-anonymous"]').click()


def _fill_category_step(page: Page) -> None:
    category_select = page.locator('select[name="category"]')
    expect(category_select).to_be_visible()
    for opt in category_select.locator("option").all():
        val = opt.get_attribute("value") or ""
        if val:
            category_select.select_option(val)
            break


def _fill_description_step(page: Page) -> None:
    page.locator('textarea[name="description"]').fill(
        "This report exercises the native browser Back button at every wizard "
        "step. Long enough to pass the minimum description length validation."
    )


def _fill_whatever_step_is_showing(page: Page) -> None:
    """Fill in the current step's required field(s), if it has any, and advance.

    Location, attachments, and review need no input to click Next. Written
    generically (rather than assuming a fixed step order) because a native
    Back navigation always resolves to the session's real current step, which
    may not be the step the test last saw.
    """
    if page.locator('label[for="mode-anonymous"]').count() > 0:
        _fill_mode_step(page)
    elif page.locator('select[name="category"]').count() > 0:
        _fill_category_step(page)
    elif page.locator('textarea[name="description"]').count() > 0:
        _fill_description_step(page)
    _advance_step(page)


def _assert_submit_page_healthy(page: Page) -> None:
    """After a browser Back to /submit, the page must be a normal, working step —

    not a browser-generated resubmission/error interstitial, and not a server
    error page.
    """
    assert page.url.rstrip("/").endswith("/submit"), (
        f"Back navigation left the browser on an unexpected URL: {page.url}"
    )
    assert page.locator(".alert-error").count() == 0, (
        f"Unexpected validation error shown after Back: {page.content()}"
    )
    step_markers = [
        'label[for="mode-anonymous"]',
        'select[name="location_id"]',
        'select[name="category"]',
        'textarea[name="description"]',
        'input[type="file"][name="files"]',
        _NEXT_BTN,
    ]
    assert any(page.locator(sel).count() > 0 for sel in step_markers), (
        f"Back navigation did not land on a recognizable wizard step: {page.content()}"
    )


def test_submit_page_loads(page: Page, base_url: str) -> None:
    """The submission wizard landing page (step 1) loads correctly."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")
    assert "OpenWhistle" in page.title()
    # Mode card labels are visible (underlying radio inputs are CSS-hidden for styling)
    expect(page.locator("label.mode-card").first).to_be_visible()


def test_anonymous_submission_full_wizard(page: Page, base_url: str) -> None:
    """Anonymous submission flows through all steps and produces a case number + PIN."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    # Step 1: select anonymous mode — radio inputs are CSS-hidden; click the label card
    page.locator('label[for="mode-anonymous"]').click()
    _advance_step(page)

    # Step 2 (location — conditional): skip if present
    _skip_location_if_present(page)

    # Step 3: category — select first non-placeholder option
    page.wait_for_load_state("networkidle")
    category_select = page.locator('select[name="category"]')
    expect(category_select).to_be_visible()
    # Select the first real option (not the placeholder "")
    options = category_select.locator("option").all()
    for opt in options:
        val = opt.get_attribute("value") or ""
        if val:
            category_select.select_option(val)
            break
    _advance_step(page)

    # Step 4: description
    page.wait_for_load_state("networkidle")
    desc_area = page.locator('textarea[name="description"]')
    expect(desc_area).to_be_visible()
    desc_area.fill(
        "This is an anonymous test report submitted via E2E tests. "
        "It contains enough characters to pass the minimum length validation."
    )
    _advance_step(page)

    # Step 5: attachments (skip — no file)
    page.wait_for_load_state("networkidle")
    _advance_step(page)

    # Step 6: review — submit the form
    page.wait_for_load_state("networkidle")
    _advance_step(page)

    # Success page: check for case number and PIN
    page.wait_for_load_state("networkidle")
    body = page.content()
    assert _CASE_RE.search(body) is not None, (
        f"No case number (OW-XXXX-NNNNN) found on success page. URL: {page.url}"
    )
    # PIN should be a UUID-like or long string
    assert (
        re.search(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", body) is not None
        or re.search(r"[a-zA-Z0-9\-]{20,}", body) is not None
    ), "No PIN found on success page"


def test_confidential_submission_full_wizard(page: Page, base_url: str) -> None:
    """Confidential submission fills name and contact fields and completes successfully."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    # Step 1: select confidential mode — click the label card (radio inputs are CSS-hidden)
    page.locator('label[for="mode-confidential"]').click()
    # The confidential fields should become visible (JS toggles on change event)
    confidential_fields = page.locator("#confidential-fields")
    expect(confidential_fields).to_be_visible()
    page.fill('input[name="confidential_name"]', "E2E Test Submitter")
    page.fill('input[name="confidential_contact"]', "e2e-test@example.invalid")
    _advance_step(page)

    # Step 2 (location — conditional): skip if present
    _skip_location_if_present(page)

    # Step 3: category
    page.wait_for_load_state("networkidle")
    category_select = page.locator('select[name="category"]')
    expect(category_select).to_be_visible()
    options = category_select.locator("option").all()
    for opt in options:
        val = opt.get_attribute("value") or ""
        if val:
            category_select.select_option(val)
            break
    _advance_step(page)

    # Step 4: description
    page.wait_for_load_state("networkidle")
    page.locator('textarea[name="description"]').fill(
        "This is a confidential test report submitted via E2E tests. "
        "Enough content to satisfy minimum length validation for the description field."
    )
    _advance_step(page)

    # Step 5: attachments (skip)
    page.wait_for_load_state("networkidle")
    _advance_step(page)

    # Step 6: review page — check confidential mode is displayed
    page.wait_for_load_state("networkidle")
    review_content = page.content()
    # Either the word "Confidential" or an equivalent translated label should appear
    assert any(
        word in review_content
        for word in ["confidential", "Confidential", "vertraulich", "Vertraulich"]
    ), "Confidential mode not shown on review page"
    _advance_step(page)

    # Success page
    page.wait_for_load_state("networkidle")
    body = page.content()
    assert _CASE_RE.search(body) is not None, (
        f"No case number found on success page after confidential submission. URL: {page.url}"
    )


def test_back_from_empty_description_does_not_validate(page: Page, base_url: str) -> None:
    """Back navigation from the description step works even when the textarea is empty.

    Regression: the double-submit guard disabled the form's first submit button
    (which is "Back") while the entry list was still being built, so action=back
    never reached the server and the step was validated as a "Next".
    """
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    # Step 1: anonymous mode
    page.locator('label[for="mode-anonymous"]').click()
    _advance_step(page)

    # Step 2 (location — conditional): skip if present
    _skip_location_if_present(page)

    # Step 3: category
    page.wait_for_load_state("networkidle")
    category_select = page.locator('select[name="category"]')
    expect(category_select).to_be_visible()
    for opt in category_select.locator("option").all():
        val = opt.get_attribute("value") or ""
        if val:
            category_select.select_option(val)
            break
    _advance_step(page)

    # Step 4: description — leave it empty and go back
    page.wait_for_load_state("networkidle")
    expect(page.locator('textarea[name="description"]')).to_be_visible()
    page.click(_BACK_BTN)
    page.wait_for_load_state("networkidle")

    # We are back on the category step, with no validation error shown
    expect(page.locator('select[name="category"]')).to_be_visible()
    expect(page.locator('textarea[name="description"]')).to_have_count(0)
    assert page.locator(".alert-error").count() == 0, (
        f"Validation error shown after clicking Back with an empty description: {page.content()}"
    )


def test_submission_with_file_attachment(page: Page, base_url: str) -> None:
    """Submission with a file attachment shows the filename on the review page."""
    # A parseable PDF: uploads that cannot be stripped of metadata are refused.
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(72, 72)
    buf = io.BytesIO()
    writer.write(buf)
    fake_pdf = buf.getvalue()

    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    # Step 1: anonymous mode — click label card (radio inputs are CSS-hidden)
    page.locator('label[for="mode-anonymous"]').click()
    _advance_step(page)

    # Step 2 (location — conditional): skip if present
    _skip_location_if_present(page)

    # Step 3: category
    page.wait_for_load_state("networkidle")
    category_select = page.locator('select[name="category"]')
    options = category_select.locator("option").all()
    for opt in options:
        val = opt.get_attribute("value") or ""
        if val:
            category_select.select_option(val)
            break
    _advance_step(page)

    # Step 4: description
    page.wait_for_load_state("networkidle")
    page.locator('textarea[name="description"]').fill(
        "Test report with file attachment. Contains sufficient length to pass validation."
    )
    _advance_step(page)

    # Step 5: attachments — upload a fake PDF
    page.wait_for_load_state("networkidle")
    file_input = page.locator('input[type="file"][name="files"]')
    expect(file_input).to_be_attached()
    file_input.set_input_files(
        [{"name": "e2e_test_attachment.pdf", "mimeType": "application/pdf", "buffer": fake_pdf}]
    )
    _advance_step(page)

    # Step 6: review — check that the filename is shown
    page.wait_for_load_state("networkidle")
    review_content = page.content()
    assert "e2e_test_attachment.pdf" in review_content, "Uploaded filename not shown on review page"
    _advance_step(page)

    # Success page
    page.wait_for_load_state("networkidle")
    body = page.content()
    assert _CASE_RE.search(body) is not None, (
        f"No case number found on success page after attachment submission. URL: {page.url}"
    )


def test_every_wizard_step_transition_is_post_redirect_get(page: Page, base_url: str) -> None:
    """Every step's Next/Back POST redirects rather than rendering HTML directly.

    Regression guard: a step that renders straight from its POST's 200 response
    creates a browser history entry for a POST. Native Back to that entry then
    forces the browser to either replay the POST (the "Confirm Form
    Resubmission" dialog) or serve a stale cached snapshot — the underlying
    cause of the Back button "not working" halfway through the form. Every
    transition must instead redirect (303) to a plain GET /submit, which a
    browser can always safely re-issue with no dialog.
    """
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    _fill_mode_step(page)
    _click_expect_redirect(page, _NEXT_BTN)

    if page.locator('select[name="location_id"]').count() > 0:
        _click_expect_redirect(page, _NEXT_BTN)

    _fill_category_step(page)
    _click_expect_redirect(page, _NEXT_BTN)

    _fill_description_step(page)
    _click_expect_redirect(page, _NEXT_BTN)

    _click_expect_redirect(page, _BACK_BTN)
    _fill_description_step(page)
    _click_expect_redirect(page, _NEXT_BTN)
    _click_expect_redirect(page, _NEXT_BTN)

    _advance_step(page)

    page.wait_for_load_state("networkidle")
    assert _CASE_RE.search(page.content()) is not None, (
        f"Wizard did not reach the success page after redirect-based navigation. URL: {page.url}"
    )


def test_native_back_button_after_every_step_keeps_wizard_usable(page: Page, base_url: str) -> None:
    """The browser's native Back button never leaves the wizard in a broken state.

    Walks the full wizard and, after every step transition, uses the browser's
    own Back button (not the in-page "Back" link) — the exact action the bug
    report described as "not working when halfway through the form" — then
    verifies the page is a healthy, recognizable wizard step (no validation
    error, no server error, no stuck resubmission interstitial) and that the
    wizard is still completable afterward.

    Every Back is immediately preceded and followed by a forward step, so the
    browser always has a history entry to go back to; the loop is driven by
    whatever step is actually showing rather than an assumed step order,
    since a session-authoritative wizard can legitimately show the same
    "current step" again rather than a literal history rewind.
    """
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    def _done() -> bool:
        return _CASE_RE.search(page.content()) is not None

    for _ in range(8):
        _fill_whatever_step_is_showing(page)
        if _done():
            break

        page.go_back()
        page.wait_for_load_state("networkidle")
        _assert_submit_page_healthy(page)

        _fill_whatever_step_is_showing(page)
        if _done():
            break
    else:
        pytest.fail(f"Wizard did not reach the success page within 8 steps. URL: {page.url}")

    assert _done(), (
        f"Wizard was not completable after native Back navigation at every step. URL: {page.url}"
    )


def test_in_wizard_back_button_preserves_uploaded_attachment(page: Page, base_url: str) -> None:
    """The in-wizard "Back" button must not silently drop an uploaded attachment.

    A browser can never pre-fill a file input, so revisiting the attachments
    step via the "Back" button always shows it empty regardless of what's
    already attached. Clicking "Next" again without re-selecting anything
    must be read as "leave it as-is", not "clear the attachments" — this is
    the concrete bug report behind "the back button doesn't work correctly
    halfway through the form": going back and continuing forward again used
    to silently discard the already-uploaded evidence file with no warning.
    """
    from pypdf import PdfWriter

    writer = PdfWriter()
    writer.add_blank_page(72, 72)
    buf = io.BytesIO()
    writer.write(buf)
    fake_pdf = buf.getvalue()

    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    page.locator('label[for="mode-anonymous"]').click()
    _advance_step(page)
    _skip_location_if_present(page)

    page.wait_for_load_state("networkidle")
    _fill_category_step(page)
    _advance_step(page)

    page.wait_for_load_state("networkidle")
    _fill_description_step(page)
    _advance_step(page)

    page.wait_for_load_state("networkidle")
    page.locator('input[type="file"][name="files"]').set_input_files(
        [{"name": "back_button_test.pdf", "mimeType": "application/pdf", "buffer": fake_pdf}]
    )
    _advance_step(page)

    page.wait_for_load_state("networkidle")
    assert "back_button_test.pdf" in page.content(), "Filename not shown on review page"

    page.click(_BACK_BTN)
    page.wait_for_load_state("networkidle")
    assert page.locator('input[type="file"][name="files"]').count() == 1, (
        "Back from review did not land on the attachments step"
    )
    assert "back_button_test.pdf" in page.content(), (
        "Attachments step gives no indication the file is already attached after Back"
    )

    _advance_step(page)

    page.wait_for_load_state("networkidle")
    assert "back_button_test.pdf" in page.content(), (
        "The previously-uploaded attachment was silently dropped after "
        "Back then Next without re-selecting a file"
    )


def test_description_validation_failure_preserves_typed_text(page: Page, base_url: str) -> None:
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")

    page.locator('label[for="mode-anonymous"]').click()
    _advance_step(page)
    _skip_location_if_present(page)

    page.wait_for_load_state("networkidle")
    _fill_category_step(page)
    _advance_step(page)

    page.wait_for_load_state("networkidle")
    desc_area = page.locator('textarea[name="description"]')
    desc_area.fill("abcdef")
    _advance_step(page)

    page.wait_for_load_state("networkidle")
    assert page.locator('textarea[name="description"]').input_value() == "abcdef", (
        f"Typed text was not preserved after a failed validation. URL: {page.url}"
    )

    page.locator('textarea[name="description"]').fill("xyztuv")
    _advance_step(page)

    page.wait_for_load_state("networkidle")
    assert page.locator('textarea[name="description"]').input_value() == "xyztuv", (
        f"Textarea reverted to a previous value instead of the just-typed text. URL: {page.url}"
    )


def test_wrongly_attached_file_can_be_removed(page: Page, base_url: str) -> None:
    """Attachments survive Back, so a mistaken file needs its own Remove control."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")
    _fill_mode_step(page)
    _advance_step(page)
    _skip_location_if_present(page)
    page.wait_for_load_state("networkidle")
    _fill_category_step(page)
    _advance_step(page)
    page.wait_for_load_state("networkidle")
    _fill_description_step(page)
    _advance_step(page)

    page.wait_for_load_state("networkidle")
    page.locator('input[type="file"][name="files"]').set_input_files(
        [
            {"name": "keep.txt", "mimeType": "text/plain", "buffer": b"evidence to keep"},
            {"name": "wrong.txt", "mimeType": "text/plain", "buffer": b"attached by mistake"},
        ]
    )
    _advance_step(page)
    page.wait_for_load_state("networkidle")
    page.click(_BACK_BTN)
    page.wait_for_load_state("networkidle")

    page.get_by_role("button", name="Remove wrong.txt").click()
    page.wait_for_load_state("networkidle")
    assert "wrong.txt" not in page.content()
    assert "keep.txt" in page.content()

    _advance_step(page)
    page.wait_for_load_state("networkidle")
    review = page.content()
    assert "keep.txt" in review
    assert "wrong.txt" not in review


def _walk_to_review(page: Page, base_url: str, description: str) -> None:
    """Anonymous submission, mode through attachments; stops on the review step."""
    page.goto(f"{base_url}/submit")
    page.wait_for_load_state("networkidle")
    _fill_mode_step(page)
    _advance_step(page)
    _skip_location_if_present(page)
    page.wait_for_load_state("networkidle")
    _fill_category_step(page)
    _advance_step(page)
    page.wait_for_load_state("networkidle")
    page.locator('textarea[name="description"]').fill(description)
    _advance_step(page)
    page.wait_for_load_state("networkidle")
    _advance_step(page)  # attachments step — skip, no file
    page.wait_for_load_state("networkidle")


def _boxes_overlap(a: dict, b: dict) -> bool:
    return not (
        a["x"] + a["width"] <= b["x"]
        or b["x"] + b["width"] <= a["x"]
        or a["y"] + a["height"] <= b["y"]
        or b["y"] + b["height"] <= a["y"]
    )


@pytest.mark.parametrize("width", [1440, 390])
def test_pin_and_case_number_fit_without_scrolling(
    browser: Browser, base_url: str, width: int
) -> None:
    """The success screen's case number and PIN must be fully visible at every
    width, never cut off behind a scrollbar, and never sit under the copy
    button — Chrome review finding: 469px of PIN content in a 434px box, the
    PIN scrolled and partly hidden behind the copy button."""
    ctx = browser.new_context(viewport={"width": width, "height": 900}, base_url=base_url)
    page = ctx.new_page()
    _walk_to_review(
        page,
        base_url,
        "Overflow regression test report — long enough to pass the minimum "
        "description length validation for the wizard.",
    )
    _advance_step(page)  # review -> submit
    page.wait_for_load_state("networkidle")

    for elem_id in ("case-number", "pin-value"):
        box_el = page.locator(f"#{elem_id}")
        if box_el.count() == 0:
            continue
        overflow = box_el.evaluate("el => el.scrollWidth - el.clientWidth")
        assert overflow <= 0, f"#{elem_id}: {overflow}px horizontal overflow at {width}px"

        token = box_el.locator(".token")
        copy_btn = box_el.locator(".copy-btn")
        # The container's own scrollWidth is blind to a flex child's ink
        # overflow (a `min-width: 0` child that cannot wrap just paints past
        # its shrunk box without enlarging the flex row) — checking the token
        # span's own scrollWidth is what actually catches a reintroduced
        # `white-space: nowrap` on `.token`.
        token_overflow = token.evaluate("el => el.scrollWidth - el.clientWidth")
        assert token_overflow <= 0, (
            f"#{elem_id} .token: {token_overflow}px of text does not fit its own box "
            f"at {width}px (white-space: nowrap would cause exactly this)"
        )

        token_box, btn_box = token.bounding_box(), copy_btn.bounding_box()
        assert token_box and btn_box
        assert not _boxes_overlap(token_box, btn_box), (
            f"#{elem_id}: copy button overlaps the value at {width}px"
        )

        visible_text = token.inner_text().strip()
        raw_value = copy_btn.get_attribute("data-copy")
        assert visible_text == raw_value, (
            f"#{elem_id}: visible text {visible_text!r} != raw value {raw_value!r}"
        )
    ctx.close()


def test_review_step_label_and_value_do_not_overlap_in_german(
    browser: Browser, base_url: str
) -> None:
    """Chrome review finding: the German label "EINREICHUNGSMODUS" overlapped
    its value "Anonym" — the label column was too narrow for that locale."""
    ctx = browser.new_context(viewport={"width": 1440, "height": 900}, base_url=base_url)
    ctx.add_cookies([{"name": "ow-lang", "value": "de", "url": base_url}])
    page = ctx.new_page()
    _walk_to_review(
        page,
        base_url,
        "Deutschsprachiger Testbericht mit ausreichend Zeichen zur Validierung "
        "der Mindestlänge im Formular.",
    )

    mode_row = page.locator(".review-row").first
    label = mode_row.locator(".review-label")
    value = mode_row.locator(".review-value")
    # A fixed-width label with an unbreakable, single-word value ("EINREICHUNGS-
    # MODUS") doesn't shrink its own box to the overflowing text — the box
    # (and getBoundingClientRect) stays at its CSS width while the text paints
    # past it, so an overlap check on the two boxes alone can miss it; the
    # label's own scrollWidth vs. clientWidth catches exactly that overflow.
    label_overflow = label.evaluate("el => el.scrollWidth - el.clientWidth")
    assert label_overflow <= 0, (
        f"German review label does not fit its own column ({label_overflow}px over)"
    )
    label_box, value_box = label.bounding_box(), value.bounding_box()
    assert label_box and value_box
    assert not _boxes_overlap(label_box, value_box), "German review label overlaps its value"
    assert "Anonym" in value.inner_text()
    ctx.close()
