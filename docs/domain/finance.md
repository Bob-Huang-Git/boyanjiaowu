# 收款与应收

`Receivable` 表示学员应交，`Payment` 表示学校实际收到，`PaymentAllocation` 保存二者之间的分配。应收与收款彼此独立，一笔收款可以分配给多个应收，一个应收也可以分多次收取。未分配收款保留为资金余额，不计入某项收入。

培训费来源为报名绑定的 `FeePolicyVersion`，考试费来源为已确认的 `ExamFeeAssessment`。来源字段有唯一约束，重复交接返回已有记录。确认后的原金额不覆盖修改；调整追加 `ReceivableAdjustment`，错误分配和付款通过冲正保留历史。

所有金额字段单位为整数分，不使用浮点数。`SCHOOL_REVENUE` 是学校培训收入，`AGENCY_COLLECTION` 是代考试机构收取的资金，账户、汇总和异常队列分别计算两类资金。
