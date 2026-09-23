# ruff: noqa: B008, E501, E701, E702, I001
# fmt: off
import hashlib
import json
import uuid
from datetime import date, datetime
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import (
    AgencyDisbursement,
    AgencyDisbursementAllocation,
    AgencyPayable,
    AttendanceRecord,
    AuditLog,
    ClassCycle,
    ClassMembership,
    ClassSession,
    CourseEnrollment,
    CurriculumVersion,
    ExamFeeAssessment,
    FeePolicyVersion,
    Payment,
    PaymentAllocation,
    Receivable,
    ReceivableAdjustment,
    RefundAttendanceSnapshotLine,
    RefundCalculationSnapshot,
    RefundPayment,
    RefundAllocation,
    RefundPolicyVersion,
    RefundRequest,
    SessionTeacherAssignment,
    Student,
    TeacherPayment,
    TeacherPaymentAllocation,
    TeacherProfile,
    TeacherSettlementBatch,
    TeacherSettlementLine,
    User,
    utc_now,
)
from app.core.pii import encrypt
from app.modules.iam.router import Db, require_permission

router = APIRouter(prefix="/api", tags=["finance"])

ReceivableRead = Annotated[User, Depends(require_permission("receivable.read"))]
ReceivableManage = Annotated[User, Depends(require_permission("receivable.manage"))]
ReceivableAdjust = Annotated[User, Depends(require_permission("receivable.adjust"))]
PaymentRead = Annotated[User, Depends(require_permission("payment.read"))]
PaymentCreate = Annotated[User, Depends(require_permission("payment.create"))]
PaymentConfirm = Annotated[User, Depends(require_permission("payment.confirm"))]
PaymentAllocate = Annotated[User, Depends(require_permission("payment.allocate"))]
PaymentReverse = Annotated[User, Depends(require_permission("payment.reverse"))]
AgencyRead = Annotated[User, Depends(require_permission("agency_payable.read"))]
AgencyManage = Annotated[User, Depends(require_permission("agency_payable.manage"))]
AgencyCreate = Annotated[User, Depends(require_permission("agency_disbursement.create"))]
AgencyConfirm = Annotated[User, Depends(require_permission("agency_disbursement.confirm"))]
RefundRead = Annotated[User, Depends(require_permission("refund.read"))]
RefundCalculate = Annotated[User, Depends(require_permission("refund.calculate"))]
RefundSubmit = Annotated[User, Depends(require_permission("refund.submit"))]
RefundApprove = Annotated[User, Depends(require_permission("refund.approve"))]
RefundPay = Annotated[User, Depends(require_permission("refund.pay"))]
RefundReverse = Annotated[User, Depends(require_permission("refund.reverse"))]
SettlementRead = Annotated[User, Depends(require_permission("teacher_settlement.read"))]
SettlementCalculate = Annotated[User, Depends(require_permission("teacher_settlement.calculate"))]
SettlementSubmit = Annotated[User, Depends(require_permission("teacher_settlement.submit"))]
SettlementApprove = Annotated[User, Depends(require_permission("teacher_settlement.approve"))]
TeacherPayCreate = Annotated[User, Depends(require_permission("teacher_payment.create"))]
TeacherPayConfirm = Annotated[User, Depends(require_permission("teacher_payment.confirm"))]


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def code(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12].upper()}"


def audit(db: Session, user: User, request: Request, action: str, kind: str, item_id: str, detail: dict[str, Any] | None = None) -> None:
    db.add(AuditLog(organization_id=user.organization_id, actor_user_id=user.id, action=action, subject_type=kind, subject_id=item_id, correlation_id=request.state.correlation_id, detail_json=json.dumps(detail or {}, ensure_ascii=False)))


def checked(item: Any, version: int) -> None:
    if item.version != version:
        raise error(409, "VERSION_CONFLICT", "记录已被其他操作更新，请刷新后重试。")


def round_ratio(numerator: int, denominator: int, mode: str) -> int:
    if numerator < 0 or denominator <= 0:
        raise ValueError("invalid non-negative ratio")
    quotient, remainder = divmod(numerator, denominator)
    if mode == "FLOOR":
        return quotient
    if mode == "CEILING":
        return quotient + int(remainder > 0)
    if mode == "HALF_UP":
        return quotient + int(remainder * 2 >= denominator)
    raise ValueError("unsupported rounding mode")


def enrollment_for(db: Session, user: User, item_id: str) -> CourseEnrollment:
    item = db.scalar(select(CourseEnrollment).where(CourseEnrollment.id == item_id, CourseEnrollment.organization_id == user.organization_id))
    if not item:
        raise error(404, "ENROLLMENT_NOT_FOUND", "未找到报名。")
    return item


def receivable_for(db: Session, user: User, item_id: str) -> Receivable:
    item = db.scalar(select(Receivable).where(Receivable.id == item_id, Receivable.organization_id == user.organization_id))
    if not item:
        raise error(404, "RECEIVABLE_NOT_FOUND", "未找到应收。")
    return item


def payment_for(db: Session, user: User, item_id: str) -> Payment:
    item = db.scalar(select(Payment).where(Payment.id == item_id, Payment.organization_id == user.organization_id))
    if not item:
        raise error(404, "PAYMENT_NOT_FOUND", "未找到收款。")
    return item


def active_allocated(db: Session, *, payment_id: str | None = None, receivable_id: str | None = None) -> int:
    query = select(func.coalesce(func.sum(PaymentAllocation.allocated_amount_cent), 0)).where(PaymentAllocation.allocation_status == "ACTIVE")
    if payment_id:
        query = query.where(PaymentAllocation.payment_id == payment_id)
    if receivable_id:
        query = query.where(PaymentAllocation.receivable_id == receivable_id)
    return int(db.scalar(query) or 0)


def refunded_for_receivable(db: Session, receivable_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(RefundAllocation.refunded_amount_cent), 0)).where(RefundAllocation.receivable_id == receivable_id, RefundAllocation.allocation_status == "ACTIVE")) or 0)


def recalc_receivable(db: Session, item: Receivable) -> None:
    if item.receivable_status in {"DRAFT", "CANCELLED"}:
        return
    allocated = active_allocated(db, receivable_id=item.id)
    refunded = refunded_for_receivable(db, item.id)
    if refunded >= allocated and allocated > 0:
        item.receivable_status = "REFUNDED"
    elif refunded > 0:
        item.receivable_status = "PARTIALLY_REFUNDED"
    elif allocated >= item.payable_amount_cent:
        item.receivable_status = "PAID"
    elif allocated > 0:
        item.receivable_status = "PARTIALLY_PAID"
    else:
        item.receivable_status = "CONFIRMED"


def recalc_payment(db: Session, item: Payment) -> None:
    if item.payment_status in {"DRAFT", "VOIDED", "REVERSED"}:
        return
    allocated = active_allocated(db, payment_id=item.id)
    item.payment_status = "FULLY_ALLOCATED" if allocated >= item.received_amount_cent else ("PARTIALLY_ALLOCATED" if allocated else "CONFIRMED")


def recalc_enrollment(db: Session, item: CourseEnrollment) -> None:
    rows = db.scalars(select(Receivable).where(Receivable.course_enrollment_id == item.id, Receivable.receivable_status != "CANCELLED")).all()
    if not rows:
        item.financial_status = "UNPAID"
        return
    payable = sum(row.payable_amount_cent for row in rows)
    allocated = sum(active_allocated(db, receivable_id=row.id) for row in rows)
    refunded = sum(refunded_for_receivable(db, row.id) for row in rows)
    item.financial_status = "REFUNDED" if refunded and refunded >= allocated else ("PAID" if allocated >= payable else ("PARTIALLY_PAID" if allocated else "UNPAID"))


def receivable_view(db: Session, item: Receivable) -> dict[str, Any]:
    allocated = active_allocated(db, receivable_id=item.id)
    refunded = refunded_for_receivable(db, item.id)
    return {"id": item.id, "receivable_no": item.receivable_no, "course_enrollment_id": item.course_enrollment_id, "student_id": item.student_id, "receivable_type": item.receivable_type, "economic_nature": item.economic_nature, "source_type": item.source_type, "source_id": item.source_id, "original_amount_cent": item.original_amount_cent, "adjusted_amount_cent": item.adjusted_amount_cent, "payable_amount_cent": item.payable_amount_cent, "allocated_amount_cent": allocated, "refunded_amount_cent": refunded, "outstanding_amount_cent": max(0, item.payable_amount_cent - allocated), "receivable_status": item.receivable_status, "version": item.version}


def payment_view(db: Session, item: Payment) -> dict[str, Any]:
    allocated = active_allocated(db, payment_id=item.id)
    return {"id": item.id, "payment_no": item.payment_no, "student_id": item.student_id, "payer_name": item.payer_name, "received_amount_cent": item.received_amount_cent, "allocated_amount_cent": allocated, "unallocated_amount_cent": max(0, item.received_amount_cent - allocated), "payment_method": item.payment_method, "received_at": item.received_at, "external_transaction_no_last4": item.external_transaction_no_last4, "internal_receipt_no": item.internal_receipt_no, "payment_status": item.payment_status, "version": item.version}


class VersionInput(BaseModel):
    version: int


class ReasonInput(VersionInput):
    reason: str = Field(min_length=1, max_length=500)


class TuitionInput(BaseModel):
    due_at: datetime | None = None


class AdjustmentInput(VersionInput):
    adjustment_type: Literal["INCREASE", "DECREASE"]
    amount_cent: int = Field(gt=0)
    reason: str = Field(min_length=1, max_length=500)


class PaymentInput(BaseModel):
    student_id: str
    received_amount_cent: int = Field(gt=0)
    payment_method: Literal["CASH", "BANK_TRANSFER", "WECHAT_OFFLINE_CONFIRMED", "ALIPAY_OFFLINE_CONFIRMED", "OTHER"]
    received_at: datetime
    idempotency_key: str = Field(min_length=4, max_length=100)
    payer_name: str | None = None
    external_transaction_no: str | None = None
    internal_receipt_no: str | None = None
    remarks: str | None = None


class AllocationInput(VersionInput):
    receivable_id: str
    allocated_amount_cent: int = Field(gt=0)
    idempotency_key: str = Field(min_length=4, max_length=100)
    remarks: str | None = None


@router.get("/receivables")
def list_receivables(db: Db, user: ReceivableRead, student_id: str | None = None, enrollment_id: str | None = None, limit: int = Query(50, ge=1, le=200)) -> dict:
    query = select(Receivable).where(Receivable.organization_id == user.organization_id).order_by(Receivable.created_at.desc()).limit(limit)
    if student_id: query = query.where(Receivable.student_id == student_id)
    if enrollment_id: query = query.where(Receivable.course_enrollment_id == enrollment_id)
    rows = db.scalars(query).all()
    return {"items": [receivable_view(db, row) for row in rows], "calculated_at": utc_now()}


@router.get("/receivables/{item_id}")
def get_receivable(item_id: str, db: Db, user: ReceivableRead) -> dict:
    return receivable_view(db, receivable_for(db, user, item_id))


@router.post("/enrollments/{enrollment_id}/tuition-receivable")
def create_tuition(enrollment_id: str, payload: TuitionInput, request: Request, db: Db, user: ReceivableManage) -> dict:
    enrollment = enrollment_for(db, user, enrollment_id)
    existing = db.scalar(select(Receivable).where(Receivable.source_type == "ENROLLMENT_FEE_POLICY", Receivable.source_id == enrollment.id))
    if existing: return receivable_view(db, existing)
    policy = enrollment.fee_policy_version_id and db.get(FeePolicyVersion, enrollment.fee_policy_version_id)
    if not policy: raise error(409, "FEE_POLICY_MISSING", "报名未绑定有效费用政策。")
    item = Receivable(organization_id=user.organization_id, receivable_no=code("AR"), course_enrollment_id=enrollment.id, student_id=enrollment.student_id, receivable_type="TUITION", economic_nature="SCHOOL_REVENUE", source_type="ENROLLMENT_FEE_POLICY", source_id=enrollment.id, fee_policy_version_id=policy.id, original_amount_cent=policy.tuition_amount_cent, adjusted_amount_cent=0, payable_amount_cent=policy.tuition_amount_cent, due_at=payload.due_at, receivable_status="DRAFT", description=f"培训费（政策 {policy.version_no}）", created_by=user.id)
    db.add(item); db.flush(); audit(db, user, request, "receivable.create", "receivable", item.id, {"amount_cent": item.original_amount_cent}); db.commit(); db.refresh(item)
    return receivable_view(db, item)


@router.post("/exam-fee-assessments/handoff-preview")
def preview_exam_handoff(db: Db, user: ReceivableRead) -> dict:
    rows = db.scalars(select(ExamFeeAssessment).join(CourseEnrollment).where(CourseEnrollment.organization_id == user.organization_id, ExamFeeAssessment.assessment_status == "CONFIRMED", ExamFeeAssessment.responsibility == "STUDENT", ExamFeeAssessment.finance_reference.is_(None))).all()
    return {"items": [{"id": row.id, "assessment_no": row.assessment_no, "fee_type": row.fee_type, "amount_cent": row.amount_cent} for row in rows]}


class HandoffInput(BaseModel):
    assessment_ids: list[str] = Field(min_length=1)


@router.post("/exam-fee-assessments/handoff-confirm")
def confirm_exam_handoff(payload: HandoffInput, request: Request, db: Db, user: ReceivableManage) -> dict:
    results = []
    for item_id in payload.assessment_ids:
        assessment = db.get(ExamFeeAssessment, item_id)
        enrollment = assessment and db.get(CourseEnrollment, assessment.course_enrollment_id)
        if not assessment or not enrollment or enrollment.organization_id != user.organization_id:
            results.append({"id": item_id, "status": "FAILED", "code": "ASSESSMENT_NOT_FOUND"}); continue
        existing = db.scalar(select(Receivable).where(Receivable.source_type == "EXAM_FEE_ASSESSMENT", Receivable.source_id == assessment.id))
        if existing:
            results.append({"id": item_id, "status": "SKIPPED", "receivable_id": existing.id}); continue
        if assessment.assessment_status != "CONFIRMED" or assessment.responsibility != "STUDENT":
            results.append({"id": item_id, "status": "FAILED", "code": "ASSESSMENT_NOT_ELIGIBLE"}); continue
        item = Receivable(organization_id=user.organization_id, receivable_no=code("AR"), course_enrollment_id=enrollment.id, student_id=enrollment.student_id, receivable_type="INITIAL_EXAM_FEE" if assessment.fee_type == "INITIAL" else "RESIT_FEE", economic_nature="AGENCY_COLLECTION", source_type="EXAM_FEE_ASSESSMENT", source_id=assessment.id, fee_policy_version_id=assessment.fee_policy_version_id, original_amount_cent=assessment.amount_cent, adjusted_amount_cent=0, payable_amount_cent=assessment.amount_cent, receivable_status="CONFIRMED", confirmed_at=utc_now(), confirmed_by=user.id, description=f"考试费用认定 {assessment.assessment_no}", created_by=user.id)
        db.add(item); db.flush(); assessment.assessment_status = "HANDED_OFF_TO_FINANCE"; assessment.finance_reference = item.receivable_no; audit(db, user, request, "exam_fee.handoff", "exam_fee_assessment", assessment.id, {"receivable_id": item.id, "amount_cent": item.original_amount_cent}); results.append({"id": item_id, "status": "SUCCESS", "receivable_id": item.id})
    try: db.commit()
    except IntegrityError as exc: db.rollback(); raise error(409, "HANDOFF_CONFLICT", "费用认定已交接。") from exc
    return {"items": results}


@router.post("/receivables/{item_id}/confirm")
def confirm_receivable(item_id: str, payload: VersionInput, request: Request, db: Db, user: ReceivableManage) -> dict:
    item = receivable_for(db, user, item_id); checked(item, payload.version)
    if item.receivable_status != "DRAFT": raise error(409, "INVALID_RECEIVABLE_STATUS", "仅草稿应收可确认。")
    item.receivable_status = "CONFIRMED"; item.confirmed_at = utc_now(); item.confirmed_by = user.id; item.version += 1; audit(db, user, request, "receivable.confirm", "receivable", item.id); db.commit(); db.refresh(item); return receivable_view(db, item)


@router.post("/receivables/{item_id}/adjust")
def adjust_receivable(item_id: str, payload: AdjustmentInput, request: Request, db: Db, user: ReceivableAdjust) -> dict:
    item = receivable_for(db, user, item_id); checked(item, payload.version)
    if item.receivable_status in {"DRAFT", "CANCELLED"}: raise error(409, "INVALID_RECEIVABLE_STATUS", "当前应收不可调整。")
    delta = payload.amount_cent if payload.adjustment_type == "INCREASE" else -payload.amount_cent
    if item.payable_amount_cent + delta < active_allocated(db, receivable_id=item.id): raise error(409, "ADJUSTMENT_BELOW_ALLOCATED", "调整后应付金额不能低于已分配金额。")
    db.add(ReceivableAdjustment(receivable_id=item.id, adjustment_type=payload.adjustment_type, amount_cent=payload.amount_cent, reason=payload.reason, approval_status="APPROVED", approved_at=utc_now(), approved_by=user.id, created_by=user.id)); item.adjusted_amount_cent += delta; item.payable_amount_cent += delta; item.version += 1; recalc_receivable(db, item); audit(db, user, request, "receivable.adjust", "receivable", item.id, {"delta_cent": delta, "reason": payload.reason}); db.commit(); db.refresh(item); return receivable_view(db, item)


@router.post("/receivables/{item_id}/cancel")
def cancel_receivable(item_id: str, payload: ReasonInput, request: Request, db: Db, user: ReceivableManage) -> dict:
    item = receivable_for(db, user, item_id); checked(item, payload.version)
    if active_allocated(db, receivable_id=item.id): raise error(409, "RECEIVABLE_HAS_ALLOCATIONS", "已有收款分配的应收不能取消。")
    item.receivable_status = "CANCELLED"; item.cancellation_reason = payload.reason; item.version += 1; audit(db, user, request, "receivable.cancel", "receivable", item.id, {"reason": payload.reason}); db.commit(); db.refresh(item); return receivable_view(db, item)


@router.get("/payments")
def list_payments(db: Db, user: PaymentRead, student_id: str | None = None, limit: int = Query(50, ge=1, le=200)) -> dict:
    query = select(Payment).where(Payment.organization_id == user.organization_id).order_by(Payment.created_at.desc()).limit(limit)
    if student_id: query = query.where(Payment.student_id == student_id)
    return {"items": [payment_view(db, row) for row in db.scalars(query).all()], "calculated_at": utc_now()}


@router.get("/payments/{item_id}")
def get_payment(item_id: str, db: Db, user: PaymentRead) -> dict:
    item = payment_for(db, user, item_id)
    allocations = db.scalars(select(PaymentAllocation).where(PaymentAllocation.payment_id == item.id)).all()
    result = payment_view(db, item); result["allocations"] = [{"id": row.id, "receivable_id": row.receivable_id, "allocated_amount_cent": row.allocated_amount_cent, "allocation_status": row.allocation_status, "version": row.version} for row in allocations]; return result


@router.post("/payments")
def create_payment(payload: PaymentInput, request: Request, db: Db, user: PaymentCreate) -> dict:
    existing = db.scalar(select(Payment).where(Payment.idempotency_key == payload.idempotency_key))
    if existing:
        if existing.organization_id != user.organization_id: raise error(409, "IDEMPOTENCY_CONFLICT", "幂等键冲突。")
        return payment_view(db, existing)
    student = db.scalar(select(Student).where(Student.id == payload.student_id, Student.organization_id == user.organization_id))
    if not student: raise error(404, "STUDENT_NOT_FOUND", "未找到学员。")
    external = payload.external_transaction_no.strip() if payload.external_transaction_no else None
    item = Payment(organization_id=user.organization_id, payment_no=code("PM"), student_id=student.id, payer_name=payload.payer_name, received_amount_cent=payload.received_amount_cent, payment_method=payload.payment_method, received_at=payload.received_at, external_transaction_no_ciphertext=encrypt(external) if external else None, external_transaction_no_last4=external[-4:] if external else None, internal_receipt_no=payload.internal_receipt_no, payment_status="DRAFT", idempotency_key=payload.idempotency_key, remarks=payload.remarks, created_by=user.id)
    db.add(item); db.flush(); audit(db, user, request, "payment.create", "payment", item.id, {"amount_cent": item.received_amount_cent}); db.commit(); db.refresh(item); return payment_view(db, item)


@router.post("/payments/{item_id}/confirm")
def confirm_payment(item_id: str, payload: VersionInput, request: Request, db: Db, user: PaymentConfirm) -> dict:
    item = payment_for(db, user, item_id); checked(item, payload.version)
    if item.payment_status != "DRAFT": raise error(409, "INVALID_PAYMENT_STATUS", "仅草稿收款可确认。")
    item.payment_status = "CONFIRMED"; item.confirmed_at = utc_now(); item.confirmed_by = user.id; item.version += 1; audit(db, user, request, "payment.confirm", "payment", item.id); db.commit(); db.refresh(item); return payment_view(db, item)


@router.post("/payments/{item_id}/allocate")
def allocate_payment(item_id: str, payload: AllocationInput, request: Request, db: Db, user: PaymentAllocate) -> dict:
    payment = payment_for(db, user, item_id); checked(payment, payload.version)
    existing = db.scalar(select(PaymentAllocation).where(PaymentAllocation.idempotency_key == payload.idempotency_key))
    if existing: return {"id": existing.id, "payment": payment_view(db, payment)}
    if payment.payment_status not in {"CONFIRMED", "PARTIALLY_ALLOCATED"}: raise error(409, "PAYMENT_NOT_ALLOCATABLE", "收款尚未确认或已无可分配余额。")
    receivable = receivable_for(db, user, payload.receivable_id)
    if receivable.student_id != payment.student_id: raise error(409, "STUDENT_MISMATCH", "收款与应收不属于同一学员。")
    if receivable.receivable_status in {"DRAFT", "CANCELLED"}: raise error(409, "RECEIVABLE_NOT_ALLOCATABLE", "应收尚未确认或已取消。")
    if payload.allocated_amount_cent > payment.received_amount_cent - active_allocated(db, payment_id=payment.id): raise error(409, "PAYMENT_ALLOCATION_EXCEEDS_BALANCE", "分配金额超过收款未分配余额。")
    if payload.allocated_amount_cent > receivable.payable_amount_cent - active_allocated(db, receivable_id=receivable.id): raise error(409, "RECEIVABLE_ALLOCATION_EXCEEDS_BALANCE", "分配金额超过应收待收余额。")
    allocation = PaymentAllocation(payment_id=payment.id, receivable_id=receivable.id, allocated_amount_cent=payload.allocated_amount_cent, allocation_status="ACTIVE", idempotency_key=payload.idempotency_key, allocated_at=utc_now(), allocated_by=user.id, remarks=payload.remarks)
    db.add(allocation); db.flush(); payment.version += 1; recalc_payment(db, payment); recalc_receivable(db, receivable); enrollment = db.get(CourseEnrollment, receivable.course_enrollment_id); recalc_enrollment(db, enrollment); audit(db, user, request, "payment.allocate", "payment_allocation", allocation.id, {"amount_cent": allocation.allocated_amount_cent}); db.commit(); db.refresh(payment); return {"id": allocation.id, "payment": payment_view(db, payment), "receivable": receivable_view(db, receivable)}


@router.post("/payment-allocations/{allocation_id}/reverse")
def reverse_allocation(allocation_id: str, payload: ReasonInput, request: Request, db: Db, user: PaymentReverse) -> dict:
    allocation = db.get(PaymentAllocation, allocation_id)
    if not allocation: raise error(404, "ALLOCATION_NOT_FOUND", "未找到分配。")
    checked(allocation, payload.version); payment = payment_for(db, user, allocation.payment_id); receivable = receivable_for(db, user, allocation.receivable_id)
    refunded = int(db.scalar(select(func.coalesce(func.sum(RefundAllocation.refunded_amount_cent), 0)).where(RefundAllocation.payment_allocation_id == allocation.id, RefundAllocation.allocation_status == "ACTIVE")) or 0)
    if refunded: raise error(409, "ALLOCATION_HAS_REFUND", "已发生退款的分配不能直接反向。")
    if allocation.allocation_status != "ACTIVE": raise error(409, "ALLOCATION_ALREADY_REVERSED", "分配已反向。")
    allocation.allocation_status = "REVERSED"; allocation.version += 1; recalc_payment(db, payment); recalc_receivable(db, receivable); recalc_enrollment(db, db.get(CourseEnrollment, receivable.course_enrollment_id)); audit(db, user, request, "payment.allocation.reverse", "payment_allocation", allocation.id, {"reason": payload.reason}); db.commit(); return {"status": "REVERSED"}


@router.post("/payments/{item_id}/void")
def void_payment(item_id: str, payload: ReasonInput, request: Request, db: Db, user: PaymentReverse) -> dict:
    item = payment_for(db, user, item_id); checked(item, payload.version)
    if active_allocated(db, payment_id=item.id): raise error(409, "PAYMENT_HAS_ALLOCATIONS", "请先反向所有分配。")
    if item.payment_status not in {"DRAFT", "CONFIRMED"}: raise error(409, "PAYMENT_NOT_VOIDABLE", "当前收款不可作废。")
    item.payment_status = "VOIDED"; item.void_reason = payload.reason; item.version += 1; audit(db, user, request, "payment.void", "payment", item.id, {"reason": payload.reason}); db.commit(); db.refresh(item); return payment_view(db, item)


@router.post("/payments/{item_id}/reverse")
def reverse_payment(item_id: str, payload: ReasonInput, request: Request, db: Db, user: PaymentReverse) -> dict:
    item = payment_for(db, user, item_id); checked(item, payload.version)
    if active_allocated(db, payment_id=item.id): raise error(409, "PAYMENT_HAS_ALLOCATIONS", "请先反向所有分配。")
    if item.payment_status not in {"CONFIRMED", "PARTIALLY_ALLOCATED", "FULLY_ALLOCATED"}: raise error(409, "PAYMENT_NOT_REVERSIBLE", "当前收款不可冲正。")
    reversal = Payment(organization_id=item.organization_id, payment_no=code("PR"), student_id=item.student_id, payer_name=item.payer_name, received_amount_cent=item.received_amount_cent, payment_method=item.payment_method, received_at=utc_now(), payment_status="REVERSED", idempotency_key=f"reverse:{item.id}", remarks=payload.reason, reversal_of_payment_id=item.id, created_by=user.id, confirmed_at=utc_now(), confirmed_by=user.id)
    db.add(reversal); item.payment_status = "REVERSED"; item.version += 1; db.flush(); audit(db, user, request, "payment.reverse", "payment", item.id, {"reversal_id": reversal.id, "reason": payload.reason}); db.commit(); return {"id": reversal.id, "status": "REVERSED"}


def agency_paid(db: Session, payable_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(AgencyDisbursementAllocation.allocated_amount_cent), 0)).where(AgencyDisbursementAllocation.agency_payable_id == payable_id, AgencyDisbursementAllocation.allocation_status == "ACTIVE")) or 0)


def disbursement_allocated(db: Session, disbursement_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(AgencyDisbursementAllocation.allocated_amount_cent), 0)).where(AgencyDisbursementAllocation.agency_disbursement_id == disbursement_id, AgencyDisbursementAllocation.allocation_status == "ACTIVE")) or 0)


def agency_view(db: Session, item: AgencyPayable) -> dict[str, Any]:
    paid = agency_paid(db, item.id)
    return {"id": item.id, "agency_payable_no": item.agency_payable_no, "source_receivable_id": item.source_receivable_id, "payee_name": item.payee_name, "payable_amount_cent": item.payable_amount_cent, "paid_amount_cent": paid, "unpaid_amount_cent": max(0, item.payable_amount_cent - paid), "payable_status": item.payable_status, "version": item.version}


class AgencyGenerateInput(BaseModel):
    receivable_ids: list[str] = Field(min_length=1)
    payee_name: str = Field(min_length=1, max_length=200)


class DisbursementInput(BaseModel):
    payee_name: str = Field(min_length=1, max_length=200)
    paid_amount_cent: int = Field(gt=0)
    payment_method: str = Field(min_length=1, max_length=40)
    paid_at: datetime
    idempotency_key: str = Field(min_length=4, max_length=100)
    external_transaction_no: str | None = None
    remarks: str | None = None


class AgencyAllocationInput(VersionInput):
    agency_payable_id: str
    allocated_amount_cent: int = Field(gt=0)
    idempotency_key: str = Field(min_length=4, max_length=100)


@router.get("/agency-payables")
def list_agency_payables(db: Db, user: AgencyRead, limit: int = Query(100, ge=1, le=200)) -> dict:
    rows = db.scalars(select(AgencyPayable).where(AgencyPayable.organization_id == user.organization_id).order_by(AgencyPayable.created_at.desc()).limit(limit)).all()
    return {"items": [agency_view(db, row) for row in rows], "calculated_at": utc_now()}


@router.post("/agency-payables/generate-preview")
def preview_agency_payables(db: Db, user: AgencyRead) -> dict:
    rows = db.scalars(select(Receivable).where(Receivable.organization_id == user.organization_id, Receivable.economic_nature == "AGENCY_COLLECTION", Receivable.receivable_status.in_(["PARTIALLY_PAID", "PAID", "PARTIALLY_REFUNDED"]))).all()
    items = []
    for row in rows:
        existing = db.scalar(select(AgencyPayable).where(AgencyPayable.source_receivable_id == row.id))
        if not existing: items.append({"receivable_id": row.id, "receivable_no": row.receivable_no, "collected_amount_cent": active_allocated(db, receivable_id=row.id), "suggested_payable_amount_cent": row.payable_amount_cent})
    return {"items": items}


@router.post("/agency-payables/generate-confirm")
def generate_agency_payables(payload: AgencyGenerateInput, request: Request, db: Db, user: AgencyManage) -> dict:
    results = []
    for receivable_id in payload.receivable_ids:
        receivable = db.scalar(select(Receivable).where(Receivable.id == receivable_id, Receivable.organization_id == user.organization_id))
        if not receivable or receivable.economic_nature != "AGENCY_COLLECTION": results.append({"id": receivable_id, "status": "FAILED", "code": "NOT_AGENCY_RECEIVABLE"}); continue
        existing = db.scalar(select(AgencyPayable).where(AgencyPayable.source_receivable_id == receivable.id))
        if existing: results.append({"id": receivable_id, "status": "SKIPPED", "agency_payable_id": existing.id}); continue
        item = AgencyPayable(organization_id=user.organization_id, agency_payable_no=code("AP"), payee_type="EXAM_INSTITUTION", payee_name=payload.payee_name, source_receivable_id=receivable.id, payable_amount_cent=receivable.payable_amount_cent, payable_status="CONFIRMED", confirmed_at=utc_now(), confirmed_by=user.id, created_by=user.id)
        db.add(item); db.flush(); audit(db, user, request, "agency_payable.generate", "agency_payable", item.id, {"amount_cent": item.payable_amount_cent}); results.append({"id": receivable_id, "status": "SUCCESS", "agency_payable_id": item.id})
    db.commit(); return {"items": results}


@router.post("/agency-payables/{item_id}/confirm")
def confirm_agency_payable(item_id: str, payload: VersionInput, request: Request, db: Db, user: AgencyManage) -> dict:
    item = db.scalar(select(AgencyPayable).where(AgencyPayable.id == item_id, AgencyPayable.organization_id == user.organization_id))
    if not item: raise error(404, "AGENCY_PAYABLE_NOT_FOUND", "未找到应代缴。")
    checked(item, payload.version)
    if item.payable_status != "DRAFT": raise error(409, "INVALID_AGENCY_PAYABLE_STATUS", "仅草稿可确认。")
    item.payable_status = "CONFIRMED"; item.confirmed_at = utc_now(); item.confirmed_by = user.id; item.version += 1; audit(db, user, request, "agency_payable.confirm", "agency_payable", item.id); db.commit(); return agency_view(db, item)


@router.post("/agency-disbursements")
def create_disbursement(payload: DisbursementInput, request: Request, db: Db, user: AgencyCreate) -> dict:
    existing = db.scalar(select(AgencyDisbursement).where(AgencyDisbursement.idempotency_key == payload.idempotency_key))
    if existing: return {"id": existing.id, "status": existing.disbursement_status, "version": existing.version}
    external = payload.external_transaction_no.strip() if payload.external_transaction_no else None
    item = AgencyDisbursement(organization_id=user.organization_id, disbursement_no=code("AD"), payee_name=payload.payee_name, paid_amount_cent=payload.paid_amount_cent, payment_method=payload.payment_method, paid_at=payload.paid_at, external_transaction_no_ciphertext=encrypt(external) if external else None, disbursement_status="DRAFT", idempotency_key=payload.idempotency_key, remarks=payload.remarks, created_by=user.id)
    db.add(item); db.flush(); audit(db, user, request, "agency_disbursement.create", "agency_disbursement", item.id, {"amount_cent": item.paid_amount_cent}); db.commit(); return {"id": item.id, "status": item.disbursement_status, "version": item.version}


@router.post("/agency-disbursements/{item_id}/confirm")
def confirm_disbursement(item_id: str, payload: VersionInput, request: Request, db: Db, user: AgencyConfirm) -> dict:
    item = db.scalar(select(AgencyDisbursement).where(AgencyDisbursement.id == item_id, AgencyDisbursement.organization_id == user.organization_id))
    if not item: raise error(404, "DISBURSEMENT_NOT_FOUND", "未找到代缴付款。")
    checked(item, payload.version)
    if item.disbursement_status != "DRAFT": raise error(409, "INVALID_DISBURSEMENT_STATUS", "仅草稿可确认。")
    item.disbursement_status = "CONFIRMED"; item.confirmed_at = utc_now(); item.confirmed_by = user.id; item.version += 1; audit(db, user, request, "agency_disbursement.confirm", "agency_disbursement", item.id); db.commit(); return {"id": item.id, "status": item.disbursement_status, "version": item.version}


@router.post("/agency-disbursements/{item_id}/allocate")
def allocate_disbursement(item_id: str, payload: AgencyAllocationInput, request: Request, db: Db, user: AgencyConfirm) -> dict:
    item = db.scalar(select(AgencyDisbursement).where(AgencyDisbursement.id == item_id, AgencyDisbursement.organization_id == user.organization_id)); payable = db.get(AgencyPayable, payload.agency_payable_id)
    if not item or not payable or payable.organization_id != user.organization_id: raise error(404, "AGENCY_ITEM_NOT_FOUND", "未找到代缴付款或应付。")
    checked(item, payload.version)
    existing = db.scalar(select(AgencyDisbursementAllocation).where(AgencyDisbursementAllocation.idempotency_key == payload.idempotency_key))
    if existing: return {"id": existing.id, "status": "ACTIVE"}
    if item.disbursement_status not in {"CONFIRMED", "PARTIALLY_ALLOCATED"}: raise error(409, "DISBURSEMENT_NOT_ALLOCATABLE", "代缴付款不可分配。")
    if payload.allocated_amount_cent > item.paid_amount_cent - disbursement_allocated(db, item.id): raise error(409, "DISBURSEMENT_ALLOCATION_EXCEEDS_BALANCE", "超过代缴付款余额。")
    if payload.allocated_amount_cent > payable.payable_amount_cent - agency_paid(db, payable.id): raise error(409, "AGENCY_PAYABLE_ALLOCATION_EXCEEDS_BALANCE", "超过应代缴余额。")
    allocation = AgencyDisbursementAllocation(agency_disbursement_id=item.id, agency_payable_id=payable.id, allocated_amount_cent=payload.allocated_amount_cent, allocation_status="ACTIVE", idempotency_key=payload.idempotency_key, created_by=user.id)
    db.add(allocation); db.flush(); allocated = disbursement_allocated(db, item.id); paid = agency_paid(db, payable.id); item.disbursement_status = "FULLY_ALLOCATED" if allocated >= item.paid_amount_cent else "PARTIALLY_ALLOCATED"; payable.payable_status = "PAID" if paid >= payable.payable_amount_cent else "PARTIALLY_PAID"; item.version += 1; audit(db, user, request, "agency_disbursement.allocate", "agency_disbursement_allocation", allocation.id, {"amount_cent": allocation.allocated_amount_cent}); db.commit(); return {"id": allocation.id, "disbursement_status": item.disbursement_status, "payable_status": payable.payable_status}


@router.post("/agency-disbursements/{item_id}/reverse")
def reverse_disbursement(item_id: str, payload: ReasonInput, request: Request, db: Db, user: PaymentReverse) -> dict:
    item = db.scalar(select(AgencyDisbursement).where(AgencyDisbursement.id == item_id, AgencyDisbursement.organization_id == user.organization_id))
    if not item: raise error(404, "DISBURSEMENT_NOT_FOUND", "未找到代缴付款。")
    checked(item, payload.version); allocations = db.scalars(select(AgencyDisbursementAllocation).where(AgencyDisbursementAllocation.agency_disbursement_id == item.id, AgencyDisbursementAllocation.allocation_status == "ACTIVE")).all()
    for allocation in allocations:
        allocation.allocation_status = "REVERSED"; payable = db.get(AgencyPayable, allocation.agency_payable_id); payable.payable_status = "CONFIRMED" if agency_paid(db, payable.id) == 0 else "PARTIALLY_PAID"
    item.disbursement_status = "REVERSED"; item.version += 1; audit(db, user, request, "agency_disbursement.reverse", "agency_disbursement", item.id, {"reason": payload.reason}); db.commit(); return {"status": "REVERSED"}


class RefundRequestInput(BaseModel):
    course_enrollment_id: str
    refund_reason: str = Field(min_length=1, max_length=1000)
    requested_amount_cent: int | None = Field(default=None, ge=0)


class RefundApprovalInput(VersionInput):
    approved_refund_amount_cent: int = Field(ge=0)
    manual_adjustment_amount_cent: int = 0
    manual_adjustment_reason: str | None = None


class RefundPaymentInput(BaseModel):
    paid_amount_cent: int = Field(gt=0)
    payment_method: str = Field(min_length=1, max_length=40)
    paid_at: datetime
    idempotency_key: str = Field(min_length=4, max_length=100)
    payee_name: str | None = None
    external_transaction_no: str | None = None
    remarks: str | None = None


def refund_for(db: Session, user: User, item_id: str) -> RefundRequest:
    item = db.scalar(select(RefundRequest).where(RefundRequest.id == item_id, RefundRequest.organization_id == user.organization_id))
    if not item: raise error(404, "REFUND_REQUEST_NOT_FOUND", "未找到退款申请。")
    return item


def confirmed_refund_paid(db: Session, request_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(RefundPayment.paid_amount_cent), 0)).where(RefundPayment.refund_request_id == request_id, RefundPayment.payment_status == "CONFIRMED")) or 0)


def refund_view(db: Session, item: RefundRequest) -> dict[str, Any]:
    snapshots = db.scalars(select(RefundCalculationSnapshot).where(RefundCalculationSnapshot.refund_request_id == item.id).order_by(RefundCalculationSnapshot.calculation_version_no.desc())).all()
    return {"id": item.id, "refund_request_no": item.refund_request_no, "course_enrollment_id": item.course_enrollment_id, "student_id": item.student_id, "request_status": item.request_status, "requested_amount_cent": item.requested_amount_cent, "calculated_refundable_amount_cent": item.calculated_refundable_amount_cent, "approved_refund_amount_cent": item.approved_refund_amount_cent, "paid_refund_amount_cent": confirmed_refund_paid(db, item.id), "active_snapshot_id": item.active_snapshot_id, "snapshots": [{"id": row.id, "calculation_version_no": row.calculation_version_no, "tuition_paid_allocated_cent": row.tuition_paid_allocated_cent, "curriculum_total_minutes": row.curriculum_total_minutes, "locked_attended_minutes": row.locked_attended_minutes, "consumed_amount_numerator": row.consumed_amount_numerator, "consumed_amount_denominator": row.consumed_amount_denominator, "consumed_amount_cent": row.consumed_amount_cent, "refundable_amount_cent": row.refundable_amount_cent, "rounding_mode": row.rounding_mode, "stale": row.stale, "warnings": json.loads(row.warning_json)} for row in snapshots], "version": item.version}


@router.get("/refund-requests")
def list_refunds(db: Db, user: RefundRead, limit: int = Query(100, ge=1, le=200)) -> dict:
    rows = db.scalars(select(RefundRequest).where(RefundRequest.organization_id == user.organization_id).order_by(RefundRequest.created_at.desc()).limit(limit)).all(); return {"items": [refund_view(db, row) for row in rows]}


@router.post("/refund-requests")
def create_refund(payload: RefundRequestInput, request: Request, db: Db, user: RefundSubmit) -> dict:
    enrollment = enrollment_for(db, user, payload.course_enrollment_id); policy = db.get(RefundPolicyVersion, enrollment.refund_policy_version_id)
    if not policy: raise error(409, "REFUND_POLICY_MISSING", "报名未绑定退款政策。")
    item = RefundRequest(organization_id=user.organization_id, refund_request_no=code("RR"), course_enrollment_id=enrollment.id, student_id=enrollment.student_id, refund_policy_version_id=policy.id, refund_reason=payload.refund_reason, request_status="DRAFT", requested_amount_cent=payload.requested_amount_cent, manual_adjustment_amount_cent=0, created_by=user.id)
    db.add(item); db.flush(); audit(db, user, request, "refund.create", "refund_request", item.id); db.commit(); db.refresh(item); return refund_view(db, item)


def calculate_refund_snapshot(db: Session, user: User, item: RefundRequest, request: Request) -> RefundCalculationSnapshot:
    if item.request_status not in {"DRAFT", "CALCULATED"}: raise error(409, "REFUND_NOT_CALCULATABLE", "当前退款申请不可计算。")
    enrollment = db.get(CourseEnrollment, item.course_enrollment_id); policy = db.get(RefundPolicyVersion, item.refund_policy_version_id); curriculum = db.get(CurriculumVersion, enrollment.curriculum_version_id)
    if not curriculum or curriculum.total_minutes <= 0: raise error(409, "INVALID_CURRICULUM_MINUTES", "课程总分钟必须大于0。")
    method = policy.calculation_method or "PRO_RATA_BY_ATTENDED_MINUTES"; rounding = policy.rounding_mode or "HALF_UP"
    if method != "PRO_RATA_BY_ATTENDED_MINUTES": raise error(409, "UNSUPPORTED_REFUND_METHOD", "当前退款计算方法不受支持。")
    tuition = db.scalar(select(Receivable).where(Receivable.course_enrollment_id == enrollment.id, Receivable.receivable_type == "TUITION", Receivable.receivable_status != "CANCELLED"))
    if not tuition: raise error(409, "TUITION_RECEIVABLE_MISSING", "未找到培训费应收。")
    attendance = db.execute(select(AttendanceRecord, ClassSession).join(ClassMembership, AttendanceRecord.class_membership_id == ClassMembership.id).join(ClassSession, AttendanceRecord.class_session_id == ClassSession.id).where(ClassMembership.course_enrollment_id == enrollment.id, AttendanceRecord.workflow_status == "LOCKED")).all()
    raw_minutes = sum(record.actual_attendance_minutes for record, _session in attendance); warnings = []
    locked_minutes = min(raw_minutes, curriculum.total_minutes)
    if raw_minutes > curriculum.total_minutes: warnings.append("LOCKED_MINUTES_CAPPED_AT_CURRICULUM_TOTAL")
    paid = active_allocated(db, receivable_id=tuition.id); previous_refunded = refunded_for_receivable(db, tuition.id); numerator = tuition.payable_amount_cent * locked_minutes; consumed = round_ratio(numerator, curriculum.total_minutes, rounding); minimum = policy.minimum_deduction_amount_cent or 0; consumed = max(consumed, minimum if locked_minutes else 0); admin = policy.administrative_fee_amount_cent or 0; refundable = max(0, paid - consumed - admin - previous_refunded)
    version_no = int(db.scalar(select(func.coalesce(func.max(RefundCalculationSnapshot.calculation_version_no), 0)).where(RefundCalculationSnapshot.refund_request_id == item.id)) or 0) + 1
    raw = {"request": item.id, "version": version_no, "paid": paid, "total_minutes": curriculum.total_minutes, "locked_minutes": locked_minutes, "numerator": numerator, "denominator": curriculum.total_minutes, "rounding": rounding, "consumed": consumed, "admin": admin, "previous_refunded": previous_refunded, "refundable": refundable, "attendance": [(record.id, record.current_revision_no, record.actual_attendance_minutes) for record, _session in attendance]}
    snapshot = RefundCalculationSnapshot(refund_request_id=item.id, calculation_version_no=version_no, tuition_receivable_id=tuition.id, tuition_paid_allocated_cent=paid, curriculum_total_minutes=curriculum.total_minutes, locked_attended_minutes=locked_minutes, minutes_cutoff_at=utc_now(), policy_method=method, rounding_mode=rounding, consumed_amount_numerator=numerator, consumed_amount_denominator=curriculum.total_minutes, consumed_amount_cent=consumed, administrative_fee_cent=admin, nonrefundable_fee_cent=0, previous_refunded_amount_cent=previous_refunded, refundable_amount_cent=refundable, snapshot_hash=hashlib.sha256(json.dumps(raw, sort_keys=True).encode()).hexdigest(), stale=False, warning_json=json.dumps(warnings), calculated_by=user.id)
    db.add(snapshot); db.flush()
    for record, session in attendance:
        db.add(RefundAttendanceSnapshotLine(refund_calculation_snapshot_id=snapshot.id, attendance_record_id=record.id, attendance_revision_no=record.current_revision_no, class_session_id=session.id, service_date=session.service_date, actual_attendance_minutes=record.actual_attendance_minutes, locked_at=record.locked_at))
    item.active_snapshot_id = snapshot.id; item.calculated_refundable_amount_cent = refundable; item.calculated_at = utc_now(); item.calculated_by = user.id; item.request_status = "CALCULATED"; item.version += 1; audit(db, user, request, "refund.calculate", "refund_request", item.id, {"snapshot_id": snapshot.id, "refundable_amount_cent": refundable}); return snapshot


@router.post("/refund-requests/{item_id}/calculate")
def calculate_refund(item_id: str, payload: VersionInput, request: Request, db: Db, user: RefundCalculate) -> dict:
    item = refund_for(db, user, item_id); checked(item, payload.version); calculate_refund_snapshot(db, user, item, request); db.commit(); db.refresh(item); return refund_view(db, item)


@router.post("/refund-requests/{item_id}/recalculate")
def recalculate_refund(item_id: str, payload: VersionInput, request: Request, db: Db, user: RefundCalculate) -> dict:
    item = refund_for(db, user, item_id); checked(item, payload.version); calculate_refund_snapshot(db, user, item, request); db.commit(); db.refresh(item); return refund_view(db, item)


def snapshot_is_stale(db: Session, snapshot: RefundCalculationSnapshot) -> bool:
    lines = db.scalars(select(RefundAttendanceSnapshotLine).where(RefundAttendanceSnapshotLine.refund_calculation_snapshot_id == snapshot.id)).all()
    refund = db.get(RefundRequest, snapshot.refund_request_id)
    current_ids = set(db.scalars(select(AttendanceRecord.id).join(ClassMembership, AttendanceRecord.class_membership_id == ClassMembership.id).where(ClassMembership.course_enrollment_id == refund.course_enrollment_id, AttendanceRecord.workflow_status == "LOCKED")).all())
    if current_ids != {line.attendance_record_id for line in lines}: return True
    for line in lines:
        record = db.get(AttendanceRecord, line.attendance_record_id)
        if not record or record.workflow_status != "LOCKED" or record.current_revision_no != line.attendance_revision_no or record.actual_attendance_minutes != line.actual_attendance_minutes: return True
    return False


@router.post("/refund-requests/{item_id}/submit")
def submit_refund(item_id: str, payload: VersionInput, request: Request, db: Db, user: RefundSubmit) -> dict:
    item = refund_for(db, user, item_id); checked(item, payload.version)
    if item.request_status != "CALCULATED": raise error(409, "REFUND_NOT_SUBMITTABLE", "仅已计算退款可提交。")
    snapshot = db.get(RefundCalculationSnapshot, item.active_snapshot_id)
    if snapshot_is_stale(db, snapshot): snapshot.stale = True; db.commit(); raise error(409, "REFUND_SNAPSHOT_STALE", "考勤已变化，请重新计算退款。")
    item.request_status = "SUBMITTED"; item.submitted_at = utc_now(); item.submitted_by = user.id; item.version += 1; audit(db, user, request, "refund.submit", "refund_request", item.id); db.commit(); return refund_view(db, item)


@router.post("/refund-requests/{item_id}/approve")
def approve_refund(item_id: str, payload: RefundApprovalInput, request: Request, db: Db, user: RefundApprove) -> dict:
    item = refund_for(db, user, item_id); checked(item, payload.version)
    if item.request_status != "SUBMITTED": raise error(409, "REFUND_NOT_APPROVABLE", "仅已提交退款可审批。")
    if item.submitted_by == user.id: raise error(409, "REFUND_SELF_APPROVAL_FORBIDDEN", "申请人不能审批自己的退款。")
    snapshot = db.get(RefundCalculationSnapshot, item.active_snapshot_id)
    if snapshot_is_stale(db, snapshot): snapshot.stale = True; db.commit(); raise error(409, "REFUND_SNAPSHOT_STALE", "考勤已变化，请重新计算退款。")
    current_source_limit = max(0, active_allocated(db, receivable_id=snapshot.tuition_receivable_id) - snapshot.consumed_amount_cent - snapshot.administrative_fee_cent - refunded_for_receivable(db, snapshot.tuition_receivable_id))
    maximum = max(0, (item.calculated_refundable_amount_cent or 0) + payload.manual_adjustment_amount_cent)
    maximum = min(maximum, current_source_limit + max(0, payload.manual_adjustment_amount_cent))
    if payload.manual_adjustment_amount_cent and not payload.manual_adjustment_reason: raise error(422, "ADJUSTMENT_REASON_REQUIRED", "人工调整必须填写原因。")
    if payload.approved_refund_amount_cent > maximum: raise error(409, "REFUND_APPROVAL_EXCEEDS_CALCULATION", "批准金额超过计算与调整后的上限。")
    item.approved_refund_amount_cent = payload.approved_refund_amount_cent; item.manual_adjustment_amount_cent = payload.manual_adjustment_amount_cent; item.manual_adjustment_reason = payload.manual_adjustment_reason; item.request_status = "APPROVED"; item.approved_at = utc_now(); item.approved_by = user.id; item.version += 1; audit(db, user, request, "refund.approve", "refund_request", item.id, {"approved_amount_cent": item.approved_refund_amount_cent, "adjustment_cent": payload.manual_adjustment_amount_cent}); db.commit(); return refund_view(db, item)


@router.post("/refund-requests/{item_id}/reject")
def reject_refund(item_id: str, payload: ReasonInput, request: Request, db: Db, user: RefundApprove) -> dict:
    item = refund_for(db, user, item_id); checked(item, payload.version)
    if item.request_status != "SUBMITTED": raise error(409, "REFUND_NOT_REJECTABLE", "仅已提交退款可拒绝。")
    item.request_status = "REJECTED"; item.rejected_at = utc_now(); item.rejected_by = user.id; item.rejection_reason = payload.reason; item.version += 1; audit(db, user, request, "refund.reject", "refund_request", item.id, {"reason": payload.reason}); db.commit(); return refund_view(db, item)


@router.post("/refund-requests/{item_id}/cancel")
def cancel_refund(item_id: str, payload: ReasonInput, request: Request, db: Db, user: RefundSubmit) -> dict:
    item = refund_for(db, user, item_id); checked(item, payload.version)
    if item.request_status not in {"DRAFT", "CALCULATED", "SUBMITTED"}: raise error(409, "REFUND_NOT_CANCELLABLE", "当前退款不可取消。")
    item.request_status = "CANCELLED"; item.version += 1; audit(db, user, request, "refund.cancel", "refund_request", item.id, {"reason": payload.reason}); db.commit(); return refund_view(db, item)


@router.post("/refund-payments")
def create_refund_payment(refund_request_id: str, payload: RefundPaymentInput, request: Request, db: Db, user: RefundPay) -> dict:
    item = refund_for(db, user, refund_request_id); existing = db.scalar(select(RefundPayment).where(RefundPayment.idempotency_key == payload.idempotency_key))
    if existing: return {"id": existing.id, "status": existing.payment_status, "version": existing.version}
    if item.request_status not in {"APPROVED", "PAYMENT_PENDING", "PARTIALLY_PAID"}: raise error(409, "REFUND_NOT_PAYABLE", "退款尚未批准。")
    drafts = int(db.scalar(select(func.coalesce(func.sum(RefundPayment.paid_amount_cent), 0)).where(RefundPayment.refund_request_id == item.id, RefundPayment.payment_status.in_(["DRAFT", "CONFIRMED"]))) or 0)
    if drafts + payload.paid_amount_cent > (item.approved_refund_amount_cent or 0): raise error(409, "REFUND_PAYMENT_EXCEEDS_APPROVAL", "退款付款总额超过批准金额。")
    external = payload.external_transaction_no.strip() if payload.external_transaction_no else None
    payment = RefundPayment(refund_payment_no=code("RP"), refund_request_id=item.id, paid_amount_cent=payload.paid_amount_cent, payment_method=payload.payment_method, paid_at=payload.paid_at, payee_name=payload.payee_name, external_transaction_no_ciphertext=encrypt(external) if external else None, payment_status="DRAFT", idempotency_key=payload.idempotency_key, remarks=payload.remarks, created_by=user.id)
    db.add(payment); item.request_status = "PAYMENT_PENDING"; item.version += 1; db.flush(); audit(db, user, request, "refund_payment.create", "refund_payment", payment.id, {"amount_cent": payment.paid_amount_cent}); db.commit(); return {"id": payment.id, "status": payment.payment_status, "version": payment.version}


@router.post("/refund-payments/{payment_id}/confirm")
def confirm_refund_payment(payment_id: str, payload: VersionInput, request: Request, db: Db, user: RefundPay) -> dict:
    payment = db.get(RefundPayment, payment_id)
    if not payment: raise error(404, "REFUND_PAYMENT_NOT_FOUND", "未找到退款付款。")
    item = refund_for(db, user, payment.refund_request_id); checked(payment, payload.version)
    if payment.payment_status != "DRAFT": raise error(409, "INVALID_REFUND_PAYMENT_STATUS", "仅草稿退款付款可确认。")
    remaining = payment.paid_amount_cent; allocations = db.scalars(select(PaymentAllocation).join(Receivable, PaymentAllocation.receivable_id == Receivable.id).where(Receivable.course_enrollment_id == item.course_enrollment_id, Receivable.receivable_type == "TUITION", PaymentAllocation.allocation_status == "ACTIVE").order_by(PaymentAllocation.allocated_at)).all()
    for source in allocations:
        already = int(db.scalar(select(func.coalesce(func.sum(RefundAllocation.refunded_amount_cent), 0)).where(RefundAllocation.payment_allocation_id == source.id, RefundAllocation.allocation_status == "ACTIVE")) or 0); available = source.allocated_amount_cent - already
        if available <= 0: continue
        amount = min(remaining, available); db.add(RefundAllocation(refund_payment_id=payment.id, payment_allocation_id=source.id, receivable_id=source.receivable_id, refunded_amount_cent=amount, allocation_status="ACTIVE", created_by=user.id)); remaining -= amount
        if remaining == 0: break
    if remaining: raise error(409, "REFUND_EXCEEDS_SOURCE_ALLOCATIONS", "退款金额超过可追溯的培训费收款分配。")
    payment.payment_status = "CONFIRMED"; payment.confirmed_at = utc_now(); payment.confirmed_by = user.id; payment.version += 1; db.flush(); paid = confirmed_refund_paid(db, item.id); item.request_status = "PAID" if paid >= (item.approved_refund_amount_cent or 0) else "PARTIALLY_PAID"; item.version += 1; tuition = db.scalar(select(Receivable).where(Receivable.course_enrollment_id == item.course_enrollment_id, Receivable.receivable_type == "TUITION", Receivable.receivable_status != "CANCELLED")); recalc_receivable(db, tuition); recalc_enrollment(db, db.get(CourseEnrollment, item.course_enrollment_id)); audit(db, user, request, "refund_payment.confirm", "refund_payment", payment.id, {"amount_cent": payment.paid_amount_cent}); db.commit(); return {"id": payment.id, "status": payment.payment_status, "refund_request_status": item.request_status}


@router.post("/refund-payments/{payment_id}/reverse")
def reverse_refund_payment(payment_id: str, payload: ReasonInput, request: Request, db: Db, user: RefundReverse) -> dict:
    payment = db.get(RefundPayment, payment_id)
    if not payment: raise error(404, "REFUND_PAYMENT_NOT_FOUND", "未找到退款付款。")
    item = refund_for(db, user, payment.refund_request_id); checked(payment, payload.version)
    if payment.payment_status != "CONFIRMED": raise error(409, "REFUND_PAYMENT_NOT_REVERSIBLE", "仅已确认退款可冲正。")
    for allocation in db.scalars(select(RefundAllocation).where(RefundAllocation.refund_payment_id == payment.id, RefundAllocation.allocation_status == "ACTIVE")).all(): allocation.allocation_status = "REVERSED"
    reversal = RefundPayment(refund_payment_no=code("RPR"), refund_request_id=item.id, paid_amount_cent=payment.paid_amount_cent, payment_method=payment.payment_method, paid_at=utc_now(), payment_status="REVERSED", idempotency_key=f"reverse:{payment.id}", remarks=payload.reason, created_by=user.id, reversal_of_refund_payment_id=payment.id)
    db.add(reversal); payment.payment_status = "REVERSED"; payment.version += 1; db.flush(); paid = confirmed_refund_paid(db, item.id); item.request_status = "PARTIALLY_PAID" if paid else "APPROVED"; item.version += 1; tuition = db.scalar(select(Receivable).where(Receivable.course_enrollment_id == item.course_enrollment_id, Receivable.receivable_type == "TUITION")); recalc_receivable(db, tuition); recalc_enrollment(db, db.get(CourseEnrollment, item.course_enrollment_id)); audit(db, user, request, "refund_payment.reverse", "refund_payment", payment.id, {"reason": payload.reason}); db.commit(); return {"status": "REVERSED", "reversal_id": reversal.id}


def teacher_line_paid(db: Session, line_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(TeacherPaymentAllocation.allocated_amount_cent), 0)).where(TeacherPaymentAllocation.teacher_settlement_line_id == line_id, TeacherPaymentAllocation.allocation_status == "ACTIVE")) or 0)


def teacher_payment_allocated(db: Session, payment_id: str) -> int:
    return int(db.scalar(select(func.coalesce(func.sum(TeacherPaymentAllocation.allocated_amount_cent), 0)).where(TeacherPaymentAllocation.teacher_payment_id == payment_id, TeacherPaymentAllocation.allocation_status == "ACTIVE")) or 0)


def settlement_view(db: Session, item: TeacherSettlementBatch) -> dict[str, Any]:
    lines = db.scalars(select(TeacherSettlementLine).where(TeacherSettlementLine.settlement_batch_id == item.id).order_by(TeacherSettlementLine.service_date, TeacherSettlementLine.teacher_id)).all()
    return {"id": item.id, "batch_no": item.batch_no, "period_start": item.period_start, "period_end": item.period_end, "settlement_status": item.settlement_status, "total_minutes": item.total_minutes, "total_amount_cent": item.total_amount_cent, "paid_amount_cent": sum(teacher_line_paid(db, line.id) for line in lines), "lines": [{"id": line.id, "teacher_id": line.teacher_id, "class_session_id": line.class_session_id, "service_date": line.service_date, "teaching_role": line.teaching_role, "settleable_minutes": line.settleable_minutes, "rate_amount_cent": line.rate_amount_cent, "rate_unit_minutes": line.rate_unit_minutes, "base_amount_cent": line.base_amount_cent, "adjustment_amount_cent": line.adjustment_amount_cent, "final_amount_cent": line.final_amount_cent, "paid_amount_cent": teacher_line_paid(db, line.id), "line_status": line.line_status, "version": line.version} for line in lines], "version": item.version}


class SettlementPeriodInput(BaseModel):
    period_start: date
    period_end: date


class SettlementAdjustInput(VersionInput):
    adjustment_amount_cent: int
    reason: str = Field(min_length=1, max_length=500)


class TeacherPaymentInput(BaseModel):
    teacher_id: str
    paid_amount_cent: int = Field(gt=0)
    payment_method: str = Field(min_length=1, max_length=40)
    paid_at: datetime
    idempotency_key: str = Field(min_length=4, max_length=100)
    external_transaction_no: str | None = None
    remarks: str | None = None


class TeacherAllocationInput(VersionInput):
    teacher_settlement_line_id: str
    allocated_amount_cent: int = Field(gt=0)
    idempotency_key: str = Field(min_length=4, max_length=100)


def eligible_assignments(db: Session, user: User, start: date, end: date) -> list[tuple[SessionTeacherAssignment, ClassSession]]:
    rows = db.execute(select(SessionTeacherAssignment, ClassSession).join(ClassSession, SessionTeacherAssignment.class_session_id == ClassSession.id).join(ClassCycle, ClassSession.class_cycle_id == ClassCycle.id).where(ClassCycle.organization_id == user.organization_id, ClassSession.service_date >= start, ClassSession.service_date <= end, ClassSession.session_status == "COMPLETED", SessionTeacherAssignment.confirmation_status == "CONFIRMED", SessionTeacherAssignment.settleable_minutes.is_not(None), SessionTeacherAssignment.rate_amount_cent.is_not(None), SessionTeacherAssignment.rate_unit_minutes.is_not(None))).all()
    return [(assignment, session) for assignment, session in rows if not db.scalar(select(TeacherSettlementLine.id).where(TeacherSettlementLine.session_teacher_assignment_id == assignment.id))]


@router.post("/teacher-settlement-batches/preview")
def preview_settlement(payload: SettlementPeriodInput, db: Db, user: SettlementRead) -> dict:
    if payload.period_end < payload.period_start: raise error(422, "INVALID_PERIOD", "结算结束日期不能早于开始日期。")
    items = []
    for assignment, session in eligible_assignments(db, user, payload.period_start, payload.period_end):
        amount = round_ratio(assignment.settleable_minutes * assignment.rate_amount_cent, assignment.rate_unit_minutes, "HALF_UP")
        items.append({"assignment_id": assignment.id, "teacher_id": assignment.teacher_id, "class_session_id": session.id, "service_date": session.service_date, "settleable_minutes": assignment.settleable_minutes, "rate_amount_cent": assignment.rate_amount_cent, "rate_unit_minutes": assignment.rate_unit_minutes, "amount_cent": amount})
    return {"items": items, "total_minutes": sum(row["settleable_minutes"] for row in items), "total_amount_cent": sum(row["amount_cent"] for row in items)}


@router.post("/teacher-settlement-batches")
def create_settlement(payload: SettlementPeriodInput, request: Request, db: Db, user: SettlementCalculate) -> dict:
    if payload.period_end < payload.period_start: raise error(422, "INVALID_PERIOD", "结算结束日期不能早于开始日期。")
    item = TeacherSettlementBatch(organization_id=user.organization_id, batch_no=code("TS"), period_start=payload.period_start, period_end=payload.period_end, settlement_status="DRAFT", total_minutes=0, total_amount_cent=0, created_by=user.id)
    db.add(item); db.flush(); audit(db, user, request, "teacher_settlement.create", "teacher_settlement_batch", item.id); db.commit(); return settlement_view(db, item)


@router.get("/teacher-settlement-batches")
def list_settlements(db: Db, user: SettlementRead, limit: int = Query(50, ge=1, le=200)) -> dict:
    rows = db.scalars(select(TeacherSettlementBatch).where(TeacherSettlementBatch.organization_id == user.organization_id).order_by(TeacherSettlementBatch.created_at.desc()).limit(limit)).all(); return {"items": [settlement_view(db, row) for row in rows]}


@router.get("/teacher-settlement-batches/{item_id}")
def get_settlement(item_id: str, db: Db, user: SettlementRead) -> dict:
    item = db.scalar(select(TeacherSettlementBatch).where(TeacherSettlementBatch.id == item_id, TeacherSettlementBatch.organization_id == user.organization_id))
    if not item: raise error(404, "SETTLEMENT_BATCH_NOT_FOUND", "未找到教师结算批次。")
    return settlement_view(db, item)


@router.post("/teacher-settlement-batches/{item_id}/calculate")
def calculate_settlement(item_id: str, payload: VersionInput, request: Request, db: Db, user: SettlementCalculate) -> dict:
    item = db.scalar(select(TeacherSettlementBatch).where(TeacherSettlementBatch.id == item_id, TeacherSettlementBatch.organization_id == user.organization_id))
    if not item: raise error(404, "SETTLEMENT_BATCH_NOT_FOUND", "未找到教师结算批次。")
    checked(item, payload.version)
    if item.settlement_status not in {"DRAFT", "CALCULATED"}: raise error(409, "SETTLEMENT_NOT_CALCULATABLE", "当前批次不可计算。")
    if db.scalar(select(TeacherSettlementLine.id).where(TeacherSettlementLine.settlement_batch_id == item.id)): raise error(409, "SETTLEMENT_ALREADY_CALCULATED", "已有结算明细，不可覆盖计算。")
    total_minutes = total_amount = 0
    for assignment, session in eligible_assignments(db, user, item.period_start, item.period_end):
        amount = round_ratio(assignment.settleable_minutes * assignment.rate_amount_cent, assignment.rate_unit_minutes, "HALF_UP")
        db.add(TeacherSettlementLine(settlement_batch_id=item.id, teacher_id=assignment.teacher_id, session_teacher_assignment_id=assignment.id, class_session_id=session.id, class_cycle_id=session.class_cycle_id, service_date=session.service_date, teaching_role=assignment.teaching_role, settleable_minutes=assignment.settleable_minutes, rate_amount_cent=assignment.rate_amount_cent, rate_unit_minutes=assignment.rate_unit_minutes, base_amount_cent=amount, adjustment_amount_cent=0, final_amount_cent=amount, line_status="INCLUDED", source_version=assignment.version, created_by=user.id)); total_minutes += assignment.settleable_minutes; total_amount += amount
    item.total_minutes = total_minutes; item.total_amount_cent = total_amount; item.settlement_status = "CALCULATED"; item.calculated_at = utc_now(); item.calculated_by = user.id; item.version += 1; audit(db, user, request, "teacher_settlement.calculate", "teacher_settlement_batch", item.id, {"total_minutes": total_minutes, "total_amount_cent": total_amount}); db.commit(); return settlement_view(db, item)


@router.post("/teacher-settlement-lines/{line_id}/adjust")
def adjust_settlement_line(line_id: str, payload: SettlementAdjustInput, request: Request, db: Db, user: SettlementCalculate) -> dict:
    line = db.get(TeacherSettlementLine, line_id)
    if not line: raise error(404, "SETTLEMENT_LINE_NOT_FOUND", "未找到结算明细。")
    batch = db.scalar(select(TeacherSettlementBatch).where(TeacherSettlementBatch.id == line.settlement_batch_id, TeacherSettlementBatch.organization_id == user.organization_id))
    if not batch: raise error(404, "SETTLEMENT_LINE_NOT_FOUND", "未找到结算明细。")
    checked(line, payload.version)
    if batch.settlement_status != "CALCULATED": raise error(409, "SETTLEMENT_LINE_NOT_ADJUSTABLE", "仅已计算批次可调整。")
    final = line.base_amount_cent + payload.adjustment_amount_cent
    if final < 0: raise error(409, "NEGATIVE_SETTLEMENT_AMOUNT", "结算金额不能为负。")
    old = line.final_amount_cent; line.adjustment_amount_cent = payload.adjustment_amount_cent; line.adjustment_reason = payload.reason; line.final_amount_cent = final; line.version += 1; batch.total_amount_cent += final - old; batch.version += 1; audit(db, user, request, "teacher_settlement.adjust", "teacher_settlement_line", line.id, {"before_cent": old, "after_cent": final, "reason": payload.reason}); db.commit(); return {"id": line.id, "final_amount_cent": final, "version": line.version}


@router.post("/teacher-settlement-batches/{item_id}/submit")
def submit_settlement(item_id: str, payload: VersionInput, request: Request, db: Db, user: SettlementSubmit) -> dict:
    item = db.scalar(select(TeacherSettlementBatch).where(TeacherSettlementBatch.id == item_id, TeacherSettlementBatch.organization_id == user.organization_id))
    if not item: raise error(404, "SETTLEMENT_BATCH_NOT_FOUND", "未找到教师结算批次。")
    checked(item, payload.version)
    if item.settlement_status != "CALCULATED": raise error(409, "SETTLEMENT_NOT_SUBMITTABLE", "仅已计算批次可提交。")
    item.settlement_status = "SUBMITTED"; item.submitted_at = utc_now(); item.submitted_by = user.id; item.version += 1; audit(db, user, request, "teacher_settlement.submit", "teacher_settlement_batch", item.id); db.commit(); return settlement_view(db, item)


@router.post("/teacher-settlement-batches/{item_id}/approve")
def approve_settlement(item_id: str, payload: VersionInput, request: Request, db: Db, user: SettlementApprove) -> dict:
    item = db.scalar(select(TeacherSettlementBatch).where(TeacherSettlementBatch.id == item_id, TeacherSettlementBatch.organization_id == user.organization_id))
    if not item: raise error(404, "SETTLEMENT_BATCH_NOT_FOUND", "未找到教师结算批次。")
    checked(item, payload.version)
    if item.settlement_status != "SUBMITTED": raise error(409, "SETTLEMENT_NOT_APPROVABLE", "仅已提交批次可审批。")
    if item.submitted_by == user.id: raise error(409, "SETTLEMENT_SELF_APPROVAL_FORBIDDEN", "提交人不能审批自己的结算批次。")
    item.settlement_status = "APPROVED"; item.approved_at = utc_now(); item.approved_by = user.id; item.version += 1; audit(db, user, request, "teacher_settlement.approve", "teacher_settlement_batch", item.id); db.commit(); return settlement_view(db, item)


@router.post("/teacher-settlement-batches/{item_id}/cancel")
def cancel_settlement(item_id: str, payload: ReasonInput, request: Request, db: Db, user: SettlementApprove) -> dict:
    item = db.scalar(select(TeacherSettlementBatch).where(TeacherSettlementBatch.id == item_id, TeacherSettlementBatch.organization_id == user.organization_id))
    if not item: raise error(404, "SETTLEMENT_BATCH_NOT_FOUND", "未找到教师结算批次。")
    checked(item, payload.version)
    if item.settlement_status in {"PARTIALLY_PAID", "PAID"}: raise error(409, "SETTLEMENT_HAS_PAYMENTS", "已有付款的结算批次不能取消。")
    item.settlement_status = "CANCELLED"; item.cancellation_reason = payload.reason; item.version += 1; audit(db, user, request, "teacher_settlement.cancel", "teacher_settlement_batch", item.id, {"reason": payload.reason}); db.commit(); return settlement_view(db, item)


@router.post("/teacher-payments")
def create_teacher_payment(payload: TeacherPaymentInput, request: Request, db: Db, user: TeacherPayCreate) -> dict:
    existing = db.scalar(select(TeacherPayment).where(TeacherPayment.idempotency_key == payload.idempotency_key))
    if existing: return {"id": existing.id, "status": existing.payment_status, "version": existing.version}
    teacher = db.scalar(select(TeacherProfile).join(User, TeacherProfile.created_by == User.id).where(TeacherProfile.id == payload.teacher_id, User.organization_id == user.organization_id))
    if not teacher: raise error(404, "TEACHER_NOT_FOUND", "未找到教师。")
    external = payload.external_transaction_no.strip() if payload.external_transaction_no else None
    item = TeacherPayment(organization_id=user.organization_id, teacher_payment_no=code("TP"), teacher_id=teacher.id, paid_amount_cent=payload.paid_amount_cent, payment_method=payload.payment_method, paid_at=payload.paid_at, external_transaction_no_ciphertext=encrypt(external) if external else None, payment_status="DRAFT", idempotency_key=payload.idempotency_key, remarks=payload.remarks, created_by=user.id)
    db.add(item); db.flush(); audit(db, user, request, "teacher_payment.create", "teacher_payment", item.id, {"amount_cent": item.paid_amount_cent}); db.commit(); return {"id": item.id, "status": item.payment_status, "version": item.version}


@router.post("/teacher-payments/{item_id}/confirm")
def confirm_teacher_payment(item_id: str, payload: VersionInput, request: Request, db: Db, user: TeacherPayConfirm) -> dict:
    item = db.scalar(select(TeacherPayment).where(TeacherPayment.id == item_id, TeacherPayment.organization_id == user.organization_id))
    if not item: raise error(404, "TEACHER_PAYMENT_NOT_FOUND", "未找到教师付款。")
    checked(item, payload.version)
    if item.payment_status != "DRAFT": raise error(409, "INVALID_TEACHER_PAYMENT_STATUS", "仅草稿付款可确认。")
    item.payment_status = "CONFIRMED"; item.confirmed_at = utc_now(); item.confirmed_by = user.id; item.version += 1; audit(db, user, request, "teacher_payment.confirm", "teacher_payment", item.id); db.commit(); return {"id": item.id, "status": item.payment_status, "version": item.version}


@router.post("/teacher-payments/{item_id}/allocate")
def allocate_teacher_payment(item_id: str, payload: TeacherAllocationInput, request: Request, db: Db, user: TeacherPayConfirm) -> dict:
    item = db.scalar(select(TeacherPayment).where(TeacherPayment.id == item_id, TeacherPayment.organization_id == user.organization_id)); line = db.get(TeacherSettlementLine, payload.teacher_settlement_line_id)
    if not item or not line: raise error(404, "TEACHER_PAYMENT_ITEM_NOT_FOUND", "未找到教师付款或结算明细。")
    checked(item, payload.version); batch = db.get(TeacherSettlementBatch, line.settlement_batch_id)
    if batch.organization_id != user.organization_id or line.teacher_id != item.teacher_id: raise error(409, "TEACHER_MISMATCH", "付款与结算明细不属于同一教师。")
    if batch.settlement_status not in {"APPROVED", "PARTIALLY_PAID"}: raise error(409, "SETTLEMENT_NOT_PAYABLE", "结算批次尚未批准。")
    existing = db.scalar(select(TeacherPaymentAllocation).where(TeacherPaymentAllocation.idempotency_key == payload.idempotency_key))
    if existing: return {"id": existing.id, "status": "ACTIVE"}
    if item.payment_status not in {"CONFIRMED", "PARTIALLY_ALLOCATED"}: raise error(409, "TEACHER_PAYMENT_NOT_ALLOCATABLE", "教师付款不可分配。")
    if payload.allocated_amount_cent > item.paid_amount_cent - teacher_payment_allocated(db, item.id): raise error(409, "TEACHER_PAYMENT_EXCEEDS_BALANCE", "超过教师付款未分配余额。")
    if payload.allocated_amount_cent > line.final_amount_cent - teacher_line_paid(db, line.id): raise error(409, "SETTLEMENT_LINE_EXCEEDS_BALANCE", "超过结算明细未付余额。")
    allocation = TeacherPaymentAllocation(teacher_payment_id=item.id, teacher_settlement_line_id=line.id, allocated_amount_cent=payload.allocated_amount_cent, allocation_status="ACTIVE", idempotency_key=payload.idempotency_key, created_by=user.id)
    db.add(allocation); db.flush(); item.payment_status = "FULLY_ALLOCATED" if teacher_payment_allocated(db, item.id) >= item.paid_amount_cent else "PARTIALLY_ALLOCATED"; item.version += 1; lines = db.scalars(select(TeacherSettlementLine).where(TeacherSettlementLine.settlement_batch_id == batch.id)).all(); paid = sum(teacher_line_paid(db, candidate.id) for candidate in lines); batch.settlement_status = "PAID" if paid >= batch.total_amount_cent else "PARTIALLY_PAID"; batch.version += 1; audit(db, user, request, "teacher_payment.allocate", "teacher_payment_allocation", allocation.id, {"amount_cent": allocation.allocated_amount_cent}); db.commit(); return {"id": allocation.id, "payment_status": item.payment_status, "batch_status": batch.settlement_status}


@router.post("/teacher-payments/{item_id}/reverse")
def reverse_teacher_payment(item_id: str, payload: ReasonInput, request: Request, db: Db, user: PaymentReverse) -> dict:
    item = db.scalar(select(TeacherPayment).where(TeacherPayment.id == item_id, TeacherPayment.organization_id == user.organization_id))
    if not item: raise error(404, "TEACHER_PAYMENT_NOT_FOUND", "未找到教师付款。")
    checked(item, payload.version)
    allocations = db.scalars(select(TeacherPaymentAllocation).where(TeacherPaymentAllocation.teacher_payment_id == item.id, TeacherPaymentAllocation.allocation_status == "ACTIVE")).all(); batches = set()
    for allocation in allocations:
        allocation.allocation_status = "REVERSED"; line = db.get(TeacherSettlementLine, allocation.teacher_settlement_line_id); batches.add(line.settlement_batch_id)
    reversal = TeacherPayment(organization_id=item.organization_id, teacher_payment_no=code("TPR"), teacher_id=item.teacher_id, paid_amount_cent=item.paid_amount_cent, payment_method=item.payment_method, paid_at=utc_now(), payment_status="REVERSED", idempotency_key=f"reverse:{item.id}", remarks=payload.reason, created_by=user.id, reversal_of_teacher_payment_id=item.id)
    db.add(reversal); item.payment_status = "REVERSED"; item.version += 1; db.flush()
    for batch_id in batches:
        batch = db.get(TeacherSettlementBatch, batch_id); lines = db.scalars(select(TeacherSettlementLine).where(TeacherSettlementLine.settlement_batch_id == batch.id)).all(); paid = sum(teacher_line_paid(db, line.id) for line in lines); batch.settlement_status = "PARTIALLY_PAID" if paid else "APPROVED"; batch.version += 1
    audit(db, user, request, "teacher_payment.reverse", "teacher_payment", item.id, {"reason": payload.reason, "reversal_id": reversal.id}); db.commit(); return {"status": "REVERSED", "reversal_id": reversal.id}


@router.get("/students/{student_id}/financial-overview")
def student_financial_overview(student_id: str, db: Db, user: ReceivableRead) -> dict:
    student = db.scalar(select(Student).where(Student.id == student_id, Student.organization_id == user.organization_id))
    if not student: raise error(404, "STUDENT_NOT_FOUND", "未找到学员。")
    receivables = db.scalars(select(Receivable).where(Receivable.student_id == student.id, Receivable.organization_id == user.organization_id)).all(); payments = db.scalars(select(Payment).where(Payment.student_id == student.id, Payment.organization_id == user.organization_id, Payment.payment_status.not_in(["VOIDED", "REVERSED", "DRAFT"]))).all(); views = [receivable_view(db, row) for row in receivables]
    return {"student_id": student.id, "receivables": views, "summary": {"school_revenue_payable_cent": sum(row.payable_amount_cent for row in receivables if row.economic_nature == "SCHOOL_REVENUE"), "agency_collection_payable_cent": sum(row.payable_amount_cent for row in receivables if row.economic_nature == "AGENCY_COLLECTION"), "allocated_cent": sum(row["allocated_amount_cent"] for row in views), "outstanding_cent": sum(row["outstanding_amount_cent"] for row in views), "refunded_cent": sum(row["refunded_amount_cent"] for row in views), "unallocated_payment_cent": sum(max(0, row.received_amount_cent - active_allocated(db, payment_id=row.id)) for row in payments)}, "calculated_at": utc_now()}


@router.get("/enrollments/{enrollment_id}/financial-statement")
def enrollment_statement(enrollment_id: str, db: Db, user: ReceivableRead) -> dict:
    enrollment = enrollment_for(db, user, enrollment_id); rows = db.scalars(select(Receivable).where(Receivable.course_enrollment_id == enrollment.id)).all(); return {"enrollment_id": enrollment.id, "financial_status": enrollment.financial_status, "receivables": [receivable_view(db, row) for row in rows], "calculated_at": utc_now()}


@router.get("/finance/agency-summary")
def agency_summary(db: Db, user: AgencyRead) -> dict:
    receivables = db.scalars(select(Receivable).where(Receivable.organization_id == user.organization_id, Receivable.economic_nature == "AGENCY_COLLECTION")).all(); payables = db.scalars(select(AgencyPayable).where(AgencyPayable.organization_id == user.organization_id, AgencyPayable.payable_status != "CANCELLED")).all(); collected = sum(active_allocated(db, receivable_id=row.id) for row in receivables); payable = sum(row.payable_amount_cent for row in payables); paid = sum(agency_paid(db, row.id) for row in payables); return {"collected_amount_cent": collected, "payable_amount_cent": payable, "paid_amount_cent": paid, "unpaid_amount_cent": max(0, payable - paid), "collection_payable_difference_cent": collected - payable, "items": [agency_view(db, row) for row in payables], "calculated_at": utc_now()}


@router.get("/teachers/{teacher_id}/settlement-summary")
def teacher_summary(teacher_id: str, db: Db, user: SettlementRead) -> dict:
    teacher = db.scalar(select(TeacherProfile).join(User, TeacherProfile.created_by == User.id).where(TeacherProfile.id == teacher_id, User.organization_id == user.organization_id))
    if not teacher: raise error(404, "TEACHER_NOT_FOUND", "未找到教师。")
    lines = db.scalars(select(TeacherSettlementLine).join(TeacherSettlementBatch).where(TeacherSettlementLine.teacher_id == teacher.id, TeacherSettlementBatch.organization_id == user.organization_id, TeacherSettlementBatch.settlement_status.in_(["APPROVED", "PARTIALLY_PAID", "PAID"]))).all(); amount = sum(line.final_amount_cent for line in lines); paid = sum(teacher_line_paid(db, line.id) for line in lines); return {"teacher_id": teacher.id, "settled_minutes": sum(line.settleable_minutes for line in lines), "settled_amount_cent": amount, "paid_amount_cent": paid, "unpaid_amount_cent": max(0, amount - paid), "calculated_at": utc_now()}


@router.get("/finance/exceptions")
def finance_exceptions(db: Db, user: ReceivableRead) -> dict:
    payments = db.scalars(select(Payment).where(Payment.organization_id == user.organization_id, Payment.payment_status.in_(["CONFIRMED", "PARTIALLY_ALLOCATED"]))).all(); assessments = db.scalars(select(ExamFeeAssessment).join(CourseEnrollment).where(CourseEnrollment.organization_id == user.organization_id, ExamFeeAssessment.assessment_status == "CONFIRMED", ExamFeeAssessment.finance_reference.is_(None))).all(); refunds = db.scalars(select(RefundRequest).where(RefundRequest.organization_id == user.organization_id, RefundRequest.request_status.in_(["APPROVED", "PAYMENT_PENDING", "PARTIALLY_PAID"]))).all(); stale = db.scalars(select(RefundCalculationSnapshot).join(RefundRequest).where(RefundRequest.organization_id == user.organization_id, RefundCalculationSnapshot.stale.is_(True))).all(); agency_receivables = db.scalars(select(Receivable).where(Receivable.organization_id == user.organization_id, Receivable.economic_nature == "AGENCY_COLLECTION", Receivable.receivable_status.in_(["PARTIALLY_PAID", "PAID"]))).all()
    return {"unallocated_payments": [{"payment_id": row.id, "payment_no": row.payment_no, "amount_cent": row.received_amount_cent - active_allocated(db, payment_id=row.id)} for row in payments if row.received_amount_cent > active_allocated(db, payment_id=row.id)], "exam_assessments_not_handed_off": [{"assessment_id": row.id, "assessment_no": row.assessment_no} for row in assessments], "agency_collections_without_payable": [{"receivable_id": row.id, "receivable_no": row.receivable_no} for row in agency_receivables if not db.scalar(select(AgencyPayable.id).where(AgencyPayable.source_receivable_id == row.id))], "approved_refunds_unpaid": [{"refund_request_id": row.id, "refund_request_no": row.refund_request_no, "unpaid_amount_cent": (row.approved_refund_amount_cent or 0) - confirmed_refund_paid(db, row.id)} for row in refunds], "stale_refund_snapshots": [{"snapshot_id": row.id, "refund_request_id": row.refund_request_id} for row in stale], "calculated_at": utc_now()}
