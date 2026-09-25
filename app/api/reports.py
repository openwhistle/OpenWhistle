"""Whistleblower-facing endpoints: submit (multi-step), status, reply."""

import json
import re
import secrets
import uuid
from collections.abc import Awaitable
from typing import Any, cast
from urllib.parse import urlsplit

from cryptography.fernet import Fernet, InvalidToken
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
from app.i18n import get_lang, make_translator
from app.models.report import SubmissionMode
from app.onion import cookie_secure
from app.redis_client import get_redis
from app.services import report as report_service
from app.services.categories import get_active_categories
from app.services.locations import get_active_locations, get_location_by_id
from app.templating import render

router = APIRouter()

# Allowlist pattern for whistleblower session keys (URL-safe base64, 1–86 chars).
_SESSION_KEY_RE = re.compile(r"^[A-Za-z0-9_-]{1,86}$")

# Submission session TTL — 2 hours
_SUBMISSION_TTL = 7200

# Draft cookie "<id>.<key>": the key encrypts the draft and exists only in the
# whistleblower's browser, so Redis (or a dump of it) holds nothing readable.
_DRAFT_COOKIE_RE = re.compile(r"^[A-Za-z0-9_-]{43}\.[A-Za-z0-9_-]{43}$")

_NEXT_ALLOWLIST: dict[str, str] = {
    "/submit": "/submit",
    "/status": "/status",
    "/admin/login": "/admin/login",
    "/admin/dashboard": "/admin/dashboard",
    "/admin/mfa/setup": "/admin/mfa/setup",
    "/setup": "/setup",
}

# Steps: mode → location (conditional) → category → description → attachments → review
_STEP_MODE = 1
_STEP_LOCATION = 2
_STEP_CATEGORY = 3
_STEP_DESCRIPTION = 4
_STEP_ATTACHMENTS = 5
_STEP_REVIEW = 6

# Which form field a wizard error code belongs to, so the template can mark that
# field aria-invalid and point it at an inline message. Codes absent here (e.g.
# session_incomplete) concern no single field and show only in the banner.
_ERROR_FIELD: dict[str, str] = {
    "mode_required": "submission_mode",
    "invalid_location": "location_id",
    "category_required": "category",
    "description_too_short": "description",
    "description_too_long": "description",
    "attachments_too_large": "files",
    "attachments_no_room": "files",
}


def _new_draft_id() -> str:
    return f"{secrets.token_urlsafe(32)}.{secrets.token_urlsafe(32)}"


def _draft_fernet(session_id: str) -> Fernet:
    # token_urlsafe(32) is 32 random bytes in unpadded urlsafe base64 — a Fernet key.
    return Fernet(session_id.split(".")[1] + "=")


def _submission_key(session_id: str) -> str:
    return f"submission-session:{session_id.split('.')[0]}"


async def _load_submission(redis: Redis, session_id: str) -> dict[str, Any]:
    raw = await redis.get(_submission_key(session_id))
    if not raw:
        return {}
    try:
        data = _draft_fernet(session_id).decrypt(raw)
    except InvalidToken:
        return {}  # wrong or missing key: the draft is as good as expired
    return cast(dict[str, Any], json.loads(data))


async def _save_submission(redis: Redis, session_id: str, state: dict[str, Any]) -> None:
    token = _draft_fernet(session_id).encrypt(json.dumps(state).encode())
    await redis.set(_submission_key(session_id), token, ex=_SUBMISSION_TTL)


async def _redis_has_room(redis: Redis) -> bool:
    """False when Redis is past DRAFT_REDIS_MEMORY_PERCENT of its maxmemory.

    Drafts carry attachments; refusing new ones near the limit keeps room for
    sessions and rate-limit counters. Without maxmemory there is no limit to
    measure against, and an unreadable INFO never blocks a report.
    """
    try:
        info = await redis.info("memory")
    except Exception:  # noqa: BLE001
        return True
    limit = int(info.get("maxmemory", 0))
    return not limit or int(info["used_memory"]) < limit * settings.draft_redis_memory_percent / 100


async def _get_or_create_submission_session(
    request: Request, redis: Redis
) -> tuple[str, dict[str, Any]]:
    raw = request.cookies.get("ow-submission-session")
    session_id: str | None = raw if raw and _DRAFT_COOKIE_RE.match(raw) else None
    if session_id:
        state = await _load_submission(redis, session_id)
        if state:
            return session_id, state
    session_id = _new_draft_id()
    return session_id, {}


def _set_submission_cookie(
    response: Response | RedirectResponse, session_id: str, request: Request
) -> None:
    response.set_cookie(
        "ow-submission-session",
        session_id,
        max_age=_SUBMISSION_TTL,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
    )


def _clear_submission_cookie(response: Response | RedirectResponse, request: Request) -> None:
    response.delete_cookie(
        "ow-submission-session", httponly=True, samesite="lax", secure=cookie_secure(request)
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
    safe_lang = {"en": "en", "de": "de", "fr": "fr", "pt-br": "pt-br"}.get(lang, "en")
    parsed = urlsplit(next_url)
    safe_path = _NEXT_ALLOWLIST.get(parsed.path)
    if safe_path is None:
        safe_url = "/admin/dashboard" if parsed.path.startswith("/admin/") else "/submit"
    else:
        safe_url = safe_path + (f"?{parsed.query}" if parsed.query else "")
    response = RedirectResponse(safe_url, status_code=303)
    response.set_cookie(
        "ow-lang",
        safe_lang,
        max_age=31_536_000,
        httponly=False,
        samesite="lax",
        secure=cookie_secure(request),
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
        # redis-py 8's async stubs type ping() as Awaitable[bool] | bool; the
        # async client always returns an awaitable here.
        await cast("Awaitable[Any]", redis.ping())
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
    flash_error = state.pop("_flash_error", None)
    flash_field_errors = state.pop("_flash_field_errors", None)

    ctx: dict[str, Any] = {
        "state": state,
        "step": current_step,
        "total_steps": total_steps,
        "has_locations": has_locations,
        "locations": locations,
        "categories": categories,
        "display_step": _compute_step_label(current_step, has_locations),
    }
    if flash_error:
        ctx["error"] = flash_error
        if flash_field_errors:
            ctx["field_errors"] = flash_field_errors
        elif flash_error in _ERROR_FIELD:
            ctx["field_errors"] = {_ERROR_FIELD[flash_error]: f"submit.error.{flash_error}"}

    rendered = render(request, "submit.html", ctx)
    _set_submission_cookie(rendered, session_id, request)
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
        if raw_cookie and _DRAFT_COOKIE_RE.match(raw_cookie)
        else _new_draft_id()
    )
    state = await _load_submission(redis, session_id)
    if not state and raw_cookie:
        # Never adopt a client-supplied session id that has no server-side state
        # (session fixation): mint a fresh server-generated id instead, matching
        # the GET handler's behaviour.
        session_id = _new_draft_id()
        state = {}

    locations = await get_active_locations(db)
    has_locations = len(locations) > 0
    categories = await get_active_categories(db)
    valid_cat_slugs = {c.slug for c in categories}

    def _redirect_after_post() -> RedirectResponse:
        # Post/Redirect/Get: every step is rendered by GET /submit, so a native
        # browser Back never lands on a POST result (resubmit dialog, stale page).
        resp = RedirectResponse("/submit", status_code=303)
        _set_submission_cookie(resp, session_id, request)
        return resp

    async def _fail(
        step_no: int, error: str, field_errors: dict[str, str] | None = None
    ) -> RedirectResponse:
        # One-shot flash, shown and popped by the next GET /submit.
        state["step"] = step_no
        state["_flash_error"] = error
        if field_errors:
            state["_flash_field_errors"] = field_errors
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    # A step that does not match the session's progress exactly is stale (a
    # back/forward-cached page, a replayed POST) or runs ahead of the wizard
    # (a brand-new session posting step=<attachments> to stash blobs in Redis).
    # Never process it: show the session's real step instead.
    if action == "next" and step != state.get("step", _STEP_MODE):
        if not state:
            state["_flash_error"] = "session_incomplete"
        state.setdefault("step", _STEP_MODE)
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    if action == "back":
        current = state.get("step", _STEP_MODE)
        prev = current - 1
        if not has_locations and prev == _STEP_LOCATION:
            prev = _STEP_MODE
        state["step"] = max(_STEP_MODE, prev)
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    # ── Step 1: mode selection ─────────────────────────────────────
    if step == _STEP_MODE:
        # When the operator has disabled mode selection, every report is forced
        # to anonymous — a confidential submission must not be accepted.
        effective_mode = submission_mode
        if not settings.submission_mode_enabled:
            effective_mode = "anonymous"

        if effective_mode not in ("anonymous", "confidential"):
            return await _fail(_STEP_MODE, "mode_required")

        state["submission_mode"] = effective_mode

        if effective_mode == "confidential":
            name_stripped = confidential_name.strip()
            contact_stripped = confidential_contact.strip()
            email_stripped = secure_email.strip()
            state["confidential_name"] = name_stripped
            state["confidential_contact"] = contact_stripped
            state["secure_email"] = email_stripped
        else:
            # Purge any identifying fields entered on a previous confidential
            # pass — they must not linger in the Redis session for an anonymous
            # report.
            state.pop("confidential_name", None)
            state.pop("confidential_contact", None)
            state.pop("secure_email", None)

        state["step"] = _STEP_LOCATION if has_locations else _STEP_CATEGORY
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    # ── Step 2: location selection (conditional) ──────────────────
    if step == _STEP_LOCATION:
        if has_locations:
            loc_id_stripped = location_id.strip()
            if loc_id_stripped:
                try:
                    loc_uuid = uuid.UUID(loc_id_stripped)
                except ValueError:
                    return await _fail(_STEP_LOCATION, "invalid_location")
                loc = await get_location_by_id(db, loc_uuid)
                if not loc or not loc.is_active:
                    return await _fail(_STEP_LOCATION, "invalid_location")
                state["location_id"] = str(loc_uuid)
            else:
                state["location_id"] = None

        state["step"] = _STEP_CATEGORY
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    # ── Step 3: category ──────────────────────────────────────────
    if step == _STEP_CATEGORY:
        if not category or category not in valid_cat_slugs:
            return await _fail(_STEP_CATEGORY, "category_required")
        state["category"] = category
        state["step"] = _STEP_DESCRIPTION
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    # ── Step 4: description ───────────────────────────────────────
    if step == _STEP_DESCRIPTION:
        desc_stripped = description.strip()
        if len(desc_stripped) < 10:
            return await _fail(_STEP_DESCRIPTION, "description_too_short")
        if len(desc_stripped) > 10000:
            return await _fail(_STEP_DESCRIPTION, "description_too_long")
        state["description"] = desc_stripped
        state["step"] = _STEP_ATTACHMENTS
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    # ── Step 5: attachments ───────────────────────────────────────
    if step == _STEP_ATTACHMENTS:
        from app.services.attachment import (
            MAX_DRAFT_ATTACHMENT_BYTES,
            UploadError,
            read_upload_files,
        )

        file_tuples, file_error = await read_upload_files(files)
        if file_error:
            if isinstance(file_error, UploadError):
                file_error = make_translator(get_lang(request))(file_error.key, **file_error.params)
            return await _fail(_STEP_ATTACHMENTS, file_error, {"files": file_error})
        if sum(len(ft[2]) for ft in file_tuples) > MAX_DRAFT_ATTACHMENT_BYTES:
            return await _fail(_STEP_ATTACHMENTS, "attachments_too_large")
        if file_tuples and not await _redis_has_room(redis):
            return await _fail(_STEP_ATTACHMENTS, "attachments_no_room")

        # A file input is always empty on revisit, so Next with nothing chosen
        # keeps what is attached; new files (already scanned and stripped by
        # read_upload_files) replace it.
        if file_tuples:
            import base64 as _b64

            state["file_meta"] = [{"filename": ft[0], "size": len(ft[2])} for ft in file_tuples]
            state["file_data"] = [
                {
                    "filename": ft[0],
                    "content_type": ft[1],
                    "data": _b64.b64encode(ft[2]).decode(),
                }
                for ft in file_tuples
            ]
        state["step"] = _STEP_REVIEW
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    # ── Step 6: review + final submit ────────────────────────────
    if step == _STEP_REVIEW:
        required = ["submission_mode", "category", "description"]
        for req in required:
            if req not in state:
                return await _fail(_STEP_MODE, "session_incomplete")

        from app.services.crypto import encrypt

        mode = SubmissionMode(state.get("submission_mode", "anonymous"))
        loc_id_raw = state.get("location_id") if has_locations else None
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
        await create_attachments(db, report, file_tuples_restored)

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
                    {"filename": name, "size_str": format_size(len(data))}
                    for name, _, data in file_tuples_restored
                ],
            },
        )
        _clear_submission_cookie(response, request)
        response.delete_cookie(
            "ow-status-session", httponly=True, samesite="lax", secure=cookie_secure(request)
        )
        return response

    # Unknown step — restart
    state["step"] = _STEP_MODE
    await _save_submission(redis, session_id, state)
    return _redirect_after_post()


@router.post("/submit/restart")
async def submit_restart(
    request: Request,
    redis: Redis = Depends(get_redis),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    raw = request.cookies.get("ow-submission-session")
    if raw and _DRAFT_COOKIE_RE.match(raw):
        await redis.delete(_submission_key(raw))
    response = RedirectResponse("/submit", status_code=303)
    _clear_submission_cookie(response, request)
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
                replied = request.query_params.get("replied") == "1"
                success = "status.reply.sent" if replied else None

                from datetime import UTC, datetime, timedelta

                now = datetime.now(UTC)
                submitted = report.submitted_at
                if submitted.tzinfo is None:
                    submitted = submitted.replace(tzinfo=UTC)

                ack_deadline = submitted + timedelta(days=7)
                ack_days_remaining = (ack_deadline - now).days

                from app.services.report import decrypt_attachment_names, decrypt_report_fields

                _, dec_msgs = decrypt_report_fields(report)

                return render(request, "status.html", {
                    "report": report,
                    "decrypted_messages": dec_msgs,
                    "attachment_names": decrypt_attachment_names(report),
                    "case_number": None,
                    "pin": None,
                    "from_session": True,
                    "success": success,
                    "ack_deadline": ack_deadline,
                    "ack_days_remaining": ack_days_remaining,
                    "now": now,
                })

    return render(request, "status.html", {"report": None})


@router.post("/status", response_class=HTMLResponse)
async def status_post(
    request: Request,
    case_number: str = Form(...),
    pin: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> Response:
    report, lockout_ttl = await report_service.authenticate_whistleblower(
        db, redis, case_number, pin
    )

    if report is None:
        return render(
            request,
            "status.html",
            {
                "error": make_translator(get_lang(request))("status.error.invalid"),
                "report": None,
                "locked": bool(lockout_ttl),
                "lockout_ttl": lockout_ttl,
                "case_number_value": case_number.strip(),
            },
            status_code=401,
        )

    status_session_key = secrets.token_urlsafe(32)
    await redis.set(f"status-session:{status_session_key}", str(report.id), ex=7200)

    response = RedirectResponse("/status", status_code=303)
    response.set_cookie(
        "ow-status-session",
        status_session_key,
        max_age=7200,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
    )
    return response


@router.post("/reply", response_class=HTMLResponse)
async def reply_post(
    request: Request,
    case_number: str = Form(""),
    pin: str = Form(""),
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
        report, lockout_ttl = await report_service.authenticate_whistleblower(
            db, redis, case_number, pin
        )
        if report is None:
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS
                if lockout_ttl
                else status.HTTP_401_UNAUTHORIZED
            )
        status_session_key = secrets.token_urlsafe(32)
        await redis.set(f"status-session:{status_session_key}", str(report.id), ex=7200)

    stripped = content.strip()
    if not stripped:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)
    if len(stripped) > 5000:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)

    await report_service.add_whistleblower_message(db, report, stripped)

    fresh_key = secrets.token_urlsafe(32)
    await redis.set(f"status-session:{fresh_key}", str(report.id), ex=7200)
    if status_session_key:
        await redis.delete(f"status-session:{status_session_key}")

    response = RedirectResponse("/status?replied=1", status_code=303)
    response.set_cookie(
        "ow-status-session",
        fresh_key,
        max_age=7200,
        httponly=True,
        samesite="lax",
        secure=cookie_secure(request),
    )
    return response


@router.post("/status/logout")
async def status_logout(
    request: Request,
    redis: Redis = Depends(get_redis),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    _raw = request.cookies.get("ow-status-session")
    session_key: str | None = _raw if _raw and _SESSION_KEY_RE.match(_raw) else None
    if session_key:
        await redis.delete(f"status-session:{session_key}")
    response = RedirectResponse("/status", status_code=303)
    response.delete_cookie(
        "ow-status-session", httponly=True, samesite="lax", secure=cookie_secure(request)
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

    from app.services.attachment import (
        attachment_filename,
        content_disposition_attachment,
        read_attachment,
    )

    try:
        data = await read_attachment(db, attachment)
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from exc

    name = await attachment_filename(db, attachment)
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": content_disposition_attachment(name)},
    )
