"""Two built-in German category labels were spelled without ß.

Only a label still as seeded is changed; one an operator edited is left alone.

Revision ID: d4f1b8c6e203
Revises: c3e9a2d5f417
Create Date: 2026-10-15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "d4f1b8c6e203"
down_revision: str | None = "c3e9a2d5f417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

__all__ = ["branch_labels", "depends_on", "down_revision", "downgrade", "revision", "upgrade"]

_LABELS = {
    "environmental": ("Umweltverstoss", "Umweltverstoß"),
    "data_protection": ("Datenschutzverstoss", "Datenschutzverstoß"),
}


def _relabel(old_index: int, new_index: int) -> None:
    for slug, labels in _LABELS.items():
        op.execute(
            sa.text(
                "UPDATE report_categories SET label_de = :new"
                " WHERE slug = :slug AND is_default AND label_de = :old"
            ).bindparams(slug=slug, old=labels[old_index], new=labels[new_index])
        )


def upgrade() -> None:
    _relabel(0, 1)


def downgrade() -> None:
    _relabel(1, 0)
