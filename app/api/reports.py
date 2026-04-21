"""Whistleblower-facing endpoints: submit, status, reply."""

import secrets

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.report import ReportCategory
from app.redis_client import get_redis
from app.services import rate_limit as rl
from app.services import report as report_service
from app.templating import templates

router = APIRouter()


@router.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "version": "0.1.0"}


@router.get("/", response_class=HTMLResponse)
async def index(request: Request, db: AsyncSession = Depends(get_db)) -> HTMLResponse:
    from sqlalchemy import select

    from app.models.setup import SetupStatus

    result = await db.execute(select(SetupStatus).where(SetupStatus.id == 1))
    setup = result.scalar_one_or_none()
    if setup is None or not setup.completed:
        return RedirectResponse("/setup", status_code=302)
    return RedirectResponse("/submit", status_code=302)


@router.get("/submit", response_class=HTMLResponse)
async def submit_get(request: Request) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        "submit.html",
        {"categories": list(ReportCategory)},
    )


@router.post("/submit", response_class=HTMLResponse)
async def submit_post(
    request: Request,
    category: str = Form(...),
    description: str = Form(...),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    try:
        cat = ReportCategory(category)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid category"
        ) from exc

    if len(description.strip()) < 10:
        return templates.TemplateResponse(
            request,
            "submit.html",
            {
                "categories": list(ReportCategory),
                "error": "Description must be at least 10 characters.",
            },
            status_code=422,
        )

    report, plain_pin = await report_service.create_report(
        db=db,
        category=cat.value,
        description=description.strip(),
    )

    return templates.TemplateResponse(
        request,
        "submit_success.html",
        {
            "case_number": report.case_number,
            "pin": plain_pin,
        },
    )


@router.get("/status", response_class=HTMLResponse)
async def status_get(request: Request) -> HTMLResponse:
    session_token = secrets.token_urlsafe(32)
    return templates.TemplateResponse(
        request,
        "status.html",
        {"session_token": session_token, "report": None},
    )


@router.post("/status", response_class=HTMLResponse)
async def status_post(
    request: Request,
    case_number: str = Form(...),
    pin: str = Form(...),
    session_token: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if not await rl.check_whistleblower_attempts(redis, session_token):
        return templates.TemplateResponse(
            request,
            "status.html",
            {
                "session_token": session_token,
                "error": "Too many failed attempts. Please wait before trying again.",
                "report": None,
                "locked": True,
            },
            status_code=429,
        )

    report = await report_service.get_report_by_credentials(db, case_number.strip(), pin.strip())

    if report is None:
        remaining = await rl.remaining_whistleblower_attempts(redis, session_token)
        await rl.record_whistleblower_failure(redis, session_token)
        return templates.TemplateResponse(
            request,
            "status.html",
            {
                "session_token": session_token,
                "error": f"Invalid case number or PIN. {remaining - 1} attempts remaining.",
                "report": None,
            },
            status_code=401,
        )

    await rl.reset_whistleblower_attempts(redis, session_token)
    new_session_token = secrets.token_urlsafe(32)

    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "session_token": new_session_token,
            "report": report,
            "case_number": case_number.strip(),
            "pin": pin.strip(),
        },
    )


@router.post("/reply", response_class=HTMLResponse)
async def reply_post(
    request: Request,
    case_number: str = Form(...),
    pin: str = Form(...),
    session_token: str = Form(...),
    content: str = Form(...),
    redis: Redis = Depends(get_redis),
    db: AsyncSession = Depends(get_db),
) -> HTMLResponse:
    if not await rl.check_whistleblower_attempts(redis, session_token):
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS)

    report = await report_service.get_report_by_credentials(db, case_number.strip(), pin.strip())

    if report is None:
        await rl.record_whistleblower_failure(redis, session_token)
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED)

    if not content.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    await report_service.add_whistleblower_message(db, report, content.strip())
    await rl.reset_whistleblower_attempts(redis, session_token)

    # Redirect to status page with fresh session token
    new_session_token = secrets.token_urlsafe(32)
    return templates.TemplateResponse(
        request,
        "status.html",
        {
            "session_token": new_session_token,
            "report": report,
            "case_number": case_number.strip(),
            "pin": pin.strip(),
            "success": "Your reply has been sent.",
        },
    )
