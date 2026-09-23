# ruff: noqa: E501, E702, I001
# fmt: off
from datetime import date, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import ClassCycle, ClassSession, CourseEnrollment, Organization, SessionTeacherAssignment, TeacherProfile, User
from app.modules.finance.router import round_ratio


def login(client):  # noqa: ANN001
    assert client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"}).status_code == 200


def csrf(client):  # noqa: ANN001
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def enrollment(client):  # noqa: ANN001
    course = client.post("/api/courses", headers=csrf(client), json={"course_code": "FIN", "course_name": "资金闭环测试"}).json()
    version = client.post(
        f"/api/courses/{course['id']}/versions",
        headers=csrf(client),
        json={
            "version_no": "V1", "version_name": "第一版",
            "curriculum": {"version_no": "FIN-C", "name": "6000分钟课程", "total_minutes": 6000},
            "exam_scheme": {"version_no": "FIN-E", "name": "考试", "subjects": [{"subject_code": "S1", "subject_name": "科目"}]},
            "fee_policy": {"version_no": "FIN-F", "name": "收费", "tuition_amount_cent": 100000, "initial_exam_fee_cent": 5000},
            "refund_policy": {"version_no": "FIN-R", "name": "按分钟退费"},
        },
    ).json()
    offering = client.post(f"/api/course-versions/{version['id']}/publish", headers=csrf(client)).json()
    student = client.post("/api/students", headers=csrf(client), json={"full_name": "财务测试学员"}).json()
    enrolled = client.post("/api/enrollments", headers=csrf(client), json={"student_id": student["id"], "course_offering_version_id": offering["id"], "idempotency_key": "finance-enrollment"}).json()
    return student, enrolled


def create_confirm_payment(client, student_id: str, amount: int, key: str) -> dict:  # noqa: ANN001
    payment = client.post("/api/payments", headers=csrf(client), json={"student_id": student_id, "received_amount_cent": amount, "payment_method": "BANK_TRANSFER", "received_at": "2026-09-23T08:00:00Z", "idempotency_key": key})
    assert payment.status_code == 200, payment.text
    confirmed = client.post(f"/api/payments/{payment.json()['id']}/confirm", headers=csrf(client), json={"version": payment.json()["version"]})
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def test_integer_rounding_boundaries():
    assert round_ratio(1, 3, "FLOOR") == 0
    assert round_ratio(1, 3, "CEILING") == 1
    assert round_ratio(1, 2, "HALF_UP") == 1
    assert round_ratio(499, 1000, "HALF_UP") == 0
    assert round_ratio(500, 1000, "HALF_UP") == 1


def test_tuition_payment_allocation_and_overpayment_guards(client):  # noqa: ANN001
    login(client); student, enrolled = enrollment(client)
    first = client.post(f"/api/enrollments/{enrolled['id']}/tuition-receivable", headers=csrf(client), json={})
    assert first.status_code == 200, first.text
    duplicate = client.post(f"/api/enrollments/{enrolled['id']}/tuition-receivable", headers=csrf(client), json={})
    assert duplicate.json()["id"] == first.json()["id"]
    confirmed = client.post(f"/api/receivables/{first.json()['id']}/confirm", headers=csrf(client), json={"version": first.json()["version"]}).json()
    payment1 = create_confirm_payment(client, student["id"], 60000, "payment-one")
    allocation1 = client.post(f"/api/payments/{payment1['id']}/allocate", headers=csrf(client), json={"version": payment1["version"], "receivable_id": confirmed["id"], "allocated_amount_cent": 60000, "idempotency_key": "allocation-one"})
    assert allocation1.status_code == 200, allocation1.text
    assert allocation1.json()["receivable"]["receivable_status"] == "PARTIALLY_PAID"
    payment2 = create_confirm_payment(client, student["id"], 45000, "payment-two")
    allocation2 = client.post(f"/api/payments/{payment2['id']}/allocate", headers=csrf(client), json={"version": payment2["version"], "receivable_id": confirmed["id"], "allocated_amount_cent": 40000, "idempotency_key": "allocation-two"})
    assert allocation2.status_code == 200, allocation2.text
    assert allocation2.json()["receivable"]["receivable_status"] == "PAID"
    assert allocation2.json()["payment"]["unallocated_amount_cent"] == 5000
    too_much = client.post(f"/api/payments/{payment2['id']}/allocate", headers=csrf(client), json={"version": allocation2.json()["payment"]["version"], "receivable_id": confirmed["id"], "allocated_amount_cent": 1, "idempotency_key": "allocation-too-much"})
    assert too_much.status_code == 409
    overview = client.get(f"/api/students/{student['id']}/financial-overview").json()
    assert overview["summary"]["school_revenue_payable_cent"] == 100000
    assert overview["summary"]["allocated_cent"] == 100000
    assert overview["summary"]["unallocated_payment_cent"] == 5000


def test_refund_snapshot_uses_integer_formula_and_is_immutable(client):  # noqa: ANN001
    login(client); student, enrolled = enrollment(client)
    receivable = client.post(f"/api/enrollments/{enrolled['id']}/tuition-receivable", headers=csrf(client), json={}).json()
    receivable = client.post(f"/api/receivables/{receivable['id']}/confirm", headers=csrf(client), json={"version": receivable["version"]}).json()
    payment = create_confirm_payment(client, student["id"], 100000, "refund-source-payment")
    assert client.post(f"/api/payments/{payment['id']}/allocate", headers=csrf(client), json={"version": payment["version"], "receivable_id": receivable["id"], "allocated_amount_cent": 100000, "idempotency_key": "refund-source-allocation"}).status_code == 200
    request = client.post("/api/refund-requests", headers=csrf(client), json={"course_enrollment_id": enrolled["id"], "refund_reason": "未开课退费"})
    assert request.status_code == 200, request.text
    calculated = client.post(f"/api/refund-requests/{request.json()['id']}/calculate", headers=csrf(client), json={"version": request.json()["version"]})
    assert calculated.status_code == 200, calculated.text
    assert calculated.json()["calculated_refundable_amount_cent"] == 100000
    assert calculated.json()["snapshots"][0]["consumed_amount_numerator"] == 0
    recalculated = client.post(f"/api/refund-requests/{request.json()['id']}/recalculate", headers=csrf(client), json={"version": calculated.json()["version"]}).json()
    assert len(recalculated["snapshots"]) == 2
    assert {row["calculation_version_no"] for row in recalculated["snapshots"]} == {1, 2}


def test_reader_cannot_access_finance(client):  # noqa: ANN001
    login(client); client.post("/api/auth/logout", headers=csrf(client)); login_response = client.post("/api/auth/login", json={"username": "reader", "password": "correct-password"}); assert login_response.status_code == 200
    assert client.get("/api/receivables").status_code == 403


def test_teacher_settlement_uses_each_confirmed_assignment_once(client, seeded_db):  # noqa: ANN001
    login(client); _student, enrolled = enrollment(client)
    with Session(seeded_db) as db:
        enrollment_row = db.get(CourseEnrollment, enrolled["id"]); admin = db.scalar(select(User).where(User.username == "admin")); org = db.scalar(select(Organization))
        cycle = ClassCycle(organization_id=org.id, class_code="FIN-CLASS", class_name="结算班", course_offering_version_id=enrollment_row.course_offering_version_id, class_status="OPEN", created_by=admin.id)
        teacher_a = TeacherProfile(teacher_no="T-FIN-A", full_name="教师甲", created_by=admin.id)
        teacher_b = TeacherProfile(teacher_no="T-FIN-B", full_name="教师乙", created_by=admin.id)
        db.add_all([cycle, teacher_a, teacher_b]); db.flush()
        start = datetime(2026, 9, 1, 8, 0); session = ClassSession(class_cycle_id=cycle.id, session_no="S-001", session_title="共同授课", service_date=date(2026, 9, 1), planned_start_at=start, planned_end_at=start + timedelta(minutes=120), planned_minutes=120, actual_minutes=120, session_status="COMPLETED", completed_at=start + timedelta(minutes=120), created_by=admin.id)
        db.add(session); db.flush()
        db.add_all([
            SessionTeacherAssignment(class_session_id=session.id, teacher_id=teacher_a.id, teaching_role="LEAD", planned_minutes=120, actual_minutes=120, settleable_minutes=120, rate_amount_cent=6000, rate_unit_minutes=60, confirmation_status="CONFIRMED", confirmed_at=start, confirmed_by=admin.id, created_by=admin.id),
            SessionTeacherAssignment(class_session_id=session.id, teacher_id=teacher_b.id, teaching_role="ASSISTANT", planned_minutes=120, actual_minutes=120, settleable_minutes=120, rate_amount_cent=3000, rate_unit_minutes=60, confirmation_status="CONFIRMED", confirmed_at=start, confirmed_by=admin.id, created_by=admin.id),
        ]); db.commit()
    preview = client.post("/api/teacher-settlement-batches/preview", headers=csrf(client), json={"period_start":"2026-09-01", "period_end":"2026-09-30"})
    assert preview.status_code == 200, preview.text
    assert preview.json()["total_minutes"] == 240
    assert preview.json()["total_amount_cent"] == 18000
    batch = client.post("/api/teacher-settlement-batches", headers=csrf(client), json={"period_start":"2026-09-01", "period_end":"2026-09-30"}).json()
    calculated = client.post(f"/api/teacher-settlement-batches/{batch['id']}/calculate", headers=csrf(client), json={"version":batch["version"]})
    assert calculated.status_code == 200, calculated.text
    assert len(calculated.json()["lines"]) == 2
    assert client.post("/api/teacher-settlement-batches/preview", headers=csrf(client), json={"period_start":"2026-09-01", "period_end":"2026-09-30"}).json()["items"] == []
