# ruff: noqa: E501, E702
# fmt: off
"""Idempotent development finance seed. Run after the regular demo and enrollment seed."""

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import (
    CourseEnrollment,
    FeePolicyVersion,
    Payment,
    PaymentAllocation,
    Receivable,
    User,
    new_id,
    utc_now,
)


def main() -> None:
    with Session(get_engine()) as db:
        enrollment = db.scalar(select(CourseEnrollment).order_by(CourseEnrollment.created_at))
        if not enrollment:
            print("No enrollment found; create demo enrollment first")
            return
        user = db.get(User, enrollment.created_by) if enrollment.created_by else db.scalar(select(User).where(User.organization_id == enrollment.organization_id))
        if not user:
            print("No organization user found; run bootstrap first")
            return
        policy = db.get(FeePolicyVersion, enrollment.fee_policy_version_id)
        receivable = db.scalar(select(Receivable).where(Receivable.source_type == "ENROLLMENT_FEE_POLICY", Receivable.source_id == enrollment.id))
        if not receivable:
            receivable = Receivable(organization_id=enrollment.organization_id, receivable_no=f"DEMO-AR-{enrollment.enrollment_no}", course_enrollment_id=enrollment.id, student_id=enrollment.student_id, receivable_type="TUITION", economic_nature="SCHOOL_REVENUE", source_type="ENROLLMENT_FEE_POLICY", source_id=enrollment.id, fee_policy_version_id=policy.id, original_amount_cent=policy.tuition_amount_cent, adjusted_amount_cent=0, payable_amount_cent=policy.tuition_amount_cent, receivable_status="CONFIRMED", confirmed_at=utc_now(), confirmed_by=user.id, description="Sprint 5 演示培训费", created_by=user.id)
            db.add(receivable); db.flush()
        first_amount = min(60000, receivable.payable_amount_cent)
        second_amount = max(0, receivable.payable_amount_cent - first_amount)
        for index, amount in enumerate((first_amount, second_amount), start=1):
            if amount <= 0:
                continue
            key = f"sprint5-demo-payment-{enrollment.id}-{index}"
            payment = db.scalar(select(Payment).where(Payment.idempotency_key == key))
            if not payment:
                payment = Payment(organization_id=enrollment.organization_id, payment_no=f"DEMO-PM-{enrollment.enrollment_no}-{index}", student_id=enrollment.student_id, payer_name="演示付款人", received_amount_cent=amount, payment_method="BANK_TRANSFER", received_at=utc_now(), payment_status="FULLY_ALLOCATED", idempotency_key=key, remarks="仅用于开发环境", confirmed_at=utc_now(), confirmed_by=user.id, created_by=user.id)
                db.add(payment); db.flush()
            allocation_key = f"sprint5-demo-allocation-{enrollment.id}-{index}"
            if not db.scalar(select(PaymentAllocation).where(PaymentAllocation.idempotency_key == allocation_key)):
                db.add(PaymentAllocation(id=new_id(), payment_id=payment.id, receivable_id=receivable.id, allocated_amount_cent=amount, allocation_status="ACTIVE", idempotency_key=allocation_key, allocated_at=utc_now(), allocated_by=user.id, remarks="仅用于开发环境"))
        receivable.receivable_status = "PAID"; enrollment.financial_status = "PAID"; db.commit()
    print("Sprint 5 finance demo seed synchronized")


if __name__ == "__main__":
    main()
