# 本地附件存储（Sprint 2）

Sprint 2 使用三层模型：`FileObject` 保存不可变文件元数据与 SHA-256，`FileReplica` 保存受控逻辑对象键与物理副本状态，`StudentDocument` 将文件关联到学员与资料分类。数据库不保存二进制、绝对路径或对象键以外的物理位置。

当前唯一可用副本是 `LOCAL` 主副本。业务服务只使用 `StorageBackend`，由配置工厂注入 `LocalStorageBackend`；前端只按学员资料 ID 下载和预览。对象键格式为 `student-documents/YYYY/MM/<UUID>.<extension>`，不含 PII。

状态：文件 `STAGED → ACTIVE`，异常可标为 `MISSING` 或 `QUARANTINED`，逻辑删除为 `DELETED`；资料 `PENDING_REVIEW → VERIFIED|REJECTED`，替换旧资料为 `SUPERSEDED`，删除为 `DELETED`。替换必定建立新的 FileObject 和 StudentDocument。

SQLite 的部分唯一索引保证一个 FileObject 只有一个未删除主副本，并保证同一学员分类只有一个当前主资料。服务层也会检查冲突。
