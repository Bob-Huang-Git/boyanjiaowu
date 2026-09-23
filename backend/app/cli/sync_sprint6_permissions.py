from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Permission, Role, RolePermission
from app.core.permission_catalog import SPRINT6_PERMISSIONS


def sync(db: Session) -> int:
    roles = db.scalars(select(Role).where(Role.code == "admin")).all()
    for code, description in SPRINT6_PERMISSIONS.items():
        permission = db.scalar(select(Permission).where(Permission.code == code))
        if permission is None:
            permission = Permission(code=code, description=description)
            db.add(permission)
            db.flush()
        for role in roles:
            exists = db.scalar(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.permission_id == permission.id,
                )
            )
            if exists is None:
                db.add(
                    RolePermission(
                        organization_id=role.organization_id,
                        role_id=role.id,
                        permission_id=permission.id,
                    )
                )
    return len(roles)


def main() -> None:
    with Session(get_engine()) as db:
        role_count = sync(db)
        db.commit()
    print(f"Sprint 6 permissions synchronized for {role_count} admin role(s)")


if __name__ == "__main__":
    main()
