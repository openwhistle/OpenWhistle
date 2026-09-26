"""Whistleblower-facing endpoints: submit (multi-step), status, reply."""

import asyncio
import json
import logging
import re
import secrets
import uuid
from collections.abc import Awaitable
from dataclasses import dataclass
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
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.csrf import validate_csrf
from app.database import get_db
from app.i18n import get_lang, make_translator
from app.models.organisation import Organisation
from app.models.report import SubmissionMode
from app.onion import cookie_secure
from app.redis_client import get_redis
from app.services import report as report_service
from app.services.categories import get_active_categories
from app.services.locations import get_active_locations, get_location_by_id
from app.templating import render

router = APIRouter()
_log = logging.getLogger(__name__)

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
# An organisation's wizard, /submit/<slug> (slugs are [a-z0-9-], see create_organisation).
_ORG_SUBMIT_RE = re.compile(r"/submit/([a-z0-9-]{1,64})")

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


# One draft yields at most one report: the draft carries the report's id from
# its first save, and the primary key refuses a second insert with it.
#
# A final submit claims the draft by renaming it to its ":claimed" key (same
# encryption, same TTL) and sets "pending" to a nonce of its own. Claim to
# commit is bounded by _SUBMIT_TIMEOUT_SECONDS, well under _PENDING_TTL. Once
# "pending" expires, the claimed draft is given back only if its report does
# not exist; otherwise the session gets the "received" page. A concurrent submit
# of the same draft waits up to _RESULT_WAIT_SECONDS for the stored result.
_RESULT_WAIT_SECONDS = 10.0
_RESULT_TTL = 120
_PENDING_TTL = 120
_SUBMIT_TIMEOUT_SECONDS = 30

# KEYS: draft, report-id. ARGV: draft token as read, new id, TTL.
# One id for a draft saved before v1.6.0, whoever loads it; none once the
# draft changed or was spent (its report-id key goes with it).
_ASSIGN_REPORT_ID = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return false
end
redis.call('SET', KEYS[2], ARGV[2], 'NX', 'EX', ARGV[3])
return redis.call('GET', KEYS[2])
"""

# KEYS: draft, claimed, pending. ARGV: pending TTL, nonce.
_CLAIM_DRAFT = """
if redis.call('EXISTS', KEYS[1]) == 0 or redis.call('EXISTS', KEYS[2]) == 1 then
  return false
end
redis.call('RENAME', KEYS[1], KEYS[2])
redis.call('SET', KEYS[3], ARGV[2], 'EX', ARGV[1])
return redis.call('GET', KEYS[2])
"""

# KEYS: draft, claimed, pending, result, report-id. ARGV: claimed token, result
# token or "" (the report does not exist: give the draft back), result TTL.
_RECOVER_DRAFT = """
if redis.call('EXISTS', KEYS[3]) == 1 or redis.call('EXISTS', KEYS[1]) == 1
   or redis.call('GET', KEYS[2]) ~= ARGV[1] then
  return 0
end
if ARGV[2] == '' then
  redis.call('RENAME', KEYS[2], KEYS[1])
else
  redis.call('DEL', KEYS[2], KEYS[5])
  redis.call('SET', KEYS[4], ARGV[2], 'EX', ARGV[3])
end
return 1
"""

# KEYS: draft, claimed, pending. ARGV: draft token, draft TTL, nonce.
# Never touches a newer claim, never overwrites a draft that came back.
_GIVE_BACK_DRAFT = """
local pending = redis.call('GET', KEYS[3])
if pending and pending ~= ARGV[3] then
  return 0
end
if redis.call('EXISTS', KEYS[1]) == 0 then
  redis.call('SET', KEYS[1], ARGV[1], 'EX', ARGV[2])
end
redis.call('DEL', KEYS[2], KEYS[3])
return 1
"""

# KEYS: draft, claimed, pending, result, report-id. ARGV: nonce, result token
# or "", TTL. The report exists: the draft is spent, unless a newer claim holds it.
_FINISH_CLAIM = """
if ARGV[2] ~= '' then
  redis.call('SET', KEYS[4], ARGV[2], 'EX', ARGV[3])
end
local pending = redis.call('GET', KEYS[3])
if not pending or pending == ARGV[1] then
  redis.call('DEL', KEYS[1], KEYS[2], KEYS[3], KEYS[5])
end
return 1
"""


@dataclass(frozen=True)
class _Tenant:
    """Whose wizard a request is on: the organisation its reports are filed
    under, and the wizard's own URL. Unscoped with multi-tenancy off."""

    scoped: bool
    org_id: uuid.UUID | None
    path: str

    @property
    def scope(self) -> dict[str, Any]:
        return {"scope_org": self.scoped, "org_id": self.org_id}

    @property
    def draft_org(self) -> str | None:
        return str(self.org_id) if self.org_id else None


async def _tenant(request: Request, db: AsyncSession) -> _Tenant | RedirectResponse:
    """/submit is the default organisation's wizard, /submit/<slug> that
    organisation's. An unknown or inactive slug is a 404; there is no list of
    the instance's organisations. With multi-tenancy off there is one unscoped
    wizard at /submit, and only the default slug redirects to it."""
    org_slug: str | None = request.path_params.get("org_slug")
    if not settings.multi_tenancy_enabled:
        if org_slug is None:
            return _Tenant(scoped=False, org_id=None, path="/submit")
        if org_slug == settings.default_org_slug:
            return RedirectResponse("/submit", status_code=303)
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    org_id = await db.scalar(
        select(Organisation.id).where(
            Organisation.slug == (org_slug or settings.default_org_slug),
            Organisation.is_active.is_(True),
        )
    )
    if org_slug is None:
        return _Tenant(scoped=True, org_id=org_id, path="/submit")
    if org_id is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return _Tenant(scoped=True, org_id=org_id, path=f"/submit/{org_slug}")


async def _load_draft(redis: Redis, session_id: str, tenant: _Tenant) -> dict[str, Any]:
    """The draft, unless it belongs to another organisation: a draft never
    moves between organisations (its categories and locations are its own).
    One saved without an organisation joins the first wizard that saves it."""
    state = await _load_submission(redis, session_id)
    if tenant.scoped and state.get("org_id", tenant.draft_org) != tenant.draft_org:
        return {}
    return state


def _mode_error(mode: object) -> str | None:
    allowed = ("anonymous", "confidential") if settings.submission_mode_enabled else ("anonymous",)
    return None if mode in allowed else "mode_required"


async def _location_error(db: AsyncSession, location_id: object, tenant: _Tenant) -> str | None:
    if not location_id:
        return None
    try:
        loc_uuid = uuid.UUID(str(location_id))
    except ValueError:
        return "invalid_location"
    loc = await get_location_by_id(db, loc_uuid)
    if not loc or not loc.is_active or (tenant.scoped and loc.org_id != tenant.org_id):
        return "invalid_location"
    return None


def _category_error(category: object, category_slugs: set[str]) -> str | None:
    return None if category in category_slugs else "category_required"


def _description_error(description: object) -> str | None:
    length = len(description.strip()) if isinstance(description, str) else 0
    if length < 10:
        return "description_too_short"
    return "description_too_long" if length > 10000 else None


async def _draft_error(
    db: AsyncSession,
    state: dict[str, Any],
    category_slugs: set[str],
    has_locations: bool,
    tenant: _Tenant,
) -> tuple[int, str] | None:
    """The first step whose value no longer passes its own check, and why.

    Run again before the final submit: a rejected description stays in the
    draft for editing, and a location, category or mode can be switched off
    by the operator after the reporter chose it.
    """
    checks: list[tuple[int, str | None]] = [
        (_STEP_MODE, _mode_error(state.get("submission_mode"))),
        (
            _STEP_LOCATION,
            await _location_error(db, state.get("location_id"), tenant)
            if has_locations
            else None,
        ),
        (_STEP_CATEGORY, _category_error(state.get("category"), category_slugs)),
        (_STEP_DESCRIPTION, _description_error(state.get("description"))),
    ]
    return next(((step_no, err) for step_no, err in checks if err), None)


def _pending_key(session_id: str) -> str:
    return _submission_key(session_id) + ":pending"


def _result_key(session_id: str) -> str:
    return _submission_key(session_id) + ":result"


def _claimed_key(session_id: str) -> str:
    return _submission_key(session_id) + ":claimed"


def _claim_keys(session_id: str) -> tuple[str, str, str]:
    return _submission_key(session_id), _claimed_key(session_id), _pending_key(session_id)


async def _claim_draft(redis: Redis, session_id: str) -> tuple[str, str] | None:
    """(draft token, claim nonce) for exactly one of several concurrent submits."""
    nonce = secrets.token_urlsafe(16)
    token = await cast(
        Awaitable[str | None],
        redis.eval(_CLAIM_DRAFT, 3, *_claim_keys(session_id), _PENDING_TTL, nonce),
    )
    return None if token is None else (token, nonce)


async def _recover_draft(redis: Redis, db: AsyncSession, session_id: str) -> None:
    """A claim whose submit ended without cleanup ("pending" expired): give the
    draft back if its report does not exist, else store the "received" result."""
    draft_key, claimed_key, pending_key = _claim_keys(session_id)
    if await redis.exists(draft_key, pending_key):
        return
    token = await redis.get(claimed_key)
    if token is None:
        return
    try:
        report_id = json.loads(_draft_fernet(session_id).decrypt(token)).get("report_id")
    except InvalidToken:
        return
    case_number = await _committed_case_number(db, report_id) if report_id else None
    result = "" if case_number is None else _encrypt_result(session_id, _received(case_number))
    await redis.eval(
        _RECOVER_DRAFT, 5, draft_key, claimed_key, pending_key, _result_key(session_id),
        _report_id_key(session_id), token, result, _RESULT_TTL,
    )


async def _give_back_draft(redis: Redis, session_id: str, token: str, nonce: str) -> bool:
    """The submit failed and its report does not exist: the draft is the reporter's
    again. False when a newer claim holds it."""
    return bool(
        await cast(
            Awaitable[int],
            redis.eval(
                _GIVE_BACK_DRAFT, 3, *_claim_keys(session_id), token, _SUBMISSION_TTL, nonce
            ),
        )
    )


async def _finish_claim(
    redis: Redis, session_id: str, nonce: str, result: dict[str, Any] | None
) -> None:
    await redis.eval(
        _FINISH_CLAIM, 5, *_claim_keys(session_id), _result_key(session_id),
        _report_id_key(session_id), nonce,
        "" if result is None else _encrypt_result(session_id, result), _RESULT_TTL,
    )


def _encrypt_result(session_id: str, result: dict[str, Any]) -> str:
    # Encrypted with the draft's key, like the draft was.
    return _draft_fernet(session_id).encrypt(json.dumps(result).encode()).decode()


def _received(case_number: str) -> dict[str, Any]:
    """The result of a report whose PIN is no longer known (shown once, elsewhere)."""
    return {"case_number": case_number, "pin": None, "attachments": []}


async def _committed_case_number(db: AsyncSession, report_id: str | uuid.UUID) -> str | None:
    """The case number of the report with this id, if one was committed. Asked on
    a fresh session (the request's may be broken), bounded like the submit."""
    from app.models.report import Report  # noqa: PLC0415

    async with asyncio.timeout(_SUBMIT_TIMEOUT_SECONDS), AsyncSession(db.bind) as fresh:
        case_number: str | None = await fresh.scalar(
            select(Report.case_number).where(Report.id == uuid.UUID(str(report_id)))
        )
        return case_number


async def _submit_in_flight(redis: Redis, session_id: str) -> bool:
    return bool(
        await redis.exists(
            _pending_key(session_id), _result_key(session_id), _claimed_key(session_id)
        )
    )


def _new_draft_id() -> str:
    return f"{secrets.token_urlsafe(32)}.{secrets.token_urlsafe(32)}"


def _draft_fernet(session_id: str) -> Fernet:
    # token_urlsafe(32) is 32 random bytes in unpadded urlsafe base64 — a Fernet key.
    return Fernet(session_id.split(".")[1] + "=")


def _submission_key(session_id: str) -> str:
    return f"submission-session:{session_id.split('.')[0]}"


def _report_id_key(session_id: str) -> str:
    return _submission_key(session_id) + ":report-id"


async def _load_submission(redis: Redis, session_id: str) -> dict[str, Any]:
    # Bounded: a draft re-saved without an id on every attempt counts as expired.
    for _ in range(3):
        raw = await redis.get(_submission_key(session_id))
        if not raw:
            return {}
        try:
            data = _draft_fernet(session_id).decrypt(raw)
        except InvalidToken:
            return {}  # wrong or missing key: the draft is as good as expired
        state = cast(dict[str, Any], json.loads(data))
        if state and "report_id" not in state:
            # Saved before v1.6.0: concurrent loaders must agree on one id.
            report_id = await cast(
                Awaitable[str | None],
                redis.eval(
                    _ASSIGN_REPORT_ID, 2, _submission_key(session_id), _report_id_key(session_id),
                    raw, str(uuid.uuid4()), _SUBMISSION_TTL,
                ),
            )
            if report_id is None:  # saved or spent meanwhile: read what is there now
                continue
            state["report_id"] = report_id
        return state
    return {}


async def _save_submission(redis: Redis, session_id: str, state: dict[str, Any]) -> None:
    # Fixed at the draft's first non-empty save and carried by every later one
    # (they all save a loaded state): every submit inserts the same primary key.
    if state:
        state.setdefault("report_id", str(uuid.uuid4()))
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
    request: Request, redis: Redis, tenant: _Tenant
) -> tuple[str, dict[str, Any]]:
    raw = request.cookies.get("ow-submission-session")
    session_id: str | None = raw if raw and _DRAFT_COOKIE_RE.match(raw) else None
    if session_id:
        state = await _load_draft(redis, session_id, tenant)
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
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    safe_lang = {"en": "en", "de": "de", "fr": "fr", "pt-br": "pt-br"}.get(lang, "en")
    parsed = urlsplit(next_url)
    safe_path = _NEXT_ALLOWLIST.get(parsed.path)
    if safe_path is None and (org_path := _ORG_SUBMIT_RE.fullmatch(parsed.path)):
        safe_path = f"/submit/{org_path.group(1)}"
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
) -> Response:
    tenant = await _tenant(request, db)
    if isinstance(tenant, Response):
        return tenant
    raw_cookie = request.cookies.get("ow-submission-session")
    if raw_cookie and _DRAFT_COOKIE_RE.match(raw_cookie):
        if not await _load_submission(redis, raw_cookie) and await _submit_in_flight(
            redis, raw_cookie
        ):
            # "Check again" after a submit whose outcome was not known yet;
            # _submit_outcome also gives the draft back once "pending" expired.
            page = await _submit_outcome(request, redis, db, raw_cookie, tenant.path, wait=0)
            if page is not None:
                return page
    session_id, state = await _get_or_create_submission_session(request, redis, tenant)

    locations = await get_active_locations(db, **tenant.scope)
    has_locations = len(locations) > 0
    total_steps = _compute_total_steps(has_locations)

    # Determine which step to show based on state
    current_step = state.get("step", _STEP_MODE)
    if not has_locations and current_step == _STEP_LOCATION:
        current_step = _STEP_CATEGORY
        state["step"] = current_step

    categories = await get_active_categories(db, **tenant.scope)
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
        "submit_path": tenant.path,
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
    tenant = await _tenant(request, db)
    if isinstance(tenant, Response):
        return tenant
    raw_cookie = request.cookies.get("ow-submission-session")
    session_id: str = (
        raw_cookie
        if raw_cookie and _DRAFT_COOKIE_RE.match(raw_cookie)
        else _new_draft_id()
    )
    state = await _load_draft(redis, session_id, tenant)
    if not state and raw_cookie == session_id:
        # Reload whoever recovered it: a concurrent request may have.
        await _recover_draft(redis, db, session_id)
        state = await _load_draft(redis, session_id, tenant)
        if not state and await _submit_in_flight(redis, session_id):
            # Another request holds this draft's submit (a second click on
            # "Submit"): show its outcome, never touch the draft.
            return await _await_other_submit(request, redis, db, session_id, tenant.path)
    if not state and raw_cookie:
        # Never adopt a client-supplied session id that has no server-side state
        # (session fixation): mint a fresh server-generated id instead, matching
        # the GET handler's behaviour.
        session_id = _new_draft_id()
        state = {}

    locations = await get_active_locations(db, **tenant.scope)
    has_locations = len(locations) > 0
    categories = await get_active_categories(db, **tenant.scope)
    valid_cat_slugs = {c.slug for c in categories}

    def _redirect_after_post() -> RedirectResponse:
        # Post/Redirect/Get: every step is rendered by the GET, so a native
        # browser Back never lands on a POST result (resubmit dialog, stale page).
        resp = RedirectResponse(tenant.path, status_code=303)
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
    # Never process it, nor an unknown action: show the session's real step.
    if action not in ("next", "back") or (
        action == "next" and step != state.get("step", _STEP_MODE)
    ):
        if not state:
            state["_flash_error"] = "session_incomplete"
        state.setdefault("step", _STEP_MODE)
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    if tenant.scoped:
        state.setdefault("org_id", tenant.draft_org)  # fixed from here on

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

        if mode_error := _mode_error(effective_mode):
            return await _fail(_STEP_MODE, mode_error)

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
            if loc_error := await _location_error(db, loc_id_stripped, tenant):
                return await _fail(_STEP_LOCATION, loc_error)
            state["location_id"] = str(uuid.UUID(loc_id_stripped)) if loc_id_stripped else None

        state["step"] = _STEP_CATEGORY
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    # ── Step 3: category ──────────────────────────────────────────
    if step == _STEP_CATEGORY:
        if cat_error := _category_error(category, valid_cat_slugs):
            return await _fail(_STEP_CATEGORY, cat_error)
        state["category"] = category
        state["step"] = _STEP_DESCRIPTION
        await _save_submission(redis, session_id, state)
        return _redirect_after_post()

    # ── Step 4: description ───────────────────────────────────────
    if step == _STEP_DESCRIPTION:
        desc_stripped = description.strip()
        # Kept even when rejected, so the reporter can edit what was typed.
        state["description"] = desc_stripped[:10000]
        if desc_error := _description_error(desc_stripped):
            return await _fail(_STEP_DESCRIPTION, desc_error)
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
        # Renaming the draft to its claimed key hands it to exactly one of
        # several concurrent submits (no JS guard in Tor Browser "Safest").
        claim = await _claim_draft(redis, session_id)
        if claim is None:
            await db.rollback()  # do not hold a pooled connection while waiting
            return await _await_other_submit(request, redis, db, session_id, tenant.path)
        claimed, nonce = claim

        import base64 as _b64  # noqa: PLC0415

        from sqlalchemy import text  # noqa: PLC0415

        from app.services.attachment import create_attachments, format_size
        from app.services.crypto import encrypt

        state.clear()
        state.update(json.loads(_draft_fernet(session_id).decrypt(claimed)))
        report_id = state.get("report_id")
        if not report_id:  # a draft saved before v1.6.0: the next save adds one
            await _give_back_draft(redis, session_id, claimed, nonce)
            return _redirect_after_post()
        our_case: str | None = None
        commit_error: BaseException | None = None
        # Report and attachments commit together, so nothing is left behind.
        try:
            async with asyncio.timeout(_SUBMIT_TIMEOUT_SECONDS):
                await db.execute(
                    text(f"SET LOCAL statement_timeout = {_SUBMIT_TIMEOUT_SECONDS * 1000}")
                )
                if draft_error := await _draft_error(
                    db, state, valid_cat_slugs, has_locations, tenant
                ):
                    await _give_back_draft(redis, session_id, claimed, nonce)
                    return await _fail(*draft_error)  # saves the draft again, flagged

                mode = SubmissionMode(state["submission_mode"])
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

                file_tuples_restored: list[tuple[str, str, bytes]] = [
                    (fd["filename"], fd["content_type"], _b64.b64decode(fd["data"]))
                    for fd in state.get("file_data", [])
                ]
                report, plain_pin = await report_service.create_report(
                    db=db,
                    category=state["category"],
                    description=state["description"].strip(),
                    lang=get_lang(request),
                    submission_mode=mode,
                    location_id=report_loc_uuid,
                    confidential_name_enc=conf_name_enc,
                    confidential_contact_enc=conf_contact_enc,
                    secure_email_enc=sec_email_enc,
                    commit=False,
                    report_id=uuid.UUID(report_id),
                    org_id=tenant.org_id,
                )
                await create_attachments(db, report, file_tuples_restored, commit=False)
                our_case = report.case_number
                await db.commit()
        except BaseException as exc:
            # The database decides: a lost reply can hide a commit that went
            # through, and another submit of this draft may own the report. If
            # this lookup fails too, nothing is given back: the recovery asks
            # again once "pending" expires.
            try:
                committed_case = await _committed_case_number(db, report_id)
            except Exception:
                if not isinstance(exc, Exception):
                    raise exc from None
                return _pending_page(request, tenant.path, kept=True)
            if committed_case is None:
                if our_case is not None:  # the COMMIT was issued and may still land
                    if not isinstance(exc, Exception):
                        raise
                    return _pending_page(request, tenant.path, kept=True)
                given_back = await _give_back_draft(redis, session_id, claimed, nonce)
                if not isinstance(exc, Exception):
                    raise  # cancelled, or the worker is going away: nobody to answer
                if not given_back:  # a newer claim holds the draft
                    return await _await_other_submit(
                        request, redis, db, session_id, tenant.path
                    )
                _log.warning("Final submit failed before its commit: %s", type(exc).__name__)
                return await _fail(_STEP_REVIEW, "submit_failed")  # nothing was sent
            if committed_case != our_case:  # another submit of this draft made it
                await _finish_claim(redis, session_id, nonce, None)
                if isinstance(exc, asyncio.CancelledError):
                    raise
                return await _stored_result_page(request, redis, session_id, committed_case)
            commit_error = exc
        # Committed: from here on nothing may bring the draft back.

        from app.services.notifications import notify_new_report
        assert our_case is not None  # committed: ours, or the lookup matched it
        background_tasks.add_task(notify_new_report, our_case)

        result = {
            "case_number": our_case,
            "pin": plain_pin,
            "attachments": [
                {"filename": name, "size_str": format_size(len(data))}
                for name, _, data in file_tuples_restored
            ],
        }
        # For a concurrent second click, which the browser shows instead of
        # this response. If this write fails, the recovery finds the report.
        try:
            await _finish_claim(redis, session_id, nonce, result)
        except Exception:  # noqa: BLE001, S110 — best effort: this response has the PIN
            pass
        if isinstance(commit_error, asyncio.CancelledError):
            raise commit_error  # nobody to answer; a retry reads the stored result
        return _success_page(request, result)

    # Unknown step — restart
    state["step"] = _STEP_MODE
    await _save_submission(redis, session_id, state)
    return _redirect_after_post()


def _success_page(request: Request, result: dict[str, Any]) -> HTMLResponse:
    response = render(request, "submit_success.html", result)
    _clear_submission_cookie(response, request)
    response.delete_cookie(
        "ow-status-session", httponly=True, samesite="lax", secure=cookie_secure(request)
    )
    return response


def _pending_page(request: Request, path: str, *, kept: bool) -> HTMLResponse:
    return render(request, "submit_pending.html", {"answers_kept": kept, "submit_path": path})


async def _stored_result_page(
    request: Request, redis: Redis, session_id: str, case_number: str
) -> HTMLResponse:
    """The page for a report another submit of this draft created: with its PIN
    while the stored result is there, else with the case number only."""
    raw = await redis.get(_result_key(session_id))
    result = json.loads(_draft_fernet(session_id).decrypt(raw)) if raw else None
    if not result or result["case_number"] != case_number:
        result = _received(case_number)
    return _success_page(request, result)


async def _submit_outcome(
    request: Request, redis: Redis, db: AsyncSession, session_id: str, path: str, wait: float
) -> Response | None:
    """A concurrent submit's success page once its result is stored (the
    browser shows only the last click's response); the "still processing"
    page while it runs; None once the draft is the reporter's again.

    The cookie stays until the outcome is known: a restored draft must remain
    reachable, and "received" is said only with a case number.
    """
    deadline = asyncio.get_running_loop().time() + wait
    while (
        await redis.exists(_pending_key(session_id))
        and asyncio.get_running_loop().time() < deadline
    ):
        if raw := await redis.getdel(_result_key(session_id)):
            break
        await asyncio.sleep(0.1)
    else:
        await _recover_draft(redis, db, session_id)
        raw = await redis.getdel(_result_key(session_id))
    if raw:
        return _success_page(request, json.loads(_draft_fernet(session_id).decrypt(raw)))
    if await _load_submission(redis, session_id):
        return None
    # The answers are kept only while the claimed draft exists.
    kept = bool(await redis.exists(_claimed_key(session_id)))
    return _pending_page(request, path, kept=kept)


async def _await_other_submit(
    request: Request, redis: Redis, db: AsyncSession, session_id: str, path: str
) -> Response:
    page = await _submit_outcome(request, redis, db, session_id, path, wait=_RESULT_WAIT_SECONDS)
    if page is not None:
        return page
    # The other submit failed before its commit and gave the draft back.
    resp = RedirectResponse(path, status_code=303)
    _set_submission_cookie(resp, session_id, request)
    return resp


@router.post("/submit/attachments/remove")
async def submit_remove_attachment(
    request: Request,
    index: int = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    """Remove one already-attached file from the draft, on the attachments step only."""
    tenant = await _tenant(request, db)
    if isinstance(tenant, RedirectResponse):
        return tenant
    raw = request.cookies.get("ow-submission-session")
    if raw and _DRAFT_COOKIE_RE.match(raw):
        state = await _load_draft(redis, raw, tenant)
        files = state.get("file_data", [])
        if state.get("step") == _STEP_ATTACHMENTS and 0 <= index < len(files):
            del files[index]
            del state["file_meta"][index]
            await _save_submission(redis, raw, state)
    return RedirectResponse(tenant.path, status_code=303)


@router.post("/submit/restart")
async def submit_restart(
    request: Request,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    tenant = await _tenant(request, db)
    if isinstance(tenant, RedirectResponse):
        return tenant
    raw = request.cookies.get("ow-submission-session")
    if raw and _DRAFT_COOKIE_RE.match(raw):
        await redis.delete(_submission_key(raw), _report_id_key(raw))
    response = RedirectResponse(tenant.path, status_code=303)
    _clear_submission_cookie(response, request)
    return response


# An organisation's wizard. Registered after /submit/restart, which a slug
# route would otherwise take (create_organisation refuses the slug "restart").
router.add_api_route(
    "/submit/{org_slug}", submit_get, methods=["GET"], response_class=HTMLResponse
)
router.add_api_route(
    "/submit/{org_slug}", submit_post, methods=["POST"], response_class=HTMLResponse
)
router.add_api_route(
    "/submit/{org_slug}/attachments/remove", submit_remove_attachment, methods=["POST"]
)
router.add_api_route("/submit/{org_slug}/restart", submit_restart, methods=["POST"])


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
                # No TTL refresh on view: the session ends 2 h after login, so its
                # remaining lifetime does not reveal when the page was last opened.
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

    # A fresh key, but the old one's remaining lifetime: a reply must not extend
    # the session either (see status_get).
    remaining = 7200
    if status_session_key:
        remaining = max(1, int(await redis.ttl(f"status-session:{status_session_key}")))
    fresh_key = secrets.token_urlsafe(32)
    await redis.set(f"status-session:{fresh_key}", str(report.id), ex=remaining)
    if status_session_key:
        await redis.delete(f"status-session:{status_session_key}")

    response = RedirectResponse("/status?replied=1", status_code=303)
    response.set_cookie(
        "ow-status-session",
        fresh_key,
        max_age=remaining,
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
