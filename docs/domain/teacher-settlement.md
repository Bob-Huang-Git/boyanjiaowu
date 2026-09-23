# 教师结算

结算只纳入 `COMPLETED` 课次中状态为 `CONFIRMED` 的教师安排。每位教师使用自己的 `settleable_minutes`、`rate_amount_cent` 和 `rate_unit_minutes` 快照，金额采用整数 `HALF_UP` 计算。同一课次的两名教师分别结算，班级分钟不替代教师分钟。

批次经过计算、提交、审批后才能付款，提交人默认不能自审。调整保存金额和原因；批准后普通接口不能修改明细。`TeacherPaymentAllocation` 支持同一教师分次付款或一笔付款覆盖多条明细，并拒绝跨教师与超额分配。确认付款通过冲正保留历史。

本模块是课时业务结算，不含个税、工资、社保和会计凭证。
