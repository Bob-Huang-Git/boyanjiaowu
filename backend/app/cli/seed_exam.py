# ruff: noqa: E501
import uuid
from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import (
    CertificateCase,
    CertificateDeliveryEvent,
    CourseCatalog,
    CourseEnrollment,
    CourseOfferingVersion,
    CourseSubjectVersion,
    ExamAttempt,
    ExamBatch,
    ExamBatchSubject,
    ExamFeeAssessment,
    ExamRegistration,
    ExamRegistrationSubject,
    Organization,
    Student,
    User,
    utc_now,
)
from app.core.pii import encrypt


def code(prefix: str) -> str:
    return f"{prefix}{uuid.uuid4().hex[:12].upper()}"


def seed_certificate(
    db: Session,
    enrollment: CourseEnrollment,
    user: User,
    target: str,
) -> None:
    case = CertificateCase(
        certificate_case_no=code("CERT"),
        course_enrollment_id=enrollment.id,
        certificate_status="ELIGIBLE",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(case)
    db.flush()
    path = ["APPLYING", "ISSUED", "RECEIVED_BY_SCHOOL", "READY_FOR_DELIVERY", "DELIVERED"]
    previous = "ELIGIBLE"
    for status in path:
        if status == "ISSUED":
            case.certificate_no_ciphertext = encrypt(f"DEMO-CERT-{enrollment.enrollment_no}")
            case.certificate_no_last4 = enrollment.enrollment_no[-4:]
            case.issuing_authority = "演示考试机构"
            case.issued_at = utc_now()
        elif status == "APPLYING":
            case.application_submitted_at = utc_now()
        elif status == "RECEIVED_BY_SCHOOL":
            case.school_received_at = utc_now()
        elif status == "READY_FOR_DELIVERY":
            case.ready_at = utc_now()
        elif status == "DELIVERED":
            case.delivered_at = utc_now()
            case.delivery_method = "PICKUP"
            case.recipient_name = "演示学员"
        case.certificate_status = status
        db.add(
            CertificateDeliveryEvent(
                certificate_case_id=case.id,
                event_type=status,
                from_status=previous,
                to_status=status,
                operator_id=user.id,
                remarks="Sprint 4 安全演示数据",
            )
        )
        previous = status
        if status == target:
            break


def register_results(
    db: Session,
    enrollment: CourseEnrollment,
    batch: ExamBatch,
    results: list[tuple[CourseSubjectVersion, str, int]],
    user: User,
) -> None:
    registration = ExamRegistration(
        registration_no=code("ER"),
        course_enrollment_id=enrollment.id,
        exam_batch_id=batch.id,
        registration_status="COMPLETED",
        registration_source="INITIAL",
        idempotency_key=f"demo-{enrollment.enrollment_no}-{batch.batch_code}",
        registered_at=utc_now(),
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(registration)
    db.flush()
    types: set[str] = set()
    for subject, result_status, score in results:
        attempt_no = (
            len(
                db.scalars(
                    select(ExamAttempt).where(
                        ExamAttempt.course_enrollment_id == enrollment.id,
                        ExamAttempt.course_subject_version_id == subject.id,
                    )
                ).all()
            )
            + 1
        )
        attempt_type = "INITIAL" if attempt_no == 1 else "RESIT"
        types.add(attempt_type)
        batch_subject = db.scalar(
            select(ExamBatchSubject).where(
                ExamBatchSubject.exam_batch_id == batch.id,
                ExamBatchSubject.course_subject_version_id == subject.id,
            )
        )
        row = ExamRegistrationSubject(
            exam_registration_id=registration.id,
            exam_batch_subject_id=batch_subject.id,
            course_subject_version_id=subject.id,
            attempt_type=attempt_type,
            planned_attempt_no=attempt_no,
            subject_registration_status="COMPLETED",
            created_by=user.id,
        )
        db.add(row)
        db.flush()
        attempt = ExamAttempt(
            course_enrollment_id=enrollment.id,
            course_subject_version_id=subject.id,
            exam_registration_subject_id=row.id,
            attempt_no=attempt_no,
            attempt_type=attempt_type,
            attendance_status="PRESENT",
            score_value_scaled=score * 100,
            score_scale=100,
            result_status=result_status,
            result_confirm_status="OFFICIALLY_CONFIRMED",
            result_source="MANUAL",
            confirmed_at=utc_now(),
            confirmed_by=user.id,
            created_by=user.id,
            updated_by=user.id,
        )
        db.add(attempt)
        db.flush()
        amount = 2500 if attempt_type == "INITIAL" else 1200
        db.add(
            ExamFeeAssessment(
                assessment_no=code("EFA"),
                course_enrollment_id=enrollment.id,
                exam_attempt_id=attempt.id,
                exam_registration_subject_id=row.id,
                course_subject_version_id=subject.id,
                fee_policy_version_id=enrollment.fee_policy_version_id,
                fee_type="INITIAL_EXAM" if attempt_type == "INITIAL" else "RESIT",
                responsibility="SCHOOL" if attempt_type == "INITIAL" else "STUDENT",
                amount_cent=amount,
                assessment_status="CONFIRMED",
                policy_snapshot_description="Sprint 4 演示费用快照",
                confirmed_at=utc_now(),
                confirmed_by=user.id,
                created_by=user.id,
                updated_by=user.id,
            )
        )
    registration.registration_source = "MIXED" if len(types) > 1 else next(iter(types))


def create_enrollment(
    db: Session,
    organization: Organization,
    offering: CourseOfferingVersion,
    user: User,
    suffix: str,
    name: str,
) -> CourseEnrollment | None:
    student_no = f"DEMO-EX-{suffix}"
    if db.scalar(
        select(Student).where(
            Student.organization_id == organization.id,
            Student.student_no == student_no,
        )
    ):
        return None
    student = Student(
        organization_id=organization.id,
        student_no=student_no,
        full_name=name,
        remarks="Sprint 4 虚构演示学员",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(student)
    db.flush()
    enrollment = CourseEnrollment(
        organization_id=organization.id,
        enrollment_no=f"ENR-EX-{suffix}",
        student_id=student.id,
        course_offering_version_id=offering.id,
        curriculum_version_id=offering.curriculum_version_id,
        exam_scheme_version_id=offering.exam_scheme_version_id,
        fee_policy_version_id=offering.fee_policy_version_id,
        refund_policy_version_id=offering.refund_policy_version_id,
        idempotency_key=f"demo-exam-enrollment-{suffix}",
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(enrollment)
    db.flush()
    return enrollment


def main() -> None:
    with Session(get_engine()) as db:
        organization = db.scalar(select(Organization).limit(1))
        user = db.scalar(select(User).limit(1))
        course = (
            db.scalar(
                select(CourseCatalog).where(
                    CourseCatalog.organization_id == organization.id,
                    CourseCatalog.course_code == "AI_TRAINER",
                )
            )
            if organization
            else None
        )
        if not organization or not user or not course:
            raise SystemExit("Run bootstrap and seed_demo before seed_exam")
        offering = db.scalar(
            select(CourseOfferingVersion).where(
                CourseOfferingVersion.course_catalog_id == course.id,
                CourseOfferingVersion.status == "PUBLISHED",
            )
        )
        subjects = db.scalars(
            select(CourseSubjectVersion)
            .where(CourseSubjectVersion.exam_scheme_version_id == offering.exam_scheme_version_id)
            .order_by(CourseSubjectVersion.display_order)
        ).all()
        for subject in subjects:
            subject.passing_score = 60
        batches: list[ExamBatch] = []
        for index in range(1, 4):
            batch_code = f"DEMO-EXAM-B{index}"
            batch = db.scalar(select(ExamBatch).where(ExamBatch.batch_code == batch_code))
            if not batch:
                exam_date = date.today() + timedelta(days=index * 7)
                batch = ExamBatch(
                    organization_id=organization.id,
                    batch_code=batch_code,
                    batch_name=f"演示考试第 {index} 批",
                    exam_scheme_version_id=offering.exam_scheme_version_id,
                    exam_start_date=exam_date,
                    exam_end_date=exam_date,
                    batch_status="COMPLETED",
                    organizing_institution="演示考试机构",
                    created_by=user.id,
                    updated_by=user.id,
                )
                db.add(batch)
                db.flush()
                for subject in subjects:
                    db.add(
                        ExamBatchSubject(
                            exam_batch_id=batch.id,
                            course_subject_version_id=subject.id,
                            exam_start_at=utc_now() + timedelta(days=index * 7),
                            initial_exam_fee_amount_cent=2500,
                            resit_fee_amount_cent=1200,
                            subject_status="COMPLETED",
                        )
                    )
                db.flush()
            batches.append(batch)

        first = create_enrollment(db, organization, offering, user, "01", "演示·首次双科通过")
        if first:
            register_results(
                db,
                first,
                batches[0],
                [(subjects[0], "PASSED", 82), (subjects[1], "PASSED", 79)],
                user,
            )
            first.exam_status = "PASSED"
            first.certificate_status = "ELIGIBLE"
            seed_certificate(db, first, user, "APPLYING")
        third = create_enrollment(db, organization, offering, user, "02", "演示·第三次补考通过")
        if third:
            register_results(
                db,
                third,
                batches[0],
                [(subjects[0], "PASSED", 86), (subjects[1], "FAILED", 48)],
                user,
            )
            register_results(db, third, batches[1], [(subjects[1], "FAILED", 55)], user)
            register_results(db, third, batches[2], [(subjects[1], "PASSED", 74)], user)
            third.exam_status = "PASSED"
            third.certificate_status = "ELIGIBLE"
            seed_certificate(db, third, user, "RECEIVED_BY_SCHOOL")
        pending = create_enrollment(db, organization, offering, user, "03", "演示·仍待补考")
        if pending:
            register_results(
                db,
                pending,
                batches[0],
                [(subjects[0], "PASSED", 76), (subjects[1], "FAILED", 51)],
                user,
            )
            pending.exam_status = "PARTIALLY_PASSED"
        delivered = create_enrollment(db, organization, offering, user, "04", "演示·证书已发放")
        if delivered:
            register_results(
                db,
                delivered,
                batches[0],
                [(subjects[0], "PASSED", 90), (subjects[1], "PASSED", 88)],
                user,
            )
            delivered.exam_status = "PASSED"
            delivered.certificate_status = "DELIVERED"
            seed_certificate(db, delivered, user, "DELIVERED")
        db.commit()
    print("Sprint 4 exam demo data seeded")


if __name__ == "__main__":
    main()
