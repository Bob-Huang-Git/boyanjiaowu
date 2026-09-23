# ruff: noqa: E501, E702
from datetime import UTC, date, datetime, timedelta
from io import BytesIO

from openpyxl import Workbook

from app.modules.attachments.storage import LocalStorageBackend

PNG = b"\x89PNG\r\n\x1a\n" + b"exam-evidence"


def login(client):  # noqa: ANN001
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "correct-password"}
        ).status_code
        == 200
    )


def csrf(client):  # noqa: ANN001
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def offering(client):  # noqa: ANN001
    course = client.post(
        "/api/courses",
        headers=csrf(client),
        json={"course_code": "EXAM", "course_name": "考试测试"},
    ).json()
    version = client.post(
        f"/api/courses/{course['id']}/versions",
        headers=csrf(client),
        json={
            "version_no": "V1",
            "version_name": "第一版",
            "curriculum": {"version_no": "EC", "name": "课程", "total_minutes": 240},
            "exam_scheme": {
                "version_no": "EE",
                "name": "考试",
                "subjects": [
                    {"subject_code": "A", "subject_name": "科目A", "passing_score": 60},
                    {"subject_code": "B", "subject_name": "科目B", "passing_score": 60},
                ],
            },
            "fee_policy": {
                "version_no": "EF",
                "name": "收费",
                "tuition_amount_cent": 10000,
                "initial_exam_fee_cent": 5000,
            },
            "refund_policy": {"version_no": "ER", "name": "退费"},
        },
    ).json()
    return client.post(f"/api/course-versions/{version['id']}/publish", headers=csrf(client)).json()


def make_batch(client, scheme_id, code, subjects):  # noqa: ANN001
    batch = client.post(
        "/api/exam-batches",
        headers=csrf(client),
        json={
            "batch_code": code,
            "batch_name": code,
            "exam_scheme_version_id": scheme_id,
            "exam_start_date": str(date.today()),
            "exam_end_date": str(date.today()),
        },
    ).json()
    ids = []
    for subject in subjects:
        response = client.post(
            f"/api/exam-batches/{batch['id']}/subjects",
            headers=csrf(client),
            json={
                "course_subject_version_id": subject["id"],
                "exam_start_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
                "initial_exam_fee_amount_cent": 2500,
                "resit_fee_amount_cent": 1200,
            },
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    opened = client.post(
        f"/api/exam-batches/{batch['id']}/open",
        headers=csrf(client),
        json={"version": batch["version"]},
    )
    assert opened.status_code == 200
    return batch["id"], ids


def set_result(client, attempt, status, score):  # noqa: ANN001
    draft = client.patch(
        f"/api/exam-attempts/{attempt['id']}/draft-result",
        headers=csrf(client),
        json={
            "score_value_scaled": score * 100,
            "score_scale": 100,
            "result_status": status,
            "attendance_status": "PRESENT",
            "version": attempt["version"],
        },
    )
    assert draft.status_code == 200, draft.text
    submitted = client.post(
        f"/api/exam-attempts/{attempt['id']}/submit-result",
        headers=csrf(client),
        json={"version": draft.json()["version"]},
    )
    assert submitted.status_code == 200
    confirmed = client.post(
        f"/api/exam-attempts/{attempt['id']}/confirm-result",
        headers=csrf(client),
        json={"version": submitted.json()["version"]},
    )
    assert confirmed.status_code == 200
    return confirmed.json()


def test_exam_resit_fee_and_certificate_flow(client, tmp_path, monkeypatch):  # noqa: ANN001
    import app.modules.exam.router as exam_router

    storage = LocalStorageBackend(str(tmp_path / "attachments"), str(tmp_path / "temp"))
    monkeypatch.setattr(exam_router, "get_storage", lambda: storage)
    login(client)
    off = offering(client)
    student = client.post(
        "/api/students", headers=csrf(client), json={"full_name": "考试学员"}
    ).json()
    enrollment = client.post(
        "/api/enrollments",
        headers=csrf(client),
        json={
            "student_id": student["id"],
            "course_offering_version_id": off["id"],
            "idempotency_key": "exam-enroll-001",
        },
    ).json()
    progress = client.get(f"/api/enrollments/{enrollment['id']}/exam-progress").json()
    subjects = [{"id": x["subject_id"], "code": x["subject_code"]} for x in progress["subjects"]]
    batch_id, batch_subjects = make_batch(
        client, off["exam_scheme_version_id"], "BATCH-1", subjects
    )
    registered = client.post(
        "/api/exam-registrations",
        headers=csrf(client),
        json={
            "course_enrollment_id": enrollment["id"],
            "exam_batch_id": batch_id,
            "exam_batch_subject_ids": batch_subjects,
            "idempotency_key": "exam-reg-0001",
        },
    )
    assert registered.status_code == 201, registered.text
    progress = client.get(f"/api/enrollments/{enrollment['id']}/exam-progress").json()
    set_result(client, progress["subjects"][0]["attempts"][0], "PASSED", 80)
    set_result(client, progress["subjects"][1]["attempts"][0], "FAILED", 50)
    progress = client.get(f"/api/enrollments/{enrollment['id']}/exam-progress").json()
    assert progress["exam_status"] == "PARTIALLY_PASSED"
    batch2, subject2 = make_batch(client, off["exam_scheme_version_id"], "BATCH-2", [subjects[1]])
    resit = client.post(
        "/api/exam-registrations",
        headers=csrf(client),
        json={
            "course_enrollment_id": enrollment["id"],
            "exam_batch_id": batch2,
            "exam_batch_subject_ids": subject2,
            "idempotency_key": "exam-reg-0002",
        },
    )
    assert resit.status_code == 201, resit.text
    progress = client.get(f"/api/enrollments/{enrollment['id']}/exam-progress").json()
    attempt = progress["subjects"][1]["attempts"][1]
    assert attempt["attempt_type"] == "RESIT"
    set_result(client, attempt, "PASSED", 75)
    eligible = client.get(f"/api/enrollments/{enrollment['id']}/certificate-eligibility").json()
    assert eligible["eligible"] is True
    certificate = client.post(
        f"/api/enrollments/{enrollment['id']}/certificate-case", headers=csrf(client)
    ).json()
    applying = client.post(
        f"/api/certificates/{certificate['id']}/start-application",
        headers=csrf(client),
        json={"version": 1},
    )
    assert applying.status_code == 200
    issued = client.post(
        f"/api/certificates/{certificate['id']}/mark-issued",
        headers=csrf(client),
        json={"version": 2, "certificate_no": "CERT-TEST-1234", "issuing_authority": "测试机构"},
    )
    assert issued.status_code == 200
    uploaded = client.post(
        f"/api/certificates/{certificate['id']}/attachments",
        headers=csrf(client),
        data={"attachment_type": "CERTIFICATE_SCAN"},
        files={"file": ("certificate.png", PNG, "image/png")},
    )
    assert uploaded.status_code == 201, uploaded.text
    attachment_id = uploaded.json()["id"]
    downloaded = client.get(
        f"/api/certificates/{certificate['id']}/attachments/{attachment_id}/download"
    )
    assert downloaded.content == PNG
    detail = client.get(f"/api/certificates/{certificate['id']}").json()
    assert detail["attachments"][0]["original_filename"] == "certificate.png"
    assert "object_key" not in str(detail)
    passed_attempt = client.get(f"/api/enrollments/{enrollment['id']}/exam-progress").json()[
        "subjects"
    ][0]["attempts"][0]
    invalidated = client.post(
        f"/api/exam-attempts/{passed_attempt['id']}/revise-result",
        headers=csrf(client),
        json={
            "score_value_scaled": 5000,
            "score_scale": 100,
            "result_status": "FAILED",
            "attendance_status": "PRESENT",
            "reason": "官方撤销合格结论",
            "version": passed_attempt["version"],
        },
    )
    assert invalidated.status_code == 200
    assert (
        client.get(f"/api/certificates/{certificate['id']}").json()["certificate_status"]
        == "EXCEPTION"
    )
    assert (
        client.get(f"/api/certificates/{certificate['id']}/events").json()["items"][-1][
            "event_type"
        ]
        == "ELIGIBILITY_INVALIDATED"
    )
    fees = client.get("/api/exam-fee-assessments").json()["items"]
    assert len(fees) == 3
    assert any(
        x["fee_type"] == "RESIT" and x["responsibility"] == "STUDENT" and x["amount_cent"] == 1200
        for x in fees
    )
    assert all("paid" not in x for x in fees)


def test_confirmed_result_requires_revision(client):  # noqa: ANN001
    login(client)
    off = offering(client)
    student = client.post(
        "/api/students", headers=csrf(client), json={"full_name": "修订学员"}
    ).json()
    enrollment = client.post(
        "/api/enrollments",
        headers=csrf(client),
        json={
            "student_id": student["id"],
            "course_offering_version_id": off["id"],
            "idempotency_key": "exam-enroll-002",
        },
    ).json()
    subjects = client.get(f"/api/enrollments/{enrollment['id']}/exam-progress").json()["subjects"]
    batch, bs = make_batch(
        client, off["exam_scheme_version_id"], "BATCH-R", [{"id": subjects[0]["subject_id"]}]
    )
    client.post(
        "/api/exam-registrations",
        headers=csrf(client),
        json={
            "course_enrollment_id": enrollment["id"],
            "exam_batch_id": batch,
            "exam_batch_subject_ids": bs,
            "idempotency_key": "exam-reg-revision",
        },
    )
    attempt = client.get(f"/api/enrollments/{enrollment['id']}/exam-progress").json()["subjects"][
        0
    ]["attempts"][0]
    confirmed = set_result(client, attempt, "PASSED", 80)
    blocked = client.patch(
        f"/api/exam-attempts/{attempt['id']}/draft-result",
        headers=csrf(client),
        json={
            "score_value_scaled": 5000,
            "score_scale": 100,
            "result_status": "FAILED",
            "version": confirmed["version"],
        },
    )
    assert blocked.status_code == 409
    revised = client.post(
        f"/api/exam-attempts/{attempt['id']}/revise-result",
        headers=csrf(client),
        json={
            "score_value_scaled": 5000,
            "score_scale": 100,
            "result_status": "FAILED",
            "attendance_status": "PRESENT",
            "reason": "官方更正",
            "version": confirmed["version"],
        },
    )
    assert revised.status_code == 200
    assert (
        client.get(f"/api/exam-attempts/{attempt['id']}/revisions").json()["items"][0]["reason"]
        == "官方更正"
    )


def test_exam_result_import_preview_confirm_and_conflict(client):  # noqa: ANN001
    login(client)
    off = offering(client)
    student = client.post(
        "/api/students", headers=csrf(client), json={"full_name": "导入学员"}
    ).json()
    enrollment = client.post(
        "/api/enrollments",
        headers=csrf(client),
        json={
            "student_id": student["id"],
            "course_offering_version_id": off["id"],
            "idempotency_key": "exam-import-enroll",
        },
    ).json()
    progress = client.get(f"/api/enrollments/{enrollment['id']}/exam-progress").json()
    subject = progress["subjects"][0]
    batch_id, batch_subjects = make_batch(
        client,
        off["exam_scheme_version_id"],
        "IMPORT-BATCH",
        [{"id": subject["subject_id"]}],
    )
    created = client.post(
        "/api/exam-registrations",
        headers=csrf(client),
        json={
            "course_enrollment_id": enrollment["id"],
            "exam_batch_id": batch_id,
            "exam_batch_subject_ids": batch_subjects,
            "idempotency_key": "exam-import-registration",
        },
    ).json()
    registration = client.get(f"/api/exam-registrations/{created['id']}").json()
    attempt = registration["subjects"][0]["attempt"]

    workbook = Workbook()
    sheet = workbook.active
    sheet.append(
        [
            "考试批次编码",
            "报名编号",
            "姓名",
            "科目编码",
            "准考证号",
            "考试日期",
            "出席状态",
            "分数",
            "结果",
            "结果发布日期",
            "备注",
        ]
    )
    sheet.append(
        [
            "IMPORT-BATCH",
            registration["registration_no"],
            "导入学员",
            subject["subject_code"],
            "",
            str(date.today()),
            "PRESENT",
            "85.50",
            "PASSED",
            str(date.today()),
            "批量导入",
        ]
    )
    output = BytesIO()
    workbook.save(output)
    file_bytes = output.getvalue()
    preview = client.post(
        "/api/imports/exam-results/preview",
        headers=csrf(client),
        files={
            "file": (
                "results.xlsx",
                file_bytes,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
    )
    assert preview.status_code == 200, preview.text
    assert preview.json()["items"][0]["status"] == "READY"
    assert client.get(f"/api/exam-attempts/{attempt['id']}").json()["result_status"] == "PENDING"

    confirmed = client.post(
        f"/api/imports/exam-results/{preview.json()['id']}/confirm",
        headers=csrf(client),
        json={"idempotency_key": "confirm-import-0001"},
    )
    assert confirmed.status_code == 200
    assert confirmed.json()["items"][0]["status"] == "SUCCESS"
    imported = client.get(f"/api/exam-attempts/{attempt['id']}").json()
    assert imported["score_value_scaled"] == 8550
    assert imported["result_confirm_status"] == "SUBMITTED"
    assert (
        client.post(
            f"/api/imports/exam-results/{preview.json()['id']}/confirm",
            headers=csrf(client),
            json={"idempotency_key": "confirm-import-0001"},
        ).status_code
        == 200
    )
    official = client.post(
        f"/api/exam-attempts/{attempt['id']}/confirm-result",
        headers=csrf(client),
        json={"version": imported["version"]},
    )
    assert official.status_code == 200
    conflict = client.post(
        "/api/imports/exam-results/preview",
        headers=csrf(client),
        files={"file": ("results.xlsx", file_bytes)},
    )
    assert conflict.json()["items"][0]["status"] == "CONFLICT"


def test_exam_permissions_are_enforced(client):  # noqa: ANN001
    assert (
        client.post(
            "/api/auth/login", json={"username": "reader", "password": "correct-password"}
        ).status_code
        == 200
    )
    assert client.get("/api/exam-batches").status_code == 403
    assert client.get("/api/exam-fee-assessments").status_code == 403
    assert client.get("/api/certificates").status_code == 403
