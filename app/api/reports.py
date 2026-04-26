"""Whistleblower-facing endpoints: submit (multi-step), status, reply."""

import json
import re
import secrets
import uuid
from typing import Any, cast
from urllib.parse import urlsplit

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    File,
    Form,
    HTTPException,
    Request,
    UploadFile,
    status,
)
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.csrf import validate_csrf
from app.database import get_db
from app.i18n import get_lang
from app.models.report import SubmissionMode
from app.redis_client import get_redis
from app.services import rate_limit as rl
from app.services import report as report_service
from app.services.categories import get_active_categories
from app.services.locations import get_active_locations, get_location_by_id
from app.templating import render

router = APIRouter()

# Allowlist pattern for whistleblower session keys (URL-safe base64, 1–86 chars).
_SESSION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,86}$")

# Submission session TTL — 2 hours
_SUBMISSION_TTL = 7200

_NEXT_ALLOWLIST: dict[str, str] = {
    "/submit": "/submit",
    "/status": "/status",
    "/admin/login": "/admin/login",
    "/admin/dashboard": "/admin/dashboard",
    "/setup": "/setup",
}

# Steps: mode → location (conditional) → category → description → attachments → review
_STEP_MODE = 1
_STEP_LOCATION = 2
_STEP_CATEGORY = 3
_STEP_DESCRIPTION = 4
_STEP_ATTACHMENTS = 5
_STEP_REVIEW = 6


def _submission_key(session_id: str) -> str:
    return f"submission-session:{session_id}"


async def _load_submission(redis: Redis, session_id: str) -> dict[str, Any]:
    raw = await redis.get(_submission_key(session_id))
    if not raw:
        return {}
    data = raw.decode() if isinstance(raw, bytes) else raw
    return cast(dict[str, Any], json.loads(data))


async def _save_submission(redis: Redis, session_id: str, state: dict[str, Any]) -> None:
    await redis.setex(_submission_key(session_id), _SUBMISSION_TTL, json.dumps(state))


async def _get_or_create_submission_session(
    request: Request, redis: Redis
) -> tuple[str, dict[str, Any]]:
    raw = request.cookies.get("ow-submission-session")
    session_id: str | None = raw if raw and _SESSION_KEY_RE.match(raw) else None
    if session_id:
        state = await _load_submission(redis, session_id)
        if state:
            return session_id, state
    session_id = secrets.token_urlsafe(32)
    return session_id, {}


def _set_submission_cookie(response: Response | RedirectResponse, session_id: str) -> None:
    response.set_cookie(
        "ow-submission-session",
        session_id,
        max_age=_SUBMISSION_TTL,
        httponly=True,
        samesite="lax",
        secure=not settings.demo_mode,
    )


def _clear_submission_cookie(response: Response | RedirectResponse) -> None:
    response.delete_cookie(
        "ow-submission-session", httponly=True, samesite="lax", secure=not settings.demo_mode
    )


def _compute_total_steps(has_locations: bool) -> int:
    return 6 if has_locations else 5


def _compute_step_label(step: int, has_locations: bool) -> int:
    """Return the display step number given logical step and whether locations exist."""
    if has_locations:
        return step
    # Without location step: steps 3-6 shift down by 1 for display
    if step >= _STEP_CATEGORY:
        return step - 1
    return step


@router.post("/set-language")
async def set_language(
    request: Request,
    lang: str = Form(...),
    next_url: str = Form("/submit", alias="next"),
) -> RedirectResponse:
    safe_lang = {"en": "en", "de": "de", "fr": "fr"}.get(lang, "en")
    parsed_path = urlsplit(next_url).path
    safe_url = _NEXT_ALLOWLIST.get(parsed_path)
    if safe_url is None:
        safe_url = "/admin/dashboard" if parsed_path.startswith("/admin/") else "/submit"
    response = RedirectResponse(safe_url, status_code=303)
    response.set_cookie(
        "ow-lang",
        safe_lang,
        max_age=31_536_000,
        httponly=False,
        samesite="lax",
        secure=not settings.demo_mode,
    )
    return response


@router.get("/health")
async def health(
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
) -> Response:
    from fastapi.responses import JSONResponse
    from sqlalchemy import text

    components: dict[str, str] = {}
    healthy = True

    try:
        await db.execute(text("SELECT 1"))
        components["database"] = "ok"
    except Exception:
        components["database"] = "error"
        healthy = False

    try:
        await redis.ping()  # type: ignore[misc]
        components["redis"] = "ok"
    except Exception:
        components["redis"] = "error"
        healthy = False

    body = {
        "status": "ok" if healthy else "degraded",
        "version": settings.app_version,
        "components": components,
    }
    return JSONResponse(body, status_code=200 if healthy else 503)


@router.get("/", response_class=HTMLResponse, response_model=None)
async def index(request: Request, db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    from sqlalchemy import select

    from app.models.setup import SetupStatus

    result = await db.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result.scalar_one_or_none()
    if setup is None or not setup.completed:
        return RedirectResponse("/setup", status_code=302)
    return RedirectResponse("/submit", status_code=302)


# ── Multi-step submission ──────────────────────────────────────────


@router.get("/submit", response_class=HTMLResponse)
async def submit_get(
    request: Request,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    session_id, state = await _get_or_create_submission_session(request, redis)

    locations = await get_active_locations(db)
    has_locations = len(locations) > 0
    total_steps = _compute_total_steps(has_locations)

    # Determine which step to show based on state
    current_step = state.get("step", _STEP_MODE)
    if not has_locations and current_step == _STEP_LOCATION:
        current_step = _STEP_CATEGORY
        state["step"] = current_step

    categories = await get_active_categories(db)

    ctx: dict[str, Any] = {
        "state": state,
        "step": current_step,
        "total_steps": total_steps,
        "has_locations": has_locations,
        "locations": locations,
        "categories": categories,
        "display_step": _compute_step_label(current_step, has_locations),
    }

    rendered = render(request, "submit.html", ctx)
    _set_submission_cookie(rendered, session_id)
    await _save_submission(redis, session_id, state)
    return rendered


@router.post("/submit", response_class=HTMLResponse)
async def submit_post(
    request: Request,
    background_tasks: BackgroundTasks,
    action: str = Form("next"),
    step: int = Form(1),
    # Step 1 — mode
    submission_mode: str = Form(""),
    confidential_name: str = Form(""),
    confidential_contact: str = Form(""),
    secure_email: str = Form(""),
    # Step 2 — location
    location_id: str = Form(""),
    # Step 3 — category
    category: str = Form(""),
    # Step 4 — description
    description: str = Form(""),
    # Step 5 — attachments handled separately below
    files: list[UploadFile] = File(default=[]),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> Response:
    raw_cookie = request.cookies.get("ow-submission-session")
    session_id: str = (
        raw_cookie
        if raw_cookie and _SESSION_KEY_RE.match(raw_cookie)
        else secrets.token_urlsafe(32)
    )
    state = await _load_submission(redis, session_id)

    locations = await get_active_locations(db)
    has_locations = len(locations) > 0
    total_steps = _compute_total_steps(has_locations)
    categories = await get_active_categories(db)
    valid_cat_slugs = {c.slug for c in categories}

    def _render_step(extra: dict[str, Any] | None = None) -> HTMLResponse:
        ctx: dict[str, Any] = {
            "state": state,
            "step": state.get("step", _STEP_MODE),
            "total_steps": total_steps,
            "has_locations": has_locations,
            "locations": locations,
            "categories": categories,
            "display_step": _compute_step_label(state.get("step", _STEP_MODE), has_locations),
        }
        if extra:
            ctx.update(extra)
        resp = render(request, "submit.html", ctx)
        _set_submission_cookie(resp, session_id)
        return resp

    if action == "back":
        current = state.get("step", _STEP_MODE)
        prev = current - 1
        if not has_locations and prev == _STEP_LOCATION:
            prev = _STEP_MODE
        state["step"] = max(_STEP_MODE, prev)
        await _save_submission(redis, session_id, state)
        return _render_step()

    # ── Step 1: mode selection ─────────────────────────────────────
    if step == _STEP_MODE:
        if submission_mode not in ("anonymous", "confidential"):
            state["step"] = _STEP_MODE
            await _save_submission(redis, session_id, state)
            return _render_step({"error": "mode_required"})

        state["submission_mode"] = submission_mode

        if submission_mode == "confidential":
            name_stripped = confidential_name.strip()
            contact_stripped = confidential_contact.strip()
            email_stripped = secure_email.strip()
            state["confidential_name"] = name_stripped
            state["confidential_contact"] = contact_stripped
            state["secure_email"] = email_stripped

        state["step"] = _STEP_LOCATION if has_locations else _STEP_CATEGORY
        await _save_submission(redis, session_id, state)
        return _render_step()

    # ── Step 2: location selection (conditional) ──────────────────
    if step == _STEP_LOCATION:
        if has_locations:
            loc_id_stripped = location_id.strip()
            if loc_id_stripped:
                try:
                    loc_uuid = uuid.UUID(loc_id_stripped)
                except ValueError:
                    state["step"] = _STEP_LOCATION
                    await _save_submission(redis, session_id, state)
                    return _render_step({"error": "invalid_location"})
                loc = await get_location_by_id(db, loc_uuid)
                if not loc or not loc.is_active:
                    state["step"] = _STEP_LOCATION
                    await _save_submission(redis, session_id, state)
                    return _render_step({"error": "invalid_location"})
                state["location_id"] = str(loc_uuid)
            else:
                state["location_id"] = None

        state["step"] = _STEP_CATEGORY
        await _save_submission(redis, session_id, state)
        return _render_step()

    # ── Step 3: category ──────────────────────────────────────────
    if step == _STEP_CATEGORY:
        if not category or category not in valid_cat_slugs:
            state["step"] = _STEP_CATEGORY
            await _save_submission(redis, session_id, state)
            return _render_step({"error": "category_required"})
        state["category"] = category
        state["step"] = _STEP_DESCRIPTION
        await _save_submission(redis, session_id, state)
        return _render_step()

    # ── Step 4: description ───────────────────────────────────────
    if step == _STEP_DESCRIPTION:
        desc_stripped = description.strip()
        if len(desc_stripped) < 10:
            state["step"] = _STEP_DESCRIPTION
            await _save_submission(redis, session_id, state)
            return _render_step({"error": "description_too_short"})
        if len(desc_stripped) > 10000:
            state["step"] = _STEP_DESCRIPTION
            await _save_submission(redis, session_id, state)
            return _render_step({"error": "description_too_long"})
        state["description"] = desc_stripped
        state["step"] = _STEP_ATTACHMENTS
        await _save_submission(redis, session_id, state)
        return _render_step()

    # ── Step 5: attachments ───────────────────────────────────────
    if step == _STEP_ATTACHMENTS:
        from app.services.attachment import read_upload_files

        file_tuples, file_error = await read_upload_files(files)
        if file_error:
            state["step"] = _STEP_ATTACHMENTS
            await _save_submission(redis, session_id, state)
            return _render_step({"error": file_error})

        state["files_stored"] = True
        state["step"] = _STEP_REVIEW
        state["file_meta"] = [
            {"filename": ft[0], "size": len(ft[2])} for ft in file_tuples
        ]
        import base64 as _b64
        file_data_list = [
            {
                "filename": ft[0],
                "content_type": ft[1],
                "data": _b64.b64encode(ft[2]).decode(),
            }
            for ft in file_tuples
        ]
        state["file_data"] = file_data_list
        await _save_submission(redis, session_id, state)
        return _render_step()

    # ── Step 6: review + final submit ────────────────────────────
    if step == _STEP_REVIEW:
        required = ["submission_mode", "category", "description"]
        for req in required:
            if req not in state:
                state["step"] = _STEP_MODE
                await _save_submission(redis, session_id, state)
                return _render_step({"error": "session_incomplete"})

        from app.services.crypto import encrypt

        mode = SubmissionMode(state.get("submission_mode", "anonymous"))
        loc_id_raw = state.get("location_id")
        report_loc_uuid: uuid.UUID | None = uuid.UUID(loc_id_raw) if loc_id_raw else None

        conf_name_enc: str | None = None
        conf_contact_enc: str | None = None
        sec_email_enc: str | None = None

        if mode == SubmissionMode.confidential:
            cn = state.get("confidential_name", "").strip()
            cc = state.get("confidential_contact", "").strip()
            se = state.get("secure_email", "").strip()
            if cn:
                conf_name_enc = encrypt(cn)
            if cc:
                conf_contact_enc = encrypt(cc)
            if se:
                sec_email_enc = encrypt(se)

        lang = get_lang(request)
        report, plain_pin = await report_service.create_report(
            db=db,
            category=state["category"],
            description=state["description"],
            lang=lang,
            submission_mode=mode,
            location_id=report_loc_uuid,
            confidential_name_enc=conf_name_enc,
            confidential_contact_enc=conf_contact_enc,
            secure_email_enc=sec_email_enc,
        )

        # Store attachments from session
        import base64 as _b64  # noqa: PLC0415

        from app.services.attachment import create_attachments, format_size

        file_data_list = state.get("file_data", [])
        file_tuples_restored: list[tuple[str, str, bytes]] = [
            (fd["filename"], fd["content_type"], _b64.b64decode(fd["data"]))
            for fd in file_data_list
        ]
        stored = await create_attachments(db, report.id, file_tuples_restored)

        from app.services.notifications import notify_new_report
        background_tasks.add_task(notify_new_report, report.case_number)

        # Clean up submission session
        await redis.delete(_submission_key(session_id))

        response = render(
            request,
            "submit_success.html",
            {
                "case_number": report.case_number,
                "pin": plain_pin,
                "attachments": [
                    {"filename": a.filename, "size_str": format_size(a.size)} for a in stored
                ],
            },
        )
        _clear_submission_cookie(response)
        response.delete_cookie(
            "ow-status-session", httponly=True, samesite="lax", secure=not settings.demo_mode
        )
        return response

    # Unknown step — restart
    state["step"] = _STEP_MODE
    await _save_submission(redis, session_id, state)
    return _render_step()


@router.post("/submit/restart")
async def submit_restart(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    raw = request.cookies.get("ow-submission-session")
    if raw and _SESSION_KEY_RE.match(raw):
        await redis.delete(_submission_key(raw))
    response = RedirectResponse("/submit", status_code=303)
    _clear_submission_cookie(response)
    return response


# ── Status ────────────────────────────────────────────────────────


@router.get("/status", response_class=HTMLResponse)
async def status_get(
    request: Request,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    _raw = request.cookies.get("ow-status-session")
    session_key: str | None = _raw if _raw and _SESSION_KEY_RE.match(_raw) else None
    if session_key:
        report_id_str = await redis.get(f"status-session:{session_key}")
        if report_id_str:
            decoded_id = (
                report_id_str.decode() if isinstance(report_id_str, bytes) else report_id_str
            )
            report = await report_service.get_report_by_id(db, uuid.UUID(decoded_id))
            if report:
                await redis.expire(f"status-session:{session_key}", 7200)
                new_session_token = secrets.token_urlsafe(32)
                replied = request.query_params.get("replied") == "1"
                success = "Your reply has been sent." if replied else None

                from datetime import UTC, datetime, timedelta

                now = datetime.now(UTC)
                submitted = report.submitted_at
                if submitted.tzinfo is None:
                    submitted = submitted.replace(tzinfo=UTC)

                ack_deadline = submitted + timedelta(days=7)
                ack_days_remaining = (ack_deadline - now).days

                return render(request, "status.html", {
                    "session_token": new_session_token,
                    "report": report,
                    "case_number": None,
                    "pin": None,
                    "from_session": True,
                    "success": success,
                    "ack_deadline": ack_deadline,
                    "ack_days_remaining": ack_days_remaining,
                    "now": now,
                })

    session_token = secrets.token_urlsafe(32)
    return render(request, "status.html", {"session_token": session_token, "report": None})


@router.post("/status", response_class=HTMLResponse)
async def status_post(
    request: Request,
    case_number: str = Form(...),
    pin: str = Form(...),
    session_token: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> Response:
    if not await rl.check_whistleblower_attempts(redis, session_token):
        lockout_ttl = await rl.get_whistleblower_lockout_ttl(redis, session_token)
        return render(
            request,
            "status.html",
            {
                "session_token": session_token,
                "report": None,
                "locked": True,
                "lockout_ttl": lockout_ttl,
            },
        )

    report = await report_service.get_report_by_credentials(db, case_number.strip(), pin.strip())

    if report is None:
        remaining = await rl.remaining_whistleblower_attempts(redis, session_token)
        await rl.record_whistleblower_failure(redis, session_token)
        return render(
            request,
            "status.html",
            {
                "session_token": session_token,
                "error": f"Invalid case number or PIN. {remaining - 1} attempts remaining.",
                "report": None,
                "case_number_value": case_number.strip(),
            },
            status_code=401,
        )

    await rl.reset_whistleblower_attempts(redis, session_token)

    status_session_key = secrets.token_urlsafe(32)
    await redis.setex(f"status-session:{status_session_key}", 7200, str(report.id))

    response = RedirectResponse("/status", status_code=303)
    response.set_cookie(
        "ow-status-session",
        status_session_key,
        max_age=7200,
        httponly=True,
        samesite="lax",
        secure=not settings.demo_mode,
    )
    return response


@router.post("/reply", response_class=HTMLResponse)
async def reply_post(
    request: Request,
    case_number: str = Form(""),
    pin: str = Form(""),
    session_token: str = Form(...),
    content: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> Response:
    _raw_key = request.cookies.get("ow-status-session")
    status_session_key: str | None = (
        _raw_key if _raw_key and _SESSION_KEY_RE.match(_raw_key) else None
    )
    report = None

    if status_session_key:
        report_id_str = await redis.get(f"status-session:{status_session_key}")
        if report_id_str:
            decoded_id = (
                report_id_str.decode() if isinstance(report_id_str, bytes) else report_id_str
            )
            report = await report_service.get_report_by_id(
                db, uuid.UUID(decoded_id)
            )

    if report is None:
        if not case_number or not pin:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not await rl.check_whistleblower_attempts(redis, session_token):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        report = await report_service.get_report_by_credentials(
            db, case_number.strip(), pin.strip()
        )
        if report is None:
            await rl.record_whistleblower_failure(redis, session_token)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await rl.reset_whistleblower_attempts(redis, session_token)
        status_session_key = secrets.token_urlsafe(32)
        await redis.setex(f"status-session:{status_session_key}", 7200, str(report.id))

    stripped = content.strip()
    if not stripped:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    if len(stripped) > 5000:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    await report_service.add_whistleblower_message(db, report, stripped)

    fresh_key = secrets.token_urlsafe(32)
    await redis.setex(f"status-session:{fresh_key}", 7200, str(report.id))
    if status_session_key:
        await redis.delete(f"status-session:{status_session_key}")

    response = RedirectResponse("/status?replied=1", status_code=303)
    response.set_cookie(
        "ow-status-session",
        fresh_key,
        max_age=7200,
        httponly=True,
        samesite="lax",
        secure=not settings.demo_mode,
    )
    return response


@router.get("/status/logout")
async def status_logout(
    request: Request,
    redis: Redis = Depends(get_redis),
) -> RedirectResponse:
    _raw = request.cookies.get("ow-status-session")
    session_key: str | None = _raw if _raw and _SESSION_KEY_RE.match(_raw) else None
    if session_key:
        await redis.delete(f"status-session:{session_key}")
    response = RedirectResponse("/status", status_code=303)
    response.delete_cookie(
        "ow-status-session", httponly=True, samesite="lax", secure=not settings.demo_mode
    )
    return response


@router.get("/status/attachments/{attachment_id}")
async def whistleblower_download_attachment(
    request: Request,
    attachment_id: uuid.UUID,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> Response:
    session_key = request.cookies.get("ow-status-session")
    if not session_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    report_id_str = await redis.get(f"status-session:{session_key}")
    if not report_id_str:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    decoded_id = report_id_str.decode() if isinstance(report_id_str, bytes) else report_id_str

    from app.services.attachment import get_attachment_by_id
    attachment = await get_attachment_by_id(db, attachment_id)

    if not attachment or str(attachment.report_id) != decoded_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if attachment.storage_key:
        from app.services.storage import get_storage_backend
        data = await get_storage_backend().get(attachment.storage_key)
    else:
        if attachment.data is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        data = attachment.data

    safe_name = attachment.filename.replace('"', "")
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )
