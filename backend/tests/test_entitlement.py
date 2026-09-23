"""培训权益与滚班财务处理测试。

覆盖 docs/implementation/acceptance-checklist.md 中的条目：

- P5「免费滚班不重复收费」
- P5「补差滚班只生成补差 Charge」
- P3「重复滚班幂等」
"""

from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.models import (
    ClassMembership,
    Receivable,
    TrainingEntitlement,
    TrainingEntitlementEntry,
)


def login(client):  # noqa: ANN001
    assert (
        client.post(
            "/api/auth/login", json={"username": "admin", "password": "correct-password"}
        ).status_code
        == 200
    )


def csrf(client):  # noqa: ANN001
    return {"X-CSRF-Token": client.cookies.get("csrf_token")}


def make_enrollment(client, code: str):  # noqa: ANN001
    """建课程版本、学员与报名，返回 (报名, 已发布课程版本)。"""
    course = client.post(
        "/api/courses",
        headers=csrf(client),
        json={"course_code": code, "course_name": "权益测试课程"},
    ).json()
    version = client.post(
        f"/api/courses/{course['id']}/versions",
        headers=csrf(client),
        json={
            "version_no": "V1",
            "version_name": "第一版",
            "curriculum": {"version_no": f"{code}-C", "name": "课程", "total_minutes": 6000},
            "exam_scheme": {
                "version_no": f"{code}-E",
                "name": "考试",
                "subjects": [{"subject_code": "S1", "subject_name": "科目"}],
            },
            "fee_policy": {
                "version_no": f"{code}-F",
                "name": "收费",
                "tuition_amount_cent": 100000,
            },
            "refund_policy": {"version_no": f"{code}-R", "name": "退费"},
        },
    ).json()
    offering = client.post(
        f"/api/course-versions/{version['id']}/publish", headers=csrf(client)
    ).json()
    student = client.post(
        "/api/students", headers=csrf(client), json={"full_name": "权益测试学员"}
    ).json()
    enrolled = client.post(
        "/api/enrollments",
        headers=csrf(client),
        json={
            "student_id": student["id"],
            "course_offering_version_id": offering["id"],
            "idempotency_key": f"{code}-enroll-0001",
        },
    ).json()
    return enrolled, offering


def make_class(client, offering: dict, code: str) -> dict:  # noqa: ANN001
    return client.post(
        "/api/classes",
        headers=csrf(client),
        json={
            "class_code": code,
            "class_name": code,
            "course_offering_version_id": offering["id"],
            "class_status": "OPEN",
        },
    ).json()


def join_class(client, cycle: dict, enrolled: dict, key: str) -> dict:  # noqa: ANN001
    response = client.post(
        f"/api/classes/{cycle['id']}/members",
        headers=csrf(client),
        json={"course_enrollment_id": enrolled["id"], "idempotency_key": key},
    )
    assert response.status_code == 200, response.text
    return response.json()


def rollover(  # noqa: ANN001
    client, enrolled: dict, source: dict, target: dict, treatment: str, key: str, **extra: object
):
    body = {
        "source_membership_id": source["id"],
        "target_class_cycle_id": target["id"],
        "effective_at": (datetime.now(UTC) + timedelta(days=1)).isoformat(),
        "reason": "滚班测试",
        "financial_treatment": treatment,
        "idempotency_key": key,
        "version": 1,
    }
    body.update(extra)
    return client.post(
        f"/api/enrollments/{enrolled['id']}/rollover", headers=csrf(client), json=body
    )


def receivables_of(engine, enrollment_id: str) -> list[Receivable]:  # noqa: ANN001
    with Session(engine) as db:
        return list(
            db.scalars(
                select(Receivable).where(Receivable.course_enrollment_id == enrollment_id)
            ).all()
        )


def test_free_rollover_creates_no_charge(client, seeded_db):  # noqa: ANN001
    """免费滚班：不重复消耗、不产生任何应收。"""
    login(client)
    enrolled, offering = make_enrollment(client, "FREE")
    first = make_class(client, offering, "FREE-A")
    second = make_class(client, offering, "FREE-B")
    source = join_class(client, first, enrolled, "free-member-0001")

    response = rollover(
        client, enrolled, source, second, "CARRY_OVER", "free-roll-0001", rollover_minutes=600
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["financial_applied"] == "FREE"
    assert body["supplement_receivable_id"] is None

    assert receivables_of(seeded_db, enrolled["id"]) == []
    with Session(seeded_db) as db:
        entitlement = db.scalar(
            select(TrainingEntitlement).where(
                TrainingEntitlement.course_enrollment_id == enrolled["id"]
            )
        )
        assert entitlement is not None
        assert entitlement.free_rollover_minutes == 600
        assert entitlement.consumed_minutes == 0
        assert entitlement.purchased_minutes == 0


def test_supplement_rollover_creates_only_supplement_charge(client, seeded_db):  # noqa: ANN001
    """补差滚班：只生成补差应收，不重复收全额培训费。"""
    login(client)
    enrolled, offering = make_enrollment(client, "SUP")
    first = make_class(client, offering, "SUP-A")
    second = make_class(client, offering, "SUP-B")
    source = join_class(client, first, enrolled, "sup-member-00001")

    response = rollover(
        client,
        enrolled,
        source,
        second,
        "SUPPLEMENT_REQUIRED",
        "sup-roll-0001",
        supplement_minutes=1200,
        supplement_amount_cent=50000,
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["financial_applied"] == "SUPPLEMENT"

    items = receivables_of(seeded_db, enrolled["id"])
    assert len(items) == 1
    assert items[0].receivable_type == "SUPPLEMENT"
    assert items[0].original_amount_cent == 50000
    assert items[0].payable_amount_cent == 50000
    assert all(item.receivable_type != "TUITION" for item in items)

    with Session(seeded_db) as db:
        entitlement = db.scalar(
            select(TrainingEntitlement).where(
                TrainingEntitlement.course_enrollment_id == enrolled["id"]
            )
        )
        assert entitlement.supplement_minutes == 1200
        assert entitlement.free_rollover_minutes == 0


def test_supplement_rollover_requires_explicit_amount(client):  # noqa: ANN001
    """补差金额必须显式给出——系统不推算写死单价。"""
    login(client)
    enrolled, offering = make_enrollment(client, "NOAMT")
    first = make_class(client, offering, "NOAMT-A")
    second = make_class(client, offering, "NOAMT-B")
    source = join_class(client, first, enrolled, "noamt-member-001")

    response = rollover(
        client,
        enrolled,
        source,
        second,
        "SUPPLEMENT_REQUIRED",
        "noamt-roll-001",
        supplement_minutes=1200,
    )
    assert response.status_code == 422, response.text


def test_rollover_is_idempotent(client, seeded_db):  # noqa: ANN001
    """重复滚班请求不产生第二条班级经历，也不重复建账。"""
    login(client)
    enrolled, offering = make_enrollment(client, "IDEM")
    first = make_class(client, offering, "IDEM-A")
    second = make_class(client, offering, "IDEM-B")
    source = join_class(client, first, enrolled, "idem-member-0001")

    first_call = rollover(
        client, enrolled, source, second, "CARRY_OVER", "idem-roll-0001", rollover_minutes=600
    )
    assert first_call.status_code == 200, first_call.text
    assert first_call.json()["idempotent"] is False

    second_call = rollover(
        client, enrolled, source, second, "CARRY_OVER", "idem-roll-0001", rollover_minutes=600
    )
    assert second_call.status_code == 200, second_call.text
    assert second_call.json()["idempotent"] is True
    assert second_call.json()["id"] == first_call.json()["id"]

    with Session(seeded_db) as db:
        memberships = db.scalar(
            select(func.count())
            .select_from(ClassMembership)
            .where(ClassMembership.course_enrollment_id == enrolled["id"])
        )
        assert memberships == 2
        entries = db.scalar(
            select(func.count())
            .select_from(TrainingEntitlementEntry)
            .where(TrainingEntitlementEntry.idempotency_key == "rollover:idem-roll-0001")
        )
        assert entries == 1


def test_entitlement_entries_balance_and_guards(client, seeded_db):  # noqa: ANN001
    """分钟余额：购买、消耗、幂等重放与超额扣减保护。"""
    login(client)
    enrolled, _offering = make_enrollment(client, "BAL")
    url = f"/api/enrollments/{enrolled['id']}/entitlement/entries"

    purchase = client.post(
        url,
        headers=csrf(client),
        json={"entry_type": "PURCHASE", "minutes": 6000, "idempotency_key": "bal-purchase-0001"},
    )
    assert purchase.status_code == 200, purchase.text
    assert purchase.json()["entitlement"]["available_minutes"] == 6000
    assert purchase.json()["entitlement"]["total_minutes"] == 6000

    consume = client.post(
        url,
        headers=csrf(client),
        json={"entry_type": "CONSUME", "minutes": 2400, "idempotency_key": "bal-consume-0001"},
    )
    assert consume.status_code == 200, consume.text
    assert consume.json()["entitlement"]["available_minutes"] == 3600
    assert consume.json()["entitlement"]["consumed_minutes"] == 2400

    replay = client.post(
        url,
        headers=csrf(client),
        json={"entry_type": "CONSUME", "minutes": 2400, "idempotency_key": "bal-consume-0001"},
    )
    assert replay.status_code == 200, replay.text
    assert replay.json()["created"] is False
    assert replay.json()["entitlement"]["available_minutes"] == 3600

    overdraw = client.post(
        url,
        headers=csrf(client),
        json={"entry_type": "CONSUME", "minutes": 4000, "idempotency_key": "bal-consume-0002"},
    )
    assert overdraw.status_code == 409, overdraw.text

    with Session(seeded_db) as db:
        entries = db.scalar(
            select(func.count())
            .select_from(TrainingEntitlementEntry)
            .where(
                TrainingEntitlementEntry.entitlement_id
                == db.scalar(
                    select(TrainingEntitlement.id).where(
                        TrainingEntitlement.course_enrollment_id == enrolled["id"]
                    )
                )
            )
        )
        assert entries == 2


def test_entitlement_reversal_reduces_again(client, seeded_db):  # noqa: ANN001
    """冲正用反向分录，方向取反，不改历史。"""
    login(client)
    enrolled, _offering = make_enrollment(client, "REV")
    url = f"/api/enrollments/{enrolled['id']}/entitlement/entries"

    purchase = client.post(
        url,
        headers=csrf(client),
        json={"entry_type": "PURCHASE", "minutes": 6000, "idempotency_key": "rev-purchase-001"},
    )
    assert purchase.status_code == 200, purchase.text
    assert purchase.json()["entitlement"]["purchased_minutes"] == 6000
    purchase_entry_id = purchase.json()["entry"]["id"]

    reversal = client.post(
        url,
        headers=csrf(client),
        json={
            "entry_type": "PURCHASE",
            "minutes": 6000,
            "idempotency_key": "rev-purchase-002",
            "reversal_of_entry_id": purchase_entry_id,
            "reason": "录入错误冲正",
        },
    )
    assert reversal.status_code == 200, reversal.text
    assert reversal.json()["entitlement"]["purchased_minutes"] == 0
    assert reversal.json()["entitlement"]["available_minutes"] == 0
    assert reversal.json()["entry"]["minutes_delta"] == -6000

    with Session(seeded_db) as db:
        entries = db.scalar(select(func.count()).select_from(TrainingEntitlementEntry))
        assert entries == 2


def test_entitlement_read_and_scope(client):  # noqa: ANN001
    """未建账时读取返回空；建账后可读回台账与明细。"""
    login(client)
    enrolled, _offering = make_enrollment(client, "READ")
    url = f"/api/enrollments/{enrolled['id']}/entitlement"

    empty = client.get(url)
    assert empty.status_code == 200, empty.text
    assert empty.json() == {"entitlement": None, "entries": []}

    client.post(
        f"/api/enrollments/{enrolled['id']}/entitlement/entries",
        headers=csrf(client),
        json={"entry_type": "GIFT", "minutes": 300, "idempotency_key": "read-gift-0001"},
    )
    loaded = client.get(url)
    assert loaded.status_code == 200, loaded.text
    assert loaded.json()["entitlement"]["gifted_minutes"] == 300
    assert loaded.json()["entitlement"]["available_minutes"] == 300
    assert len(loaded.json()["entries"]) == 1
    assert loaded.json()["entries"][0]["entry_type"] == "GIFT"
