# 考试领域

`CourseEnrollment` 是考试身份。一次批次报名形成 `ExamRegistration`，所选批次科目分别形成 `ExamRegistrationSubject` 和一条 `ExamAttempt`。滚班不会新建或替换课程报名，因此考试历史保持连续。

每个课程科目的 `attempt_no` 从 1 连续递增。第 1 次为 `INITIAL`，第 2 次及以后为 `RESIT`。已有官方确认通过的科目不能再次报名；上一尝试尚未官方确认时也不能创建补考。总体 `exam_status` 是明细投影：无尝试、进行中、部分通过、失败和全部通过均由必考科目的官方确认结果计算。

当前默认规则中，报名创建的尝试即占用一个连续次数；缺考在官方确认为 `ABSENT` 后也计入该次尝试，下一次报名按补考处理。将来如考试方案允许免计次数，需要在版本化考试政策中新增明确字段后再改变规则。

分数使用 `score_value_scaled` 与 `score_scale`，例如 85.50 分保存为 8550/100，不使用浮点数。成绩依次经过 `DRAFT`、`SUBMITTED`、`OFFICIALLY_CONFIRMED`。官方确认后普通编辑被拒绝；独立修订动作要求理由并保存前后快照。若修订使已发证学员失去资格，证书案例进入 `EXCEPTION` 并追加事件，历史不会删除。

批次状态通过动作迁移：`DRAFT → OPEN → REGISTRATION_CLOSED → IN_PROGRESS → COMPLETED`。取消使用独立动作并保留报名、尝试和费用历史。
