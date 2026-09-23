# 未来方案：OSS（尚未实现）

本阶段没有 OSS SDK、配置、密钥、连接、签名 URL、Mock 或迁移命令。`STORAGE_BACKEND=oss` 会使应用以“OSS后端尚未实现”明确失败。

未来新增 `OssStorageBackend` 实现同一 `StorageBackend` 接口。迁移原则是：为同一 FileObject 创建 OSS FileReplica，从 LOCAL 流式复制，校验大小与 SHA-256，才提升 OSS 主副本，并保留 LOCAL 观察期；校验失败可恢复已验证 LOCAL 主副本。业务资料、权限、审核和下载 API 不需要改动。
