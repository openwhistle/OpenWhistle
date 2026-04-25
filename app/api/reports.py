"""Whistleblower-facing endpoints: submit, status, reply."""

import secrets
import uuid

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.csrf import validate_csrf
from app.database import get_db
from app.i18n import get_lang
from app.models.report import ReportCategory
from app.redis_client import get_redis
from app.services import rate_limit as rl
from app.services import report as report_service
from app.templating import render

router = APIRouter()


@router.post("/set-language")
async def set_language(
    request: Request,
    lang: str = Form(...),
    next_url: str = Form("/submit", alias="next"),
) -> RedirectResponse:
    supported = {"en", "de"}
    safe_lang = lang if lang in supported else "en"
    # Restrict redirect to same-origin paths only
    if not next_url.startswith("/") or next_url.startswith("//"):
        next_url = "/submit"
    response = RedirectResponse(next_url, status_code=303)
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
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@router.get("/", response_class=HTMLResponse, response_model=None)
async def index(request: Request, db: AsyncSession = Depends(get_db)) -> RedirectResponse:
    from sqlalchemy import select

    from app.models.setup import SetupStatus

    result = await db.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result.scalar_one_or_none()
    if setup is None or not setup.completed:
        return RedirectResponse("/setup", status_code=302)
    return RedirectResponse("/submit", status_code=302)


@router.get("/submit", response_class=HTMLResponse)
async def submit_get(request: Request) -> HTMLResponse:
    return render(
        request,
        "submit.html",
        {"categories": list(ReportCategory), "selected_category": ""},
    )


@router.post("/submit", response_class=HTMLResponse)
async def submit_post(
    request: Request,
    background_tasks: BackgroundTasks,
    category: str = Form(""),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse:
    if not category:
        return render(
            request,
            "submit.html",
            {
                "categories": list(ReportCategory),
                "error": "Please select a category.",
                "selected_category": "",
            },
        )

    try:
        cat = ReportCategory(category)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category"
        ) from exc

    description_stripped = description.strip()

    if len(description_stripped) < 10:
        return render(
            request,
            "submit.html",
            {
                "categories": list(ReportCategory),
                "error": "Description must be at least 10 characters.",
                "selected_category": category,
            },
        )

    if len(description_stripped) > 10000:
        return render(
            request,
            "submit.html",
            {
                "categories": list(ReportCategory),
                "error": "Description must not exceed 10,000 characters.",
                "selected_category": category,
            },
        )

    lang = get_lang(request)
    report, plain_pin = await report_service.create_report(
        db=db,
        category=cat.value,
        description=description_stripped,
        lang=lang,
    )

    from app.services.notifications import notify_new_report
    background_tasks.add_task(notify_new_report, report.case_number)

    response = render(
        request,
        "submit_success.html",
        {
            "case_number": report.case_number,
            "pin": plain_pin,
        },
    )
    # Clear any stale whistleblower session so "Continue to Report Status"
    # always shows the login form for the newly submitted report.
    response.delete_cookie("ow-status-session")
    return response


@router.get("/status", response_class=HTMLResponse)
async def status_get(
    request: Request,
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    session_key = request.cookies.get("ow-status-session")
    if session_key:
        report_id_str = await redis.get(f"status-session:{session_key}")
        if report_id_str:
            decoded_id = report_id_str.decode() if isinstance(report_id_str, bytes) else report_id_str
            report = await report_service.get_report_by_id(db, uuid.UUID(decoded_id))
            if report:
                # Refresh TTL
                await redis.expire(f"status-session:{session_key}", 7200)
                new_session_token = secrets.token_urlsafe(32)
                success = "Your reply has been sent." if request.query_params.get("replied") == "1" else None
                return render(request, "status.html", {
                    "session_token": new_session_token,
                    "report": report,
                    "case_number": None,
                    "pin": None,
                    "from_session": True,
                    "success": success,
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
        )

    await rl.reset_whistleblower_attempts(redis, session_token)

    # Create a Redis-backed status session (2 hours)
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
) -> Response:
    # Try status-session cookie first
    status_session_key = request.cookies.get("ow-status-session")
    report = None

    if status_session_key:
        report_id_str = await redis.get(f"status-session:{status_session_key}")
        if report_id_str:
            decoded_id = report_id_str.decode() if isinstance(report_id_str, bytes) else report_id_str
            report = await report_service.get_report_by_id(
                db, uuid.UUID(decoded_id)
            )

    # Fall back to case_number+pin if no session
    if report is None:
        if not case_number or not pin:
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        if not await rl.check_whistleblower_attempts(redis, session_token):
            raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)
        report = await report_service.get_report_by_credentials(db, case_number.strip(), pin.strip())
        if report is None:
            await rl.record_whistleblower_failure(redis, session_token)
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)
        await rl.reset_whistleblower_attempts(redis, session_token)
        # Create session for this user
        status_session_key = secrets.token_urlsafe(32)
        await redis.setex(f"status-session:{status_session_key}", 7200, str(report.id))

    if not content.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    await report_service.add_whistleblower_message(db, report, content.strip())

    if status_session_key:
        await redis.expire(f"status-session:{status_session_key}", 7200)

    response = RedirectResponse("/status?replied=1", status_code=303)
    if status_session_key:
        response.set_cookie(
            "ow-status-session",
            status_session_key,
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
    session_key = request.cookies.get("ow-status-session")
    if session_key:
        await redis.delete(f"status-session:{session_key}")
    response = RedirectResponse("/status", status_code=303)
    response.delete_cookie("ow-status-session")
    return response
