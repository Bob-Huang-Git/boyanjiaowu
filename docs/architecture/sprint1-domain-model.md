# Sprint 1 领域模型

```text
Student 1 ── * CourseEnrollment * ── 1 CourseOfferingVersion
                     │
                     └── * ClassMembership * ── 1 ClassCycle
```

`Student` 是自然人唯一主档。它不等于报名记录，也不等于班级名单的一行。一个学员可以报名多门课程，也可以在未来重新购买同一课程，因此 `CourseEnrollment` 代表一次独立业务关系。

`ClassMembership` 只关联报名，不直接关联学员。滚班时应结束旧成员经历并创建引用 `previous_membership_id` 的新经历；不能通过修改原记录的班级伪造滚班，也不能把滚班误建为新报名。

课程目录 `CourseCatalog` 是稳定品类；`CourseOfferingVersion` 绑定课程方案、考试方案、收费规则和退费规则的快照。报名保存这些版本 ID，因此后续发布新版本不会改变历史报名。

关键数据库规则：学员编号、课程编码、班级编码、报名编号唯一；证件类型与盲索引唯一；报名在同一时刻至多有一条 ACTIVE 班级经历；报名幂等键在机构内唯一。金额使用整数分，时长使用整数分钟。

