# ruff: noqa: E501, E702
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import (
    CourseCatalog,
    CourseOfferingVersion,
    CourseSubjectVersion,
    CurriculumVersion,
    ExamSchemeVersion,
    FeePolicyVersion,
    Organization,
    RefundPolicyVersion,
    utc_now,
)


def seed_course(db: Session, organization: Organization, code: str, name: str) -> None:
    if db.scalar(
        select(CourseCatalog).where(
            CourseCatalog.organization_id == organization.id, CourseCatalog.course_code == code
        )
    ):
        return
    curriculum = CurriculumVersion(
        version_no=f"DEMO-{code}-CUR-1",
        name=f"{name}课程方案",
        total_minutes=240,
        status="PUBLISHED",
    )
    exam = ExamSchemeVersion(
        version_no=f"DEMO-{code}-EXAM-1", name=f"{name}考试方案", status="PUBLISHED"
    )
    fee = FeePolicyVersion(
        version_no=f"DEMO-{code}-FEE-1",
        name=f"{name}收费规则",
        tuition_amount_cent=100000,
        status="PUBLISHED",
    )
    refund = RefundPolicyVersion(
        version_no=f"DEMO-{code}-REF-1", name=f"{name}退费规则", status="PUBLISHED"
    )
    db.add_all([curriculum, exam, fee, refund])
    db.flush()
    db.add_all(
        [
            CourseSubjectVersion(
                exam_scheme_version_id=exam.id,
                subject_code="DEMO-S1",
                subject_name="演示科目一",
                display_order=1,
            ),
            CourseSubjectVersion(
                exam_scheme_version_id=exam.id,
                subject_code="DEMO-S2",
                subject_name="演示科目二",
                display_order=2,
            ),
        ]
    )
    course = CourseCatalog(organization_id=organization.id, course_code=code, course_name=name)
    db.add(course)
    db.flush()
    db.add(
        CourseOfferingVersion(
            course_catalog_id=course.id,
            version_no="V1",
            version_name="演示第一版",
            status="PUBLISHED",
            curriculum_version_id=curriculum.id,
            exam_scheme_version_id=exam.id,
            fee_policy_version_id=fee.id,
            refund_policy_version_id=refund.id,
            published_at=utc_now(),
        )
    )


def main() -> None:
    with Session(get_engine()) as db:
        organization = db.scalar(select(Organization).limit(1))
        if organization is None:
            raise SystemExit("Run alembic upgrade head first")
        seed_course(db, organization, "AI_TRAINER", "人工智能训练师")
        seed_course(db, organization, "MEDIA_OPERATION", "全媒体运营")
        db.commit()
    print("Demo courses seeded")


if __name__ == "__main__":
    main()
