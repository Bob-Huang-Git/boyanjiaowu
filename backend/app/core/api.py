"""跨模块共用的 API 辅助函数。

建立本模块的原因：``error`` / ``code`` / ``audit`` / ``checked`` 这四个函数
原本在 sprint1 / exam / teaching / finance 四个 router 里各复制了一份
（见 docs/architecture/design-conformance-review-2026-09-23.md 关于缺少
service 层的分析）。新增模块不再复制，统一从这里引用。

既有模块**不在本批次改动**——按渐进原则，它们可在后续重构时逐步切换过来。
"""

import json
import uuid
from typing import Any

from fastapi import HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import AuditLog, CourseEnrollment, User


def error(status: int, code: str, message: str) -> HTTPException:
    """统一错误响应：``{"code": ..., "message": ...}``。"""
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def business_code(prefix: str) -> str:
    """生成业务单号，如 ``FC`` + 12 位大写十六进制。"""
    return f"{prefix}{uuid.uuid4().hex[:12].upper()}"


def audit(
    db: Session,
    user: User,
    request: Request,
    action: str,
    kind: str,
    item_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    """写业务审计日志。运行日志与业务 AuditLog 分离（设计 Prompt 11 第七节）。"""
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            actor_user_id=user.id,
            action=action,
            subject_type=kind,
            subject_id=item_id,
            correlation_id=request.state.correlation_id,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )


def checked(item: Any, version: int) -> None:
    """乐观锁校验：版本不一致即拒绝，防止并发覆盖。"""
    if item.version != version:
        raise error(409, "VERSION_CONFLICT", "记录已被其他操作更新，请刷新后重试。")


def scoped(
    db: Session, model: Any, item_id: str, user: User, not_found_code: str, label: str
) -> Any:
    """按组织边界取对象，取不到统一抛 404（不泄露跨组织对象是否存在）。"""
    item = db.scalar(
        select(model).where(model.id == item_id, model.organization_id == user.organization_id)
    )
    if not item:
        raise error(404, not_found_code, f"未找到{label}。")
    return item


def enrollment_for(db: Session, user: User, item_id: str) -> CourseEnrollment:
    return scoped(db, CourseEnrollment, item_id, user, "ENROLLMENT_NOT_FOUND", "报名")
