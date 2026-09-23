from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Permission, Role, RolePermission

PERMISSIONS = {
    "exam.batch.read": "查看考试批次",
    "exam.batch.manage": "管理考试批次",
    "exam.registration.read": "查看考试报名",
    "exam.registration.manage": "管理考试报名",
    "exam.result.read": "查看考试成绩",
    "exam.result.edit": "录入考试成绩",
    "exam.result.submit": "提交考试成绩",
    "exam.result.confirm": "确认官方成绩",
    "exam.result.revise": "修订官方成绩",
    "exam.result.import": "导入考试成绩",
    "exam_fee_assessment.read": "查看考试费用认定",
    "exam_fee_assessment.confirm": "确认考试费用认定",
    "exam_fee_assessment.waive": "减免考试费用认定",
    "certificate.read": "查看证书",
    "certificate.manage": "管理证书代发",
    "certificate.deliver": "发放证书",
    "certificate.sensitive.reveal": "查看证书敏感编号",
    "certificate.attachment.read": "查看证书附件",
}


def main() -> None:
    with Session(get_engine()) as db:
        roles = db.scalars(select(Role).where(Role.code == "admin")).all()
        for code, description in PERMISSIONS.items():
            permission = db.scalar(select(Permission).where(Permission.code == code))
            if not permission:
                permission = Permission(code=code, description=description)
                db.add(permission)
                db.flush()
            for role in roles:
                exists = db.scalar(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == permission.id,
                    )
                )
                if not exists:
                    db.add(
                        RolePermission(
                            organization_id=role.organization_id,
                            role_id=role.id,
                            permission_id=permission.id,
                        )
                    )
        db.commit()
    print(f"Sprint 4 permissions synchronized for {len(roles)} admin role(s)")


if __name__ == "__main__":
    main()
