"""Admin dashboard endpoints."""

import uuid
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, require_admin, require_superadmin
from app.config import settings
from app.csrf import validate_csrf
from app.database import get_db
from app.middleware import check_ip_warning, clear_ip_warning
from app.models.report import STATUS_TRANSITIONS, ReportStatus
from app.models.user import AdminRole, AdminUser
from app.redis_client import get_redis
from app.services import audit as audit_service
from app.services import report as report_service
from app.services.audit import AuditAction
from app.templating import render

router = APIRouter(prefix="/admin")


async def _cleanup_report_sessions(redis: Redis, report_id: uuid.UUID) -> None:
    target = str(report_id)
    cursor = 0
    while True:
        cursor, keys = await redis.scan(cursor, match="status-session:*", count=100)
        if keys:
            values = await redis.mget(*keys)
            to_delete = [
                key for key, val in zip(keys, values, strict=False)
                if val is not None
                and (val.decode() if isinstance(val, bytes) else val) == target
            ]
            if to_delete:
                await redis.delete(*to_delete)
        if cursor == 0:
            break


_ALLOWED_SORT = frozenset({"submitted_at", "case_number", "category", "status"})
_ALLOWED_PER_PAGE = frozenset({10, 25, 50, 100})


# ── Dashboard ──────────────────────────────────────────────────────


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
    my_cases = qp.get("my_cases", "") == "1"
    location_filter_str = qp.get("location_id", "") or None
    location_filter: uuid.UUID | None = None
    if location_filter_str:
        try:
            location_filter = uuid.UUID(location_filter_str)
        except ValueError:
            pass

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

    assigned_filter = current_user.id if my_cases else None
    reports, total = await report_service.get_reports_paginated(
        db,
        page=page,
        per_page=per_page,
        status_filter=status_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        assigned_to_id=assigned_filter,
        location_id=location_filter,
    )
    stats = await report_service.get_report_stats(db)
    total_pages = max(1, (total + per_page - 1) // per_page)
    now = datetime.now(UTC)
    ip_warning = await check_ip_warning()

    from app.services.locations import get_all_locations

    all_locations = await get_all_locations(db)

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
            "my_cases": my_cases,
            "all_locations": all_locations,
            "location_filter": str(location_filter) if location_filter else "",
        },
    )


# ── Report detail ──────────────────────────────────────────────────


@router.get("/reports/{report_id}", response_class=HTMLResponse)
async def report_detail(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> HTMLResponse:
    from datetime import UTC, datetime

    from app.services.users import get_all_users

    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    all_admins = await get_all_users(db)

    # Collect linked reports with case numbers for display
    linked: list[dict[str, str]] = []
    for linked_report_id, link_id in report_service.get_linked_reports(report):
        linked_report = await report_service.get_report_by_id(db, linked_report_id)
        if linked_report:
            linked.append({
                "link_id": link_id,
                "case_number": linked_report.case_number,
                "category": linked_report.category,
                "status": linked_report.status.value,
                "id": str(linked_report.id),
            })

    allowed_transitions = list(
        STATUS_TRANSITIONS.get(report.status.value, set())
    )

    # Fetch audit log for this report
    audit_entries, _ = await audit_service.get_audit_log(db, report_id=report_id, per_page=20)

    from app.services.crypto import decrypt_or_none
    from app.services.report import decrypt_report_fields

    confidential_name = decrypt_or_none(report.confidential_name)
    confidential_contact = decrypt_or_none(report.confidential_contact)
    has_secure_email = bool(report.secure_email)

    decrypted_description, decrypted_msg_contents = decrypt_report_fields(report)

    return render(
        request,
        "admin/report.html",
        {
            "user": current_user,
            "report": report,
            "decrypted_description": decrypted_description,
            "decrypted_messages": decrypted_msg_contents,
            "now": datetime.now(UTC),
            "statuses": list(ReportStatus),
            "allowed_transitions": allowed_transitions,
            "all_admins": all_admins,
            "linked_reports": linked,
            "audit_entries": audit_entries,
            "is_admin": current_user.role in {AdminRole.admin, AdminRole.superadmin},
            "confidential_name": confidential_name,
            "confidential_contact": confidential_contact,
            "has_secure_email": has_secure_email,
        },
    )


# ── Report actions ─────────────────────────────────────────────────


@router.post("/reports/{report_id}/acknowledge")
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

    old_status = report.status.value
    await report_service.acknowledge_report(db, report)
    await audit_service.log(
        db, current_user, AuditAction.REPORT_ACKNOWLEDGED, report_id=report.id,
        detail={"old_status": old_status, "new_status": report.status.value},
    )
    await db.commit()
    return RedirectResponse(f"/admin/reports/{report.id}", status_code=302)


@router.post("/reports/{report_id}/status")
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

    if not report_service.is_valid_transition(report.status.value, s.value):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status transition: {report.status.value} → {s.value}",
        )

    old_status = report.status.value
    await report_service.update_report_status(db, report, s)
    await audit_service.log(
        db, current_user, AuditAction.REPORT_STATUS_CHANGED, report_id=report.id,
        detail={"old": old_status, "new": s.value},
    )
    await db.commit()
    return RedirectResponse(f"/admin/reports/{report.id}", status_code=302)


@router.post("/reports/{report_id}/reply")
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

    await report_service.add_admin_message(
        db, report, content.strip(), notify_whistleblower=True
    )
    await audit_service.log(
        db, current_user, AuditAction.REPORT_MESSAGE_SENT, report_id=report.id,
    )
    await db.commit()
    return RedirectResponse(f"/admin/reports/{report.id}", status_code=302)


@router.post("/reports/{report_id}/assign")
async def assign_report(
    request: Request,
    report_id: uuid.UUID,
    admin_id: str = Form(default=""),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.users import get_user_by_id as get_admin_by_id

    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)

    assignee: AdminUser | None = None
    if admin_id:
        try:
            aid = uuid.UUID(admin_id)
        except ValueError as exc:
            raise HTTPException(status_code=400) from exc
        assignee = await get_admin_by_id(db, aid)
        if not assignee:
            raise HTTPException(status_code=404, detail="Admin user not found")

    old_assignee = report.assigned_to.username if report.assigned_to else None
    await report_service.assign_report(db, report, assignee)
    await audit_service.log(
        db, current_user, AuditAction.REPORT_ASSIGNED, report_id=report.id,
        detail={"from": old_assignee, "to": assignee.username if assignee else None},
    )
    await db.commit()
    return RedirectResponse(f"/admin/reports/{report.id}", status_code=302)


# ── Internal notes ─────────────────────────────────────────────────


@router.post("/reports/{report_id}/notes")
async def add_note(
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
        raise HTTPException(status_code=422)

    await report_service.add_note(db, report, current_user, content.strip())
    await audit_service.log(
        db, current_user, AuditAction.REPORT_NOTE_ADDED, report_id=report.id,
    )
    await db.commit()
    return RedirectResponse(f"/admin/reports/{report.id}#notes", status_code=302)


# ── Case linking ───────────────────────────────────────────────────


@router.post("/reports/{report_id}/links")
async def link_report(
    request: Request,
    report_id: uuid.UUID,
    case_number: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404)

    other = await report_service.get_report_by_case_number(db, case_number.strip().upper())
    if not other:
        raise HTTPException(status_code=404, detail="Case number not found")
    if other.id == report.id:
        raise HTTPException(status_code=400, detail="Cannot link a report to itself")

    await report_service.link_cases(db, report, other, current_user)
    await audit_service.log(
        db, current_user, AuditAction.REPORT_LINK_ADDED, report_id=report.id,
        detail={"linked_with": other.case_number},
    )
    await db.commit()
    return RedirectResponse(f"/admin/reports/{report.id}#links", status_code=302)


@router.post("/reports/{report_id}/links/{link_id}/delete")
async def unlink_report(
    request: Request,
    report_id: uuid.UUID,
    link_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    link = await report_service.get_link(db, link_id)
    if not link:
        raise HTTPException(status_code=404)
    if link.report_id_a != report_id and link.report_id_b != report_id:
        raise HTTPException(status_code=404)

    await report_service.unlink_cases(db, link)
    await audit_service.log(
        db, current_user, AuditAction.REPORT_LINK_REMOVED, report_id=report_id,
    )
    await db.commit()
    return RedirectResponse(f"/admin/reports/{report_id}#links", status_code=302)


# ── 4-eyes deletion ────────────────────────────────────────────────


@router.post("/reports/{report_id}/request-delete")
async def request_delete(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404)
    if report.deletion_request is not None:
        raise HTTPException(status_code=409, detail="A deletion request already exists.")

    await report_service.request_deletion(db, report, current_user)
    await audit_service.log(
        db, current_user, AuditAction.REPORT_DELETE_REQUESTED, report_id=report.id,
    )
    await db.commit()
    return RedirectResponse(f"/admin/reports/{report.id}", status_code=302)


@router.post("/reports/{report_id}/confirm-delete")
async def confirm_delete(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404)

    dr = report.deletion_request
    if not dr:
        raise HTTPException(status_code=400, detail="No pending deletion request.")
    if dr.requested_by_id == current_user.id:
        raise HTTPException(
            status_code=409,
            detail="The same admin who requested deletion cannot confirm it.",
        )

    case_number = report.case_number
    await report_service.confirm_deletion(db, report, dr, current_user)
    await _cleanup_report_sessions(redis, report_id)
    safe_case = quote(case_number, safe="")
    return RedirectResponse(f"/admin/dashboard?deleted={safe_case}", status_code=302)


@router.post("/reports/{report_id}/cancel-delete")
async def cancel_delete(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404)

    dr = report.deletion_request
    if not dr:
        raise HTTPException(status_code=400)
    if dr.requested_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the requesting admin can cancel.")

    await report_service.cancel_deletion_request(db, dr)
    await audit_service.log(
        db, current_user, AuditAction.REPORT_DELETE_CANCELLED, report_id=report_id,
    )
    await db.commit()
    return RedirectResponse(f"/admin/reports/{report_id}", status_code=302)


# ── PDF export ─────────────────────────────────────────────────────


@router.get("/reports/{report_id}/export.pdf")
async def export_pdf(
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> Response:
    from app.services.pdf import generate_report_pdf

    report = await report_service.get_report_by_id(db, report_id)
    if not report:
        raise HTTPException(status_code=404)

    pdf_bytes = generate_report_pdf(report)
    safe_name = f"{report.case_number}_export.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# ── Attachment download ─────────────────────────────────────────────


@router.get("/reports/{report_id}/attachments/{attachment_id}")
async def admin_download_attachment(
    report_id: uuid.UUID,
    attachment_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> Response:
    from app.services.attachment import get_attachment_by_id

    attachment = await get_attachment_by_id(db, attachment_id)
    if not attachment or attachment.report_id != report_id:
        raise HTTPException(status_code=404)

    if attachment.storage_key:
        from app.services.storage import get_storage_backend
        data = await get_storage_backend().get(attachment.storage_key)
    else:
        if attachment.data is None:
            raise HTTPException(status_code=404)
        data = attachment.data

    safe_name = attachment.filename.replace('"', "")
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


# ── Categories ─────────────────────────────────────────────────────


@router.get("/categories", response_class=HTMLResponse)
async def categories_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
) -> HTMLResponse:
    from app.services.categories import get_all_categories
    cats = await get_all_categories(db)
    return render(request, "admin/categories.html", {"user": current_user, "categories": cats})


@router.post("/categories")
async def create_category(
    request: Request,
    slug: str = Form(...),
    label_en: str = Form(...),
    label_de: str = Form(...),
    sort_order: int = Form(default=50),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.categories import create_category as svc_create
    from app.services.categories import get_category_by_slug

    slug_clean = slug.strip().lower().replace(" ", "_")
    existing = await get_category_by_slug(db, slug_clean)
    if existing:
        raise HTTPException(status_code=409, detail="Slug already exists")

    cat = await svc_create(db, slug_clean, label_en.strip(), label_de.strip(), sort_order)
    await audit_service.log(
        db, current_user, AuditAction.CATEGORY_CREATED,
        detail={"slug": cat.slug, "label_en": cat.label_en},
    )
    await db.commit()
    return RedirectResponse("/admin/categories", status_code=302)


@router.post("/categories/{cat_id}/deactivate")
async def deactivate_category(
    request: Request,
    cat_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.categories import deactivate_category as svc_deact
    from app.services.categories import get_category_by_id

    cat = await get_category_by_id(db, cat_id)
    if not cat:
        raise HTTPException(status_code=404)
    if cat.is_default:
        raise HTTPException(status_code=422, detail="Default categories cannot be deactivated.")

    await svc_deact(db, cat)
    await audit_service.log(
        db, current_user, AuditAction.CATEGORY_DEACTIVATED,
        detail={"slug": cat.slug},
    )
    await db.commit()
    return RedirectResponse("/admin/categories", status_code=302)


@router.post("/categories/{cat_id}/reactivate")
async def reactivate_category(
    request: Request,
    cat_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.categories import get_category_by_id
    from app.services.categories import reactivate_category as svc_react

    cat = await get_category_by_id(db, cat_id)
    if not cat:
        raise HTTPException(status_code=404)
    await svc_react(db, cat)
    await audit_service.log(
        db, current_user, AuditAction.CATEGORY_UPDATED,
        detail={"slug": cat.slug, "action": "reactivated"},
    )
    await db.commit()
    return RedirectResponse("/admin/categories", status_code=302)


# ── Admin user management ──────────────────────────────────────────


@router.get("/users", response_class=HTMLResponse)
async def users_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
) -> HTMLResponse:
    from app.services.users import get_all_users
    users = await get_all_users(db)
    return render(request, "admin/users.html", {
        "user": current_user,
        "users": users,
        "roles": list(AdminRole),
    })


@router.post("/users")
async def create_user(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    role: str = Form(default="admin"),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services import auth as auth_svc
    from app.services.users import create_user as svc_create

    existing = await auth_svc.get_user_by_username(db, username.strip())
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    try:
        role_enum = AdminRole(role)
    except ValueError:
        role_enum = AdminRole.admin

    new_user, _totp_secret = await svc_create(db, username.strip(), password, role_enum)
    await audit_service.log(
        db, current_user, AuditAction.ADMIN_CREATED,
        detail={"username": new_user.username, "role": role_enum.value},
    )
    await db.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/role")
async def change_user_role(
    request: Request,
    user_id: uuid.UUID,
    role: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.users import get_user_by_id, update_user_role

    target = await get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(status_code=404)
    try:
        role_enum = AdminRole(role)
    except ValueError as exc:
        raise HTTPException(status_code=400) from exc

    old_role = target.role.value
    await update_user_role(db, target, role_enum)
    await audit_service.log(
        db, current_user, AuditAction.ADMIN_ROLE_CHANGED,
        detail={"username": target.username, "old": old_role, "new": role_enum.value},
    )
    await db.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/deactivate")
async def deactivate_user(
    request: Request,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.users import count_active_admins, get_user_by_id
    from app.services.users import deactivate_user as svc_deact

    target = await get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(status_code=404)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")

    if target.role == AdminRole.admin:
        active_admin_count = await count_active_admins(db)
        if active_admin_count <= 1:
            raise HTTPException(
                status_code=422,
                detail="Cannot deactivate the last active admin.",
            )

    await svc_deact(db, target)
    await audit_service.log(
        db, current_user, AuditAction.ADMIN_DEACTIVATED,
        detail={"username": target.username},
    )
    await db.commit()
    return RedirectResponse("/admin/users", status_code=302)


@router.post("/users/{user_id}/reactivate")
async def reactivate_user(
    request: Request,
    user_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.users import get_user_by_id
    from app.services.users import reactivate_user as svc_react

    target = await get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(status_code=404)

    await svc_react(db, target)
    await audit_service.log(
        db, current_user, AuditAction.ADMIN_REACTIVATED,
        detail={"username": target.username},
    )
    await db.commit()
    return RedirectResponse("/admin/users", status_code=302)


# ── Audit log ──────────────────────────────────────────────────────


@router.get("/audit-log", response_class=HTMLResponse)
async def audit_log_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
) -> HTMLResponse:
    qp = request.query_params
    try:
        page = max(1, int(qp.get("page", "1")))
    except ValueError:
        page = 1
    report_id_str = qp.get("report_id", "")
    action_filter = qp.get("action", "")

    report_id = None
    if report_id_str:
        try:
            report_id = uuid.UUID(report_id_str)
        except ValueError:
            pass

    entries, total = await audit_service.get_audit_log(
        db,
        report_id=report_id,
        action=action_filter or None,
        page=page,
        per_page=50,
    )
    total_pages = max(1, (total + 49) // 50)

    return render(request, "admin/audit_log.html", {
        "user": current_user,
        "entries": entries,
        "total": total,
        "page": page,
        "total_pages": total_pages,
        "action_filter": action_filter,
        "report_id_filter": report_id_str,
    })


@router.get("/audit-log/export.csv")
async def audit_log_csv(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
) -> Response:
    import csv
    import io

    entries, _ = await audit_service.get_audit_log(db, per_page=10000)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["timestamp", "admin", "action", "report_id", "detail"])
    for e in entries:
        writer.writerow([
            e.created_at.isoformat(),
            e.admin_username,
            e.action,
            str(e.report_id) if e.report_id else "",
            e.detail or "",
        ])

    return Response(
        content=output.getvalue().encode("utf-8"),
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=audit_log.csv"},
    )


# ── Dashboard statistics ────────────────────────────────────────────


@router.get("/stats", response_class=HTMLResponse)
async def stats_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> HTMLResponse:
    stats = await report_service.get_dashboard_stats(db)
    from app.services.categories import get_all_categories
    categories = await get_all_categories(db)
    cat_map = {c.slug: c.label_en for c in categories}
    return render(request, "admin/stats.html", {
        "user": current_user,
        "stats": stats,
        "cat_map": cat_map,
    })


# ── Locations ──────────────────────────────────────────────────────


@router.get("/locations", response_class=HTMLResponse)
async def locations_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
) -> HTMLResponse:
    from app.services.locations import get_all_locations

    locs = await get_all_locations(db)
    return render(request, "admin/locations.html", {"user": current_user, "locations": locs})


@router.post("/locations")
async def create_location(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    description: str = Form(default=""),
    sort_order: int = Form(default=0),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.locations import create_location as svc_create
    from app.services.locations import get_location_by_code

    code_clean = code.strip().upper()
    if not code_clean:
        raise HTTPException(status_code=400, detail="Code is required")

    existing = await get_location_by_code(db, code_clean)
    if existing:
        raise HTTPException(status_code=409, detail="Location code already exists")

    await svc_create(
        db,
        name=name.strip(),
        code=code_clean,
        description=description.strip() or None,
        sort_order=sort_order,
    )
    await audit_service.log(
        db, current_user, AuditAction.CATEGORY_CREATED,
        detail={"location_code": code_clean, "name": name.strip()},
    )
    await db.commit()
    return RedirectResponse("/admin/locations", status_code=302)


@router.post("/locations/{loc_id}/deactivate")
async def deactivate_location(
    request: Request,
    loc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.locations import deactivate_location as svc_deact
    from app.services.locations import get_location_by_id

    loc = await get_location_by_id(db, loc_id)
    if not loc:
        raise HTTPException(status_code=404)
    await svc_deact(db, loc)
    await db.commit()
    return RedirectResponse("/admin/locations", status_code=302)


@router.post("/locations/{loc_id}/reactivate")
async def reactivate_location(
    request: Request,
    loc_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.locations import get_location_by_id
    from app.services.locations import reactivate_location as svc_react

    loc = await get_location_by_id(db, loc_id)
    if not loc:
        raise HTTPException(status_code=404)
    await svc_react(db, loc)
    await db.commit()
    return RedirectResponse("/admin/locations", status_code=302)


# ── Misc ───────────────────────────────────────────────────────────


@router.post("/ip-warning/dismiss")
async def dismiss_ip_warning(
    current_user: AdminUser = Depends(get_current_admin),
) -> JSONResponse:
    await clear_ip_warning()
    return JSONResponse({"cleared": True})


@router.post("/demo/reset")
async def demo_reset(
    current_user: AdminUser = Depends(get_current_admin),
) -> JSONResponse:
    if not settings.demo_mode:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    from app.services.demo_seed import seed_demo_data
    await seed_demo_data()
    return JSONResponse({"reset": True})


# ── Telephone channel stub (HinSchG §16) ─────────────────────────────────────


@router.get("/telephone-channel", response_class=HTMLResponse)
async def telephone_channel_page(
    request: Request,
    current_user: AdminUser = Depends(get_current_admin),
) -> HTMLResponse:
    return render(request, "admin/telephone_channel.html", {"user": current_user})


# ── Data retention ────────────────────────────────────────────────────────────


@router.get("/retention", response_class=HTMLResponse)
async def retention_page(
    request: Request,
    current_user: AdminUser = Depends(require_admin),
) -> HTMLResponse:
    from datetime import UTC, datetime, timedelta

    now = datetime.now(UTC)
    next_run = (now + timedelta(days=1)).replace(hour=3, minute=0, second=0, microsecond=0)
    return render(
        request,
        "admin/retention.html",
        {
            "user": current_user,
            "retention_enabled": settings.retention_enabled,
            "retention_days": settings.retention_days,
            "next_run": next_run,
        },
    )


# ── Organisation management (superadmin only) ─────────────────────────────────


@router.get("/organisations", response_class=HTMLResponse)
async def organisations_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
) -> HTMLResponse:
    from sqlalchemy import select

    from app.models.organisation import Organisation

    result = await db.execute(select(Organisation).order_by(Organisation.created_at))
    orgs = result.scalars().all()
    return render(
        request,
        "admin/organisations.html",
        {"user": current_user, "organisations": orgs},
    )


@router.post("/organisations", response_class=HTMLResponse)
async def create_organisation(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
    name: str = Form(...),
    slug: str = Form(...),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    import re

    from sqlalchemy import select

    from app.models.organisation import Organisation

    slug_clean = re.sub(r"[^a-z0-9-]", "-", slug.strip().lower())
    if not slug_clean:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid slug.")

    existing = await db.execute(
        select(Organisation).where(Organisation.slug == slug_clean)
    )
    if existing.scalar_one_or_none():
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail="Slug already exists."
        )

    org = Organisation(id=__import__("uuid").uuid4(), name=name.strip(), slug=slug_clean)
    db.add(org)
    await audit_service.log(
        db, current_user, AuditAction.ORG_CREATED, detail={"name": name, "slug": slug_clean}
    )
    await db.commit()
    return RedirectResponse("/admin/organisations", status_code=302)


@router.post("/organisations/{org_id}/deactivate")
async def deactivate_organisation(
    org_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_superadmin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from sqlalchemy import select

    from app.models.organisation import Organisation

    result = await db.execute(select(Organisation).where(Organisation.id == org_id))
    org = result.scalar_one_or_none()
    if not org:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    if org.slug == "default":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The default organisation cannot be deactivated.",
        )
    org.is_active = False
    await audit_service.log(
        db, current_user, AuditAction.ORG_DEACTIVATED, detail={"org_id": str(org_id)}
    )
    await db.commit()
    return RedirectResponse("/admin/organisations", status_code=302)
