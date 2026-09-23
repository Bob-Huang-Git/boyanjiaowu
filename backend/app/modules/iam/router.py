from datetime import timedelta
from typing import Annotated

from fastapi import APIRouter, Cookie, Depends, Header, HTTPException, Request, Response
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.core.db import get_db
from app.core.models import (
    AuditLog,
    Permission,
    RolePermission,
    User,
    UserRole,
    UserSession,
    utc_now,
)
from app.core.security import csrf_digest, random_token, token_digest, verify_password

router = APIRouter(prefix="/api/auth", tags=["auth"])
Db = Annotated[Session, Depends(get_db)]


class LoginBody(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    password: str = Field(min_length=1)


def audit(db: Session, user: User, action: str, request: Request, subject_id: str) -> None:
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            actor_user_id=user.id,
            action=action,
            subject_type="user_session",
            subject_id=subject_id,
            correlation_id=request.state.correlation_id,
        )
    )


def current_context(
    db: Db,
    session_token: Annotated[str | None, Cookie(alias=get_settings().session_cookie_name)] = None,
) -> tuple[User, UserSession]:
    if not session_token:
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    user_session = db.scalar(
        select(UserSession).where(UserSession.token_hash == token_digest(session_token))
    )
    if user_session is None or user_session.revoked_at or user_session.expires_at <= utc_now():
        raise HTTPException(status_code=401, detail="SESSION_EXPIRED")
    user = db.get(User, user_session.user_id)
    if user is None or not user.active or user.organization_id != user_session.organization_id:
        raise HTTPException(status_code=401, detail="AUTH_REQUIRED")
    return user, user_session


Context = Annotated[tuple[User, UserSession], Depends(current_context)]


def csrf_context(
    context: Context,
    csrf_cookie: Annotated[str | None, Cookie(alias="csrf_token")] = None,
    csrf_header: Annotated[str | None, Header(alias="X-CSRF-Token")] = None,
) -> tuple[User, UserSession]:
    if not csrf_cookie or not csrf_header or csrf_cookie != csrf_header:
        raise HTTPException(status_code=403, detail="CSRF_INVALID")
    if csrf_digest(csrf_header) != context[1].csrf_hash:
        raise HTTPException(status_code=403, detail="CSRF_INVALID")
    return context


CsrfContext = Annotated[tuple[User, UserSession], Depends(csrf_context)]


def permissions_for(db: Session, user_id: str) -> set[str]:
    stmt = (
        select(Permission.code)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .join(UserRole, UserRole.role_id == RolePermission.role_id)
        .where(UserRole.user_id == user_id)
    )
    return set(db.scalars(stmt).all())


def require_permission(code: str):
    def dependency(context: Context, db: Db) -> User:
        permissions = permissions_for(db, context[0].id)
        if code not in permissions and "system.admin" not in permissions:
            raise HTTPException(status_code=403, detail="PERMISSION_DENIED")
        return context[0]

    return dependency


@router.post("/login")
def login(body: LoginBody, request: Request, response: Response, db: Db) -> dict:
    user = db.scalar(select(User).where(User.username == body.username, User.active.is_(True)))
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(status_code=401, detail="INVALID_CREDENTIALS")
    token, csrf = random_token(), random_token()
    user_session = UserSession(
        organization_id=user.organization_id,
        user_id=user.id,
        token_hash=token_digest(token),
        csrf_hash=csrf_digest(csrf),
        expires_at=utc_now() + timedelta(hours=12),
        ip_address=request.client.host if request.client else None,
        user_agent_hash=token_digest(request.headers.get("user-agent", "")),
    )
    db.add(user_session)
    db.flush()
    audit(db, user, "auth.login", request, user_session.id)
    db.commit()
    secure = get_settings().cookie_secure
    response.set_cookie(
        get_settings().session_cookie_name,
        token,
        httponly=True,
        secure=secure,
        samesite=get_settings().session_samesite,
        max_age=43200,
        path="/",
    )
    response.set_cookie(
        "csrf_token", csrf, httponly=False, secure=secure, samesite="lax", max_age=43200, path="/"
    )
    return {
        "id": user.id,
        "display_name": user.display_name,
        "permissions": sorted(permissions_for(db, user.id)),
    }


@router.get("/me")
def me(context: Context, db: Db) -> dict:
    user = context[0]
    return {
        "id": user.id,
        "display_name": user.display_name,
        "permissions": sorted(permissions_for(db, user.id)),
    }


@router.post("/logout")
def logout(context: CsrfContext, request: Request, response: Response, db: Db) -> dict:
    user, user_session = context
    user_session.revoked_at = utc_now()
    audit(db, user, "auth.logout", request, user_session.id)
    db.commit()
    response.delete_cookie(get_settings().session_cookie_name, path="/")
    response.delete_cookie("csrf_token", path="/")
    return {"ok": True}


@router.post("/sessions/{session_id}/revoke")
def revoke(session_id: str, context: CsrfContext, request: Request, db: Db) -> dict:
    user = context[0]
    target = db.scalar(
        select(UserSession).where(UserSession.id == session_id, UserSession.user_id == user.id)
    )
    if target is None:
        raise HTTPException(status_code=404, detail="NOT_FOUND")
    target.revoked_at = utc_now()
    audit(db, user, "auth.revoke", request, target.id)
    db.commit()
    return {"ok": True}
