# ruff: noqa: E501, E702, I001
# fmt: off
"""Prompt 6 第一节（身份层）与第二、三节（项目资格与学校垫资）的测试。

覆盖 docs/implementation/acceptance-checklist.md 中 P6 的条目：

- P6「非退役学员不能建立 FundingCase」
- P6「一个学员多门课程分别审核资格」
- P6「滚班不自动重置培训补贴资格」

另附身份层 PII 约束与幂等约束的断言（设计 Prompt 6 第一节、第三节）。
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.models import AuditLog, EligibilityAssessment, FundingCase, ProjectCost, VeteranIdentity


def login(client):  # noqa: ANN001
    assert client.post("/api/auth/login", json={"username": "admin", "password": "correct-password"}).status_code == 200


def csrf(client):  # noqa: ANN001
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def make_student(client, name: str) -> dict:  # noqa: ANN001
    response = client.post("/api/students", headers=csrf(client), json={"full_name": name})
    assert response.status_code == 200, response.text
    return response.json()


def make_offering(client, code: str) -> dict:  # noqa: ANN001
    """建课程、版本并发布，返回可报名的课程版本。"""
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


def make_veteran(client, student: dict, card_no: str = "310101199001011234") -> dict:  # noqa: ANN001
    response = client.post(
        f"/api/students/{student['id']}/veteran-identity",
        headers=csrf(client),
        json={"retirement_card_no": card_no, "retired_on": "2024-03-01", "service_branch": "陆军"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def verify_veteran(client, identity: dict, status: str = "PASSED") -> dict:  # noqa: ANN001
    response = client.post(
        f"/api/veteran-identities/{identity['id']}/verifications",
        headers=csrf(client),
        json={"verification_status": status, "method": "线下核验"},
    )
    assert response.status_code == 200, response.text
    return response.json()


def make_published_program(client, code: str, region: str = "浦东新区", department: str = "退役军人事务局") -> dict:  # noqa: ANN001
    program = client.post("/api/funding-programs", headers=csrf(client), json={"program_code": code, "program_name": f"{code}项目", "department": department}).json()
    version = client.post(
        f"/api/funding-programs/{program['id']}/versions",
        headers=csrf(client),
        json={"version_no": "V1", "region": region, "department": department, "effective_from": "2026-01-01"},
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
    return published.json()


def make_class(client, offering: dict, code: str) -> dict:  # noqa: ANN001
    return client.post("/api/classes", headers=csrf(client), json={"class_code": code, "class_name": code, "course_offering_version_id": offering["id"], "class_status": "OPEN"}).json()


def join_class(client, cycle: dict, enrolled: dict, key: str) -> dict:  # noqa: ANN001
    response = client.post(f"/api/classes/{cycle['id']}/members", headers=csrf(client), json={"course_enrollment_id": enrolled["id"], "idempotency_key": key})
    assert response.status_code == 200, response.text
    return response.json()


def rollover(client, enrolled: dict, source: dict, target: dict, key: str):  # noqa: ANN001
    return client.post(
        f"/api/enrollments/{enrolled['id']}/rollover",
        headers=csrf(client),
        json={
            "source_membership_id": source["id"],
            "target_class_cycle_id": target["id"],
            "effective_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
            "reason": "滚班",
            "financial_treatment": "CARRY_OVER",
            "idempotency_key": key,
            "version": 1,
        },
    )


def case_of(engine, enrollment_id: str):  # noqa: ANN001
    with Session(engine) as db:
        return db.scalar(select(FundingCase).where(FundingCase.course_enrollment_id == enrollment_id))


# ---------------------------------------------------------------------------
# 身份层
# ---------------------------------------------------------------------------


def test_retirement_card_is_encrypted_and_blind_indexed(client, seeded_db):  # noqa: ANN001
    """退役证号必须密文存储 + HMAC 盲索引，明文不落库。"""
    login(client)
    student = make_student(client, "退役学员甲")
    card_no = "310101199001011234"
    identity = make_veteran(client, student, card_no)

    assert identity["retirement_card_no_masked"] == "退役证 ****1234"
    assert "retirement_card_no_plaintext" in identity and identity["retirement_card_no_plaintext"] is None

    with Session(seeded_db) as db:
        row = db.scalar(select(VeteranIdentity).where(VeteranIdentity.student_id == student["id"]))
        assert row.retirement_card_no_encrypted and card_no not in row.retirement_card_no_encrypted
        # 表结构里不存在任何明文列：明文在物理上无处可落
        assert not any("plaintext" in column.name for column in VeteranIdentity.__table__.columns)
        assert row.retirement_card_no_hmac and len(row.retirement_card_no_hmac) == 64
        assert row.retirement_card_no_key_version == "v1"
        assert row.service_branch == "陆军"


def test_lookup_by_card_reports_existence_without_leaking(client):  # noqa: ANN001
    login(client)
    student = make_student(client, "退役学员乙")
    make_veteran(client, student, "310101199002022345")

    hit = client.get("/api/veteran-identities/lookup", params={"retirement_card_no": "310101199002022345"})
    assert hit.status_code == 200 and hit.json() == {"exists": True}
    miss = client.get("/api/veteran-identities/lookup", params={"retirement_card_no": "999999999999999999"})
    assert miss.json() == {"exists": False}


def test_same_card_cannot_bind_second_student(client):  # noqa: ANN001
    """查重命中只拒绝，不自动合并。"""
    login(client)
    first = make_student(client, "退役学员丙")
    second = make_student(client, "退役学员丁")
    make_veteran(client, first, "310101199003033456")

    response = client.post(
        f"/api/students/{second['id']}/veteran-identity",
        headers=csrf(client),
        json={"retirement_card_no": "310101199003033456"},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "VETERAN_CARD_ALREADY_BOUND"


def test_plaintext_view_requires_permission_and_reason(client, seeded_db):  # noqa: ANN001
    login(client)
    student = make_student(client, "退役学员戊")
    card_no = "310101199004044567"
    identity = make_veteran(client, student, card_no)

    blank = client.post(f"/api/veteran-identities/{identity['id']}/plaintext", headers=csrf(client), json={"reason": ""})
    assert blank.status_code == 422

    ok = client.post(f"/api/veteran-identities/{identity['id']}/plaintext", headers=csrf(client), json={"reason": "政府申报需要核对"})
    assert ok.status_code == 200 and ok.json()["retirement_card_no"] == card_no

    with Session(seeded_db) as db:
        actions = {row.action for row in db.scalars(select(AuditLog).where(AuditLog.subject_id == identity["id"])).all()}
        assert "veteran_identity.view_plaintext" in actions


# ---------------------------------------------------------------------------
# 资格案
# ---------------------------------------------------------------------------


def test_non_veteran_cannot_open_funding_case(client):  # noqa: ANN001
    """P6 必测：非退役学员不能建立 FundingCase。"""
    login(client)
    student = make_student(client, "普通学员")
    offering = make_offering(client, "NOVET")
    enrolled = enroll(client, student, offering, "novet-enroll-0001")
    program_version = make_published_program(client, "NOVET")

    response = client.post(
        f"/api/enrollments/{enrolled['id']}/funding-case",
        headers=csrf(client),
        json={"funding_program_version_id": program_version["id"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "VETERAN_IDENTITY_REQUIRED"


def test_unverified_veteran_cannot_open_funding_case(client):  # noqa: ANN001
    login(client)
    student = make_student(client, "待核验退役学员")
    offering = make_offering(client, "UNVER")
    enrolled = enroll(client, student, offering, "unver-enroll-0001")
    make_veteran(client, student, "310101199005055678")
    program_version = make_published_program(client, "UNVER")

    response = client.post(
        f"/api/enrollments/{enrolled['id']}/funding-case",
        headers=csrf(client),
        json={"funding_program_version_id": program_version["id"]},
    )
    assert response.status_code == 409
    assert response.json()["detail"]["code"] == "VETERAN_IDENTITY_NOT_VERIFIED"


def test_one_student_two_courses_assessed_separately(client):  # noqa: ANN001
    """P6 必测：一个学员多门课程分别审核资格。"""
    login(client)
    student = make_student(client, "退役学员己")
    identity = make_veteran(client, student, "310101199006066789")
    verify_veteran(client, identity)

    first_offering = make_offering(client, "TWO-A")
    second_offering = make_offering(client, "TWO-B")
    first_enrolled = enroll(client, student, first_offering, "two-a-enroll-01")
    second_enrolled = enroll(client, student, second_offering, "two-b-enroll-01")
    program_version = make_published_program(client, "TWO")

    cases = []
    for enrolled in (first_enrolled, second_enrolled):
        opened = client.post(
            f"/api/enrollments/{enrolled['id']}/funding-case",
            headers=csrf(client),
            json={"funding_program_version_id": program_version["id"]},
        )
        assert opened.status_code == 200, opened.text
        cases.append(opened.json())
    assert cases[0]["id"] != cases[1]["id"]

    # 两门课程分别评定：一门通过、一门驳回，互不影响
    passed = client.post(f"/api/funding-cases/{cases[0]['id']}/assessments", headers=csrf(client), json={"assessment_status": "PASSED", "basis": {"rule": "首次申请"}})
    assert passed.status_code == 200, passed.text
    assert passed.json()["case_status"] == "ELIGIBLE"

    failed = client.post(f"/api/funding-cases/{cases[1]['id']}/assessments", headers=csrf(client), json={"assessment_status": "FAILED", "basis": {"rule": "材料不符"}})
    assert failed.json()["case_status"] == "INELIGIBLE"

    # 评定版本化：每条 case 各自只有一条当前有效评定
    detail_first = client.get(f"/api/funding-cases/{cases[0]['id']}").json()
    detail_second = client.get(f"/api/funding-cases/{cases[1]['id']}").json()
    assert detail_first["current_assessment"]["assessment_status"] == "PASSED"
    assert detail_second["current_assessment"]["assessment_status"] == "FAILED"


def test_rollover_does_not_reset_funding_eligibility(client, seeded_db):  # noqa: ANN001
    """P6 必测：滚班不自动重置培训补贴资格。

    FundingCase 挂在 CourseEnrollment 上，滚班只新增 ClassMembership，
    因此资格案与其评定结论在滚班后必须原样保留。
    """
    login(client)
    student = make_student(client, "退役学员庚")
    identity = make_veteran(client, student, "310101199007077890")
    verify_veteran(client, identity)

    offering = make_offering(client, "ROLL")
    enrolled = enroll(client, student, offering, "roll-enroll-0001")
    program_version = make_published_program(client, "ROLL")
    case = client.post(
        f"/api/enrollments/{enrolled['id']}/funding-case",
        headers=csrf(client),
        json={"funding_program_version_id": program_version["id"]},
    ).json()
    assessed = client.post(f"/api/funding-cases/{case['id']}/assessments", headers=csrf(client), json={"assessment_status": "PASSED", "basis": {}})
    assert assessed.json()["case_status"] == "ELIGIBLE"

    first_class = make_class(client, offering, "ROLL-A")
    second_class = make_class(client, offering, "ROLL-B")
    source = join_class(client, first_class, enrolled, "roll-member-0001")
    moved = rollover(client, enrolled, source, second_class, "roll-key-000001")
    assert moved.status_code == 200, moved.text

    after = case_of(seeded_db, enrolled["id"])
    assert after is not None and after.id == case["id"]
    assert after.case_status == "ELIGIBLE"

    detail = client.get(f"/api/funding-cases/{case['id']}").json()
    assert detail["current_assessment"]["assessment_status"] == "PASSED"
    assert detail["case_status"] == "ELIGIBLE"

    with Session(seeded_db) as db:
        current = db.scalars(select(EligibilityAssessment).where(EligibilityAssessment.funding_case_id == case["id"], EligibilityAssessment.is_current.is_(True))).all()
        assert len(current) == 1


def test_published_version_required_and_duplicate_case_rejected(client):  # noqa: ANN001
    login(client)
    student = make_student(client, "退役学员辛")
    identity = make_veteran(client, student, "310101199008088901")
    verify_veteran(client, identity)
    offering = make_offering(client, "GUARD")
    enrolled = enroll(client, student, offering, "guard-enroll-001")

    # 未发布版本不能立项
    program = client.post("/api/funding-programs", headers=csrf(client), json={"program_code": "GUARD", "program_name": "未发布项目", "department": "人社局"}).json()
    draft = client.post(f"/api/funding-programs/{program['id']}/versions", headers=csrf(client), json={"version_no": "V1", "region": "浦东新区", "department": "人社局", "effective_from": "2026-01-01"}).json()
    blocked = client.post(f"/api/enrollments/{enrolled['id']}/funding-case", headers=csrf(client), json={"funding_program_version_id": draft["id"]})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "PROGRAM_VERSION_NOT_PUBLISHED"

    # 同一报名不能有两个资格案
    published = make_published_program(client, "GUARD2")
    first = client.post(f"/api/enrollments/{enrolled['id']}/funding-case", headers=csrf(client), json={"funding_program_version_id": published["id"]})
    assert first.status_code == 200, first.text
    again = client.post(f"/api/enrollments/{enrolled['id']}/funding-case", headers=csrf(client), json={"funding_program_version_id": published["id"]})
    assert again.status_code == 409 and again.json()["detail"]["code"] == "FUNDING_CASE_EXISTS"


# ---------------------------------------------------------------------------
# 学校垫资
# ---------------------------------------------------------------------------


def test_project_cost_idempotent_and_allocation_bounded(client, seeded_db):  # noqa: ANN001
    login(client)
    student = make_student(client, "退役学员壬")
    offering = make_offering(client, "COST")
    enrolled = enroll(client, student, offering, "cost-enroll-0001")
    cycle = make_class(client, offering, "COST-A")

    body = {"cost_type": "TEACHER_FEE", "amount_cent": 500000, "idempotency_key": "cost-key-000001"}
    first = client.post(f"/api/class-cycles/{cycle['id']}/project-costs", headers=csrf(client), json=body)
    assert first.status_code == 200, first.text
    repeated = client.post(f"/api/class-cycles/{cycle['id']}/project-costs", headers=csrf(client), json=body)
    assert repeated.json()["duplicated"] is True
    assert repeated.json()["id"] == first.json()["id"]

    with Session(seeded_db) as db:
        assert len(db.scalars(select(ProjectCost)).all()) == 1

    # 分摊不得超过成本总额
    over = client.post(f"/api/project-costs/{first.json()['id']}/allocations", headers=csrf(client), json={"allocation_basis": "MANUAL", "course_enrollment_id": enrolled["id"], "amount_cent": 500001})
    assert over.status_code == 409 and over.json()["detail"]["code"] == "ALLOCATION_EXCEEDS_COST"

    ok = client.post(f"/api/project-costs/{first.json()['id']}/allocations", headers=csrf(client), json={"allocation_basis": "PER_STUDENT", "course_enrollment_id": enrolled["id"], "amount_cent": 300000})
    assert ok.status_code == 200 and ok.json()["allocated_total_cent"] == 300000

    # 成本确认后锁定分摊
    confirmed = client.post(f"/api/project-costs/{first.json()['id']}/confirm", headers=csrf(client), json={"version": 1})
    assert confirmed.status_code == 200 and confirmed.json()["cost_status"] == "CONFIRMED"
    stale = client.post(f"/api/project-costs/{first.json()['id']}/confirm", headers=csrf(client), json={"version": 1})
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "VERSION_CONFLICT"
