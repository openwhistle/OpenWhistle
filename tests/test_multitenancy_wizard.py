"""With multi-tenancy on, each organisation has its own reporting link
/submit/<slug>: the wizard offers only that organisation's categories and
locations, and the report is filed under it."""

from __future__ import annotations

import asyncio
import re
import uuid
from collections.abc import AsyncGenerator
from dataclasses import dataclass

import pytest
import pytest_asyncio
from httpx import AsyncClient, Response
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import get_current_admin
from app.config import settings
from app.main import app
from app.models.category import ReportCategory
from app.models.location import Location
from app.models.organisation import Organisation
from app.models.report import Report
from app.models.user import AdminRole, AdminUser

_CASE_RE = re.compile(r"OW-\d{4}-\d+")
_PIN_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[0-9a-f]{4}-[0-9a-f]{12}")
_HTML = {"accept": "text/html"}


@dataclass
class _Org:
    org: Organisation
    category: ReportCategory
    location: Location
    admin: AdminUser

    @property
    def path(self) -> str:
        return f"/submit/{self.org.slug}"


def _csrf(text: str) -> str:
    m = re.search(r'name="csrf_token" value="([^"]+)"', text)
    return m.group(1) if m else ""


def _step(text: str) -> int:
    m = re.search(r'name="step" value="(\d+)"', text)
    return int(m.group(1)) if m else 1


def _org(tag: str) -> _Org:
    hex6 = uuid.uuid4().hex[:6]
    org = Organisation(id=uuid.uuid4(), name=f"Org {tag} {hex6}", slug=f"org-{tag}-{hex6}")
    return _Org(
        org=org,
        category=ReportCategory(
            id=uuid.uuid4(), slug=f"cat_{tag}_{hex6}", label_en=f"Category {tag} {hex6}",
            label_de=f"Kategorie {tag} {hex6}", is_default=False, is_active=True,
            sort_order=1, org_id=org.id,
        ),
        location=Location(
            id=uuid.uuid4(), name=f"Site {tag} {hex6}", code=f"S{tag.upper()}{hex6}",
            is_active=True, sort_order=0, org_id=org.id,
        ),
        admin=AdminUser(
            id=uuid.uuid4(), username=f"mtw_{tag}_{hex6}", role=AdminRole.admin, org_id=org.id,
            is_active=True, totp_secret="JBSWY3DPEHPK3PXP", totp_enabled=True,
        ),
    )


@pytest_asyncio.fixture(loop_scope="function")
async def orgs(
    db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> AsyncGenerator[dict[str, _Org]]:
    monkeypatch.setattr(settings, "multi_tenancy_enabled", True)
    made = {"a": _org("a"), "b": _org("b"), "c": _org("c")}
    made["c"].org.is_active = False
    db_session.add_all(o.org for o in made.values())
    await db_session.flush()
    for o in made.values():
        db_session.add_all([o.category, o.location, o.admin])
    await db_session.commit()
    org_ids = [o.org.id for o in made.values()]
    yield made
    # Other tests run the wizard unscoped: leave nothing of ours in it.
    await db_session.rollback()
    for model in (ReportCategory, Location):
        await db_session.execute(
            update(model).where(model.org_id.in_(org_ids)).values(is_active=False)
        )
    await db_session.commit()


async def _post(
    client: AsyncClient, path: str, step: int | None = None, **fields: str
) -> Response:
    page = await client.get(path)
    data = {
        "csrf_token": _csrf(page.text),
        "step": str(step if step is not None else _step(page.text)),
        "action": "next",
        **fields,
    }
    return await client.post(path, data=data, follow_redirects=False)


async def _walk_to_review(
    client: AsyncClient, o: _Org, *, category: str | None = None, location_id: str = "",
    description: str = "A description long enough to pass.",
) -> None:
    await _post(client, o.path, submission_mode="anonymous")
    assert _step((await client.get(o.path)).text) == 2  # the org has a location
    await _post(client, o.path, location_id=location_id)
    await _post(client, o.path, category=category or o.category.slug)
    await _post(client, o.path, description=description)
    await _post(client, o.path)  # attachments: none


async def _report(db: AsyncSession, case_number: str) -> Report:
    return (
        await db.execute(
            select(Report)
            .where(Report.case_number == case_number)
            .execution_options(populate_existing=True)
        )
    ).scalar_one()


async def _count(db: AsyncSession) -> int:
    return int((await db.execute(select(func.count()).select_from(Report))).scalar_one())


# ── The wizard at /submit/<slug> ─────────────────────────────────────


@pytest.mark.asyncio
async def test_each_link_offers_only_its_own_orgs_locations_and_categories(
    client: AsyncClient, orgs: dict[str, _Org]
) -> None:
    for me, other in ((orgs["a"], orgs["b"]), (orgs["b"], orgs["a"])):
        client.cookies.clear()
        await _post(client, me.path, submission_mode="anonymous")
        location_page = (await client.get(me.path)).text
        assert me.location.name in location_page
        assert other.location.name not in location_page
        await _post(client, me.path, location_id="")
        category_page = (await client.get(me.path)).text
        assert _step(category_page) == 3
        assert me.category.slug in category_page
        assert other.category.slug not in category_page
        assert "financial_fraud" not in category_page  # the default org's


@pytest.mark.asyncio
async def test_the_form_posts_back_to_the_org_link(
    client: AsyncClient, orgs: dict[str, _Org]
) -> None:
    page = (await client.get(orgs["b"].path)).text
    assert f'action="{orgs["b"].path}"' in page
    assert 'action="/submit"' not in page
    resp = await _post(client, orgs["b"].path, submission_mode="anonymous")
    assert resp.status_code == 303
    assert resp.headers["location"] == orgs["b"].path


@pytest.mark.asyncio
async def test_a_report_through_org_bs_link_is_filed_under_org_b(
    client: AsyncClient, orgs: dict[str, _Org], db_session: AsyncSession
) -> None:
    b = orgs["b"]
    await _walk_to_review(client, b, location_id=str(b.location.id))
    done = await _post(client, b.path)
    case = _CASE_RE.search(done.text)
    assert case, "the final submit shows the case number"
    report = await _report(db_session, case.group(0))
    assert report.org_id == b.org.id
    assert report.location_id == b.location.id
    assert report.category == b.category.slug

    for viewer, sees in ((orgs["a"], False), (b, True)):
        app.dependency_overrides[get_current_admin] = lambda viewer=viewer: viewer.admin
        try:
            dashboard = (await client.get("/admin/dashboard")).text
        finally:
            app.dependency_overrides.pop(get_current_admin, None)
        assert (case.group(0) in dashboard) is sees


@pytest.mark.asyncio
async def test_another_orgs_location_is_refused(
    client: AsyncClient, orgs: dict[str, _Org]
) -> None:
    b = orgs["b"]
    await _post(client, b.path, submission_mode="anonymous")
    resp = await _post(client, b.path, location_id=str(orgs["a"].location.id))
    assert resp.status_code == 303
    page = (await client.get(b.path)).text
    assert _step(page) == 2
    assert "location is not valid" in page


@pytest.mark.asyncio
async def test_another_orgs_category_is_refused(
    client: AsyncClient, orgs: dict[str, _Org]
) -> None:
    b = orgs["b"]
    await _post(client, b.path, submission_mode="anonymous")
    await _post(client, b.path, location_id="")
    resp = await _post(client, b.path, category=orgs["a"].category.slug)
    assert resp.status_code == 303
    page = (await client.get(b.path)).text
    assert _step(page) == 3
    assert "Please select a category" in page


@pytest.mark.asyncio
@pytest.mark.parametrize("field", ["category", "location_id"])
async def test_the_final_submit_checks_the_draft_against_its_own_org(
    client: AsyncClient, orgs: dict[str, _Org], db_session: AsyncSession, field: str
) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    b = orgs["b"]
    await _walk_to_review(client, b)
    session_id = client.cookies.get("ow-submission-session")
    assert session_id
    redis = await get_redis()
    draft = await reports._load_submission(redis, session_id)
    draft[field] = (
        orgs["a"].category.slug if field == "category" else str(orgs["a"].location.id)
    )
    await reports._save_submission(redis, session_id, draft)
    before = await _count(db_session)

    resp = await _post(client, b.path)
    assert resp.status_code == 303
    assert _step((await client.get(b.path)).text) == (3 if field == "category" else 2)
    assert await _count(db_session) == before


@pytest.mark.asyncio
async def test_a_draft_does_not_move_to_another_org(
    client: AsyncClient, orgs: dict[str, _Org], db_session: AsyncSession
) -> None:
    a, b = orgs["a"], orgs["b"]
    await _walk_to_review(client, a, description="What org A's reporter typed.")
    a_cookie = client.cookies.get("ow-submission-session")
    assert a_cookie

    # Opening org B's link starts a draft for org B: nothing of A's shows.
    page = (await client.get(b.path)).text
    assert _step(page) == 1
    assert "What org A" not in page

    # A crafted final submit to org B's URL with org A's draft creates nothing.
    client.cookies.set("ow-submission-session", a_cookie)
    before = await _count(db_session)
    resp = await client.post(
        b.path, data={"csrf_token": _csrf(page), "step": "6", "action": "next"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == b.path
    assert await _count(db_session) == before

    # Org A's draft is untouched and still files under org A.
    client.cookies.set("ow-submission-session", a_cookie)
    assert _step((await client.get(a.path)).text) == 6
    case = _CASE_RE.search((await _post(client, a.path)).text)
    assert case
    assert (await _report(db_session, case.group(0))).org_id == a.org.id


@pytest.mark.asyncio
async def test_submit_without_a_slug_is_the_default_org(
    client: AsyncClient, orgs: dict[str, _Org], db_session: AsyncSession
) -> None:
    default_id = (
        await db_session.execute(
            select(Organisation.id).where(Organisation.slug == settings.default_org_slug)
        )
    ).scalar_one()
    await _post(client, "/submit", submission_mode="anonymous")
    if _step((await client.get("/submit")).text) == 2:
        page = (await client.get("/submit")).text
        assert orgs["a"].location.name not in page
        await _post(client, "/submit", location_id="")
    page = (await client.get("/submit")).text
    assert orgs["a"].category.slug not in page
    await _post(client, "/submit", category="financial_fraud")
    await _post(client, "/submit", description="A description long enough to pass.")
    await _post(client, "/submit")
    case = _CASE_RE.search((await _post(client, "/submit")).text)
    assert case
    assert (await _report(db_session, case.group(0))).org_id == default_id


@pytest.mark.asyncio
@pytest.mark.parametrize("which", ["unknown", "inactive"])
async def test_an_unknown_or_inactive_slug_is_a_styled_404(
    client: AsyncClient, orgs: dict[str, _Org], which: str
) -> None:
    slug = "no-such-org" if which == "unknown" else orgs["c"].org.slug
    resp = await client.get(f"/submit/{slug}", headers=_HTML)
    assert resp.status_code == 404
    assert resp.headers["content-type"].startswith("text/html")
    assert "<html" in resp.text
    csrf = _csrf((await client.get("/submit")).text)
    post = await client.post(
        f"/submit/{slug}", data={"csrf_token": csrf, "step": "1"}, headers=_HTML
    )
    assert post.status_code == 404


@pytest.mark.asyncio
async def test_with_multi_tenancy_off_only_the_default_slug_redirects(
    client: AsyncClient, db_session: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "multi_tenancy_enabled", False)
    other = Organisation(id=uuid.uuid4(), name="Off", slug=f"off-{uuid.uuid4().hex[:6]}")
    db_session.add(other)
    await db_session.commit()

    resp = await client.get(f"/submit/{settings.default_org_slug}", follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers["location"] == "/submit"
    assert (await client.get(f"/submit/{other.slug}", headers=_HTML)).status_code == 404
    page = (await client.get("/submit")).text
    assert 'action="/submit"' in page
    assert (await _post(client, "/submit", submission_mode="anonymous")).headers[
        "location"
    ] == "/submit"


@pytest.mark.asyncio
async def test_with_multi_tenancy_off_the_wizard_is_not_scoped(
    client: AsyncClient, orgs: dict[str, _Org], db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off means as before: every active category, and the default org files it."""
    monkeypatch.setattr(settings, "multi_tenancy_enabled", False)
    await _post(client, "/submit", submission_mode="anonymous")
    await _post(client, "/submit", location_id=str(orgs["a"].location.id))
    page = (await client.get("/submit")).text
    assert _step(page) == 3
    assert orgs["a"].category.slug in page and orgs["b"].category.slug in page


@pytest.mark.asyncio
async def test_the_language_switch_keeps_the_org_link(
    client: AsyncClient, orgs: dict[str, _Org]
) -> None:
    b = orgs["b"]
    page = (await client.get(b.path)).text
    resp = await client.post(
        "/set-language",
        data={"lang": "de", "next": b.path, "csrf_token": _csrf(page)},
        follow_redirects=False,
    )
    assert resp.headers["location"] == b.path
    assert f'href="{b.path}"' in page  # the nav's "Submit a report" stays on it


@pytest.mark.asyncio
async def test_restart_on_an_org_link_returns_to_it(
    client: AsyncClient, orgs: dict[str, _Org]
) -> None:
    b = orgs["b"]
    await _walk_to_review(client, b)
    page = (await client.get(b.path)).text
    assert f'action="{b.path}/restart"' in page
    resp = await client.post(
        f"{b.path}/restart", data={"csrf_token": _csrf(page)}, follow_redirects=False
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == b.path
    assert _step((await client.get(b.path)).text) == 1


@pytest.mark.asyncio
async def test_removing_an_attachment_on_an_org_link_returns_to_it(
    client: AsyncClient, orgs: dict[str, _Org]
) -> None:
    b = orgs["b"]
    await _walk_to_review(client, b)
    page = (await client.get(b.path)).text
    await client.post(
        b.path, data={"csrf_token": _csrf(page), "step": "6", "action": "back"},
        follow_redirects=False,
    )
    page = (await client.get(b.path)).text
    assert _step(page) == 5
    resp = await client.post(
        f"{b.path}/attachments/remove", data={"csrf_token": _csrf(page), "index": "0"},
        follow_redirects=False,
    )
    assert resp.status_code == 303
    assert resp.headers["location"] == b.path


# ── The double-submit guarantees on an org link ─────────────────────


def _slow_create(monkeypatch: pytest.MonkeyPatch, delay: float) -> None:
    from app.services import report as report_service

    real_create = report_service.create_report

    async def _slow(*args: object, **kwargs: object):  # type: ignore[no-untyped-def]
        await asyncio.sleep(delay)
        return await real_create(*args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(report_service, "create_report", _slow)


@pytest.mark.asyncio
async def test_concurrent_final_submits_on_an_org_link_create_one_report(
    client: AsyncClient, orgs: dict[str, _Org], db_session: AsyncSession,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    b = orgs["b"]
    _slow_create(monkeypatch, 0.3)
    await _walk_to_review(client, b)
    page = (await client.get(b.path)).text
    data = {"csrf_token": _csrf(page), "step": str(_step(page)), "action": "next"}
    before = await _count(db_session)

    first, second = await asyncio.gather(
        client.post(b.path, data=data), client.post(b.path, data=data)
    )
    assert await _count(db_session) == before + 1
    shown = []
    for resp in (first, second):
        case, pin = _CASE_RE.search(resp.text), _PIN_RE.search(resp.text)
        assert case and pin
        shown.append((case.group(0), pin.group(0)))
    assert shown[0] == shown[1]
    assert (await _report(db_session, shown[0][0])).org_id == b.org.id


@pytest.mark.asyncio
async def test_the_processing_page_checks_again_on_the_org_link(
    client: AsyncClient, orgs: dict[str, _Org], monkeypatch: pytest.MonkeyPatch
) -> None:
    import app.api.reports as reports
    from app.redis_client import get_redis

    b = orgs["b"]
    monkeypatch.setattr(reports, "_RESULT_WAIT_SECONDS", 0.3)
    await _walk_to_review(client, b)
    page = (await client.get(b.path)).text
    session_id = client.cookies.get("ow-submission-session")
    assert session_id
    assert await reports._claim_draft(await get_redis(), session_id)

    resp = await client.post(
        b.path, data={"csrf_token": _csrf(page), "step": "6", "action": "next"}
    )
    assert "still being processed" in resp.text
    assert f'href="{b.path}"' in resp.text  # "Check again"
    assert "still being processed" in (await client.get(b.path)).text


# ── Status page ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_the_status_page_never_names_the_org(
    client: AsyncClient, orgs: dict[str, _Org]
) -> None:
    b = orgs["b"]
    await _walk_to_review(client, b)
    done = (await _post(client, b.path)).text
    case, pin = _CASE_RE.search(done), _PIN_RE.search(done)
    assert case and pin
    csrf = _csrf((await client.get("/status")).text)
    wrong = await client.post(
        "/status", data={"case_number": case.group(0), "pin": str(uuid.uuid4()),
                         "csrf_token": csrf},
    )
    assert wrong.status_code == 401
    right = await client.post(
        "/status", data={"case_number": case.group(0), "pin": pin.group(0), "csrf_token": csrf},
    )
    assert right.status_code == 200
    for page in (wrong.text, right.text):
        assert b.org.name not in page
        assert b.org.slug not in page


@pytest.mark.asyncio
async def test_the_slug_restart_is_refused(client: AsyncClient) -> None:
    """/submit/restart is the wizard's own route: that org's wizard would be unreachable."""
    root = AdminUser(
        id=uuid.uuid4(), username=f"root_{uuid.uuid4().hex[:6]}", role=AdminRole.superadmin,
        is_active=True, totp_secret="JBSWY3DPEHPK3PXP", totp_enabled=True,
    )
    csrf = _csrf((await client.get("/submit")).text)
    app.dependency_overrides[get_current_admin] = lambda: root
    try:
        resp = await client.post(
            "/admin/organisations", data={"name": "Clash", "slug": "restart", "csrf_token": csrf},
            follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
    assert resp.status_code == 400


# ── DEFAULT_ORG_SLUG names the default organisation everywhere ──────


@pytest.mark.asyncio
async def test_the_configured_default_org_cannot_be_deactivated(
    client: AsyncClient, orgs: dict[str, _Org], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(settings, "default_org_slug", orgs["a"].org.slug)
    root = AdminUser(
        id=uuid.uuid4(), username=f"root_{uuid.uuid4().hex[:6]}", role=AdminRole.superadmin,
        is_active=True, totp_secret="JBSWY3DPEHPK3PXP", totp_enabled=True,
    )
    csrf = _csrf((await client.get("/submit")).text)
    app.dependency_overrides[get_current_admin] = lambda: root
    try:
        resp = await client.post(
            f"/admin/organisations/{orgs['a'].org.id}/deactivate",
            data={"csrf_token": csrf}, follow_redirects=False,
        )
    finally:
        app.dependency_overrides.pop(get_current_admin, None)
    assert resp.status_code == 400


@pytest.mark.asyncio
async def test_setup_creates_the_configured_default_org(
    throwaway_db: AsyncSession, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.api.wizard import create_initial_admin

    monkeypatch.setattr(settings, "default_org_slug", "acme")
    assert await create_initial_admin(throwaway_db, "first", "pw-" + "x" * 20, "JBSWY3DPEHPK3PXP")
    admin = (
        await throwaway_db.execute(select(AdminUser).where(AdminUser.username == "first"))
    ).scalar_one()
    org = await throwaway_db.get(Organisation, admin.org_id)
    assert org is not None and org.slug == "acme"
