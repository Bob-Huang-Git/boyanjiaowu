# ruff: noqa: E501, E702, I001
# fmt: off
"""Prompt 6 第四至七节：每日出勤事实、住宿事实、版本化政策、权益与支付。

覆盖 docs/implementation/acceptance-checklist.md 中 P6 的条目：

- P6「同日两个课次只产生一条按日餐补权益」
- P6「缺勤不产生权益」
- P6「半天规则」
- P6「跨年度使用不同政策版本」
- P6「没有住宿事实不能产生住宿补贴」
- P6「权益、应付和实际支付金额互不混淆」
- P6「调整和冲正保留历史」

另附政策发布门槛（每个发布规则必须有测试样例）与住宿幂等/防重的断言。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import EntitlementAdjustment


def login(client):  # noqa: ANN001
    assert client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"}).status_code == 200


def csrf(client):  # noqa: ANN001
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def make_student(client, name: str) -> dict:  # noqa: ANN001
    response = client.post("/api/students", headers=csrf(client), json={"full_name": name})
    assert response.status_code == 200, response.text
    return response.json()


def make_offering(client, code: str) -> dict:  # noqa: ANN001
    course = client.post("/api/courses", headers=csrf(client), json={"course_code": code, "course_name": f"{code}课程"}).json()
    version = client.post(
        f"/api/courses/{course['id']}/versions",
        headers=csrf(client),
        json={
            "version_no": "V1",
            "version_name": "第一版",
            "curriculum": {"version_no": f"{code}-C", "name": "课程", "total_minutes": 6000},
            "exam_scheme": {"version_no": f"{code}-E", "name": "考试", "subjects": [{"subject_code": "S1", "subject_name": "科目"}]},
            "fee_policy": {"version_no": f"{code}-F", "name": "收费", "tuition_amount_cent": 100000},
            "refund_policy": {"version_no": f"{code}-R", "name": "退费"},
        },
    ).json()
    published = client.post(f"/api/course-versions/{version['id']}/publish", headers=csrf(client))
    assert published.status_code == 200, published.text
    return published.json()


def enroll(client, student: dict, offering: dict, key: str) -> dict:  # noqa: ANN001
    response = client.post(
        "/api/enrollments",
        headers=csrf(client),
        json={"student_id": student["id"], "course_offering_version_id": offering["id"], "idempotency_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def make_published_program(client, code: str, region: str = "浦东新区", department: str = "退役军人事务局", effective_from: str = "2026-01-01") -> dict:  # noqa: ANN001
    program = client.post("/api/funding-programs", headers=csrf(client), json={"program_code": code, "program_name": f"{code}项目", "department": department}).json()
    version = client.post(
        f"/api/funding-programs/{program['id']}/versions",
        headers=csrf(client),
        json={"version_no": "V1", "region": region, "department": department, "effective_from": effective_from},
    ).json()
    source = client.post("/api/funding-sources", headers=csrf(client), json={"source_code": f"{code}-SRC", "source_name": f"{code}资金来源", "department": department}).json()
    linked = client.post(
        f"/api/funding-program-versions/{version['id']}/funding-sources",
        headers=csrf(client),
        json={"funding_source_id": source["id"], "allocation_rule_type": "EXCLUSIVE"},
    )
    assert linked.status_code == 200, linked.text
    published = client.post(f"/api/funding-program-versions/{version['id']}/publish", headers=csrf(client), json={"version": version["version"]})
    assert published.status_code == 200, published.text
    body = published.json()
    # publish 响应只回传 id/version_no/region/program_status 之类，补齐测试构造政策需要的维度
    body["region"] = region
    body["department"] = department
    body["effective_from"] = effective_from
    return body


def make_eligible_case(client, student, offering, program_version, key: str) -> dict:  # noqa: ANN001
    """建报名 → 立项 → 评定通过，返回 case_status=ELIGIBLE 的资格案。"""
    enrolled = enroll(client, student, offering, key)
    opened = client.post(
        f"/api/enrollments/{enrolled['id']}/funding-case",
        headers=csrf(client),
        json={"funding_program_version_id": program_version["id"]},
    )
    assert opened.status_code == 200, opened.text
    case = opened.json()
    assessed = client.post(
        f"/api/funding-cases/{case['id']}/assessments",
        headers=csrf(client),
        json={"assessment_status": "PASSED", "basis": {"rule": "符合条件"}},
    )
    assert assessed.status_code == 200, assessed.text
    assert assessed.json()["case_status"] == "ELIGIBLE"
    return {"case": assessed.json(), "enrollment": enrolled}


def make_class(client, offering: dict, code: str) -> dict:  # noqa: ANN001
    response = client.post(
        "/api/classes",
        headers=csrf(client),
        json={"class_code": code, "class_name": code, "course_offering_version_id": offering["id"], "class_status": "OPEN"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def join_class(client, cycle: dict, enrolled: dict, key: str) -> dict:  # noqa: ANN001
    response = client.post(
        f"/api/classes/{cycle['id']}/members",
        headers=csrf(client),
        json={"course_enrollment_id": enrolled["id"], "idempotency_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def complete_session(client, cycle: dict, starts_at: datetime, minutes: int) -> dict:  # noqa: ANN001
    end = starts_at + timedelta(minutes=minutes)
    created = client.post(
        f"/api/classes/{cycle['id']}/sessions",
        headers=csrf(client),
        json={"session_title": "课次", "planned_start_at": starts_at.isoformat(), "planned_end_at": end.isoformat()},
    )
    assert created.status_code == 201, created.text
    session = created.json()
    scheduled = client.post(f"/api/class-sessions/{session['id']}/schedule", headers=csrf(client), json={"version": session["version"], "reason": "排课"})
    assert scheduled.status_code == 200, scheduled.text
    running = client.post(f"/api/class-sessions/{session['id']}/start", headers=csrf(client), json={"version": session["version"] + 1, "reason": "开课"})
    assert running.status_code == 200, running.text
    completed = client.post(
        f"/api/class-sessions/{session['id']}/complete",
        headers=csrf(client),
        json={"version": running.json()["version"], "actual_start_at": starts_at.isoformat(), "actual_end_at": end.isoformat()},
    )
    assert completed.status_code == 200, completed.text
    return completed.json()


def record_attendance(client, session: dict, membership_id: str, status: str, minutes: int) -> None:  # noqa: ANN001
    draft = client.post(
        f"/api/class-sessions/{session['id']}/attendance/batch-draft",
        headers=csrf(client),
        json={"items": [{"class_membership_id": membership_id, "attendance_status": status, "actual_attendance_minutes": minutes}]},
    )
    assert draft.status_code == 200, draft.text
    assert draft.json()["items"][0]["status"] == "SUCCESS", draft.text
    submitted = client.post(f"/api/class-sessions/{session['id']}/attendance/submit", headers=csrf(client), json={"version": 1, "reason": "提交"})
    assert submitted.status_code == 200, submitted.text
    confirmed = client.post(f"/api/class-sessions/{session['id']}/attendance/confirm", headers=csrf(client), json={"version": 1, "reason": "确认"})
    assert confirmed.status_code == 200, confirmed.text


def make_policy(client, program_version: dict, allowance_type: str, *, unit: int, version_no: str, effective_from: str, effective_to: str | None = None, half: int = 240, full: int = 480, sample: str | None = '{"case": "样例"}') -> dict:  # noqa: ANN001
    rule = "PER_ATTENDED_DAY" if allowance_type == "MEAL" else "PER_LODGING_NIGHT"
    payload = {
        "funding_program_version_id": program_version["id"],
        "region": program_version["region"],
        "department": program_version["department"],
        "allowance_type": allowance_type,
        "version_no": version_no,
        "effective_from": effective_from,
        "basis_rule": rule,
        "unit_amount_cent": unit,
        "half_day_threshold_minutes": half,
        "full_day_threshold_minutes": full,
        "test_sample_json": sample,
    }
    if effective_to:
        payload["effective_to"] = effective_to
    created = client.post("/api/allowance-policies", headers=csrf(client), json=payload)
    assert created.status_code == 200, created.text
    policy = created.json()
    published = client.post(f"/api/allowance-policies/{policy['id']}/publish", headers=csrf(client), json={"version": policy["version"]})
    assert published.status_code == 200, published.text
    return published.json()


def confirm_day_fact(client, membership: dict, day) -> dict:  # noqa: ANN001
    created = client.post(
        "/api/attendance-day-facts",
        headers=csrf(client),
        json={"class_membership_id": membership["id"], "fact_date": day.date().isoformat()},
    )
    assert created.status_code == 200, created.text
    fact = created.json()
    confirmed = client.post(f"/api/attendance-day-facts/{fact['id']}/confirm", headers=csrf(client))
    assert confirmed.status_code == 200, confirmed.text
    return confirmed.json()


def try_compute(client, case: dict, allowance_type: str, anchor: str, **extra):  # noqa: ANN001
    """返回原始响应，供期望失败的用例断言错误码。"""
    payload = {"allowance_type": allowance_type, "anchor": anchor}
    payload.update(extra)
    return client.post(f"/api/funding-cases/{case['id']}/allowances", headers=csrf(client), json=payload)


def compute(client, case: dict, allowance_type: str, anchor: str, **extra):  # noqa: ANN001
    response = try_compute(client, case, allowance_type, anchor, **extra)
    if response.status_code != 200:
        raise AssertionError(f"计算补贴失败 {response.status_code}: {response.text}")
    return response


# 课次日期必须晚于班级成员的 entered_at（eligible_members 以此过滤），
# 因此 2026 年度用当年晚于建档日期的日；2027 年度用次年日期。
DAY_2026 = datetime(2026, 9, 25, 2, 0, tzinfo=UTC)
DAY_2026_B = datetime(2026, 9, 25, 6, 0, tzinfo=UTC)
DAY_2027 = datetime(2027, 6, 1, 2, 0, tzinfo=UTC)


def prepare(client, code: str):  # noqa: ANN001
    """建一个可计算补贴的完整前置：学员 + 退役核验 + 两门课程报名 + 资格案 + 班级成员。"""
    student = make_student(client, f"{code}学员")
    identity = client.post(
        f"/api/students/{student['id']}/veteran-identity",
        headers=csrf(client),
        json={"retirement_card_no": f"3101{abs(hash(code)) % 10**14:014d}", "retired_on": "2024-03-01", "service_branch": "陆军"},
    ).json()
    verified = client.post(
        f"/api/veteran-identities/{identity['id']}/verifications",
        headers=csrf(client),
        json={"verification_status": "PASSED", "method": "线下核验"},
    )
    assert verified.status_code == 200, verified.text

    # 资格案建在 2026 年度项目上；2026 / 2027 两门课程各有自己的政策
    offering_2026 = make_offering(client, f"{code}26")
    program_2026 = make_published_program(client, f"{code}P26", effective_from="2026-01-01")
    primary = make_eligible_case(client, student, offering_2026, program_2026, f"{code}-e26")

    cycle = make_class(client, offering_2026, f"{code}-CLS")
    membership = join_class(client, cycle, primary["enrollment"], f"{code}-m-01")
    return {"student": student, "case": primary["case"], "enrollment": primary["enrollment"], "cycle": cycle, "membership": membership, "program": program_2026}


# ---------------------------------------------------------------------------
# 每日出勤事实与餐补
# ---------------------------------------------------------------------------


def test_same_day_two_sessions_produce_single_meal_day(client):  # noqa: ANN001
    """P6 必测：同日两个课次只产生一条按日餐补权益。"""
    login(client)
    ctx = prepare(client, "MEAL1")
    make_policy(client, ctx["program"], "MEAL", unit=3000, version_no="M26", effective_from="2026-01-01", effective_to="2026-12-31")

    # 同一天两个课次，各 240 分钟
    first = complete_session(client, ctx["cycle"], DAY_2026, 240)
    record_attendance(client, first, ctx["membership"]["id"], "PRESENT", 240)
    second = complete_session(client, ctx["cycle"], DAY_2026_B, 240)
    record_attendance(client, second, ctx["membership"]["id"], "PRESENT", 240)

    fact = confirm_day_fact(client, ctx["membership"], DAY_2026)
    assert fact["attended_minutes"] == 480
    assert fact["planned_minutes"] == 480
    assert fact["day_part"] == "FULL_DAY"

    # 数据库层只允许一条当前有效事实
    facts = client.get("/api/attendance-day-facts", params={"student_id": ctx["student"]["id"]}).json()
    assert len(facts) == 1

    computed = compute(client, ctx["case"], "MEAL", "2026-09-25")
    assert computed.status_code == 200, computed.text
    body = computed.json()
    assert body["covered_day_count"] == 1, "同一天多个课次不得重复产生按日餐补"
    assert body["computed_amount_cent"] == 3000


def test_absent_day_produces_no_entitlement(client):  # noqa: ANN001
    """P6 必测：缺勤不产生权益。"""
    login(client)
    ctx = prepare(client, "ABSENT")
    make_policy(client, ctx["program"], "MEAL", unit=3000, version_no="M26", effective_from="2026-01-01")

    session = complete_session(client, ctx["cycle"], DAY_2026, 240)
    record_attendance(client, session, ctx["membership"]["id"], "ABSENT", 0)

    fact = confirm_day_fact(client, ctx["membership"], DAY_2026)
    assert fact["attended_minutes"] == 0
    assert fact["day_part"] == "NONE"
    assert fact["absent_minutes"] == 240

    computed = try_compute(client, ctx["case"], "MEAL", "2026-09-25")
    assert computed.status_code == 409
    assert computed.json()["detail"]["code"] == "ALLOWANCE_NO_ATTENDED_DAY"


def test_half_day_uses_half_day_amount(client):  # noqa: ANN001
    """P6 必测：半天规则——出勤达半天阈值但未达全天阈值，按 half_day_percent 计。"""
    login(client)
    ctx = prepare(client, "HALFD")
    policy_payload = {
        "funding_program_version_id": ctx["program"]["id"],
        "region": ctx["program"]["region"],
        "department": ctx["program"]["department"],
        "allowance_type": "MEAL",
        "version_no": "M26",
        "effective_from": "2026-01-01",
        "basis_rule": "PER_ATTENDED_DAY",
        "unit_amount_cent": 3000,
        "half_day_threshold_minutes": 120,
        "full_day_threshold_minutes": 480,
        "rule_params_json": '{"half_day_percent": 50}',
        "test_sample_json": '{"case": "半天"}',
    }
    created = client.post("/api/allowance-policies", headers=csrf(client), json=policy_payload).json()
    client.post(f"/api/allowance-policies/{created['id']}/publish", headers=csrf(client), json={"version": created["version"]})

    session = complete_session(client, ctx["cycle"], DAY_2026, 240)
    record_attendance(client, session, ctx["membership"]["id"], "PRESENT", 240)
    fact = confirm_day_fact(client, ctx["membership"], DAY_2026)
    assert fact["day_part"] == "HALF_DAY"

    computed = compute(client, ctx["case"], "MEAL", "2026-09-25").json()
    assert computed["computed_amount_cent"] == 1500, "半天应为单价 50%"


def test_cross_year_uses_different_policy_versions(client):  # noqa: ANN001
    """P6 必测：跨年度使用不同政策版本，两条权益并存，应付为其合计。"""
    login(client)
    ctx = prepare(client, "Xyear")
    p2026 = make_policy(client, ctx["program"], "MEAL", unit=3000, version_no="M26", effective_from="2026-01-01", effective_to="2026-12-31")

    # 2027 年度政策：同维度新版本号
    p2027 = make_policy(client, ctx["program"], "MEAL", unit=4000, version_no="M27", effective_from="2027-01-01", effective_to="2027-12-31")

    session = complete_session(client, ctx["cycle"], DAY_2026, 480)
    record_attendance(client, session, ctx["membership"]["id"], "PRESENT", 480)
    confirm_day_fact(client, ctx["membership"], DAY_2026)

    session_2027 = complete_session(client, ctx["cycle"], DAY_2027, 480)
    record_attendance(client, session_2027, ctx["membership"]["id"], "PRESENT", 480)
    confirm_day_fact(client, ctx["membership"], DAY_2027)

    first = compute(client, ctx["case"], "MEAL", "2026-09-25", policy_id=p2026["id"])
    assert first.status_code == 200, first.text
    assert first.json()["computed_amount_cent"] == 3000

    second = compute(client, ctx["case"], "MEAL", "2027-06-01", policy_id=p2027["id"])
    assert second.status_code == 200, second.text
    assert second.json()["computed_amount_cent"] == 4000
    assert second.json()["allowance_policy_id"] != first.json()["allowance_policy_id"]

    summary = client.get(f"/api/funding-cases/{ctx['case']['id']}/allowances").json()
    assert summary["entitlement_total_cent"] == 7000
    assert summary["payable_total_cent"] == 7000


# ---------------------------------------------------------------------------
# 住宿事实
# ---------------------------------------------------------------------------


def test_no_lodging_fact_no_lodging_allowance(client):  # noqa: ANN001
    """P6 必测：没有住宿事实不能产生住宿补贴（不得凭考勤推断）。"""
    login(client)
    ctx = prepare(client, "NOLODG")
    make_policy(client, ctx["program"], "LODGING", unit=5000, version_no="L26", effective_from="2026-01-01")

    # 只有考勤，没有住宿事实
    session = complete_session(client, ctx["cycle"], DAY_2026, 480)
    record_attendance(client, session, ctx["membership"]["id"], "PRESENT", 480)

    computed = try_compute(client, ctx["case"], "LODGING", "2026-09-25")
    assert computed.status_code == 409
    assert computed.json()["detail"]["code"] == "ALLOWANCE_NO_LODGING_NIGHT"


def test_lodging_review_generates_nights_and_blocks_duplicate(client):  # noqa: ANN001
    """住宿单审核通过后逐夜生成事实；跨单重复主张同一夜被数据库约束拦截。"""
    login(client)
    ctx = prepare(client, "LODGE")
    make_policy(client, ctx["program"], "LODGING", unit=5000, version_no="L26", effective_from="2026-01-01")

    stay = client.post(
        "/api/lodging-stays",
        headers=csrf(client),
        json={
            "course_enrollment_id": ctx["enrollment"]["id"],
            "check_in_date": "2026-06-01",
            "check_out_date": "2026-06-03",
            "location": "学校宿舍",
            "is_school_arranged": True,
            "idempotency_key": "lodge-stay-0001",
        },
    ).json()
    reviewed = client.post(f"/api/lodging-stays/{stay['id']}/review", headers=csrf(client), json={"review_status": "APPROVED"})
    assert reviewed.status_code == 200, reviewed.text
    nights = reviewed.json()["nights"]
    assert [n["night_date"] for n in nights] == ["2026-06-01", "2026-06-02"]

    computed = compute(client, ctx["case"], "LODGING", "2026-09-25").json()
    assert computed["covered_night_count"] == 2
    assert computed["computed_amount_cent"] == 10000

    # 第二张住宿单覆盖 6/2 —— 该夜已被主张
    other = client.post(
        "/api/lodging-stays",
        headers=csrf(client),
        json={
            "course_enrollment_id": ctx["enrollment"]["id"],
            "check_in_date": "2026-06-02",
            "check_out_date": "2026-06-04",
            "location": "另一处",
            "idempotency_key": "lodge-stay-0002",
        },
    ).json()
    duplicate = client.post(f"/api/lodging-stays/{other['id']}/review", headers=csrf(client), json={"review_status": "APPROVED"})
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "LODGING_NIGHT_ALREADY_CLAIMED"


def test_lodging_stay_idempotent(client):  # noqa: ANN001
    """重复提交同一 idempotency_key 不得产生第二张住宿单。"""
    login(client)
    ctx = prepare(client, "LODGID")
    payload = {
        "course_enrollment_id": ctx["enrollment"]["id"],
        "check_in_date": "2026-06-01",
        "check_out_date": "2026-06-02",
        "idempotency_key": "lodge-idem-0001",
    }
    first = client.post("/api/lodging-stays", headers=csrf(client), json=payload)
    second = client.post("/api/lodging-stays", headers=csrf(client), json=payload)
    assert first.status_code == 200, first.text
    assert second.status_code == 200, second.text
    assert first.json()["id"] == second.json()["id"]


# ---------------------------------------------------------------------------
# 权益 / 应付 / 实付 三层分离
# ---------------------------------------------------------------------------


def test_entitlement_payable_and_payment_are_separate(client):  # noqa: ANN001
    """P6 必测：权益、应付和实际支付金额互不混淆；支付不得超过应付余额。"""
    login(client)
    ctx = prepare(client, "THREE")
    make_policy(client, ctx["program"], "MEAL", unit=3000, version_no="M26", effective_from="2026-01-01")

    session = complete_session(client, ctx["cycle"], DAY_2026, 480)
    record_attendance(client, session, ctx["membership"]["id"], "PRESENT", 480)
    confirm_day_fact(client, ctx["membership"], DAY_2026)

    entitlement = compute(client, ctx["case"], "MEAL", "2026-09-25").json()
    assert entitlement["computed_amount_cent"] == 3000
    assert entitlement["adjusted_amount_cent"] == 0

    listed = client.get("/api/allowance-payables").json()
    assert len(listed) == 1
    payable = listed[0]
    assert payable["payable_amount_cent"] == 3000
    assert payable["paid_amount_cent"] == 0
    assert payable["outstanding_amount_cent"] == 3000

    # 超付被拒
    over = client.post(
        f"/api/allowance-payables/{payable['id']}/payments",
        headers=csrf(client),
        json={"amount_cent": 3001, "payment_method": "BANK", "idempotency_key": "pay-over-0001"},
    )
    assert over.status_code == 409
    assert over.json()["detail"]["code"] == "ALLOWANCE_PAYMENT_EXCEEDS_OUTSTANDING"

    # 分两次支付
    first = client.post(
        f"/api/allowance-payables/{payable['id']}/payments",
        headers=csrf(client),
        json={"amount_cent": 1000, "payment_method": "BANK", "idempotency_key": "pay-a-0001"},
    )
    assert first.status_code == 200, first.text
    second = client.post(
        f"/api/allowance-payables/{payable['id']}/payments",
        headers=csrf(client),
        json={"amount_cent": 2000, "payment_method": "BANK", "idempotency_key": "pay-b-0001"},
    )
    assert second.status_code == 200, second.text

    after = client.get("/api/allowance-payables").json()[0]
    assert after["paid_amount_cent"] == 3000
    assert after["outstanding_amount_cent"] == 0
    assert after["payable_status"] == "SETTLED"
    # 权益金额不受支付影响
    summary = client.get(f"/api/funding-cases/{ctx['case']['id']}/allowances").json()
    assert summary["entitlement_total_cent"] == 3000
    assert summary["payable_total_cent"] == 3000
    assert summary["paid_total_cent"] == 3000


def test_adjustment_and_reversal_preserve_history(client, seeded_db):  # noqa: ANN001
    """P6 必测：调整和冲正保留历史；冲正必须与原调整金额完全相反。"""
    login(client)
    ctx = prepare(client, "ADJUST")
    make_policy(client, ctx["program"], "MEAL", unit=3000, version_no="M26", effective_from="2026-01-01")

    session = complete_session(client, ctx["cycle"], DAY_2026, 480)
    record_attendance(client, session, ctx["membership"]["id"], "PRESENT", 480)
    confirm_day_fact(client, ctx["membership"], DAY_2026)

    entitlement = compute(client, ctx["case"], "MEAL", "2026-09-25").json()

    added = client.post(
        f"/api/subsidy-entitlements/{entitlement['id']}/adjustments",
        headers=csrf(client),
        json={"amount_delta_cent": 1000, "reason": "政策补差", "idempotency_key": "adj-add-0001"},
    )
    assert added.status_code == 200, added.text
    assert added.json()["amount_delta_cent"] == 1000

    # 幂等重放
    replay = client.post(
        f"/api/subsidy-entitlements/{entitlement['id']}/adjustments",
        headers=csrf(client),
        json={"amount_delta_cent": 1000, "reason": "政策补差", "idempotency_key": "adj-add-0001"},
    )
    assert replay.json()["id"] == added.json()["id"]

    # 金额不符的冲正被拒
    wrong = client.post(
        f"/api/subsidy-entitlements/{entitlement['id']}/adjustments",
        headers=csrf(client),
        json={"amount_delta_cent": -500, "reason": "冲正", "adjustment_of_id": added.json()["id"], "idempotency_key": "adj-rev-bad1"},
    )
    assert wrong.status_code == 422
    assert wrong.json()["detail"]["code"] == "ENTITLEMENT_ADJUSTMENT_REVERSAL_MISMATCH"

    reversed_ = client.post(
        f"/api/subsidy-entitlements/{entitlement['id']}/adjustments",
        headers=csrf(client),
        json={"amount_delta_cent": -1000, "reason": "冲正", "adjustment_of_id": added.json()["id"], "idempotency_key": "adj-rev-0001"},
    )
    assert reversed_.status_code == 200, reversed_.text

    summary = client.get(f"/api/funding-cases/{ctx['case']['id']}/allowances").json()
    current = [e for e in summary["entitlements"] if e["is_current"]][0]
    assert current["computed_amount_cent"] == 3000
    assert current["adjusted_amount_cent"] == 0
    assert summary["payable_total_cent"] == 3000

    # 两条调整都在，历史未被覆盖
    with Session(seeded_db) as db:
        rows = db.scalars(select(EntitlementAdjustment).order_by(EntitlementAdjustment.created_at)).all()
        assert len(rows) == 2
        assert rows[1].adjustment_of_id == rows[0].id


# ---------------------------------------------------------------------------
# 政策发布门槛
# ---------------------------------------------------------------------------


def test_policy_publish_requires_test_sample(client):  # noqa: ANN001
    """设计 P6 第六节：每个发布规则必须有测试样例，发布后不能修改。"""
    login(client)
    ctx = prepare(client, "SAMPLE")
    created = client.post(
        "/api/allowance-policies",
        headers=csrf(client),
        json={
            "funding_program_version_id": ctx["program"]["id"],
            "region": ctx["program"]["region"],
            "department": ctx["program"]["department"],
            "allowance_type": "MEAL",
            "version_no": "NOPE",
            "effective_from": "2026-01-01",
            "basis_rule": "PER_ATTENDED_DAY",
            "unit_amount_cent": 1000,
        },
    )
    assert created.status_code == 200, created.text
    policy = created.json()
    blocked = client.post(f"/api/allowance-policies/{policy['id']}/publish", headers=csrf(client), json={"version": policy["version"]})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "ALLOWANCE_POLICY_SAMPLE_REQUIRED"

    # 不受支持的基准规则被拒
    bad = client.post(
        "/api/allowance-policies",
        headers=csrf(client),
        json={
            "funding_program_version_id": ctx["program"]["id"],
            "region": ctx["program"]["region"],
            "department": ctx["program"]["department"],
            "allowance_type": "MEAL",
            "version_no": "BAD",
            "effective_from": "2026-01-01",
            "basis_rule": "python:eval",
            "unit_amount_cent": 1000,
        },
    )
    assert bad.status_code == 422
    assert bad.json()["detail"]["code"] == "ALLOWANCE_POLICY_RULE_UNSUPPORTED"

    # 住宿策略挂到餐补上被拒
    mismatch = client.post(
        "/api/allowance-policies",
        headers=csrf(client),
        json={
            "funding_program_version_id": ctx["program"]["id"],
            "region": ctx["program"]["region"],
            "department": ctx["program"]["department"],
            "allowance_type": "MEAL",
            "version_no": "MISMATCH",
            "effective_from": "2026-01-01",
            "basis_rule": "PER_LODGING_NIGHT",
            "unit_amount_cent": 1000,
        },
    )
    assert mismatch.status_code == 422
    assert mismatch.json()["detail"]["code"] == "ALLOWANCE_POLICY_RULE_MISMATCH"
