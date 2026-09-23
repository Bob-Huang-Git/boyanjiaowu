import getpass

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.db import get_engine
from app.core.models import Organization, Permission, Role, RolePermission, User, UserRole
from app.core.permission_catalog import SPRINT6_PERMISSIONS
from app.core.security import hash_password


def main() -> None:
    username = input("Administrator username: ").strip()
    if not username:
        raise SystemExit("Username is required")
    password = getpass.getpass("Administrator password: ")
    if len(password) < 6:
        raise SystemExit("Password must have at least 6 characters")
    with Session(get_engine()) as db:
        if db.scalar(select(User).where(User.username == username)):
            raise SystemExit("Username already exists")
        organization = db.scalar(select(Organization).limit(1))
        if organization is None:
            raise SystemExit("Run alembic upgrade head first")
        role = db.scalar(
            select(Role).where(Role.organization_id == organization.id, Role.code == "admin")
        )
        if role is None:
            role = Role(organization_id=organization.id, code="admin", name="系统管理员")
            db.add(role)
            db.flush()
        permissions = {
            "system.admin": "系统管理",
            "student.read": "查看学员",
            "student.create": "创建学员",
            "student.update": "修改学员",
            "student.deactivate": "停用学员",
            "student.sensitive.reveal": "查看敏感信息",
            "student.import": "导入学员",
            "course.read": "查看课程",
            "course.manage": "管理课程",
            "course.publish": "发布课程",
            "enrollment.read": "查看报名",
            "enrollment.create": "创建报名",
            "enrollment.cancel": "取消报名",
            "class.read": "查看班级",
            "class.manage": "管理班级",
            "class.member.manage": "管理班级成员",
            "attachment.read": "查看资料附件",
            "attachment.upload": "上传资料附件",
            "attachment.download": "下载资料附件",
            "attachment.review": "审核资料附件",
            "attachment.replace": "替换资料附件",
            "attachment.delete": "删除资料附件",
            "attachment.category.manage": "管理资料分类",
            "attachment.storage.inspect": "检查附件存储",
            "teacher.read": "查看教师",
            "teacher.manage": "管理教师",
            "class_session.read": "查看课次",
            "class_session.manage": "管理课次",
            "class_session.complete": "完成课次",
            "session_teacher.manage": "管理授课安排",
            "session_teacher.confirm": "确认教师分钟",
            "attendance.read": "查看考勤",
            "attendance.edit": "编辑考勤",
            "attendance.submit": "提交考勤",
            "attendance.confirm": "确认考勤",
            "attendance.lock": "锁定考勤",
            "attendance.revise": "修订考勤",
            "enrollment.rollover": "滚班",
            "recording.read": "查看录屏",
            "recording.manage": "管理录屏",
            "recording.review": "审核录屏",
            "recording.access_code.reveal": "查看录屏口令",
            "teaching_summary.read": "查看教师课时",
            "teaching_summary.export": "导出教师课时",
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
            "receivable.read": "查看应收",
            "receivable.manage": "管理应收",
            "receivable.adjust": "调整应收",
            "payment.read": "查看收款",
            "payment.create": "录入收款",
            "payment.confirm": "确认收款",
            "payment.allocate": "分配收款",
            "payment.reverse": "冲正收款",
            "agency_payable.read": "查看应代缴",
            "agency_payable.manage": "管理应代缴",
            "agency_disbursement.create": "录入代缴付款",
            "agency_disbursement.confirm": "确认代缴付款",
            "refund.read": "查看退款",
            "refund.calculate": "计算退款",
            "refund.submit": "提交退款",
            "refund.approve": "审批退款",
            "refund.pay": "执行退款付款",
            "refund.reverse": "冲正退款",
            "teacher_settlement.read": "查看教师结算",
            "teacher_settlement.calculate": "计算教师结算",
            "teacher_settlement.submit": "提交教师结算",
            "teacher_settlement.approve": "审批教师结算",
            "teacher_payment.create": "录入教师付款",
            "teacher_payment.confirm": "确认教师付款",
            "finance.evidence.read": "查看财务凭证",
            "finance.export": "导出财务数据",
        }
        permissions.update(SPRINT6_PERMISSIONS)
        for permission_code, description in permissions.items():
            permission = db.scalar(select(Permission).where(Permission.code == permission_code))
            if permission is None:
                permission = Permission(code=permission_code, description=description)
                db.add(permission)
                db.flush()
            if (
                db.scalar(
                    select(RolePermission).where(
                        RolePermission.role_id == role.id,
                        RolePermission.permission_id == permission.id,
                    )
                )
                is None
            ):
                db.add(
                    RolePermission(
                        organization_id=organization.id,
                        role_id=role.id,
                        permission_id=permission.id,
                    )
                )
        user = User(
            organization_id=organization.id,
            username=username,
            display_name=username,
            password_hash=hash_password(password),
        )
        db.add(user)
        db.flush()
        db.add(UserRole(organization_id=organization.id, user_id=user.id, role_id=role.id))
        db.commit()
    print("Administrator created")


if __name__ == "__main__":
    main()
