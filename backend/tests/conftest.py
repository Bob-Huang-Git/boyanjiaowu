from collections.abc import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.core.db import Base, get_db, make_engine
from app.core.models import Organization, Permission, Role, RolePermission, User, UserRole
from app.core.security import hash_password
from app.main import app


@pytest.fixture
def db_engine(tmp_path):  # noqa: ANN001
    engine = make_engine(str(tmp_path / "test.db"))
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


@pytest.fixture
def seeded_db(db_engine):  # noqa: ANN001
    with Session(db_engine) as db:
        org = Organization(name="Test school")
        db.add(org)
        db.flush()
        admin_role = Role(organization_id=org.id, code="admin", name="Admin")
        reader_role = Role(organization_id=org.id, code="reader", name="Reader")
        permission = Permission(code="system.admin", description="Manage system")
        db.add_all([admin_role, reader_role, permission])
        db.flush()
        admin = User(
            organization_id=org.id,
            username="admin",
            display_name="Admin",
            password_hash=hash_password("correct-password"),
        )
        reader = User(
            organization_id=org.id,
            username="reader",
            display_name="Reader",
            password_hash=hash_password("correct-password"),
        )
        db.add_all([admin, reader])
        db.flush()
        db.add_all(
            [
                UserRole(organization_id=org.id, user_id=admin.id, role_id=admin_role.id),
                UserRole(organization_id=org.id, user_id=reader.id, role_id=reader_role.id),
                RolePermission(
                    organization_id=org.id,
                    role_id=admin_role.id,
                    permission_id=permission.id,
                ),
            ]
        )
        db.commit()
    return db_engine


@pytest.fixture
def client(seeded_db) -> Generator[TestClient, None, None]:  # noqa: ANN001
    def test_db():
        with Session(seeded_db) as db:
            yield db

    app.dependency_overrides[get_db] = test_db
    with TestClient(app) as test_client:
        yield test_client
    app.dependency_overrides.clear()
