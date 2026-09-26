"""Admin dashboard endpoints."""

import uuid
from typing import Any
from urllib.parse import quote

from fastapi import APIRouter, Depends, Form, HTTPException, Request, status
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from redis.asyncio import Redis
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin, require_admin, require_superadmin
from app.config import settings
from app.csrf import validate_csrf, validate_csrf_header
from app.database import get_db
from app.i18n import get_lang, make_translator
from app.middleware import check_ip_warning, clear_ip_warning
from app.models.report import STATUS_TRANSITIONS, Report, ReportStatus
from app.models.user import AdminRole, AdminUser
from app.redis_client import get_redis
from app.services import audit as audit_service
from app.services import report as report_service
from app.services.audit import AuditAction
from app.templating import REASON_UNREADABLE, audit_detail, render

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

# Role privilege ranking — used for tier checks in user management.
_ROLE_RANK: dict[AdminRole, int] = {
    AdminRole.case_manager: 0,
    AdminRole.admin: 1,
    AdminRole.superadmin: 2,
}


def _can_access_report(user: AdminUser, report: Report) -> bool:
    """Object-level authorization for a single report.

    - superadmin: every report.
    - admin: every report in their own organisation (all reports when
      multi-tenancy is disabled or the report has no org).
    - case_manager: only reports assigned to them (and, with multi-tenancy,
      within their own organisation).
    """
    if user.role == AdminRole.superadmin:
        return True
    if (
        settings.multi_tenancy_enabled
        and report.org_id is not None
        and user.org_id != report.org_id
    ):
        return False
    if user.role == AdminRole.case_manager:
        return report.assigned_to_id == user.id
    return True


def _org_scope(user: AdminUser) -> dict[str, Any]:
    """Query kwargs that confine a multi-tenant non-superadmin to their own org.

    `org_id=None` with `scope_org=True` still filters (to org-less rows), so an
    org-less admin never falls through to "see everything".
    """
    scope = settings.multi_tenancy_enabled and user.role != AdminRole.superadmin
    return {"scope_org": scope, "org_id": user.org_id if scope else None}


def _own_cases_only(user: AdminUser) -> uuid.UUID | None:
    """A case manager sees only the cases assigned to them — in counts, too."""
    return user.id if user.role == AdminRole.case_manager else None


def _require_same_org(user: AdminUser, target_org_id: uuid.UUID | None) -> None:
    """404 when a scoped caller addresses a row outside their organisation."""
    scope = _org_scope(user)
    if scope["scope_org"] and target_org_id != scope["org_id"]:
        raise HTTPException(status_code=404)


async def _get_authorized_report(
    db: AsyncSession, report_id: uuid.UUID, user: AdminUser
) -> Report:
    """Fetch a report and enforce object-level authorization.

    Returns 404 (never 403) on both missing and unauthorized reports so that
    the existence of a report is not leaked across the authorization boundary.
    """
    report = await report_service.get_report_by_id(db, report_id)
    if not report or not _can_access_report(user, report):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return report


def can_reveal_identity(user: AdminUser, report: Report) -> bool:
    """HinSchG §8: a confidential identity is for whoever handles the report.

    Assigned case: only the assignee. Unassigned: an admin or superadmin of the
    case's own organisation, who must assign it before anyone else may see who
    sent it. The instance operator of another organisation is not a handler.
    """
    if report.assigned_to_id is not None:
        return report.assigned_to_id == user.id
    if user.role not in {AdminRole.admin, AdminRole.superadmin}:
        return False
    return (
        not settings.multi_tenancy_enabled
        or report.org_id is None
        or user.org_id == report.org_id
    )


_REASON_MIN, _REASON_MAX = 10, 500


def _validated_reason(raw: str) -> str | None:
    reason = raw.strip()
    return reason if _REASON_MIN <= len(reason) <= _REASON_MAX else None


# ── Dashboard ──────────────────────────────────────────────────────


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> HTMLResponse:
    # A search term never travels in the URL (browser history, proxy logs): search is POST.
    params = {k: v for k, v in request.query_params.items() if k != "q"}
    return await _dashboard(request, db, current_user, params)


@router.post("/dashboard", response_class=HTMLResponse)
async def dashboard_search(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse:
    form = await request.form()
    params = {k: v for k, v in form.items() if isinstance(v, str)}
    return await _dashboard(request, db, current_user, params)


async def _dashboard(
    request: Request, db: AsyncSession, current_user: AdminUser, qp: dict[str, str]
) -> HTMLResponse:
    from datetime import UTC, datetime

    from app.services.report import SortDir, SortField

    raw_page = qp.get("page", "1")
    raw_per_page = qp.get("per_page", "25")
    raw_sort = qp.get("sort", "submitted_at")
    raw_dir = qp.get("dir", "desc")
    status_filter = qp.get("status", "") or None
    my_cases = qp.get("my_cases", "") == "1"
    location_filter_str = qp.get("location_id", "") or None
    case_query = qp.get("q", "").strip()[:64]
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

    sort_by: SortField = (
        raw_sort if raw_sort in _ALLOWED_SORT else "submitted_at"  # type: ignore[assignment]
    )
    sort_dir: SortDir = "asc" if raw_dir == "asc" else "desc"

    # Object-level scoping: case managers only ever see reports assigned to
    # them; multi-tenant admins are confined to their own organisation
    # (superadmins span all organisations).
    assigned_filter = _own_cases_only(current_user) or (current_user.id if my_cases else None)
    # Scope the list to the caller's organisation for multi-tenant non-superadmins.
    # This must apply even when their org_id is None, otherwise an org-less admin
    # would fall through to the unfiltered "see everything" branch — a metadata
    # leak inconsistent with the object-level check that denies them those reports.
    # Content search decrypts in memory, so it is only worth doing for a query
    # long enough to be meaningful, and it is scoped identically to the listing
    # itself (same assigned_to_id/location/status/org filters) so it never
    # decrypts a report outside what this caller may already see, and the
    # CONTENT_SEARCH_LIMIT budget is spent on the caller's current view rather
    # than every status/location outside it.
    content_ids = (
        await report_service.content_match_ids(
            db, case_query, assigned_to_id=assigned_filter, location_id=location_filter,
            status_filter=status_filter, **_org_scope(current_user)
        )
        if len(case_query) >= 3 else None
    )
    if content_ids is not None:
        # Reading report text is audited like opening a case; the term is encrypted
        # like an identity-reveal reason (scripts/rotate_encryption_key.py rotates both).
        from app.services.crypto import encrypt  # noqa: PLC0415

        await audit_service.log(
            db, current_user, AuditAction.CONTENT_SEARCHED,
            detail={"term": encrypt(case_query), "hits": len(content_ids)},
        )
        await db.commit()
    reports, total = await report_service.get_reports_paginated(
        db,
        page=page,
        per_page=per_page,
        status_filter=status_filter,
        sort_by=sort_by,
        sort_dir=sort_dir,
        assigned_to_id=assigned_filter,
        location_id=location_filter,
        case_query=case_query or None,
        content_ids=content_ids,
        **_org_scope(current_user),
    )
    # Pill counts are what each status pill's link would show: the caller's
    # visible cases (a case manager's own only), within the chosen location.
    stats = await report_service.get_report_stats(
        db, assigned_to_id=_own_cases_only(current_user), location_id=location_filter,
        **_org_scope(current_user),
    )
    total_pages = max(1, (total + per_page - 1) // per_page)
    now = datetime.now(UTC)
    ip_warning = await check_ip_warning()

    # An org's own reporting link, to hand to its employees (/submit is the default org's).
    reporting_path, reporting_link = "/submit", None
    if settings.multi_tenancy_enabled and current_user.org_id is not None:
        from app.models.organisation import Organisation  # noqa: PLC0415

        org = await db.get(Organisation, current_user.org_id)
        if org is not None and org.is_active:
            reporting_path = f"/submit/{org.slug}"
            reporting_link = settings.app_public_url.rstrip("/") + reporting_path

    from app.services.categories import get_category_labels
    from app.services.locations import get_all_locations

    all_locations = await get_all_locations(db, **_org_scope(current_user))
    category_labels = await get_category_labels(
        db, get_lang(request), **_org_scope(current_user)
    )

    return render(
        request,
        "admin/dashboard.html",
        {
            "user": current_user,
            "reports": reports,
            "now": now,
            "ip_warning": ip_warning,
            "reporting_path": reporting_path,
            "reporting_link": reporting_link,
            "category_labels": category_labels,
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
            "case_query": case_query,
            "per_page_options": [10, 25, 50, 100],
            "my_cases": my_cases,
            "all_locations": all_locations,
            "location_filter": str(location_filter) if location_filter else "",
            "view": {
                "page": 1, "per_page": per_page, "sort": sort_by, "dir": sort_dir,
                "status": status_filter or "", "my_cases": "1" if my_cases else "",
                "location_id": str(location_filter) if location_filter else "",
            },
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
    report = await _get_authorized_report(db, report_id, current_user)
    await audit_service.log(db, current_user, AuditAction.REPORT_VIEWED, report_id=report.id)
    await db.commit()
    return await _render_report(request, db, report, current_user)


async def _reveal_gate(
    request: Request,
    db: AsyncSession,
    report_id: uuid.UUID,
    current_user: AdminUser,
    reason: str,
) -> tuple[Report, str] | HTMLResponse:
    """Shared 404 → 403 → reason-validation gate for both ways to reveal an
    identity (the case page and the PDF export). A refused reveal is still an
    audited view of the whole case, and the typed reason is refilled — the
    same rule either way, so the two callers cannot drift again.
    """
    report = await _get_authorized_report(db, report_id, current_user)
    if not can_reveal_identity(current_user, report):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)
    valid = _validated_reason(reason)
    if valid is None:
        await audit_service.log(db, current_user, AuditAction.REPORT_VIEWED, report_id=report.id)
        await db.commit()
        return await _render_report(
            request, db, report, current_user,
            field_errors={"reason": "admin.report.identity.reason_error"}, status_code=422,
            reason_draft=reason,
        )
    return report, valid


@router.post("/reports/{report_id}/identity", response_class=HTMLResponse)
async def reveal_identity(
    request: Request,
    report_id: uuid.UUID,
    reason: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse:
    from app.services.crypto import decrypt_or_none, encrypt

    gate = await _reveal_gate(request, db, report_id, current_user, reason)
    if isinstance(gate, HTMLResponse):
        return gate
    report, valid = gate
    await audit_service.log(
        db, current_user, AuditAction.IDENTITY_REVEALED,
        report_id=report.id, detail={"reason": encrypt(valid)},
    )
    await db.commit()
    return await _render_report(request, db, report, current_user, identity={
        "name": decrypt_or_none(report.confidential_name),
        "contact": decrypt_or_none(report.confidential_contact),
    })


async def _render_report(
    request: Request,
    db: AsyncSession,
    report: Report,
    current_user: AdminUser,
    *,
    identity: dict[str, str | None] | None = None,
    field_errors: dict[str, str] | None = None,
    status_code: int = 200,
    reason_draft: str = "",
) -> HTMLResponse:
    from datetime import UTC, datetime

    from app.services.categories import get_category_labels
    from app.services.users import get_all_users

    category_labels = await get_category_labels(
        db, get_lang(request), **_org_scope(current_user)
    )

    all_admins = [
        u for u in await get_all_users(db)
        if not settings.multi_tenancy_enabled or report.org_id is None or u.org_id == report.org_id
    ]

    # Collect linked reports with case numbers for display
    linked: list[dict[str, str]] = []
    for linked_report_id, link_id in report_service.get_linked_reports(report):
        linked_report = await report_service.get_report_by_id(db, linked_report_id)
        # Only reveal a linked report's metadata to a viewer who is independently
        # authorized to see it — a link must not leak case data across the
        # assignment / organisation boundary.
        if linked_report and _can_access_report(current_user, linked_report):
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
    audit_entries, _ = await audit_service.get_audit_log(
        db, report_id=report.id, per_page=20, exclude_action=AuditAction.REPORT_VIEWED
    )

    from app.services.report import (
        decrypt_attachment_names,
        decrypt_note_contents,
        decrypt_report_fields,
    )

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
            "decrypted_notes": decrypt_note_contents(report),
            "attachment_names": decrypt_attachment_names(report),
            "now": datetime.now(UTC),
            "statuses": list(ReportStatus),
            "allowed_transitions": allowed_transitions,
            "all_admins": all_admins,
            "linked_reports": linked,
            "category_labels": category_labels,
            "audit_entries": audit_entries,
            "is_admin": current_user.role in {AdminRole.admin, AdminRole.superadmin},
            "has_identity": bool(report.confidential_name or report.confidential_contact),
            "can_reveal": can_reveal_identity(current_user, report),
            "identity": identity,
            "field_errors": field_errors or {},
            "reason_draft": reason_draft,
            "has_secure_email": has_secure_email,
        },
        status_code=status_code,
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
    report = await _get_authorized_report(db, report_id, current_user)

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
    report = await _get_authorized_report(db, report_id, current_user)

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
    report = await _get_authorized_report(db, report_id, current_user)
    if not content.strip():
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT)

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

    report = await _get_authorized_report(db, report_id, current_user)

    assignee: AdminUser | None = None
    if admin_id:
        try:
            aid = uuid.UUID(admin_id)
        except ValueError as exc:
            raise HTTPException(status_code=400) from exc
        assignee = await get_admin_by_id(db, aid)
        if not assignee:
            raise HTTPException(status_code=404, detail="Admin user not found")
        if not assignee.is_active:
            raise HTTPException(
                status_code=400,
                detail="Cannot assign a report to a deactivated user.",
            )
        if (
            settings.multi_tenancy_enabled
            and report.org_id is not None
            and assignee.org_id != report.org_id
        ):
            raise HTTPException(
                status_code=400,
                detail="Cannot assign a report to a user of another organisation.",
            )

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
    report = await _get_authorized_report(db, report_id, current_user)
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
    report = await _get_authorized_report(db, report_id, current_user)

    other = await report_service.get_report_by_case_number(db, case_number.strip().upper())
    if not other or not _can_access_report(current_user, other):
        raise HTTPException(status_code=404, detail="Case number not found")
    if other.id == report.id:
        raise HTTPException(status_code=400, detail="Cannot link a report to itself")
    if await report_service.get_link_between(db, report.id, other.id) is not None:
        raise HTTPException(status_code=409, detail="These cases are already linked.")

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
    report = await _get_authorized_report(db, report_id, current_user)
    link = await report_service.get_link(db, link_id)
    if not link:
        raise HTTPException(status_code=404)
    if link.report_id_a != report.id and link.report_id_b != report.id:
        raise HTTPException(status_code=404)

    await report_service.unlink_cases(db, link)
    await audit_service.log(
        db, current_user, AuditAction.REPORT_LINK_REMOVED, report_id=report.id,
    )
    await db.commit()
    # Use report.id (DB-sourced) for the redirect — not the user-supplied path parameter
    return RedirectResponse(f"/admin/reports/{report.id}#links", status_code=302)


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
    report = await _get_authorized_report(db, report_id, current_user)
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
    report = await _get_authorized_report(db, report_id, current_user)

    # Re-read the deletion request under a row lock so a concurrent cancel
    # cannot withdraw it between this check and the actual deletion.
    dr = await report_service.get_active_deletion_request(db, report.id, for_update=True)
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
    report = await _get_authorized_report(db, report_id, current_user)

    dr = report.deletion_request
    if not dr:
        raise HTTPException(status_code=400)
    if dr.requested_by_id != current_user.id:
        raise HTTPException(status_code=403, detail="Only the requesting admin can cancel.")

    await report_service.cancel_deletion_request(db, dr)
    await audit_service.log(
        db, current_user, AuditAction.REPORT_DELETE_CANCELLED, report_id=report.id,
    )
    await db.commit()
    # Use report.id (DB-sourced) for the redirect — not the user-supplied path parameter
    return RedirectResponse(f"/admin/reports/{report.id}", status_code=302)


# ── PDF export ─────────────────────────────────────────────────────


@router.get("/reports/{report_id}/export.pdf")
async def export_pdf(
    request: Request,
    report_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
) -> Response:
    from app.services.categories import category_label, get_category_labels
    from app.services.pdf import generate_report_pdf

    report = await _get_authorized_report(db, report_id, current_user)
    await audit_service.log(db, current_user, AuditAction.REPORT_VIEWED, report_id=report.id)
    await db.commit()

    category_labels = await get_category_labels(
        db, get_lang(request), **_org_scope(current_user)
    )
    pdf_bytes = generate_report_pdf(
        report, category_label=category_label(report.category, category_labels)
    )
    safe_name = f"{report.case_number}_export.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{safe_name}"'},
    )


@router.post("/reports/{report_id}/export.pdf", response_model=None)
async def export_pdf_with_identity(
    request: Request,
    report_id: uuid.UUID,
    reason: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf),
) -> Response:
    from app.services.categories import category_label, get_category_labels
    from app.services.crypto import encrypt
    from app.services.pdf import generate_report_pdf

    gate = await _reveal_gate(request, db, report_id, current_user, reason)
    if isinstance(gate, HTMLResponse):
        return gate
    report, valid = gate
    await audit_service.log(
        db, current_user, AuditAction.IDENTITY_REVEALED,
        report_id=report.id, detail={"reason": encrypt(valid), "via": "pdf"},
    )
    await db.commit()
    category_labels = await get_category_labels(
        db, get_lang(request), **_org_scope(current_user)
    )
    return Response(
        content=generate_report_pdf(
            report,
            include_identity=True,
            category_label=category_label(report.category, category_labels),
        ),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{report.case_number}_export.pdf"'},
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

    # Enforce object-level authorization on the parent report before serving
    # any attachment bytes (prevents cross-assignment / cross-org access).
    await _get_authorized_report(db, report_id, current_user)

    attachment = await get_attachment_by_id(db, attachment_id)
    if not attachment or attachment.report_id != report_id:
        raise HTTPException(status_code=404)

    from app.services.attachment import (
        attachment_filename,
        content_disposition_attachment,
        read_attachment,
    )

    try:
        data = await read_attachment(db, attachment)
    except LookupError as exc:
        raise HTTPException(status_code=404) from exc

    name = await attachment_filename(db, attachment)
    return Response(
        content=data,
        media_type=attachment.content_type,
        headers={"Content-Disposition": content_disposition_attachment(name)},
    )


# ── Categories ─────────────────────────────────────────────────────


@router.get("/categories", response_class=HTMLResponse)
async def categories_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
) -> HTMLResponse:
    from app.services.categories import get_all_categories
    cats = await get_all_categories(db, **_org_scope(current_user))
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
    from app.services.categories import DuplicateSlugError
    from app.services.categories import create_category as svc_create

    slug_clean = slug.strip().lower().replace(" ", "_")
    try:
        cat = await svc_create(
            db, slug_clean, label_en.strip(), label_de.strip(), sort_order,
            org_id=current_user.org_id,
        )
    except DuplicateSlugError:
        raise HTTPException(status_code=409, detail="Slug already exists") from None
    await audit_service.log(
        db, current_user, AuditAction.CATEGORY_CREATED,
        detail={"slug": cat.slug, "label_en": cat.label_en}, target_org=cat.org_id,
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
    _require_same_org(current_user, cat.org_id)
    if cat.is_default:
        raise HTTPException(status_code=422, detail="Default categories cannot be deactivated.")

    await svc_deact(db, cat)
    await audit_service.log(
        db, current_user, AuditAction.CATEGORY_DEACTIVATED,
        detail={"slug": cat.slug}, target_org=cat.org_id,
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
    _require_same_org(current_user, cat.org_id)
    await svc_react(db, cat)
    await audit_service.log(
        db, current_user, AuditAction.CATEGORY_UPDATED,
        detail={"slug": cat.slug, "action": "reactivated"}, target_org=cat.org_id,
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
    scope = _org_scope(current_user)
    users = [
        u for u in await get_all_users(db)
        if not scope["scope_org"] or u.org_id == scope["org_id"]
    ]
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
    role: str = Form(default=AdminRole.case_manager.value),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services.users import create_user as svc_create
    from app.services.users import get_user_by_username_ci

    existing = await get_user_by_username_ci(db, username.strip())
    if existing:
        raise HTTPException(status_code=409, detail="Username already exists")

    try:
        role_enum = AdminRole(role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unknown role.") from exc

    # Privilege-tier check: only a superadmin may create superadmin accounts.
    if role_enum == AdminRole.superadmin and current_user.role != AdminRole.superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a superadmin can create superadmin accounts.",
        )

    try:
        new_user, _totp_secret = await svc_create(db, username.strip(), password, role_enum)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if settings.multi_tenancy_enabled:
        new_user.org_id = current_user.org_id
    await audit_service.log(
        db, current_user, AuditAction.ADMIN_CREATED,
        detail={"username": new_user.username, "role": role_enum.value},
        target_org=new_user.org_id,
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
    from app.services.users import (
        count_active_privileged_admins,
        get_user_by_id,
        update_user_role,
    )

    target = await get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(status_code=404)
    _require_same_org(current_user, target.org_id)
    try:
        role_enum = AdminRole(role)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail="Unknown role.") from exc

    # Prevent self-escalation: an account may not change its own role.
    if target.id == current_user.id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="You cannot change your own role.",
        )
    # Privilege-tier check: only a superadmin may grant the superadmin role or
    # modify an existing superadmin (an admin cannot promote itself/others to,
    # or demote, the top tier).
    if (
        role_enum == AdminRole.superadmin or target.role == AdminRole.superadmin
    ) and current_user.role != AdminRole.superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a superadmin can assign or change the superadmin role.",
        )
    # Availability invariant: never demote the last privileged account, or the
    # instance would be left with no admin/superadmin able to manage it.
    if (
        target.role in (AdminRole.admin, AdminRole.superadmin)
        and role_enum not in (AdminRole.admin, AdminRole.superadmin)
        and target.is_active
        and await count_active_privileged_admins(db) <= 1
    ):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail="Cannot demote the last active administrator.",
        )

    old_role = target.role.value
    await update_user_role(db, target, role_enum)
    await audit_service.log(
        db, current_user, AuditAction.ADMIN_ROLE_CHANGED,
        detail={"username": target.username, "old": old_role, "new": role_enum.value},
        target_org=target.org_id,
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
    from app.services.users import count_active_privileged_admins, get_user_by_id
    from app.services.users import deactivate_user as svc_deact

    target = await get_user_by_id(db, user_id)
    if not target:
        raise HTTPException(status_code=404)
    _require_same_org(current_user, target.org_id)
    if target.id == current_user.id:
        raise HTTPException(status_code=400, detail="You cannot deactivate your own account.")

    # Only a superadmin may deactivate a superadmin (a plain admin cannot disable
    # a higher-privileged account).
    if target.role == AdminRole.superadmin and current_user.role != AdminRole.superadmin:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Only a superadmin can deactivate a superadmin account.",
        )

    # Availability invariant: never deactivate the last account able to
    # administer the instance (admin OR superadmin).
    if (
        target.role in (AdminRole.admin, AdminRole.superadmin)
        and await count_active_privileged_admins(db) <= 1
    ):
        raise HTTPException(
            status_code=422,
            detail="Cannot deactivate the last active administrator.",
        )

    await svc_deact(db, target)
    await audit_service.log(
        db, current_user, AuditAction.ADMIN_DEACTIVATED,
        detail={"username": target.username}, target_org=target.org_id,
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
    _require_same_org(current_user, target.org_id)

    await svc_react(db, target)
    await audit_service.log(
        db, current_user, AuditAction.ADMIN_REACTIVATED,
        detail={"username": target.username}, target_org=target.org_id,
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
    show_views = qp.get("views") == "1"

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
        exclude_action=_views_excluded(show_views or action_filter == AuditAction.REPORT_VIEWED),
        page=page,
        per_page=50,
        viewer_id=current_user.id,
        **_org_scope(current_user),
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
        "show_views": show_views,
        "audit_actions": audit_service.ALL_ACTIONS,
    })


def _views_excluded(show_views: bool) -> str | None:
    """Case views outnumber every other action; the trail hides them unless asked."""
    return None if show_views else AuditAction.REPORT_VIEWED


def _csv_cell(value: str) -> str:
    """Neutralise spreadsheet formulas (OWASP CSV injection)."""
    return f"'{value}" if value[:1] in ("=", "+", "-", "@", "\t", "\r") else value


def _csv_detail(raw: str | None, t: Any) -> str:
    """One unambiguous cell: a JSON object, or a legacy free-text detail as is."""
    import json

    try:
        is_object = isinstance(json.loads(raw or ""), dict)
    except ValueError:
        is_object = False
    if not is_object:
        return raw or ""
    data = {k: _csv_detail_value(k, v, t) for k, v in audit_detail(raw)}
    return json.dumps(data, ensure_ascii=False)


def _csv_detail_value(key: str, value: str, t: Any) -> str:
    """A reveal's `via` reads as its label, the same as the case page; everything else as-is."""
    if value == REASON_UNREADABLE:
        return str(t(value))
    if key == "via":
        label_key = f"audit.detail.via.{value}"
        label = t(label_key)
        if label != label_key:
            return str(label)
    return value


@router.get("/audit-log/export.csv")
async def audit_log_csv(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
) -> Response:
    import csv
    import io

    entries, _ = await audit_service.get_audit_log(
        db, per_page=10000, viewer_id=current_user.id,
        exclude_action=_views_excluded(request.query_params.get("views") == "1"),
        **_org_scope(current_user),
    )
    output = io.StringIO()
    writer = csv.writer(output)
    # "action" keeps the machine code for tooling; "action_label" is for people.
    t = make_translator(get_lang(request))
    writer.writerow(["timestamp", "admin", "action", "action_label", "report_id", "detail"])
    for e in entries:
        label_key = f"audit.action.{e.action}"
        label = t(label_key)
        writer.writerow([_csv_cell(c) for c in (
            e.created_at.isoformat(),
            e.admin_username or "",
            e.action,
            e.action if label == label_key else label,
            str(e.report_id) if e.report_id else "",
            _csv_detail(e.detail, t),
        )])

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
    stats = await report_service.get_dashboard_stats(
        db, assigned_to_id=_own_cases_only(current_user), **_org_scope(current_user)
    )
    from app.services.categories import get_category_labels
    cat_map = await get_category_labels(db, get_lang(request), **_org_scope(current_user))
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

    locs = await get_all_locations(db, **_org_scope(current_user))
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
    from app.services.locations import DuplicateCodeError
    from app.services.locations import create_location as svc_create

    code_clean = code.strip().upper()
    if not code_clean:
        raise HTTPException(status_code=400, detail="Code is required")

    try:
        loc = await svc_create(
            db,
            name=name.strip(),
            code=code_clean,
            description=description.strip() or None,
            sort_order=sort_order,
            org_id=current_user.org_id,
        )
    except DuplicateCodeError:
        raise HTTPException(status_code=409, detail="Location code already exists") from None
    await audit_service.log(
        db, current_user, AuditAction.LOCATION_CREATED,
        detail={"location_code": code_clean, "name": name.strip()}, target_org=loc.org_id,
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
    _require_same_org(current_user, loc.org_id)
    await svc_deact(db, loc)
    await audit_service.log(
        db, current_user, AuditAction.LOCATION_DEACTIVATED, detail={"location_code": loc.code},
        target_org=loc.org_id,
    )
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
    _require_same_org(current_user, loc.org_id)
    await svc_react(db, loc)
    await audit_service.log(
        db, current_user, AuditAction.LOCATION_REACTIVATED, detail={"location_code": loc.code},
        target_org=loc.org_id,
    )
    await db.commit()
    return RedirectResponse("/admin/locations", status_code=302)


# ── Misc ───────────────────────────────────────────────────────────


@router.post("/ip-warning/dismiss")
async def dismiss_ip_warning(
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf_header),
) -> JSONResponse:
    await clear_ip_warning()
    return JSONResponse({"cleared": True})


@router.post("/demo/reset")
async def demo_reset(
    current_user: AdminUser = Depends(get_current_admin),
    _csrf: None = Depends(validate_csrf_header),
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


# ── System / About ────────────────────────────────────────────────────────────


@router.get("/system", response_class=HTMLResponse)
async def system_page(
    request: Request,
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: AdminUser = Depends(require_admin),
) -> HTMLResponse:
    from app.services import telemetry
    from app.services.integrity import get_integrity_status
    from app.services.version_check import get_update_status

    update = await get_update_status(redis, settings.app_version)
    recheck = request.query_params.get("recheck") == "1"
    integrity = await get_integrity_status(redis, recheck=recheck)
    state = await telemetry.get_state(db)
    await db.commit()  # the identifier, if this was its first use
    return render(
        request,
        "admin/system.html",
        {
            "user": current_user, "update": update, "integrity": integrity,
            "telemetry": {
                "enabled": telemetry.is_enabled(state),
                "locked_by": telemetry.locked_by(),
                "installation_id": state.installation_id,
                "url": telemetry.report_url(state.installation_id),
                "last_sent_at": state.last_sent_at,
                "env": settings.telemetry_enabled,
            },
        },
    )


@router.post("/system/telemetry")
async def system_telemetry_toggle(
    enabled: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services import telemetry

    if telemetry.locked_by() is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT,
                            detail="The installation count is set by the environment.")
    state = await telemetry.get_state(db)
    wanted = enabled == "1"
    if state.enabled != wanted:
        state.enabled = wanted
        await audit_service.log(
            db, current_user,
            AuditAction.TELEMETRY_ENABLED if wanted else AuditAction.TELEMETRY_DISABLED,
        )
    await db.commit()
    return RedirectResponse("/admin/system#heading-telemetry", status_code=302)


@router.post("/system/telemetry/reset-id")
async def system_telemetry_reset_id(
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    from app.services import telemetry

    state = await telemetry.get_state(db)
    state.installation_id = telemetry.new_installation_id()
    state.last_sent_at = None  # a new installation, as far as the far end can tell
    await audit_service.log(db, current_user, AuditAction.TELEMETRY_ID_RESET)
    await db.commit()
    return RedirectResponse("/admin/system#heading-telemetry", status_code=302)


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
        {
            "user": current_user,
            "organisations": orgs,
            "default_org_slug": settings.default_org_slug,
            # Without multi-tenancy there is one wizard, at /submit: no links to list.
            "public_url": settings.app_public_url.rstrip("/")
            if settings.multi_tenancy_enabled
            else None,
        },
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
    # /submit/restart is the wizard's own: that org's link would never reach its wizard.
    if not slug_clean or slug_clean == "restart":
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
    await db.flush()  # the audit row references it
    await audit_service.log(
        db, current_user, AuditAction.ORG_CREATED, detail={"name": name, "slug": slug_clean},
        target_org=org.id,
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
    if org.slug == settings.default_org_slug:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="The default organisation cannot be deactivated.",
        )
    org.is_active = False
    await audit_service.log(
        db, current_user, AuditAction.ORG_DEACTIVATED, detail={"org_id": str(org_id)},
        target_org=org.id,
    )
    await db.commit()
    return RedirectResponse("/admin/organisations", status_code=302)
