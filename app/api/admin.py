"""Admin dashboard endpoints."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.config import settings
from app.csrf import validate_csrf
from app.database import get_db
from app.middleware import check_ip_warning, clear_ip_warning
from app.models.report import ReportStatus
from app.models.user import AdminUser
from app.services import report as report_service
from app.templating import render

router = APIRouter(prefix="/admin")


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> HTMLResponse:
    from datetime import UTC, datetime

    reports = await report_service.get_all_reports(db)
    now = datetime.now(UTC)
    ip_warning = await check_ip_warning()

    return render(
        request,
        "admin/dashboard.html",
        {
            "user": current_user,
            "reports": reports,
            "now": now,
            "ip_warning": ip_warning,
            "ack_deadline_days": 7,
            "feedback_deadline_days": 90,
            "deleted_case": request.query_params.get("deleted"),
        },
    )


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> HTMLResponse:
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    from datetime import UTC, datetime

    return render(
        request,
        "admin/report.html",
        {
            "user": current_user,
            "report": report,
            "now": datetime.now(UTC),
            "statuses": list(ReportStatus),
        },
    )


@router.post("/reports/{report_id}/acknowledge", response_class=HTMLResponse)
async def acknowledge_report(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    await report_service.acknowledge_report(db, report)
    return RedirectResponse(f"/admin/reports/{report.id}", status_code=302)


@router.post("/reports/{report_id}/status", response_class=HTMLResponse)
async def update_status(
    request: Request,
    report_id: uuid.UUID,
    new_status: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    try:
        s = ReportStatus(new_status)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST) from exc

    await report_service.update_report_status(db, report, s)
    return RedirectResponse(f"/admin/reports/{report.id}", status_code=302)


@router.post("/reports/{report_id}/reply", response_class=HTMLResponse)
async def admin_reply(
    request: Request,
    report_id: uuid.UUID,
    content: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    if not content.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)

    await report_service.add_admin_message(db, report, content.strip())
    return RedirectResponse(f"/admin/reports/{report.id}", status_code=302)


@router.post("/reports/{report_id}/delete", response_class=HTMLResponse)
async def delete_report(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    """Hard delete a report (DSGVO Art. 17 right to erasure)."""
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    case_number = report.case_number
    await report_service.delete_report(db, report)
    safe_case = quote(case_number, safe="")
    return RedirectResponse(f"/admin/dashboard?deleted={safe_case}", status_code=302)


@router.post("/ip-warning/dismiss")
async def dismiss_ip_warning(
    current_user: AdminUser = Depends(get_current_admin),
) -> JSONResponse:
    await clear_ip_warning()
    return JSONResponse({"cleared": True})


@router.get("/reports/{report_id}/attachments/{attachment_id}")
async def admin_download_attachment(
    report_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> Response:
    """Download a report attachment — requires an active admin session."""
    from app.services.attachment import get_attachment_by_id

    attachment = await get_attachment_by_id(db, attachment_id)
    if not attachment or attachment.report_id != report_id:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    safe_name = attachment.filename.replace('"', "")
    return Response(
        content=attachment.data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.post("/demo/reset")
async def demo_reset(
    current_user: AdminUser = Depends(get_current_admin),
) -> JSONResponse:
    if not settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)

    from app.services.demo_seed import seed_demo_data
    await seed_demo_data()
    return JSONResponse({"reset": True})
