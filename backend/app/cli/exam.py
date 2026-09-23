import argparse

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import CourseEnrollment
from app.modules.exam.router import recompute


def main() -> None:
    parser = argparse.ArgumentParser(description="Verify course enrollment exam-status projections")
    parser.add_argument("command", choices=["verify"])
    parser.add_argument("--repair", action="store_true")
    args = parser.parse_args()
    mismatches: list[tuple[str, str, str]] = []
    with Session(get_engine()) as db:
        for enrollment in db.scalars(select(CourseEnrollment)).all():
            before = enrollment.exam_status
            calculated = recompute(db, enrollment)
            if before != calculated:
                mismatches.append((enrollment.enrollment_no, before, calculated))
        if args.repair:
            db.commit()
        else:
            db.rollback()
    for enrollment_no, before, calculated in mismatches:
        print(f"{enrollment_no}: stored={before} calculated={calculated}")
    print(f"Exam projection mismatches: {len(mismatches)}; repaired={args.repair}")


if __name__ == "__main__":
    main()
