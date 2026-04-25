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


_ALLOWED_SORT = frozenset({"submitted_at", "case_number", "category", "status"})
_ALLOWED_PER_PAGE = frozenset({10, 25, 50, 100})


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> HTMLResponse:
    from datetime import UTC, datetime

    from app.services.report import SortDir, SortField

    qp = request.query_params

    raw_page = qp.get("page", "1")
    raw_per_page = qp.get("per_page", "25")
    raw_sort = qp.get("sort", "submitted_at")
    raw_dir = qp.get("dir", "desc")
    status_filter = qp.get("status", "") or None

    try:
        page = max(1, int(raw_page))
    except ValueError:
        page = 1

    try:
        per_page_raw = int(raw_per_page)
        per_page = per_page_raw if per_page_raw in _ALLOWED_PER_PAGE else 25
    except ValueError:
        per_page = 25

    sort_by: SortField = raw_sort if raw_sort in _ALLOWED_SORT else "submitted_at"  # type: ignore[assignment]
    sort_dir: SortDir = "asc" if raw_dir == "asc" else "desc"

    reports, total = await report_service.get_reports_paginated(
        db,
        page=page,
        per_page=per_page,
        status_filter=status_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
    )
    stats = await report_service.get_report_stats(db)

    total_pages = max(1, (total + per_page - 1) // per_page)
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
            "stats": stats,
            "page": page,
            "per_page": per_page,
            "total": total,
            "total_pages": total_pages,
            "sort_by": sort_by,
            "sort_dir": sort_dir,
            "status_filter": status_filter or "",
            "per_page_options": [10, 25, 50, 100],
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
