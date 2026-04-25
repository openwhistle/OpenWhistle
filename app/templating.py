"""Shared Jinja2 templates instance — avoids circular imports."""

from typing import Any

from fastapi import Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from markupsafe import Markup

from app.config import settings
from app.i18n import get_lang, make_translator
from app.services.attachment import format_size

templates = Jinja2Templates(directory="app/templates")

templates.env.filters["format_size"] = format_size

templates.env.globals["brand"] = {
    "name": settings.app_name,
    "primary_color": settings.brand_primary_color,
    "secondary_color": settings.brand_secondary_color,
    "logo_url": settings.brand_logo_url,
}


def render(
    request: Request,
    template: str,
    context: dict[str, Any] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    ctx: dict[str, Any] = dict(context or {})
    lang = get_lang(request)
    _t = make_translator(lang)

    def t(key: str, **kwargs: Any) -> str | Markup:
        result = _t(key, **kwargs)
        # Mark safe only for keys that explicitly contain HTML (suffixed .html)
        return Markup(result) if key.endswith(".html") else result  # noqa: S704

    ctx["t"] = t
    ctx["lang"] = lang
    return templates.TemplateResponse(request, template, ctx, status_code=status_code)
