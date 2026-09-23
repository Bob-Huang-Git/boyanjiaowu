# ruff: noqa: B008, E501, E701, E702, I001
# fmt: off
"""Prompt 6 第二、三节：政府项目、资格案与学校垫资。

关键设计约束：
- ``FundingCase`` 属于 **CourseEnrollment**，不属于 ClassCycle。
  因此滚班（新建 ClassMembership）不会重建或重置资格案 —— 这是 P6 必测用例
  「滚班不自动重置培训补贴资格」的结构性保证，而不是靠额外判断逻辑实现。
- 同一学员的多门课程各自持有独立 FundingCase（唯一约束落在 course_enrollment_id 上）。
- 非退役身份的学员不得建立 FundingCase（P6 必测用例）。
- 学校实际成本（ProjectCost）与政府补贴权益、政府应收**互不推导**。
"""

import json
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.api import audit, checked, enrollment_for, error, scoped
from app.core.models import (
    ClassCycle,
    EligibilityAssessment,
    FundingCase,
    FundingCaseComponent,
    FundingProgram,
    FundingProgramVersion,
    FundingSource,
    ProgramFundingSource,
    ProjectCost,
    ProjectCostAllocation,
    User,
    VeteranIdentity,
    utc_now,
)
from app.modules.iam.router import Db, require_permission

router = APIRouter(prefix="/api", tags=["funding"])

ProgramManage = Annotated[User, Depends(require_permission("funding_program.manage"))]
ProgramRead = Annotated[User, Depends(require_permission("funding_program.read"))]
CaseRead = Annotated[User, Depends(require_permission("funding_case.read"))]
CaseManage = Annotated[User, Depends(require_permission("funding_case.manage"))]
CaseAssess = Annotated[User, Depends(require_permission("funding_case.assess"))]
CostManage = Annotated[User, Depends(require_permission("project_cost.manage"))]
CostRead = Annotated[User, Depends(require_permission("project_cost.read"))]

COMPONENT_TYPES = ("TRAINING_SUBSIDY", "MEAL_ALLOWANCE", "LODGING_ALLOWANCE")


class ProgramInput(BaseModel):
    program_code: str = Field(min_length=1, max_length=40)
    program_name: str = Field(min_length=1, max_length=120)
    department: str = Field(min_length=1, max_length=80)
    remarks: str | None = None


class ProgramVersionInput(BaseModel):
    version_no: str = Field(min_length=1, max_length=30)
    region: str = Field(min_length=1, max_length=60)
    department: str = Field(min_length=1, max_length=80)
    effective_from: date
    effective_to: date | None = None
    policy_document_no: str | None = Field(default=None, max_length=80)
    policy_document_file_object_id: str | None = None
    remarks: str | None = None


class FundingSourceInput(BaseModel):
    source_code: str = Field(min_length=1, max_length=40)
    source_name: str = Field(min_length=1, max_length=120)
    department: str = Field(min_length=1, max_length=80)


class ProgramSourceInput(BaseModel):
    funding_source_id: str
    allocation_rule_type: str = Field(pattern="^(EXCLUSIVE|SPLIT_RATIO)$")
    allocation_ratio_bp: int | None = Field(default=None, ge=0, le=10000)
    priority: int = Field(default=1, ge=1)


class FundingCaseInput(BaseModel):
    funding_program_version_id: str
    remarks: str | None = None


class AssessmentInput(BaseModel):
    assessment_status: str = Field(pattern="^(PASSED|FAILED|RETURNED)$")
    basis: dict = Field(default_factory=dict)
    assessed_on: date | None = None
    note: str | None = None


class ComponentStatusInput(BaseModel):
    component_status: str = Field(pattern="^(PENDING|ELIGIBLE|INELIGIBLE|CLOSED)$")
    note: str | None = None
    version: int = Field(ge=1)


class VersionInput(BaseModel):
    version: int = Field(ge=1)


class ProjectCostInput(BaseModel):
    cost_type: str = Field(pattern="^(TEACHER_FEE|VENUE|LODGING|OTHER)$")
    amount_cent: int = Field(ge=0)
    period_start: date | None = None
    period_end: date | None = None
    funding_program_version_id: str | None = None
    note: str | None = None
    idempotency_key: str = Field(min_length=1, max_length=100)


class CostAllocationInput(BaseModel):
    allocation_basis: str = Field(pattern="^(PER_STUDENT|PER_MINUTE|MANUAL)$")
    course_enrollment_id: str | None = None
    student_id: str | None = None
    amount_cent: int = Field(ge=0)
    note: str | None = None


def program_version_for(db, user, item_id):  # noqa: ANN001
    return scoped(db, FundingProgramVersion, item_id, user, "FUNDING_PROGRAM_VERSION_NOT_FOUND", "政府项目版本")


def funding_case_for(db, user, item_id):  # noqa: ANN001
    return scoped(db, FundingCase, item_id, user, "FUNDING_CASE_NOT_FOUND", "政府项目资格案")


def require_published_version(db, version: FundingProgramVersion) -> None:
    if version.program_status != "PUBLISHED":
        raise error(409, "PROGRAM_VERSION_NOT_PUBLISHED", "政府项目版本尚未发布，不能用于资格立项。")


# ---------------------------------------------------------------------------
# 项目目录与版本
# ---------------------------------------------------------------------------


@router.post("/funding-programs")
def create_program(payload: ProgramInput, request: Request, db: Db, user: ProgramManage) -> dict:
    existing = db.scalar(select(FundingProgram).where(FundingProgram.organization_id == user.organization_id, FundingProgram.program_code == payload.program_code))
    if existing:
        raise error(409, "FUNDING_PROGRAM_EXISTS", "该项目编码已存在。")
    program = FundingProgram(organization_id=user.organization_id, program_code=payload.program_code, program_name=payload.program_name, department=payload.department, remarks=payload.remarks, created_by=user.id)
    db.add(program)
    db.flush()
    audit(db, user, request, "funding_program.create", "funding_program", program.id)
    db.commit()
    return {"id": program.id, "program_code": program.program_code, "program_name": program.program_name, "department": program.department}


@router.get("/funding-programs")
def list_programs(db: Db, user: ProgramRead) -> dict:
    rows = db.scalars(select(FundingProgram).where(FundingProgram.organization_id == user.organization_id).order_by(FundingProgram.program_code)).all()
    return {"items": [{"id": r.id, "program_code": r.program_code, "program_name": r.program_name, "department": r.department, "active": r.active} for r in rows]}


@router.post("/funding-programs/{program_id}/versions")
def create_program_version(program_id: str, payload: ProgramVersionInput, request: Request, db: Db, user: ProgramManage) -> dict:
    program = scoped(db, FundingProgram, program_id, user, "FUNDING_PROGRAM_NOT_FOUND", "政府项目")
    if payload.effective_to and payload.effective_to < payload.effective_from:
        raise error(422, "INVALID_EFFECTIVE_RANGE", "生效结束日期不能早于生效开始日期。")
    existing = db.scalar(select(FundingProgramVersion).where(FundingProgramVersion.funding_program_id == program.id, FundingProgramVersion.version_no == payload.version_no))
    if existing:
        raise error(409, "PROGRAM_VERSION_EXISTS", "该项目版本号已存在。")
    version = FundingProgramVersion(
        organization_id=user.organization_id,
        funding_program_id=program.id,
        version_no=payload.version_no,
        region=payload.region,
        department=payload.department,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        policy_document_no=payload.policy_document_no,
        policy_document_file_object_id=payload.policy_document_file_object_id,
        remarks=payload.remarks,
        created_by=user.id,
    )
    db.add(version)
    db.flush()
    audit(db, user, request, "funding_program_version.create", "funding_program_version", version.id, {"version_no": version.version_no})
    db.commit()
    return {"id": version.id, "version_no": version.version_no, "region": version.region, "program_status": version.program_status, "version": version.version}


@router.post("/funding-program-versions/{item_id}/publish")
def publish_program_version(item_id: str, payload: VersionInput, request: Request, db: Db, user: ProgramManage) -> dict:
    version = program_version_for(db, user, item_id)
    checked(version, payload.version)
    if version.program_status == "PUBLISHED":
        raise error(409, "PROGRAM_VERSION_ALREADY_PUBLISHED", "该项目版本已发布。")
    if version.program_status == "RETIRED":
        raise error(409, "PROGRAM_VERSION_RETIRED", "已停用的项目版本不能重新发布。")
    sources = db.scalars(select(ProgramFundingSource).where(ProgramFundingSource.funding_program_version_id == version.id, ProgramFundingSource.active.is_(True))).all()
    if not sources:
        raise error(409, "FUNDING_SOURCE_REQUIRED", "发布前必须至少关联一个资金来源与分摊规则。")
    ratios = [s.allocation_ratio_bp for s in sources if s.allocation_rule_type == "SPLIT_RATIO"]
    if ratios and sum(r or 0 for r in ratios) != 10000:
        raise error(422, "ALLOCATION_RATIO_INVALID", "分摊比例之和必须等于 10000 基点（100%）。")
    version.program_status = "PUBLISHED"
    version.published_at = __import__("app.core.models", fromlist=["utc_now"]).utc_now()
    version.published_by = user.id
    version.version += 1
    db.flush()
    audit(db, user, request, "funding_program_version.publish", "funding_program_version", version.id)
    db.commit()
    return {"id": version.id, "program_status": version.program_status}


@router.post("/funding-sources")
def create_funding_source(payload: FundingSourceInput, request: Request, db: Db, user: ProgramManage) -> dict:
    existing = db.scalar(select(FundingSource).where(FundingSource.organization_id == user.organization_id, FundingSource.source_code == payload.source_code))
    if existing:
        raise error(409, "FUNDING_SOURCE_EXISTS", "该资金来源编码已存在。")
    source = FundingSource(organization_id=user.organization_id, source_code=payload.source_code, source_name=payload.source_name, department=payload.department, created_by=user.id)
    db.add(source)
    db.flush()
    audit(db, user, request, "funding_source.create", "funding_source", source.id)
    db.commit()
    return {"id": source.id, "source_code": source.source_code, "department": source.department}


@router.post("/funding-program-versions/{item_id}/funding-sources")
def link_funding_source(item_id: str, payload: ProgramSourceInput, request: Request, db: Db, user: ProgramManage) -> dict:
    version = program_version_for(db, user, item_id)
    if version.program_status == "PUBLISHED":
        raise error(409, "PROGRAM_VERSION_PUBLISHED", "已发布的项目版本不能修改资金来源，请新建版本。")
    source = scoped(db, FundingSource, payload.funding_source_id, user, "FUNDING_SOURCE_NOT_FOUND", "资金来源")
    if payload.allocation_rule_type == "SPLIT_RATIO" and payload.allocation_ratio_bp is None:
        raise error(422, "ALLOCATION_RATIO_REQUIRED", "按比例分摊必须给出分配比例。")
    existing = db.scalar(select(ProgramFundingSource).where(ProgramFundingSource.funding_program_version_id == version.id, ProgramFundingSource.funding_source_id == source.id))
    if existing:
        raise error(409, "PROGRAM_SOURCE_EXISTS", "该资金来源已关联到此项目版本。")
    link = ProgramFundingSource(
        organization_id=user.organization_id,
        funding_program_version_id=version.id,
        funding_source_id=source.id,
        allocation_rule_type=payload.allocation_rule_type,
        allocation_ratio_bp=payload.allocation_ratio_bp,
        priority=payload.priority,
        created_by=user.id,
    )
    db.add(link)
    db.flush()
    audit(db, user, request, "program_funding_source.link", "funding_program_version", version.id, {"funding_source_id": source.id})
    db.commit()
    return {"id": link.id, "allocation_rule_type": link.allocation_rule_type, "allocation_ratio_bp": link.allocation_ratio_bp}


# ---------------------------------------------------------------------------
# 资格案
# ---------------------------------------------------------------------------


@router.post("/enrollments/{enrollment_id}/funding-case")
def open_funding_case(enrollment_id: str, payload: FundingCaseInput, request: Request, db: Db, user: CaseManage) -> dict:
    enrollment = enrollment_for(db, user, enrollment_id)

    # P6 必测：非退役身份的学员不能建立 FundingCase
    identity = db.scalar(select(VeteranIdentity).where(VeteranIdentity.organization_id == user.organization_id, VeteranIdentity.student_id == enrollment.student_id))
    if identity is None:
        raise error(409, "VETERAN_IDENTITY_REQUIRED", "该学员没有退役士兵身份主档，不能建立政府项目资格案。")
    if identity.verified_status != "VERIFIED":
        raise error(409, "VETERAN_IDENTITY_NOT_VERIFIED", "退役身份尚未核验通过，不能建立政府项目资格案。")

    version = program_version_for(db, user, payload.funding_program_version_id)
    require_published_version(db, version)

    existing = db.scalar(select(FundingCase).where(FundingCase.course_enrollment_id == enrollment.id))
    if existing:
        raise error(409, "FUNDING_CASE_EXISTS", "该课程报名已有政府项目资格案。滚班请沿用原资格案，不要新建。")

    snapshot = {
        "funding_program_version_id": version.id,
        "version_no": version.version_no,
        "region": version.region,
        "department": version.department,
        "effective_from": version.effective_from.isoformat(),
        "effective_to": version.effective_to.isoformat() if version.effective_to else None,
        "policy_document_no": version.policy_document_no,
    }
    case = FundingCase(
        organization_id=user.organization_id,
        course_enrollment_id=enrollment.id,
        student_id=enrollment.student_id,
        funding_program_version_id=version.id,
        region=version.region,
        department=version.department,
        case_status="ASSESSING",
        policy_snapshot_json=json.dumps(snapshot, ensure_ascii=False),
        remarks=payload.remarks,
        created_by=user.id,
    )
    db.add(case)
    db.flush()
    for component_type in COMPONENT_TYPES:
        db.add(FundingCaseComponent(organization_id=user.organization_id, funding_case_id=case.id, component_type=component_type, component_status="PENDING", created_by=user.id))
    db.flush()
    audit(db, user, request, "funding_case.open", "funding_case", case.id, {"enrollment_id": enrollment.id})
    db.commit()
    return {"id": case.id, "course_enrollment_id": case.course_enrollment_id, "case_status": case.case_status, "region": case.region, "department": case.department}


@router.get("/enrollments/{enrollment_id}/funding-case")
def get_case_by_enrollment(enrollment_id: str, db: Db, user: CaseRead) -> dict:
    enrollment = enrollment_for(db, user, enrollment_id)
    case = db.scalar(select(FundingCase).where(FundingCase.course_enrollment_id == enrollment.id))
    if case is None:
        return {"exists": False, "course_enrollment_id": enrollment.id}
    return {"exists": True, **case_view(db, case)}


def case_view(db, case: FundingCase) -> dict:  # noqa: ANN001
    components = db.scalars(select(FundingCaseComponent).where(FundingCaseComponent.funding_case_id == case.id)).all()
    current = db.scalar(select(EligibilityAssessment).where(EligibilityAssessment.funding_case_id == case.id, EligibilityAssessment.is_current.is_(True)))
    return {
        "id": case.id,
        "course_enrollment_id": case.course_enrollment_id,
        "student_id": case.student_id,
        "case_status": case.case_status,
        "region": case.region,
        "department": case.department,
        "funding_program_version_id": case.funding_program_version_id,
        "components": [{"component_type": c.component_type, "component_status": c.component_status} for c in components],
        "current_assessment": None if current is None else {"id": current.id, "assessment_version": current.assessment_version, "assessment_status": current.assessment_status},
        "version": case.version,
    }


@router.get("/funding-cases/{item_id}")
def get_funding_case(item_id: str, db: Db, user: CaseRead) -> dict:
    case = funding_case_for(db, user, item_id)
    return case_view(db, case)


@router.post("/funding-cases/{item_id}/assessments")
def assess_funding_case(item_id: str, payload: AssessmentInput, request: Request, db: Db, user: CaseAssess) -> dict:
    """资格评定：每次产生新版本，``is_current`` 保证只有一条当前有效。

    注意执行顺序：必须**先把旧记录退出当前有效**并 flush，再插入新记录，
    否则会撞上 ``uq_eligibility_assessment_current`` 部分唯一索引。
    """
    case = funding_case_for(db, user, item_id)
    previous = db.scalar(select(EligibilityAssessment).where(EligibilityAssessment.funding_case_id == case.id, EligibilityAssessment.is_current.is_(True)))
    next_version = 1
    if previous is not None:
        next_version = previous.assessment_version + 1
        previous.is_current = False
        previous.version += 1
        db.flush()  # 显式 flush：先让旧记录退出部分唯一索引

    record = EligibilityAssessment(
        organization_id=user.organization_id,
        funding_case_id=case.id,
        assessment_version=next_version,
        assessment_status=payload.assessment_status,
        is_current=True,
        basis_json=json.dumps(payload.basis, ensure_ascii=False),
        assessed_on=payload.assessed_on or date.today(),
        assessed_by=user.id,
        note=payload.note,
        created_by=user.id,
    )
    db.add(record)
    db.flush()
    if payload.assessment_status == "PASSED":
        case.case_status = "ELIGIBLE"
    elif payload.assessment_status == "FAILED":
        case.case_status = "INELIGIBLE"
    else:
        case.case_status = "ASSESSING"
    case.version += 1
    db.flush()
    audit(db, user, request, "funding_case.assess", "funding_case", case.id, {"assessment_version": next_version, "status": payload.assessment_status})
    db.commit()
    return {"id": record.id, "assessment_version": record.assessment_version, "assessment_status": record.assessment_status, "case_status": case.case_status}


@router.get("/funding-cases/{item_id}/assessments")
def list_assessments(item_id: str, db: Db, user: CaseRead) -> dict:
    case = funding_case_for(db, user, item_id)
    rows = db.scalars(select(EligibilityAssessment).where(EligibilityAssessment.funding_case_id == case.id).order_by(EligibilityAssessment.assessment_version)).all()
    return {"items": [{"id": r.id, "assessment_version": r.assessment_version, "assessment_status": r.assessment_status, "is_current": r.is_current, "assessed_on": r.assessed_on.isoformat() if r.assessed_on else None, "note": r.note, "basis": json.loads(r.basis_json) if r.basis_json else None} for r in rows]}


@router.post("/funding-cases/{item_id}/components/{component_type}/status")
def set_component_status(item_id: str, component_type: str, payload: ComponentStatusInput, request: Request, db: Db, user: CaseAssess) -> dict:
    if component_type not in COMPONENT_TYPES:
        raise error(422, "COMPONENT_TYPE_INVALID", "不支持的资格组成成分。")
    case = funding_case_for(db, user, item_id)
    component = db.scalar(select(FundingCaseComponent).where(FundingCaseComponent.funding_case_id == case.id, FundingCaseComponent.component_type == component_type))
    if component is None:
        raise error(404, "COMPONENT_NOT_FOUND", "未找到该资格组成成分。")
    checked(component, payload.version)
    component.component_status = payload.component_status
    component.note = payload.note or component.note
    component.version += 1
    db.flush()
    audit(db, user, request, "funding_case.component_status", "funding_case", case.id, {"component_type": component_type, "status": payload.component_status})
    db.commit()
    return {"component_type": component_type, "component_status": component.component_status}


# ---------------------------------------------------------------------------
# 学校垫资成本
# ---------------------------------------------------------------------------


@router.post("/class-cycles/{class_cycle_id}/project-costs")
def create_project_cost(class_cycle_id: str, payload: ProjectCostInput, request: Request, db: Db, user: CostManage) -> dict:
    """登记学校实际垫付成本。同一幂等键重复提交返回原记录。"""
    cycle = scoped(db, ClassCycle, class_cycle_id, user, "CLASS_CYCLE_NOT_FOUND", "班级")
    existing = db.scalar(select(ProjectCost).where(ProjectCost.organization_id == user.organization_id, ProjectCost.idempotency_key == payload.idempotency_key))
    if existing:
        return {"id": existing.id, "cost_type": existing.cost_type, "amount_cent": existing.amount_cent, "cost_status": existing.cost_status, "duplicated": True}
    if payload.period_start and payload.period_end and payload.period_end < payload.period_start:
        raise error(422, "INVALID_PERIOD", "成本期间结束日期不能早于开始日期。")
    cost = ProjectCost(
        organization_id=user.organization_id,
        class_cycle_id=cycle.id,
        funding_program_version_id=payload.funding_program_version_id,
        cost_type=payload.cost_type,
        period_start=payload.period_start,
        period_end=payload.period_end,
        amount_cent=payload.amount_cent,
        note=payload.note,
        idempotency_key=payload.idempotency_key,
        created_by=user.id,
    )
    db.add(cost)
    db.flush()
    audit(db, user, request, "project_cost.create", "project_cost", cost.id, {"amount_cent": cost.amount_cent})
    db.commit()
    return {"id": cost.id, "cost_type": cost.cost_type, "amount_cent": cost.amount_cent, "cost_status": cost.cost_status, "duplicated": False}


@router.post("/project-costs/{item_id}/confirm")
def confirm_project_cost(item_id: str, payload: VersionInput, request: Request, db: Db, user: CostManage) -> dict:
    cost = scoped(db, ProjectCost, item_id, user, "PROJECT_COST_NOT_FOUND", "学校成本")
    checked(cost, payload.version)
    if cost.cost_status != "DRAFT":
        raise error(409, "INVALID_COST_STATUS", "仅草稿状态的学校成本可以确认。")
    cost.cost_status = "CONFIRMED"
    cost.confirmed_at = utc_now()
    cost.confirmed_by = user.id
    cost.version += 1
    db.flush()
    audit(db, user, request, "project_cost.confirm", "project_cost", cost.id)
    db.commit()
    return {"id": cost.id, "cost_status": cost.cost_status}


@router.post("/project-costs/{item_id}/allocations")
def allocate_project_cost(item_id: str, payload: CostAllocationInput, request: Request, db: Db, user: CostManage) -> dict:
    """成本分摊：仅用于学校内部成本核算。**不产生学员应付，也不产生政府应收。**"""
    cost = scoped(db, ProjectCost, item_id, user, "PROJECT_COST_NOT_FOUND", "学校成本")
    if cost.cost_status != "DRAFT":
        raise error(409, "COST_ALLOCATION_LOCKED", "已确认的成本不能再修改分摊。")
    if payload.course_enrollment_id and payload.student_id is None:
        enrollment = enrollment_for(db, user, payload.course_enrollment_id)
        payload = payload.model_copy(update={"student_id": enrollment.student_id})
    allocated = db.scalars(select(ProjectCostAllocation).where(ProjectCostAllocation.project_cost_id == cost.id)).all()
    total = sum(a.amount_cent for a in allocated) + payload.amount_cent
    if total > cost.amount_cent:
        raise error(409, "ALLOCATION_EXCEEDS_COST", "分摊合计不得超过成本总额。")
    existing = db.scalar(select(ProjectCostAllocation).where(ProjectCostAllocation.project_cost_id == cost.id, ProjectCostAllocation.course_enrollment_id == payload.course_enrollment_id))
    if existing:
        raise error(409, "ALLOCATION_EXISTS", "该报名已有分摊记录。")
    allocation = ProjectCostAllocation(
        organization_id=user.organization_id,
        project_cost_id=cost.id,
        allocation_basis=payload.allocation_basis,
        student_id=payload.student_id,
        course_enrollment_id=payload.course_enrollment_id,
        amount_cent=payload.amount_cent,
        note=payload.note,
        created_by=user.id,
    )
    db.add(allocation)
    db.flush()
    audit(db, user, request, "project_cost.allocate", "project_cost", cost.id, {"amount_cent": allocation.amount_cent})
    db.commit()
    return {"id": allocation.id, "amount_cent": allocation.amount_cent, "allocated_total_cent": total}


@router.get("/class-cycles/{class_cycle_id}/project-costs")
def list_project_costs(class_cycle_id: str, db: Db, user: CostRead) -> dict:
    cycle = scoped(db, ClassCycle, class_cycle_id, user, "CLASS_CYCLE_NOT_FOUND", "班级")
    rows = db.scalars(select(ProjectCost).where(ProjectCost.class_cycle_id == cycle.id).order_by(ProjectCost.created_at)).all()
    return {"items": [{"id": r.id, "cost_type": r.cost_type, "amount_cent": r.amount_cent, "cost_status": r.cost_status, "period_start": r.period_start.isoformat() if r.period_start else None, "period_end": r.period_end.isoformat() if r.period_end else None} for r in rows]}
