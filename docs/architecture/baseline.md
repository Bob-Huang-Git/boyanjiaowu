# 权威基线（Authoritative Baseline）

- **生效日期**：2026-09-23
- **基线锚点**：git tag `baseline-v0.5.0-sprint5`
- **维护规则**：本文件是**唯一**的基线声明处。任何对基线的变更都必须经 ADR 留档后，在此登记。

---

## 一、基线由什么构成

| 组成 | 文件 | 性质 | 可修改性 |
| --- | --- | --- | --- |
| **需求基线** | `docs/requirements/codex-prompts-fastapi-sqlite-training-system.md` | 工作副本（已含偏离） | 可修订，但每次修订必须在本文件登记 |
| **需求原件** | `docs/requirements/codex-prompts-v3.0-original.md` | V3.0 原始设计 | **不可改写**（见第四节：待落盘） |
| **偏离决策** | `docs/architecture/adr/ADR-*.md` | 决策记录 | 只能被新 ADR 取代，不得原地修改 |
| **验收基线** | `docs/implementation/acceptance-checklist.md` | 必测用例与阶段交付物清单 | 只增不减；削减需记录理由 |

## 二、当前已确认的偏离（登记表）

| # | ADR | 偏离内容 | 状态 |
| --- | --- | --- | --- |
| 1 | [ADR-0001](adr/ADR-0001-native-deploy-instead-of-docker.md) | 放弃 Docker Compose，改为 ECS 原生部署（Nginx + systemd + Uvicorn 单 worker） | 已采纳，已落地 |
| 2 | [ADR-0002](adr/ADR-0002-local-storage-first-oss-later.md) | 附件存储本地优先，OSS 后续接入（保留 `StorageBackend` 抽象） | 已采纳，本地阶段已实现 |

**决策记录（非偏离，业务口径澄清）**：

| # | 内容 | 日期 | 处置 |
| --- | --- | --- | --- |
| 1 | 一个课程报名**只允许一条证书记录** → `CertificateCase` 的 `UniqueConstraint("course_enrollment_id")` 是正确设计 | 2026-09-23 | 保留约束，不做迁移 |
| 2 | 本系统**不需要**成绩有效期，也**不需要**区分必考 / 选考 → `required_subject_count = len(subjects)` 语义正确（全部科目均为必考） | 2026-09-23 | 不新增字段 |

上述两项曾出现在 `design-conformance-review-2026-09-23.md` 的缺口清单中，**已撤回**，详见该报告第五节「已撤回项」。

## 三、不得偏离的锁定项（来自 V3.0，无需 ADR）

以下为 V3.0 明确锁定、且当前**没有**任何偏离决策的硬约束。任何人（含 AI 助手）不得以「生产化」「性能」「以后可能扩容」为由擅自引入：

**技术栈锁定**

- Python 3.12、FastAPI、SQLAlchemy 2.x **同步** Session、Pydantic v2、SQLite、Alembic（SQLite batch migration）
- Vue 3、TypeScript、Vite、Element Plus、Pinia、pytest、Ruff、openpyxl、docxtpl、python-docx
- 阿里云官方 Python OSS SDK（**封装为独立适配器**，业务层不得直接依赖）

**第一期禁止引入**

> PostgreSQL、MySQL、Redis、Celery、RabbitMQ、Kafka、微服务、Kubernetes、Elasticsearch、第二套 ORM、第二套数据库迁移工具、Docker / 容器运行时

**数据规范锁定**

- 金额一律**整数分**（`_amount_cent` / `_price_cent`），**禁止 float**
- 时长一律**整数分钟**；课时换算规则须版本化
- 业务时区 `Asia/Shanghai`；数据库存 UTC；政策 / 上课 / 住宿日期用独立 `date` 字段，不从 UTC 时间推断
- SQLite 启动必须生效：`journal_mode=WAL`、`foreign_keys=ON`、`busy_timeout=5000`、`synchronous=NORMAL`
- **单 Uvicorn worker**；数据库文件必须在 ECS 本地数据盘，**禁止放 OSS / NAS / NFS / 网络共享目录**

**历史数据锁定**（确认后禁止覆盖或删除，只能用撤销 / 冲正 / 调整 / 新 revision）

> 已确认考勤、官方考试结果、收款与收款分配、已审批退款、考试机构代缴、已确认教师课时、已审批教师结算、补贴权益与政府申报、正式报表快照

**禁止清单**（V3.0 附录「执行纪律补充」，违反即为退化）

- 把业务状态塞进一个万能 `status`（须按 lifecycle / learning / exam / financial / certificate / funding 分列）
- 把课程、科目、政策写死在 Python 枚举或前端
- 复制正在运行的 SQLite 文件作为备份（须用 `sqlite3` backup API 或 `VACUUM INTO`）
- 在 FastAPI BackgroundTasks 中处理退款、申报等关键业务
- 保存永久 OSS URL / 预签名 URL 到数据库或日志
- 身份证号、退役证号进入 Object Key
- 用前端按钮禁用代替数据库唯一约束与幂等键
- 让数据库执行任意 Python / SQL / `eval` / 不受控 Jinja 表达式

## 四、待办：需求原件落盘

**现状**：`docs/requirements/codex-prompts-v3.0-original.md` **尚不存在**。仓库内 `docs/requirements/` 下只有已被改写的派生版（实测「docker」出现 0 次），且 git 历史中亦无原件（仓库仅 1 个 commit，该 commit 内已是派生版）。

**影响**：需求基线目前**依赖项目负责人持有的原件**。若原件丢失，则无法复核派生版是否还有其他未被登记的就地改写。

**要求**：由项目负责人将 V3.0 原件**逐字**落盘为 `docs/requirements/codex-prompts-v3.0-original.md`，此后**永不改写**。

> 说明：本项刻意**不代为转录**。逐字保真的唯一可靠来源是原件本身；任何"凭上下文重写"都可能引入不可察觉的偏差——而这正是本仓库已经发生过、并被本项目批评过的问题（设计文档被就地改写且无留档）。宁可留一个显式的待办，也不制造第二份「看起来像原文」的副本。

补充说明：**该待办不阻塞任何开发与评审**。因为已识别的偏离均已在 ADR-0001 / ADR-0002 中留档，验收标尺已由 `acceptance-checklist.md` 独立承载。

## 五、基线变更流程

任何偏离基线的要求，必须按以下顺序处理：

1. **写 ADR**：`docs/architecture/adr/ADR-XXXX-<slug>.md`，含状态、决策人、日期、背景、决策、理由、影响、被放弃的原文要求、后续。
2. **在本文件第二节登记**（表格追加一行）。
3. **同步修订派生版需求文档**：在文件头声明偏离项，指向对应 ADR。
4. **不得原地静默改写**基线文件。

**ADR 状态用词**：`提议（Proposed）` / `已采纳（Accepted）` / `已废弃（Deprecated）` / `被取代（Superseded by ADR-XXXX）`。

**取代规则**：ADR 一旦采纳不得原地修改；若要改变决策，新建 ADR 并标注被取代关系。

## 六、基线锚点

| 锚点 | 含义 |
| --- | --- |
| git tag `baseline-v0.5.0-sprint5` | Sprint 0–5 交付完成、基线文件建立时的代码快照 |

后续每个 Sprint 完成并通过验收后，追加新 tag，并在本表登记。

---

*关联文档：`docs/implementation/roadmap.md`（实施顺序）、`docs/implementation/acceptance-checklist.md`（验收基线）、`docs/architecture/target-architecture.md`（目标架构）、`docs/architecture/data-conventions.md`（数据规范）*
