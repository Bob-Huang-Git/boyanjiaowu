# ruff: noqa: B008, E501, E701, E702, B904
"""Sprint 3 teaching execution APIs with explicit state transitions."""

import hashlib
import json
from datetime import datetime
from typing import Annotated, Any
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.models import (
    AttendanceFinalization,
    AttendanceRecord,
    AttendanceRevision,
    AuditLog,
    ClassCycle,
    ClassMembership,
    ClassSession,
    CourseEnrollment,
    CourseOfferingVersion,
    EnrollmentRolloverRequest,
    SessionRecording,
    SessionTeacherAssignment,
    Student,
    TeacherProfile,
    User,
    utc_now,
)
from app.core.pii import decrypt, encrypt, mask_phone
from app.modules.iam.router import Db, require_permission

router = APIRouter(prefix="/api", tags=["teaching"])
TeacherRead = Annotated[User, Depends(require_permission("teacher.read"))]
TeacherManage = Annotated[User, Depends(require_permission("teacher.manage"))]
SessionRead = Annotated[User, Depends(require_permission("class_session.read"))]
SessionManage = Annotated[User, Depends(require_permission("class_session.manage"))]
SessionComplete = Annotated[User, Depends(require_permission("class_session.complete"))]
AssignmentManage = Annotated[User, Depends(require_permission("session_teacher.manage"))]
AssignmentConfirm = Annotated[User, Depends(require_permission("session_teacher.confirm"))]
AttendanceRead = Annotated[User, Depends(require_permission("attendance.read"))]
AttendanceEdit = Annotated[User, Depends(require_permission("attendance.edit"))]
AttendanceSubmit = Annotated[User, Depends(require_permission("attendance.submit"))]
AttendanceConfirm = Annotated[User, Depends(require_permission("attendance.confirm"))]
AttendanceLock = Annotated[User, Depends(require_permission("attendance.lock"))]
AttendanceRevise = Annotated[User, Depends(require_permission("attendance.revise"))]
Rollover = Annotated[User, Depends(require_permission("enrollment.rollover"))]
RecordingRead = Annotated[User, Depends(require_permission("recording.read"))]
RecordingManage = Annotated[User, Depends(require_permission("recording.manage"))]
RecordingReview = Annotated[User, Depends(require_permission("recording.review"))]
RecordingReveal = Annotated[User, Depends(require_permission("recording.access_code.reveal"))]
SummaryRead = Annotated[User, Depends(require_permission("teaching_summary.read"))]


def error(status: int, code: str, message: str) -> HTTPException:
    return HTTPException(status_code=status, detail={"code": code, "message": message})


def audit(
    db: Session,
    user: User,
    request: Request,
    action: str,
    subject: str,
    subject_id: str,
    detail: dict[str, Any] | None = None,
) -> None:
    db.add(
        AuditLog(
            organization_id=user.organization_id,
            actor_user_id=user.id,
            action=action,
            subject_type=subject,
            subject_id=subject_id,
            correlation_id=request.state.correlation_id,
            detail_json=json.dumps(detail or {}, ensure_ascii=False),
        )
    )


def code(prefix: str) -> str:
    return f"{prefix}{hashlib.sha256(str(utc_now()).encode()).hexdigest()[:10].upper()}"


def cycle(db: Session, user: User, cycle_id: str) -> ClassCycle:
    item = db.scalar(
        select(ClassCycle).where(
            ClassCycle.id == cycle_id, ClassCycle.organization_id == user.organization_id
        )
    )
    if not item:
        raise error(404, "CLASS_NOT_FOUND", "未找到班级。")
    return item


def session(db: Session, user: User, session_id: str) -> ClassSession:
    item = db.scalar(
        select(ClassSession)
        .join(ClassCycle)
        .where(ClassSession.id == session_id, ClassCycle.organization_id == user.organization_id)
    )
    if not item:
        raise error(404, "SESSION_NOT_FOUND", "未找到课次。")
    return item


def teacher(db: Session, teacher_id: str) -> TeacherProfile:
    item = db.get(TeacherProfile, teacher_id)
    if not item:
        raise error(404, "TEACHER_NOT_FOUND", "未找到教师。")
    return item


def minutes(start: datetime, end: datetime) -> int:
    value = int((end - start).total_seconds() // 60)
    if value <= 0:
        raise error(422, "TIME_RANGE_INVALID", "结束时间必须晚于开始时间。")
    return value


def session_view(item: ClassSession) -> dict[str, Any]:
    return {
        "id": item.id,
        "class_cycle_id": item.class_cycle_id,
        "session_no": item.session_no,
        "session_title": item.session_title,
        "service_date": item.service_date,
        "planned_start_at": item.planned_start_at,
        "planned_end_at": item.planned_end_at,
        "planned_minutes": item.planned_minutes,
        "actual_start_at": item.actual_start_at,
        "actual_end_at": item.actual_end_at,
        "actual_minutes": item.actual_minutes,
        "session_status": item.session_status,
        "delivery_mode": item.delivery_mode,
        "teaching_topic": item.teaching_topic,
        "version": item.version,
    }


def attendance_view(
    item: AttendanceRecord, member: ClassMembership | None = None
) -> dict[str, Any]:
    return {
        "id": item.id,
        "class_membership_id": item.class_membership_id,
        "attendance_status": item.attendance_status,
        "expected_minutes": item.expected_minutes,
        "actual_attendance_minutes": item.actual_attendance_minutes,
        "late_minutes": item.late_minutes,
        "early_leave_minutes": item.early_leave_minutes,
        "workflow_status": item.workflow_status,
        "remarks": item.remarks,
        "version": item.version,
        "student_id": member and db_student_id(member),
    }


def db_student_id(member: ClassMembership) -> str | None:
    return None


class TeacherInput(BaseModel):
    full_name: str = Field(min_length=1, max_length=120)
    phone: str | None = None
    employment_type: str | None = None
    default_rate_amount_cent: int | None = Field(default=None, ge=0)
    default_rate_unit_minutes: int | None = Field(default=None, gt=0)
    remarks: str | None = None


class SessionInput(BaseModel):
    session_title: str = Field(min_length=1, max_length=200)
    planned_start_at: datetime
    planned_end_at: datetime
    delivery_mode: str = "OFFLINE"
    teaching_topic: str | None = None
    teaching_content: str | None = None
    location_name: str | None = None


class SessionPatch(BaseModel):
    session_title: str | None = None
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None
    teaching_topic: str | None = None
    teaching_content: str | None = None
    version: int


class ActualInput(BaseModel):
    actual_start_at: datetime
    actual_end_at: datetime
    version: int
    adjustment_reason: str | None = None


class ReasonInput(BaseModel):
    reason: str = Field(min_length=1, max_length=500)
    version: int


class AssignmentInput(BaseModel):
    teacher_id: str
    teaching_role: str
    planned_start_at: datetime | None = None
    planned_end_at: datetime | None = None


class AssignmentPatch(BaseModel):
    actual_start_at: datetime | None = None
    actual_end_at: datetime | None = None
    settleable_minutes: int | None = Field(default=None, ge=0)
    adjustment_reason: str | None = None
    version: int


class AttendanceLine(BaseModel):
    class_membership_id: str
    attendance_status: str
    actual_attendance_minutes: int | None = None
    late_minutes: int = 0
    early_leave_minutes: int = 0
    remarks: str | None = None
    version: int | None = None


class AttendanceBatch(BaseModel):
    items: list[AttendanceLine] = Field(max_length=100)


class ReviseInput(BaseModel):
    attendance_status: str
    actual_attendance_minutes: int
    late_minutes: int = 0
    early_leave_minutes: int = 0
    reason: str = Field(min_length=1, max_length=500)
    version: int


class RolloverInput(BaseModel):
    source_membership_id: str
    target_class_cycle_id: str
    effective_at: datetime
    reason: str = Field(min_length=1, max_length=500)
    financial_treatment: str = "CARRY_OVER"
    idempotency_key: str = Field(min_length=8, max_length=100)
    version: int


class RecordingInput(BaseModel):
    recording_title: str = Field(min_length=1, max_length=200)
    platform_code: str
    external_url: str
    access_code: str | None = None
    duration_minutes: int | None = Field(default=None, ge=0)


@router.get("/teachers")
def teachers(db: Db, _user: TeacherRead) -> dict[str, Any]:
    return {
        "items": [
            {
                "id": x.id,
                "teacher_no": x.teacher_no,
                "full_name": x.full_name,
                "phone_masked": mask_phone(decrypt(x.phone_ciphertext))
                if x.phone_ciphertext
                else None,
                "teacher_status": x.teacher_status,
                "version": x.version,
            }
            for x in db.scalars(select(TeacherProfile).order_by(TeacherProfile.full_name)).all()
        ]
    }


@router.post("/teachers", status_code=201)
def create_teacher(
    data: TeacherInput, request: Request, db: Db, user: TeacherManage
) -> dict[str, Any]:
    item = TeacherProfile(
        teacher_no=code("TCH"),
        full_name=data.full_name,
        phone_ciphertext=encrypt(data.phone) if data.phone else None,
        employment_type=data.employment_type,
        default_rate_amount_cent=data.default_rate_amount_cent,
        default_rate_unit_minutes=data.default_rate_unit_minutes,
        remarks=data.remarks,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(item)
    db.flush()
    audit(db, user, request, "teacher.create", "teacher", item.id)
    db.commit()
    return {"id": item.id, "teacher_no": item.teacher_no}


@router.post("/teachers/{teacher_id}/deactivate")
def deactivate_teacher(
    teacher_id: str, data: ReasonInput, request: Request, db: Db, user: TeacherManage
) -> dict[str, bool]:
    item = teacher(db, teacher_id)
    if item.version != data.version:
        raise error(409, "VERSION_CONFLICT", "教师档案已更新。")
    item.teacher_status = "INACTIVE"
    item.version += 1
    audit(db, user, request, "teacher.deactivate", "teacher", item.id, {"reason": data.reason})
    db.commit()
    return {"ok": True}


@router.get("/classes/{class_id}/sessions")
def list_sessions(class_id: str, db: Db, user: SessionRead) -> dict[str, Any]:
    cycle(db, user, class_id)
    return {
        "items": [
            session_view(x)
            for x in db.scalars(
                select(ClassSession)
                .where(ClassSession.class_cycle_id == class_id)
                .order_by(ClassSession.planned_start_at)
            ).all()
        ]
    }


@router.post("/classes/{class_id}/sessions", status_code=201)
def create_session(
    class_id: str, data: SessionInput, request: Request, db: Db, user: SessionManage
) -> dict[str, Any]:
    cycle(db, user, class_id)
    duration = minutes(data.planned_start_at, data.planned_end_at)
    service = data.planned_start_at.astimezone(ZoneInfo("Asia/Shanghai")).date()
    item = ClassSession(
        class_cycle_id=class_id,
        session_no=code("S"),
        session_title=data.session_title,
        service_date=service,
        planned_start_at=data.planned_start_at,
        planned_end_at=data.planned_end_at,
        planned_minutes=duration,
        delivery_mode=data.delivery_mode,
        teaching_topic=data.teaching_topic,
        teaching_content=data.teaching_content,
        location_name=data.location_name,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(item)
    db.flush()
    audit(db, user, request, "class_session.create", "class_session", item.id)
    db.commit()
    return session_view(item)


@router.get("/class-sessions/{session_id}")
def get_session(session_id: str, db: Db, user: SessionRead) -> dict[str, Any]:
    return session_view(session(db, user, session_id))


@router.patch("/class-sessions/{session_id}")
def patch_session(
    session_id: str, data: SessionPatch, request: Request, db: Db, user: SessionManage
) -> dict[str, Any]:
    item = session(db, user, session_id)
    if item.version != data.version or item.session_status not in {"DRAFT", "SCHEDULED"}:
        raise error(409, "SESSION_UPDATE_CONFLICT", "课次当前状态不能修改。")
    start = data.planned_start_at or item.planned_start_at
    end = data.planned_end_at or item.planned_end_at
    item.planned_minutes = minutes(start, end)
    item.planned_start_at = start
    item.planned_end_at = end
    for name in ("session_title", "teaching_topic", "teaching_content"):
        if getattr(data, name) is not None:
            setattr(item, name, getattr(data, name))
    item.version += 1
    item.updated_by = user.id
    audit(db, user, request, "class_session.update", "class_session", item.id)
    db.commit()
    return session_view(item)


def transition(
    session_id: str, data: ReasonInput | None, request: Request, db: Db, user: User, target: str
) -> dict[str, Any]:
    item = session(db, user, session_id)
    allowed = {
        "SCHEDULED": {"DRAFT"},
        "IN_PROGRESS": {"SCHEDULED"},
        "COMPLETED": {"IN_PROGRESS"},
        "CANCELLED": {"DRAFT", "SCHEDULED", "IN_PROGRESS"},
    }
    if item.session_status not in allowed[target]:
        raise error(409, "SESSION_STATUS_CONFLICT", "非法课次状态转换。")
    if target == "CANCELLED" and not data:
        raise error(422, "REASON_REQUIRED", "取消课次必须填写原因。")
    item.session_status = target
    item.version += 1
    if data and item.version - 1 != data.version:
        raise error(409, "VERSION_CONFLICT", "课次已更新。")
    if target == "CANCELLED":
        item.cancellation_reason = data.reason
    if target == "COMPLETED":
        item.completed_at = utc_now()
        item.completed_by = user.id
    audit(db, user, request, f"class_session.{target.lower()}", "class_session", item.id)
    db.commit()
    return session_view(item)


@router.post("/class-sessions/{session_id}/schedule")
def schedule(
    session_id: str, data: ReasonInput, request: Request, db: Db, user: SessionManage
) -> dict[str, Any]:
    return transition(session_id, data, request, db, user, "SCHEDULED")


@router.post("/class-sessions/{session_id}/start")
def start(
    session_id: str, data: ReasonInput, request: Request, db: Db, user: SessionManage
) -> dict[str, Any]:
    return transition(session_id, data, request, db, user, "IN_PROGRESS")


@router.post("/class-sessions/{session_id}/complete")
def complete(
    session_id: str, data: ActualInput, request: Request, db: Db, user: SessionComplete
) -> dict[str, Any]:
    item = session(db, user, session_id)
    if item.version != data.version or item.session_status != "IN_PROGRESS":
        raise error(409, "SESSION_STATUS_CONFLICT", "课次当前状态不能完成。")
    item.actual_start_at = data.actual_start_at
    item.actual_end_at = data.actual_end_at
    item.actual_minutes = minutes(data.actual_start_at, data.actual_end_at)
    item.actual_adjustment_reason = data.adjustment_reason
    item.session_status = "COMPLETED"
    item.completed_at = utc_now()
    item.completed_by = user.id
    item.version += 1
    audit(
        db,
        user,
        request,
        "class_session.complete",
        "class_session",
        item.id,
        {"actual_minutes": item.actual_minutes},
    )
    db.commit()
    return session_view(item)


@router.post("/class-sessions/{session_id}/cancel")
def cancel(
    session_id: str, data: ReasonInput, request: Request, db: Db, user: SessionManage
) -> dict[str, Any]:
    return transition(session_id, data, request, db, user, "CANCELLED")


@router.get("/class-sessions/{session_id}/teachers")
def list_assignments(session_id: str, db: Db, user: SessionRead) -> dict[str, Any]:
    session(db, user, session_id)
    rows = db.execute(
        select(SessionTeacherAssignment, TeacherProfile)
        .join(TeacherProfile)
        .where(SessionTeacherAssignment.class_session_id == session_id)
    ).all()
    return {
        "items": [
            {
                "id": a.id,
                "teacher_id": t.id,
                "teacher_name": t.full_name,
                "teaching_role": a.teaching_role,
                "planned_minutes": a.planned_minutes,
                "actual_minutes": a.actual_minutes,
                "settleable_minutes": a.settleable_minutes,
                "confirmation_status": a.confirmation_status,
                "version": a.version,
            }
            for a, t in rows
        ]
    }


@router.post("/class-sessions/{session_id}/teachers", status_code=201)
def assign_teacher(
    session_id: str, data: AssignmentInput, request: Request, db: Db, user: AssignmentManage
) -> dict[str, Any]:
    item = session(db, user, session_id)
    person = teacher(db, data.teacher_id)
    if person.teacher_status != "ACTIVE":
        raise error(409, "TEACHER_INACTIVE", "已停用教师不能安排新课次。")
    start = data.planned_start_at or item.planned_start_at
    end = data.planned_end_at or item.planned_end_at
    overlap = db.scalar(
        select(SessionTeacherAssignment)
        .join(ClassSession)
        .where(
            SessionTeacherAssignment.teacher_id == person.id,
            ClassSession.session_status != "CANCELLED",
            ClassSession.planned_start_at < end,
            ClassSession.planned_end_at > start,
        )
    )
    if overlap:
        raise error(409, "TEACHER_TIME_CONFLICT", "教师与其他课次时间冲突。")
    assignment = SessionTeacherAssignment(
        class_session_id=item.id,
        teacher_id=person.id,
        teaching_role=data.teaching_role,
        planned_start_at=start,
        planned_end_at=end,
        planned_minutes=minutes(start, end),
        rate_amount_cent=person.default_rate_amount_cent,
        rate_unit_minutes=person.default_rate_unit_minutes,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(assignment)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        raise error(409, "TEACHER_ASSIGNMENT_CONFLICT", "教师安排重复。")
    audit(db, user, request, "session_teacher.create", "session_teacher_assignment", assignment.id)
    db.commit()
    return {"id": assignment.id, "planned_minutes": assignment.planned_minutes}


@router.post("/session-teacher-assignments/{assignment_id}/confirm")
def confirm_assignment(
    assignment_id: str, data: ReasonInput, request: Request, db: Db, user: AssignmentConfirm
) -> dict[str, Any]:
    item = db.get(SessionTeacherAssignment, assignment_id)
    if not item or item.version != data.version:
        raise error(409, "VERSION_CONFLICT", "教师安排已更新。")
    item.confirmation_status = "CONFIRMED"
    item.confirmed_at = utc_now()
    item.confirmed_by = user.id
    item.actual_minutes = item.actual_minutes or item.planned_minutes
    item.settleable_minutes = item.settleable_minutes or item.actual_minutes
    item.version += 1
    audit(db, user, request, "session_teacher.confirm", "session_teacher_assignment", item.id)
    db.commit()
    return {"id": item.id, "confirmation_status": item.confirmation_status}


def eligible_members(db: Session, item: ClassSession) -> list[ClassMembership]:
    return db.scalars(
        select(ClassMembership).where(
            ClassMembership.class_cycle_id == item.class_cycle_id,
            ClassMembership.entered_at <= item.planned_start_at,
            (ClassMembership.exited_at.is_(None))
            | (ClassMembership.exited_at > item.planned_start_at),
        )
    ).all()


def validate_attendance(line: AttendanceLine, expected: int) -> int:
    actual = (
        line.actual_attendance_minutes
        if line.actual_attendance_minutes is not None
        else (expected if line.attendance_status == "PRESENT" else 0)
    )
    if (
        line.attendance_status not in {"PRESENT", "LATE", "EARLY_LEAVE", "LEAVE", "ABSENT"}
        or actual < 0
        or actual > expected
        or (line.attendance_status == "ABSENT" and actual != 0)
    ):
        raise error(422, "ATTENDANCE_INVALID", "考勤状态和分钟不一致。")
    return actual


@router.get("/class-sessions/{session_id}/attendance")
def attendance(session_id: str, db: Db, user: AttendanceRead) -> dict[str, Any]:
    item = session(db, user, session_id)
    existing = {
        r.class_membership_id: r
        for r in db.scalars(
            select(AttendanceRecord).where(AttendanceRecord.class_session_id == item.id)
        ).all()
    }
    rows = []
    for member in eligible_members(db, item):
        enrollment = db.get(CourseEnrollment, member.course_enrollment_id)
        student = db.get(Student, enrollment.student_id)
        record = existing.get(member.id)
        rows.append(
            {
                "class_membership_id": member.id,
                "student_id": student.id,
                "student_no": student.student_no,
                "full_name": student.full_name,
                "record": attendance_view(record) if record else None,
            }
        )
    return {"items": rows, "expected_minutes": item.actual_minutes or item.planned_minutes}


@router.post("/class-sessions/{session_id}/attendance/batch-draft")
def batch_draft(
    session_id: str, data: AttendanceBatch, request: Request, db: Db, user: AttendanceEdit
) -> dict[str, Any]:
    item = session(db, user, session_id)
    if item.session_status == "CANCELLED":
        raise error(409, "SESSION_CANCELLED", "取消课次不能录入考勤。")
    allowed = {m.id for m in eligible_members(db, item)}
    expected = item.actual_minutes or item.planned_minutes
    result = []
    for line in data.items:
        if line.class_membership_id not in allowed:
            result.append(
                {
                    "class_membership_id": line.class_membership_id,
                    "status": "FAILED",
                    "code": "MEMBERSHIP_NOT_ELIGIBLE",
                }
            )
            continue
        record = db.scalar(
            select(AttendanceRecord).where(
                AttendanceRecord.class_session_id == item.id,
                AttendanceRecord.class_membership_id == line.class_membership_id,
            )
        )
        try:
            actual = validate_attendance(line, expected)
        except HTTPException as exc:
            result.append(
                {
                    "class_membership_id": line.class_membership_id,
                    "status": "FAILED",
                    "code": exc.detail["code"],
                }
            )
            continue
        if record and record.workflow_status == "LOCKED":
            result.append(
                {
                    "class_membership_id": line.class_membership_id,
                    "status": "FAILED",
                    "code": "ATTENDANCE_LOCKED",
                }
            )
            continue
        if record is None:
            record = AttendanceRecord(
                class_session_id=item.id,
                class_membership_id=line.class_membership_id,
                attendance_status=line.attendance_status,
                expected_minutes=expected,
                actual_attendance_minutes=actual,
                late_minutes=line.late_minutes,
                early_leave_minutes=line.early_leave_minutes,
                remarks=line.remarks,
                created_by=user.id,
                updated_by=user.id,
            )
            db.add(record)
        else:
            record.attendance_status = line.attendance_status
            record.expected_minutes = expected
            record.actual_attendance_minutes = actual
            record.late_minutes = line.late_minutes
            record.early_leave_minutes = line.early_leave_minutes
            record.remarks = line.remarks
            record.version += 1
            record.updated_by = user.id
        db.flush()
        result.append(
            {
                "class_membership_id": line.class_membership_id,
                "status": "SUCCESS",
                "attendance_id": record.id,
            }
        )
    audit(
        db,
        user,
        request,
        "attendance.batch_draft",
        "class_session",
        item.id,
        {"count": len(result)},
    )
    db.commit()
    return {"items": result}


def attendance_action(
    session_id: str, data: ReasonInput, request: Request, db: Db, user: User, target: str
) -> dict[str, Any]:
    item = session(db, user, session_id)
    records = db.scalars(
        select(AttendanceRecord).where(AttendanceRecord.class_session_id == item.id)
    ).all()
    needed = {m.id for m in eligible_members(db, item)}
    if set(r.class_membership_id for r in records) != needed:
        raise error(409, "ATTENDANCE_INCOMPLETE", "仍有应点名成员未录考勤。")
    current = {"SUBMITTED": "DRAFT", "CONFIRMED": "SUBMITTED", "LOCKED": "CONFIRMED"}[target]
    if any(r.workflow_status != current for r in records):
        raise error(409, "ATTENDANCE_STATUS_CONFLICT", "考勤当前状态不能执行该动作。")
    if target == "LOCKED" and item.session_status != "COMPLETED":
        raise error(409, "SESSION_NOT_COMPLETED", "课次未完成不能锁定。")
    now = utc_now()
    for r in records:
        r.workflow_status = target
        r.version += 1
        setattr(r, f"{target.lower()}_at", now)
        setattr(r, f"{target.lower()}_by", user.id)
    if target == "LOCKED":
        no = (
            db.scalar(
                select(func.max(AttendanceFinalization.finalization_no)).where(
                    AttendanceFinalization.class_session_id == item.id
                )
            )
            or 0
        ) + 1
        payload = "|".join(f"{r.id}:{r.actual_attendance_minutes}" for r in records)
        db.add(
            AttendanceFinalization(
                class_session_id=item.id,
                finalization_no=no,
                locked_record_count=len(records),
                total_expected_minutes=sum(r.expected_minutes for r in records),
                total_actual_minutes=sum(r.actual_attendance_minutes for r in records),
                finalized_by=user.id,
                snapshot_hash=hashlib.sha256(payload.encode()).hexdigest(),
                reason=data.reason,
            )
        )
    audit(db, user, request, f"attendance.{target.lower()}", "class_session", item.id)
    db.commit()
    return {"ok": True, "count": len(records)}


@router.post("/class-sessions/{session_id}/attendance/submit")
def submit_attendance(
    session_id: str, data: ReasonInput, request: Request, db: Db, user: AttendanceSubmit
) -> dict[str, Any]:
    return attendance_action(session_id, data, request, db, user, "SUBMITTED")


@router.post("/class-sessions/{session_id}/attendance/confirm")
def confirm_attendance(
    session_id: str, data: ReasonInput, request: Request, db: Db, user: AttendanceConfirm
) -> dict[str, Any]:
    return attendance_action(session_id, data, request, db, user, "CONFIRMED")


@router.post("/class-sessions/{session_id}/attendance/lock")
def lock_attendance(
    session_id: str, data: ReasonInput, request: Request, db: Db, user: AttendanceLock
) -> dict[str, Any]:
    return attendance_action(session_id, data, request, db, user, "LOCKED")


@router.post("/attendance-records/{attendance_id}/revise")
def revise(
    attendance_id: str, data: ReviseInput, request: Request, db: Db, user: AttendanceRevise
) -> dict[str, Any]:
    item = db.get(AttendanceRecord, attendance_id)
    if not item or item.workflow_status != "LOCKED" or item.version != data.version:
        raise error(409, "ATTENDANCE_REVISION_CONFLICT", "只能修订当前锁定考勤。")
    old = {
        "attendance_status": item.attendance_status,
        "actual_attendance_minutes": item.actual_attendance_minutes,
        "late_minutes": item.late_minutes,
        "early_leave_minutes": item.early_leave_minutes,
    }
    line = AttendanceLine(
        class_membership_id=item.class_membership_id,
        attendance_status=data.attendance_status,
        actual_attendance_minutes=data.actual_attendance_minutes,
        late_minutes=data.late_minutes,
        early_leave_minutes=data.early_leave_minutes,
    )
    validate_attendance(line, item.expected_minutes)
    item.attendance_status = data.attendance_status
    item.actual_attendance_minutes = data.actual_attendance_minutes
    item.late_minutes = data.late_minutes
    item.early_leave_minutes = data.early_leave_minutes
    item.current_revision_no += 1
    item.workflow_status = "DRAFT"
    item.version += 1
    db.add(
        AttendanceRevision(
            attendance_record_id=item.id,
            revision_no=item.current_revision_no,
            previous_values_json=json.dumps(old),
            new_values_json=json.dumps(
                {
                    "attendance_status": data.attendance_status,
                    "actual_attendance_minutes": data.actual_attendance_minutes,
                }
            ),
            change_type="CORRECTION",
            reason=data.reason,
            request_id=request.state.correlation_id,
            created_by=user.id,
        )
    )
    audit(
        db,
        user,
        request,
        "attendance.revise",
        "attendance_record",
        item.id,
        {"reason": data.reason},
    )
    db.commit()
    return attendance_view(item)


@router.post("/enrollments/{enrollment_id}/rollover-preview")
def rollover_preview(
    enrollment_id: str, data: RolloverInput, db: Db, user: Rollover
) -> dict[str, Any]:
    enrollment = db.get(CourseEnrollment, enrollment_id)
    source = db.get(ClassMembership, data.source_membership_id)
    target = cycle(db, user, data.target_class_cycle_id)
    ok = bool(
        enrollment
        and source
        and source.course_enrollment_id == enrollment_id
        and source.membership_status == "ACTIVE"
        and target.course_offering_version_id == enrollment.course_offering_version_id
    )
    return {
        "allowed": ok,
        "target_capacity": target.capacity,
        "active_member_count": db.scalar(
            select(func.count())
            .select_from(ClassMembership)
            .where(
                ClassMembership.class_cycle_id == target.id,
                ClassMembership.membership_status == "ACTIVE",
            )
        )
        or 0,
    }


@router.post("/enrollments/{enrollment_id}/rollover")
def rollover(
    enrollment_id: str, data: RolloverInput, request: Request, db: Db, user: Rollover
) -> dict[str, Any]:
    prior = db.scalar(
        select(EnrollmentRolloverRequest).where(
            EnrollmentRolloverRequest.idempotency_key == data.idempotency_key
        )
    )
    if prior:
        return {"id": prior.result_membership_id, "idempotent": True}
    enrollment = db.get(CourseEnrollment, enrollment_id)
    source = db.get(ClassMembership, data.source_membership_id)
    target = cycle(db, user, data.target_class_cycle_id)
    if (
        not enrollment
        or source is None
        or source.course_enrollment_id != enrollment_id
        or source.membership_status != "ACTIVE"
        or target.course_offering_version_id != enrollment.course_offering_version_id
    ):
        raise error(409, "ROLLOVER_INVALID", "滚班前提不满足。")
    count = (
        db.scalar(
            select(func.count())
            .select_from(ClassMembership)
            .where(
                ClassMembership.class_cycle_id == target.id,
                ClassMembership.membership_status == "ACTIVE",
            )
        )
        or 0
    )
    if target.capacity and count >= target.capacity:
        raise error(409, "TARGET_CLASS_FULL", "目标班已满。")
    source.membership_status = "ROLLED_OVER"
    source.exited_at = data.effective_at
    source.exit_reason = data.reason
    source.version += 1
    new = ClassMembership(
        class_cycle_id=target.id,
        course_enrollment_id=enrollment_id,
        entered_at=data.effective_at,
        membership_status="ACTIVE",
        entry_reason="ROLLOVER",
        previous_membership_id=source.id,
        financial_treatment=data.financial_treatment,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(new)
    db.flush()
    db.add(
        EnrollmentRolloverRequest(
            course_enrollment_id=enrollment_id,
            source_membership_id=source.id,
            target_class_cycle_id=target.id,
            idempotency_key=data.idempotency_key,
            result_membership_id=new.id,
            created_by=user.id,
        )
    )
    audit(
        db,
        user,
        request,
        "enrollment.rollover",
        "course_enrollment",
        enrollment_id,
        {"source": source.id, "target": target.id},
    )
    db.commit()
    return {"id": new.id, "idempotent": False}


def valid_url(value: str) -> None:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc or parsed.username or parsed.password:
        raise error(422, "RECORDING_URL_INVALID", "录屏地址必须为不含账户信息的 HTTPS 地址。")


@router.get("/class-sessions/{session_id}/recordings")
def recordings(session_id: str, db: Db, user: RecordingRead) -> dict[str, Any]:
    session(db, user, session_id)
    return {
        "items": [
            {
                "id": x.id,
                "recording_title": x.recording_title,
                "platform_code": x.platform_code,
                "external_url": x.external_url,
                "recording_status": x.recording_status,
                "review_status": x.review_status,
                "version": x.version,
            }
            for x in db.scalars(
                select(SessionRecording).where(SessionRecording.class_session_id == session_id)
            ).all()
        ]
    }


@router.post("/class-sessions/{session_id}/recordings", status_code=201)
def add_recording(
    session_id: str, data: RecordingInput, request: Request, db: Db, user: RecordingManage
) -> dict[str, Any]:
    session(db, user, session_id)
    valid_url(data.external_url)
    item = SessionRecording(
        class_session_id=session_id,
        recording_title=data.recording_title,
        platform_code=data.platform_code,
        external_url=data.external_url,
        access_code_ciphertext=encrypt(data.access_code) if data.access_code else None,
        duration_minutes=data.duration_minutes,
        created_by=user.id,
        updated_by=user.id,
    )
    db.add(item)
    db.flush()
    audit(db, user, request, "recording.create", "session_recording", item.id)
    db.commit()
    return {"id": item.id, "external_url": item.external_url}


@router.post("/session-recordings/{recording_id}/reveal-access-code")
def reveal_code(
    recording_id: str, data: ReasonInput, request: Request, db: Db, user: RecordingReveal
) -> dict[str, str]:
    item = db.get(SessionRecording, recording_id)
    if not item or not item.access_code_ciphertext:
        raise error(404, "ACCESS_CODE_NOT_FOUND", "未设置访问口令。")
    audit(
        db,
        user,
        request,
        "recording.access_code.reveal",
        "session_recording",
        item.id,
        {"reason": data.reason},
    )
    db.commit()
    return {"access_code": decrypt(item.access_code_ciphertext)}


@router.get("/classes/{class_id}/teaching-progress")
def progress(class_id: str, db: Db, user: SessionRead) -> dict[str, Any]:
    cycle_item = cycle(db, user, class_id)
    sessions = db.scalars(select(ClassSession).where(ClassSession.class_cycle_id == class_id)).all()
    offering = db.get(CourseOfferingVersion, cycle_item.course_offering_version_id)
    return {
        "planned_minutes": sum(
            x.planned_minutes for x in sessions if x.session_status != "CANCELLED"
        ),
        "completed_minutes": sum(
            x.actual_minutes or 0 for x in sessions if x.session_status == "COMPLETED"
        ),
        "cancelled_minutes": sum(
            x.planned_minutes for x in sessions if x.session_status == "CANCELLED"
        ),
        "curriculum_version_id": offering.curriculum_version_id,
    }


@router.get("/teachers/{teacher_id}/teaching-summary")
def teaching_summary(teacher_id: str, db: Db, _user: SummaryRead) -> dict[str, Any]:
    rows = db.execute(
        select(SessionTeacherAssignment, ClassSession)
        .join(ClassSession)
        .where(SessionTeacherAssignment.teacher_id == teacher_id)
    ).all()
    valid = [(a, s) for a, s in rows if s.session_status != "CANCELLED"]
    return {
        "planned_teaching_minutes": sum(a.planned_minutes for a, s in valid),
        "actual_teaching_minutes": sum(a.actual_minutes or 0 for a, s in valid),
        "confirmed_teaching_minutes": sum(
            (a.actual_minutes or 0)
            for a, s in valid
            if s.session_status == "COMPLETED" and a.confirmation_status == "CONFIRMED"
        ),
        "settleable_minutes": sum(
            (a.settleable_minutes or 0)
            for a, s in valid
            if s.session_status == "COMPLETED" and a.confirmation_status == "CONFIRMED"
        ),
        "completed_session_count": sum(1 for _, s in valid if s.session_status == "COMPLETED"),
    }
