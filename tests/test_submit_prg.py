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
