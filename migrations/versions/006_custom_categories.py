"""Replace hardcoded category enum with DB-driven report_categories table.

Revision ID: 006
Revises: 005
Create Date: 2026-04-26
"""

from collections.abc import Sequence

from alembic import op

revision: str = "006"
down_revision: str | None = "005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE report_categories (
            id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
            slug        VARCHAR(64) UNIQUE NOT NULL,
            label_en    VARCHAR(128) NOT NULL,
            label_de    VARCHAR(128) NOT NULL,
            is_default  BOOLEAN NOT NULL DEFAULT FALSE,
            is_active   BOOLEAN NOT NULL DEFAULT TRUE,
            sort_order  INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Seed default categories
    op.execute("""
        INSERT INTO report_categories (slug, label_en, label_de, is_default, sort_order) VALUES
        ('financial_fraud',  'Financial Fraud',           'Finanzbetrug',               TRUE, 1),
        ('workplace_safety', 'Workplace Safety',          'Arbeitssicherheit',           TRUE, 2),
        ('environmental',    'Environmental Violation',   'Umweltverstoss',              TRUE, 3),
        ('corruption',       'Corruption / Bribery',      'Korruption / Bestechung',     TRUE, 4),
        ('data_protection',  'Data Protection Violation', 'Datenschutzverstoss',         TRUE, 5),
        ('discrimination',   'Discrimination / Harassment','Diskriminierung / Belästigung',TRUE,6),
        ('other',            'Other',                     'Sonstiges',                   TRUE, 99)
    """)

    # Migrate reports.category from enum type to VARCHAR
    # First add a temp column, copy data, drop enum column, rename
    op.execute("ALTER TABLE reports ADD COLUMN category_text VARCHAR(64)")
    op.execute("UPDATE reports SET category_text = category::text")
    op.execute("ALTER TABLE reports DROP COLUMN category")
    op.execute("ALTER TABLE reports RENAME COLUMN category_text TO category")
    op.execute("ALTER TABLE reports ALTER COLUMN category SET NOT NULL")

    # Drop the now-unused Python enum type from DB
    op.execute("DROP TYPE IF EXISTS reportcategory")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS report_categories")
    # Restore enum and column — data loss for custom categories
    op.execute("""
        CREATE TYPE reportcategory AS ENUM (
            'financial_fraud','workplace_safety','environmental',
            'corruption','data_protection','discrimination','other'
        )
    """)
    op.execute("ALTER TABLE reports ADD COLUMN category_enum reportcategory")
    op.execute("""
        UPDATE reports SET category_enum = category::reportcategory
        WHERE category IN (
            'financial_fraud','workplace_safety','environmental',
            'corruption','data_protection','discrimination','other'
        )
    """)
    op.execute("UPDATE reports SET category_enum = 'other' WHERE category_enum IS NULL")
    op.execute("ALTER TABLE reports DROP COLUMN category")
    op.execute("ALTER TABLE reports RENAME COLUMN category_enum TO category")
    op.execute("ALTER TABLE reports ALTER COLUMN category SET NOT NULL")
