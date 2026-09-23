# Sprint 4 API 约定

API 位于 `/api`，交互式 OpenAPI 为 `/api/docs`。所有写请求沿用会话 Cookie、CSRF 请求头和权限校验。

主要资源：

- `/exam-batches`：批次创建、科目配置和状态动作。
- `/exam-registrations`：分科报名；服务自动判断 `INITIAL`、`RESIT` 或 `MIXED`。
- `/exam-attempts`：定点成绩草稿、提交、退回、官方确认和修订。
- `/imports/exam-results`：xlsx 模板、Preview、Confirm 和结果。
- `/exam-fee-assessments`：费用依据确认、减免和取消，没有付款动作。
- `/certificates`：资格、申请、发证、学校接收、待发放、发放、异常和事件。

金额字段均以 `_amount_cent` 或 `amount_cent` 命名，单位为人民币分。分数展示值等于 `score_value_scaled / score_scale`。报名和导入确认接受客户端幂等键；状态动作接受当前 `version`，并发冲突返回 HTTP 409。

常见稳定错误码包括 `EXAM_BATCH_STATUS_CONFLICT`、`EXAM_REGISTRATION_CLOSED`、`SUBJECT_ALREADY_PASSED`、`PREVIOUS_RESULT_PENDING`、`EXAM_RESULT_SCORE_MISMATCH`、`EXAM_RESULT_LOCKED`、`EXAM_IMPORT_EXPIRED`、`FEE_ASSESSMENT_CONFLICT` 和 `CERTIFICATE_STATUS_CONFLICT`。错误响应位于 `detail.code` 与 `detail.message`，不会返回密文、对象键、本地路径或内部堆栈。
