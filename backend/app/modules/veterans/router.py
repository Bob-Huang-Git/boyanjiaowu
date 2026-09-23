# ruff: noqa: B008, E501, E701, E702, I001
# fmt: off
"""Prompt 6 第一节：退役士兵身份层。

设计约束：
- 稳定身份与时间性属性分离：``VeteranIdentity`` 存稳定身份，
  ``VeteranAttributeHistory`` 存随时间变化的属性，禁止覆盖旧值。
- 退役证号加密保存（AES-GCM），并提供 HMAC 盲索引用于查重。
- 查重命中只提示人工核实，**不自动合并**（与 Prompt 2 对身份证的口径一致）。
- 明文查看是独立权限、必须填理由、必须留审计。
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field
from sqlalchemy import select

from app.core.api import audit, business_code, error, scoped
from app.core.models import Student, User, VeteranAttributeHistory, VeteranIdentity, VeteranIdentityEvidence, VeteranIdentityVerification
from app.core.pii import blind_index, decrypt, encrypt
from app.modules.iam.router import Db, require_permission

router = APIRouter(prefix="/api", tags=["veterans"])

VeteranRead = Annotated[User, Depends(require_permission("veteran_identity.read"))]
VeteranManage = Annotated[User, Depends(require_permission("veteran_identity.manage"))]
VeteranVerify = Annotated[User, Depends(require_permission("veteran_identity.verify"))]
VeteranPlaintext = Annotated[User, Depends(require_permission("veteran_identity.view_plaintext"))]


class VeteranIdentityInput(BaseModel):
    retirement_card_no: str | None = Field(default=None, max_length=80)
    retired_on: date | None = None
    service_branch: str | None = Field(default=None, max_length=80)
    remarks: str | None = None


class VerificationInput(BaseModel):
    verification_status: str = Field(pattern="^(PASSED|FAILED|PENDING)$")
    method: str | None = Field(default=None, max_length=60)
    verified_on: date | None = None
    note: str | None = None


class AttributeInput(BaseModel):
    attribute_code: str = Field(min_length=1, max_length=60)
    value_text: str | None = Field(default=None, max_length=200)
    value_date: date | None = None
    effective_from: date
    effective_to: date | None = None
    source: str | None = Field(default=None, max_length=120)
    note: str | None = None


class ReasonInput(BaseModel):
    reason: str = Field(min_length=1, max_length=200)


def mask_card(number: str) -> str:
    """退役证号脱敏：仅保留末 4 位。"""
    return f"退役证 ****{number[-4:]}" if len(number) >= 4 else "退役证 ****"


def identity_for(db, user, item_id):  # noqa: ANN001
    return scoped(db, VeteranIdentity, item_id, user, "VETERAN_IDENTITY_NOT_FOUND", "退役身份")


def identity_view(item: VeteranIdentity, plaintext: str | None = None) -> dict:
    """默认视图不含明文；``plaintext`` 仅在独立权限路径下传入。"""
    return {
        "id": item.id,
        "student_id": item.student_id,
        "retirement_card_no_masked": item.retirement_card_no_masked,
        "retirement_card_no_plaintext": plaintext,
        "has_retirement_card_no": item.retirement_card_no_encrypted is not None,
        "retired_on": item.retired_on.isoformat() if item.retired_on else None,
        "service_branch": item.service_branch,
        "identity_status": item.identity_status,
        "verified_status": item.verified_status,
        "version": item.version,
    }


@router.get("/students/{student_id}/veteran-identity")
def get_identity_by_student(student_id: str, db: Db, user: VeteranRead) -> dict:
    student = scoped(db, Student, student_id, user, "STUDENT_NOT_FOUND", "学员")
    item = db.scalar(select(VeteranIdentity).where(VeteranIdentity.student_id == student.id))
    if item is None:
        return {"exists": False, "student_id": student.id}
    return {"exists": True, **identity_view(item)}


@router.post("/students/{student_id}/veteran-identity")
def create_identity(student_id: str, payload: VeteranIdentityInput, request: Request, db: Db, user: VeteranManage) -> dict:
    student = scoped(db, Student, student_id, user, "STUDENT_NOT_FOUND", "学员")
    existing = db.scalar(select(VeteranIdentity).where(VeteranIdentity.student_id == student.id))
    if existing:
        raise error(409, "VETERAN_IDENTITY_EXISTS", "该学员已有退役身份主档，同一自然人只能有一份。")

    encrypted = hmac_value = masked = None
    if payload.retirement_card_no:
        normalized = payload.retirement_card_no.strip()
        hmac_value = blind_index(normalized)
        duplicate = db.scalar(select(VeteranIdentity).where(VeteranIdentity.organization_id == user.organization_id, VeteranIdentity.retirement_card_no_hmac == hmac_value))
        if duplicate:
            raise error(409, "VETERAN_CARD_ALREADY_BOUND", "该退役证号已绑定其他学员。系统不会自动合并，请人工核实后再处理。")
        encrypted = encrypt(normalized)
        masked = mask_card(normalized)

    item = VeteranIdentity(
        organization_id=user.organization_id,
        student_id=student.id,
        retirement_card_no_encrypted=encrypted,
        retirement_card_no_hmac=hmac_value,
        retirement_card_no_masked=masked,
        retirement_card_no_key_version="v1" if encrypted else None,
        retired_on=payload.retired_on,
        service_branch=payload.service_branch,
        remarks=payload.remarks,
        created_by=user.id,
    )
    db.add(item)
    db.flush()
    audit(db, user, request, "veteran_identity.create", "veteran_identity", item.id)
    db.commit()
    return identity_view(item)


@router.get("/veteran-identities/lookup")
def lookup_by_card(retirement_card_no: str, db: Db, user: VeteranRead) -> dict:
    """按 HMAC 盲索引查重：只回答"是否已存在"，不返回任何学员信息。"""
    digest = blind_index(retirement_card_no.strip())
    found = db.scalar(select(VeteranIdentity.id).where(VeteranIdentity.organization_id == user.organization_id, VeteranIdentity.retirement_card_no_hmac == digest))
    return {"exists": found is not None}


@router.post("/veteran-identities/{item_id}/plaintext")
def view_plaintext(item_id: str, payload: ReasonInput, request: Request, db: Db, user: VeteranPlaintext) -> dict:
    """明文查看：独立权限 + 必填理由 + 审计。"""
    item = identity_for(db, user, item_id)
    if not item.retirement_card_no_encrypted:
        raise error(404, "RETIREMENT_CARD_NOT_SET", "该退役身份未登记退役证号。")
    plaintext = decrypt(item.retirement_card_no_encrypted)
    audit(db, user, request, "veteran_identity.view_plaintext", "veteran_identity", item.id, {"reason": payload.reason})
    db.commit()
    return {"id": item.id, "retirement_card_no": plaintext, "reason": payload.reason}


@router.post("/veteran-identities/{item_id}/verifications")
def add_verification(item_id: str, payload: VerificationInput, request: Request, db: Db, user: VeteranVerify) -> dict:
    item = identity_for(db, user, item_id)
    record = VeteranIdentityVerification(
        organization_id=user.organization_id,
        veteran_identity_id=item.id,
        verification_no=business_code("VV"),
        verification_status=payload.verification_status,
        method=payload.method,
        verified_on=payload.verified_on or date.today(),
        verified_by=user.id,
        note=payload.note,
        created_by=user.id,
    )
    db.add(record)
    # 身份主档的核验结论按"最新一次核验"汇总，历史核验记录全部保留
    item.verified_status = "VERIFIED" if payload.verification_status == "PASSED" else ("REJECTED" if payload.verification_status == "FAILED" else "UNVERIFIED")
    item.version += 1
    db.flush()
    audit(db, user, request, "veteran_identity.verify", "veteran_identity", item.id, {"verification_no": record.verification_no, "status": payload.verification_status})
    db.commit()
    return {"id": record.id, "verification_no": record.verification_no, "verified_status": item.verified_status}


@router.get("/veteran-identities/{item_id}/verifications")
def list_verifications(item_id: str, db: Db, user: VeteranRead) -> dict:
    item = identity_for(db, user, item_id)
    rows = db.scalars(select(VeteranIdentityVerification).where(VeteranIdentityVerification.veteran_identity_id == item.id).order_by(VeteranIdentityVerification.created_at)).all()
    return {"items": [{"id": r.id, "verification_no": r.verification_no, "verification_status": r.verification_status, "method": r.method, "verified_on": r.verified_on.isoformat() if r.verified_on else None, "note": r.note} for r in rows]}


@router.get("/veteran-identities/{item_id}/attributes")
def list_attributes(item_id: str, db: Db, user: VeteranRead) -> dict:
    item = identity_for(db, user, item_id)
    rows = db.scalars(select(VeteranAttributeHistory).where(VeteranAttributeHistory.veteran_identity_id == item.id).order_by(VeteranAttributeHistory.effective_from.desc())).all()
    return {"items": [{"id": r.id, "attribute_code": r.attribute_code, "value_text": r.value_text, "value_date": r.value_date.isoformat() if r.value_date else None, "effective_from": r.effective_from.isoformat(), "effective_to": r.effective_to.isoformat() if r.effective_to else None, "source": r.source} for r in rows]}


@router.post("/veteran-identities/{item_id}/attributes")
def add_attribute(item_id: str, payload: AttributeInput, request: Request, db: Db, user: VeteranManage) -> dict:
    item = identity_for(db, user, item_id)
    if payload.effective_to and payload.effective_to < payload.effective_from:
        raise error(422, "INVALID_EFFECTIVE_RANGE", "生效结束日期不能早于生效开始日期。")
    record = VeteranAttributeHistory(
        organization_id=user.organization_id,
        veteran_identity_id=item.id,
        attribute_code=payload.attribute_code,
        value_text=payload.value_text,
        value_date=payload.value_date,
        effective_from=payload.effective_from,
        effective_to=payload.effective_to,
        source=payload.source,
        note=payload.note,
        created_by=user.id,
    )
    db.add(record)
    db.flush()
    audit(db, user, request, "veteran_attribute.add", "veteran_identity", item.id, {"attribute_code": payload.attribute_code})
    db.commit()
    return {"id": record.id}


@router.post("/veteran-identities/{item_id}/evidences")
def add_evidence(item_id: str, evidence_type: str, file_object_id: str, request: Request, db: Db, user: VeteranManage) -> dict:
    item = identity_for(db, user, item_id)
    record = VeteranIdentityEvidence(organization_id=user.organization_id, veteran_identity_id=item.id, evidence_type=evidence_type, file_object_id=file_object_id, created_by=user.id)
    db.add(record)
    db.flush()
    audit(db, user, request, "veteran_evidence.add", "veteran_identity", item.id, {"evidence_type": evidence_type})
    db.commit()
    return {"id": record.id}
