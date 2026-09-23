# ruff: noqa: E501, E702
# fmt: off
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Permission, Role, RolePermission

PERMISSIONS = {
    "receivable.read": "查看应收", "receivable.manage": "管理应收", "receivable.adjust": "调整应收",
    "payment.read": "查看收款", "payment.create": "录入收款", "payment.confirm": "确认收款",
    "payment.allocate": "分配收款", "payment.reverse": "冲正收款",
    "agency_payable.read": "查看应代缴", "agency_payable.manage": "管理应代缴",
    "agency_disbursement.create": "录入代缴付款", "agency_disbursement.confirm": "确认代缴付款",
    "refund.read": "查看退款", "refund.calculate": "计算退款", "refund.submit": "提交退款",
    "refund.approve": "审批退款", "refund.pay": "执行退款付款", "refund.reverse": "冲正退款",
    "teacher_settlement.read": "查看教师结算", "teacher_settlement.calculate": "计算教师结算",
    "teacher_settlement.submit": "提交教师结算", "teacher_settlement.approve": "审批教师结算",
    "teacher_payment.create": "录入教师付款", "teacher_payment.confirm": "确认教师付款",
    "finance.evidence.read": "查看财务凭证", "finance.export": "导出财务数据",
}


def main() -> None:
    with Session(get_engine()) as db:
        roles = db.scalars(select(Role).where(Role.code == "admin")).all()
        for code, description in PERMISSIONS.items():
            permission = db.scalar(select(Permission).where(Permission.code == code))
            if not permission:
                permission = Permission(code=code, description=description); db.add(permission); db.flush()
            for role in roles:
                if not db.scalar(select(RolePermission).where(RolePermission.role_id == role.id, RolePermission.permission_id == permission.id)):
                    db.add(RolePermission(organization_id=role.organization_id, role_id=role.id, permission_id=permission.id))
        db.commit()
    print(f"Sprint 5 permissions synchronized for {len(roles)} admin role(s)")


if __name__ == "__main__":
    main()
