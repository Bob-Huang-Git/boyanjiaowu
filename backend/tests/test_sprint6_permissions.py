from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.cli.sync_sprint6_permissions import sync
from app.core.models import Permission, Role, RolePermission
from app.core.permission_catalog import SPRINT6_PERMISSIONS


def test_sprint6_permission_sync_is_complete_and_idempotent(seeded_db):  # noqa: ANN001
    with Session(seeded_db) as db:
        assert sync(db) == 1
        db.commit()
        assert sync(db) == 1
        db.commit()

        admin = db.scalar(select(Role).where(Role.code == "admin"))
        saved_codes = set(
            db.scalars(
                select(Permission.code)
                .join(RolePermission, RolePermission.permission_id == Permission.id)
                .where(RolePermission.role_id == admin.id)
            ).all()
        )
        assert set(SPRINT6_PERMISSIONS) <= saved_codes
        link_count = db.scalar(
            select(func.count(RolePermission.id)).where(RolePermission.role_id == admin.id)
        )
        assert link_count == len(SPRINT6_PERMISSIONS) + 1
