"""Shared Jinja2 templates instance — avoids circular imports."""

import functools
import hashlib
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup, escape

from app.config import settings
from app.i18n import format_count, format_decimal, format_percent, get_lang, make_translator
from app.services import brand_colour, deadlines
from app.services.attachment import format_size
from app.services.categories import category_label
from app.services.report import format_day, whistleblower_caused

templates = Jinja2Templates(directory="app/templates")

templates.env.filters["format_size"] = format_size
templates.env.filters["day"] = format_day
templates.env.filters["format_count"] = format_count
templates.env.filters["format_percent"] = format_percent
templates.env.filters["format_decimal"] = format_decimal
templates.env.globals["whistleblower_caused"] = whistleblower_caused
# §17 HinSchG deadlines: the dashboard, the case page and the status page read
# the same computation (app/services/deadlines.py).
templates.env.globals["ack_status"] = deadlines.ack_status
templates.env.globals["feedback_status"] = deadlines.feedback_status


def wbr_after_hyphens(value: str) -> Markup:
    """Insert a `<wbr>` after each hyphen of an identifier (case number, PIN).

    A `<wbr>` is a wrap opportunity, never a forced break: the browser only
    uses it when the identifier does not fit its box, and only right after a
    hyphen, so a case number or PIN never breaks in the middle of a group.
    """
    return Markup("-<wbr>").join(escape(part) for part in str(value).split("-"))


templates.env.filters["wbr_after_hyphens"] = wbr_after_hyphens


templates.env.filters["category_label"] = category_label


def brand_tokens(primary: str) -> dict[str, str]:
    """The theme tokens for a brand colour; a misconfigured colour renders as the default."""
    try:
        return brand_colour.tokens(primary)
    except ValueError:
        return brand_colour.tokens(brand_colour.DEFAULT)


templates.env.globals["brand_tokens"] = brand_tokens

templates.env.globals["brand"] = {
    "name": settings.app_name,
    "primary_color": settings.brand_primary_color,
    "logo_url": settings.brand_logo_url,
}

templates.env.globals["is_demo"] = settings.demo_mode
templates.env.globals["privacy_policy_url"] = settings.privacy_policy_url
templates.env.globals["legal_notice_url"] = settings.legal_notice_url

# Installed version, available to every template (e.g. the footer).
templates.env.globals["app_version"] = settings.app_version


def static_url(path: str) -> str:
    """A cache-busted `/static/` URL for CSS, JS and font assets.

    `/static/` is served without cache-busting (see app/main.py), so a
    browser that visited before an upgrade keeps the old file. The content-hash
    query forces a fresh fetch; every stylesheet/script link must go through
    this helper rather than hand-typing `/static/...` (test_static_versioning.py).
    """
    return f"/static/{path}?v={_content_hash(path)}"


_STATIC_DIR = Path(__file__).resolve().parent / "static"


@functools.cache
def _content_hash(path: str) -> str:
    # The file's own hash, not the app version: ?v=2.3.0 told every visitor which
    # release runs here (OWASP ASVS 14.3.3), and a hash changes only with the file.
    return hashlib.sha256((_STATIC_DIR / path).read_bytes()).hexdigest()[:12]


templates.env.globals["static_url"] = static_url

# A callable (not the value) so templates re-read it at render time — tests
# that monkeypatch settings.onion_location must see the new value.
templates.env.globals["onion_location"] = lambda: settings.onion_location
templates.env.globals["oidc_enabled"] = lambda: settings.oidc_enabled


def sso_result(request: Request) -> str | None:
    """The linking outcome to show on the account page, only from the known set."""
    from app.services.oidc import SSO_RESULTS  # noqa: PLC0415

    value = request.query_params.get("sso")
    return value if value in SSO_RESULTS else None


templates.env.globals["sso_result"] = sso_result


def template_translator(lang: str) -> Callable[..., str | Markup]:
    """The ``t()`` templates call: a translator that marks HTML keys safe."""
    _t = make_translator(lang)

    def t(key: str, **kwargs: Any) -> str | Markup:
        result = _t(key, **kwargs)
        # Mark safe only for locale keys that explicitly contain HTML (suffixed
        # .html). A miss returns the key itself, and templates also pass plain
        # messages through t() — those must stay escaped whatever they end with.
        is_html = key.endswith(".html") and result != key
        return Markup(result) if is_html else result  # noqa: S704

    return t


# Audit detail keys whose value is stored encrypted (app.services.crypto).
ENCRYPTED_DETAIL_KEYS = ("reason", "term")

# Locale key shown in place of an encrypted reason that no longer decrypts.
REASON_UNREADABLE = "audit.detail.reason_unreadable"


def audit_detail(detail: str | None, decrypt: bool = True) -> list[tuple[str, str]]:
    """Split an audit entry's JSON detail into (key, value) pairs for display.

    Anything that is not a JSON object is returned as one pair with an empty
    key, so a legacy free-text detail still shows. Values stay plain strings;
    Jinja escapes them on output.
    """
    if not detail:
        return []
    try:
        data = json.loads(detail)
    except ValueError:
        return [("", detail)]
    if not isinstance(data, dict):
        return [("", detail)]
    return [(str(k), _detail_value(str(k), v, decrypt)) for k, v in data.items()]


def _detail_value(key: str, value: object, decrypt: bool) -> str:
    """An identity reveal's `reason` and a content search's `term` are Fernet tokens;
    the retention job's `reason` is plain text."""
    from app.services.crypto import decrypt_or_none  # noqa: PLC0415

    if value is None:
        return "—"
    text = str(value)
    if decrypt and key in ENCRYPTED_DETAIL_KEYS and text.startswith("gAAAAA"):
        return decrypt_or_none(text) or REASON_UNREADABLE
    return text


templates.env.filters["audit_detail"] = audit_detail
templates.env.globals["REASON_UNREADABLE"] = REASON_UNREADABLE


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    ctx: dict[str, Any] = dict(context or {})
    lang = get_lang(request)
    ctx["t"] = template_translator(lang)
    ctx["lang"] = lang

    session_expires_at = getattr(request.state, "session_expires_at", None)
    if session_expires_at is not None:
        ctx.setdefault("session_expires_at", session_expires_at)

    return templates.TemplateResponse(request, template, ctx, status_code=status_code)


# Admin navigation: (group label, ((href, label, minimum role), …)). None = every role.
_ADMIN_NAV: tuple[tuple[str, tuple[tuple[str, str, str | None], ...]], ...] = (
    (
        "admin.nav.group.cases",
        (
            ("/admin/dashboard", "admin.dashboard.title", None),
            ("/admin/stats", "admin.nav.stats", None),
            ("/admin/telephone-channel", "admin.nav.telephone_channel", None),
        ),
    ),
    (
        "admin.nav.group.setup",
        (
            ("/admin/categories", "admin.nav.categories", "admin"),
            ("/admin/locations", "admin.nav.locations", "admin"),
            ("/admin/retention", "admin.nav.retention", "admin"),
        ),
    ),
    (
        "admin.nav.group.administration",
        (
            ("/admin/users", "admin.nav.users", "admin"),
            ("/admin/audit-log", "admin.nav.audit_log", "admin"),
            ("/admin/organisations", "admin.nav.organisations", "tenants"),
            ("/admin/system", "admin.nav.system", "instance"),
        ),
    ),
)
_RANK = {"case_manager": 0, "admin": 1, "superadmin": 2}


def admin_nav(user: Any) -> list[dict[str, Any]]:
    """The groups and links this user may open; the routes enforce the same roles."""
    from app.api.deps import may_run_the_instance  # noqa: PLC0415

    rank = _RANK[user.role.value]
    groups = []
    for label, items in _ADMIN_NAV:
        allowed = [
            {"href": href, "label": item_label}
            for href, item_label, minimum in items
            if minimum is None
            or (
                may_run_the_instance(user)
                if minimum == "instance"
                # Organisations: a superadmin's, and only with multi-tenancy (require_tenants).
                else rank == 2 and settings.multi_tenancy_enabled
                if minimum == "tenants"
                else rank >= _RANK[minimum]
            )
        ]
        if allowed:
            groups.append({"label": label, "items": allowed})
    return groups


templates.env.globals["admin_nav"] = admin_nav
