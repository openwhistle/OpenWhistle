"""Shared Jinja2 templates instance — avoids circular imports."""

from fastapi.templating import Jinja2Templates

from app.config import settings

templates = Jinja2Templates(directory="app/templates")

templates.env.globals["brand"] = {
    "name": settings.app_name,
    "primary_color": settings.brand_primary_color,
    "secondary_color": settings.brand_secondary_color,
    "logo_url": settings.brand_logo_url,
}
