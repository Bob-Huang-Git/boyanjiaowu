# ADR-0002：附件存储本地优先，OSS 后续接入

- **状态**：已采纳（Accepted）——本地阶段已实现，OSS 阶段待启动
- **决策人**：项目负责人（用户）
- **留档日期**：2026-09-23
- **影响范围**：附件模块、上传协议、前端上传路径、部署（`/data` 挂载与容量）、Prompt 2（原为 Sprint 2 本地附件中心）、Prompt 9（OSS 私有附件）
- **基线偏离**：本决策**偏离** V3.0 原文「附件存储：阿里云 OSS 私有 Bucket」的第一期落地时序。原文 Prompt 9 要求第一期即采用「prepare-upload → V4 预签名 URL → 浏览器直传 OSS → complete-upload → HeadObject 校验」的链路；本决策改为**先本地落盘、后接入 OSS**。

---

## 一、背景

V3.0 原文把「阿里云 OSS 私有附件」列为 Prompt 9，并规定第一期使用单一私有 Bucket + 前缀隔离，上传走浏览器直传 + 预签名。

项目推进中，项目负责人明确要求：**附件先使用本地存储，后续再接 OSS**。

## 二、决策

**建立存储抽象层 `StorageBackend`，第一期仅实现本地受控副本后端；OSS 后端与直传协议推迟到后续阶段。**

分层职责：

| 层 | 第一期 | 后续（接入 OSS 时） |
| --- | --- | --- |
| 存储抽象（ABC） | 已建：`StorageBackend` | 新增 `AliyunOssStorage` 实现，**业务代码不需要改动** |
| 上传路径 | FormData 经 FastAPI 落本地受控目录 | 改为 prepare-upload / complete-upload + 浏览器直传 |
| 下载路径 | `create_download_reference()` 抽象方法 | 改为短时签名 URL |
| 副本管理 | 单副本（本地为主副本） | 本地 → OSS 复制 → 校验 → 提升 OSS 为主副本 |

## 三、理由

1. **先闭环业务，再引入外部依赖**：附件能力不是业务主干，本地存储即可让学员 360 的资料页签、审核替换流程跑通，避免在业务模型尚未稳定时被 OSS 的签名、CORS、RAM Policy 细节拖住。
2. **降低环境依赖**：开发与测试环境不需要真实 Bucket，也不需要在 CI 中配置云端凭证。
3. **抽象层让迁移成本可控**：`get_storage()` 是唯一入口，业务层不感知具体后端——这使「以后换 OSS」成为**替换实现**而不是**改造业务**。
4. **数据主副本留在本地更安全**：在 OSS 方案未完成权限与生命周期配置评审前，本地主副本避免了「唯一副本在云端但配置未评审」的风险。

## 四、已实现的抽象质量（实测，优于原设计）

| 项 | 事实 | 评价 |
| --- | --- | --- |
| 抽象泄漏 | 业务代码（`app/modules/**`、`app/cli/**`）**零处**直接引用 `LocalStorageBackend`，全部经 `get_storage()` | ✅ 抽象干净 |
| 多副本模型 | `FileReplica` 使用 `Index("uq_file_replicas_primary", "file_object_id", unique=True, sqlite_where=text("is_primary = 1 AND deleted_at IS NULL"))` | ✅ **优于原设计**：原设计只有单一 `FileObject`，此处天然支持「本地主副本 → 复制到 OSS → 校验 → 提升 OSS 为主副本 → 本地降级」 |
| 副本状态机 | `replica_status` 含 `COPYING`，另有 `provider_etag`、`provider_version_id`、`verified_at`、`last_checked_at`、`failure_code` | ✅ 迁移所需的观测字段齐备 |
| 隔离态预留 | `QUARANTINED` 状态已预留（病毒扫描为上线增强项） | ✅ 符合 Prompt 9 第五节「架构保留 QUARANTINED 状态」 |
| 清理 CLI | `cleanup-staged`、`cleanup-orphans` 已实现 | ✅ 符合 Prompt 9 第五节「pending 孤儿对象由 Cron 清理」 |
| 落盘原子性 | tmp + fsync + `os.replace` | ✅ |
| 路径安全 | 对象键校验拒绝 `..`、绝对路径、反斜杠 | ✅ 符合 Prompt 9 第三节「禁止 PII 进入 Object Key」的方向 |

## 五、已知缺口（接入 OSS 前必须补齐）

> **不要把 OSS 接入估算为「新增一个实现类」。** 持久层已就绪，**上传协议层是空白**。

现状：上传走 `multipart/form-data` 经 FastAPI 进程；`StorageBackend` ABC 中**只有 `create_download_reference()`，没有 `create_upload_reference()`**；无分片（upload_id / part）概念。

接入 OSS 的真实工作量：

1. 在 ABC 中新增 `create_upload_reference()`，并实现本地与 OSS 两个版本。
2. 新增 `POST /api/files/prepare-upload` 与 `POST /api/files/complete-upload` 两个端点；`complete-upload` **必须幂等**，并用 HeadObject 校验存在性、大小、Content-Type 与校验信息。
3. **改造前端上传路径**为「先请求预签名 → 直传 → 回报」三段式（当前是表单直提）。
4. 录屏等大文件引入分片上传（后端控制 `upload_id` 与 `object_key`，前端只上传授权 part），并补「清理未完成分片」的 CLI。

其他待补项（Prompt 9 要求，本地阶段未覆盖）：

- 扩展名 / Content-Type / **文件魔数**三者一致性校验。
- 文件大小限制与「Office/PDF 模板仅允许授权管理员上传」。
- 下载时**每次重新鉴权**（组织、对象归属、角色、数据范围、附件权限、文件状态）。
- 签名 URL 有效期 60–300 秒，且**不写入数据库、不写入日志**（日志不记录完整 query string）。
- 身份证 / 退役证下载需记录理由与审计。

## 六、后续

1. **OSS 阶段启动前，先写 ADR-0003《上传协议：服务端中转 vs 浏览器直传》**，把上述 4 项工作量确认为设计，避免边写边改。
2. 本地阶段的数据迁移方案：以 `FileReplica` 的 `is_primary` 部分唯一索引为支撑，采用「新增 OSS 副本（非主）→ 校验哈希与大小 → 将 OSS 提升为主副本 → 本地副本降级为备份后按策略清理」，全过程保留 `verified_at` 与 `failure_code` 作为可观测证据。
3. 本地磁盘容量与 `/data` 挂载属于部署约束，需在 OSS 接入后重新评估保留策略（`docs/operations/local-storage.md`）。

---

*关联文档：`docs/architecture/baseline.md`、`docs/architecture/future-oss.md`、`docs/architecture/file-storage.md`、`docs/architecture/design-conformance-review-2026-09-23.md` 第八节（迁移就绪度评估）、`ADR-0001`（原生部署）*
