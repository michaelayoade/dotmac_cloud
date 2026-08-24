"""Create the tenant-scoped Cloud adapter receipt ledger."""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "ca_0001_receipts"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = "cloud_assembly"
depends_on: str | Sequence[str] | None = None

TABLE = "cloud_adapter_receipts"
POLICY = "cloud_adapter_receipts_tenant_isolation"


def upgrade() -> None:
    """Create data, isolation and grants as one indivisible schema change."""
    op.create_table(
        TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("tenant_id", sa.Uuid(), nullable=False),
        sa.Column("adapter", sa.String(length=120), nullable=False),
        sa.Column("source_owner", sa.String(length=120), nullable=False),
        sa.Column("source_ref", sa.String(length=255), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False),
        sa.Column("fingerprint", sa.String(length=255), nullable=False),
        sa.Column("outcome", sa.String(length=16), nullable=False),
        sa.Column("observed_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "source_version > 0",
            name="ck_cloud_receipt_version_positive",
        ),
        sa.CheckConstraint(
            "outcome IN ('applied', 'refused')",
            name="ck_cloud_receipt_outcome",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "tenant_id",
            "adapter",
            "source_owner",
            "source_ref",
            "source_version",
            name="uq_cloud_receipt_exact_fact",
        ),
        schema="public",
    )
    op.create_index(
        "ix_cloud_receipt_reconciliation",
        TABLE,
        ["tenant_id", "adapter", "source_owner", "source_ref"],
        schema="public",
    )
    op.execute(f"ALTER TABLE public.{TABLE} ENABLE ROW LEVEL SECURITY")
    op.execute(f"ALTER TABLE public.{TABLE} FORCE ROW LEVEL SECURITY")
    op.execute(
        f"""
        CREATE POLICY {POLICY} ON public.{TABLE}
        USING (
            tenant_id = NULLIF(
                current_setting('app.current_tenant', true), ''
            )::uuid
        )
        WITH CHECK (
            tenant_id = NULLIF(
                current_setting('app.current_tenant', true), ''
            )::uuid
        )
        """
    )
    op.execute(f"REVOKE ALL ON TABLE public.{TABLE} FROM PUBLIC")
    op.execute(
        f"REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER "
        f"ON TABLE public.{TABLE} FROM app_user"
    )
    op.execute(f"GRANT SELECT, INSERT ON TABLE public.{TABLE} TO app_user")


def downgrade() -> None:
    """Remove the unreleased assembly ledger."""
    op.drop_index(
        "ix_cloud_receipt_reconciliation",
        table_name=TABLE,
        schema="public",
    )
    op.drop_table(TABLE, schema="public")
