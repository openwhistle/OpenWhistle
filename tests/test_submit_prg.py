"""Submission wizard: Post/Redirect/Get and the stale-step guard (#94)."""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient, Response
from sqlalchemy.ext.asyncio import AsyncSession


def _csrf(text: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', text)
    return m.group(1) if m else ""


def _step(text: str) -> int:
    m = re.search(r'name="step" value="(\d+)"', text)
    return int(m.group(1)) if m else 1


async def _post(client: AsyncClient, step: int | None = None, **fields: str) -> Response:
    """POST the current wizard step (or `step`) without following the redirect."""
    page = await client.get("/submit")
    data = {
        "csrf_token": _csrf(page.text),
        "step": str(step if step is not None else _step(page.text)),
        "action": "next",
        **fields,
    }
    return await client.post("/submit", data=data, follow_redirects=False)


async def _walk_to_description(client: AsyncClient) -> None:
    await _post(client, submission_mode="anonymous")
    if _step((await client.get("/submit")).text) == 2:
        await _post(client, location_id="")
    await _post(client, category="financial_fraud")


@pytest.mark.asyncio
async def test_every_step_transition_redirects_to_get(client: AsyncClient) -> None:
    resp = await _post(client, submission_mode="anonymous")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/submit"
    assert "ow-submission-session" in resp.headers.get("set-cookie", "")


@pytest.mark.asyncio
async def test_back_action_redirects_to_get(client: AsyncClient) -> None:
    await _post(client, submission_mode="anonymous")
    page = await client.get("/submit")
    resp = await client.post(
        "/submit",
        data={"csrf_token": _csrf(page.text), "step": str(_step(page.text)), "action": "back"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert _step((await client.get("/submit")).text) == 1


@pytest.mark.asyncio
async def test_validation_error_is_a_one_shot_flash(client: AsyncClient) -> None:
    resp = await _post(client, submission_mode="")
    assert resp.status_code == 303
    first = await client.get("/submit")
    assert 'role="alert"' in first.text
    assert 'aria-invalid="true"' in first.text
    second = await client.get("/submit")
    assert 'aria-invalid="true"' not in second.text


@pytest.mark.asyncio
async def test_upload_error_flash_marks_the_file_field(client: AsyncClient) -> None:
    await _walk_to_description(client)
    await _post(client, description="A description long enough to pass.")
    page = await client.get("/submit")
    resp = await client.post(
        "/submit",
        data={"csrf_token": _csrf(page.text), "step": str(_step(page.text)), "action": "next"},
        files={"files": ("evil.exe", b"MZ\x90\x00", "application/octet-stream")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    shown = await client.get("/submit")
    assert re.search(r'id="files"[^>]*aria-invalid="true"', shown.text, re.S)


@pytest.mark.asyncio
async def test_stale_earlier_step_is_not_reprocessed(client: AsyncClient) -> None:
    """A replayed step-1 POST must not rewind progress or change the stored mode."""
    await _walk_to_description(client)
    description_step = _step((await client.get("/submit")).text)

    resp = await _post(
        client, step=1, submission_mode="confidential", confidential_name="Replayed Name"
    )
    assert resp.status_code == 303
    page = await client.get("/submit")
    assert _step(page.text) == description_step
    assert 'role="alert"' not in page.text

    # The mode stored before the replay is still anonymous on the review step.
    await _post(client, description="A description long enough to pass.")
    await _post(client)
    review = (await client.get("/submit")).text
    mode_shown = re.search(r'class="review-value">\s*(\w+)', review)
    assert mode_shown is not None
    assert mode_shown.group(1) == "Anonymous"


@pytest.mark.asyncio
async def test_step_ahead_on_fresh_session_shows_session_incomplete(
    client: AsyncClient,
) -> None:
    resp = await _post(client, step=5)
    assert resp.status_code == 303
    page = await client.get("/submit")
    assert _step(page.text) == 1
    assert "start over" in page.text.lower()


# ── Attachments survive Back (#94) ─────────────────────────────────


async def _walk_to_attachments(client: AsyncClient) -> None:
    await _walk_to_description(client)
    await _post(client, description="A description long enough to pass.")


async def _upload(client: AsyncClient, *files: tuple[str, bytes]) -> Response:
    page = await client.get("/submit")
    return await client.post(
        "/submit",
        data={"csrf_token": _csrf(page.text), "step": str(_step(page.text)), "action": "next"},
        files=[("files", (name, data, "text/plain")) for name, data in files],
        follow_redirects=False,
    )


async def _back(client: AsyncClient) -> None:
    page = await client.get("/submit")
    await client.post(
        "/submit",
        data={"csrf_token": _csrf(page.text), "step": str(_step(page.text)), "action": "back"},
        follow_redirects=False,
    )


@pytest.mark.asyncio
async def test_back_then_next_without_files_keeps_attachments(client: AsyncClient) -> None:
    await _walk_to_attachments(client)
    await _upload(client, ("evidence.txt", b"first evidence file"))
    assert "evidence.txt" in (await client.get("/submit")).text  # review

    await _back(client)
    attachments_step = (await client.get("/submit")).text
    assert 'name="files"' in attachments_step
    assert "Already attached" in attachments_step
    assert "evidence.txt" in attachments_step

    await _upload(client)  # Next with the (always empty) file input
    assert "evidence.txt" in (await client.get("/submit")).text


@pytest.mark.asyncio
async def test_new_files_replace_the_attached_ones(client: AsyncClient) -> None:
    await _walk_to_attachments(client)
    await _upload(client, ("old.txt", b"the old evidence"))
    await _back(client)
    await _upload(client, ("new.txt", b"the new evidence"))
    review = (await client.get("/submit")).text
    assert "new.txt" in review
    assert "old.txt" not in review


@pytest.mark.asyncio
async def test_infected_replacement_keeps_the_attached_file(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.virus_scan as virus_scan

    async def _scan(data: bytes) -> str | None:
        return "Eicar-Test-Signature" if b"EICAR" in data else None

    monkeypatch.setattr(virus_scan, "scan_bytes", _scan)
    await _walk_to_attachments(client)
    await _upload(client, ("clean.txt", b"clean evidence"))
    await _back(client)

    resp = await _upload(client, ("infected.txt", b"EICAR payload"))
    assert resp.status_code == 303
    page = (await client.get("/submit")).text
    assert 'name="files"' in page  # still on the attachments step, with the error
    assert "infected.txt" in page
    assert "clean.txt" in page

    await _upload(client)
    review = (await client.get("/submit")).text
    assert "clean.txt" in review
    assert "infected.txt" not in review


@pytest.mark.asyncio
async def test_unstrippable_replacement_keeps_the_attached_file(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.attachment as attachment

    real_strip = attachment.strip_metadata

    def _strip(name: str, data: bytes) -> bytes:
        if name == "broken.txt":
            raise attachment.MetadataError(name)
        return real_strip(name, data)

    monkeypatch.setattr(attachment, "strip_metadata", _strip)
    await _walk_to_attachments(client)
    await _upload(client, ("kept.txt", b"kept evidence"))
    await _back(client)

    await _upload(client, ("broken.txt", b"cannot be stripped"))
    await _upload(client)
    review = (await client.get("/submit")).text
    assert "kept.txt" in review
    assert "broken.txt" not in review


# ── A failed description keeps what was typed (#94) ────────────────


@pytest.mark.asyncio
async def test_too_short_description_is_kept_in_the_textarea(client: AsyncClient) -> None:
    await _walk_to_description(client)
    await _post(client, description="abcdef")
    page = (await client.get("/submit")).text
    assert "at least 10" in page
    assert re.search(r"<textarea[^>]*>abcdef</textarea>", page, re.S)


@pytest.mark.asyncio
async def test_too_long_description_is_kept_truncated(client: AsyncClient) -> None:
    await _walk_to_description(client)
    await _post(client, description="x" * 10001)
    page = (await client.get("/submit")).text
    assert re.search(r"<textarea[^>]*>" + "x" * 10000 + "</textarea>", page, re.S)


@pytest.mark.asyncio
async def test_short_description_does_not_advance_the_session(client: AsyncClient) -> None:
    """Keeping the text must not count it as accepted: submit still needs a valid one."""
    await _walk_to_description(client)
    step = _step((await client.get("/submit")).text)
    await _post(client, description="abcdef")
    assert _step((await client.get("/submit")).text) == step
    resp = await _post(client, step=step + 2)  # jump to review
    assert resp.status_code == 303
    assert _step((await client.get("/submit")).text) == step


# ── Removing a wrongly attached file ────────────────────────────────


async def _remove(client: AsyncClient, index: str, csrf: str | None = None) -> Response:
    page = await client.get("/submit")
    return await client.post(
        "/submit/attachments/remove",
        data={"csrf_token": _csrf(page.text) if csrf is None else csrf, "index": index},
        follow_redirects=False,
    )


async def _attach_two_and_go_back(client: AsyncClient) -> None:
    await _walk_to_attachments(client)
    await _upload(client, ("keep.txt", b"evidence to keep"), ("wrong.txt", b"attached by mistake"))
    await _back(client)


@pytest.mark.asyncio
async def test_remove_drops_only_the_chosen_file(client: AsyncClient) -> None:
    await _attach_two_and_go_back(client)
    page = (await client.get("/submit")).text
    assert 'action="/submit/attachments/remove"' in page
    assert 'aria-label="Remove wrong.txt"' in page

    resp = await _remove(client, "1")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/submit"
    page = (await client.get("/submit")).text
    assert 'name="files"' in page  # still on the attachments step
    assert "wrong.txt" not in page

    await _upload(client)
    review = (await client.get("/submit")).text
    assert "keep.txt" in review
    assert "wrong.txt" not in review


@pytest.mark.asyncio
async def test_removing_the_last_file_leaves_no_attachments(client: AsyncClient) -> None:
    await _walk_to_attachments(client)
    await _upload(client, ("only.txt", b"attached by mistake"))
    await _back(client)
    await _remove(client, "0")
    assert "Already attached" not in (await client.get("/submit")).text
    await _upload(client)
    assert "only.txt" not in (await client.get("/submit")).text


@pytest.mark.asyncio
@pytest.mark.parametrize("index", ["2", "-1"])
async def test_remove_out_of_range_index_changes_nothing(client: AsyncClient, index: str) -> None:
    await _attach_two_and_go_back(client)
    await _remove(client, index)
    page = (await client.get("/submit")).text
    assert "keep.txt" in page
    assert "wrong.txt" in page


@pytest.mark.asyncio
async def test_remove_is_refused_outside_the_attachments_step(client: AsyncClient) -> None:
    await _walk_to_attachments(client)
    await _upload(client, ("keep.txt", b"evidence to keep"))  # now on review
    await _remove(client, "0")
    assert "keep.txt" in (await client.get("/submit")).text


@pytest.mark.asyncio
async def test_remove_requires_csrf(client: AsyncClient) -> None:
    await _attach_two_and_go_back(client)
    resp = await _remove(client, "0", csrf="not-the-token")
    assert resp.status_code == 403
    assert "keep.txt" in (await client.get("/submit")).text


@pytest.mark.asyncio
async def test_remove_without_a_draft_just_redirects(client: AsyncClient) -> None:
    resp = await _remove(client, "0")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/submit"


# ── Review-step integrity (#94 review) ──────────────────────────────

_CASE_RE = re.compile(r"OW-\d{4}-\d+")


async def _draft(client: AsyncClient) -> dict[str, object]:
    import app.api.reports as reports
    from app.redis_client import get_redis

    session_id = client.cookies.get("ow-submission-session")
    assert session_id
    return await reports._load_submission(await get_redis(), session_id)


async def _walk_to_review(client: AsyncClient) -> None:
    await _walk_to_attachments(client)
    await _upload(client)


@pytest.mark.asyncio
@pytest.mark.parametrize("action", ["x", "", "submit"])
async def test_unknown_action_with_a_kept_short_description_creates_no_report(
    client: AsyncClient, action: str
) -> None:
    await _walk_to_description(client)
    await _post(client, description="abcdef")  # rejected, but kept for editing
    page = await client.get("/submit")
    resp = await client.post(
        "/submit",
        data={"csrf_token": _csrf(page.text), "step": "6", "action": action},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert _CASE_RE.search((await client.get("/submit")).text) is None
    assert (await _draft(client))["step"] == _step(page.text)  # still on description


@pytest.mark.asyncio
async def test_unknown_action_on_a_fresh_session_stores_no_file(client: AsyncClient) -> None:
    page = await client.get("/submit")
    resp = await client.post(
        "/submit",
        data={"csrf_token": _csrf(page.text), "step": "5", "action": "x"},
        files={"files": ("stash.txt", b"a blob to stash in redis", "text/plain")},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    draft = await _draft(client)
    assert draft["step"] == 1
    assert "file_data" not in draft


_PIN_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}")


async def _set_draft(client: AsyncClient, draft: dict[str, object]) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    session_id = client.cookies.get("ow-submission-session")
    assert session_id
    await reports._save_submission(await get_redis(), session_id, draft)


async def _report_count() -> int:
    from sqlalchemy import func, select
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.config import settings
    from app.models.report import Report

    engine = create_async_engine(settings.database_url)
    try:
        async with engine.connect() as conn:
            return int((await conn.execute(select(func.count()).select_from(Report))).scalar_one())
    finally:
        await engine.dispose()


def _final_form(page_text: str) -> dict[str, str]:
    return {"csrf_token": _csrf(page_text), "step": str(_step(page_text)), "action": "next"}


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("field", "value", "back_to", "message"),
    [
        ("description", "abcdef", 4, "at least 10"),
        ("description", "x" * 10001, 4, "10,000"),
        ("description", "   short   ", 4, "at least 10"),
        ("category", "no_such_category", 3, "Please select a category"),
        ("submission_mode", "public", 1, "submission mode"),
    ],
    ids=["short", "too-long", "short-after-strip", "unknown-category", "unknown-mode"],
)
async def test_review_revalidates_the_draft_before_creating_a_report(
    client: AsyncClient, field: str, value: str, back_to: int, message: str
) -> None:
    await _walk_to_review(client)
    draft = await _draft(client)
    draft[field] = value
    await _set_draft(client, draft)
    before = await _report_count()

    resp = await _post(client)  # final submit on the review step
    assert resp.status_code == 303
    page = (await client.get("/submit")).text
    assert _CASE_RE.search(page) is None
    assert message in page
    assert (await _draft(client))["step"] == back_to
    assert await _report_count() == before


@pytest.mark.asyncio
async def test_location_deactivated_after_its_step_returns_to_the_location_step(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    import uuid

    from app.models.location import Location

    chosen = Location(id=uuid.uuid4(), name="Closing site", code=f"C{uuid.uuid4().hex[:5]}")
    other = Location(id=uuid.uuid4(), name="Open site", code=f"O{uuid.uuid4().hex[:5]}")
    db_session.add_all([chosen, other])
    await db_session.commit()
    try:
        await _post(client, submission_mode="anonymous")
        await _post(client, location_id=str(chosen.id))
        await _post(client, category="financial_fraud")
        await _post(client, description="A description long enough to pass.")
        await _upload(client)
        chosen.is_active = False
        await db_session.commit()

        resp = await _post(client)
        assert resp.status_code == 303
        page = (await client.get("/submit")).text
        assert _step(page) == 2
        assert "location is not valid" in page
        assert _CASE_RE.search(page) is None
    finally:
        await db_session.delete(chosen)
        await db_session.delete(other)
        await db_session.commit()


@pytest.mark.asyncio
async def test_confidential_mode_switched_off_returns_to_the_mode_step(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.config import settings

    await _post(client, submission_mode="confidential", confidential_name="Jane Roe")
    if _step((await client.get("/submit")).text) == 2:
        await _post(client, location_id="")
    await _post(client, category="financial_fraud")
    await _post(client, description="A description long enough to pass.")
    await _upload(client)
    monkeypatch.setattr(settings, "submission_mode_enabled", False)

    resp = await _post(client)
    assert resp.status_code == 303
    page = (await client.get("/submit")).text
    assert _step(page) == 1
    assert "submission mode" in page
    assert _CASE_RE.search(page) is None


def _slow_create(monkeypatch: pytest.MonkeyPatch, delay: float) -> None:
    import asyncio

    from app.services import report as report_service

    real_create = report_service.create_report

    async def _slow(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        await asyncio.sleep(delay)
        return await real_create(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(report_service, "create_report", _slow)


@pytest.mark.asyncio
async def test_concurrent_final_submits_create_one_report_and_both_show_the_pin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    _slow_create(monkeypatch, 0.3)
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    before = await _report_count()

    first, second = await asyncio.gather(
        client.post("/submit", data=data), client.post("/submit", data=data)
    )
    assert await _report_count() == before + 1
    shown = []
    for resp in (first, second):
        case, pin = _CASE_RE.search(resp.text), _PIN_RE.search(resp.text)
        assert case and pin, "every click must show the case number and PIN"
        shown.append((case.group(0), pin.group(0)))
    assert shown[0] == shown[1]


@pytest.mark.asyncio
async def test_second_click_after_the_draft_was_taken_shows_the_same_pin(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's P4: the second POST arrives while the first is still creating."""
    import asyncio

    import app.api.reports as reports
    from app.redis_client import get_redis

    _slow_create(monkeypatch, 1.0)
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    before = await _report_count()

    first = asyncio.create_task(client.post("/submit", data=data))
    await asyncio.sleep(0.3)  # the first request holds the draft now
    session_id = client.cookies.get("ow-submission-session")
    assert session_id
    second = await client.post("/submit", data=data)
    first_resp = await first

    assert await _report_count() == before + 1
    pin = _PIN_RE.search(first_resp.text)
    assert pin
    assert pin.group(0) in second.text
    redis = await get_redis()
    assert not await redis.exists(reports._result_key(session_id))  # read once, then gone


@pytest.mark.asyncio
async def test_the_result_is_kept_120_seconds_for_a_second_click(client: AsyncClient) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    session_id = client.cookies.get("ow-submission-session")
    assert session_id
    resp = await _post(client)
    assert resp.status_code == 200
    redis = await get_redis()
    ttl = await redis.ttl(reports._result_key(session_id))
    assert 0 < ttl <= 120
    stored = await redis.get(reports._result_key(session_id))
    assert _PIN_RE.search(resp.text).group(0) not in stored  # type: ignore[union-attr]
    assert not await redis.exists(reports._pending_key(session_id))


@pytest.mark.asyncio
async def test_second_click_without_a_result_says_where_the_pin_was_shown(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    monkeypatch.setattr(reports, "_RESULT_WAIT_SECONDS", 0.3)
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    session_id = client.cookies.get("ow-submission-session")
    assert session_id
    redis = await get_redis()
    # A first click that took the draft and has not finished within the wait.
    await redis.delete(reports._submission_key(session_id))
    await redis.set(reports._pending_key(session_id), "1", ex=30)

    resp = await client.post("/submit", data=data)
    assert resp.status_code == 200
    assert "Report already submitted" in resp.text
    assert _PIN_RE.search(resp.text) is None
    assert 'name="step"' not in resp.text  # not an empty wizard step 1


@pytest.mark.asyncio
async def test_losing_claim_waits_for_the_other_request_in_the_review_branch(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The draft was loaded, but another request took it before this one's GETDEL."""
    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    session_id = client.cookies.get("ow-submission-session")
    assert session_id
    redis = await get_redis()
    result = {"case_number": "OW-2026-12345", "pin": str(__import__("uuid").uuid4()),
              "attachments": []}
    token = reports._draft_fernet(session_id).encrypt(__import__("json").dumps(result).encode())

    real_eval = redis.eval

    async def _taken(*args: object) -> None:
        await redis.delete(reports._submission_key(session_id))
        await redis.set(reports._result_key(session_id), token, ex=120)
        return None

    monkeypatch.setattr(redis, "eval", _taken)
    resp = await client.post("/submit", data=data)
    monkeypatch.setattr(redis, "eval", real_eval)
    assert "OW-2026-12345" in resp.text
    assert result["pin"] in resp.text


@pytest.mark.asyncio
async def test_losing_claim_after_a_failed_first_submit_returns_to_the_wizard(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.redis_client import get_redis

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    redis = await get_redis()

    async def _gave_it_back(*args: object) -> None:
        return None  # the other request failed and restored the draft

    monkeypatch.setattr(redis, "eval", _gave_it_back)
    resp = await client.post("/submit", data=data, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/submit"


@pytest.mark.asyncio
async def test_failed_create_restores_the_draft_for_a_retry(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.services import report as report_service

    real_create = report_service.create_report
    calls = 0

    async def _flaky_create(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        nonlocal calls
        calls += 1
        if calls == 1:
            raise RuntimeError("database went away")
        return await real_create(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(report_service, "create_report", _flaky_create)
    await _walk_to_review(client)
    with pytest.raises(RuntimeError):
        await _post(client)
    retry = await _post(client)
    assert retry.status_code == 200
    assert _CASE_RE.search(retry.text)


@pytest.mark.asyncio
async def test_failed_attachment_store_leaves_no_report_and_restores_the_draft(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.services.attachment as attachment

    await _walk_to_attachments(client)
    await _upload(client, ("evidence.txt", b"evidence for the report"))
    before = await _report_count()

    real_store = attachment.create_attachments

    async def _broken(*args: object, **kwargs: object) -> None:
        raise RuntimeError("storage backend down")

    monkeypatch.setattr(attachment, "create_attachments", _broken)
    with pytest.raises(RuntimeError):
        await _post(client)
    assert await _report_count() == before  # rolled back with the attachments
    draft = await _draft(client)
    assert draft["step"] == 6
    assert draft["file_meta"]

    monkeypatch.setattr(attachment, "create_attachments", real_store)
    retry = await _post(client)
    assert _CASE_RE.search(retry.text)
    assert await _report_count() == before + 1


@pytest.mark.asyncio
async def test_exception_after_the_commit_never_allows_a_second_report(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's P5: the report is committed, then the request fails."""
    import app.api.reports as reports

    await _walk_to_review(client)
    before = await _report_count()

    def _boom(*args: object) -> None:
        raise RuntimeError("client went away")

    monkeypatch.setattr(reports, "_success_page", _boom)
    with pytest.raises(RuntimeError):
        await _post(client)
    monkeypatch.undo()
    # A retry finds no draft: it can only show the one report's stored result.
    page = await client.get("/submit")
    retry = await client.post("/submit", data={"csrf_token": _csrf(page.text), "step": "6"})
    assert retry.status_code == 200
    assert await _report_count() == before + 1
