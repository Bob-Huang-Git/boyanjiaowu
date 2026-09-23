"""培训权益与滚班财务处理。

设计依据：《职业培训教务系统 Codex 提示词》Prompt 5 第四节——
「实现轻量 TrainingEntitlement 或等效记录」，以及
「ClassMembership 的 ``financial_treatment`` 决定新班学习是否重复消耗或产生补差 Charge」。

职责边界
--------
本模块只实现**机制**：分钟额度的登记、消耗、扣减，以及滚班财务处理的分派。
具体计费口径（哪些滚班情形免费、补差单价、退费可退分钟如何扣减）由业务方确认，
见 ``docs/implementation/roadmap.md`` 的「真实资料待确认」。**本模块不编造任何金额与政策。**

一致性保证
----------
1. 汇总（``TrainingEntitlement``）与明细（``TrainingEntitlementEntry``）在同一事务内写入；
2. 每次变动必须带 ``idempotency_key``，由「组织 + key」唯一约束拦截重复请求；
3. 补差应收再用 ``source_type`` + ``source_id`` 唯一约束兜一层，防止重复生成 Charge；
4. 明细只增不改，冲正走反向分录（``reversal_of_entry_id``）；
5. 消耗不得使可用分钟为负（应用层校验 + 数据库 CHECK 约束双保险）。
"""

from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import (
    AuditLog,
    ClassMembership,
    CourseEnrollment,
    Receivable,
    TrainingEntitlement,
    TrainingEntitlementEntry,
    User,
)
from app.modules.iam.router import Db, require_permission

router = APIRouter(prefix="/api", tags=["training-entitlement"])

EntitlementRead = Annotated[User, Depends(require_permission("receivable.read"))]
EntitlementWrite = Annotated[User, Depends(require_permission("receivable.manage"))]

# ---------------------------------------------------------------------------
# 台账分录类型
# ---------------------------------------------------------------------------

ENTRY_PURCHASE = "PURCHASE"
ENTRY_GIFT = "GIFT"
ENTRY_FREE_ROLLOVER = "FREE_ROLLOVER"
ENTRY_SUPPLEMENT = "SUPPLEMENT"
ENTRY_CONSUME = "CONSUME"
ENTRY_REFUND_DEDUCT = "REFUND_DEDUCT"

ENTRY_TYPES = frozenset(
    {
        ENTRY_PURCHASE,
        ENTRY_GIFT,
        ENTRY_FREE_ROLLOVER,
        ENTRY_SUPPLEMENT,
        ENTRY_CONSUME,
        ENTRY_REFUND_DEDUCT,
    }
)

#: 分录类型 → 受其影响的汇总字段。常规分录累加；反向分录（冲正）累减。
_SUMMARY_FIELD: dict[str, str] = {
    ENTRY_PURCHASE: "purchased_minutes",
    ENTRY_GIFT: "gifted_minutes",
    ENTRY_FREE_ROLLOVER: "free_rollover_minutes",
    ENTRY_SUPPLEMENT: "supplement_minutes",
    ENTRY_CONSUME: "consumed_minutes",
    ENTRY_REFUND_DEDUCT: "refund_deducted_minutes",
}

#: 常规分录下增加可用权益的类型；其余类型（消耗、退费扣减）减少可用权益。
#: 反向分录（``reversal_of_entry_id`` 非空）方向取反。
_POSITIVE_ONLY = frozenset({ENTRY_PURCHASE, ENTRY_GIFT, ENTRY_FREE_ROLLOVER, ENTRY_SUPPLEMENT})

# ---------------------------------------------------------------------------
# 滚班财务处理方式
#
# ⚠️ 取值集合与分组是**实现定义**，用于承载机制；具体哪种滚班情形归哪一组，
#    取决于业务方确认。既有滚班接口的默认值为 CARRY_OVER。
# ---------------------------------------------------------------------------

TREATMENT_CARRY_OVER = "CARRY_OVER"
TREATMENT_FREE_ROLLOVER = "FREE_ROLLOVER"
TREATMENT_SUPPLEMENT_REQUIRED = "SUPPLEMENT_REQUIRED"
TREATMENT_RE_CONSUME = "RE_CONSUME"

ROLLOVER_TREATMENTS = frozenset(
    {
        TREATMENT_CARRY_OVER,
        TREATMENT_FREE_ROLLOVER,
        TREATMENT_SUPPLEMENT_REQUIRED,
        TREATMENT_RE_CONSUME,
    }
)

#: 免费结转：不重复消耗、不产生应收
FREE_ROLLOVER_TREATMENTS = frozenset({TREATMENT_CARRY_OVER, TREATMENT_FREE_ROLLOVER})
#: 需补差：只生成补差应收，不重复收全额培训费
BILLABLE_ROLLOVER_TREATMENTS = frozenset({TREATMENT_SUPPLEMENT_REQUIRED})

#: 补差应收的来源标识（与 Receivable 的 source_type + source_id 唯一约束配合做幂等）
SUPPLEMENT_SOURCE_TYPE = "CLASS_MEMBERSHIP_SUPPLEMENT"


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def _code(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12].upper()}"


def _audit(
    db: Session,
    user: User,
    correlation_id: str | None,
    action: str,
    subject_type: str,
    subject_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            actor_user_id=user.id,
            action=action,
            subject_type=subject_type,
            subject_id=subject_id,
            correlation_id=correlation_id,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )


def correlation_id_of(request: Request | None) -> str | None:
    state = getattr(request, "state", None)
    return getattr(state, "correlation_id", None)


# ---------------------------------------------------------------------------
# 领域服务
# ---------------------------------------------------------------------------


def available_minutes(entitlement: TrainingEntitlement) -> int:
    """可用分钟 = 购买 + 赠送 + 免费滚班 + 补差 - 已消耗 - 退费扣减。"""
    return (
        entitlement.purchased_minutes
        + entitlement.gifted_minutes
        + entitlement.free_rollover_minutes
        + entitlement.supplement_minutes
        - entitlement.consumed_minutes
        - entitlement.refund_deducted_minutes
    )


def entitlement_view(entitlement: TrainingEntitlement) -> dict[str, Any]:
    return {
        "id": entitlement.id,
        "course_enrollment_id": entitlement.course_enrollment_id,
        "purchased_minutes": entitlement.purchased_minutes,
        "gifted_minutes": entitlement.gifted_minutes,
        "free_rollover_minutes": entitlement.free_rollover_minutes,
        "supplement_minutes": entitlement.supplement_minutes,
        "consumed_minutes": entitlement.consumed_minutes,
        "refund_deducted_minutes": entitlement.refund_deducted_minutes,
        "total_minutes": entitlement.purchased_minutes + entitlement.gifted_minutes,
        "available_minutes": available_minutes(entitlement),
        "entitlement_status": entitlement.entitlement_status,
        "rule_version": entitlement.rule_version,
        "version": entitlement.version,
    }


def get_or_create_entitlement(
    db: Session,
    *,
    organization_id: str,
    course_enrollment_id: str,
    created_by: str | None = None,
    rule_version: str | None = None,
) -> TrainingEntitlement:
    entitlement = db.scalar(
        select(TrainingEntitlement).where(
            TrainingEntitlement.organization_id == organization_id,
            TrainingEntitlement.course_enrollment_id == course_enrollment_id,
        )
    )
    if entitlement is not None:
        return entitlement
    entitlement = TrainingEntitlement(
        organization_id=organization_id,
        course_enrollment_id=course_enrollment_id,
        rule_version=rule_version,
        created_by=created_by,
    )
    db.add(entitlement)
    db.flush()
    return entitlement


def post_entry(
    db: Session,
    *,
    entitlement: TrainingEntitlement,
    entry_type: str,
    minutes: int,
    idempotency_key: str,
    created_by: str,
    source_type: str | None = None,
    source_id: str | None = None,
    reason: str | None = None,
    rule_version: str | None = None,
    reversal_of_entry_id: str | None = None,
) -> tuple[TrainingEntitlementEntry, bool]:
    """登记一条权益变动，并同步汇总字段。返回 ``(entry, created)``。

    ``minutes`` 一律传**正数**，方向由 ``entry_type`` 决定：
    ``CONSUME`` / ``REFUND_DEDUCT`` 减少可用权益，其余增加。
    传入 ``reversal_of_entry_id`` 表示冲正分录，方向取反。
    """
    if entry_type not in ENTRY_TYPES:
        raise error(422, "ENTITLEMENT_ENTRY_TYPE_INVALID", "权益变动类型不受支持。")
    if minutes <= 0:
        raise error(422, "ENTITLEMENT_MINUTES_INVALID", "分钟数必须为正整数。")

    existing = db.scalar(
        select(TrainingEntitlementEntry).where(
            TrainingEntitlementEntry.organization_id == entitlement.organization_id,
            TrainingEntitlementEntry.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return existing, False

    is_reversal = reversal_of_entry_id is not None
    increases_available = entry_type in _POSITIVE_ONLY
    if is_reversal:
        increases_available = not increases_available
    if not increases_available and available_minutes(entitlement) < minutes:
        raise error(409, "ENTITLEMENT_INSUFFICIENT", "可用培训时长不足，无法完成本次扣减。")

    field = _SUMMARY_FIELD[entry_type]
    delta = minutes if increases_available else -minutes
    if is_reversal:
        setattr(entitlement, field, getattr(entitlement, field) - minutes)
    else:
        setattr(entitlement, field, getattr(entitlement, field) + minutes)

    entry = TrainingEntitlementEntry(
        organization_id=entitlement.organization_id,
        entitlement_id=entitlement.id,
        entry_type=entry_type,
        minutes_delta=delta,
        source_type=source_type,
        source_id=source_id,
        reason=reason,
        rule_version=rule_version or entitlement.rule_version,
        idempotency_key=idempotency_key,
        reversal_of_entry_id=reversal_of_entry_id,
        created_by=created_by,
    )
    db.add(entry)
    entitlement.updated_by = created_by
    entitlement.version += 1
    db.flush()
    return entry, True


def apply_rollover_financial_treatment(
    db: Session,
    *,
    user: User,
    enrollment: CourseEnrollment,
    membership: ClassMembership,
    treatment: str,
    idempotency_key: str,
    rollover_minutes: int = 0,
    supplement_minutes: int = 0,
    supplement_amount_cent: int = 0,
    rule_version: str | None = None,
    reason: str | None = None,
    correlation_id: str | None = None,
) -> dict[str, Any]:
    """按 ``ClassMembership.financial_treatment`` 执行滚班的财务动作。

    分派规则：

    - ``CARRY_OVER`` / ``FREE_ROLLOVER``：**免费**。仅登记免费滚班分钟，
      不消耗既有余额、不生成任何应收（对应必测用例「免费滚班不重复收费」）；
    - ``SUPPLEMENT_REQUIRED``：**只生成补差应收**（``receivable_type=SUPPLEMENT``），
      金额由调用方明确给出，不按任何写死单价推算（对应「补差滚班只生成补差 Charge」）；
    - ``RE_CONSUME``：新班学习继续消耗既有余额，滚班动作本身不产生分录与应收。

    幂等：同 ``idempotency_key`` 重复调用直接返回既有结果，不重复建账、不重复收费。
    """
    if treatment not in ROLLOVER_TREATMENTS:
        raise error(422, "ROLLOVER_TREATMENT_INVALID", "滚班财务处理方式不受支持。")
    if rollover_minutes < 0 or supplement_minutes < 0 or supplement_amount_cent < 0:
        raise error(422, "ROLLOVER_MINUTES_INVALID", "分钟数与金额不得为负。")

    entitlement = get_or_create_entitlement(
        db,
        organization_id=user.organization_id,
        course_enrollment_id=enrollment.id,
        created_by=user.id,
        rule_version=rule_version,
    )
    entry_key = f"rollover:{idempotency_key}"

    prior = db.scalar(
        select(TrainingEntitlementEntry).where(
            TrainingEntitlementEntry.organization_id == user.organization_id,
            TrainingEntitlementEntry.idempotency_key == entry_key,
        )
    )
    if prior is not None:
        return {
            "idempotent": True,
            "treatment": treatment,
            "entitlement": entitlement_view(entitlement),
            "entry_id": prior.id,
            "receivable_id": None,
        }

    entry_id: str | None = None
    receivable_id: str | None = None
    applied: str

    if treatment in FREE_ROLLOVER_TREATMENTS:
        applied = "FREE"
        if rollover_minutes > 0:
            entry, _ = post_entry(
                db,
                entitlement=entitlement,
                entry_type=ENTRY_FREE_ROLLOVER,
                minutes=rollover_minutes,
                idempotency_key=entry_key,
                created_by=user.id,
                source_type="CLASS_MEMBERSHIP",
                source_id=membership.id,
                reason=reason or f"滚班免费结转（{treatment}）",
                rule_version=rule_version,
            )
            entry_id = entry.id

    elif treatment in BILLABLE_ROLLOVER_TREATMENTS:
        applied = "SUPPLEMENT"
        if supplement_amount_cent <= 0:
            raise error(
                422,
                "ROLLOVER_SUPPLEMENT_AMOUNT_REQUIRED",
                "补差滚班必须明确补差金额，系统不推算写死单价。",
            )
        existing_receivable = db.scalar(
            select(Receivable).where(
                Receivable.source_type == SUPPLEMENT_SOURCE_TYPE,
                Receivable.source_id == membership.id,
            )
        )
        if existing_receivable is None:
            receivable = Receivable(
                organization_id=user.organization_id,
                receivable_no=_code("AR"),
                course_enrollment_id=enrollment.id,
                student_id=enrollment.student_id,
                receivable_type="SUPPLEMENT",
                economic_nature="SCHOOL_REVENUE",
                source_type=SUPPLEMENT_SOURCE_TYPE,
                source_id=membership.id,
                fee_policy_version_id=enrollment.fee_policy_version_id,
                original_amount_cent=supplement_amount_cent,
                adjusted_amount_cent=0,
                payable_amount_cent=supplement_amount_cent,
                receivable_status="DRAFT",
                description=f"滚班补差（班级经历 {membership.id}）",
                created_by=user.id,
            )
            db.add(receivable)
            db.flush()
            existing_receivable = receivable
        receivable_id = existing_receivable.id
        if supplement_minutes > 0:
            entry, _ = post_entry(
                db,
                entitlement=entitlement,
                entry_type=ENTRY_SUPPLEMENT,
                minutes=supplement_minutes,
                idempotency_key=entry_key,
                created_by=user.id,
                source_type="CLASS_MEMBERSHIP",
                source_id=membership.id,
                reason=reason or "滚班补差购买时长",
                rule_version=rule_version,
            )
            entry_id = entry.id

    else:  # TREATMENT_RE_CONSUME
        applied = "RE_CONSUME"

    _audit(
        db,
        user,
        correlation_id,
        "enrollment.rollover.financial_treatment",
        "class_membership",
        membership.id,
        {
            "treatment": treatment,
            "applied": applied,
            "rollover_minutes": rollover_minutes,
            "supplement_minutes": supplement_minutes,
            "supplement_amount_cent": supplement_amount_cent,
            "receivable_id": receivable_id,
            "entry_id": entry_id,
        },
    )
    return {
        "idempotent": False,
        "treatment": treatment,
        "applied": applied,
        "entitlement": entitlement_view(entitlement),
        "entry_id": entry_id,
        "receivable_id": receivable_id,
    }


# ---------------------------------------------------------------------------
# HTTP 接口
# ---------------------------------------------------------------------------


def _enrollment_for(db: Session, user: User, enrollment_id: str) -> CourseEnrollment:
    enrollment = db.scalar(
        select(CourseEnrollment).where(
            CourseEnrollment.id == enrollment_id,
            CourseEnrollment.organization_id == user.organization_id,
        )
    )
    if not enrollment:
        raise error(404, "ENROLLMENT_NOT_FOUND", "未找到报名。")
    return enrollment


@router.get("/enrollments/{enrollment_id}/entitlement")
def read_entitlement(enrollment_id: str, db: Db, user: EntitlementRead) -> dict[str, Any]:
    """读取报名的培训权益台账（含最近变动明细）。"""
    enrollment = _enrollment_for(db, user, enrollment_id)
    entitlement = db.scalar(
        select(TrainingEntitlement).where(
            TrainingEntitlement.course_enrollment_id == enrollment.id,
            TrainingEntitlement.organization_id == user.organization_id,
        )
    )
    if entitlement is None:
        return {"entitlement": None, "entries": []}
    entries = db.scalars(
        select(TrainingEntitlementEntry)
        .where(TrainingEntitlementEntry.entitlement_id == entitlement.id)
        .order_by(TrainingEntitlementEntry.created_at.desc())
        .limit(100)
    ).all()
    return {
        "entitlement": entitlement_view(entitlement),
        "entries": [
            {
                "id": item.id,
                "entry_type": item.entry_type,
                "minutes_delta": item.minutes_delta,
                "source_type": item.source_type,
                "source_id": item.source_id,
                "reason": item.reason,
                "rule_version": item.rule_version,
                "occurred_at": item.occurred_at.isoformat(),
                "idempotency_key": item.idempotency_key,
                "reversal_of_entry_id": item.reversal_of_entry_id,
            }
            for item in entries
        ],
    }


class EntitlementEntryInput(BaseModel):
    entry_type: str
    minutes: int = Field(gt=0)
    idempotency_key: str = Field(min_length=8, max_length=100)
    source_type: str | None = None
    source_id: str | None = None
    reason: str | None = Field(default=None, max_length=500)
    rule_version: str | None = Field(default=None, max_length=40)
    reversal_of_entry_id: str | None = None


@router.post("/enrollments/{enrollment_id}/entitlement/entries")
def create_entitlement_entry(
    enrollment_id: str,
    payload: EntitlementEntryInput,
    request: Request,
    db: Db,
    user: EntitlementWrite,
) -> dict[str, Any]:
    """登记一条权益变动（购买 / 赠送 / 消耗 / 退费扣减；冲正传 ``reversal_of_entry_id``）。"""
    enrollment = _enrollment_for(db, user, enrollment_id)
    entitlement = get_or_create_entitlement(
        db,
        organization_id=user.organization_id,
        course_enrollment_id=enrollment.id,
        created_by=user.id,
        rule_version=payload.rule_version,
    )
    entry, created = post_entry(
        db,
        entitlement=entitlement,
        entry_type=payload.entry_type,
        minutes=payload.minutes,
        idempotency_key=payload.idempotency_key,
        created_by=user.id,
        source_type=payload.source_type,
        source_id=payload.source_id,
        reason=payload.reason,
        rule_version=payload.rule_version,
        reversal_of_entry_id=payload.reversal_of_entry_id,
    )
    if created:
        _audit(
            db,
            user,
            correlation_id_of(request),
            "training_entitlement.entry",
            "training_entitlement",
            entitlement.id,
            {
                "entry_type": entry.entry_type,
                "minutes_delta": entry.minutes_delta,
                "available_minutes": available_minutes(entitlement),
            },
        )
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - 唯一约束兜底
        db.rollback()
        raise error(409, "ENTITLEMENT_ENTRY_CONFLICT", "该权益变动已登记。") from exc
    db.refresh(entitlement)
    return {
        "entry": {
            "id": entry.id,
            "entry_type": entry.entry_type,
            "minutes_delta": entry.minutes_delta,
            "idempotency_key": entry.idempotency_key,
        },
        "created": created,
        "entitlement": entitlement_view(entitlement),
    }


class RolloverTreatmentInput(BaseModel):
    membership_id: str
    financial_treatment: str
    idempotency_key: str = Field(min_length=8, max_length=100)
    rollover_minutes: int = Field(default=0, ge=0)
    supplement_minutes: int = Field(default=0, ge=0)
    supplement_amount_cent: int = Field(default=0, ge=0)
    rule_version: str | None = Field(default=None, max_length=40)
    reason: str | None = Field(default=None, max_length=500)


@router.post("/enrollments/{enrollment_id}/entitlement/rollover-treatment")
def apply_rollover_treatment(
    enrollment_id: str,
    payload: RolloverTreatmentInput,
    request: Request,
    db: Db,
    user: EntitlementWrite,
) -> dict[str, Any]:
    """对一次班级经历的滚班财务处理补记／复核。

    正常滚班流程由班级模块在同事务内自动调用同一服务；
    本接口用于补记历史数据或人工复核，幂等键与滚班一致。
    """
    enrollment = _enrollment_for(db, user, enrollment_id)
    membership = db.get(ClassMembership, payload.membership_id)
    if membership is None or membership.course_enrollment_id != enrollment.id:
        raise error(404, "CLASS_MEMBERSHIP_NOT_FOUND", "未找到该报名下的班级经历。")
    result = apply_rollover_financial_treatment(
        db,
        user=user,
        enrollment=enrollment,
        membership=membership,
        treatment=payload.financial_treatment,
        idempotency_key=payload.idempotency_key,
        rollover_minutes=payload.rollover_minutes,
        supplement_minutes=payload.supplement_minutes,
        supplement_amount_cent=payload.supplement_amount_cent,
        rule_version=payload.rule_version,
        reason=payload.reason,
        correlation_id=correlation_id_of(request),
    )
    try:
        db.commit()
    except IntegrityError as exc:  # pragma: no cover - 唯一约束兜底
        db.rollback()
        raise error(409, "ROLLOVER_TREATMENT_CONFLICT", "该滚班财务处理已登记。") from exc
    return result


__all__ = [
    "ENTRY_CONSUME",
    "ENTRY_FREE_ROLLOVER",
    "ENTRY_GIFT",
    "ENTRY_PURCHASE",
    "ENTRY_REFUND_DEDUCT",
    "ENTRY_SUPPLEMENT",
    "TREATMENT_CARRY_OVER",
    "TREATMENT_FREE_ROLLOVER",
    "TREATMENT_RE_CONSUME",
    "TREATMENT_SUPPLEMENT_REQUIRED",
    "apply_rollover_financial_treatment",
    "available_minutes",
    "entitlement_view",
    "get_or_create_entitlement",
    "post_entry",
    "router",
]
