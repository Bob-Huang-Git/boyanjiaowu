# ruff: noqa: E501
from io import BytesIO

from openpyxl import Workbook
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import AuditLog, Student, StudentIdentityDocument
from app.modules.sprint1.router import IMPORT_HEADERS


def login(client, username: str = "admin") -> None:  # noqa: ANN001
    response = client.post(
        "/api/auth/login", json={"username": username, "password": "correct-password"}
    )
    assert response.status_code == 200


def csrf(client) -> dict[str, str]:  # noqa: ANN001
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def published_offering(client, course_code: str, course_name: str) -> dict:  # noqa: ANN001
    course = client.post(
        "/api/courses",
        headers=csrf(client),
        json={"course_code": course_code, "course_name": course_name},
    )
    assert course.status_code == 200
    version = client.post(
        f"/api/courses/{course.json()['id']}/versions",
        headers=csrf(client),
        json={
            "version_no": "V1",
            "version_name": "第一版",
            "curriculum": {
                "version_no": f"{course_code}-C1",
                "name": "课程方案",
                "total_minutes": 240,
            },
            "exam_scheme": {
                "version_no": f"{course_code}-E1",
                "name": "考试方案",
                "subjects": [
                    {"subject_code": "S1", "subject_name": "科目一"},
                    {"subject_code": "S2", "subject_name": "科目二"},
                ],
            },
            "fee_policy": {
                "version_no": f"{course_code}-F1",
                "name": "收费规则",
                "tuition_amount_cent": 10000,
            },
            "refund_policy": {"version_no": f"{course_code}-R1", "name": "退费规则"},
        },
    )
    assert version.status_code == 200, version.text
    published = client.post(
        f"/api/course-versions/{version.json()['id']}/publish", headers=csrf(client)
    )
    assert published.status_code == 200, published.text
    return published.json()


def test_student_course_enrollment_class_and_sensitive_data(client, seeded_db):  # noqa: ANN001
    login(client)
    ai = published_offering(client, "AI", "人工智能训练师")
    media = published_offering(client, "MEDIA", "全媒体运营")
    created = client.post(
        "/api/students",
        headers=csrf(client),
        json={
            "full_name": "测试学员甲",
            "birth_date": "1990-01-02",
            "phone": "13800138000",
            "identity_document": {"document_type": "PRC_ID", "document_number": "TESTID1234X"},
        },
    )
    assert created.status_code == 200, created.text
    student = created.json()
    assert student["student_no"].startswith("STU")
    assert student["phone_masked"] == "138****8000"
    assert "document_number" not in student
    duplicate = client.post(
        "/api/students",
        headers=csrf(client),
        json={
            "full_name": "另一人",
            "identity_document": {"document_type": "PRC_ID", "document_number": "TESTID1234X"},
        },
    )
    assert duplicate.status_code == 409
    first = client.post(
        "/api/enrollments",
        headers=csrf(client),
        json={
            "student_id": student["id"],
            "course_offering_version_id": ai["id"],
            "idempotency_key": "enroll-ai-0001",
        },
    )
    second = client.post(
        "/api/enrollments",
        headers=csrf(client),
        json={
            "student_id": student["id"],
            "course_offering_version_id": media["id"],
            "idempotency_key": "enroll-media-01",
        },
    )
    assert first.status_code == second.status_code == 200
    assert (
        client.post(
            "/api/enrollments",
            headers=csrf(client),
            json={
                "student_id": student["id"],
                "course_offering_version_id": ai["id"],
                "idempotency_key": "enroll-ai-0001",
            },
        ).json()["id"]
        == first.json()["id"]
    )
    cycle = client.post(
        "/api/classes",
        headers=csrf(client),
        json={
            "class_code": "AI-001",
            "class_name": "AI 第一期",
            "course_offering_version_id": ai["id"],
            "capacity": 1,
            "class_status": "OPEN",
        },
    )
    assert cycle.status_code == 200
    mismatch = client.post(
        f"/api/classes/{cycle.json()['id']}/members",
        headers=csrf(client),
        json={"course_enrollment_id": second.json()["id"], "idempotency_key": "member-0001"},
    )
    assert mismatch.status_code == 422
    member = client.post(
        f"/api/classes/{cycle.json()['id']}/members",
        headers=csrf(client),
        json={"course_enrollment_id": first.json()["id"], "idempotency_key": "member-0002"},
    )
    assert member.status_code == 200
    assert client.get(f"/api/students/{student['id']}/enrollments").json()["items"].__len__() == 2
    with Session(seeded_db) as db:
        saved = db.get(Student, student["id"])
        document = db.scalar(
            select(StudentIdentityDocument).where(
                StudentIdentityDocument.student_id == student["id"]
            )
        )
        assert "13800138000" not in saved.phone_ciphertext
        assert "TESTID1234X" not in document.document_number_ciphertext
    document_id = document.id
    client.post("/api/auth/logout", headers=csrf(client))
    login(client, "reader")
    denied = client.post(
        f"/api/students/{student['id']}/identity-documents/{document_id}/reveal",
        headers=csrf(client),
        json={"reason": "核验"},
    )
    assert denied.status_code == 403
    client.post("/api/auth/logout", headers=csrf(client))
    login(client)
    revealed = client.post(
        f"/api/students/{student['id']}/identity-documents/{document_id}/reveal",
        headers=csrf(client),
        json={"reason": "业务核验"},
    )
    assert revealed.json()["document_number"] == "TESTID1234X"
    with Session(seeded_db) as db:
        assert db.scalar(select(AuditLog).where(AuditLog.action == "student.sensitive.reveal"))


def test_import_preview_does_not_create_students_and_confirm_is_idempotent(client):  # noqa: ANN001
    login(client)
    workbook = Workbook()
    sheet = workbook.active
    sheet.append(IMPORT_HEADERS)
    sheet.append(["导入测试乙", "PRC_ID", "IMPORT-001", "13900139000", "UNKNOWN", "1991-02-03"])
    content = BytesIO()
    workbook.save(content)
    before = client.get("/api/students").json()["total"]
    preview = client.post(
        "/api/imports/students/preview",
        headers=csrf(client),
        files={
            "file": (
                "students.xlsx",
                content.getvalue(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    assert client.get("/api/students").json()["total"] == before
    batch_id = preview.json()["id"]
    confirmed = client.post(
        f"/api/imports/students/{batch_id}/confirm",
        headers=csrf(client),
        json={"idempotency_key": "confirm-import-0001"},
    )
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["items"][0]["status"] == "SUCCESS"
    repeated = client.post(
        f"/api/imports/students/{batch_id}/confirm",
        headers=csrf(client),
        json={"idempotency_key": "confirm-import-0001"},
    )
    assert repeated.status_code == 200
    assert client.get("/api/students").json()["total"] == before + 1
