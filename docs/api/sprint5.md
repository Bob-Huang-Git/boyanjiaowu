# Sprint 5 API 约定

财务 API 位于 `/api`。金额字段以 `_cent` 结尾并使用整数分，分钟字段以 `_minutes` 结尾并使用整数分钟。创建付款和分配要求 `idempotency_key`；状态动作要求当前 `version`，并发冲突返回 HTTP 409 与稳定业务错误码。

主要资源包括 `/receivables`、`/payments`、`/agency-payables`、`/agency-disbursements`、`/refund-requests`、`/refund-payments`、`/teacher-settlement-batches` 和 `/teacher-payments`。状态只能通过 `/confirm`、`/allocate`、`/submit`、`/approve`、`/cancel`、`/void` 或 `/reverse` 等动作端点变更。

账户汇总为 `/students/{id}/financial-overview`、`/enrollments/{id}/financial-statement`、`/finance/agency-summary`、`/teachers/{id}/settlement-summary` 和 `/finance/exceptions`。汇总返回 `calculated_at`，数字可下钻到明细。
