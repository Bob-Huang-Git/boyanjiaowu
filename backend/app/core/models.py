# ruff: noqa: E501
# fmt: off
import uuid
from datetime import UTC, date, datetime

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.core.db import Base


def new_id() -> str:
    return str(uuid.uuid4())


def utc_now() -> datetime:
    # SQLite stores timestamps without timezone metadata; all persisted values are UTC.
    return datetime.now(UTC).replace(tzinfo=None)


class RecordMixin:
    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utc_now, onupdate=utc_now
    )
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class Organization(RecordMixin, Base):
    __tablename__ = "organizations"
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class User(RecordMixin, Base):
    __tablename__ = "users"
    __table_args__ = (UniqueConstraint("organization_id", "username"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    username: Mapped[str] = mapped_column(String(80), nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(255), nullable=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class Role(RecordMixin, Base):
    __tablename__ = "roles"
    __table_args__ = (UniqueConstraint("organization_id", "code"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    code: Mapped[str] = mapped_column(String(80), nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)


class Permission(RecordMixin, Base):
    __tablename__ = "permissions"
    code: Mapped[str] = mapped_column(String(100), unique=True)
    description: Mapped[str] = mapped_column(String(255))


class UserRole(RecordMixin, Base):
    __tablename__ = "user_roles"
    __table_args__ = (UniqueConstraint("user_id", "role_id"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), index=True)


class RolePermission(RecordMixin, Base):
    __tablename__ = "role_permissions"
    __table_args__ = (UniqueConstraint("role_id", "permission_id"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    role_id: Mapped[str] = mapped_column(ForeignKey("roles.id"), index=True)
    permission_id: Mapped[str] = mapped_column(ForeignKey("permissions.id"), index=True)


class UserDataScope(RecordMixin, Base):
    __tablename__ = "user_data_scopes"
    __table_args__ = (UniqueConstraint("user_id", "scope_type", "scope_id"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    scope_type: Mapped[str] = mapped_column(String(30))
    scope_id: Mapped[str] = mapped_column(String(36))


class UserSession(RecordMixin, Base):
    __tablename__ = "user_sessions"
    __table_args__ = (Index("ix_user_sessions_user_expires", "user_id", "expires_at"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True)
    csrf_hash: Mapped[str] = mapped_column(String(64))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ip_address: Mapped[str | None] = mapped_column(String(45))
    user_agent_hash: Mapped[str | None] = mapped_column(String(64))


class AuditLog(RecordMixin, Base):
    __tablename__ = "audit_logs"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    actor_user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(100), index=True)
    subject_type: Mapped[str] = mapped_column(String(80))
    subject_id: Mapped[str | None] = mapped_column(String(36))
    correlation_id: Mapped[str] = mapped_column(String(36), index=True)
    detail_json: Mapped[str] = mapped_column(Text, default="{}")


class BusinessEvent(RecordMixin, Base):
    __tablename__ = "business_events"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(100), index=True)
    aggregate_type: Mapped[str] = mapped_column(String(80))
    aggregate_id: Mapped[str] = mapped_column(String(36))
    payload_json: Mapped[str] = mapped_column(Text, default="{}")


class AppSetting(RecordMixin, Base):
    __tablename__ = "app_settings"
    __table_args__ = (UniqueConstraint("organization_id", "key"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    key: Mapped[str] = mapped_column(String(100))
    value_json: Mapped[str] = mapped_column(Text)


class Student(RecordMixin, Base):
    __tablename__ = "students"
    __table_args__ = (
        UniqueConstraint("organization_id", "student_no"),
        Index("ix_students_org_name", "organization_id", "full_name"),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    student_no: Mapped[str] = mapped_column(String(32), nullable=False)
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    gender: Mapped[str] = mapped_column(String(20), default="UNKNOWN", nullable=False)
    birth_date: Mapped[date | None] = mapped_column(Date)
    phone_ciphertext: Mapped[str | None] = mapped_column(Text)
    phone_blind_index: Mapped[str | None] = mapped_column(String(64), index=True)
    email: Mapped[str | None] = mapped_column(String(255))
    education_level: Mapped[str | None] = mapped_column(String(50))
    residence_region_code: Mapped[str | None] = mapped_column(String(50))
    address_ciphertext: Mapped[str | None] = mapped_column(Text)
    source_channel: Mapped[str | None] = mapped_column(String(80))
    student_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    remarks: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class StudentIdentityDocument(RecordMixin, Base):
    __tablename__ = "student_identity_documents"
    __table_args__ = (
        UniqueConstraint("document_type", "document_number_blind_index"),
        Index("ix_student_documents_student_primary", "student_id", "is_primary"),
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    document_type: Mapped[str] = mapped_column(String(30), nullable=False)
    document_number_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    document_number_blind_index: Mapped[str] = mapped_column(String(64), nullable=False)
    document_number_last4: Mapped[str] = mapped_column(String(4), nullable=False)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    verification_status: Mapped[str] = mapped_column(
        String(30), default="UNVERIFIED", nullable=False
    )
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class CurriculumVersion(RecordMixin, Base):
    __tablename__ = "curriculum_versions"
    version_no: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    total_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    theory_minutes: Mapped[int | None] = mapped_column(Integer)
    practical_minutes: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)


class ExamSchemeVersion(RecordMixin, Base):
    __tablename__ = "exam_scheme_versions"
    version_no: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    scheme_type: Mapped[str] = mapped_column(String(50), default="STANDARD")
    pass_rule_description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)


class CourseSubjectVersion(RecordMixin, Base):
    __tablename__ = "course_subject_versions"
    __table_args__ = (UniqueConstraint("exam_scheme_version_id", "subject_code"),)
    exam_scheme_version_id: Mapped[str] = mapped_column(
        ForeignKey("exam_scheme_versions.id"), index=True
    )
    subject_code: Mapped[str] = mapped_column(String(40), nullable=False)
    subject_name: Mapped[str] = mapped_column(String(120), nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=1)
    passing_score: Mapped[int | None] = mapped_column(Integer)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class FeePolicyVersion(RecordMixin, Base):
    __tablename__ = "fee_policy_versions"
    version_no: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    tuition_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    initial_exam_fee_cent: Mapped[int | None] = mapped_column(Integer)
    description: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)


class RefundPolicyVersion(RecordMixin, Base):
    __tablename__ = "refund_policy_versions"
    version_no: Mapped[str] = mapped_column(String(40), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    policy_description: Mapped[str | None] = mapped_column(Text)
    calculation_method: Mapped[str | None] = mapped_column(String(50))
    consumed_minutes_basis: Mapped[str | None] = mapped_column(String(50))
    rounding_mode: Mapped[str | None] = mapped_column(String(20))
    minimum_deduction_amount_cent: Mapped[int | None] = mapped_column(Integer)
    administrative_fee_amount_cent: Mapped[int | None] = mapped_column(Integer)
    initial_exam_fee_refundable: Mapped[bool] = mapped_column(Boolean, default=False)
    resit_fee_refundable: Mapped[bool] = mapped_column(Boolean, default=False)
    refund_deadline_rule: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)


class CourseCatalog(RecordMixin, Base):
    __tablename__ = "course_catalogs"
    __table_args__ = (UniqueConstraint("organization_id", "course_code"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    course_code: Mapped[str] = mapped_column(String(40), nullable=False)
    course_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_code: Mapped[str | None] = mapped_column(String(50))
    description: Mapped[str | None] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False, index=True)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class CourseOfferingVersion(RecordMixin, Base):
    __tablename__ = "course_offering_versions"
    __table_args__ = (UniqueConstraint("course_catalog_id", "version_no"),)
    course_catalog_id: Mapped[str] = mapped_column(ForeignKey("course_catalogs.id"), index=True)
    version_no: Mapped[str] = mapped_column(String(40), nullable=False)
    version_name: Mapped[str] = mapped_column(String(120), nullable=False)
    status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date)
    curriculum_version_id: Mapped[str | None] = mapped_column(ForeignKey("curriculum_versions.id"))
    exam_scheme_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("exam_scheme_versions.id")
    )
    fee_policy_version_id: Mapped[str | None] = mapped_column(ForeignKey("fee_policy_versions.id"))
    refund_policy_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("refund_policy_versions.id")
    )
    published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    published_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class CourseEnrollment(RecordMixin, Base):
    __tablename__ = "course_enrollments"
    __table_args__ = (
        UniqueConstraint("organization_id", "enrollment_no"),
        UniqueConstraint("organization_id", "idempotency_key"),
        Index("ix_enrollments_student_status", "student_id", "lifecycle_status"),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    enrollment_no: Mapped[str] = mapped_column(String(32), nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    course_offering_version_id: Mapped[str] = mapped_column(
        ForeignKey("course_offering_versions.id"), index=True
    )
    curriculum_version_id: Mapped[str] = mapped_column(ForeignKey("curriculum_versions.id"))
    exam_scheme_version_id: Mapped[str] = mapped_column(ForeignKey("exam_scheme_versions.id"))
    fee_policy_version_id: Mapped[str] = mapped_column(ForeignKey("fee_policy_versions.id"))
    refund_policy_version_id: Mapped[str] = mapped_column(ForeignKey("refund_policy_versions.id"))
    enrolled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    enrollment_channel: Mapped[str | None] = mapped_column(String(80))
    idempotency_key: Mapped[str | None] = mapped_column(String(100))
    lifecycle_status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    learning_status: Mapped[str] = mapped_column(String(30), default="NOT_STARTED")
    exam_status: Mapped[str] = mapped_column(String(30), default="NOT_REGISTERED")
    financial_status: Mapped[str] = mapped_column(String(30), default="UNPAID")
    certificate_status: Mapped[str] = mapped_column(String(30), default="NOT_ELIGIBLE")
    funding_status: Mapped[str] = mapped_column(String(30), default="NOT_APPLICABLE")
    cancelled_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    cancelled_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    cancel_reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ClassCycle(RecordMixin, Base):
    __tablename__ = "class_cycles"
    __table_args__ = (UniqueConstraint("organization_id", "class_code"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    class_code: Mapped[str] = mapped_column(String(40), nullable=False)
    class_name: Mapped[str] = mapped_column(String(120), nullable=False)
    course_offering_version_id: Mapped[str] = mapped_column(
        ForeignKey("course_offering_versions.id"), index=True
    )
    planned_start_date: Mapped[date | None] = mapped_column(Date)
    planned_end_date: Mapped[date | None] = mapped_column(Date)
    capacity: Mapped[int | None] = mapped_column(Integer)
    class_status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    homeroom_teacher_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    remarks: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ClassMembership(RecordMixin, Base):
    __tablename__ = "class_memberships"
    __table_args__ = (
        Index(
            "uq_class_memberships_active_enrollment",
            "course_enrollment_id",
            unique=True,
            sqlite_where=text("membership_status = 'ACTIVE'"),
        ),
    )
    class_cycle_id: Mapped[str] = mapped_column(ForeignKey("class_cycles.id"), index=True)
    course_enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("course_enrollments.id"), index=True
    )
    entered_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    exited_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    membership_status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    entry_reason: Mapped[str] = mapped_column(String(80), default="INITIAL")
    exit_reason: Mapped[str | None] = mapped_column(Text)
    previous_membership_id: Mapped[str | None] = mapped_column(ForeignKey("class_memberships.id"))
    financial_treatment: Mapped[str | None] = mapped_column(String(80))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class StudentImportBatch(RecordMixin, Base):
    __tablename__ = "student_import_batches"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PREVIEWED", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confirm_idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    preview_payload_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, default="{}")


class StudentImportLine(RecordMixin, Base):
    __tablename__ = "student_import_lines"
    __table_args__ = (UniqueConstraint("batch_id", "row_number"),)
    batch_id: Mapped[str] = mapped_column(ForeignKey("student_import_batches.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(40), index=True)
    student_id: Mapped[str | None] = mapped_column(ForeignKey("students.id"))
    result_json: Mapped[str] = mapped_column(Text, default="{}")


class FileObject(RecordMixin, Base):
    __tablename__ = "file_objects"
    __table_args__ = (Index("ix_file_objects_status", "file_status"),)
    original_filename: Mapped[str] = mapped_column(String(255), nullable=False)
    safe_extension: Mapped[str] = mapped_column(String(12), nullable=False)
    declared_content_type: Mapped[str | None] = mapped_column(String(120))
    detected_content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    file_status: Mapped[str] = mapped_column(String(20), default="STAGED", nullable=False)
    sensitivity_level: Mapped[str] = mapped_column(String(30), default="NORMAL", nullable=False)
    activated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    deleted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    delete_reason: Mapped[str | None] = mapped_column(Text)
    metadata_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class FileReplica(RecordMixin, Base):
    __tablename__ = "file_replicas"
    __table_args__ = (
        UniqueConstraint("storage_provider", "object_key"),
        Index(
            "uq_file_replicas_primary",
            "file_object_id",
            unique=True,
            sqlite_where=text("is_primary = 1 AND deleted_at IS NULL"),
        ),
    )
    file_object_id: Mapped[str] = mapped_column(ForeignKey("file_objects.id"), index=True)
    storage_provider: Mapped[str] = mapped_column(String(20), nullable=False)
    object_key: Mapped[str] = mapped_column(String(500), nullable=False)
    replica_status: Mapped[str] = mapped_column(String(20), default="COPYING", nullable=False)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    provider_etag: Mapped[str | None] = mapped_column(String(255))
    provider_version_id: Mapped[str | None] = mapped_column(String(255))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    last_checked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    failure_code: Mapped[str | None] = mapped_column(String(80))
    failure_message_sanitized: Mapped[str | None] = mapped_column(String(255))
    retention_until: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class DocumentCategory(RecordMixin, Base):
    __tablename__ = "document_categories"
    __table_args__ = (UniqueConstraint("category_code"),)
    category_code: Mapped[str] = mapped_column(String(60), nullable=False)
    category_name: Mapped[str] = mapped_column(String(120), nullable=False)
    owner_domain: Mapped[str] = mapped_column(String(30), default="STUDENT", nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    sensitivity_level: Mapped[str] = mapped_column(String(30), default="NORMAL", nullable=False)
    max_size_bytes: Mapped[int] = mapped_column(Integer, nullable=False)
    allow_multiple: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    requires_review: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    validity_required: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class DocumentCategoryAllowedType(RecordMixin, Base):
    __tablename__ = "document_category_allowed_types"
    __table_args__ = (UniqueConstraint("category_id", "extension", "detected_content_type"),)
    category_id: Mapped[str] = mapped_column(ForeignKey("document_categories.id"), index=True)
    extension: Mapped[str] = mapped_column(String(12), nullable=False)
    mime_type: Mapped[str] = mapped_column(String(120), nullable=False)
    detected_content_type: Mapped[str] = mapped_column(String(120), nullable=False)
    inline_preview: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class StudentDocument(RecordMixin, Base):
    __tablename__ = "student_documents"
    __table_args__ = (
        Index("ix_student_documents_student_status", "student_id", "document_status"),
        Index(
            "uq_student_documents_primary",
            "student_id",
            "category_id",
            unique=True,
            sqlite_where=text(
                "is_primary = 1 AND deleted_at IS NULL AND document_status != 'SUPERSEDED'"
            ),
        ),
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    file_object_id: Mapped[str] = mapped_column(ForeignKey("file_objects.id"), index=True)
    category_id: Mapped[str] = mapped_column(ForeignKey("document_categories.id"), index=True)
    document_status: Mapped[str] = mapped_column(
        String(30), default="PENDING_REVIEW", nullable=False
    )
    document_number_masked: Mapped[str | None] = mapped_column(String(80))
    document_date: Mapped[date | None] = mapped_column(Date)
    valid_from: Mapped[date | None] = mapped_column(Date)
    valid_until: Mapped[date | None] = mapped_column(Date)
    is_primary: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    supersedes_document_id: Mapped[str | None] = mapped_column(ForeignKey("student_documents.id"))
    description: Mapped[str | None] = mapped_column(Text)
    review_comment: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    reviewed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    delete_reason: Mapped[str | None] = mapped_column(Text)


class StudentDocumentRequirement(RecordMixin, Base):
    __tablename__ = "student_document_requirements"
    __table_args__ = (UniqueConstraint("requirement_code"),)
    requirement_code: Mapped[str] = mapped_column(String(80), nullable=False)
    requirement_name: Mapped[str] = mapped_column(String(120), nullable=False)
    category_id: Mapped[str] = mapped_column(ForeignKey("document_categories.id"), index=True)
    applicable_course_catalog_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_catalogs.id")
    )
    required_count: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    effective_from: Mapped[date | None] = mapped_column(Date)
    effective_until: Mapped[date | None] = mapped_column(Date)
    display_order: Mapped[int] = mapped_column(Integer, default=1, nullable=False)


class TeacherProfile(RecordMixin, Base):
    __tablename__ = "teacher_profiles"
    __table_args__ = (UniqueConstraint("teacher_no"), UniqueConstraint("user_id"))
    teacher_no: Mapped[str] = mapped_column(String(32), nullable=False)
    user_id: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    full_name: Mapped[str] = mapped_column(String(120), nullable=False)
    phone_ciphertext: Mapped[str | None] = mapped_column(Text)
    teacher_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", nullable=False)
    employment_type: Mapped[str | None] = mapped_column(String(20))
    default_rate_amount_cent: Mapped[int | None] = mapped_column(Integer)
    default_rate_unit_minutes: Mapped[int | None] = mapped_column(Integer)
    remarks: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ClassSession(RecordMixin, Base):
    __tablename__ = "class_sessions"
    __table_args__ = (
        UniqueConstraint("class_cycle_id", "session_no"),
        Index("ix_class_sessions_cycle_start", "class_cycle_id", "planned_start_at"),
    )
    class_cycle_id: Mapped[str] = mapped_column(ForeignKey("class_cycles.id"), index=True)
    session_no: Mapped[str] = mapped_column(String(40), nullable=False)
    session_title: Mapped[str] = mapped_column(String(200), nullable=False)
    session_type: Mapped[str] = mapped_column(String(20), default="REGULAR", nullable=False)
    source_session_id: Mapped[str | None] = mapped_column(ForeignKey("class_sessions.id"))
    service_date: Mapped[date] = mapped_column(Date, nullable=False, index=True)
    planned_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planned_end_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    planned_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_minutes: Mapped[int | None] = mapped_column(Integer)
    actual_adjustment_reason: Mapped[str | None] = mapped_column(Text)
    delivery_mode: Mapped[str] = mapped_column(String(20), default="OFFLINE", nullable=False)
    location_name: Mapped[str | None] = mapped_column(String(200))
    online_meeting_url: Mapped[str | None] = mapped_column(String(1000))
    teaching_topic: Mapped[str | None] = mapped_column(String(500))
    teaching_content: Mapped[str | None] = mapped_column(Text)
    session_status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class SessionTeacherAssignment(RecordMixin, Base):
    __tablename__ = "session_teacher_assignments"
    __table_args__ = (
        UniqueConstraint("class_session_id", "teacher_id", "teaching_role"),
        Index("ix_assignment_teacher_status", "teacher_id", "confirmation_status"),
    )
    class_session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id"), index=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("teacher_profiles.id"), index=True)
    teaching_role: Mapped[str] = mapped_column(String(20), nullable=False)
    planned_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    planned_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_start_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    actual_minutes: Mapped[int | None] = mapped_column(Integer)
    settleable_minutes: Mapped[int | None] = mapped_column(Integer)
    rate_amount_cent: Mapped[int | None] = mapped_column(Integer)
    rate_unit_minutes: Mapped[int | None] = mapped_column(Integer)
    confirmation_status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    adjustment_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class AttendanceRecord(RecordMixin, Base):
    __tablename__ = "attendance_records"
    __table_args__ = (UniqueConstraint("class_session_id", "class_membership_id"),)
    class_session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id"), index=True)
    class_membership_id: Mapped[str] = mapped_column(ForeignKey("class_memberships.id"), index=True)
    attendance_status: Mapped[str] = mapped_column(String(20), nullable=False)
    expected_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    actual_attendance_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    late_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    early_leave_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    check_in_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    check_out_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    workflow_status: Mapped[str] = mapped_column(String(20), default="DRAFT", nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="MANUAL", nullable=False)
    current_revision_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    locked_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    locked_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class AttendanceRevision(RecordMixin, Base):
    __tablename__ = "attendance_revisions"
    __table_args__ = (UniqueConstraint("attendance_record_id", "revision_no"),)
    attendance_record_id: Mapped[str] = mapped_column(
        ForeignKey("attendance_records.id"), index=True
    )
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    new_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    change_type: Mapped[str] = mapped_column(String(20), nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    request_id: Mapped[str | None] = mapped_column(String(36))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class AttendanceFinalization(RecordMixin, Base):
    __tablename__ = "attendance_finalizations"
    __table_args__ = (UniqueConstraint("class_session_id", "finalization_no"),)
    class_session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id"), index=True)
    finalization_no: Mapped[int] = mapped_column(Integer, nullable=False)
    locked_record_count: Mapped[int] = mapped_column(Integer, nullable=False)
    total_expected_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    total_actual_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    finalized_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    finalized_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    reason: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(String(20), default="LOCKED", nullable=False)


class AttendanceEvidence(RecordMixin, Base):
    __tablename__ = "attendance_evidences"
    attendance_record_id: Mapped[str] = mapped_column(
        ForeignKey("attendance_records.id"), index=True
    )
    attendance_revision_id: Mapped[str | None] = mapped_column(
        ForeignKey("attendance_revisions.id")
    )
    file_object_id: Mapped[str] = mapped_column(ForeignKey("file_objects.id"), index=True)
    evidence_type: Mapped[str] = mapped_column(String(30), nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    deleted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    deleted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    delete_reason: Mapped[str | None] = mapped_column(Text)


class SessionRecording(RecordMixin, Base):
    __tablename__ = "session_recordings"
    __table_args__ = (
        Index("ix_recordings_session_status", "class_session_id", "recording_status"),
    )
    class_session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id"), index=True)
    recording_title: Mapped[str] = mapped_column(String(200), nullable=False)
    platform_code: Mapped[str] = mapped_column(String(50), nullable=False)
    external_url: Mapped[str] = mapped_column(String(1000), nullable=False)
    access_code_ciphertext: Mapped[str | None] = mapped_column(Text)
    key_version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    duration_minutes: Mapped[int | None] = mapped_column(Integer)
    recorded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    expires_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    recording_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    review_status: Mapped[str] = mapped_column(String(20), default="PENDING_REVIEW", nullable=False)
    review_comment: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class EnrollmentRolloverRequest(RecordMixin, Base):
    __tablename__ = "enrollment_rollover_requests"
    __table_args__ = (UniqueConstraint("idempotency_key"),)
    course_enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("course_enrollments.id"), index=True
    )
    source_membership_id: Mapped[str] = mapped_column(ForeignKey("class_memberships.id"))
    target_class_cycle_id: Mapped[str] = mapped_column(ForeignKey("class_cycles.id"))
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    result_membership_id: Mapped[str | None] = mapped_column(ForeignKey("class_memberships.id"))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ExamBatch(RecordMixin, Base):
    __tablename__ = "exam_batches"
    __table_args__ = (UniqueConstraint("batch_code"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    batch_code: Mapped[str] = mapped_column(String(40), nullable=False)
    batch_name: Mapped[str] = mapped_column(String(160), nullable=False)
    exam_scheme_version_id: Mapped[str] = mapped_column(ForeignKey("exam_scheme_versions.id"))
    organizing_institution: Mapped[str | None] = mapped_column(String(200))
    registration_open_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    registration_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    exam_start_date: Mapped[date] = mapped_column(Date, nullable=False)
    exam_end_date: Mapped[date] = mapped_column(Date, nullable=False)
    batch_status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    remarks: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ExamBatchSubject(RecordMixin, Base):
    __tablename__ = "exam_batch_subjects"
    __table_args__ = (UniqueConstraint("exam_batch_id", "course_subject_version_id"),)
    exam_batch_id: Mapped[str] = mapped_column(ForeignKey("exam_batches.id"), index=True)
    course_subject_version_id: Mapped[str] = mapped_column(
        ForeignKey("course_subject_versions.id"), index=True
    )
    exam_start_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    exam_end_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    venue_name: Mapped[str | None] = mapped_column(String(200))
    registration_deadline_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    capacity: Mapped[int | None] = mapped_column(Integer)
    initial_exam_fee_amount_cent: Mapped[int | None] = mapped_column(Integer)
    resit_fee_amount_cent: Mapped[int | None] = mapped_column(Integer)
    subject_status: Mapped[str] = mapped_column(String(20), default="SCHEDULED", nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)


class ExamRegistration(RecordMixin, Base):
    __tablename__ = "exam_registrations"
    __table_args__ = (
        UniqueConstraint("registration_no"),
        UniqueConstraint("course_enrollment_id", "exam_batch_id"),
        UniqueConstraint("idempotency_key"),
    )
    registration_no: Mapped[str] = mapped_column(String(40), nullable=False)
    course_enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("course_enrollments.id"), index=True
    )
    exam_batch_id: Mapped[str] = mapped_column(ForeignKey("exam_batches.id"), index=True)
    registration_status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    registration_source: Mapped[str] = mapped_column(String(20), nullable=False)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    registered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    external_registration_no: Mapped[str | None] = mapped_column(String(100))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ExamRegistrationSubject(RecordMixin, Base):
    __tablename__ = "exam_registration_subjects"
    __table_args__ = (UniqueConstraint("exam_registration_id", "exam_batch_subject_id"),)
    exam_registration_id: Mapped[str] = mapped_column(
        ForeignKey("exam_registrations.id"), index=True
    )
    exam_batch_subject_id: Mapped[str] = mapped_column(
        ForeignKey("exam_batch_subjects.id"), index=True
    )
    course_subject_version_id: Mapped[str] = mapped_column(
        ForeignKey("course_subject_versions.id"), index=True
    )
    attempt_type: Mapped[str] = mapped_column(String(20), nullable=False)
    planned_attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    subject_registration_status: Mapped[str] = mapped_column(
        String(30), default="DRAFT", nullable=False
    )
    admission_ticket_no_ciphertext: Mapped[str | None] = mapped_column(Text)
    admission_ticket_no_last4: Mapped[str | None] = mapped_column(String(4))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ExamAttempt(RecordMixin, Base):
    __tablename__ = "exam_attempts"
    __table_args__ = (
        UniqueConstraint("course_enrollment_id", "course_subject_version_id", "attempt_no"),
    )
    course_enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("course_enrollments.id"), index=True
    )
    course_subject_version_id: Mapped[str] = mapped_column(
        ForeignKey("course_subject_versions.id"), index=True
    )
    exam_registration_subject_id: Mapped[str | None] = mapped_column(
        ForeignKey("exam_registration_subjects.id"), unique=True
    )
    attempt_no: Mapped[int] = mapped_column(Integer, nullable=False)
    attempt_type: Mapped[str] = mapped_column(String(20), nullable=False)
    attendance_status: Mapped[str] = mapped_column(String(30), default="UNKNOWN", nullable=False)
    score_value_scaled: Mapped[int | None] = mapped_column(Integer)
    score_scale: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    max_score_value_scaled: Mapped[int | None] = mapped_column(Integer)
    result_status: Mapped[str] = mapped_column(String(20), default="PENDING", nullable=False)
    result_confirm_status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    result_source: Mapped[str] = mapped_column(String(20), default="MANUAL", nullable=False)
    result_published_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    remarks: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    current_revision_no: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ExamResultRevision(RecordMixin, Base):
    __tablename__ = "exam_result_revisions"
    __table_args__ = (UniqueConstraint("exam_attempt_id", "revision_no"),)
    exam_attempt_id: Mapped[str] = mapped_column(ForeignKey("exam_attempts.id"), index=True)
    revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    previous_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    new_values_json: Mapped[str] = mapped_column(Text, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_file_object_id: Mapped[str | None] = mapped_column(ForeignKey("file_objects.id"))
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    revised_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class ExamFeeAssessment(RecordMixin, Base):
    __tablename__ = "exam_fee_assessments"
    __table_args__ = (
        UniqueConstraint("exam_attempt_id", "fee_type"),
        UniqueConstraint("assessment_no"),
    )
    assessment_no: Mapped[str] = mapped_column(String(40), nullable=False)
    course_enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("course_enrollments.id"), index=True
    )
    exam_attempt_id: Mapped[str] = mapped_column(ForeignKey("exam_attempts.id"), index=True)
    exam_registration_subject_id: Mapped[str | None] = mapped_column(
        ForeignKey("exam_registration_subjects.id")
    )
    course_subject_version_id: Mapped[str | None] = mapped_column(
        ForeignKey("course_subject_versions.id")
    )
    fee_policy_version_id: Mapped[str | None] = mapped_column(ForeignKey("fee_policy_versions.id"))
    fee_type: Mapped[str] = mapped_column(String(20), nullable=False)
    responsibility: Mapped[str] = mapped_column(String(20), default="STUDENT", nullable=False)
    amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    assessment_status: Mapped[str] = mapped_column(String(30), default="DRAFT", nullable=False)
    policy_snapshot_description: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    waiver_reason: Mapped[str | None] = mapped_column(Text)
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    finance_reference: Mapped[str | None] = mapped_column(String(100))
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class CertificateCase(RecordMixin, Base):
    __tablename__ = "certificate_cases"
    __table_args__ = (
        UniqueConstraint("course_enrollment_id"),
        UniqueConstraint("certificate_case_no"),
    )
    certificate_case_no: Mapped[str] = mapped_column(String(40), nullable=False)
    course_enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("course_enrollments.id"), nullable=False
    )
    eligibility_status: Mapped[str] = mapped_column(String(30), default="ELIGIBLE", nullable=False)
    certificate_status: Mapped[str] = mapped_column(String(30), default="ELIGIBLE", nullable=False)
    certificate_type_code: Mapped[str] = mapped_column(String(50), default="COURSE", nullable=False)
    certificate_type_name_snapshot: Mapped[str] = mapped_column(String(120), default="培训证书")
    issuing_authority: Mapped[str | None] = mapped_column(String(200))
    application_submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    issued_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    certificate_no_ciphertext: Mapped[str | None] = mapped_column(Text)
    certificate_no_last4: Mapped[str | None] = mapped_column(String(4))
    school_received_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ready_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    delivery_method: Mapped[str | None] = mapped_column(String(20))
    recipient_name: Mapped[str | None] = mapped_column(String(120))
    courier_company: Mapped[str | None] = mapped_column(String(120))
    tracking_no_ciphertext: Mapped[str | None] = mapped_column(Text)
    exception_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class CertificateDeliveryEvent(RecordMixin, Base):
    __tablename__ = "certificate_delivery_events"
    certificate_case_id: Mapped[str] = mapped_column(ForeignKey("certificate_cases.id"), index=True)
    event_type: Mapped[str] = mapped_column(String(50), nullable=False)
    from_status: Mapped[str] = mapped_column(String(30), nullable=False)
    to_status: Mapped[str] = mapped_column(String(30), nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    operator_id: Mapped[str] = mapped_column(ForeignKey("users.id"))
    remarks: Mapped[str | None] = mapped_column(Text)
    evidence_file_object_id: Mapped[str | None] = mapped_column(ForeignKey("file_objects.id"))


class ExamResultImportBatch(RecordMixin, Base):
    __tablename__ = "exam_result_import_batches"
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"), index=True)
    status: Mapped[str] = mapped_column(String(30), default="PREVIEWED", index=True)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    confirm_idempotency_key: Mapped[str | None] = mapped_column(String(100), unique=True)
    preview_payload_ciphertext: Mapped[str] = mapped_column(Text, nullable=False)
    summary_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class ExamResultImportLine(RecordMixin, Base):
    __tablename__ = "exam_result_import_lines"
    __table_args__ = (UniqueConstraint("batch_id", "row_number"),)
    batch_id: Mapped[str] = mapped_column(ForeignKey("exam_result_import_batches.id"), index=True)
    row_number: Mapped[int] = mapped_column(Integer, nullable=False)
    status: Mapped[str] = mapped_column(String(30), index=True)
    exam_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("exam_attempts.id"))
    result_json: Mapped[str] = mapped_column(Text, default="{}", nullable=False)


class ExamDomainAttachment(RecordMixin, Base):
    __tablename__ = "exam_domain_attachments"
    __table_args__ = (UniqueConstraint("owner_type", "owner_id", "file_object_id"),)
    owner_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    owner_id: Mapped[str] = mapped_column(String(36), nullable=False, index=True)
    file_object_id: Mapped[str] = mapped_column(ForeignKey("file_objects.id"), index=True)
    attachment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class Receivable(RecordMixin, Base):
    __tablename__ = "receivables"
    __table_args__ = (
        UniqueConstraint("receivable_no"),
        UniqueConstraint("source_type", "source_id"),
        CheckConstraint("original_amount_cent >= 0", name="ck_receivable_original_nonnegative"),
        CheckConstraint("payable_amount_cent >= 0", name="ck_receivable_payable_nonnegative"),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    receivable_no: Mapped[str] = mapped_column(String(40), nullable=False)
    course_enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("course_enrollments.id"), index=True
    )
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    receivable_type: Mapped[str] = mapped_column(String(30), nullable=False, index=True)
    economic_nature: Mapped[str] = mapped_column(String(30), nullable=False)
    source_type: Mapped[str] = mapped_column(String(40), nullable=False)
    source_id: Mapped[str] = mapped_column(String(36), nullable=False)
    fee_policy_version_id: Mapped[str | None] = mapped_column(ForeignKey("fee_policy_versions.id"))
    original_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    adjusted_amount_cent: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    payable_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    receivable_status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    description: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class ReceivableAdjustment(RecordMixin, Base):
    __tablename__ = "receivable_adjustments"
    __table_args__ = (CheckConstraint("amount_cent > 0", name="ck_receivable_adjustment_positive"),)
    receivable_id: Mapped[str] = mapped_column(ForeignKey("receivables.id"), index=True)
    adjustment_type: Mapped[str] = mapped_column(String(20), nullable=False)
    amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    reason: Mapped[str] = mapped_column(Text, nullable=False)
    approval_status: Mapped[str] = mapped_column(String(20), default="APPROVED", nullable=False)
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reversal_of_adjustment_id: Mapped[str | None] = mapped_column(
        ForeignKey("receivable_adjustments.id")
    )


class Payment(RecordMixin, Base):
    __tablename__ = "payments"
    __table_args__ = (
        UniqueConstraint("payment_no"),
        UniqueConstraint("idempotency_key"),
        UniqueConstraint("internal_receipt_no"),
        CheckConstraint("received_amount_cent > 0", name="ck_payment_amount_positive"),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    payment_no: Mapped[str] = mapped_column(String(40), nullable=False)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    payer_name: Mapped[str | None] = mapped_column(String(120))
    received_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(40), nullable=False)
    received_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    external_transaction_no_ciphertext: Mapped[str | None] = mapped_column(Text)
    external_transaction_no_last4: Mapped[str | None] = mapped_column(String(4))
    internal_receipt_no: Mapped[str | None] = mapped_column(String(80))
    payment_status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    void_reason: Mapped[str | None] = mapped_column(Text)
    reversal_of_payment_id: Mapped[str | None] = mapped_column(ForeignKey("payments.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class PaymentAllocation(RecordMixin, Base):
    __tablename__ = "payment_allocations"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        CheckConstraint("allocated_amount_cent > 0", name="ck_payment_allocation_positive"),
    )
    payment_id: Mapped[str] = mapped_column(ForeignKey("payments.id"), index=True)
    receivable_id: Mapped[str] = mapped_column(ForeignKey("receivables.id"), index=True)
    allocated_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_status: Mapped[str] = mapped_column(String(20), default="ACTIVE", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    allocated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    allocated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reversal_of_allocation_id: Mapped[str | None] = mapped_column(ForeignKey("payment_allocations.id"))
    remarks: Mapped[str | None] = mapped_column(Text)


class AgencyPayable(RecordMixin, Base):
    __tablename__ = "agency_payables"
    __table_args__ = (
        UniqueConstraint("agency_payable_no"),
        UniqueConstraint("source_receivable_id"),
        CheckConstraint("payable_amount_cent >= 0", name="ck_agency_payable_nonnegative"),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    agency_payable_no: Mapped[str] = mapped_column(String(40), nullable=False)
    payee_type: Mapped[str] = mapped_column(String(30), default="EXAM_INSTITUTION")
    payee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    exam_batch_id: Mapped[str | None] = mapped_column(ForeignKey("exam_batches.id"))
    exam_attempt_id: Mapped[str | None] = mapped_column(ForeignKey("exam_attempts.id"))
    source_receivable_id: Mapped[str] = mapped_column(ForeignKey("receivables.id"), index=True)
    payable_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    payable_status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    due_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class AgencyDisbursement(RecordMixin, Base):
    __tablename__ = "agency_disbursements"
    __table_args__ = (
        UniqueConstraint("disbursement_no"),
        UniqueConstraint("idempotency_key"),
        CheckConstraint("paid_amount_cent > 0", name="ck_agency_disbursement_positive"),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    disbursement_no: Mapped[str] = mapped_column(String(40), nullable=False)
    payee_name: Mapped[str] = mapped_column(String(200), nullable=False)
    paid_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(40), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    external_transaction_no_ciphertext: Mapped[str | None] = mapped_column(Text)
    disbursement_status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class AgencyDisbursementAllocation(RecordMixin, Base):
    __tablename__ = "agency_disbursement_allocations"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        CheckConstraint("allocated_amount_cent > 0", name="ck_agency_allocation_positive"),
    )
    agency_disbursement_id: Mapped[str] = mapped_column(
        ForeignKey("agency_disbursements.id"), index=True
    )
    agency_payable_id: Mapped[str] = mapped_column(ForeignKey("agency_payables.id"), index=True)
    allocated_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reversal_of_allocation_id: Mapped[str | None] = mapped_column(
        ForeignKey("agency_disbursement_allocations.id")
    )


class RefundRequest(RecordMixin, Base):
    __tablename__ = "refund_requests"
    __table_args__ = (UniqueConstraint("refund_request_no"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    refund_request_no: Mapped[str] = mapped_column(String(40), nullable=False)
    course_enrollment_id: Mapped[str] = mapped_column(ForeignKey("course_enrollments.id"), index=True)
    student_id: Mapped[str] = mapped_column(ForeignKey("students.id"), index=True)
    refund_policy_version_id: Mapped[str] = mapped_column(ForeignKey("refund_policy_versions.id"))
    refund_reason: Mapped[str] = mapped_column(Text, nullable=False)
    request_status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    requested_amount_cent: Mapped[int | None] = mapped_column(Integer)
    calculated_refundable_amount_cent: Mapped[int | None] = mapped_column(Integer)
    approved_refund_amount_cent: Mapped[int | None] = mapped_column(Integer)
    manual_adjustment_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    manual_adjustment_reason: Mapped[str | None] = mapped_column(Text)
    active_snapshot_id: Mapped[str | None] = mapped_column(String(36))
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    rejected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    rejected_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    rejection_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class RefundCalculationSnapshot(RecordMixin, Base):
    __tablename__ = "refund_calculation_snapshots"
    __table_args__ = (UniqueConstraint("refund_request_id", "calculation_version_no"),)
    refund_request_id: Mapped[str] = mapped_column(ForeignKey("refund_requests.id"), index=True)
    calculation_version_no: Mapped[int] = mapped_column(Integer, nullable=False)
    tuition_receivable_id: Mapped[str] = mapped_column(ForeignKey("receivables.id"))
    tuition_paid_allocated_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    curriculum_total_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    locked_attended_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    minutes_cutoff_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    policy_method: Mapped[str] = mapped_column(String(50), nullable=False)
    rounding_mode: Mapped[str] = mapped_column(String(20), nullable=False)
    consumed_amount_numerator: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_amount_denominator: Mapped[int] = mapped_column(Integer, nullable=False)
    consumed_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    administrative_fee_cent: Mapped[int] = mapped_column(Integer, default=0)
    nonrefundable_fee_cent: Mapped[int] = mapped_column(Integer, default=0)
    previous_refunded_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    refundable_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    stale: Mapped[bool] = mapped_column(Boolean, default=False)
    warning_json: Mapped[str] = mapped_column(Text, default="[]")
    calculated_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class RefundAttendanceSnapshotLine(RecordMixin, Base):
    __tablename__ = "refund_attendance_snapshot_lines"
    __table_args__ = (UniqueConstraint("refund_calculation_snapshot_id", "attendance_record_id"),)
    refund_calculation_snapshot_id: Mapped[str] = mapped_column(
        ForeignKey("refund_calculation_snapshots.id"), index=True
    )
    attendance_record_id: Mapped[str] = mapped_column(ForeignKey("attendance_records.id"))
    attendance_revision_no: Mapped[int] = mapped_column(Integer, nullable=False)
    class_session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id"))
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    actual_attendance_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    locked_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)


class RefundPayment(RecordMixin, Base):
    __tablename__ = "refund_payments"
    __table_args__ = (
        UniqueConstraint("refund_payment_no"),
        UniqueConstraint("idempotency_key"),
        CheckConstraint("paid_amount_cent > 0", name="ck_refund_payment_positive"),
    )
    refund_payment_no: Mapped[str] = mapped_column(String(40), nullable=False)
    refund_request_id: Mapped[str] = mapped_column(ForeignKey("refund_requests.id"), index=True)
    paid_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(40), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    payee_name: Mapped[str | None] = mapped_column(String(120))
    external_transaction_no_ciphertext: Mapped[str | None] = mapped_column(Text)
    payment_status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reversal_of_refund_payment_id: Mapped[str | None] = mapped_column(ForeignKey("refund_payments.id"))


class RefundAllocation(RecordMixin, Base):
    __tablename__ = "refund_allocations"
    __table_args__ = (
        UniqueConstraint("refund_payment_id", "payment_allocation_id"),
        CheckConstraint("refunded_amount_cent > 0", name="ck_refund_allocation_positive"),
    )
    refund_payment_id: Mapped[str] = mapped_column(ForeignKey("refund_payments.id"), index=True)
    payment_allocation_id: Mapped[str] = mapped_column(ForeignKey("payment_allocations.id"), index=True)
    receivable_id: Mapped[str] = mapped_column(ForeignKey("receivables.id"), index=True)
    refunded_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class TeacherSettlementBatch(RecordMixin, Base):
    __tablename__ = "teacher_settlement_batches"
    __table_args__ = (UniqueConstraint("batch_no"),)
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    batch_no: Mapped[str] = mapped_column(String(40), nullable=False)
    period_start: Mapped[date] = mapped_column(Date, nullable=False)
    period_end: Mapped[date] = mapped_column(Date, nullable=False)
    settlement_status: Mapped[str] = mapped_column(String(30), default="DRAFT", index=True)
    total_minutes: Mapped[int] = mapped_column(Integer, default=0)
    total_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    calculated_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    calculated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    submitted_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    submitted_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    approved_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    cancellation_reason: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class TeacherSettlementLine(RecordMixin, Base):
    __tablename__ = "teacher_settlement_lines"
    __table_args__ = (
        UniqueConstraint("session_teacher_assignment_id"),
        CheckConstraint("final_amount_cent >= 0", name="ck_teacher_line_final_nonnegative"),
    )
    settlement_batch_id: Mapped[str] = mapped_column(ForeignKey("teacher_settlement_batches.id"), index=True)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("teacher_profiles.id"), index=True)
    session_teacher_assignment_id: Mapped[str] = mapped_column(
        ForeignKey("session_teacher_assignments.id"), nullable=False
    )
    class_session_id: Mapped[str] = mapped_column(ForeignKey("class_sessions.id"))
    class_cycle_id: Mapped[str] = mapped_column(ForeignKey("class_cycles.id"))
    service_date: Mapped[date] = mapped_column(Date, nullable=False)
    teaching_role: Mapped[str] = mapped_column(String(20), nullable=False)
    settleable_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    rate_unit_minutes: Mapped[int] = mapped_column(Integer, nullable=False)
    base_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    adjustment_amount_cent: Mapped[int] = mapped_column(Integer, default=0)
    final_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    adjustment_reason: Mapped[str | None] = mapped_column(Text)
    line_status: Mapped[str] = mapped_column(String(20), default="INCLUDED")
    source_version: Mapped[int] = mapped_column(Integer, nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class TeacherPayment(RecordMixin, Base):
    __tablename__ = "teacher_payments"
    __table_args__ = (
        UniqueConstraint("teacher_payment_no"),
        UniqueConstraint("idempotency_key"),
        CheckConstraint("paid_amount_cent > 0", name="ck_teacher_payment_positive"),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    teacher_payment_no: Mapped[str] = mapped_column(String(40), nullable=False)
    teacher_id: Mapped[str] = mapped_column(ForeignKey("teacher_profiles.id"), index=True)
    paid_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    payment_method: Mapped[str] = mapped_column(String(40), nullable=False)
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    external_transaction_no_ciphertext: Mapped[str | None] = mapped_column(Text)
    payment_status: Mapped[str] = mapped_column(String(20), default="DRAFT", index=True)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    remarks: Mapped[str | None] = mapped_column(Text)
    confirmed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    confirmed_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reversal_of_teacher_payment_id: Mapped[str | None] = mapped_column(ForeignKey("teacher_payments.id"))


class TeacherPaymentAllocation(RecordMixin, Base):
    __tablename__ = "teacher_payment_allocations"
    __table_args__ = (
        UniqueConstraint("idempotency_key"),
        CheckConstraint("allocated_amount_cent > 0", name="ck_teacher_payment_allocation_positive"),
    )
    teacher_payment_id: Mapped[str] = mapped_column(ForeignKey("teacher_payments.id"), index=True)
    teacher_settlement_line_id: Mapped[str] = mapped_column(
        ForeignKey("teacher_settlement_lines.id"), index=True
    )
    allocated_amount_cent: Mapped[int] = mapped_column(Integer, nullable=False)
    allocation_status: Mapped[str] = mapped_column(String(20), default="ACTIVE")
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
    reversal_of_allocation_id: Mapped[str | None] = mapped_column(
        ForeignKey("teacher_payment_allocations.id")
    )


class FinanceAttachment(RecordMixin, Base):
    __tablename__ = "finance_attachments"
    __table_args__ = (UniqueConstraint("owner_type", "owner_id", "file_object_id"),)
    owner_type: Mapped[str] = mapped_column(String(40), index=True)
    owner_id: Mapped[str] = mapped_column(String(36), index=True)
    file_object_id: Mapped[str] = mapped_column(ForeignKey("file_objects.id"), index=True)
    attachment_type: Mapped[str] = mapped_column(String(40), nullable=False)
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))


class TrainingEntitlement(RecordMixin, Base):
    """培训权益台账：一条课程报名对应的分钟额度汇总。

    汇总口径（单位：整数分钟，禁止 float）::

        total     = purchased_minutes + gifted_minutes
        available = total + free_rollover_minutes + supplement_minutes
                    - consumed_minutes - refund_deducted_minutes

    字段语义：

    - ``purchased_minutes`` 学员付费购买的分钟；
    - ``gifted_minutes`` 机构赠送的分钟；
    - ``free_rollover_minutes`` 因机构原因滚班而免费结转的分钟（不重复收费）；
    - ``supplement_minutes`` 学员补差后新增的分钟（对应补差应收）；
    - ``consumed_minutes`` 已消耗分钟（已履约）；
    - ``refund_deducted_minutes`` 退费时按已履约口径扣减的分钟（退费扣减依据）。

    本模型只承载**机制**；具体计费口径、哪些滚班情形免费、补差单价，
    取决于业务方确认（见 ``docs/implementation/roadmap.md`` 「真实资料待确认」）。
    """

    __tablename__ = "training_entitlements"
    __table_args__ = (
        UniqueConstraint("organization_id", "course_enrollment_id"),
        CheckConstraint("purchased_minutes >= 0", name="ck_entitlement_purchased_nonnegative"),
        CheckConstraint("gifted_minutes >= 0", name="ck_entitlement_gifted_nonnegative"),
        CheckConstraint(
            "free_rollover_minutes >= 0", name="ck_entitlement_free_rollover_nonnegative"
        ),
        CheckConstraint("supplement_minutes >= 0", name="ck_entitlement_supplement_nonnegative"),
        CheckConstraint("consumed_minutes >= 0", name="ck_entitlement_consumed_nonnegative"),
        CheckConstraint(
            "refund_deducted_minutes >= 0", name="ck_entitlement_refund_deducted_nonnegative"
        ),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    course_enrollment_id: Mapped[str] = mapped_column(
        ForeignKey("course_enrollments.id"), index=True
    )
    purchased_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    gifted_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    free_rollover_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    supplement_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    consumed_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    refund_deducted_minutes: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    entitlement_status: Mapped[str] = mapped_column(String(30), default="ACTIVE", index=True)
    rule_version: Mapped[str | None] = mapped_column(String(40))
    remarks: Mapped[str | None] = mapped_column(Text)
    created_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))
    updated_by: Mapped[str | None] = mapped_column(ForeignKey("users.id"))


class TrainingEntitlementEntry(RecordMixin, Base):
    """培训权益变动明细：只增不改，冲正用反向分录（``reversal_of_entry_id``）。

    ``minutes_delta`` 为正表示增加权益，为负表示消耗或扣减。
    每次变动必须带 ``idempotency_key``，与组织组成唯一约束，用于拦截重复请求。
    """

    __tablename__ = "training_entitlement_entries"
    __table_args__ = (
        UniqueConstraint("organization_id", "idempotency_key"),
        CheckConstraint("minutes_delta <> 0", name="ck_entitlement_entry_nonzero"),
    )
    organization_id: Mapped[str] = mapped_column(ForeignKey("organizations.id"), index=True)
    entitlement_id: Mapped[str] = mapped_column(ForeignKey("training_entitlements.id"), index=True)
    entry_type: Mapped[str] = mapped_column(String(40), nullable=False, index=True)
    minutes_delta: Mapped[int] = mapped_column(Integer, nullable=False)
    source_type: Mapped[str | None] = mapped_column(String(40))
    source_id: Mapped[str | None] = mapped_column(String(36))
    reason: Mapped[str | None] = mapped_column(Text)
    rule_version: Mapped[str | None] = mapped_column(String(40))
    accounting_date: Mapped[date | None] = mapped_column(Date)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utc_now)
    idempotency_key: Mapped[str] = mapped_column(String(100), nullable=False)
    reversal_of_entry_id: Mapped[str | None] = mapped_column(
        ForeignKey("training_entitlement_entries.id")
    )
    created_by: Mapped[str] = mapped_column(ForeignKey("users.id"))
