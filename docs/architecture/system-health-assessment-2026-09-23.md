# 系统现状评估与专业建议（2026-09-23）

> **历史快照提示**：本文评估的是 `b4cda0e` 附近的 Sprint 5 状态。当前仓库已经增加培训权益与 Sprint 6 后端，提交数、模型数、路由数、迁移数和测试数均已变化；当前进度以 `docs/implementation/team-roles.md` 和 `acceptance-checklist.md` 为准。

评估对象：`D:\workstation\boyan教务`（职业培训教务系统）
评估视角：架构合理性 / 教务业务可落地性 / 用户体验可用性
评估方式：源码实测（代码度量、测试执行、类型检查、约束核查）+ 需求文档比对

---

## 一、结论摘要

**一句话结论**：领域建模与安全底座达到生产级水准，但**前端是空壳、模块边界已被迭代代号污染、数据范围权限只有表没有实现**——系统当前处于「后端能力过剩、产品不可交付」的失衡状态。

| 维度 | 评级 | 一句话判断 |
| --- | --- | --- |
| 领域建模 | A- | 70+ 模型，金额分、时长分钟、UTC、revision/冲正保留历史，规范执行到位 |
| 安全基线 | A- | Argon2、token 哈希、CSRF 双提交、AES-GCM + HMAC 盲索引、生产配置强校验 |
| 数据层与运维 | B+ | SQLite 生产约束齐全，备份/恢复/清理 CLI 与 systemd/Nginx 齐备 |
| 后端架构 | C | 190 路由压缩在 6 个巨型 router，无 service/schema 层，模块名是 `sprint1` |
| 权限模型 | D | `UserDataScope` 建表但**零引用**，需求中的班级/字段数据范围未实现 |
| 前端交付 | F | 全量 605 行，三大工作空间（学员360/报名工作空间/班级360）均未实现 |
| 工程质量 | D+ | 1 个 commit、21 个测试守护 190 路由、无 lint、无前端测试 |

---

## 二、系统画像（实测数据）

### 代码规模

| 部分 | 规模 | 说明 |
| --- | --- | --- |
| 后端 Python | ~8,900 行 | 6 个 router 文件承载全部业务 |
| 数据模型 | 70+ 个类 / 1,282 行 | 全部集中在 `backend/app/core/models.py` |
| API 路由 | 190 个 | exam 50 / finance 53 / teaching 27 / sprint1 35 / attachments 21 / iam 4 |
| 后端函数 | ~280 个 | 全部内联在 router，无 service 层 |
| 前端 Vue+TS | **605 行 / 21 文件** | 最大视图 142 行，8 个视图不足 25 行 |
| 测试 | 1,352 行 / **21 用例** | 全部通过（10.28s） |
| Alembic 迁移 | 9 个版本 | 覆盖 Sprint 0–5 |
| Git 提交 | **1 个** | Sprint 5 全部内容（21 个文件变更）未提交 |

### 后端模块实际结构

```
backend/app/
├── core/
│   ├── models.py      # 1,282 行，70+ 模型全在一个文件
│   ├── config.py      # 配置与生产强校验（质量高）
│   ├── db.py          # SQLite PRAGMA 与 Session（质量高）
│   ├── pii.py         # AES-GCM + HMAC 盲索引（质量高）
│   └── security.py    # Argon2 + HMAC digest（质量高）
└── modules/
    ├── sprint1/router.py       # 1,426 行 ← 迭代代号当模块名
    ├── exam/router.py          # 1,939 行 / 50 路由 / 69 函数
    ├── teaching/router.py      # 1,041 行
    ├── finance/router.py       # 873 行 / 53 路由 / 80 函数
    ├── attachments/router.py   # 673 行
    └── iam/router.py           # 170 行
```

**需求文档要求的结构是**：`modules/{iam, organization, students, catalog, enrollment, teaching, examination, finance, subsidy, documents, reporting, workflow, audit}`，且每个模块含 `models.py / schemas.py / service.py / repository.py / router.py / permissions.py`。

**实测结果**：`service.py`、`schemas.py`、`repository.py`、`permissions.py` **一个都不存在**。Pydantic 模型直接内联在 router 里（exam 9 个、sprint1 16 个、finance 11 个）。

### 前端实测

| 视图 | 行数 | API 调用数 | 状态 |
| --- | --- | --- | --- |
| `ExamView.vue` | 142 | 12 | 唯一有实质功能的页面 |
| `FinanceView.vue` | 52 | 8 | 半成品 |
| `HomeView.vue` | 51 | **0** | 硬编码静态壳，无待办/异常/指标 |
| `LoginView.vue` | 45 | 0 | 可用 |
| `StudentsView.vue` | 44 | 2 | 仅列表 + 新增 |
| `StudentDetailView.vue` | 33 | 15 | 整个模板压成 1 行 |
| `CertificatesView.vue` | 22 | 5 | 骨架 |
| `ClassesView.vue` | 17 | 7 | 骨架 |
| `CoursesView.vue` | 17 | 5 | 骨架 |
| `EnrollmentsView.vue` | 16 | 5 | 骨架 |
| `TeacherSettlementView.vue` | 15 | 4 | 骨架 |
| `TeachingView.vue` | 14 | 4 | 骨架 |
| `ImportsView.vue` | 12 | 1 | 骨架 |

路由中**没有 `ClassDetailView`（班级360）**，只有 `/classes/:id/teaching`。前端工程化配置（ESLint / Prettier / Vitest）**全部为空**。

---

## 三、值得保留的资产（先说做对的）

这些是真正有价值的工程成果，重构时必须保护，不能被推翻重来：

1. **金额与时长的建模纪律**。全库整数分（`_amount_cent` / `_price_cent`）、整数分钟，零 float 金额。这是资金类系统最常见的致命缺陷，这里守住了。
2. **历史不可覆盖的建模方式**。已确认事实通过 revision / 冲正 / 调整更正，而非覆盖。`ReceivableAdjustment`、`Payment` 冲正、`ExamResultRevision`、`AttendanceRevision`、`RefundCalculationSnapshot` 都体现这一原则。
3. **幂等设计落地到位**。所有资金与考试写入都有 `idempotency_key`，且都有真实唯一约束（`UniqueConstraint("idempotency_key")`），不是摆设。这条比多数同类系统做得好。
4. **敏感数据链路完整**。规范化 → HMAC-SHA-256 盲索引查重 → AES-GCM 加密明文 → 列表脱敏 → 明文查看独立 API。`pii.py` 的密钥长度、base64 校验、生产环境强制非空都实现了。
5. **生产配置守卫**。`config.py` 在 `APP_ENV=production` 下强制校验密钥长度 32+、`COOKIE_SECURE=true`、PII key 非空、必须为 SQLite——启动即失败优于运行期出事。
6. **SQLite 生产约束真正执行**。WAL / `foreign_keys=ON` / `busy_timeout=5000` / `synchronous=NORMAL` 通过 engine event 注入；`database is locked` 映射为 `503 DATABASE_BUSY` 而非无限重试。
7. **运维闭环**。备份/恢复/孤儿清理/暂存清理 CLI、healthcheck、systemd unit + timer、Nginx 配置、9 个 Alembic 迁移齐备。
8. **文档体系**。领域文档（考勤、退费、代缴、结算、证书）、API 文档、安全文档、导入模板文档、部署文档成体系，这在本规模项目里罕见。

---

## 四、关键问题（按优先级，附证据）

### P0-1 前端是空壳，系统实际不可交付

需求文档第 72–76 行明确定义三大产品支柱：**学员360**、**课程报名工作空间**、**班级360**，并强调三者不得复制同一套表单。实测：

- 「学员360」只有 33 行、模板压缩成单行的 `StudentDetailView.vue`，缺少要求的补贴/材料/收费/退款页签；
- 「班级360」**路由和组件都不存在**；
- 「课程报名工作空间」**不存在**；
- `HomeView.vue` 是硬编码的 `<h1>工作台</h1><p>...业务已接入。</p>`，没有待办、异常队列、角色差异——这是需求 Sprint 10 的核心内容，但连壳都没有。

**业务后果**：190 个后端 API，前端只消费了约 73 处调用。教务人员要做「给学员报名一次考试」「确认一次收款」「录入一次考勤」，大概率得打开 Swagger 手工填 UUID。**学员 ID 在 `FinanceView.vue` 里是手输文本框**（`<el-input v-model="studentId" placeholder="学员 ID"/>`），这在真实教务场景中不可用。

同时，9 个视图被压缩成单行超长模板（`StudentDetailView.vue` 第 30 行是一个 4000+ 字符的单行），**代码不可 review、不可维护、出现 UI 问题无法定位**。

### P0-2 模块边界被迭代代号污染，且缺失分层

`modules/sprint1/` 这个名字是**最需要立刻修的技术债**：它把「Sprint 1 交付的所有东西」——学员、证件、课程目录、课程版本、报名、班级成员经历——打包成一个模块。后果：

- 领域归属不明，新人无法从目录知道代码在哪；
- 后续 Sprint 6–8（退役士兵、政府申报、报表）会继续产生 `sprint6/`、`sprint7/`，代码库变成迭代日志而非领域地图；
- 所有业务规则内联在 router 函数中，**没有 service 层意味着核心规则无法单元测试**——现有 21 个测试全部是 HTTP 端到端，测不了边界分支。

这是 `sprint1/router.py` 1,426 行、`exam/router.py` 1,939 行、`finance/router.py` 873 行的根本原因。

### P0-3 权限模型只有存储结构，没有执行

`backend/app/core/models.py:88` 定义了 `UserDataScope`，全仓库**引用次数为 0**。

需求文档第 9 节明确要求：「校区、班级、项目或本人课次的数据范围」「列表查询必须在 SQL 层应用数据范围，禁止查出所有数据后只在前端隐藏」，以及具体规则「班主任只看授权班级」「教师默认不能看身份证明文和财务信息」。

**实测实际执行的范围过滤只有 `organization_id`**。而在单机构（单组织）场景下，`organization_id` 过滤**等价于没有过滤**——任何拥有 `student.read` 的用户都能查询全部学员。

附带一个直接暴露的安全缺口：`StudentDetailView.vue:10` 的 `finance` 与 `documents` 是**前端按权限判断后才发请求**（`if (can('receivable.read'))`），但后端 `/students/{id}/financial-overview`、`/students/{id}/documents` 只要权限码匹配就返回全量，没有班级/本人维度的行级过滤。

### P1-1 测试覆盖与风险严重不对称

21 个用例 / 1,352 行测试守护 190 个路由、70+ 模型、9 个迁移。分布更值得警惕：

| 模块 | 测试行数 | 风险等级 |
| --- | --- | --- |
| finance（收款/分配/冲正/代缴/退款/结算） | **123** | 最高 |
| exam（成绩/证书/导入） | 434 | 高 |
| teaching（考勤/课次） | 210 | 中 |
| attachments | 150 | 中 |
| baseline | 150 | 低 |

**最高风险的财务域测试最少**。而财务链路是全系统唯一「错了要赔钱」的地方：收款确认 → 分配 → 冲正 → 代缴 → 退费快照 → 退款付款 → 教师结算 → 付款。这些路径目前没有并发测试、没有幂等重放测试、没有金额守恒断言。

### P1-2 前端工程化基础设施缺失

- 无 ESLint / Prettier（前后端均无）→ 与后端 Ruff 的严格程度严重不对等；
- 无任何前端测试（Vitest / Playwright 都没有）；
- `api.ts` 仅 21 行，业务类型全靠手写 `Record<string, any>`（`FinanceView.vue` 9 处、`StudentDetailView.vue` 6 处）→ **类型安全形同虚设**，后端字段改名前端不会报错；
- 无统一数据获取层 → 每个视图自己 `onMounted(load)`，loading / error / 空态 / 重试各自为政，多数视图直接 `ElMessage.error(String(e))` 把异常对象字符串化丢给用户；
- 权限控制散落在每个组件的 `can()` 里，没有统一的路由级 + 按钮级方案。

### P1-3 仓库卫生与交付纪律

- **Git 只有 1 个 commit**，且 Sprint 5 的 21 个文件变更仍处于未提交状态。这意味着 Sprint 1–5 的全部演进**不可 review、不可二分定位、不可回滚**。这是当前最大的工程流程风险。
- 数据库物理文件 `backend/data/app.db`、`backend/data/sprint4_migration_gate.db` 位于项目树内，与 `docs/architecture/target-architecture.md` 第 5 行「SQLite 文件位于 ECS 本地持久数据盘」以及需求「禁止把数据库放在项目目录」的约定冲突。
- `backend/training_office.egg-info/`、`.pytest_cache/`、`.ruff_cache/` 等构建产物未从工作区清理。
- `.env.example` 与 `config.py` 默认值硬编码 Windows 盘符（`LOCAL_STORAGE_ROOT=D:/boyan-data/attachments`），生产 Linux 必须覆盖——默认值具有误导性。

### P2-1 少量约定偏离

- `finance/router.py:202,210` 用 `Literal` 硬编码了 `adjustment_type` 和 `payment_method`，而需求第 8 节要求「业务角色、课程、科目、政策和模板版本存配置或业务表，不写死在枚举中」。
- 需求定义的 `CourseEnrollment → ExamCase / TrainingOrder / Refund / Certificate / FundingCase` 聚合关系，实际是散装外键，没有聚合根承载「一条课程业务链」的语义——这会让 P0-1 的「课程报名工作空间」实现时缺乏后端支撑。
- `subsidy / reporting / workflow / organization` 模块未建（属 Sprint 6–8 范围，可接受）；OSS 后端未实现（代码已明确在 `get_settings()` 中 fail-fast，声明清晰，可接受）。

---

## 五、专业建议

### 阶段一：止损与纪律重建（预计 3–5 天）

| # | 动作 | 验收标准 |
| --- | --- | --- |
| 1 | **提交并打 tag**：把 Sprint 5 拆成 3–5 个语义化 commit（迁移/模型、API、前端、文档），打 `v0.5.0` tag | `git log` 可逐 Sprint 回溯；`git status` 干净 |
| 2 | **仓库清理**：`app.db` 移出项目树到 `../boyan-data/`，删除 egg-info 与各类 cache，`.gitignore` 补 `data/` | 项目树内无 `.db`、无构建产物 |
| 3 | **建立分支与提交规范**：`main` 保护，功能走 feature 分支；引入 commit 前钩子跑 Ruff + pytest | 无法向 main 直接提交不合规代码 |

### 阶段二：补权限与拆模块（预计 2–3 周，与阶段三并行）

**权限（P0-3，优先级最高）**
1. 实现 `UserDataScope` 的 SQL 层过滤：抽出统一依赖 `scoped_query(user, model)`，强制所有列表查询经过它，用测试断言「无范围用户查不到任何数据」。
2. 按需求补齐五类权限的实际执行：操作权限（已有）、**数据范围（缺）**、字段权限（缺）、附件权限（部分）、导出权限（缺）。
3. 落地具体规则并写测试：教师查不到财务字段、班主任只能看到授权班级的学员、明文查看需独立权限 + 理由 + 审计。
4. 把 `StudentDetailView` 的「前端判断是否请求」改为「后端按权限裁剪响应 + 前端仅做展示降级」——**权限必须在服务端裁决**。

**模块重构（P0-2）——渐进式，不要大爆炸重写**

推荐按「先立骨架，再搬逻辑」的顺序，每一步后端测试保持全绿：

```
第 1 步  modules/sprint1/  →  modules/students/  +  modules/catalog/  +  modules/enrollment/
         （纯目录与路由前缀搬迁，不改逻辑，测试全绿后提交）

第 2 步  为 finance 与 exam 各新建 service.py，把 router 里的业务函数搬进去：
         router 只保留「解析请求 → 调 service → 序列化响应」
         先搬资金链路（payment/refund/settlement），因为它风险最高、最需要单测

第 3 步  抽出 schemas.py（Pydantic 模型从 router 移出）与 permissions.py（权限依赖声明集中）
         抽出 repository.py 仅封装重复查询，不建第二套实体模型
```

**关键约束**：不要为了「结构好看」一次性重写。每步独立提交、独立验证，保持 21 个测试始终通过，并同步补充新的 service 层单测。

### 阶段三：前端交付（预计 4–6 周，这是能否上线的前提）

**先建地基，再做页面**（顺序不能反）：

1. **类型生成**：引入 `openapi-typescript`，从 FastAPI 的 `/openapi.json` 生成 `types/api.d.ts`，**禁止再手写 `Record<string, any>`**。这一步让前后端契约变成编译期检查。
2. **数据获取层**：引入 `@tanstack/vue-query`（或自研 `useApi` composable），统一 loading / error / 空态 / 重试 / 缓存失效。顺手解决现在每个视图自己 `onMounted` 的重复。
3. **工程化**：ESLint + Prettier + Vitest。加一条 CI 门禁：`typecheck && lint && test`。
4. **组件规范**：建立 `components/` 抽象（`StudentPicker` 代替手输学员 ID、`MoneyText` 统一分转元、`StatusTag` 统一状态色、`PermissionButton` 统一按钮级权限）。

**再按需求补齐三大工作空间**（严格避免需求禁止的「复制同一套表单」）：

| 优先级 | 交付物 | 要点 |
| --- | --- | --- |
| P0 | **学员360** | 抽成独立页面组件 + 8 个页签子组件；从班级名单进入时默认选中当前报名与当前班级经历；保留 `returnTo` 上下文（现已部分实现，需扩展筛选/排序/页码/页签） |
| P0 | **班级360** | 全新页面：学员名单、课次、教师、考勤、录屏、考试、资金摘要 |
| P0 | **课程报名工作空间** | 全新页面：承载「一条课程业务链」，是连接学员360 与班级360 的中间层；**需要先在后端补聚合查询 API**（见 P2-1） |
| P1 | **角色工作台** | 替换 `HomeView` 硬编码壳：待办、异常队列、按角色差异化的指标卡片 |
| P1 | 剩余骨架页 | Courses / Enrollments / Teaching / Certificates / TeacherSettlement / Imports 补全为可用页面 |

### 阶段四：风险加固（与阶段三并行）

1. **财务域测试加固（最高优先）**：为资金链路补齐
   - 全链路集成测试：应收 → 收款 → 分配 → 冲正 → 代缴 → 退费快照 → 退款付款 → 教师结算 → 付款；
   - **金额守恒断言**：每个状态变更后断言 `已收 = 已分配 + 未分配`、`应收 = 已分配 + 待收`、`应代缴 = 已代缴 + 未代缴`；
   - **并发与幂等重放**：同一 `idempotency_key` 并发提交只产生一条记录，重复提交返回同一结果；
   - 退费分钟快照与锁定考勤的一致性测试。
   - 目标：财务模块分支覆盖 ≥ 80%。
2. **可观测性**：`correlation_id` 已生成但未见结构化日志落地。补 JSON 日志（含 `correlation_id`、`user_id`、`action`）与慢查询/慢请求日志。
3. **审计完整性核对**：`AuditLog` 在 exam/finance 均有调用（质量不错），但需逐项核对需求列出的「敏感字段明文查看、附件下载、批量导出」是否都留痕，并补 `AuditLog` 的查询/导出接口（现在只写不读）。
4. **Nginx 层限流**：需求第 10 节要求对登录接口限流，需核对 `infra/nginx/boyan.conf` 是否已配置。

### 阶段五：推进「真实资料待确认」清单

`docs/implementation/roadmap.md` 第 24–33 行列出了 6 项阻塞项。其中**第 4 项（考试科目、收费标准、补考规则、证书流程）和第 5 项（校区、角色、数据范围矩阵）直接阻塞阶段二的权限与费用实现**，应优先推动业务方确认，否则权限规则无法落地、费用金额只能停留在测试数据。

---

## 六、建议的度量看板

上线前建议持续跟踪以下指标，作为「系统是否真的可用」的客观判据：

| 指标 | 当前值 | 目标值 |
| --- | --- | --- |
| 前端对后端 API 的覆盖率 | ~38%（73/190） | ≥ 90%（业务必需接口） |
| 后端 service 层覆盖率（代码行） | 0% | ≥ 60% |
| 财务模块测试分支覆盖 | 未测量（123 行测试） | ≥ 80% |
| 数据范围过滤覆盖率（受保护查询） | ~0%（仅 organization） | 100% |
| 前端 `any` 类型使用数 | 15+ 处 | 0 |
| 单个 router 文件最大行数 | 1,939 | ≤ 400 |
| `sprint*` 命名的模块目录数 | 1 | 0 |
| Git 提交粒度的可回溯性 | 1 commit | 每 Sprint 可独立回溯 |

---

## 七、一句话给决策者的建议

**不要现在加新功能。** 后端能力已经远超产品可用的程度，当前瓶颈 100% 在前端交付、权限执行和工程纪律三项。按「先止损（提交/清理）→ 再补权限（安全底线）→ 再拆模块（可维护性）→ 再建前端地基（类型+数据层+lint）→ 最后做三大工作空间」的顺序推进，是投入产出比最高的路径。反之，若继续按 Sprint 往 6/7/8 叠业务，代码库会迅速进入不可维护状态，且会带着「任何登录用户可查看全部学员及财务数据」这个安全缺口上线。

---

*评估依据：源码静态度量、`pytest` 实测（21 passed / 10.28s）、`vue-tsc --noEmit` 通过、约束与权限引用核查、与 `docs/requirements/` 需求文档逐条比对。*
