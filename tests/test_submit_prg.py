"""Submission wizard: Post/Redirect/Get and the stale-step guard (#94)."""

from __future__ import annotations

import re

import pytest
from httpx import AsyncClient, Response


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
