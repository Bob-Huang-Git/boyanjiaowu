# 考勤、锁定与修订

考勤以 `ClassMembership` 为外键，按课次计划开始时成员经历的进入和退出时间判定资格。记录保存整数应到、实到、迟到和早退分钟；批量草稿逐行返回结果。

考勤工作流为 `DRAFT → SUBMITTED → CONFIRMED → LOCKED`。锁定要求课次已完成、应点名成员记录齐全且全部已确认。锁定后只允许 `attendance.revise` 通过带理由的修订建立 `AttendanceRevision`，并将记录退回草稿以重新确认和锁定。`AttendanceFinalization` 保留每次锁定快照。
