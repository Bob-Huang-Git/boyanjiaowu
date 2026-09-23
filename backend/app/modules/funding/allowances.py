# ruff: noqa: E501, I001
"""P6 第二至七节：每日出勤事实、住宿事实、版本化政策、权益与支付。

设计约束（Prompt 6 原文）：

- 同一天多个课次**只能形成一条当前有效每日事实**；考勤更正后生成事实新版本，
  不覆盖已经申报的旧事实。数据库层由部分唯一索引
  ``uq_attendance_day_fact_current`` 保证，不依赖服务层自觉。
- 住宿补贴**必须有独立住宿事实**，不能只根据考勤推断。
- 餐补按每日出勤事实计算，**同一天多个课次不能重复产生按日餐补**——
  因为"每日事实"本身每个日期只有一条当前有效记录。
- 政策规则只允许**预定义策略 + 有类型参数**，禁止数据库执行任意
  Python / SQL / eval / 不受控 Jinja。
- 已发布政策不可修改，只能新建版本。
- **权益（政策算出多少）、应付（学校应向学员支付多少）、实付（实际支付多少）
  三者互不混淆**，分别落在三张表。
- 缺勤不产生权益。
"""

import json
from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.core.api import audit, checked, error, scoped
from app.core.models import (
    AllowancePayable,
    AllowancePayment,
    AllowancePolicy,
    AttendanceDayFact,
    AttendanceRecord,
    ClassCycle,
    ClassMembership,
    ClassSession,
    CourseEnrollment,
    EntitlementAdjustment,
    FundingCase,
    FundingProgramVersion,
    LodgingNightFact,
    LodgingStay,
    Student,
    SubsidyEntitlement,
    User,
    utc_now,
)
from app.modules.iam.router import Db, require_permission

router = APIRouter(prefix="/api", tags=["allowances"])

AllowanceRead = Annotated[User, Depends(require_permission("funding.allowance.read"))]
AllowanceManage = Annotated[User, Depends(require_permission("funding.allowance.manage"))]
PolicyPublish = Annotated[User, Depends(require_permission("funding.policy.publish"))]
AllowancePay = Annotated[User, Depends(require_permission("funding.allowance.pay"))]

# ---------------------------------------------------------------- 常量

ALLOWANCE_MEAL = "MEAL"
ALLOWANCE_LODGING = "LODGING"
ALLOWANCE_TYPES = frozenset({ALLOWANCE_MEAL, ALLOWANCE_LODGING})

#: 预定义策略。只允许这两种，参数走 ``rule_params_json`` 的**有类型**字段。
RULE_PER_ATTENDED_DAY = "PER_ATTENDED_DAY"
RULE_PER_LODGING_NIGHT = "PER_LODGING_NIGHT"
SUPPORTED_RULES = frozenset({RULE_PER_ATTENDED_DAY, RULE_PER_LODGING_NIGHT})

#: 策略 → 允许的补贴类型，防止把住宿策略挂到餐补上
RULE_ALLOWED_TYPES = {
    RULE_PER_ATTENDED_DAY: frozenset({ALLOWANCE_MEAL}),
    RULE_PER_LODGING_NIGHT: frozenset({ALLOWANCE_LODGING}),
}

DAY_FULL = "FULL_DAY"
DAY_HALF = "HALF_DAY"
DAY_NONE = "NONE"
DAY_UNCLASSIFIED = "UNCLASSIFIED"

ROUND_FLOOR = "FLOOR"
ROUND_HALF_UP = "ROUND_HALF_UP"

POLICY_DRAFT = "DRAFT"
POLICY_PUBLISHED = "PUBLISHED"
POLICY_RETIRED = "RETIRED"


# ---------------------------------------------------------------- 纯函数


def resolve_day_part(attended_minutes: int, half_day_minutes: int, full_day_minutes: int) -> str:
    """按出勤分钟判定半天/全天。

    ``NONE`` 覆盖"未出勤"与"出勤不足半天"两种情况——两者都不产生按日权益。
    """
    if attended_minutes <= 0:
        return DAY_NONE
    if attended_minutes >= full_day_minutes:
        return DAY_FULL
    if attended_minutes >= half_day_minutes:
        return DAY_HALF
    return DAY_NONE


def apply_rounding(amount: int, rule: str) -> int:
    """按政策舍入规则处理金额。金额全程整数分，不引入 float。"""
    if rule == ROUND_HALF_UP:
        return amount
    return amount


def policy_thresholds(policy: AllowancePolicy) -> tuple[int, int]:
    """取政策阈值；真实政策未提供时禁止用系统默认值代替。"""
    half = policy.half_day_threshold_minutes
    full = policy.full_day_threshold_minutes
    if half is None or full is None:
        raise error(
            422,
            "ALLOWANCE_POLICY_THRESHOLDS_REQUIRED",
            "餐补政策必须明确配置半天和全天分钟阈值。",
        )
    if full < half:
        raise error(422, "ALLOWANCE_POLICY_THRESHOLD_INVALID", "全天阈值不能小于半天阈值。")
    return half, full


def half_day_amount(policy: AllowancePolicy) -> int:
    """半天金额 = 单价 × ``half_day_percent`` / 100，全程整数分。"""
    try:
        params = json.loads(policy.rule_params_json) if policy.rule_params_json else {}
    except (TypeError, ValueError) as exc:
        raise error(422, "ALLOWANCE_POLICY_PARAMS_INVALID", "补贴政策参数不是有效 JSON。") from exc
    if not isinstance(params, dict) or "half_day_percent" not in params:
        raise error(
            422,
            "ALLOWANCE_POLICY_HALF_DAY_PERCENT_REQUIRED",
            "餐补政策必须明确配置半天计发比例。",
        )
    try:
        percent = int(params["half_day_percent"])
    except (TypeError, ValueError) as exc:
        raise error(
            422, "ALLOWANCE_POLICY_PERCENT_INVALID", "半天比例必须是 0 到 100 的整数。"
        ) from exc
    if not 0 <= percent <= 100:
        raise error(422, "ALLOWANCE_POLICY_PERCENT_INVALID", "半天比例必须在 0 到 100 之间。")
    if policy.rounding_rule == ROUND_HALF_UP:
        return (policy.unit_amount_cent * percent + 50) // 100
    return policy.unit_amount_cent * percent // 100


def validate_policy_rule(basis_rule: str, allowance_type: str) -> None:
    """校验策略与补贴类型的组合是否受支持。"""
    if basis_rule not in SUPPORTED_RULES:
        raise error(
            422,
            "ALLOWANCE_POLICY_RULE_UNSUPPORTED",
            "政策基准规则不受支持，只允许预定义策略。",
        )
    if allowance_type not in RULE_ALLOWED_TYPES[basis_rule]:
        raise error(
            422,
            "ALLOWANCE_POLICY_RULE_MISMATCH",
            "政策基准规则与补贴类型不匹配。",
        )


def validate_policy_configuration(
    allowance_type: str,
    half_day_threshold_minutes: int | None,
    full_day_threshold_minutes: int | None,
) -> None:
    """阻止缺失的正式政策字段被代码默认值静默补齐。"""
    if allowance_type != ALLOWANCE_MEAL:
        return
    if half_day_threshold_minutes is None or full_day_threshold_minutes is None:
        raise error(
            422,
            "ALLOWANCE_POLICY_THRESHOLDS_REQUIRED",
            "餐补政策必须明确配置半天和全天分钟阈值。",
        )
    if full_day_threshold_minutes < half_day_threshold_minutes:
        raise error(422, "ALLOWANCE_POLICY_THRESHOLD_INVALID", "全天阈值不能小于半天阈值。")


# ---------------------------------------------------------------- 政策解析


def membership_for(db, user: User, membership_id: str) -> ClassMembership:
    """按组织边界取班级经历。

    注意：``class_memberships`` 表**没有** ``organization_id`` 列
    （组织归属经 ``class_cycles`` 间接表达），因此不能使用通用
    ``scoped()``——这里显式沿 ``class_cycle`` 校验组织。
    """
    membership = db.get(ClassMembership, membership_id)
    if membership is None:
        raise error(404, "MEMBERSHIP_NOT_FOUND", "未找到班级经历。")
    cycle = db.get(ClassCycle, membership.class_cycle_id)
    if cycle is None or cycle.organization_id != user.organization_id:
        raise error(404, "MEMBERSHIP_NOT_FOUND", "未找到班级经历。")
    return membership


def classify_day_fact(
    db, enrollment: CourseEnrollment, fact_date: date, attended_minutes: int
) -> tuple[str, dict]:
    """只按已发布的真实政策分类；没有政策时保持未分类。"""
    if attended_minutes <= 0:
        return DAY_NONE, {"classification": "NO_ATTENDANCE"}
    case = db.scalar(select(FundingCase).where(FundingCase.course_enrollment_id == enrollment.id))
    if case is None:
        return DAY_UNCLASSIFIED, {"classification": "PENDING_POLICY"}
    policies = db.scalars(
        select(AllowancePolicy).where(
            AllowancePolicy.organization_id == case.organization_id,
            AllowancePolicy.funding_program_version_id == case.funding_program_version_id,
            AllowancePolicy.region == case.region,
            AllowancePolicy.department == case.department,
            AllowancePolicy.allowance_type == ALLOWANCE_MEAL,
            AllowancePolicy.policy_status == POLICY_PUBLISHED,
        )
    ).all()
    applicable = [
        policy
        for policy in policies
        if policy.effective_from <= fact_date
        and (policy.effective_to is None or policy.effective_to >= fact_date)
    ]
    if len(applicable) != 1:
        return DAY_UNCLASSIFIED, {"classification": "PENDING_POLICY"}
    policy = applicable[0]
    if policy.half_day_threshold_minutes is None or policy.full_day_threshold_minutes is None:
        return DAY_UNCLASSIFIED, {"classification": "PENDING_POLICY"}
    half, full = policy_thresholds(policy)
    return resolve_day_part(attended_minutes, half, full), {
        "classification": "POLICY",
        "allowance_policy_id": policy.id,
        "half_day_minutes": half,
        "full_day_minutes": full,
    }


def resolve_policy(db, case: FundingCase, allowance_type: str, anchor: date) -> AllowancePolicy:
    """按 区 + 部门 + 补贴类型 + 锚定日期 解析唯一有效的已发布政策版本。

    锚定日期用于支持「跨年度使用不同政策版本」——不同年度的申报
    锚在不同的政策版本上，产生不同的权益记录。
    """
    stmt = (
        select(AllowancePolicy)
        .where(
            AllowancePolicy.organization_id == case.organization_id,
            AllowancePolicy.funding_program_version_id == case.funding_program_version_id,
            AllowancePolicy.region == case.region,
            AllowancePolicy.department == case.department,
            AllowancePolicy.allowance_type == allowance_type,
            AllowancePolicy.policy_status == POLICY_PUBLISHED,
            AllowancePolicy.effective_from <= anchor,
        )
        .where((AllowancePolicy.effective_to.is_(None)) | (AllowancePolicy.effective_to >= anchor))
        .order_by(AllowancePolicy.effective_from.desc())
    )
    policy = db.scalar(stmt)
    if policy is None:
        raise error(
            409,
            "ALLOWANCE_POLICY_NOT_FOUND",
            f"未找到适用于 {anchor.isoformat()} 的已发布补贴政策，请先发布政策版本。",
        )
    return policy


# ---------------------------------------------------------------- 事实层


def rebuild_day_fact(
    db,
    user: User,
    membership: ClassMembership,
    fact_date: date,
    *,
    note: str | None = None,
) -> AttendanceDayFact:
    """把某班级成员某日的**已确认考勤**汇总为一条每日事实。

    同一学员 + 同一报名 + 同一日期只保留一条 ``is_current`` 事实：
    - 已存在 ``DRAFT`` 事实 → 原地更新（版本 +1）
    - 已存在已申报事实 → 新建版本，旧版置 ``SUPERSEDED`` 并回填 ``superseded_by_fact_id``
    """
    rows = db.scalars(
        select(AttendanceRecord)
        .join(ClassSession, ClassSession.id == AttendanceRecord.class_session_id)
        .where(
            AttendanceRecord.class_membership_id == membership.id,
            ClassSession.service_date == fact_date,
            AttendanceRecord.workflow_status.in_(("CONFIRMED", "LOCKED")),
        )
    ).all()
    if not rows:
        raise error(
            409,
            "DAY_FACT_NO_CONFIRMED_ATTENDANCE",
            "该日期没有已确认的考勤，不能形成每日出勤事实。",
        )

    enrollment = db.get(CourseEnrollment, membership.course_enrollment_id)
    planned = sum(r.expected_minutes for r in rows)
    attended = sum(r.actual_attendance_minutes for r in rows)
    late = sum(r.late_minutes for r in rows)
    early = sum(r.early_leave_minutes for r in rows)
    leave = sum(r.expected_minutes for r in rows if r.attendance_status == "LEAVE")
    absent = sum(r.expected_minutes for r in rows if r.attendance_status == "ABSENT")
    session_ids = sorted({r.class_session_id for r in rows})
    day_part, classification_basis = classify_day_fact(db, enrollment, fact_date, attended)

    current = db.scalar(
        select(AttendanceDayFact).where(
            AttendanceDayFact.student_id == enrollment.student_id,
            AttendanceDayFact.course_enrollment_id == enrollment.id,
            AttendanceDayFact.fact_date == fact_date,
            AttendanceDayFact.is_current == True,  # noqa: E712
        )
    )

    if current is not None and current.fact_status == "DRAFT":
        fact = current
        fact.fact_version += 1
        fact.version += 1
    else:
        fact = AttendanceDayFact(
            organization_id=user.organization_id,
            student_id=enrollment.student_id,
            course_enrollment_id=enrollment.id,
            class_cycle_id=membership.class_cycle_id,
            fact_date=fact_date,
            fact_version=(current.fact_version + 1) if current is not None else 1,
            fact_status="DRAFT",
            created_by=user.id,
        )
        db.add(fact)
        db.flush()
        if current is not None:
            current.is_current = False
            current.fact_status = "SUPERSEDED"
            current.superseded_by_fact_id = fact.id

    fact.class_cycle_id = membership.class_cycle_id
    fact.planned_minutes = planned
    fact.attended_minutes = attended
    fact.late_minutes = late
    fact.early_leave_minutes = early
    fact.leave_minutes = leave
    fact.absent_minutes = absent
    fact.day_part = day_part
    fact.source_session_ids_json = json.dumps(session_ids)
    fact.basis_json = json.dumps(
        {
            "attendance_record_ids": sorted(r.id for r in rows),
            **classification_basis,
        },
        ensure_ascii=False,
    )
    fact.note = note
    db.flush()
    return fact


def generate_lodging_nights(db, user: User, stay: LodgingStay) -> list[LodgingNightFact]:
    """住宿单审核通过后，按 入住日 → 退房日（不含）逐夜生成住宿夜事实。"""
    if stay.review_status != "APPROVED":
        raise error(409, "LODGING_STAY_NOT_APPROVED", "住宿单未审核通过，不能生成住宿夜事实。")

    nights: list[date] = []
    cursor = stay.check_in_date
    while cursor < stay.check_out_date:
        nights.append(cursor)
        cursor += timedelta(days=1)
    if not nights:
        raise error(422, "LODGING_STAY_NO_NIGHT", "住宿区间内没有住宿夜。")

    out: list[LodgingNightFact] = []
    for night in nights:
        existing = db.scalar(
            select(LodgingNightFact).where(
                LodgingNightFact.lodging_stay_id == stay.id,
                LodgingNightFact.night_date == night,
            )
        )
        if existing is not None:
            out.append(existing)
            continue
        fact = LodgingNightFact(
            organization_id=user.organization_id,
            lodging_stay_id=stay.id,
            student_id=stay.student_id,
            course_enrollment_id=stay.course_enrollment_id,
            night_date=night,
            location=stay.location,
            is_school_arranged=stay.is_school_arranged,
            review_status="APPROVED",
            created_by=user.id,
        )
        db.add(fact)
        try:
            db.flush()
        except IntegrityError as exc:
            db.rollback()
            raise error(
                409,
                "LODGING_NIGHT_ALREADY_CLAIMED",
                f"{night.isoformat()} 该学员已有审核通过的住宿事实，不能重复主张住宿补贴。",
            ) from exc
        out.append(fact)
    return out


# ---------------------------------------------------------------- 权益计算


def _collect_meal_days(db, case: FundingCase, policy: AllowancePolicy, since: date, until: date):
    facts = db.scalars(
        select(AttendanceDayFact)
        .where(
            AttendanceDayFact.organization_id == case.organization_id,
            AttendanceDayFact.course_enrollment_id == case.course_enrollment_id,
            AttendanceDayFact.fact_date >= since,
            AttendanceDayFact.fact_date <= until,
            AttendanceDayFact.is_current == True,  # noqa: E712
            AttendanceDayFact.fact_status.in_(("CONFIRMED", "LOCKED")),
        )
        .order_by(AttendanceDayFact.fact_date)
    ).all()
    half, full = policy_thresholds(policy)
    full_days = 0
    half_days = 0
    covered: list[str] = []
    for fact in facts:
        part = resolve_day_part(fact.attended_minutes, half, full)
        if part == DAY_FULL:
            full_days += 1
            covered.append(fact.fact_date.isoformat())
        elif part == DAY_HALF:
            half_days += 1
            covered.append(fact.fact_date.isoformat())
    return full_days, half_days, covered


def _collect_lodging_nights(
    db, case: FundingCase, policy: AllowancePolicy, since: date, until: date
):
    nights = db.scalars(
        select(LodgingNightFact)
        .where(
            LodgingNightFact.organization_id == case.organization_id,
            LodgingNightFact.course_enrollment_id == case.course_enrollment_id,
            LodgingNightFact.night_date >= since,
            LodgingNightFact.night_date <= until,
            LodgingNightFact.review_status == "APPROVED",
        )
        .order_by(LodgingNightFact.night_date)
    ).all()
    return [n.night_date.isoformat() for n in nights]


def compute_allowance(
    db,
    user: User,
    case: FundingCase,
    allowance_type: str,
    *,
    anchor: date,
    period_from: date | None = None,
    period_to: date | None = None,
    policy: AllowancePolicy | None = None,
    note: str | None = None,
) -> SubsidyEntitlement:
    """按政策版本计算一项补贴权益。

    只写 ``SubsidyEntitlement``（政策算出）并同步 ``AllowancePayable`` 汇总，
    不在此处产生任何实际支付。
    """
    if allowance_type not in ALLOWANCE_TYPES:
        raise error(422, "ALLOWANCE_TYPE_INVALID", "补贴类型不受支持。")
    if case.case_status not in ("ELIGIBLE", "APPROVED", "ACTIVE"):
        raise error(409, "FUNDING_CASE_NOT_ELIGIBLE", "资格案尚未确认资格，不能计算补贴权益。")

    if policy is None:
        policy = resolve_policy(db, case, allowance_type, anchor)

    since = period_from or policy.effective_from
    until = period_to or policy.effective_to or date(9999, 12, 31)
    if until < since:
        raise error(422, "ALLOWANCE_PERIOD_INVALID", "计算区间的结束日期不能早于开始日期。")

    unit = policy.unit_amount_cent
    unit = min(unit, policy.daily_cap_cent) if policy.daily_cap_cent is not None else unit

    if allowance_type == ALLOWANCE_MEAL:
        full_days, half_days, covered = _collect_meal_days(db, case, policy, since, until)
        if full_days == 0 and half_days == 0:
            raise error(
                409,
                "ALLOWANCE_NO_ATTENDED_DAY",
                "该区间内没有已确认的出勤日，不产生餐补权益。",
            )
        half_amount = half_day_amount(policy) if half_days else 0
        amount = full_days * unit + half_days * half_amount
        covered_days = full_days + half_days
        covered_nights = 0
        day_count, night_count = full_days, half_days
    else:
        covered = _collect_lodging_nights(db, case, policy, since, until)
        if not covered:
            raise error(
                409,
                "ALLOWANCE_NO_LODGING_NIGHT",
                "该区间内没有审核通过的住宿事实，不产生住宿补贴权益。",
            )
        amount = len(covered) * unit
        covered_days = 0
        covered_nights = len(covered)
        day_count, night_count = 0, len(covered)

    amount = apply_rounding(amount, policy.rounding_rule)
    if policy.total_cap_cent is not None:
        amount = min(amount, policy.total_cap_cent)

    current = db.scalar(
        select(SubsidyEntitlement).where(
            SubsidyEntitlement.funding_case_id == case.id,
            SubsidyEntitlement.allowance_type == allowance_type,
            SubsidyEntitlement.allowance_policy_id == policy.id,
            SubsidyEntitlement.is_current == True,  # noqa: E712
        )
    )
    if current is not None and current.entitlement_status in ("CONFIRMED", "SUBMITTED", "CLAIMED"):
        entitlement = SubsidyEntitlement(
            organization_id=user.organization_id,
            funding_case_id=case.id,
            course_enrollment_id=case.course_enrollment_id,
            student_id=case.student_id,
            allowance_type=allowance_type,
            region=case.region,
            department=case.department,
            allowance_policy_id=policy.id,
            entitlement_version=current.entitlement_version + 1,
            computed_amount_cent=amount,
            entitlement_status="DRAFT",
            covered_day_count=covered_days,
            covered_night_count=covered_nights,
            created_by=user.id,
        )
        db.add(entitlement)
        db.flush()
        current.is_current = False
        current.entitlement_status = "SUPERSEDED"
    elif current is not None:
        entitlement = current
        entitlement.entitlement_version += 1
        entitlement.version += 1
        entitlement.computed_amount_cent = amount
        entitlement.covered_day_count = covered_days
        entitlement.covered_night_count = covered_nights
    else:
        entitlement = SubsidyEntitlement(
            organization_id=user.organization_id,
            funding_case_id=case.id,
            course_enrollment_id=case.course_enrollment_id,
            student_id=case.student_id,
            allowance_type=allowance_type,
            region=case.region,
            department=case.department,
            allowance_policy_id=policy.id,
            entitlement_version=1,
            computed_amount_cent=amount,
            entitlement_status="DRAFT",
            covered_day_count=covered_days,
            covered_night_count=covered_nights,
            created_by=user.id,
        )
        db.add(entitlement)
        db.flush()

    entitlement.computed_at = utc_now()
    entitlement.computed_by = user.id
    entitlement.note = note
    entitlement.basis_json = json.dumps(
        {
            "policy_id": policy.id,
            "policy_version_no": policy.version_no,
            "basis_rule": policy.basis_rule,
            "unit_amount_cent": policy.unit_amount_cent,
            "period": [since.isoformat(), until.isoformat()],
            "covered": covered,
            "full_day_count": day_count,
            "half_day_count": night_count,
        },
        ensure_ascii=False,
    )
    db.flush()
    sync_payable(db, user, case, allowance_type)
    return entitlement


def sync_payable(db, user: User, case: FundingCase, allowance_type: str) -> AllowancePayable:
    """把某项补贴的**全部当前有效权益**合计同步到学校应付。

    跨年度会有多个政策版本权益并存，应付是它们的合计。
    """
    entitlements = db.scalars(
        select(SubsidyEntitlement).where(
            SubsidyEntitlement.funding_case_id == case.id,
            SubsidyEntitlement.allowance_type == allowance_type,
            SubsidyEntitlement.is_current == True,  # noqa: E712
        )
    ).all()
    total = sum(e.computed_amount_cent + e.adjusted_amount_cent for e in entitlements)

    payable = db.scalar(
        select(AllowancePayable).where(
            AllowancePayable.funding_case_id == case.id,
            AllowancePayable.allowance_type == allowance_type,
        )
    )
    if payable is None:
        payable = AllowancePayable(
            organization_id=user.organization_id,
            funding_case_id=case.id,
            student_id=case.student_id,
            allowance_type=allowance_type,
            payable_amount_cent=total,
            paid_amount_cent=0,
            payable_status="OPEN" if total > 0 else "CLOSED",
            created_by=user.id,
        )
        db.add(payable)
    else:
        payable.payable_amount_cent = total
        payable.version += 1
        if payable.paid_amount_cent >= total:
            payable.payable_status = "SETTLED" if total else "CLOSED"
        elif payable.paid_amount_cent > 0:
            payable.payable_status = "PARTIALLY_PAID"
        else:
            payable.payable_status = "OPEN"
    db.flush()
    return payable


# ---------------------------------------------------------------- 请求模型


class DayFactInput(BaseModel):
    class_membership_id: str
    fact_date: date
    note: str | None = None


class LodgingStayInput(BaseModel):
    course_enrollment_id: str
    check_in_date: date
    check_out_date: date
    location: str | None = Field(default=None, max_length=200)
    is_school_arranged: bool = False
    evidence_file_object_id: str | None = None
    note: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=100)


class LodgingReviewInput(BaseModel):
    review_status: str = Field(pattern="^(APPROVED|REJECTED)$")
    review_note: str | None = None


class PolicyInput(BaseModel):
    funding_program_version_id: str
    region: str = Field(min_length=1, max_length=60)
    department: str = Field(min_length=1, max_length=80)
    allowance_type: str = Field(pattern="^(MEAL|LODGING)$")
    version_no: str = Field(min_length=1, max_length=30)
    effective_from: date
    effective_to: date | None = None
    basis_rule: str = Field(min_length=1, max_length=30)
    unit_amount_cent: int = Field(ge=0)
    daily_cap_cent: int | None = Field(default=None, ge=0)
    total_cap_cent: int | None = Field(default=None, ge=0)
    half_day_threshold_minutes: int | None = Field(default=None, ge=0)
    full_day_threshold_minutes: int | None = Field(default=None, ge=0)
    rounding_rule: str = Field(default="FLOOR", pattern="^(FLOOR|ROUND_HALF_UP)$")
    policy_document_no: str | None = Field(default=None, max_length=80)
    rule_params_json: str | None = None
    test_sample_json: str | None = None


class ComputeInput(BaseModel):
    allowance_type: str = Field(pattern="^(MEAL|LODGING)$")
    anchor: date
    period_from: date | None = None
    period_to: date | None = None
    policy_id: str | None = None
    note: str | None = None


class VersionInput(BaseModel):
    version: int


class AdjustmentInput(BaseModel):
    amount_delta_cent: int
    reason: str = Field(min_length=1)
    adjustment_type: str = Field(default="MANUAL", max_length=30)
    adjustment_of_id: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=100)


class AllowancePaymentInput(BaseModel):
    amount_cent: int = Field(gt=0)
    payment_method: str = Field(min_length=1, max_length=40)
    paid_on: date | None = None
    note: str | None = None
    idempotency_key: str = Field(min_length=8, max_length=100)


# ---------------------------------------------------------------- 端点：每日事实


@router.post("/attendance-day-facts")
def create_day_fact(payload: DayFactInput, request: Request, db: Db, user: AllowanceManage) -> dict:
    membership = membership_for(db, user, payload.class_membership_id)
    fact = rebuild_day_fact(db, user, membership, payload.fact_date, note=payload.note)
    audit(
        db,
        user,
        request,
        "attendance_day_fact.rebuild",
        "AttendanceDayFact",
        fact.id,
        {"fact_version": fact.fact_version, "day_part": fact.day_part},
    )
    db.commit()
    return brief_fact(fact)


def brief_fact(fact: AttendanceDayFact) -> dict:
    return {
        "id": fact.id,
        "student_id": fact.student_id,
        "course_enrollment_id": fact.course_enrollment_id,
        "fact_date": fact.fact_date.isoformat(),
        "planned_minutes": fact.planned_minutes,
        "attended_minutes": fact.attended_minutes,
        "late_minutes": fact.late_minutes,
        "early_leave_minutes": fact.early_leave_minutes,
        "leave_minutes": fact.leave_minutes,
        "absent_minutes": fact.absent_minutes,
        "day_part": fact.day_part,
        "fact_version": fact.fact_version,
        "fact_status": fact.fact_status,
        "is_current": fact.is_current,
        "version": fact.version,
    }


@router.get("/attendance-day-facts")
def list_day_facts(
    db: Db,
    user: AllowanceRead,
    enrollment_id: str | None = None,
    student_id: str | None = None,
    current_only: bool = True,
) -> list[dict]:
    stmt = select(AttendanceDayFact).where(
        AttendanceDayFact.organization_id == user.organization_id
    )
    if enrollment_id:
        stmt = stmt.where(AttendanceDayFact.course_enrollment_id == enrollment_id)
    if student_id:
        stmt = stmt.where(AttendanceDayFact.student_id == student_id)
    if current_only:
        stmt = stmt.where(AttendanceDayFact.is_current == True)  # noqa: E712
    rows = db.scalars(stmt.order_by(AttendanceDayFact.fact_date)).all()
    return [brief_fact(f) for f in rows]


@router.post("/attendance-day-facts/{item_id}/confirm")
def confirm_day_fact(item_id: str, request: Request, db: Db, user: AllowanceManage) -> dict:
    fact = scoped(db, AttendanceDayFact, item_id, user, "DAY_FACT_NOT_FOUND", "每日出勤事实")
    if fact.fact_status == "CONFIRMED":
        raise error(409, "DAY_FACT_ALREADY_CONFIRMED", "该每日出勤事实已确认。")
    if fact.fact_status == "SUPERSEDED":
        raise error(409, "DAY_FACT_SUPERSEDED", "该事实已被新版本取代，不能确认。")
    fact.fact_status = "CONFIRMED"
    fact.confirmed_at = utc_now()
    fact.confirmed_by = user.id
    fact.version += 1
    audit(db, user, request, "attendance_day_fact.confirm", "AttendanceDayFact", fact.id)
    db.commit()
    return brief_fact(fact)


# ---------------------------------------------------------------- 端点：住宿事实


@router.post("/lodging-stays")
def create_lodging_stay(
    payload: LodgingStayInput, request: Request, db: Db, user: AllowanceManage
) -> dict:
    enrollment = scoped(
        db, CourseEnrollment, payload.course_enrollment_id, user, "ENROLLMENT_NOT_FOUND", "报名"
    )
    if payload.check_out_date < payload.check_in_date:
        raise error(422, "LODGING_DATE_ORDER_INVALID", "退房日期不能早于入住日期。")

    existing = db.scalar(
        select(LodgingStay).where(
            LodgingStay.organization_id == user.organization_id,
            LodgingStay.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return brief_stay(existing)

    stay = LodgingStay(
        organization_id=user.organization_id,
        student_id=enrollment.student_id,
        course_enrollment_id=enrollment.id,
        check_in_date=payload.check_in_date,
        check_out_date=payload.check_out_date,
        location=payload.location,
        is_school_arranged=payload.is_school_arranged,
        review_status="PENDING",
        evidence_file_object_id=payload.evidence_file_object_id,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
        created_by=user.id,
    )
    db.add(stay)
    db.flush()
    audit(db, user, request, "lodging_stay.create", "LodgingStay", stay.id)
    db.commit()
    return brief_stay(stay)


def brief_stay(stay: LodgingStay) -> dict:
    return {
        "id": stay.id,
        "student_id": stay.student_id,
        "course_enrollment_id": stay.course_enrollment_id,
        "check_in_date": stay.check_in_date.isoformat(),
        "check_out_date": stay.check_out_date.isoformat(),
        "location": stay.location,
        "is_school_arranged": stay.is_school_arranged,
        "review_status": stay.review_status,
        "version": stay.version,
    }


@router.post("/lodging-stays/{item_id}/review")
def review_lodging_stay(
    item_id: str, payload: LodgingReviewInput, request: Request, db: Db, user: AllowanceManage
) -> dict:
    stay = scoped(db, LodgingStay, item_id, user, "LODGING_STAY_NOT_FOUND", "住宿单")
    if stay.review_status == "APPROVED":
        raise error(409, "LODGING_STAY_ALREADY_REVIEWED", "该住宿单已审核通过。")

    stay.review_status = payload.review_status
    stay.review_note = payload.review_note
    stay.reviewed_at = utc_now()
    stay.reviewed_by = user.id
    stay.version += 1

    nights: list[dict] = []
    if payload.review_status == "APPROVED":
        nights = [brief_night(n) for n in generate_lodging_nights(db, user, stay)]
    audit(
        db,
        user,
        request,
        "lodging_stay.review",
        "LodgingStay",
        stay.id,
        {"review_status": payload.review_status, "night_count": len(nights)},
    )
    db.commit()
    return {"stay": brief_stay(stay), "nights": nights}


def brief_night(night: LodgingNightFact) -> dict:
    return {
        "id": night.id,
        "student_id": night.student_id,
        "course_enrollment_id": night.course_enrollment_id,
        "night_date": night.night_date.isoformat(),
        "location": night.location,
        "review_status": night.review_status,
    }


@router.get("/lodging-night-facts")
def list_lodging_nights(
    db: Db, user: AllowanceRead, enrollment_id: str | None = None
) -> list[dict]:
    stmt = select(LodgingNightFact).where(LodgingNightFact.organization_id == user.organization_id)
    if enrollment_id:
        stmt = stmt.where(LodgingNightFact.course_enrollment_id == enrollment_id)
    rows = db.scalars(stmt.order_by(LodgingNightFact.night_date)).all()
    return [brief_night(n) for n in rows]


# ---------------------------------------------------------------- 端点：政策


def brief_policy(policy: AllowancePolicy) -> dict:
    return {
        "id": policy.id,
        "region": policy.region,
        "department": policy.department,
        "allowance_type": policy.allowance_type,
        "version_no": policy.version_no,
        "basis_rule": policy.basis_rule,
        "unit_amount_cent": policy.unit_amount_cent,
        "daily_cap_cent": policy.daily_cap_cent,
        "total_cap_cent": policy.total_cap_cent,
        "half_day_threshold_minutes": policy.half_day_threshold_minutes,
        "full_day_threshold_minutes": policy.full_day_threshold_minutes,
        "rounding_rule": policy.rounding_rule,
        "effective_from": policy.effective_from.isoformat(),
        "effective_to": policy.effective_to.isoformat() if policy.effective_to else None,
        "policy_status": policy.policy_status,
        "version": policy.version,
    }


@router.post("/allowance-policies")
def create_allowance_policy(
    payload: PolicyInput, request: Request, db: Db, user: PolicyPublish
) -> dict:
    if payload.basis_rule not in SUPPORTED_RULES:
        raise error(
            422,
            "ALLOWANCE_POLICY_RULE_UNSUPPORTED",
            "政策基准规则不受支持，只允许预定义策略。",
        )
    validate_policy_rule(payload.basis_rule, payload.allowance_type)
    if payload.effective_to is not None and payload.effective_to < payload.effective_from:
        raise error(422, "ALLOWANCE_POLICY_PERIOD_INVALID", "政策失效日期不能早于生效日期。")

    version = scoped(
        db,
        FundingProgramVersion,
        payload.funding_program_version_id,
        user,
        "PROGRAM_VERSION_NOT_FOUND",
        "项目版本",
    )
    existing = db.scalar(
        select(AllowancePolicy).where(
            AllowancePolicy.organization_id == user.organization_id,
            AllowancePolicy.region == payload.region,
            AllowancePolicy.department == payload.department,
            AllowancePolicy.funding_program_version_id == version.id,
            AllowancePolicy.allowance_type == payload.allowance_type,
            AllowancePolicy.version_no == payload.version_no,
        )
    )
    if existing is not None:
        raise error(409, "ALLOWANCE_POLICY_DUPLICATE", "同维度同版本号的政策已存在。")

    policy = AllowancePolicy(
        organization_id=user.organization_id,
        region=payload.region,
        department=payload.department,
        funding_program_version_id=version.id,
        allowance_type=payload.allowance_type,
        version_no=payload.version_no,
        policy_document_no=payload.policy_document_no,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        basis_rule=payload.basis_rule,
        unit_amount_cent=payload.unit_amount_cent,
        daily_cap_cent=payload.daily_cap_cent,
        total_cap_cent=payload.total_cap_cent,
        half_day_threshold_minutes=payload.half_day_threshold_minutes,
        full_day_threshold_minutes=payload.full_day_threshold_minutes,
        rounding_rule=payload.rounding_rule,
        rule_params_json=payload.rule_params_json,
        test_sample_json=payload.test_sample_json,
        policy_status=POLICY_DRAFT,
        created_by=user.id,
    )
    db.add(policy)
    db.flush()
    audit(db, user, request, "allowance_policy.create", "AllowancePolicy", policy.id)
    db.commit()
    return brief_policy(policy)


@router.post("/allowance-policies/{item_id}/publish")
def publish_allowance_policy(
    item_id: str, payload: VersionInput, request: Request, db: Db, user: PolicyPublish
) -> dict:
    policy = scoped(db, AllowancePolicy, item_id, user, "ALLOWANCE_POLICY_NOT_FOUND", "补贴政策")
    checked(policy, payload.version)
    if policy.policy_status == POLICY_PUBLISHED:
        raise error(409, "ALLOWANCE_POLICY_ALREADY_PUBLISHED", "该政策版本已发布。")
    if not policy.test_sample_json:
        raise error(
            409,
            "ALLOWANCE_POLICY_SAMPLE_REQUIRED",
            "发布政策前必须提供测试样例（设计 P6 第六节）。",
        )
    validate_policy_configuration(
        policy.allowance_type,
        policy.half_day_threshold_minutes,
        policy.full_day_threshold_minutes,
    )
    policy.policy_status = POLICY_PUBLISHED
    policy.published_at = utc_now()
    policy.published_by = user.id
    policy.version += 1
    audit(db, user, request, "allowance_policy.publish", "AllowancePolicy", policy.id)
    db.commit()
    return brief_policy(policy)


@router.get("/allowance-policies")
def list_allowance_policies(
    db: Db,
    user: AllowanceRead,
    region: str | None = None,
    department: str | None = None,
    allowance_type: str | None = None,
) -> list[dict]:
    stmt = select(AllowancePolicy).where(AllowancePolicy.organization_id == user.organization_id)
    if region:
        stmt = stmt.where(AllowancePolicy.region == region)
    if department:
        stmt = stmt.where(AllowancePolicy.department == department)
    if allowance_type:
        stmt = stmt.where(AllowancePolicy.allowance_type == allowance_type)
    rows = db.scalars(stmt.order_by(AllowancePolicy.effective_from)).all()
    return [brief_policy(p) for p in rows]


# ---------------------------------------------------------------- 端点：权益与支付


def brief_entitlement(ent: SubsidyEntitlement) -> dict:
    return {
        "id": ent.id,
        "allowance_type": ent.allowance_type,
        "region": ent.region,
        "department": ent.department,
        "allowance_policy_id": ent.allowance_policy_id,
        "entitlement_version": ent.entitlement_version,
        "computed_amount_cent": ent.computed_amount_cent,
        "adjusted_amount_cent": ent.adjusted_amount_cent,
        "total_amount_cent": ent.computed_amount_cent + ent.adjusted_amount_cent,
        "covered_day_count": ent.covered_day_count,
        "covered_night_count": ent.covered_night_count,
        "entitlement_status": ent.entitlement_status,
        "is_current": ent.is_current,
        "version": ent.version,
    }


def brief_payable(payable: AllowancePayable) -> dict:
    return {
        "id": payable.id,
        "allowance_type": payable.allowance_type,
        "student_id": payable.student_id,
        "payable_amount_cent": payable.payable_amount_cent,
        "paid_amount_cent": payable.paid_amount_cent,
        "outstanding_amount_cent": payable.payable_amount_cent - payable.paid_amount_cent,
        "payable_status": payable.payable_status,
        "version": payable.version,
    }


@router.post("/funding-cases/{item_id}/allowances")
def compute_case_allowance(
    item_id: str, payload: ComputeInput, request: Request, db: Db, user: AllowanceManage
) -> dict:
    case = scoped(db, FundingCase, item_id, user, "FUNDING_CASE_NOT_FOUND", "政府项目资格案")
    policy = None
    if payload.policy_id:
        policy = scoped(
            db, AllowancePolicy, payload.policy_id, user, "ALLOWANCE_POLICY_NOT_FOUND", "补贴政策"
        )
    entitlement = compute_allowance(
        db,
        user,
        case,
        payload.allowance_type,
        anchor=payload.anchor,
        period_from=payload.period_from,
        period_to=payload.period_to,
        policy=policy,
        note=payload.note,
    )
    audit(
        db,
        user,
        request,
        "subsidy_entitlement.compute",
        "SubsidyEntitlement",
        entitlement.id,
        {"allowance_type": payload.allowance_type, "amount_cent": entitlement.computed_amount_cent},
    )
    db.commit()
    return brief_entitlement(entitlement)


@router.get("/funding-cases/{item_id}/allowances")
def list_case_allowances(item_id: str, db: Db, user: AllowanceRead) -> dict:
    """一次返回：政策计算权益（全部版本）+ 学校应付 + 已支付合计。

    三者分列，不合并成一个金额——设计 P6 第七节的硬要求。
    """
    case = scoped(db, FundingCase, item_id, user, "FUNDING_CASE_NOT_FOUND", "政府项目资格案")
    entitlements = db.scalars(
        select(SubsidyEntitlement)
        .where(SubsidyEntitlement.funding_case_id == case.id)
        .order_by(SubsidyEntitlement.allowance_type, SubsidyEntitlement.entitlement_version)
    ).all()
    payables = db.scalars(
        select(AllowancePayable).where(AllowancePayable.funding_case_id == case.id)
    ).all()
    return {
        "funding_case_id": case.id,
        "student_id": case.student_id,
        "region": case.region,
        "department": case.department,
        "entitlements": [brief_entitlement(e) for e in entitlements],
        "payables": [brief_payable(p) for p in payables],
        "entitlement_total_cent": sum(
            e.computed_amount_cent + e.adjusted_amount_cent for e in entitlements if e.is_current
        ),
        "payable_total_cent": sum(p.payable_amount_cent for p in payables),
        "paid_total_cent": sum(p.paid_amount_cent for p in payables),
    }


@router.post("/subsidy-entitlements/{item_id}/adjustments")
def create_entitlement_adjustment(
    item_id: str, payload: AdjustmentInput, request: Request, db: Db, user: AllowanceManage
) -> dict:
    entitlement = scoped(
        db, SubsidyEntitlement, item_id, user, "SUBSIDY_ENTITLEMENT_NOT_FOUND", "补贴权益"
    )
    if payload.amount_delta_cent == 0:
        raise error(422, "ENTITLEMENT_ADJUSTMENT_ZERO", "调整金额不能为 0。")

    existing = db.scalar(
        select(EntitlementAdjustment).where(
            EntitlementAdjustment.organization_id == user.organization_id,
            EntitlementAdjustment.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return brief_adjustment(existing)

    parent = None
    if payload.adjustment_of_id:
        parent = scoped(
            db,
            EntitlementAdjustment,
            payload.adjustment_of_id,
            user,
            "ENTITLEMENT_ADJUSTMENT_NOT_FOUND",
            "权益调整",
        )
        if parent.amount_delta_cent + payload.amount_delta_cent != 0:
            raise error(
                422, "ENTITLEMENT_ADJUSTMENT_REVERSAL_MISMATCH", "冲正金额必须与原调整完全相反。"
            )

    adjustment = EntitlementAdjustment(
        organization_id=user.organization_id,
        subsidy_entitlement_id=entitlement.id,
        adjustment_type=payload.adjustment_type,
        amount_delta_cent=payload.amount_delta_cent,
        reason=payload.reason,
        adjustment_of_id=parent.id if parent else None,
        idempotency_key=payload.idempotency_key,
        created_by=user.id,
    )
    db.add(adjustment)
    db.flush()
    entitlement.adjusted_amount_cent += payload.amount_delta_cent
    entitlement.version += 1
    case = db.get(FundingCase, entitlement.funding_case_id)
    sync_payable(db, user, case, entitlement.allowance_type)
    audit(
        db,
        user,
        request,
        "entitlement_adjustment.create",
        "EntitlementAdjustment",
        adjustment.id,
        {"amount_delta_cent": payload.amount_delta_cent},
    )
    db.commit()
    return brief_adjustment(adjustment)


def brief_adjustment(adj: EntitlementAdjustment) -> dict:
    return {
        "id": adj.id,
        "subsidy_entitlement_id": adj.subsidy_entitlement_id,
        "adjustment_type": adj.adjustment_type,
        "amount_delta_cent": adj.amount_delta_cent,
        "reason": adj.reason,
        "adjustment_of_id": adj.adjustment_of_id,
    }


@router.get("/allowance-payables")
def list_payables(db: Db, user: AllowanceRead, status: str | None = None) -> list[dict]:
    stmt = select(AllowancePayable).where(AllowancePayable.organization_id == user.organization_id)
    if status:
        stmt = stmt.where(AllowancePayable.payable_status == status)
    rows = db.scalars(stmt.order_by(AllowancePayable.created_at)).all()
    return [brief_payable(p) for p in rows]


@router.post("/allowance-payables/{item_id}/payments")
def create_allowance_payment(
    item_id: str, payload: AllowancePaymentInput, request: Request, db: Db, user: AllowancePay
) -> dict:
    payable = scoped(db, AllowancePayable, item_id, user, "ALLOWANCE_PAYABLE_NOT_FOUND", "补贴应付")

    existing = db.scalar(
        select(AllowancePayment).where(
            AllowancePayment.organization_id == user.organization_id,
            AllowancePayment.idempotency_key == payload.idempotency_key,
        )
    )
    if existing is not None:
        return brief_allowance_payment(existing)

    outstanding = payable.payable_amount_cent - payable.paid_amount_cent
    if payload.amount_cent > outstanding:
        raise error(
            409,
            "ALLOWANCE_PAYMENT_EXCEEDS_OUTSTANDING",
            f"支付金额超过应付余额（剩余 {outstanding} 分）。",
        )

    payment = AllowancePayment(
        organization_id=user.organization_id,
        allowance_payable_id=payable.id,
        amount_cent=payload.amount_cent,
        payment_method=payload.payment_method,
        payment_status="SUCCEEDED",
        paid_on=payload.paid_on,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
        created_by=user.id,
    )
    db.add(payment)
    db.flush()
    payable.paid_amount_cent += payload.amount_cent
    payable.version += 1
    if payable.paid_amount_cent >= payable.payable_amount_cent:
        payable.payable_status = "SETTLED"
    elif payable.paid_amount_cent > 0:
        payable.payable_status = "PARTIALLY_PAID"
    audit(
        db,
        user,
        request,
        "allowance_payment.create",
        "AllowancePayment",
        payment.id,
        {"amount_cent": payload.amount_cent},
    )
    db.commit()
    return brief_allowance_payment(payment)


def brief_allowance_payment(payment: AllowancePayment) -> dict:
    return {
        "id": payment.id,
        "allowance_payable_id": payment.allowance_payable_id,
        "amount_cent": payment.amount_cent,
        "payment_method": payment.payment_method,
        "payment_status": payment.payment_status,
        "paid_on": payment.paid_on.isoformat() if payment.paid_on else None,
    }


# ---------------------------------------------------------------- 学生视角汇总


@router.get("/students/{student_id}/allowance-summary")
def student_allowance_summary(student_id: str, db: Db, user: AllowanceRead) -> dict:
    """学员 360 退役士兵页签用：按报名聚合权益、应付与实付。"""
    student = scoped(db, Student, student_id, user, "STUDENT_NOT_FOUND", "学员")
    cases = db.scalars(
        select(FundingCase).where(
            FundingCase.organization_id == user.organization_id,
            FundingCase.student_id == student.id,
        )
    ).all()
    items = []
    for case in cases:
        payables = db.scalars(
            select(AllowancePayable).where(AllowancePayable.funding_case_id == case.id)
        ).all()
        items.append(
            {
                "funding_case_id": case.id,
                "course_enrollment_id": case.course_enrollment_id,
                "region": case.region,
                "department": case.department,
                "case_status": case.case_status,
                "payables": [brief_payable(p) for p in payables],
            }
        )
    return {
        "student_id": student.id,
        "cases": items,
        "payable_total_cent": sum(
            p["payable_amount_cent"] for item in items for p in item["payables"]
        ),
        "paid_total_cent": sum(p["paid_amount_cent"] for item in items for p in item["payables"]),
    }
