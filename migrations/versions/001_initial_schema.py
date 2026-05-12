"""Initial schema — complete state as of v1.1.0, replaces migrations 001-015.

Revision ID: 26b6f459846b
Revises:
Create Date: 2026-05-12

Compared to the old incremental migrations this single revision:
- Creates all tables in their final form (no intermediate ALTER steps)
- Seeds the default organisation and the seven built-in report categories
- Avoids the asyncpg ENUM transaction-boundary bug that existed in migration 003
  (new ENUM values are declared at CREATE TYPE time, never via ADD VALUE)
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = '26b6f459846b'
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# Fixed UUID so category rows can reference the org in the same migration.
_DEFAULT_ORG_ID = "00000000-0000-0000-0000-000000000001"


def upgrade() -> None:
    # ── organisations ────────────────────────────────────────────────────────
    op.create_table(
        'organisations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('is_active', sa.Boolean(), server_default='true', nullable=False),
        sa.Column('branding', sa.JSON(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_organisations_slug'), 'organisations', ['slug'], unique=True)

    # ── setup_status ─────────────────────────────────────────────────────────
    op.create_table(
        'setup_status',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('completed', sa.Boolean(), nullable=False),
        sa.Column('completed_at', sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── admin_users ──────────────────────────────────────────────────────────
    op.create_table(
        'admin_users',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('username', sa.String(length=64), nullable=False),
        sa.Column('password_hash', sa.String(length=72), nullable=True),
        sa.Column('totp_secret', sa.String(length=32), nullable=False),
        sa.Column('totp_enabled', sa.Boolean(), nullable=False),
        sa.Column('role', sa.Enum('superadmin', 'admin', 'case_manager', name='adminrole'), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('oidc_sub', sa.String(length=255), nullable=True),
        sa.Column('oidc_issuer', sa.String(length=255), nullable=True),
        sa.Column('ldap_username', sa.String(length=255), nullable=True),
        sa.Column('org_id', sa.UUID(), nullable=True),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('last_login_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('ldap_username'),
        sa.UniqueConstraint('oidc_sub'),
    )
    op.create_index(op.f('ix_admin_users_org_id'), 'admin_users', ['org_id'], unique=False)
    op.create_index(op.f('ix_admin_users_username'), 'admin_users', ['username'], unique=True)

    # ── locations ────────────────────────────────────────────────────────────
    op.create_table(
        'locations',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('name', sa.String(length=128), nullable=False),
        sa.Column('code', sa.String(length=32), nullable=False),
        sa.Column('description', sa.Text(), nullable=True),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('code', 'org_id', name='uq_locations_code_org'),
    )
    op.create_index(op.f('ix_locations_code'), 'locations', ['code'], unique=False)
    op.create_index(op.f('ix_locations_org_id'), 'locations', ['org_id'], unique=False)

    # ── report_categories ────────────────────────────────────────────────────
    op.create_table(
        'report_categories',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('slug', sa.String(length=64), nullable=False),
        sa.Column('label_en', sa.String(length=128), nullable=False),
        sa.Column('label_de', sa.String(length=128), nullable=False),
        sa.Column('is_default', sa.Boolean(), nullable=False),
        sa.Column('is_active', sa.Boolean(), nullable=False),
        sa.Column('sort_order', sa.Integer(), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('slug', 'org_id', name='uq_report_categories_slug_org'),
    )
    op.create_index(op.f('ix_report_categories_org_id'), 'report_categories', ['org_id'], unique=False)
    op.create_index(op.f('ix_report_categories_slug'), 'report_categories', ['slug'], unique=False)

    # ── reports ──────────────────────────────────────────────────────────────
    op.create_table(
        'reports',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('case_number', sa.String(length=20), nullable=False),
        sa.Column('pin_hash', sa.String(length=72), nullable=False),
        sa.Column('org_id', sa.UUID(), nullable=True),
        sa.Column('category', sa.String(length=64), nullable=False),
        sa.Column('description', sa.Text(), nullable=False),
        sa.Column('encrypted_dek', sa.Text(), nullable=False),
        sa.Column('status', sa.Enum('received', 'in_review', 'pending_feedback', 'closed', name='reportstatus'), nullable=False),
        sa.Column('submission_mode', sa.Enum('anonymous', 'confidential', name='submissionmode'), server_default='anonymous', nullable=False),
        sa.Column('location_id', sa.UUID(), nullable=True),
        sa.Column('confidential_name', sa.Text(), nullable=True),
        sa.Column('confidential_contact', sa.Text(), nullable=True),
        sa.Column('secure_email', sa.Text(), nullable=True),
        sa.Column('assigned_to_id', sa.UUID(), nullable=True),
        sa.Column('submitted_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('acknowledged_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('feedback_due_at', sa.DateTime(timezone=True), nullable=True),
        sa.Column('closed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['assigned_to_id'], ['admin_users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['location_id'], ['locations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_reports_assigned_to_id'), 'reports', ['assigned_to_id'], unique=False)
    op.create_index(op.f('ix_reports_case_number'), 'reports', ['case_number'], unique=True)
    op.create_index(op.f('ix_reports_location_id'), 'reports', ['location_id'], unique=False)
    op.create_index(op.f('ix_reports_org_id'), 'reports', ['org_id'], unique=False)

    # ── admin_notes ──────────────────────────────────────────────────────────
    op.create_table(
        'admin_notes',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('author_id', sa.UUID(), nullable=True),
        sa.Column('author_username', sa.String(length=64), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['author_id'], ['admin_users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_admin_notes_report_id'), 'admin_notes', ['report_id'], unique=False)

    # ── attachments ──────────────────────────────────────────────────────────
    op.create_table(
        'attachments',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('filename', sa.String(length=255), nullable=False),
        sa.Column('content_type', sa.String(length=128), nullable=False),
        sa.Column('size', sa.Integer(), nullable=False),
        sa.Column('data', sa.LargeBinary(), nullable=True),
        sa.Column('storage_key', sa.String(length=512), nullable=True),
        sa.Column('uploaded_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_attachments_report_id'), 'attachments', ['report_id'], unique=False)

    # ── audit_log ────────────────────────────────────────────────────────────
    op.create_table(
        'audit_log',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('admin_id', sa.UUID(), nullable=True),
        sa.Column('admin_username', sa.String(length=64), nullable=False),
        sa.Column('action', sa.String(length=64), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=True),
        sa.Column('detail', sa.Text(), nullable=True),
        sa.Column('org_id', sa.UUID(), nullable=True),
        sa.ForeignKeyConstraint(['admin_id'], ['admin_users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['org_id'], ['organisations.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_audit_log_action'), 'audit_log', ['action'], unique=False)
    op.create_index(op.f('ix_audit_log_created_at'), 'audit_log', ['created_at'], unique=False)
    op.create_index(op.f('ix_audit_log_org_id'), 'audit_log', ['org_id'], unique=False)
    op.create_index(op.f('ix_audit_log_report_id'), 'audit_log', ['report_id'], unique=False)

    # ── case_links ───────────────────────────────────────────────────────────
    op.create_table(
        'case_links',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('report_id_a', sa.UUID(), nullable=False),
        sa.Column('report_id_b', sa.UUID(), nullable=False),
        sa.Column('linked_by_id', sa.UUID(), nullable=True),
        sa.Column('linked_by_username', sa.String(length=64), nullable=False),
        sa.Column('linked_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['linked_by_id'], ['admin_users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['report_id_a'], ['reports.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['report_id_b'], ['reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )

    # ── deletion_requests ────────────────────────────────────────────────────
    op.create_table(
        'deletion_requests',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('requested_by_id', sa.UUID(), nullable=True),
        sa.Column('requested_by_username', sa.String(length=64), nullable=False),
        sa.Column('requested_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.Column('confirmed_by_id', sa.UUID(), nullable=True),
        sa.Column('confirmed_by_username', sa.String(length=64), nullable=True),
        sa.Column('confirmed_at', sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(['confirmed_by_id'], ['admin_users.id'], ondelete='SET NULL'),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ondelete='CASCADE'),
        sa.ForeignKeyConstraint(['requested_by_id'], ['admin_users.id'], ondelete='SET NULL'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('report_id'),
    )

    # ── report_messages ──────────────────────────────────────────────────────
    op.create_table(
        'report_messages',
        sa.Column('id', sa.UUID(), nullable=False),
        sa.Column('report_id', sa.UUID(), nullable=False),
        sa.Column('sender', sa.Enum('whistleblower', 'admin', name='reportsender'), nullable=False),
        sa.Column('content', sa.Text(), nullable=False),
        sa.Column('sent_at', sa.DateTime(timezone=True), server_default=sa.text('now()'), nullable=False),
        sa.ForeignKeyConstraint(['report_id'], ['reports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
    )
    op.create_index(op.f('ix_report_messages_report_id'), 'report_messages', ['report_id'], unique=False)

    # ── seed data ────────────────────────────────────────────────────────────
    # setup_status row — wizard marks it complete after first-run setup
    op.execute(sa.text("INSERT INTO setup_status (id, completed) VALUES (1, false)"))

    # default organisation — fixed UUID so category rows can reference it below
    op.execute(sa.text(
        f"INSERT INTO organisations (id, name, slug, is_active, created_at) "
        f"VALUES ('{_DEFAULT_ORG_ID}', 'Default Organisation', 'default', true, NOW())"
    ))

    # built-in report categories (from migration 006), linked to default org
    op.execute(sa.text(f"""
        INSERT INTO report_categories
            (id, slug, label_en, label_de, is_default, is_active, sort_order, org_id)
        VALUES
            (gen_random_uuid(), 'financial_fraud',  'Financial Fraud',            'Finanzbetrug',                TRUE, TRUE,  1, '{_DEFAULT_ORG_ID}'),
            (gen_random_uuid(), 'workplace_safety', 'Workplace Safety',           'Arbeitssicherheit',           TRUE, TRUE,  2, '{_DEFAULT_ORG_ID}'),
            (gen_random_uuid(), 'environmental',    'Environmental Violation',    'Umweltverstoss',              TRUE, TRUE,  3, '{_DEFAULT_ORG_ID}'),
            (gen_random_uuid(), 'corruption',       'Corruption / Bribery',       'Korruption / Bestechung',     TRUE, TRUE,  4, '{_DEFAULT_ORG_ID}'),
            (gen_random_uuid(), 'data_protection',  'Data Protection Violation',  'Datenschutzverstoss',         TRUE, TRUE,  5, '{_DEFAULT_ORG_ID}'),
            (gen_random_uuid(), 'discrimination',   'Discrimination / Harassment','Diskriminierung / Belästigung',TRUE, TRUE, 6, '{_DEFAULT_ORG_ID}'),
            (gen_random_uuid(), 'other',            'Other',                      'Sonstiges',                   TRUE, TRUE, 99, '{_DEFAULT_ORG_ID}')
    """))


def downgrade() -> None:
    op.drop_index(op.f('ix_report_messages_report_id'), table_name='report_messages')
    op.drop_table('report_messages')
    op.drop_table('deletion_requests')
    op.drop_table('case_links')
    op.drop_index(op.f('ix_audit_log_report_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_org_id'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_created_at'), table_name='audit_log')
    op.drop_index(op.f('ix_audit_log_action'), table_name='audit_log')
    op.drop_table('audit_log')
    op.drop_index(op.f('ix_attachments_report_id'), table_name='attachments')
    op.drop_table('attachments')
    op.drop_index(op.f('ix_admin_notes_report_id'), table_name='admin_notes')
    op.drop_table('admin_notes')
    op.drop_index(op.f('ix_reports_org_id'), table_name='reports')
    op.drop_index(op.f('ix_reports_location_id'), table_name='reports')
    op.drop_index(op.f('ix_reports_case_number'), table_name='reports')
    op.drop_index(op.f('ix_reports_assigned_to_id'), table_name='reports')
    op.drop_table('reports')
    op.drop_index(op.f('ix_report_categories_slug'), table_name='report_categories')
    op.drop_index(op.f('ix_report_categories_org_id'), table_name='report_categories')
    op.drop_table('report_categories')
    op.drop_index(op.f('ix_locations_org_id'), table_name='locations')
    op.drop_index(op.f('ix_locations_code'), table_name='locations')
    op.drop_table('locations')
    op.drop_index(op.f('ix_admin_users_username'), table_name='admin_users')
    op.drop_index(op.f('ix_admin_users_org_id'), table_name='admin_users')
    op.drop_table('admin_users')
    op.drop_table('setup_status')
    op.drop_index(op.f('ix_organisations_slug'), table_name='organisations')
    op.drop_table('organisations')
    op.execute(sa.text("DROP TYPE IF EXISTS reportsender"))
    op.execute(sa.text("DROP TYPE IF EXISTS submissionmode"))
    op.execute(sa.text("DROP TYPE IF EXISTS reportstatus"))
    op.execute(sa.text("DROP TYPE IF EXISTS adminrole"))
