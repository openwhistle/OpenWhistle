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


async def _session_id(client: AsyncClient) -> str:
    session_id = client.cookies.get("ow-submission-session")
    assert session_id
    return session_id


@pytest.mark.asyncio
async def test_second_click_without_a_result_says_it_is_still_processing(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    monkeypatch.setattr(reports, "_RESULT_WAIT_SECONDS", 0.3)
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    session_id = await _session_id(client)
    redis = await get_redis()
    # A first click that claimed the draft and has not finished within the wait.
    assert await reports._claim_draft(redis, session_id)

    resp = await client.post("/submit", data=data)
    assert resp.status_code == 200
    assert "still being processed" in resp.text
    assert "received" not in resp.text.lower()  # no case number is known
    assert _PIN_RE.search(resp.text) is None
    assert 'href="/submit"' in resp.text  # "Check again"
    assert "ow-submission-session" not in resp.headers.get("set-cookie", "")  # cookie kept


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lang", "title"),
    [
        ("en", "Your report is still being processed"),
        ("de", "Ihre Meldung wird noch verarbeitet"),
        ("fr", "Votre signalement est encore en cours de traitement"),
        ("pt-br", "Sua denúncia ainda está sendo processada"),
    ],
)
async def test_the_processing_page_is_translated(
    client: AsyncClient, lang: str, title: str
) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    session_id = await _session_id(client)
    assert await reports._claim_draft(await get_redis(), session_id)
    client.cookies.set("ow-lang", lang)
    page = (await client.get("/submit")).text
    assert title in page


@pytest.mark.asyncio
async def test_worker_dying_after_the_claim_gives_the_draft_back_when_pending_expires(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis
    from app.services import report as report_service

    class _WorkerKilled(BaseException):
        pass

    async def _die(*args: object, **kwargs: object) -> None:
        raise _WorkerKilled  # the process is gone: no cleanup runs

    async def _no_cleanup(*args: object) -> None:
        return None

    monkeypatch.setattr(report_service, "create_report", _die)
    monkeypatch.setattr(reports, "_give_back_draft", _no_cleanup)
    await _walk_to_attachments(client)
    await _upload(client, ("evidence.txt", b"evidence that must survive"))
    session_id = await _session_id(client)
    before = await _report_count()
    with pytest.raises(_WorkerKilled):
        await _post(client)
    monkeypatch.undo()

    redis = await get_redis()
    assert not await redis.exists(reports._submission_key(session_id))
    assert await redis.exists(reports._claimed_key(session_id))
    # The claimed copy keeps the draft's own TTL, so it outlives "pending".
    assert await redis.ttl(reports._claimed_key(session_id)) > reports._PENDING_TTL
    # Still pending: the honest page, not a receipt.
    assert "still being processed" in (await client.get("/submit")).text

    await redis.delete(reports._pending_key(session_id))  # the pending TTL ran out
    page = (await client.get("/submit")).text
    assert _step(page) == 6  # back at review, draft intact
    assert "evidence.txt" in page
    done = await _post(client)
    assert _CASE_RE.search(done.text)
    assert await _report_count() == before + 1


@pytest.mark.asyncio
async def test_slow_winner_that_fails_leaves_the_draft_reachable(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import app.api.reports as reports
    from app.services import report as report_service

    async def _slow_fail(*args: object, **kwargs: object) -> None:
        await asyncio.sleep(0.8)
        raise RuntimeError("database went away")

    monkeypatch.setattr(reports, "_RESULT_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(report_service, "create_report", _slow_fail)
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)

    first = asyncio.create_task(client.post("/submit", data=data))
    await asyncio.sleep(0.2)
    second = await client.post("/submit", data=data)
    assert "still being processed" in second.text
    assert "was NOT sent" in (await first).text  # back at review
    monkeypatch.undo()

    page = (await client.get("/submit")).text  # "Check again"
    assert _step(page) == 6
    assert _CASE_RE.search((await _post(client)).text)


@pytest.mark.asyncio
async def test_slow_winner_that_succeeds_shows_the_pin_on_check_again(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    import app.api.reports as reports

    monkeypatch.setattr(reports, "_RESULT_WAIT_SECONDS", 0.2)
    _slow_create(monkeypatch, 0.8)
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)

    first = asyncio.create_task(client.post("/submit", data=data))
    await asyncio.sleep(0.2)
    second = await client.post("/submit", data=data)
    assert "still being processed" in second.text
    session_id = await _session_id(client)
    first_resp = await first
    pin = _PIN_RE.search(first_resp.text)
    assert pin
    # The browser never processed the first response (it shows the last click),
    # so it still holds the draft cookie that response would have cleared.
    client.cookies.clear()
    client.cookies.set("ow-submission-session", session_id)

    again = await client.get("/submit")
    assert pin.group(0) in again.text


@pytest.mark.asyncio
async def test_losing_claim_waits_for_the_other_request_in_the_review_branch(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The draft was loaded, but another request claimed it first."""
    import json
    import uuid

    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    session_id = await _session_id(client)
    redis = await get_redis()
    result = {"case_number": "OW-2026-12345", "pin": str(uuid.uuid4()), "attachments": []}
    token = reports._draft_fernet(session_id).encrypt(json.dumps(result).encode())

    async def _taken(*args: object) -> None:
        await redis.delete(reports._submission_key(session_id))
        await redis.set(reports._result_key(session_id), token, ex=120)
        return None

    monkeypatch.setattr(reports, "_claim_draft", _taken)
    resp = await client.post("/submit", data=data)
    assert "OW-2026-12345" in resp.text
    assert result["pin"] in resp.text


@pytest.mark.asyncio
async def test_losing_claim_after_a_failed_first_submit_returns_to_the_wizard(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.reports as reports

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)

    async def _gave_it_back(*args: object) -> None:
        return None  # the other request failed and restored the draft

    monkeypatch.setattr(reports, "_claim_draft", _gave_it_back)
    resp = await client.post("/submit", data=data, follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/submit"


@pytest.mark.asyncio
async def test_waiting_click_holds_no_database_transaction(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.responses import HTMLResponse

    import app.api.reports as reports
    from app.database import get_db
    from app.main import app

    sessions: list[AsyncSession] = []
    inner = app.dependency_overrides[get_db]

    async def _tracked():  # type: ignore[no-untyped-def]
        async for session in inner():
            sessions.append(session)
            yield session

    in_transaction: list[bool] = []

    async def _spy(*args: object, **kwargs: object) -> HTMLResponse:
        in_transaction.append(sessions[-1].in_transaction())
        return HTMLResponse("waited")

    async def _taken(*args: object) -> None:
        return None

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    monkeypatch.setitem(app.dependency_overrides, get_db, _tracked)
    monkeypatch.setattr(reports, "_claim_draft", _taken)
    monkeypatch.setattr(reports, "_await_other_submit", _spy)
    await client.post("/submit", data=data)
    assert in_transaction == [False]


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
    assert (await _post(client)).status_code == 303
    assert "was NOT sent" in (await client.get("/submit")).text
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
    assert (await _post(client)).status_code == 303
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
    """The review's P5: the report is committed, then the request fails. Retrying
    the same review form in the same session shows that report's stored result."""
    import app.api.reports as reports

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    before = await _report_count()

    def _boom(*args: object) -> None:
        raise RuntimeError("client went away")

    monkeypatch.setattr(reports, "_success_page", _boom)
    with pytest.raises(RuntimeError):
        await client.post("/submit", data=data)
    monkeypatch.undo()

    retry = await client.post("/submit", data=data)
    assert _CASE_RE.search(retry.text)
    assert _PIN_RE.search(retry.text)
    assert await _report_count() == before + 1


@pytest.mark.asyncio
async def test_commit_whose_reply_is_lost_counts_as_done(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's N6 probe: the commit goes through, then CancelledError."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession as _Session

    real_commit = _Session.commit
    calls = 0

    async def _commit_then_cancel(self: _Session) -> None:
        nonlocal calls
        await real_commit(self)
        calls += 1
        if calls == 1:
            raise asyncio.CancelledError

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    before = await _report_count()
    monkeypatch.setattr(_Session, "commit", _commit_then_cancel)
    with pytest.raises(asyncio.CancelledError):
        await client.post("/submit", data=data)
    monkeypatch.undo()

    retry = await client.post("/submit", data=data)
    case = _CASE_RE.search(retry.text)
    assert case
    assert _PIN_RE.search(retry.text)
    assert await _report_count() == before + 1


@pytest.mark.asyncio
@pytest.mark.parametrize("fault", ["reset", "timeout", "killed"])
async def test_a_commit_failing_without_a_report_is_pending_not_not_sent(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, fault: str
) -> None:
    """N-R5-2: once the COMMIT is issued, a lookup finding no report proves
    nothing (the commit may still land): the claim is kept and the reporter
    is told it is being processed, never "NOT sent"."""
    import asyncio

    from sqlalchemy.ext.asyncio import AsyncSession as _Session

    import app.api.reports as reports
    from app.redis_client import get_redis

    class _WorkerKilled(BaseException):
        pass

    async def _failing_commit(self: _Session) -> None:
        if fault == "timeout":
            await asyncio.sleep(5)  # the submit's own timeout fires inside the COMMIT
        if fault == "killed":
            raise _WorkerKilled  # nobody to answer: re-raised, the claim kept
        raise ConnectionResetError("reset during COMMIT")

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    session_id = await _session_id(client)
    before = await _report_count()
    monkeypatch.setattr(reports, "_SUBMIT_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(_Session, "commit", _failing_commit)
    if fault == "killed":
        with pytest.raises(_WorkerKilled):
            await client.post("/submit", data=data, follow_redirects=False)
        resp = await client.get("/submit")
    else:
        resp = await client.post("/submit", data=data, follow_redirects=False)
    monkeypatch.undo()

    assert resp.status_code == 200
    assert "still being processed" in resp.text
    assert "answers are kept" in resp.text
    assert "NOT sent" not in resp.text
    redis = await get_redis()
    assert await redis.exists(reports._claimed_key(session_id))  # the claim is kept
    assert not await redis.exists(reports._submission_key(session_id))

    await redis.delete(reports._pending_key(session_id))  # the pending TTL ran out
    assert _step((await client.get("/submit")).text) == 6  # no report: given back
    assert await _report_count() == before


# ── One draft, one report: the primary key decides (X6 round 4) ─────


@pytest.mark.asyncio
async def test_a_submit_outliving_pending_still_yields_one_report(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's R1 probe: pending expires while the first submit still runs;
    the draft comes back and is submitted again."""
    import asyncio

    import app.api.reports as reports

    monkeypatch.setattr(reports, "_PENDING_TTL", 1)
    _slow_create(monkeypatch, 3.0)
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    before = await _report_count()

    first = asyncio.create_task(client.post("/submit", data=data))
    await asyncio.sleep(1.5)
    monkeypatch.undo()  # the second submit is fast
    monkeypatch.setattr(reports, "_PENDING_TTL", 1)
    page = (await client.get("/submit")).text
    assert _step(page) == 6  # given back: the report did not exist yet
    second = await _post(client)
    first_resp = await first

    assert await _report_count() == before + 1
    case = _CASE_RE.search(second.text)
    assert case and _PIN_RE.search(second.text)
    assert case.group(0) in first_resp.text  # the late one names the same report


@pytest.mark.asyncio
async def test_a_second_insert_waits_for_the_first_and_yields_one_report(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The first submit has inserted but not committed when the draft comes back."""
    import asyncio

    import app.api.reports as reports
    import app.services.attachment as attachment

    real_store = attachment.create_attachments
    calls = 0

    async def _slow_store(*args: object, **kwargs: object) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            await asyncio.sleep(3.0)
        await real_store(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reports, "_PENDING_TTL", 1)
    monkeypatch.setattr(attachment, "create_attachments", _slow_store)
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    before = await _report_count()

    first = asyncio.create_task(client.post("/submit", data=data))
    await asyncio.sleep(1.5)
    assert _step((await client.get("/submit")).text) == 6
    second = await _post(client)  # blocks on the uncommitted primary key
    first_resp = await first

    assert await _report_count() == before + 1
    case = _CASE_RE.search(first_resp.text)
    assert case and _PIN_RE.search(first_resp.text)
    assert case.group(0) in second.text


@pytest.mark.asyncio
async def test_a_lost_result_write_after_the_commit_never_reopens_the_draft(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's R2 probe: the commit went through, storing the result failed."""
    import app.api.reports as reports
    from app.redis_client import get_redis

    real_finish = reports._finish_claim

    async def _fail_once(redis: object, session_id: str, nonce: str, result: object) -> None:
        monkeypatch.setattr(reports, "_finish_claim", real_finish)
        raise ConnectionError("redis went away")

    monkeypatch.setattr(reports, "_finish_claim", _fail_once)
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    session_id = await _session_id(client)
    before = await _report_count()
    first = await client.post("/submit", data=data)
    case = _CASE_RE.search(first.text)
    assert case and _PIN_RE.search(first.text)

    redis = await get_redis()
    assert await redis.exists(reports._claimed_key(session_id))
    await redis.set(reports._report_id_key(session_id), "left by a pre-v1.6.0 load")
    await redis.delete(reports._pending_key(session_id))  # the pending TTL ran out
    client.cookies.set("ow-submission-session", session_id)  # the browser kept it
    page = (await client.get("/submit")).text
    assert not await redis.exists(reports._report_id_key(session_id))  # spent with the draft
    assert case.group(0) in page
    assert "shown only once" in page
    assert _PIN_RE.search(page) is None
    assert 'name="step"' not in page
    client.cookies.set("ow-submission-session", session_id)
    again = await client.post("/submit", data=data)  # the stale review form
    assert await _report_count() == before + 1
    assert _step(again.text) == 1  # the spent draft is gone: a fresh wizard


@pytest.mark.asyncio
async def test_commit_and_lookup_both_failing_yield_one_report(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The double fault: the commit's reply is lost and so is the lookup's."""
    from sqlalchemy.ext.asyncio import AsyncSession as _Session

    import app.api.reports as reports
    from app.redis_client import get_redis

    real_commit = _Session.commit

    async def _commit_then_reset(self: _Session) -> None:
        await real_commit(self)
        raise ConnectionResetError("reply lost")

    async def _lookup_down(*args: object) -> None:
        raise ConnectionResetError("database unreachable")

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    session_id = await _session_id(client)
    before = await _report_count()
    monkeypatch.setattr(_Session, "commit", _commit_then_reset)
    monkeypatch.setattr(reports, "_committed_case_number", _lookup_down)
    unknown = await client.post("/submit", data=data)
    monkeypatch.undo()
    assert "still being processed" in unknown.text  # the outcome is not known yet
    assert "answers are kept" in unknown.text

    redis = await get_redis()
    await redis.delete(reports._pending_key(session_id))  # the pending TTL ran out
    page = (await client.get("/submit")).text
    assert _CASE_RE.search(page)
    assert 'name="step"' not in page
    await client.post("/submit", data=data)
    assert await _report_count() == before + 1


@pytest.mark.asyncio
async def test_a_draft_back_after_its_report_was_committed_makes_no_second_report(
    client: AsyncClient,
) -> None:
    """Whatever brings a spent draft back, the primary key refuses a second report."""
    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    page = (await client.get("/submit")).text
    data = _final_form(page)
    session_id = await _session_id(client)
    redis = await get_redis()
    spent = await redis.get(reports._submission_key(session_id))
    before = await _report_count()
    first = await client.post("/submit", data=data)
    case = _CASE_RE.search(first.text)
    assert case

    await redis.set(reports._submission_key(session_id), spent, ex=600)
    client.cookies.set("ow-submission-session", session_id)
    again = await client.post("/submit", data=data)
    assert await _report_count() == before + 1
    assert case.group(0) in again.text
    assert not await redis.exists(reports._submission_key(session_id))


@pytest.mark.asyncio
async def test_a_late_submit_never_touches_a_newer_claim(client: AsyncClient) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    await client.get("/submit")
    session_id = await _session_id(client)
    redis = await get_redis()
    old = await reports._claim_draft(redis, session_id)
    assert old
    await redis.delete(reports._pending_key(session_id))  # the old claim outlived pending
    assert _step((await client.get("/submit")).text) == 6  # recovered
    new = await reports._claim_draft(redis, session_id)
    assert new

    await reports._give_back_draft(redis, session_id, old[0], old[1])
    await reports._finish_claim(redis, session_id, old[1], {"case_number": "x"})
    assert await redis.get(reports._pending_key(session_id)) == new[1]
    assert await redis.get(reports._claimed_key(session_id)) == new[0]
    assert not await redis.exists(reports._submission_key(session_id))


@pytest.mark.asyncio
async def test_two_posts_racing_the_recovery_stay_on_the_same_session(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The review's R3 probe: both load an empty state, only one recovers."""
    import asyncio

    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    page = (await client.get("/submit")).text
    session_id = await _session_id(client)
    redis = await get_redis()
    assert await reports._claim_draft(redis, session_id)
    await redis.delete(reports._pending_key(session_id))

    real_load = reports._load_submission
    barrier = asyncio.Barrier(2)
    first_loads = 0

    async def _load_together(redis_: object, sid: str) -> dict[str, object]:
        nonlocal first_loads
        state = await real_load(redis_, sid)  # type: ignore[arg-type]
        if first_loads < 2:
            first_loads += 1
            await barrier.wait()
        return state

    monkeypatch.setattr(reports, "_load_submission", _load_together)
    back = {"csrf_token": _csrf(page), "step": "6", "action": "back"}
    responses = await asyncio.gather(
        client.post("/submit", data=back, follow_redirects=False),
        client.post("/submit", data=back, follow_redirects=False),
    )
    monkeypatch.undo()
    for resp in responses:
        assert resp.status_code == 303
        assert f"ow-submission-session={session_id}" in resp.headers["set-cookie"]
    client.cookies.set("ow-submission-session", session_id)
    assert _step((await client.get("/submit")).text) in (4, 5)  # one or two steps back


@pytest.mark.asyncio
async def test_claim_to_commit_is_bounded_well_under_pending(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    import asyncio

    from sqlalchemy import text

    import app.api.reports as reports
    from app.services import report as report_service

    assert reports._SUBMIT_TIMEOUT_SECONDS * 3 < reports._PENDING_TTL
    real_create = report_service.create_report
    seen: list[str] = []

    async def _hang(db: AsyncSession, **kwargs: object):  # type: ignore[no-untyped-def]
        seen.append(str((await db.execute(text("SHOW statement_timeout"))).scalar_one()))
        await asyncio.sleep(5)
        return await real_create(db, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(reports, "_SUBMIT_TIMEOUT_SECONDS", 0.5)
    monkeypatch.setattr(report_service, "create_report", _hang)
    await _walk_to_review(client)
    before = await _report_count()
    assert (await _post(client)).status_code == 303
    monkeypatch.undo()

    assert seen == ["500ms"]
    assert await _report_count() == before
    page = (await client.get("/submit")).text
    assert _step(page) == 6  # given back
    assert "Your report was NOT sent." in page  # no COMMIT was issued


@pytest.mark.asyncio
async def test_the_processing_page_promises_kept_answers_only_while_they_are(
    client: AsyncClient,
) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    session_id = await _session_id(client)
    redis = await get_redis()
    assert await reports._claim_draft(redis, session_id)
    assert "answers are kept" in (await client.get("/submit")).text

    await redis.delete(reports._claimed_key(session_id))  # the draft's TTL ran out
    page = (await client.get("/submit")).text
    assert "still being processed" in page
    assert "answers are kept" not in page


@pytest.mark.asyncio
async def test_a_draft_without_a_report_id_gets_one_before_it_is_submitted(
    client: AsyncClient,
) -> None:
    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    import json

    import app.api.reports as reports
    from app.redis_client import get_redis

    draft = await _draft(client)
    draft.pop("report_id")
    session_id = await _session_id(client)
    await (await get_redis()).set(  # saved before this version
        reports._submission_key(session_id),
        reports._draft_fernet(session_id).encrypt(json.dumps(draft).encode()),
        ex=600,
    )
    before = await _report_count()

    resp = await client.post("/submit", data=data, follow_redirects=False)
    assert resp.status_code == 303
    assert await _report_count() == before
    assert _step((await client.get("/submit")).text) == 6
    assert (await _draft(client))["report_id"]
    assert _CASE_RE.search((await _post(client)).text)


@pytest.mark.asyncio
async def test_the_report_id_is_fixed_at_the_first_save_and_kept_by_every_step(
    client: AsyncClient,
) -> None:
    await _post(client, submission_mode="anonymous")
    report_id = (await _draft(client))["report_id"]
    if _step((await client.get("/submit")).text) == 2:
        await _post(client, location_id="")
    await _post(client, category="financial_fraud")
    await _post(client, description="A detailed description of the incident.")
    await _upload(client)
    await _back(client)
    await _upload(client)
    await client.get("/submit")
    assert (await _draft(client))["report_id"] == report_id


async def _strip_report_id(client: AsyncClient) -> None:
    """Rewrite the draft as a pre-v1.6.0 one: no report id."""
    import json

    import app.api.reports as reports
    from app.redis_client import get_redis

    draft = await _draft(client)
    draft.pop("report_id")
    session_id = await _session_id(client)
    await (await get_redis()).set(
        reports._submission_key(session_id),
        reports._draft_fernet(session_id).encrypt(json.dumps(draft).encode()),
        ex=600,
    )


@pytest.mark.asyncio
async def test_a_stale_save_of_a_pre_v1_6_draft_yields_one_report(client: AsyncClient) -> None:
    """The review's X6-R4-A probe: a request loads an id-less draft and stalls
    while the reporter submits; its late save must not give the draft a new id."""
    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    data = _final_form((await client.get("/submit")).text)
    await _strip_report_id(client)
    session_id = await _session_id(client)
    redis = await get_redis()
    before = await _report_count()

    stalled = await reports._load_submission(redis, session_id)  # request X, stalled
    assert (await client.post("/submit", data=data, follow_redirects=False)).status_code == 303
    assert _CASE_RE.search((await _post(client)).text)  # report A
    await reports._save_submission(redis, session_id, stalled)  # X resumes
    client.cookies.set("ow-submission-session", session_id)  # X's redirect sets it again

    await _post(client)  # the draft is back at review; submitting it again
    assert await _report_count() == before + 1
    assert not await redis.exists(reports._submission_key(session_id) + ":report-id")


@pytest.mark.asyncio
async def test_a_pre_v1_6_draft_spent_while_loading_is_not_given_an_id(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A loader that read the id-less draft just before its report finished must
    not mint a fresh id for it: the draft is gone, so the state is empty."""
    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    await _strip_report_id(client)
    session_id = await _session_id(client)
    redis = await get_redis()
    stale_token = await redis.get(reports._submission_key(session_id))
    await client.get("/submit")  # assigns the id
    assert _CASE_RE.search((await _post(client)).text)  # spent: draft and side key deleted

    real_get = redis.get
    stale_reads = [stale_token]  # the one read made just before the report finished

    async def _stale_get(key: str) -> str | None:
        if key == reports._submission_key(session_id) and stale_reads:
            return stale_reads.pop()
        return await real_get(key)

    monkeypatch.setattr(redis, "get", _stale_get, raising=False)
    try:
        assert await reports._load_submission(redis, session_id) == {}
    finally:
        monkeypatch.undo()
    assert not await redis.exists(reports._submission_key(session_id) + ":report-id")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("lang", "message"),
    [
        ("en", "Your report was NOT sent."),
        ("de", "Ihre Meldung wurde NICHT gesendet."),
        ("fr", "Votre signalement n&#39;a PAS été envoyé."),
        ("pt-br", "Sua denúncia NÃO foi enviada."),
    ],
)
async def test_a_submit_failing_before_its_commit_says_not_sent_and_keeps_the_answers(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch, lang: str, message: str
) -> None:
    """The review's X6-R4-B: no bare 500, but the review step with a message."""
    from app.services import report as report_service

    async def _down(*args: object, **kwargs: object) -> None:
        raise ConnectionResetError("database went away")

    client.cookies.set("ow-lang", lang)
    await _walk_to_attachments(client)
    await _upload(client, ("evidence.txt", b"evidence that must survive"))
    before = await _report_count()
    monkeypatch.setattr(report_service, "create_report", _down)
    resp = await _post(client)
    monkeypatch.undo()

    assert resp.status_code == 303
    page = (await client.get("/submit")).text
    assert message in page
    assert _step(page) == 6
    assert "evidence.txt" in page
    assert (await _draft(client))["description"] == "A description long enough to pass."
    assert await _report_count() == before


@pytest.mark.asyncio
async def test_a_failed_late_submit_leaves_a_newer_claim_alone(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A submit that lost its draft to a newer claim and then fails must not
    put the draft back beside that claim: it waits for the newer one."""
    import app.api.reports as reports
    from app.redis_client import get_redis
    from app.services import report as report_service

    await _walk_to_review(client)
    session_id = await _session_id(client)
    redis = await get_redis()

    async def _overtaken_then_down(*args: object, **kwargs: object) -> None:
        await redis.set(reports._pending_key(session_id), "a-newer-claim", ex=60)
        raise ConnectionResetError("database went away")

    monkeypatch.setattr(reports, "_RESULT_WAIT_SECONDS", 0.2)
    monkeypatch.setattr(report_service, "create_report", _overtaken_then_down)
    resp = await _post(client)
    monkeypatch.undo()

    assert "still being processed" in resp.text
    assert not await redis.exists(reports._submission_key(session_id))
    assert await redis.exists(reports._claimed_key(session_id))


@pytest.mark.asyncio
async def test_start_over_deletes_a_pre_v1_6_drafts_report_id_too(client: AsyncClient) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    await _strip_report_id(client)
    session_id = await _session_id(client)
    page = (await client.get("/submit")).text  # the load assigns the id
    redis = await get_redis()
    assert await redis.exists(reports._report_id_key(session_id))

    await client.post("/submit/restart", data={"csrf_token": _csrf(page)})
    assert not await redis.exists(
        reports._submission_key(session_id), reports._report_id_key(session_id)
    )


@pytest.mark.asyncio
async def test_a_draft_re_saved_without_an_id_on_every_load_is_given_up_after_3_attempts(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """N-R5-1: the retry is bounded; the draft then counts as expired."""
    import json

    import app.api.reports as reports
    from app.redis_client import get_redis

    await _walk_to_review(client)
    await _strip_report_id(client)
    session_id = await _session_id(client)
    key = reports._submission_key(session_id)
    redis = await get_redis()
    idless = reports._draft_fernet(session_id).decrypt(await redis.get(key))
    real_get, real_eval = redis.get, redis.eval
    gets: list[str] = []

    async def _counting_get(k: str) -> object:
        if k == key:
            gets.append(k)
        return await real_get(k)

    async def _resave_then_eval(script: str, *args: object) -> object:
        if script == reports._ASSIGN_REPORT_ID:  # another writer between GET and EVAL
            await redis.set(key, reports._draft_fernet(session_id).encrypt(idless), ex=600)
        return await real_eval(script, *args)  # type: ignore[arg-type]

    monkeypatch.setattr(redis, "get", _counting_get, raising=False)
    monkeypatch.setattr(redis, "eval", _resave_then_eval, raising=False)
    try:
        assert await reports._load_submission(redis, session_id) == {}
    finally:
        monkeypatch.undo()
    assert len(gets) == 3
    assert "report_id" not in json.loads(idless)
    assert (await client.get("/submit")).status_code == 200  # the loop is healthy
