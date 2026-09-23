# ruff: noqa: E501, E702
from datetime import UTC, datetime, timedelta


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
        json={"course_code": "TEACH", "course_name": "教学测试"},
    ).json()
    version = client.post(
        f"/api/courses/{course['id']}/versions",
        headers=csrf(client),
        json={
            "version_no": "V1",
            "version_name": "第一版",
            "curriculum": {"version_no": "TC", "name": "课程", "total_minutes": 240},
            "exam_scheme": {
                "version_no": "TE",
                "name": "考试",
                "subjects": [{"subject_code": "S1", "subject_name": "科目"}],
            },
            "fee_policy": {"version_no": "TF", "name": "收费", "tuition_amount_cent": 1},
            "refund_policy": {"version_no": "TR", "name": "退费"},
        },
    ).json()
    return client.post(f"/api/course-versions/{version['id']}/publish", headers=csrf(client)).json()


def test_session_teacher_attendance_and_recording(client):  # noqa: ANN001
    login(client)
    version = offering(client)
    student = client.post(
        "/api/students", headers=csrf(client), json={"full_name": "考勤测试"}
    ).json()
    enrollment = client.post(
        "/api/enrollments",
        headers=csrf(client),
        json={
            "student_id": student["id"],
            "course_offering_version_id": version["id"],
            "idempotency_key": "teach-enrollment-01",
        },
    ).json()
    cycle = client.post(
        "/api/classes",
        headers=csrf(client),
        json={
            "class_code": "TC-1",
            "class_name": "教学班",
            "course_offering_version_id": version["id"],
            "class_status": "OPEN",
        },
    ).json()
    client.post(
        f"/api/classes/{cycle['id']}/members",
        headers=csrf(client),
        json={"course_enrollment_id": enrollment["id"], "idempotency_key": "teach-member-001"},
    )
    start = datetime.now(UTC) + timedelta(minutes=1)
    end = start + timedelta(minutes=120)
    created = client.post(
        f"/api/classes/{cycle['id']}/sessions",
        headers=csrf(client),
        json={
            "session_title": "第一课",
            "planned_start_at": start.isoformat(),
            "planned_end_at": end.isoformat(),
        },
    )
    assert created.status_code == 201, created.text
    session = created.json()
    teacher1 = client.post(
        "/api/teachers",
        headers=csrf(client),
        json={
            "full_name": "教师甲",
            "default_rate_amount_cent": 1000,
            "default_rate_unit_minutes": 60,
        },
    ).json()
    teacher2 = client.post(
        "/api/teachers", headers=csrf(client), json={"full_name": "教师乙"}
    ).json()
    lead = client.post(
        f"/api/class-sessions/{session['id']}/teachers",
        headers=csrf(client),
        json={"teacher_id": teacher1["id"], "teaching_role": "LEAD"},
    )
    assert lead.status_code == 201
    assert (
        client.post(
            f"/api/class-sessions/{session['id']}/teachers",
            headers=csrf(client),
            json={"teacher_id": teacher2["id"], "teaching_role": "ASSISTANT"},
        ).status_code
        == 201
    )
    assert (
        client.post(
            f"/api/class-sessions/{session['id']}/schedule",
            headers=csrf(client),
            json={"version": session["version"], "reason": "排课"},
        ).status_code
        == 200
    )
    running = client.post(
        f"/api/class-sessions/{session['id']}/start",
        headers=csrf(client),
        json={"version": session["version"] + 1, "reason": "开课"},
    ).json()
    completed = client.post(
        f"/api/class-sessions/{session['id']}/complete",
        headers=csrf(client),
        json={
            "version": running["version"],
            "actual_start_at": start.isoformat(),
            "actual_end_at": end.isoformat(),
        },
    )
    assert completed.status_code == 200, completed.text
    attendance = client.get(f"/api/class-sessions/{session['id']}/attendance").json()["items"]
    draft = client.post(
        f"/api/class-sessions/{session['id']}/attendance/batch-draft",
        headers=csrf(client),
        json={
            "items": [
                {
                    "class_membership_id": attendance[0]["class_membership_id"],
                    "attendance_status": "PRESENT",
                }
            ]
        },
    )
    assert draft.json()["items"][0]["status"] == "SUCCESS"
    assert (
        client.post(
            f"/api/class-sessions/{session['id']}/attendance/submit",
            headers=csrf(client),
            json={"version": 1, "reason": "提交"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/class-sessions/{session['id']}/attendance/confirm",
            headers=csrf(client),
            json={"version": 1, "reason": "确认"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            f"/api/class-sessions/{session['id']}/attendance/lock",
            headers=csrf(client),
            json={"version": 1, "reason": "锁定"},
        ).status_code
        == 200
    )
    record_id = draft.json()["items"][0]["attendance_id"]
    assert (
        client.post(
            f"/api/attendance-records/{record_id}/revise",
            headers=csrf(client),
            json={
                "version": 4,
                "attendance_status": "LATE",
                "actual_attendance_minutes": 100,
                "late_minutes": 20,
                "reason": "迟到更正",
            },
        ).status_code
        == 200
    )
    recording = client.post(
        f"/api/class-sessions/{session['id']}/recordings",
        headers=csrf(client),
        json={
            "recording_title": "示例",
            "platform_code": "OTHER",
            "external_url": "https://example.test/recording",
            "access_code": "secret",
        },
    )
    assert recording.status_code == 201
    assert (
        client.post(
            f"/api/class-sessions/{session['id']}/recordings",
            headers=csrf(client),
            json={
                "recording_title": "bad",
                "platform_code": "OTHER",
                "external_url": "http://example.test",
            },
        ).status_code
        == 422
    )
