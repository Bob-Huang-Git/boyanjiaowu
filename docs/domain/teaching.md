# 教学执行（Sprint 3）

`ClassCycle → ClassSession → AttendanceRecord` 记录班级教学事实；`TeacherProfile → SessionTeacherAssignment → ClassSession` 记录每名教师的独立授课分钟。班级完成分钟只统计已完成课次的 `actual_minutes`，教师分钟按已完成且已确认的教师安排单独汇总，因此共同授课 120 分钟可产生 120 班级分钟和 240 教师分钟。

课次状态为 `DRAFT → SCHEDULED → IN_PROGRESS → COMPLETED`，取消进入 `CANCELLED` 并保留原因。状态转换使用动作 API；历史课次不会被改期覆盖。
