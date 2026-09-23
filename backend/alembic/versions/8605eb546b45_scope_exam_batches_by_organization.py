# ruff: noqa: E501
"""scope exam batches by organization

Revision ID: 8605eb546b45
Revises: 4ffc2789065a
Create Date: 2026-09-23 08:24:26.957756
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "8605eb546b45"
down_revision: str | None = "4ffc2789065a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("exam_batches", schema=None) as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.String(length=36), nullable=True))
    op.execute(
        "UPDATE exam_batches SET organization_id = COALESCE("
        "(SELECT organization_id FROM users WHERE users.id = exam_batches.created_by), "
        "(SELECT id FROM organizations ORDER BY created_at LIMIT 1))"
    )
    with op.batch_alter_table("exam_batches", schema=None) as batch_op:
        batch_op.alter_column("organization_id", existing_type=sa.String(length=36), nullable=False)
        batch_op.create_index(
            batch_op.f("ix_exam_batches_organization_id"), ["organization_id"], unique=False
        )
        batch_op.create_foreign_key(
            "fk_exam_batches_organization", "organizations", ["organization_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("exam_batches", schema=None) as batch_op:
        batch_op.drop_constraint("fk_exam_batches_organization", type_="foreignkey")
        batch_op.drop_index(batch_op.f("ix_exam_batches_organization_id"))
        batch_op.drop_column("organization_id")
