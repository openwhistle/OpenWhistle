# Branding admin page: implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for
> tracking.

**Goal:** Operators brand the reporter's pages (name, light and dark logo, brand colour) on `/admin/branding`,
with a live preview, per organisation, without weakening the CSP or the reporter's anonymity.

**Architecture:** Two pure modules (`brand_colour`: WCAG tokens from a colour; `brand_image`: Pillow pipeline)
under a `branding` service that resolves organisation → instance default → environment → built-in, cached in
Redis. A global FastAPI dependency loads the cached snapshot per request; `render()` picks the organisation the
page serves. Images live in PostgreSQL, addressed by their SHA-256, served from `/branding/<sha>.png`.

**Tech Stack:** FastAPI, SQLAlchemy 2 async, Alembic, Redis, Jinja2, Pillow ≥ 12, vanilla JS, pytest,
Playwright.

**Spec:** `docs-tech/specs/2026-10-14-branding-page-design.md`

## Global Constraints

- Python and docs in English; markdownlint clean; ruff clean; `mypy app/ --strict` clean.
- Coverage ≥ 90 % (`--cov-fail-under=90`); tests run against real PostgreSQL and Redis
  (`DATABASE_URL`, `REDIS_URL`, `SECRET_KEY` set).
- CSP stays `style-src 'self' 'nonce-…'`, `img-src 'self' data:`: never `'unsafe-inline'`, never `blob:`.
- Logo: PNG, JPEG or WebP; at most 1 MB upload; at most 16 megapixels; stored as PNG, 96 px high, no metadata.
- Colour input `^#[0-9a-fA-F]{6}$`, stored lower case; derived link/accent colours ≥ 4.5:1 on their canvas
  (light `#ffffff`, dark `#0a0a0b`); text on brand fills ≥ 4.5:1.
- Default colour `#0c7253` yields exactly DESIGN.md's tokens.
- The footer is not brandable.
- Every user-facing string in all five locales (`en`, `de`, `es`, `fr`, `pt-br`); German uses "Sie".
- Every new guard goes through `scripts/mutation_audit.py` and must go RED.
- Commits end with the two attribution lines; messages never mention Claude Code.

## Review Focus

1. **The same logo uploaded for two organisations** → one `brand_images` row, and removing it from one keeps
   it for the other (Task 4 test `test_a_shared_image_survives_its_removal_elsewhere`).
2. **A very wide or very tall logo** (4000 × 50, 50 × 4000) → neither the nav nor the preview overflows at
   390 px (Task 5 `test_a_logo_cannot_widen_the_nav`, Task 8 e2e `test_a_wide_logo_never_widens_the_nav`).
3. **Redis down or the cache holding garbage** → pages still render with the environment branding
   (Task 5 test `test_a_broken_cache_falls_back_to_the_environment`).
4. **A colour as light as `#ffffff` or as dark as `#000000`** → derived tokens still meet 4.5:1
   (Task 1 test `test_extremes_still_meet_aa`).
5. **An organisation admin posting another organisation's id in the form** → 403, nothing saved
   (Task 7 test `test_an_org_admin_cannot_brand_another_org`).

---

## File structure

| File | Responsibility |
|---|---|
| `app/services/brand_colour.py` (new) | Hex parsing, WCAG luminance and contrast, token derivation |
| `app/services/brand_image.py` (new) | Upload validation, re-encode to PNG, favicons |
| `app/models/branding.py` (new) | `Branding` row per organisation (or default), `BrandImage` by SHA-256 |
| `migrations/versions/018_branding.py` (new) | Both tables, partial unique index for the default row |
| `app/services/branding.py` (new) | Snapshot cache, resolution, image store, orphan cleanup, global dependency |
| `app/api/branding.py` (new) | `/branding/<sha>.png`, `/admin/branding` GET/POST, `/admin/branding/reset` |
| `app/templates/admin/branding.html` (new) | Form and preview |
| `app/static/js/branding.js` (new) | Live preview, client-side ratios |
| `app/templating.py`, `app/templates/base.html`, `app/static/css/site.css`, `app/middleware.py`, `app/main.py`, `app/api/deps.py`, `app/api/reports.py` | Wiring |

---

### Task 1: Colour tokens

**Files:**

- Create: `app/services/brand_colour.py`
- Modify: `app/templating.py` (remove `_DESIGN_ACCENT` and `brand_accent`), `app/templates/base.html:22-27`,
  `app/static/css/site.css:224,228,290,294`
- Test: `tests/test_brand_colour.py`

**Interfaces:**

- Produces: `parse(value: str) -> str` (raises `ValueError`), `contrast(a: str, b: str) -> float`,
  `tokens(primary: str) -> dict[str, str]` with keys `accent`, `on`, `accent-dark`, `on-dark` (default colour:
  also `accent-weak`, `accent-strong`, `accent-weak-dark`, `accent-strong-dark`), constants `DEFAULT`,
  `LIGHT_CANVAS`, `DARK_CANVAS`, `TEXT_MINIMUM`.

- [ ] **Step 1: Write the failing tests**

```python
"""A brand colour's theme tokens meet WCAG AA in both themes (spec: Colour)."""

from __future__ import annotations

import random

import pytest

from app.services import brand_colour as bc


def test_the_default_keeps_design_md_values() -> None:
    assert bc.tokens("#0c7253") == {
        "accent": "#0c7253",
        "on": "#ffffff",
        "accent-weak": "#e5f3ee",
        "accent-strong": "#0b6249",
        "accent-dark": "#23c088",
        "on-dark": "#06120d",
        "accent-weak-dark": "#0d211a",
        "accent-strong-dark": "#1fa878",
    }


def test_contrast_matches_wcag() -> None:
    assert round(bc.contrast("#000000", "#ffffff"), 2) == 21.0
    assert round(bc.contrast("#777777", "#ffffff"), 2) == 4.48


@pytest.mark.parametrize("value", ["0c7253", "#0c725", "#0c72533", "#gggggg", "", "red"])
def test_parse_refuses_anything_but_rrggbb(value: str) -> None:
    with pytest.raises(ValueError):
        bc.parse(value)


def test_parse_normalises_case_and_space() -> None:
    assert bc.parse(" #0C7253 ") == "#0c7253"


def _meets(primary: str) -> None:
    t = bc.tokens(primary)
    assert bc.contrast(t["accent"], bc.LIGHT_CANVAS) >= bc.TEXT_MINIMUM, (primary, t)
    assert bc.contrast(t["on"], t["accent"]) >= bc.TEXT_MINIMUM, (primary, t)
    assert bc.contrast(t["accent-dark"], bc.DARK_CANVAS) >= bc.TEXT_MINIMUM, (primary, t)
    assert bc.contrast(t["on-dark"], t["accent-dark"]) >= bc.TEXT_MINIMUM, (primary, t)


def test_two_hundred_colours_meet_aa_in_both_themes() -> None:
    rng = random.Random(20261014)
    for _ in range(200):
        _meets("#%06x" % rng.randrange(0x1000000))


@pytest.mark.parametrize("primary", ["#ffffff", "#000000", "#ffff00", "#0000ff", "#777777"])
def test_extremes_still_meet_aa(primary: str) -> None:
    _meets(primary)
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_brand_colour.py -q --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.services.brand_colour'`

- [ ] **Step 3: Implement `app/services/brand_colour.py`**

```python
"""A brand colour and the theme tokens derived from it, by WCAG 2.x contrast.

base.html emits the tokens as --brand-<name> custom properties; site.css reads
them for links, focus rings, outlines and the primary button in both themes.
"""

from __future__ import annotations

import re

DEFAULT = "#0c7253"
LIGHT_CANVAS = "#ffffff"
DARK_CANVAS = "#0a0a0b"
WHITE = "#ffffff"
BLACK = "#000000"
# WCAG 2.2 SC 1.4.3 for text; it also covers SC 1.4.11's 3:1 for focus and outlines.
TEXT_MINIMUM = 4.5

_HEX = re.compile(r"#[0-9a-f]{6}")

# DESIGN.md's emerald, exactly as specified there; any other colour is computed.
DESIGN_TOKENS = {
    "accent": "#0c7253",
    "on": "#ffffff",
    "accent-weak": "#e5f3ee",
    "accent-strong": "#0b6249",
    "accent-dark": "#23c088",
    "on-dark": "#06120d",
    "accent-weak-dark": "#0d211a",
    "accent-strong-dark": "#1fa878",
}


def parse(value: str) -> str:
    colour = value.strip().lower()
    if not _HEX.fullmatch(colour):
        raise ValueError("a colour is written #rrggbb")
    return colour


def _channels(colour: str) -> tuple[int, int, int]:
    return int(colour[1:3], 16), int(colour[3:5], 16), int(colour[5:7], 16)


def luminance(colour: str) -> float:
    def linear(channel: int) -> float:
        s = channel / 255
        return s / 12.92 if s <= 0.04045 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = (linear(c) for c in _channels(colour))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contrast(a: str, b: str) -> float:
    high, low = sorted((luminance(a), luminance(b)), reverse=True)
    return (high + 0.05) / (low + 0.05)


def _mix(colour: str, toward: str, share: float) -> str:
    pairs = zip(_channels(colour), _channels(toward), strict=True)
    return "#" + "".join(f"{round(c + (t - c) * share):02x}" for c, t in pairs)


def _on(fill: str) -> str:
    # Pure black, not the ink: with #0a0a0b the worst mid-grey reached only 4.44:1.
    return WHITE if contrast(fill, WHITE) >= contrast(fill, BLACK) else BLACK


def _readable(colour: str, canvas: str, toward: str) -> str:
    for step in range(51):
        candidate = _mix(colour, toward, step / 50)
        if contrast(candidate, canvas) >= TEXT_MINIMUM:
            return candidate
    return toward


def tokens(primary: str) -> dict[str, str]:
    colour = parse(primary)
    if colour == DEFAULT:
        return dict(DESIGN_TOKENS)
    light = _readable(colour, LIGHT_CANVAS, BLACK)
    dark = _readable(colour, DARK_CANVAS, WHITE)
    return {"accent": light, "on": _on(light), "accent-dark": dark, "on-dark": _on(dark)}
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_brand_colour.py -q --no-cov`
Expected: PASS (11 passed)

- [ ] **Step 5: Wire the tokens into the theme**

In `app/static/css/site.css`, light `:root` block (line 224 and 228):

```css
  --accent: var(--brand-accent, var(--brand-primary));
```

```css
  --cta-text: var(--brand-on, #fff);
```

Dark block (line 294):

```css
  --cta-text: var(--brand-on-dark, #06120d);
```

In `app/templating.py` delete `_DESIGN_ACCENT`, `brand_accent` and its `templates.env.globals["brand_accent"]`
line. In `app/templates/base.html` replace the loop at lines 24-26 with:

```jinja
            {%- for name, value in brand_tokens(brand.primary_color).items() %}
            --brand-{{ name }}: {{ value }};
            {%- endfor %}
```

and register in `app/templating.py` after the `brand` global:

```python
from app.services import brand_colour  # top of file, with the other app.services imports

templates.env.globals["brand_tokens"] = brand_colour.tokens
```

(Task 5 replaces `brand_tokens(brand.primary_color)` with `brand.tokens`.)

- [ ] **Step 6: Run the theme guards**

Run: `grep -rn "brand_accent\|_DESIGN_ACCENT" app tests` → no output.
Run:

```bash
pytest -q --no-cov tests/test_brand_colour.py tests/test_site_css.py tests/test_design_md.py tests/test_v160_design.py tests/test_mark.py
```

Expected: PASS. A test that imported `brand_accent` is updated to `brand_colour.tokens`, same assertion.

- [ ] **Step 7: Commit**

```bash
git add app/services/brand_colour.py tests/test_brand_colour.py app/templating.py app/templates/base.html app/static/css/site.css
git commit -m "feat: derive AA theme tokens from any brand colour"
```

---

### Task 2: Logo pipeline

**Files:**

- Create: `app/services/brand_image.py`
- Test: `tests/test_brand_image.py`

**Interfaces:**

- Produces: `class BrandImageError(ValueError)` with attribute `key: str` (a locale key);
  `process_logo(data: bytes) -> bytes` (PNG); `favicon(png: bytes, size: int) -> bytes` (PNG, square);
  constants `MAX_BYTES = 1_000_000`, `MAX_PIXELS = 16_000_000`, `HEIGHT = 96`.

- [ ] **Step 1: Write the failing tests**

```python
"""The logo pipeline: content-checked, re-encoded, stripped, bounded (spec: Logo pipeline)."""

from __future__ import annotations

import io
import struct
import zlib

import pytest
from PIL import Image
from PIL.PngImagePlugin import PngInfo

from app.services import brand_image as bi


def _image(fmt: str, size: tuple[int, int] = (400, 200), **save: object) -> bytes:
    out = io.BytesIO()
    Image.new("RGB", size, (12, 114, 83)).save(out, format=fmt, **save)
    return out.getvalue()


def _png_claiming(width: int, height: int) -> bytes:
    def chunk(kind: bytes, body: bytes) -> bytes:
        return (
            struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))
        )

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IEND", b"")


@pytest.mark.parametrize("fmt", ["PNG", "JPEG", "WEBP"])
def test_each_allowed_format_becomes_a_png_96_px_high(fmt: str) -> None:
    out = Image.open(io.BytesIO(bi.process_logo(_image(fmt))))
    assert out.format == "PNG" and out.height == 96 and out.width == 192


def test_a_small_logo_is_not_upscaled() -> None:
    out = Image.open(io.BytesIO(bi.process_logo(_image("PNG", (60, 30)))))
    assert out.size == (60, 30)


def test_metadata_does_not_survive() -> None:
    info = PngInfo()
    info.add_text("Author", "secret-author")
    exif = Image.Exif()
    exif[0x010E] = "secret-description"
    png = bi.process_logo(_image("PNG", pnginfo=info))
    jpg = bi.process_logo(_image("JPEG", exif=exif.tobytes()))
    for out in (png, jpg):
        assert b"secret" not in out
        assert not Image.open(io.BytesIO(out)).info.get("exif")


@pytest.mark.parametrize(
    ("data", "key"),
    [
        (b"<svg xmlns='http://www.w3.org/2000/svg'/>", "admin.branding.error.format"),
        (b"<html><script>alert(1)</script></html>", "admin.branding.error.format"),
        (_image("GIF"), "admin.branding.error.format"),
        (b"\x89PNG" + b"\0" * (bi.MAX_BYTES + 1), "admin.branding.error.too_large"),
        (_png_claiming(20_000, 20_000), "admin.branding.error.dimensions"),
    ],
)
def test_refused_uploads(data: bytes, key: str) -> None:
    with pytest.raises(bi.BrandImageError) as caught:
        bi.process_logo(data)
    assert caught.value.key == key


@pytest.mark.parametrize("size", [32, 180])
def test_a_favicon_is_square(size: int) -> None:
    out = Image.open(io.BytesIO(bi.favicon(bi.process_logo(_image("PNG")), size)))
    assert out.size == (size, size) and out.format == "PNG"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_brand_image.py -q --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.services.brand_image'`

- [ ] **Step 3: Implement `app/services/brand_image.py`**

```python
"""Operator logos: the content decides the type, Pillow re-encodes, nothing but pixels survives.

OWASP File Upload Cheat Sheet: allow-list the types, check the content not the
name, re-encode, drop metadata, bound the size. No SVG: a direct request runs
its scripts (GlobaLeaks, SecureDrop and Hush Line accept none either).
"""

from __future__ import annotations

import io

from PIL import Image, ImageOps, UnidentifiedImageError

MAX_BYTES = 1_000_000
MAX_PIXELS = 16_000_000
HEIGHT = 96  # the nav shows 32 px; three times that for dense screens
_FORMATS = {"PNG", "JPEG", "WEBP"}


class BrandImageError(ValueError):
    def __init__(self, key: str) -> None:
        super().__init__(key)
        self.key = key


def _png(image: Image.Image) -> bytes:
    out = io.BytesIO()
    image.save(out, format="PNG", optimize=True)
    return out.getvalue()


def process_logo(data: bytes) -> bytes:
    if len(data) > MAX_BYTES:
        raise BrandImageError("admin.branding.error.too_large")
    try:
        with Image.open(io.BytesIO(data)) as source:
            if source.format not in _FORMATS:
                raise BrandImageError("admin.branding.error.format")
            # Before any pixel is decoded: the header names the size.
            if source.width * source.height > MAX_PIXELS:
                raise BrandImageError("admin.branding.error.dimensions")
            image = ImageOps.exif_transpose(source).convert("RGBA")
    except (UnidentifiedImageError, OSError, Image.DecompressionBombError) as exc:
        raise BrandImageError("admin.branding.error.format") from exc
    if image.height > HEIGHT:
        width = max(1, round(image.width * HEIGHT / image.height))
        image = image.resize((width, HEIGHT), Image.Resampling.LANCZOS)
    return _png(image)


def favicon(png: bytes, size: int) -> bytes:
    with Image.open(io.BytesIO(png)) as source:
        logo = source.convert("RGBA")
    logo.thumbnail((size, size), Image.Resampling.LANCZOS)
    square = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    square.paste(logo, ((size - logo.width) // 2, (size - logo.height) // 2), logo)
    return _png(square)
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_brand_image.py -q --no-cov`
Expected: PASS (12 passed). If `WEBP` fails with "encoder not available", the image lacks libwebp:
check `python -c "from PIL import features; print(features.check('webp'))"`; it is `True` in the
`python:3.15-alpine` image and the dev venv.

- [ ] **Step 5: Commit**

```bash
git add app/services/brand_image.py tests/test_brand_image.py
git commit -m "feat: re-encode operator logos as stripped, bounded PNGs"
```

---

### Task 3: Tables

**Files:**

- Create: `app/models/branding.py`, `migrations/versions/018_branding.py`
- Modify: `app/models/__init__.py`
- Test: `tests/test_branding_model.py`

**Interfaces:**

- Produces: `class BrandImage(Base)` (`sha256: str` PK, `png: bytes`); `class Branding(Base)` (`id`, `org_id:
  uuid.UUID | None`, `name: str | None`, `primary_color: str | None`, `logo_light`, `logo_dark`, `favicon_32`,
  `favicon_180: str | None` (SHA-256 hex, FK `brand_images.sha256`), `updated_at`, `updated_by_id`).
  `Branding.IMAGE_FIELDS = ("logo_light", "logo_dark", "favicon_32", "favicon_180")`.

> Refines the spec's data model: images live in their own table keyed by hash, so one image shared by two
> organisations is stored once and the public URL is the primary key. Update the spec's "Data model" section
> in this task's commit.

- [ ] **Step 1: Write the failing test**

```python
"""One default row at most; images by hash (spec: Data model)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branding import Branding


async def test_there_is_one_default_row_at_most(db_session: AsyncSession) -> None:
    db_session.add(Branding(id=uuid.uuid4(), org_id=None, name="A"))
    await db_session.commit()
    db_session.add(Branding(id=uuid.uuid4(), org_id=None, name="B"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_branding_model.py -q --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.models.branding'`

- [ ] **Step 3: Implement `app/models/branding.py`**

```python
"""Operator branding: one row per organisation, one default row (org_id NULL), images by hash."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

from sqlalchemy import DateTime, ForeignKey, Index, LargeBinary, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class BrandImage(Base):
    __tablename__ = "brand_images"

    # The PNG's own SHA-256: the public URL, so it names no organisation.
    sha256: Mapped[str] = mapped_column(String(64), primary_key=True)
    png: Mapped[bytes] = mapped_column(LargeBinary, nullable=False)


def _image_ref() -> Mapped[str | None]:
    return mapped_column(String(64), ForeignKey("brand_images.sha256"), nullable=True)


class Branding(Base):
    __tablename__ = "branding"
    __table_args__ = (
        Index(
            "uq_branding_default",
            text("(org_id IS NULL)"),
            unique=True,
            postgresql_where=text("org_id IS NULL"),
        ),
    )

    IMAGE_FIELDS = ("logo_light", "logo_dark", "favicon_32", "favicon_180")

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=uuid.uuid4)
    org_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True),
        ForeignKey("organisations.id", ondelete="CASCADE"),
        unique=True,
        nullable=True,
    )
    name: Mapped[str | None] = mapped_column(String(64), nullable=True)
    primary_color: Mapped[str | None] = mapped_column(String(7), nullable=True)
    logo_light: Mapped[str | None] = _image_ref()
    logo_dark: Mapped[str | None] = _image_ref()
    favicon_32: Mapped[str | None] = _image_ref()
    favicon_180: Mapped[str | None] = _image_ref()
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, default=lambda: datetime.now(UTC)
    )
    updated_by_id: Mapped[uuid.UUID | None] = mapped_column(
        UUID(as_uuid=True), ForeignKey("admin_users.id", ondelete="SET NULL"), nullable=True
    )
```

Add to `app/models/__init__.py`: `from app.models.branding import BrandImage, Branding` and both names to
`__all__` (alphabetical).

- [ ] **Step 4: Write `migrations/versions/018_branding.py`**

```python
"""Operator branding: one row per organisation and one default, images by hash.

Revision ID: c3e9a2d5f417
Revises: b8d5f1a7c214
Create Date: 2026-10-14
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "c3e9a2d5f417"
down_revision: str | None = "b8d5f1a7c214"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "downgrade", "revision", "upgrade"]

_IMAGES = ("logo_light", "logo_dark", "favicon_32", "favicon_180")


def upgrade() -> None:
    op.create_table(
        "brand_images",
        sa.Column("sha256", sa.String(64), primary_key=True),
        sa.Column("png", sa.LargeBinary(), nullable=False),
    )
    op.create_table(
        "branding",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column(
            "org_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("organisations.id", ondelete="CASCADE"),
            nullable=True,
            unique=True,
        ),
        sa.Column("name", sa.String(64), nullable=True),
        sa.Column("primary_color", sa.String(7), nullable=True),
        *(
            sa.Column(name, sa.String(64), sa.ForeignKey("brand_images.sha256"), nullable=True)
            for name in _IMAGES
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "updated_by_id",
            postgresql.UUID(as_uuid=True),
            sa.ForeignKey("admin_users.id", ondelete="SET NULL"),
            nullable=True,
        ),
    )
    op.create_index(
        "uq_branding_default",
        "branding",
        [sa.text("(org_id IS NULL)")],
        unique=True,
        postgresql_where=sa.text("org_id IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_branding_default", table_name="branding")
    op.drop_table("branding")
    op.drop_table("brand_images")
```

- [ ] **Step 5: Run to verify it passes**

Run: `pytest tests/test_branding_model.py -q --no-cov` (the session fixture runs `alembic upgrade head`)
Expected: PASS. Then `alembic downgrade -1 && alembic upgrade head` against the test database: both succeed.

- [ ] **Step 6: Commit**

```bash
git add app/models/branding.py app/models/__init__.py migrations/versions/018_branding.py tests/test_branding_model.py docs-tech/specs/2026-10-14-branding-page-design.md
git commit -m "feat: branding and brand image tables"
```

---

### Task 4: Branding service

**Files:**

- Create: `app/services/branding.py`
- Test: `tests/test_branding_service.py`

**Interfaces:**

- Consumes: `brand_colour.parse`, `brand_colour.tokens`, `brand_colour.DEFAULT`, `Branding`, `BrandImage`.
- Produces:
  - `@dataclass(frozen=True) class Brand`: `name: str`, `primary_color: str`, `logo_url: str`,
    `logo_dark_url: str`, `favicon_32_url: str`, `favicon_180_url: str`, `tokens: dict[str, str]`
    (`logo_url == ""` means the OpenWhistle mark).
  - `Snapshot = dict[str, dict[str, str | None]]` keyed by `"default"` or `str(org_id)`.
  - `async def snapshot(redis: Redis) -> Snapshot`; `async def invalidate(redis: Redis) -> None`.
  - `def resolve(snap: Snapshot, org_id: uuid.UUID | None) -> Brand`.
  - `async def store_image(db: AsyncSession, png: bytes) -> str` (returns the SHA-256).
  - `async def find_row(db: AsyncSession, org_id: uuid.UUID | None) -> Branding | None` (read only).
  - `async def row_for(db: AsyncSession, org_id: uuid.UUID | None) -> Branding` (existing or new, added).
  - `async def drop_orphan_images(db: AsyncSession) -> None`.
  - `async def image(db: AsyncSession, sha: str) -> bytes | None`.
  - `CACHE_KEY = "branding:snapshot"`.

- [ ] **Step 1: Write the failing tests**

```python
"""Resolution order and the image store (spec: Resolution)."""

from __future__ import annotations

import uuid

import pytest
from redis.asyncio import Redis
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.branding import BrandImage
from app.redis_client import get_redis
from app.services import branding


def test_without_rows_the_environment_decides(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "app_name", "Env Name")
    monkeypatch.setattr(settings, "brand_primary_color", "#123456")
    monkeypatch.setattr(settings, "brand_logo_url", "/static/env.png")
    brand = branding.resolve({}, None)
    assert (brand.name, brand.primary_color, brand.logo_url) == (
        "Env Name",
        "#123456",
        "/static/env.png",
    )


def test_an_org_field_beats_the_default_and_an_empty_one_falls_back() -> None:
    org = uuid.uuid4()
    snap = {
        "default": {"name": "Default", "primary_color": "#111111", "logo_light": "a" * 64},
        str(org): {"name": "Org", "primary_color": None, "logo_light": None},
    }
    brand = branding.resolve(snap, org)
    assert brand.name == "Org"
    assert brand.primary_color == "#111111"
    assert brand.logo_url == f"/branding/{'a' * 64}.png"


def test_the_dark_logo_comes_from_the_row_whose_light_logo_is_shown() -> None:
    org = uuid.uuid4()
    snap = {
        "default": {"logo_light": "a" * 64, "logo_dark": "b" * 64},
        str(org): {"logo_light": "c" * 64, "logo_dark": None},
    }
    brand = branding.resolve(snap, org)
    assert brand.logo_url.endswith("c" * 64 + ".png") and brand.logo_dark_url == ""


def test_a_stored_colour_that_is_not_hex_falls_back_to_the_default() -> None:
    assert branding.resolve({"default": {"primary_color": "red"}}, None).primary_color == "#0c7253"


async def test_the_snapshot_reflects_a_save_after_invalidate(db_session: AsyncSession) -> None:
    redis: Redis = await get_redis()
    await branding.invalidate(redis)
    assert "default" not in await branding.snapshot(redis)
    row = await branding.row_for(db_session, None)
    row.name = "Saved"
    await db_session.commit()
    assert "default" not in await branding.snapshot(redis)  # still cached
    await branding.invalidate(redis)
    assert (await branding.snapshot(redis))["default"]["name"] == "Saved"


async def test_a_shared_image_survives_its_removal_elsewhere(db_session: AsyncSession) -> None:
    from app.models.organisation import Organisation

    org = Organisation(id=uuid.uuid4(), name="Org", slug=f"org-{uuid.uuid4().hex[:6]}")
    db_session.add(org)
    sha = await branding.store_image(db_session, b"\x89PNG-shared")
    default = await branding.row_for(db_session, None)
    own = await branding.row_for(db_session, org.id)
    default.logo_light = own.logo_light = sha
    await db_session.commit()
    own.logo_light = None
    await branding.drop_orphan_images(db_session)
    await db_session.commit()
    assert await branding.image(db_session, sha) == b"\x89PNG-shared"
    default.logo_light = None
    await branding.drop_orphan_images(db_session)
    await db_session.commit()
    assert await db_session.scalar(select(func.count()).select_from(BrandImage)) == 0
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_branding_service.py -q --no-cov`
Expected: FAIL, `ModuleNotFoundError: No module named 'app.services.branding'`

- [ ] **Step 3: Implement `app/services/branding.py`**

```python
"""Operator branding: the cached snapshot, resolution order, and the image store.

Resolution, per field: the organisation's row, the default row, the
environment (APP_NAME, BRAND_PRIMARY_COLOR, BRAND_LOGO_URL), the built-in.
The light logo, the dark logo and the favicons always come from one row.
"""

from __future__ import annotations

import hashlib
import json
import logging
import uuid
from dataclasses import dataclass, field
from typing import Any

from redis.asyncio import Redis
from sqlalchemy import delete, select, union
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.branding import BrandImage, Branding
from app.services import brand_colour

CACHE_KEY = "branding:snapshot"
CACHE_SECONDS = 3600
_FIELDS = ("name", "primary_color", *Branding.IMAGE_FIELDS)

Snapshot = dict[str, dict[str, str | None]]

log = logging.getLogger(__name__)


@dataclass(frozen=True)
class Brand:
    name: str
    primary_color: str
    logo_url: str
    logo_dark_url: str = ""
    favicon_32_url: str = ""
    favicon_180_url: str = ""
    tokens: dict[str, str] = field(default_factory=dict)


def _url(sha: str | None) -> str:
    return f"/branding/{sha}.png" if sha else ""


def resolve(snap: Snapshot, org_id: uuid.UUID | None) -> Brand:
    own = snap.get(str(org_id), {}) if org_id else {}
    base = snap.get("default", {})
    images = own if own.get("logo_light") else base
    try:
        colour = brand_colour.parse(
            own.get("primary_color") or base.get("primary_color") or settings.brand_primary_color
        )
    except ValueError:
        colour = brand_colour.DEFAULT
    return Brand(
        name=own.get("name") or base.get("name") or settings.app_name,
        primary_color=colour,
        logo_url=_url(images.get("logo_light")) or settings.brand_logo_url,
        logo_dark_url=_url(images.get("logo_dark")),
        favicon_32_url=_url(images.get("favicon_32")),
        favicon_180_url=_url(images.get("favicon_180")),
        tokens=brand_colour.tokens(colour),
    )


async def _load() -> Snapshot:
    from app.database import AsyncSessionLocal  # noqa: PLC0415

    async with AsyncSessionLocal() as db:
        rows = (await db.scalars(select(Branding))).all()
    return {
        (str(row.org_id) if row.org_id else "default"): {f: getattr(row, f) for f in _FIELDS}
        for row in rows
    }


async def snapshot(redis: Redis) -> Snapshot:
    cached = await redis.get(CACHE_KEY)
    if cached:
        data: Any = json.loads(cached)
        if isinstance(data, dict):
            return data
    snap = await _load()
    await redis.set(CACHE_KEY, json.dumps(snap), ex=CACHE_SECONDS)
    return snap


async def invalidate(redis: Redis) -> None:
    await redis.delete(CACHE_KEY)


async def find_row(db: AsyncSession, org_id: uuid.UUID | None) -> Branding | None:
    where = Branding.org_id.is_(None) if org_id is None else Branding.org_id == org_id
    return await db.scalar(select(Branding).where(where))


async def row_for(db: AsyncSession, org_id: uuid.UUID | None) -> Branding:
    row = await find_row(db, org_id)
    if row is None:
        row = Branding(id=uuid.uuid4(), org_id=org_id)
        db.add(row)
    return row


async def store_image(db: AsyncSession, png: bytes) -> str:
    sha = hashlib.sha256(png).hexdigest()
    if await db.get(BrandImage, sha) is None:
        db.add(BrandImage(sha256=sha, png=png))
        await db.flush()
    return sha


async def drop_orphan_images(db: AsyncSession) -> None:
    await db.flush()
    columns = [getattr(Branding, name) for name in Branding.IMAGE_FIELDS]
    used = union(*(select(c).where(c.is_not(None)) for c in columns)).subquery()
    await db.execute(delete(BrandImage).where(BrandImage.sha256.not_in(select(used.c[0]))))


async def image(db: AsyncSession, sha: str) -> bytes | None:
    found = await db.get(BrandImage, sha)
    return found.png if found else None
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_branding_service.py -q --no-cov`
Expected: PASS (6 passed)

- [ ] **Step 5: Commit**

```bash
git add app/services/branding.py tests/test_branding_service.py
git commit -m "feat: branding resolution, snapshot cache and image store"
```

---

### Task 5: Every page wears its organisation's branding

**Files:**

- Modify: `app/main.py` (`create_app`: global dependency), `app/templating.py` (`render`, the `brand` global),
  `app/templates/base.html` (head tokens, favicons, nav logo), `app/static/css/site.css` (nav logo),
  `app/api/deps.py` (`get_signed_in_admin`), `app/api/reports.py` (`_tenant`)
- Modify tests that monkeypatch `templates.env.globals["brand"]`: `tests/test_mark.py`,
  `tests/test_v230_bug_bounty.py`, `tests/test_footer.py` (set `settings.app_name` / `settings.brand_logo_url`
  instead; `grep -rn 'globals\["brand"\]' tests` lists them)
- Test: `tests/test_branding_pages.py`

**Interfaces:**

- Consumes: `branding.snapshot`, `branding.resolve`, `Brand`.
- Produces: `async def load_branding(request: Request) -> None` in `app/services/branding.py` (sets
  `request.state.branding_snapshot`); `request.state.org_id` set by `_tenant` and `get_signed_in_admin`;
  `render()` puts `brand` (a `Brand`) into every context.

- [ ] **Step 1: Write the failing tests**

```python
"""Pages show the branding of the organisation they serve (spec: Resolution)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.organisation import Organisation
from app.redis_client import get_redis
from app.services import branding


async def _brand(db: AsyncSession, org_id: uuid.UUID | None, **fields: str) -> None:
    row = await branding.row_for(db, org_id)
    for key, value in fields.items():
        setattr(row, key, value)
    await db.commit()
    await branding.invalidate(await get_redis())


async def test_the_default_row_names_the_wizard(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    await _brand(db_session, None, name="Acme Reports")
    html = (await client.get("/submit")).text
    assert '<span translate="no">Acme Reports</span>' in html
    assert "<title>" in html and "Acme Reports</title>" in html


async def test_an_organisations_wizard_wears_its_own(
    client: AsyncClient, db_session: AsyncSession, tenants: None
) -> None:
    mine = Organisation(id=uuid.uuid4(), name="Mine", slug=f"mine-{uuid.uuid4().hex[:6]}")
    other = Organisation(id=uuid.uuid4(), name="Other", slug=f"other-{uuid.uuid4().hex[:6]}")
    db_session.add_all([mine, other])
    await db_session.commit()
    await _brand(db_session, None, name="Default Brand")
    await _brand(db_session, mine.id, name="Mine Brand", primary_color="#aa3300")
    assert "Mine Brand" in (await client.get(f"/submit/{mine.slug}")).text
    other_html = (await client.get(f"/submit/{other.slug}")).text
    assert "Default Brand" in other_html and "Mine Brand" not in other_html


async def test_a_broken_cache_falls_back_to_the_environment(
    client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    redis = await get_redis()
    await redis.set(branding.CACHE_KEY, "not json")
    from app.config import settings

    monkeypatch.setattr(settings, "app_name", "Env Fallback")
    response = await client.get("/submit")
    await branding.invalidate(redis)
    assert response.status_code == 200 and "Env Fallback" in response.text


async def test_the_nav_logo_is_decorative(client: AsyncClient, db_session: AsyncSession) -> None:
    await _brand(db_session, None, name="Acme")
    from app.config import settings

    html_with = (await client.get("/submit")).text
    assert 'alt="' + settings.app_name not in html_with
    sha = await branding.store_image(db_session, b"\x89PNG-logo")
    await _brand(db_session, None, logo_light=sha)
    html = (await client.get("/submit")).text
    assert f'<img src="/branding/{sha}.png" alt="" class="nav-logo-img nav-logo-light"' in html


def test_a_logo_cannot_widen_the_nav() -> None:
    import re
    from pathlib import Path

    css = Path("app/static/css/site.css").read_text(encoding="utf-8")
    rule = re.search(r"(?m)^\.nav-logo-img \{([^}]*)\}", css)
    assert rule and "max-width: min(12rem, 40vw);" in rule.group(1)


async def test_no_page_needs_unsafe_inline(client: AsyncClient, db_session: AsyncSession) -> None:
    await _brand(db_session, None, primary_color="#aa3300")
    response = await client.get("/submit")
    assert "unsafe-inline" not in response.headers["content-security-policy"]
    assert "--brand-accent:" in response.text
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_branding_pages.py -q --no-cov`
Expected: FAIL (names come from `APP_NAME`; no `load_branding`).

- [ ] **Step 3: The global dependency** — append to `app/services/branding.py`:

```python
async def load_branding(request: Request) -> None:
    """Every route's dependency: one Redis read, never a failed page. A broken cache or
    an unreachable Redis leaves the environment's branding (APP_NAME and BRAND_*)."""
    from app.redis_client import get_redis  # noqa: PLC0415

    try:
        request.state.branding_snapshot = await snapshot(await get_redis())
    except Exception:  # noqa: BLE001 — branding must never take a page down
        log.warning("branding snapshot unavailable; using the environment's", exc_info=True)
        request.state.branding_snapshot = {}
```

with `from fastapi import Request` at the top. In `snapshot()`, a `json.JSONDecodeError` from a corrupt
value must fall through to `_load()`: wrap `json.loads(cached)` in `try/except json.JSONDecodeError: data = None`.

In `app/main.py` `create_app()`:

```python
from fastapi import Depends  # with the existing fastapi import
from app.services.branding import load_branding

    application = FastAPI(
        ...,
        dependencies=[Depends(load_branding)],
    )
```

- [ ] **Step 4: Which organisation a page serves**

`app/api/reports.py`, `_tenant()`: right before each `return _Tenant(...)`, set
`request.state.org_id = <the org_id passed to _Tenant>` (with multi-tenancy off it is `None`).

`app/api/deps.py`, `get_signed_in_admin()`: before `return user`, add `request.state.org_id = user.org_id`.

`app/templating.py`, `render()`:

```python
    ctx.setdefault("brand", current_brand(request, ctx))
```

with, above `render`:

```python
def current_brand(request: Request, ctx: dict[str, Any]) -> Any:
    """The branding of the organisation this page serves: the wizard's, the signed-in
    admin's, else the case's (the status page), else the instance default."""
    from app.services import branding  # noqa: PLC0415

    org_id = getattr(request.state, "org_id", None)
    if org_id is None and ctx.get("report") is not None:
        org_id = getattr(ctx["report"], "org_id", None)
    return branding.resolve(getattr(request.state, "branding_snapshot", {}), org_id)
```

Replace the static `templates.env.globals["brand"] = {...}` with
`templates.env.globals["brand"] = branding.resolve({}, None)` (pages rendered outside `render()`, e.g. a
bare error page, keep the environment's branding).

- [ ] **Step 5: Template and CSS**

`app/templates/base.html` head: replace `brand_tokens(brand.primary_color).items()` with `brand.tokens.items()`;
replace the two favicon `<link>` lines with:

```jinja
    {%- if brand.favicon_32_url %}
    <link rel="icon" href="{{ brand.favicon_32_url }}" sizes="32x32" type="image/png">
    <link rel="apple-touch-icon" href="{{ brand.favicon_180_url }}">
    {%- else %}
    <link rel="icon" href="/static/favicon.ico" sizes="32x32">
    <link rel="icon" href="/static/favicon.svg" type="image/svg+xml">
    {%- endif %}
```

Nav (line 61-62): the name is printed beside the logo, so the image is decorative (W3C WAI):

```jinja
            {% if brand.logo_url %}
                <img src="{{ brand.logo_url }}" alt="" class="nav-logo-img nav-logo-light">
                {%- if brand.logo_dark_url %}
                <img src="{{ brand.logo_dark_url }}" alt="" class="nav-logo-img nav-logo-dark">
                {%- endif %}
            {% else %}
```

`app/static/css/site.css`, replacing the existing `.nav-logo-img` rule (line 538, height, object-fit
and width only):

```css
/* An operator logo of any shape stays inside the nav: 4000 × 50 px must not
   widen a 390 px page. The dark variant replaces the light one in the dark theme. */
.nav-logo-img {
  height: 2rem;
  max-width: min(12rem, 40vw);
  object-fit: contain;
  width: auto;
}
.nav-logo-dark,
[data-theme="dark"] .nav-logo-light:has(+ .nav-logo-dark) {
  display: none;
}
[data-theme="dark"] .nav-logo-dark {
  display: inline-block;
}
```

- [ ] **Step 6: Update the brand-monkeypatching tests**

In each file `grep -rn 'globals\["brand"\]' tests` lists, replace
`monkeypatch.setitem(templates.env.globals["brand"], "name", X)` with
`monkeypatch.setattr(settings, "app_name", X)` and the `logo_url` variant with
`monkeypatch.setattr(settings, "brand_logo_url", X)` (import `from app.config import settings`).

- [ ] **Step 7: Run**

Run:

```bash
pytest tests/test_branding_pages.py tests/test_mark.py tests/test_v230_bug_bounty.py tests/test_footer.py tests/test_demo_footer.py tests/test_wizard.py -q --no-cov
```

Expected: PASS. `tests/test_wizard.py` proves the global dependency does not consume a mocked
`AsyncSession.execute` (it uses its own `AsyncSessionLocal`).

- [ ] **Step 8: Commit**

```bash
git add app/main.py app/templating.py app/templates/base.html app/static/css/site.css app/api/deps.py app/api/reports.py app/services/branding.py tests/
git commit -m "feat: every page wears its organisation's branding"
```

---

### Task 6: Serving brand images

**Files:**

- Create: `app/api/branding.py` (router), register in `app/main.py`
- Modify: `app/middleware.py:214-215` (Cache-Control)
- Test: `tests/test_branding_images.py`

**Interfaces:**

- Consumes: `branding.image`.
- Produces: `router = APIRouter()` in `app/api/branding.py`; route `GET /branding/{sha}.png`.

- [ ] **Step 1: Write the failing tests**

```python
"""/branding/<sha>.png: the hash is the name, nothing else is served (spec: Resolution)."""

from __future__ import annotations

from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.services import branding


async def test_a_stored_image_is_served_as_png(
    client: AsyncClient, db_session: AsyncSession
) -> None:
    sha = await branding.store_image(db_session, b"\x89PNG-served")
    await db_session.commit()
    response = await client.get(f"/branding/{sha}.png")
    assert response.status_code == 200 and response.content == b"\x89PNG-served"
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "public, max-age=31536000, immutable"


async def test_an_unknown_hash_is_404(client: AsyncClient) -> None:
    assert (await client.get(f"/branding/{'0' * 64}.png")).status_code == 404


async def test_anything_but_a_hash_is_404(client: AsyncClient) -> None:
    for path in ("/branding/..%2Fsecret.png", "/branding/ABC.png", f"/branding/{'a' * 63}.png"):
        assert (await client.get(path)).status_code == 404
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_branding_images.py -q --no-cov`
Expected: FAIL (404 for the stored image: no route).

- [ ] **Step 3: Implement**

`app/api/branding.py`:

```python
"""Operator branding: the public image route and the admin page."""

from __future__ import annotations

import re

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.services import branding

router = APIRouter()

_SHA = re.compile(r"[0-9a-f]{64}")


@router.get("/branding/{sha}.png", include_in_schema=False)
async def brand_image(sha: str, db: AsyncSession = Depends(get_db)) -> Response:
    png = await branding.image(db, sha) if _SHA.fullmatch(sha) else None
    if png is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    # The hash changes with the image, so the URL can be cached for good.
    return Response(
        png,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=31536000, immutable"},
    )
```

`app/main.py`: `from app.api.branding import router as branding_router` and
`application.include_router(branding_router)` beside the other routers.

`app/middleware.py`: the `no-store` rule must leave `/branding/` to the route:

```python
                path = str(scope.get("path", ""))
                if path.startswith("/static/"):
                    # (the existing comment about fonts.css and revalidation stays here)
                    mutable["Cache-Control"] = "no-cache"
                elif not path.startswith("/branding/"):
                    # A PIN, a report or an attachment must not be left in the browser
                    # cache of a shared office computer for the next user to find.
                    mutable["Cache-Control"] = "no-store"
                # /branding/<sha>.png sets its own: the hash changes with the image.
```

`nosniff` is already on every response; confirm with `grep -n "X-Content-Type-Options" app/middleware.py`.

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/test_branding_images.py tests/test_v050.py -q --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/api/branding.py app/main.py app/middleware.py tests/test_branding_images.py
git commit -m "feat: serve brand images by their hash"
```

---

### Task 7: The admin page (server)

**Files:**

- Modify: `app/api/branding.py` (GET/POST/reset), `app/templating.py` (`_ADMIN_NAV`),
  `app/services/audit.py` (`AuditAction`), `app/locales/{en,de,es,fr,pt-br}.json`
- Create: `app/templates/admin/branding.html`
- Test: `tests/test_branding_admin.py`

**Interfaces:**

- Consumes: `brand_image.process_logo`, `brand_image.favicon`, `BrandImageError`, `branding.find_row`, `branding.row_for`,
  `branding.store_image`, `branding.drop_orphan_images`, `branding.invalidate`, `branding.resolve`,
  `brand_colour.parse`, `brand_colour.tokens`, `brand_colour.contrast`, `may_run_the_instance`.
- Produces: `GET /admin/branding[?org=<uuid>]`, `POST /admin/branding`, `POST /admin/branding/reset`;
  `AuditAction.BRANDING_UPDATED = "branding.updated"`, `AuditAction.BRANDING_RESET = "branding.reset"`.

- [ ] **Step 1: Write the failing tests**

```python
"""/admin/branding: who may brand what, and what a save does (spec: Permissions and audit)."""

from __future__ import annotations

import io
import uuid
from typing import Any

import pytest
from PIL import Image
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.audit import AuditLog
from app.models.organisation import Organisation
from app.models.user import AdminRole
from app.services import branding
from tests.test_v210_bug_bounty import _totp_user


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (300, 150), (200, 30, 30)).save(out, format="PNG")
    return out.getvalue()


async def _post(client: Any, data: dict[str, str], files: dict[str, Any] | None = None) -> Any:
    return await client.post(
        "/admin/branding",
        data={"csrf_token": "x", **data},
        files=files or {},
        follow_redirects=False,
    )


async def test_a_case_manager_may_not_open_it(acting_as: Any, db_session: AsyncSession) -> None:
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.case_manager))
    assert (await client.get("/admin/branding")).status_code == 403


async def test_an_admin_saves_name_colour_and_logo(
    acting_as: Any, db_session: AsyncSession
) -> None:
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    response = await _post(
        client,
        {"name": "Acme", "primary_color": "#AA3300"},
        {"logo_light": ("logo.png", _png(), "image/png")},
    )
    assert response.status_code == 303
    row = await branding.row_for(db_session, None)
    await db_session.refresh(row)
    assert (row.name, row.primary_color) == ("Acme", "#aa3300")
    assert row.logo_light and row.favicon_32 and row.favicon_180
    entry = await db_session.scalar(select(AuditLog).where(AuditLog.action == "branding.updated"))
    assert entry and "name" in (entry.detail or "") and "logo_light" in (entry.detail or "")


@pytest.mark.parametrize(
    ("data", "files"),
    [
        ({"primary_color": "red"}, None),
        ({"name": "x" * 65}, None),
        ({}, {"logo_light": ("logo.svg", b"<svg/>", "image/svg+xml")}),
    ],
)
async def test_invalid_input_saves_nothing(
    acting_as: Any, db_session: AsyncSession, data: dict[str, str], files: Any
) -> None:
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    response = await _post(client, data, files)
    assert response.status_code == 422
    row = await db_session.scalar(
        select(branding.Branding).where(branding.Branding.org_id.is_(None))
    )
    assert row is None


async def test_reset_clears_one_field_and_the_cache_follows(
    acting_as: Any, db_session: AsyncSession
) -> None:
    client, act = acting_as
    act(await _totp_user(db_session, AdminRole.admin))
    await _post(client, {"name": "Before"})
    assert "Before" in (await client.get("/submit")).text
    response = await client.post(
        "/admin/branding/reset", data={"csrf_token": "x", "field": "name"}, follow_redirects=False
    )
    assert response.status_code == 303
    assert "Before" not in (await client.get("/submit")).text


async def test_an_org_admin_cannot_brand_another_org(
    acting_as: Any, db_session: AsyncSession, tenants: None
) -> None:
    mine = Organisation(id=uuid.uuid4(), name="Mine", slug=f"m-{uuid.uuid4().hex[:6]}")
    other = Organisation(id=uuid.uuid4(), name="Other", slug=f"o-{uuid.uuid4().hex[:6]}")
    db_session.add_all([mine, other])
    await db_session.commit()
    user = await _totp_user(db_session, AdminRole.admin)
    user.org_id = mine.id
    await db_session.commit()
    client, act = acting_as
    act(user)
    assert (await _post(client, {"name": "Hijack", "org": str(other.id)})).status_code == 403
    assert (await client.get(f"/admin/branding?org={other.id}")).status_code == 403
    assert (await _post(client, {"name": "Mine Brand"})).status_code == 303
    own = await branding.row_for(db_session, mine.id)
    await db_session.refresh(own)
    assert own.name == "Mine Brand"
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest tests/test_branding_admin.py -q --no-cov`
Expected: FAIL (404 on `/admin/branding`).

- [ ] **Step 3: Audit actions and navigation**

`app/services/audit.py`, inside `class AuditAction`, after the telemetry actions:

```python
    BRANDING_UPDATED = "branding.updated"
    BRANDING_RESET = "branding.reset"
```

`app/templating.py`, `_ADMIN_NAV` "admin.nav.group.setup" group, after retention:

```python
(("/admin/branding", "admin.nav.branding", "admin"),)
```

- [ ] **Step 4: Locale keys (all five files, inserted after `"admin.nav.system"`)**

| Key | en | de | es | fr | pt-br |
|---|---|---|---|---|---|
| `admin.nav.branding` | Branding | Branding | Imagen de marca | Image de marque | Identidade visual |
| `admin.branding.title` | Branding | Branding | Imagen de marca | Image de marque | Identidade visual |
| `admin.branding.subtitle` | Name, logo and colour on the reporter's pages. The footer is the same on every installation. | Name, Logo und Farbe auf den Seiten für Meldende. Der Footer ist in jeder Installation gleich. | Nombre, logotipo y color en las páginas para informantes. El pie de página es igual en todas las instalaciones. | Nom, logo et couleur sur les pages des lanceurs d'alerte. Le pied de page est le même dans toute installation. | Nome, logotipo e cor nas páginas para denunciantes. O rodapé é o mesmo em toda instalação. |
| `admin.branding.organisation` | Organisation | Organisation | Organización | Organisation | Organização |
| `admin.branding.default` | Default for every organisation | Standard für alle Organisationen | Predeterminado para todas las organizaciones | Par défaut pour toutes les organisations | Padrão para todas as organizações |
| `admin.branding.name` | Name | Name | Nombre | Nom | Nome |
| `admin.branding.name.hint` | Beside the logo and in the browser tab. Empty: {fallback}. | Neben dem Logo und im Browser-Tab. Leer: {fallback}. | Junto al logotipo y en la pestaña del navegador. Vacío: {fallback}. | À côté du logo et dans l'onglet du navigateur. Vide : {fallback}. | Ao lado do logotipo e na aba do navegador. Vazio: {fallback}. |
| `admin.branding.logo_light` | Logo | Logo | Logotipo | Logo | Logotipo |
| `admin.branding.logo_dark` | Logo for the dark theme | Logo für das dunkle Design | Logotipo para el tema oscuro | Logo pour le thème sombre | Logotipo para o tema escuro |
| `admin.branding.logo.hint` | PNG, JPEG or WebP, up to 1 MB. Stored as a PNG 96 px high, without metadata. | PNG, JPEG oder WebP, bis 1 MB. Gespeichert als PNG mit 96 px Höhe, ohne Metadaten. | PNG, JPEG o WebP, hasta 1 MB. Se guarda como PNG de 96 px de alto, sin metadatos. | PNG, JPEG ou WebP, jusqu'à 1 Mo. Enregistré en PNG de 96 px de haut, sans métadonnées. | PNG, JPEG ou WebP, até 1 MB. Salvo como PNG com 96 px de altura, sem metadados. |
| `admin.branding.logo_dark.hint` | Optional. Without it, the logo above is used in both themes. | Optional. Ohne dieses Logo gilt das obere in beiden Designs. | Opcional. Sin él, se usa el logotipo de arriba en ambos temas. | Facultatif. Sans lui, le logo ci-dessus sert dans les deux thèmes. | Opcional. Sem ele, o logotipo acima é usado nos dois temas. |
| `admin.branding.remove` | Remove | Entfernen | Quitar | Retirer | Remover |
| `admin.branding.colour` | Brand colour | Markenfarbe | Color de marca | Couleur de marque | Cor da marca |
| `admin.branding.colour.hex` | Hex value | Hex-Wert | Valor hexadecimal | Valeur hexadécimale | Valor hexadecimal |
| `admin.branding.contrast` | Contrast: buttons {button}, links light {light}, links dark {dark}. At least 4.5:1 is needed; the page adjusts the shade to reach it. | Kontrast: Buttons {button}, Links hell {light}, Links dunkel {dark}. Nötig sind mindestens 4,5:1; die Seite passt den Farbton dafür an. | Contraste: botones {button}, enlaces claro {light}, enlaces oscuro {dark}. Se necesita al menos 4,5:1; la página ajusta el tono para lograrlo. | Contraste : boutons {button}, liens clair {light}, liens sombre {dark}. Il faut au moins 4,5:1 ; la page ajuste la nuance pour y arriver. | Contraste: botões {button}, links claro {light}, links escuro {dark}. É preciso ao menos 4,5:1; a página ajusta o tom para isso. |
| `admin.branding.save` | Save branding | Branding speichern | Guardar imagen de marca | Enregistrer l'image de marque | Salvar identidade visual |
| `admin.branding.saved` | Branding saved. | Branding gespeichert. | Imagen de marca guardada. | Image de marque enregistrée. | Identidade visual salva. |
| `admin.branding.reset` | Reset | Zurücksetzen | Restablecer | Réinitialiser | Redefinir |
| `admin.branding.reset_all` | Reset everything | Alles zurücksetzen | Restablecer todo | Tout réinitialiser | Redefinir tudo |
| `admin.branding.preview` | Preview | Vorschau | Vista previa | Aperçu | Pré-visualização |
| `admin.branding.preview.light` | Light | Hell | Claro | Clair | Claro |
| `admin.branding.preview.dark` | Dark | Dunkel | Oscuro | Sombre | Escuro |
| `admin.branding.preview.button` | Continue | Weiter | Continuar | Continuer | Continuar |
| `admin.branding.preview.link` | A link | Ein Link | Un enlace | Un lien | Um link |
| `admin.branding.error.too_large` | The image is over 1 MB. | Das Bild ist größer als 1 MB. | La imagen supera 1 MB. | L'image dépasse 1 Mo. | A imagem tem mais de 1 MB. |
| `admin.branding.error.format` | Only PNG, JPEG or WebP images. | Nur PNG-, JPEG- oder WebP-Bilder. | Solo imágenes PNG, JPEG o WebP. | Uniquement des images PNG, JPEG ou WebP. | Apenas imagens PNG, JPEG ou WebP. |
| `admin.branding.error.dimensions` | The image has more than 16 megapixels. | Das Bild hat mehr als 16 Megapixel. | La imagen tiene más de 16 megapíxeles. | L'image dépasse 16 mégapixels. | A imagem tem mais de 16 megapixels. |
| `admin.branding.error.colour` | A colour is written #rrggbb, e.g. #0c7253. | Eine Farbe wird als #rrggbb geschrieben, z. B. #0c7253. | Un color se escribe #rrggbb, p. ej. #0c7253. | Une couleur s'écrit #rrggbb, p. ex. #0c7253. | Uma cor é escrita #rrggbb, ex.: #0c7253. |
| `admin.branding.error.name` | At most 64 characters. | Höchstens 64 Zeichen. | Máximo 64 caracteres. | 64 caractères au maximum. | No máximo 64 caracteres. |
| `audit.action.branding.updated` (beside the other `audit.action.*`) | Branding changed | Branding geändert | Imagen de marca cambiada | Image de marque modifiée | Identidade visual alterada |
| `audit.action.branding.reset` | Branding reset | Branding zurückgesetzt | Imagen de marca restablecida | Image de marque réinitialisée | Identidade visual redefinida |

Insert them with the JSON round-trip used before (`json.loads` → insert after the anchor key →
`json.dumps(indent=2, ensure_ascii=False) + "\n"`); the files round-trip byte for byte.

- [ ] **Step 5: Routes** — append to `app/api/branding.py`:

```python
import uuid
from typing import Any

from fastapi import File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from redis.asyncio import Redis
from sqlalchemy import select

from app.api.deps import may_run_the_instance, require_admin
from app.config import settings
from app.csrf import validate_csrf
from app.models.organisation import Organisation
from app.models.user import AdminUser
from app.redis_client import get_redis
from app.services import audit as audit_service
from app.services import brand_colour, brand_image
from app.services.audit import AuditAction
from app.templating import render

_RESETTABLE = ("name", "primary_color", "logo_light", "logo_dark")


async def _target(db: AsyncSession, user: AdminUser, org: str) -> uuid.UUID | None:
    """Whose branding this admin edits: an instance admin the default, or with
    multi-tenancy any organisation; an organisation's admin only their own."""
    if may_run_the_instance(user):
        if not org or not settings.multi_tenancy_enabled:
            return None
        try:
            org_id = uuid.UUID(org)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND) from None
        if await db.get(Organisation, org_id) is None:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
        return org_id
    if settings.multi_tenancy_enabled and user.org_id is not None and org in ("", str(user.org_id)):
        return user.org_id
    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


async def _page(
    request: Request,
    db: AsyncSession,
    user: AdminUser,
    org_id: uuid.UUID | None,
    *,
    error: str | None = None,
    form: dict[str, str] | None = None,
    status_code: int = 200,
) -> HTMLResponse:
    # Read only: an unsaved Branding() stands in for a row that does not exist yet.
    row = await branding.find_row(db, org_id) or branding.Branding(org_id=org_id)
    snap = getattr(request.state, "branding_snapshot", {})
    effective = branding.resolve(snap, org_id)
    tokens = effective.tokens
    orgs: list[Organisation] = []
    if may_run_the_instance(user) and settings.multi_tenancy_enabled:
        orgs = list((await db.scalars(select(Organisation).order_by(Organisation.name))).all())
    return render(
        request,
        "admin/branding.html",
        {
            "user": user,
            "row": row,
            "org_id": org_id,
            "orgs": orgs,
            "effective": effective,
            "fallback_name": branding.resolve(
                {k: v for k, v in snap.items() if k == "default"}, None
            ).name
            if org_id
            else settings.app_name,
            "ratios": {
                "button": f"{brand_colour.contrast(tokens['on'], tokens['accent']):.1f}:1",
                "light": f"{brand_colour.contrast(tokens['accent'], brand_colour.LIGHT_CANVAS):.1f}:1",
                "dark": f"{brand_colour.contrast(tokens['accent-dark'], brand_colour.DARK_CANVAS):.1f}:1",
            },
            "error": error,
            "form": form or {},
            "saved": request.query_params.get("saved") == "1",
        },
        status_code=status_code,
    )


def _back(org_id: uuid.UUID | None) -> RedirectResponse:
    suffix = f"&org={org_id}" if org_id else ""
    return RedirectResponse(f"/admin/branding?saved=1{suffix}", status_code=303)


@router.get("/admin/branding", response_class=HTMLResponse)
async def branding_get(
    request: Request,
    org: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: AdminUser = Depends(require_admin),
) -> HTMLResponse:
    return await _page(request, db, current_user, await _target(db, current_user, org))


async def _logo(upload: UploadFile | None) -> bytes | None:
    if upload is None or not upload.filename:
        return None
    data = await upload.read(brand_image.MAX_BYTES + 1)
    return brand_image.process_logo(data) if data else None


@router.post("/admin/branding", response_model=None)
async def branding_post(
    request: Request,
    name: str = Form(""),
    primary_color: str = Form(""),
    org: str = Form(""),
    remove_logo_light: str = Form(""),
    remove_logo_dark: str = Form(""),
    logo_light: UploadFile | None = File(None),
    logo_dark: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> HTMLResponse | RedirectResponse:
    org_id = await _target(db, current_user, org)
    form = {"name": name, "primary_color": primary_color}
    name = name.strip()
    try:
        if len(name) > 64:
            raise brand_image.BrandImageError("admin.branding.error.name")
        colour = None
        if primary_color.strip():
            try:
                colour = brand_colour.parse(primary_color)
            except ValueError:
                raise brand_image.BrandImageError("admin.branding.error.colour") from None
        light = await _logo(logo_light)
        dark = await _logo(logo_dark)
    except brand_image.BrandImageError as exc:
        return await _page(
            request, db, current_user, org_id, error=exc.key, form=form, status_code=422
        )

    row = await branding.row_for(db, org_id)
    changed: list[str] = []
    for field_name, value in (("name", name or None), ("primary_color", colour)):
        if getattr(row, field_name) != value:
            setattr(row, field_name, value)
            changed.append(field_name)
    if light is not None:
        row.logo_light = await branding.store_image(db, light)
        row.favicon_32 = await branding.store_image(db, brand_image.favicon(light, 32))
        row.favicon_180 = await branding.store_image(db, brand_image.favicon(light, 180))
        changed.append("logo_light")
    elif remove_logo_light == "1" and row.logo_light:
        row.logo_light = row.favicon_32 = row.favicon_180 = None
        changed.append("logo_light")
    if dark is not None:
        row.logo_dark = await branding.store_image(db, dark)
        changed.append("logo_dark")
    elif remove_logo_dark == "1" and row.logo_dark:
        row.logo_dark = None
        changed.append("logo_dark")
    if changed:
        row.updated_by_id = current_user.id
        await branding.drop_orphan_images(db)
        await audit_service.log(
            db,
            current_user,
            AuditAction.BRANDING_UPDATED,
            detail={"fields": changed},
            target_org=org_id,
        )
    await db.commit()
    await branding.invalidate(redis)
    return _back(org_id)


@router.post("/admin/branding/reset")
async def branding_reset(
    field: str = Form(...),
    org: str = Form(""),
    db: AsyncSession = Depends(get_db),
    redis: Redis = Depends(get_redis),
    current_user: AdminUser = Depends(require_admin),
    _csrf: None = Depends(validate_csrf),
) -> RedirectResponse:
    org_id = await _target(db, current_user, org)
    fields = _RESETTABLE if field == "all" else (field,)
    if not set(fields) <= set(_RESETTABLE):
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY)
    row = await branding.row_for(db, org_id)
    for name in fields:
        setattr(row, name, None)
        if name == "logo_light":
            row.favicon_32 = row.favicon_180 = None
    row.updated_by_id = current_user.id
    await branding.drop_orphan_images(db)
    await audit_service.log(
        db,
        current_user,
        AuditAction.BRANDING_RESET,
        detail={"fields": list(fields)},
        target_org=org_id,
    )
    await db.commit()
    await branding.invalidate(redis)
    return _back(org_id)
```

Move `BrandImageError` usage for the name and colour into a small local exception if ruff flags reuse as
misleading; the behaviour (one 422 path carrying a locale key) stays.

- [ ] **Step 6: Template `app/templates/admin/branding.html`**

```jinja
{% extends "admin/_layout.html" %}

{% block title %}{{ t('admin.branding.title') }} | {{ brand.name }}{% endblock %}

{% block styles %}<style nonce="{{ request.state.csp_nonce }}">
.bp-grid { display: grid; gap: var(--space-8); grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); align-items: start; }
@media (max-width: 900px) { .bp-grid { grid-template-columns: 1fr; } }
.bp-colour { display: flex; gap: var(--space-3); align-items: center; }
.bp-colour input[type="color"] { block-size: 2.5rem; inline-size: 3rem; padding: 0; border: 0; background: none; }
.bp-current { block-size: 2rem; max-inline-size: 12rem; object-fit: contain; }
.bp-previews { display: grid; gap: var(--space-4); }
.bp-panel { border-radius: var(--radius-card); box-shadow: 0 0 0 1px var(--hairline); padding: var(--space-6); display: grid; gap: var(--space-4); }
.bp-panel[data-preview="light"] { background: #ffffff; color: #3d3d40; --bp-ink: #0a0a0b; }
.bp-panel[data-preview="dark"] { background: #0a0a0b; color: #c8c8cc; --bp-ink: #fafafa; }
.bp-nav { display: flex; align-items: center; gap: var(--space-3); color: var(--bp-ink); font-weight: 600; }
.bp-nav img { block-size: 2rem; max-inline-size: 12rem; object-fit: contain; }
.bp-button { background: var(--bp-accent); color: var(--bp-on); border-radius: var(--radius-md, 8px); padding: 0.6rem 1.2rem; font-weight: 600; justify-self: start; border: 0; }
.bp-link { color: var(--bp-accent); text-decoration: underline; }
.bp-focus { outline: 2px solid var(--bp-accent); outline-offset: 2px; }
.bp-panel[data-preview="light"] { --bp-accent: {{ effective.tokens['accent'] }}; --bp-on: {{ effective.tokens['on'] }}; }
.bp-panel[data-preview="dark"] { --bp-accent: {{ effective.tokens['accent-dark'] }}; --bp-on: {{ effective.tokens['on-dark'] }}; }
</style>{% endblock %}

{% block admin_content %}
<div class="container">
    <div class="page-header">
        <h1>{{ t('admin.branding.title') }}</h1>
        <p class="page-subtitle">{{ t('admin.branding.subtitle') }}</p>
    </div>

    {% if saved %}<div class="alert alert-success" role="status">{{ t('admin.branding.saved') }}</div>{% endif %}
    {% if error %}<div class="alert alert-error" role="alert" id="branding-error">{{ t(error) }}</div>{% endif %}

    {% if orgs %}
    <form method="get" action="/admin/branding" class="form-group">
        <label class="form-label" for="bp-org">{{ t('admin.branding.organisation') }}</label>
        <select class="form-control" id="bp-org" name="org" data-autosubmit>
            <option value="">{{ t('admin.branding.default') }}</option>
            {% for o in orgs %}<option value="{{ o.id }}"{% if org_id == o.id %} selected{% endif %}>{{ o.name }}</option>{% endfor %}
        </select>
    </form>
    {% endif %}

    <div class="bp-grid">
        <form method="post" action="/admin/branding" enctype="multipart/form-data" class="panel" id="branding-form">
            <input type="hidden" name="csrf_token" value="{{ request.state.csrf_token }}">
            <input type="hidden" name="org" value="{{ org_id or '' }}">

            <div class="form-group">
                <label class="form-label" for="bp-name">{{ t('admin.branding.name') }}</label>
                <input class="form-control" id="bp-name" name="name" maxlength="64"
                       value="{{ form.get('name', row.name or '') }}" aria-describedby="bp-name-hint">
                <p class="form-hint" id="bp-name-hint">{{ t('admin.branding.name.hint', fallback=fallback_name) }}</p>
            </div>

            {% for key in ['logo_light', 'logo_dark'] %}
            <div class="form-group">
                <label class="form-label" for="bp-{{ key }}">{{ t('admin.branding.' ~ key) }}</label>
                {% set current = row|attr(key) %}
                {% if current %}<img class="bp-current" src="/branding/{{ current }}.png" alt="">{% endif %}
                <input class="form-control" type="file" id="bp-{{ key }}" name="{{ key }}"
                       accept="image/png,image/jpeg,image/webp" data-preview-logo="{{ key }}"
                       aria-describedby="bp-{{ key }}-hint">
                <p class="form-hint" id="bp-{{ key }}-hint">{{ t('admin.branding.logo.hint') if key == 'logo_light' else t('admin.branding.logo_dark.hint') }}</p>
                {% if current %}
                <label><input type="checkbox" name="remove_{{ key }}" value="1"> {{ t('admin.branding.remove') }}</label>
                {% endif %}
            </div>
            {% endfor %}

            <div class="form-group">
                <label class="form-label" for="bp-colour-hex">{{ t('admin.branding.colour') }}</label>
                <div class="bp-colour">
                    <input type="color" id="bp-colour-picker" value="{{ effective.primary_color }}" aria-label="{{ t('admin.branding.colour') }}">
                    <input class="form-control" id="bp-colour-hex" name="primary_color" pattern="#[0-9a-fA-F]{6}"
                           value="{{ form.get('primary_color', row.primary_color or '') }}" placeholder="{{ effective.primary_color }}"
                           aria-describedby="bp-contrast">
                </div>
                <p class="form-hint" id="bp-contrast" aria-live="polite"
                   data-template="{{ t('admin.branding.contrast', button='{button}', light='{light}', dark='{dark}') }}">
                    {{ t('admin.branding.contrast', button=ratios.button, light=ratios.light, dark=ratios.dark) }}
                </p>
            </div>

            <button type="submit" class="btn btn-primary">{{ t('admin.branding.save') }}</button>
        </form>

        <section class="bp-previews" aria-labelledby="bp-preview-h">
            <h2 id="bp-preview-h" class="panel-header">{{ t('admin.branding.preview') }}</h2>
            {% for theme in ['light', 'dark'] %}
            <div class="bp-panel" data-preview="{{ theme }}">
                <p class="form-hint">{{ t('admin.branding.preview.' ~ theme) }}</p>
                <div class="bp-nav">
                    {% set src = (effective.logo_dark_url if theme == 'dark' and effective.logo_dark_url else effective.logo_url) %}
                    <img data-preview-img="{{ theme }}" src="{{ src }}" alt=""{% if not src %} hidden{% endif %}>
                    <span data-preview-name>{{ effective.name }}</span>
                </div>
                <span class="bp-button">{{ t('admin.branding.preview.button') }}</span>
                <span class="bp-link">{{ t('admin.branding.preview.link') }}</span>
                <span class="bp-button bp-focus">{{ t('admin.branding.preview.button') }}</span>
            </div>
            {% endfor %}
        </section>
    </div>

    <form method="post" action="/admin/branding/reset" class="u-m0">
        <input type="hidden" name="csrf_token" value="{{ request.state.csrf_token }}">
        <input type="hidden" name="org" value="{{ org_id or '' }}">
        <input type="hidden" name="field" value="all">
        <button type="submit" class="btn btn-secondary">{{ t('admin.branding.reset_all') }}</button>
    </form>
</div>
{% endblock %}

{% block scripts %}
<script src="{{ static_url('js/branding.js') }}" nonce="{{ request.state.csp_nonce }}"></script>
{% endblock %}
```

(The token values in the `<style>` block are validated `#rrggbb` strings from `brand_colour.tokens`.)

- [ ] **Step 7: Run to verify it passes**

Run:

```bash
pytest tests/test_branding_admin.py tests/test_locales.py tests/test_locale_key_completeness.py tests/test_i18n_coverage.py tests/test_local_review.py -q --no-cov
```

Expected: PASS. `test_local_review` demands a row for `/admin/branding` and `admin/branding.html` in
`docs-tech/local-review.md`'s page matrix: add

```markdown
| /admin/branding | admin/branding.html | Name, logos, colour and the live preview; try #ffd000 and a wide logo. |
```

- [ ] **Step 8: Commit**

```bash
git add app/api/branding.py app/templating.py app/services/audit.py app/locales app/templates/admin/branding.html docs-tech/local-review.md tests/test_branding_admin.py
git commit -m "feat: /admin/branding saves name, logos and colour per organisation"
```

---

### Task 8: Live preview (browser)

**Files:**

- Create: `app/static/js/branding.js`
- Test: `tests/e2e/test_branding.py`

**Interfaces:**

- Consumes: the template's `#bp-colour-picker`, `#bp-colour-hex`, `#bp-name`, `[data-preview-logo]`,
  `[data-preview-img]`, `[data-preview-name]`, `.bp-panel[data-preview]`, `#bp-contrast[data-template]`,
  `select[data-autosubmit]`.

- [ ] **Step 1: Write the failing e2e tests**

```python
"""The preview follows the form before anything is saved (spec: The page)."""

from __future__ import annotations

from playwright.sync_api import Page


def test_the_preview_follows_the_colour(admin_page: Page) -> None:
    admin_page.goto("/admin/branding")
    admin_page.fill("#bp-colour-hex", "#aa3300")
    admin_page.dispatch_event("#bp-colour-hex", "input")
    accent = admin_page.eval_on_selector(
        '.bp-panel[data-preview="light"]', "e => e.style.getPropertyValue('--bp-accent')"
    )
    dark = admin_page.eval_on_selector(
        '.bp-panel[data-preview="dark"]', "e => e.style.getPropertyValue('--bp-accent')"
    )
    assert accent == "#aa3300" and dark not in ("", "#aa3300")
    assert admin_page.inner_text("#bp-contrast").count(":1") == 3


def test_the_preview_follows_the_name(admin_page: Page) -> None:
    admin_page.goto("/admin/branding")
    admin_page.fill("#bp-name", "Acme Preview")
    texts = admin_page.locator("[data-preview-name]").all_inner_texts()
    assert texts == ["Acme Preview", "Acme Preview"]


def test_a_wide_logo_never_widens_the_nav(admin_page: Page, tmp_path: object) -> None:
    import io
    from pathlib import Path

    from PIL import Image

    path = Path(str(tmp_path)) / "wide.png"
    buffer = io.BytesIO()
    Image.new("RGB", (4000, 50), (10, 10, 10)).save(buffer, format="PNG")
    path.write_bytes(buffer.getvalue())
    admin_page.set_viewport_size({"width": 390, "height": 844})
    admin_page.goto("/admin/branding")
    admin_page.set_input_files("#bp-logo_light", str(path))
    width = admin_page.evaluate("document.documentElement.scrollWidth")
    assert width <= 390, width
```

`admin_page` is the existing fixture in `tests/e2e/conftest.py` (signed-in demo admin). The third test only
previews; it saves nothing, so the demo stays unbranded.

- [ ] **Step 2: Run to verify it fails**

Run (local review stack or a demo-mode uvicorn):

```bash
pytest tests/e2e/test_branding.py --base-url http://localhost:8766 -q --no-cov
```

Expected: FAIL (`--bp-accent` is empty: no script yet).

- [ ] **Step 3: Implement `app/static/js/branding.js`**

```javascript
// Live preview for /admin/branding. The same WCAG 2.x rule as
// app/services/brand_colour.py; the server's values are the ones saved.
(function () {
  'use strict';
  var LIGHT = '#ffffff', DARK = '#0a0a0b', WHITE = '#ffffff', BLACK = '#000000', MIN = 4.5;

  function channels(c) { return [1, 3, 5].map(function (i) { return parseInt(c.substr(i, 2), 16); }); }
  function lum(c) {
    var v = channels(c).map(function (x) {
      var s = x / 255;
      return s <= 0.04045 ? s / 12.92 : Math.pow((s + 0.055) / 1.055, 2.4);
    });
    return 0.2126 * v[0] + 0.7152 * v[1] + 0.0722 * v[2];
  }
  function contrast(a, b) {
    var x = lum(a), y = lum(b);
    return (Math.max(x, y) + 0.05) / (Math.min(x, y) + 0.05);
  }
  function mix(c, t, share) {
    var a = channels(c), b = channels(t);
    return '#' + a.map(function (v, i) {
      return ('0' + Math.round(v + (b[i] - v) * share).toString(16)).slice(-2);
    }).join('');
  }
  function readable(c, canvas, toward) {
    for (var step = 0; step <= 50; step++) {
      var candidate = mix(c, toward, step / 50);
      if (contrast(candidate, canvas) >= MIN) { return candidate; }
    }
    return toward;
  }
  function on(fill) { return contrast(fill, WHITE) >= contrast(fill, BLACK) ? WHITE : BLACK; }

  var hex = document.getElementById('bp-colour-hex');
  var picker = document.getElementById('bp-colour-picker');
  var ratios = document.getElementById('bp-contrast');
  var panels = document.querySelectorAll('.bp-panel[data-preview]');

  function apply(colour) {
    if (!/^#[0-9a-fA-F]{6}$/.test(colour)) { return; }
    colour = colour.toLowerCase();
    var light = colour === '#0c7253' ? '#0c7253' : readable(colour, LIGHT, BLACK);
    var dark = colour === '#0c7253' ? '#23c088' : readable(colour, DARK, WHITE);
    panels.forEach(function (panel) {
      var accent = panel.dataset.preview === 'dark' ? dark : light;
      panel.style.setProperty('--bp-accent', accent);
      panel.style.setProperty('--bp-on', colour === '#0c7253' && panel.dataset.preview === 'dark' ? '#06120d' : on(accent));
    });
    if (ratios && ratios.dataset.template) {
      ratios.textContent = ratios.dataset.template
        .replace('{button}', contrast(on(light), light).toFixed(1) + ':1')
        .replace('{light}', contrast(light, LIGHT).toFixed(1) + ':1')
        .replace('{dark}', contrast(dark, DARK).toFixed(1) + ':1');
    }
  }

  if (hex && picker) {
    hex.addEventListener('input', function () {
      if (/^#[0-9a-fA-F]{6}$/.test(hex.value)) { picker.value = hex.value.toLowerCase(); }
      apply(hex.value);
    });
    picker.addEventListener('input', function () { hex.value = picker.value; apply(picker.value); });
  }

  var name = document.getElementById('bp-name');
  if (name) {
    name.addEventListener('input', function () {
      var shown = name.value.trim() || name.getAttribute('placeholder') || '';
      document.querySelectorAll('[data-preview-name]').forEach(function (el) {
        if (shown) { el.textContent = shown; }
      });
    });
  }

  // img-src 'self' data: already allows a data: URL; no CSP change for the preview.
  document.querySelectorAll('[data-preview-logo]').forEach(function (input) {
    input.addEventListener('change', function () {
      var file = input.files && input.files[0];
      if (!file) { return; }
      var reader = new FileReader();
      reader.onload = function () {
        var targets = input.dataset.previewLogo === 'logo_dark' ? ['dark'] : ['light', 'dark'];
        targets.forEach(function (theme) {
          var img = document.querySelector('[data-preview-img="' + theme + '"]');
          if (!img) { return; }
          if (theme === 'dark' && input.dataset.previewLogo === 'logo_light' && img.dataset.ownDark) { return; }
          img.src = reader.result;
          img.hidden = false;
          if (input.dataset.previewLogo === 'logo_dark') { img.dataset.ownDark = '1'; }
        });
      };
      reader.readAsDataURL(file);
    });
  });

  var autosubmit = document.querySelector('select[data-autosubmit]');
  if (autosubmit) { autosubmit.addEventListener('change', function () { autosubmit.form.submit(); }); }
})();
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest tests/e2e/test_branding.py tests/e2e/test_layout.py --base-url http://localhost:8766 -q --no-cov`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/static/js/branding.js tests/e2e/test_branding.py
git commit -m "feat: live branding preview in both themes"
```

---

### Task 9: Guards, documentation, release hygiene

**Files:**

- Create: `docs-tech/mutations/v2.4.0-branding.json`
- Modify: `README.md`, `DESIGN.md`, `CHANGELOG.md`, `docs-tech/invariants.md`
- Website (drift rule): `docs/en/docs/admin/index.html`, `docs/_data/config.yml` in openwhistle/website

- [ ] **Step 1: Mutation spec** `docs-tech/mutations/v2.4.0-branding.json`:

```json
{
 "test_groups": {
  "B": [
   "tests/test_brand_colour.py",
   "tests/test_brand_image.py",
   "tests/test_branding_service.py",
   "tests/test_branding_pages.py",
   "tests/test_branding_images.py",
   "tests/test_branding_admin.py"
  ]
 },
 "mutations": [
  {"id": "accent-not-adjusted", "file": "app/services/brand_colour.py",
   "old": "    light = _readable(colour, LIGHT_CANVAS, BLACK)", "new": "    light = colour", "tests": "B"},
  {"id": "ink-instead-of-black", "file": "app/services/brand_colour.py",
   "old": "    return WHITE if contrast(fill, WHITE) >= contrast(fill, BLACK) else BLACK",
   "new": "    return WHITE if contrast(fill, WHITE) >= contrast(fill, DARK_CANVAS) else DARK_CANVAS", "tests": "B"},
  {"id": "type-from-anything", "file": "app/services/brand_image.py",
   "old": "            if source.format not in _FORMATS:", "new": "            if False:", "tests": "B"},
  {"id": "no-pixel-cap", "file": "app/services/brand_image.py",
   "old": "            if source.width * source.height > MAX_PIXELS:", "new": "            if False:", "tests": "B"},
  {"id": "stored-as-uploaded", "file": "app/services/brand_image.py",
   "old": "    return _png(image)\n\n\ndef favicon", "new": "    return data\n\n\ndef favicon", "tests": "B"},
  {"id": "orphans-ignore-sharing", "file": "app/services/branding.py",
   "old": "    columns = [getattr(Branding, name) for name in Branding.IMAGE_FIELDS]",
   "new": "    columns = [Branding.logo_dark]", "tests": "B"},
  {"id": "org-ignored", "file": "app/services/branding.py",
   "old": "    own = snap.get(str(org_id), {}) if org_id else {}", "new": "    own = {}", "tests": "B"},
  {"id": "cache-never-cleared", "file": "app/services/branding.py",
   "old": "    await redis.delete(CACHE_KEY)", "new": "    return None", "tests": "B"},
  {"id": "org-admin-any-org", "file": "app/api/branding.py",
   "old": "    raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)\n\n\nasync def _page",
   "new": "    return uuid.UUID(org) if org else user.org_id\n\n\nasync def _page", "tests": "B"},
  {"id": "image-sniffable", "file": "app/api/branding.py",
   "old": "        media_type=\"image/png\",", "new": "        media_type=\"text/html\",", "tests": "B"},
  {"id": "wide-logo-overflows", "file": "app/static/css/site.css",
   "old": "  max-width: min(12rem, 40vw);\n", "new": "", "tests": "B"},
  {"id": "logo-alt-name", "file": "app/templates/base.html",
   "old": "<img src=\"{{ brand.logo_url }}\" alt=\"\" class=\"nav-logo-img nav-logo-light\">",
   "new": "<img src=\"{{ brand.logo_url }}\" alt=\"{{ brand.name }}\" class=\"nav-logo-img nav-logo-light\">", "tests": "B"}
 ]
}
```

Run: `python scripts/mutation_audit.py docs-tech/mutations/v2.4.0-branding.json`
Expected: every line `RED`. A `GREEN` line means a test is missing: write it in the owning task's test file,
then re-run.

- [ ] **Step 2: Documentation**

- `README.md` "Operation": `- **Branding page** — name, light and dark logo, brand colour with a live preview, per
  organisation; logos re-encoded as metadata-free PNG, colours adjusted to WCAG AA in both themes`.
- `DESIGN.md` "Colors": a subsection "A custom brand colour" stating the derivation table of the spec's
  "Colour" section and that the default keeps the listed tokens; "Navigation & footer": the operator logo
  replaces the mark, `alt=""` beside the name, the dark variant in the dark theme; the footer is not brandable.
- `CHANGELOG.md` Unreleased "Added": the branding page in one bullet (what, the no-SVG rule, AA derivation,
  per organisation); "Changed": `APP_NAME`, `BRAND_PRIMARY_COLOR`, `BRAND_LOGO_URL` are starting values below
  the page's.
- `docs-tech/invariants.md`: one row per guard of Step 1, naming its test.
- Website PR (`docs/en/docs/admin/index.html` section "Branding" with what each field does and the limits;
  `docs/_data/config.yml` descriptions of the three env vars: "starting value; `/admin/branding` overrides"),
  linked from the app PR.

- [ ] **Step 3: Full verification**

Run: `ruff check app tests scripts && ruff format --check app tests scripts && mypy app/ --strict`
Run: `pytest -q -p no:cacheprovider` (real PostgreSQL and Redis) → all green, coverage ≥ 90 %.
Run the e2e layout and branding suites against a demo-mode server.
Chrome check (`docs-tech/local-review.md`): `/admin/branding` and `/submit` in both themes at 1920 px, with
the default branding and with `#ffd000` plus a wide logo saved.

- [ ] **Step 4: Commit, PR, website PR**

```bash
git add docs-tech/mutations/v2.4.0-branding.json README.md DESIGN.md CHANGELOG.md docs-tech/invariants.md
git commit -m "docs: branding page in README, DESIGN.md, changelog and invariants"
git push -u origin feat/branding
```

Open the app PR (body: what, research summary, mutation result, website PR link) and the website PR; the app
PR merges when CI is green.
