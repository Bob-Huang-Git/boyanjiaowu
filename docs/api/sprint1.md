# Sprint 1 API 约定

列表接口在 SQL 层过滤、排序和分页。学员列表支持 `page`、`page_size`、`keyword`、`student_status`、`sort` 与 `order`；排序仅允许学员编号、姓名和更新时间。

写接口需要登录、对应业务权限和 `X-CSRF-Token`。报名和导入确认使用调用方提供的幂等键。常见稳定错误码包括 `DUPLICATE_CONFIRMED`、`POSSIBLE_DUPLICATE`、`VERSION_INCOMPLETE`、`OFFERING_NOT_AVAILABLE`、`ACTIVE_MEMBERSHIP_EXISTS`、`CLASS_COURSE_MISMATCH`、`VERSION_CONFLICT` 与 `IMPORT_BATCH_EXPIRED`。

业务详情均使用不可猜测 UUID。普通 API 不返回证件号、手机号明文、密文、加密密钥或盲索引。

