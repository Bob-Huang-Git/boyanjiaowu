# 滚班

滚班不会创建新的 `CourseEnrollment`。服务结束原 `ClassMembership` 并新建同一报名的 ACTIVE 成员经历，使用 `previous_membership_id` 连接历史。目标班必须使用相同课程版本并有容量；请求的 `idempotency_key` 防止重复提交。历史课次和考勤不复制、不删除，财务处理只保存 `financial_treatment` 供后续阶段处理。
