"""One default row at most; images by hash (spec: Data model)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.branding import Branding

pytestmark = pytest.mark.usefixtures("clean_branding")


async def test_there_is_one_default_row_at_most(db_session: AsyncSession) -> None:
    db_session.add(Branding(id=uuid.uuid4(), org_id=None, name="A"))
    await db_session.commit()
    db_session.add(Branding(id=uuid.uuid4(), org_id=None, name="B"))
    with pytest.raises(IntegrityError):
        await db_session.commit()
    await db_session.rollback()
