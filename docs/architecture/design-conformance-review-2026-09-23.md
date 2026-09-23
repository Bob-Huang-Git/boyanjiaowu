# 设计符合度比对报告（2026-09-23）

> **历史快照提示**：本文主体基于 Sprint 5 代码形成。培训权益和 Sprint 6 后端已在后续批次补齐；当前验收状态以 `docs/implementation/acceptance-checklist.md` 为准，本文保留用于追溯当时发现的问题。

比对基准：**《职业培训教务系统 Codex 提示词 V3.0》原始版**（用户提供，目标部署为「单台阿里云 ECS + Docker Compose」）
比对对象：`D:\workstation\boyan教务` 当前代码
方法：逐 Prompt 追溯（后端模型 / API / 页面 / 测试四维度）+ 源码 grep 验证
前序报告：`docs/architecture/system-health-assessment-2026-09-23.md`（本报告是对它的修订与深化）

---

## 一、结论摘要

**用设计规格当标尺，结论比上一版更严重：交付的 5 个 Sprint 中，每一个的「页面」和「测试」验收要求都被跳过了。**

设计第 0 节写明：「每个阶段测试、构建和**人工验收**通过后，再进入下一阶段」。实测结果是——后端领域模型做到了设计意图的约 65–70%（语义可映射），但：

- 设计的 11 个 Prompt 中，**P2/P3/P4/P5 的必做页面**几乎全部未交付（前端全量 605 行）；
- 设计明确列出的 **P1–P5 共约 49 个必测用例，实测 21 个**，且**全部并发类、滚班类、数据范围类用例为零**；
- 有 **2 处设计明确要求的功能在架构上缺失**（不是"没做完"，是"模型层面就没有位置"）。

**修订评级**：后端领域建模 A- 不变；但**工程交付纪律从 D+ 下调为 F**——因为问题不是"质量不够好"，而是"验收门槛未执行"。

---

## 二、发现一：需求基线已经漂移（必须先处理）

经与用户确认，当前存在**两项由用户主导的、有意的范围变更**（不是实现漏做）：

| # | 原始设计 | 当前决定 | 性质 |
| --- | --- | --- | --- |
| A | 目标部署：单台阿里云 ECS **+ Docker Compose** | 改为**原生部署**（Nginx + systemd + Uvicorn），不使用 Docker | 用户主导，已执行 |
| B | 附件存储：直接上**阿里云 OSS 私有 Bucket** | 改为**本地存储优先**，后续再迁 OSS，靠抽象层保证可替换 | 用户主导，已执行 |

### 事实

| 项 | 原始设计（用户提供） | 仓库实现 |
| --- | --- | --- |
| 目标部署 | ECS + Docker Compose | ECS 原生（`infra/nginx/boyan.conf` + 3 个 systemd unit） |
| 容器产物 | Dockerfile / compose | **无**（实测 0 个） |
| 「docker」在需求文档中出现次数 | 多处（Prompt 1 九、Prompt 11 二） | **0 次**（文档被原地改写） |
| 存储后端 | `AliyunOssStorage` | `LocalStorageBackend`，`STORAGE_BACKEND=oss` 时明确 fail-fast |

两项变更**执行都是干净的**：实测无任何容器产物残留；存储侧 `LocalStorageBackend` 零处被业务代码直接引用（详见发现七）。

### 影响

真正的问题不在变更本身，而在**记录方式**：设计文档是被**原地改写**的，而不是"保留原文 + 追加偏离说明"。导致：

1. **无法区分"用户授权的变更"和"实现漏做"**——例如 Docker 被删干净了，是授权的；但如果某天发现别的章节也被静默改过，评审时无据可查。
2. **原始设计丢失**。若无你手上这份 V3.0 原件，团队现在就没有比对基准了。
3. 后续还有其他待决策的偏离（OSS 何时切、是否保留本地为主副本、QUARANTINED 何时启用），没有流程承接。

### 建议

1. **恢复原始 V3.0 为权威基线**：存为 `docs/requirements/codex-prompts-v3.0-original.md`，**不得改写**。
2. 仓库内的改写版改名为 `...-adapted-native-deploy.md`，文件头显式列出全部偏离项。
3. 建立 `docs/architecture/adr/`，把这两项写成正式决策记录，后续所有偏离走同一流程：
   - **ADR-0001**：放弃 Docker，改 ECS 原生部署
   - **ADR-0002**：本地存储优先，OSS 后续迁移（含迁移就绪度评估，见发现七）
4. **同步把 roadmap 的 P9 行改成"存储抽象已就绪，等待 OSS 接入"**，避免它继续被读成"OSS 没做"。

---

## 三、发现二：11 个 Prompt 交付追溯矩阵

> 说明：Sprint 编号是仓库自定义的（`docs/implementation/roadmap.md`），与 Prompt 并非一一对应——仓库**插入了原设计没有的「Sprint 2 本地附件中心」**，并把 OSS 推后。插入本身合理（`StorageBackend` 抽象已留出 OSS 位置，`docs/architecture/future-oss.md` 有说明）。

| Prompt | 设计范围 | 仓库 Sprint | 后端 | 页面 | 测试 |
| --- | --- | --- | --- | --- | --- |
| P1 | 工程基线 / SQLite 骨架 | Sprint 0 | ✅ 完成 | ✅ 完成 | ✅ 达标（7/7） |
| P2 | 学员 / 课程版本 / 报名 / **双主线** | Sprint 1 | ⚠️ 基本完成 | ❌ **设计 7 项页面仅 1 项可用** | ⚠️ ~3/8 |
| — | 本地附件中心（**原设计无此阶段**） | Sprint 2 | ✅ 完成 | ⚠️ 仅有资料页签 | ✅ 3 个用例 |
| P3 | 班级 / 课次 / 多教师 / 考勤 / 录屏 | Sprint 3 | ✅ 完成 | ❌ **设计 6 项页面 0 项交付** | ⚠️ ~4/11 |
| P4 | 分科考试 / 补考费 / 证书 | Sprint 4 | ✅ 原报告 3 项缺口经业务方复核撤回，无已知缺口 | ❌ 仅学员侧摘要 | ⚠️ ~5/10 |
| P5 | 收费 / 代收代付 / 退费 / 结算 | Sprint 5 | ⚠️ 有 4 处缺口 | ❌ 仅半成品 1 页 | ⚠️ ~4/12 |
| P6 | 退役士兵 / 餐宿补贴 / 垫资 | Sprint 6 | 未开始 | — | — |
| P7 | 政府申报 / 核定 / 应收 / 到账 | Sprint 7 | 未开始 | — | — |
| P8 | 政府 Excel/Word 报表中心 | Sprint 8 | 未开始 | — | — |
| P9 | 阿里云 OSS 私有附件 | 提前到 Sprint 2，**改为本地优先** | ⚠️ 存储抽象已就绪、OSS 客户端未接入（用户决策） | — | ✅ 有 fail-fast 测试 |
| P10 | 角色工作台 / 异常队列 / 批量操作 | Sprint 10 | 未开始 | — | — |
| P11 | 单 ECS 部署 / 备份恢复 / 最终验收 | Sprint 11（部分前移） | ⚠️ 部分（备份/恢复/healthcheck 已有） | — | ✅ 有备份恢复用例 |

**注**：P9 的 OSS 在**原始设计里本来就在第 9 阶段**，所以"OSS 未接入"本身不算偏离。仓库提前把存储抽象做掉、先用本地落地，是**优于设计的工程改良**——但**抽象能不能真的承接 OSS，需要单独验证**，见发现七。

---

## 四、发现三：命名漂移（语义多数可映射，但需留档）

设计的模型名与实现名大面积不一致。大部分语义等价，但**有两处不是改名而是改语义**：

| 设计名 | 实现名 | 判定 |
| --- | --- | --- |
| `StudentIdentityDocument` | `StudentIdentityDocument` | ✅ 同名 |
| `ExamCase` | `ExamRegistration` + `ExamRegistrationSubject` | ⚠️ 拆成两层，可映射 |
| `ExamSubjectResult` | `ExamAttempt` | ⚠️ 改语义：设计是"结果"，实现是"尝试"，后者更贴合多次补考 |
| `ExamFeeObligation` | `ExamFeeAssessment` | ⚠️ 可映射，但**缺 `idempotency_key` 字段**（靠 `UniqueConstraint(exam_attempt_id, fee_type)` 兜底，效果等效） |
| `Certificate` / `CertificateDelivery` | `CertificateCase` / `CertificateDeliveryEvent` | ✅ 可映射；`UniqueConstraint(course_enrollment_id)` 经业务方确认为**正确设计**（一报名一证书） |
| `Charge` | `Receivable` | ✅ 可映射（`receivable_type` + `economic_nature` 区分资金性质） |
| `CreditAdjustment` | `ReceivableAdjustment` | ✅ 可映射 |
| **`TrainingOrder`** | **无** | ❌ **订单层被抹平**：`Receivable` 直接挂 `course_enrollment_id`，无"培训合同/订单"聚合根 |
| `ExamRemittanceBatch/Line/Refund` | `AgencyPayable` / `AgencyDisbursement` / `AgencyDisbursementAllocation` | ⚠️ 前两个可映射，**`ExamRemittanceRefund` 无对应**，见缺口 #2 |
| `TeacherSettlement/Line/Payment/Allocation` | `TeacherSettlementBatch/Line` + `TeacherPayment/Allocation` | ✅ 可映射 |
| **`TrainingEntitlement`** | **无** | ❌ **完全缺失**，见缺口 #1 |
| `AttendanceDayFact` / `LodgingStay` / `AllowancePolicy` / `SubsidyEntitlement` | 无 | ⏸ P6/P7 范围，未到阶段 |
| `WorkItem` / `ExceptionItem` / `ApprovalTask` / `BatchOperation` | 无 | ⏸ P10 范围，未到阶段 |
| `ReportTemplate` 等 | 无 | ⏸ P8 范围，未到阶段 |
| `ObjectStorage` Protocol/ABC | `StorageBackend` + `get_storage()` + `clean_filename/detect/extension` | ✅ 抽象已建，符合 P9 第一节 |

**建议**：把这张表放进 `docs/architecture/design-traceability.md` 并补充"为何改名"的一句话理由。现在没有任何地方记录这件事，未来接手的人会以为这是漏做。

---

## 五、发现四：真实功能缺口（已 grep 确认）

按严重程度排序。前两项是**架构性缺失**——不是待办，是当前模型里没有位置。

> **2026-09-23 业务方复核修订**：原报告的「缺口 #2 证书补发」与「缺口 #3 成绩有效期 / 必考选考」**经业务方确认不属于缺口，已撤回**（理由见本节末尾「已撤回项」）。本节缺口编号已重排。

### 缺口 #1 `TrainingEntitlement` 培训权益 —— 完全缺失 🔴

设计 P5 第四节明确要求实现"轻量 TrainingEntitlement 或等效记录"：购买/赠送分钟、已消耗分钟、免费滚班分钟、补差分钟、退费扣减依据；并规定"ClassMembership 的 `financial_treatment` 决定新班学习是否重复消耗或产生补差 Charge"。

**实测**：全仓库 `entitlement` 一词在 `models.py` 中出现 **0 次**。

**业务后果**（这是功能缺陷，不只是设计没对齐）：
- 滚班时无法回答"这次进班要不要再收钱"；
- 设计要求的测试用例「免费滚班不重复收费」「补差滚班只生成补差 Charge」**没有数据基础，不可能通过**；
- 退费的"已履约分钟扣减"缺一个与报名绑定的权益台账（现在只靠 `RefundCalculationSnapshot` 事后算，缺少事前口径）。

### 缺口 #2 已缴未考 / 机构退回学员 / 对账 —— 三项无法回答 🔴

设计 P5 第二节要求系统能回答四个问题。`GET /api/finance/exceptions`（`finance/router.py:873`）实际只返回 6 类异常：

| 设计问题 | 实现 | 判定 |
| --- | --- | --- |
| 已收未缴 | `agency_collections_without_payable`、`exam_assessments_not_handed_off` | ✅ 覆盖 |
| **已缴未考** | 无 | ❌ 缺失 |
| **考试机构已退但尚未退学员** | 无 | ❌ 缺失（`ExamRemittanceRefund` 无对应模型） |
| **已完成对账** | 无 | ❌ 缺失 |

**业务后果**：代收代缴是设计的核心业务之一（"代收、代缴首次考试报名费"）。现在只能看到"我收了钱但还没缴给机构"，看不到"钱缴了但学员没去考""机构把钱退给我了但我还没退学员"。**这三条恰恰是资金最容易被质疑的环节。**

### 缺口 #3 学员合并预留接口缺失 🟡

设计 P2 第一节第 6 条："建立学员合并预留模型或服务接口，但本阶段不实现复杂自动合并"。实测 `merge` 在 `app/modules/` 中出现 **0 次**。属"预留未做"，影响小，但设计明确列了。

### 缺口 #4 退费历史差额调整未验证 🟡

设计 P5 第五节："结算审批后冻结分钟和单价快照；后续修正生成下一期正负差额行，不能改历史结算"。测试 `test_teacher_settlement_uses_each_confirmed_assignment_once` 只验证了"同课次不重复结算"（`preview.items == []`），**未见差额调整路径的验证**。

### 已撤回项（业务方 2026-09-23 确认）

原报告曾把下面两项列为「架构性缺失」，经业务方复核后**撤回，不作为缺口处理**：

| 原编号 | 原报告结论 | 业务方结论 | 模型处置 |
| --- | --- | --- | --- |
| 原 #2 | 「证书补发在架构上不可能」——`UniqueConstraint("course_enrollment_id")` 阻止同一报名出现第二条证书记录 | **该约束是正确设计**：一个课程报名只应有一条证书记录 | **保留现有约束，不做迁移**（避免了一次非必要的破坏性变更） |
| 原 #3 | 「成绩有效期缺失 + 必考/选考无区分」 | **本系统不需要**成绩有效期，也**不需要**区分必考/选考 | **不新增字段**；`required_subject_count = len(subjects)` 的语义即「全部科目均为必考」，符合业务设定 |

**连带修正**：

- P4 的必测用例分母由 11 条调整为 **10 条**（删除「已通过科目先过期导致总体仍未通过」，该场景不适用）。
- 现 #2（代收代付对账）中的 **`ExamRemittanceRefund` 仍然有效**——它承载「机构已退钱给学校但学校尚未退学员」，与证书、成绩有效期无关，不受本次撤回影响。
- 重排后：**#1 培训权益**、**#2 代收代付对账**（两项 🔴）；**#3 学员合并预留**、**#4 退费差额调整验证**（两项 🟡）。

> ⚠️ **留档提醒**：撤回的这两项应同步回写到设计文档。当前原始设计 P4 第二节仍写着「成绩有效期」、第六节仍写着「补发关系」——若不同步修订，下一位评审者会再次把它读成缺口。

---

## 六、发现五：测试追溯 —— 这是本次比对最严重的发现

### 总量对比

| | 数量 |
| --- | --- |
| 设计 P1–P5 明确列出的必测用例 | **约 49 个** |
| 实际测试函数总数 | **21 个**（含 3 个附件 + 1 个备份，属插入阶段与 P11） |

### 逐个 Prompt 核对

**P1（7 项，全部覆盖 ✅）**
PRAGMA 生效、外键生效、登录/退出/会话撤销、CSRF 拒绝、权限拒绝、空库迁移、日志不含密码与 CSRF token —— 全部在 `test_baseline.py` 中落实（含 `assert "correct-password" not in caplog.text`）。**这一阶段做得扎实，是唯一完全达标的阶段。**

**P2（8 项，约 3 项覆盖 ⚠️）**

| 设计要求 | 实测 |
| --- | --- |
| 同一证件**并发**创建只产生一个学员 | ❌ 无并发测试 |
| 一人报名两门课程 | ✅ |
| 同一课程重新报名与滚班的区别 | ❌ |
| 已发布课程版本不可修改 | ⚠️ 未见显式断言 |
| 学员敏感字段加密和脱敏 | ✅ |
| 无权用户无法看明文 | ✅ |
| **从班级进学员再返回时上下文不丢失** | ❌ 无前端测试（前端无任何测试） |
| migration 升级与回滚边界说明 | ⚠️ 升级有，回滚说明未见 |

**P3（11 项，约 4 项覆盖 ⚠️）**

| 设计要求 | 实测 |
| --- | --- |
| 一班多老师 / 同课次多老师 | ✅ |
| 未确认教师分钟不进入结算统计 | ❌ 测试中教师安排全部是 `CONFIRMED` |
| 考勤唯一性 | ❌ |
| 批量考勤**部分失败** | ⚠️ 只测了单条 `SUCCESS` |
| 已锁定考勤不能覆盖 / 更正保留原值 | ⚠️ 测了"锁定后仍可 revise"，未断言原值保留 |
| **重复滚班幂等** | ❌ 滚班端点存在（`teaching/router.py:855`）但**零测试** |
| **两次并发滚班只有一条有效链** | ❌ |
| 外部录屏危险 URL 被拒绝 | ✅（http → 422） |
| **教师只能访问本人相关课次** | ❌ 数据范围未实现，不可能通过 |

**P4（10 项，约 5 项覆盖 ⚠️）**

已覆盖：两科首考、一过一挂（`PARTIALLY_PASSED`）、只为未通过科目产生补考费、成绩更正保留历史（`test_confirmed_result_requires_revision`）、未全部通过不能申请证书。

缺失：**缺考**（代码有 `ABSENT`，测试未见）、**滚班后继续补考**、**同一报名单证书唯一性**（约束已建且确认为正确设计，但无显式测试）、重复请求不重复生成费用（有唯一约束但无显式幂等重放测试）。

**P5（12 项，约 4 项覆盖 ⚠️）**

已覆盖：部分付款（`PARTIALLY_PAID`）、分配不得超过付款（409）、同一教师课次不能重复结算、汇总金额一致性（部分）。

缺失：**两个并发退款只有一笔成功占用余额**、已代缴考试费不可退、**考试机构退回后可退学员**（无功能）、补考费重复点击、**免费滚班不重复收费**（无权益模型）、**补差滚班只生成补差 Charge**、历史结算只生成差额调整、**所有总金额等于明细行合计**（无系统性守恒断言）。

### 三个结论

1. **并发测试几乎为零。** 全仓库只有 `test_baseline.py` 里 1 个针对 SQLite 写锁的线程测试。而设计在 P2、P3、P5、P7 **四处**明确要求并发验证，其中 P3 的"两次并发滚班"和 P5 的"两个并发退款"直接关系资金与学籍正确性。
2. **所有"数据范围"类测试不可能通过。** 因为 `UserDataScope` 零引用（见前序报告 P0-3）。"教师只能访问本人课次""班主任只看授权班级"在设计里各有一处测试要求，现在不是"测试没写"，是"功能没实现"。
3. **前端测试完全为零。** 设计 P2 的「上下文不丢失」、P10 的「返回列表保留上下文」都是页面级验收要求，而前端没有 Vitest / Playwright，也没有任何测试脚本。

**建议**：把设计里这 49 条必测用例**原样录成一个清单文件**（`docs/implementation/acceptance-checklist.md`），逐条标注 现状/责任人/目标 Sprint。这是现成的、免费的、需求方已经签字认可的验收标准——比重新设计一套测试策略划算得多。

---

## 七、发现六：前端页面验收被系统性架空

设计几乎每个 Prompt 都有独立的"页面"小节。逐条对照：

| Prompt | 设计要求的页面 | 仓库实际 |
| --- | --- | --- |
| P2 | ① 学员列表 ② 学员360基础页 ③ **课程报名工作空间** ④ 班级列表 ⑤ **班级360基础页** ⑥ 从班级名单进学员360并默认选中当前报名 ⑦ 返回时恢复筛选/排序/页码/页签 | ① ⚠️ 44 行 ② ⚠️ 33 行（模板压缩成单行）③ ❌ **不存在** ④ ⚠️ 17 行 ⑤ ❌ **不存在** ⑥ ❌ ⑦ ⚠️ 仅 `returnTo` + `tab`，缺筛选/排序/页码 |
| P3 | ① 班级360教学计划 ② 课次日历 ③ **批量考勤表** ④ 教师与课时 ⑤ 录屏列表 ⑥ **教师移动端今日课次与点名** | 全部 ❌；`TeachingView.vue` 仅 14 行 |
| P4 | 学员360与班级360均可看考试摘要并下钻全部历史 | 学员侧 ⚠️ 有；班级侧 ❌ 无 |
| P5 | （无独立页面小节，但"财务数据只对授权角色可见"需页面配合） | ⚠️ `FinanceView.vue` 52 行半成品 |

**合计：P2–P4 设计明确要求约 14 项页面，实际可用 1–2 项。**

对比一个刺眼的事实：设计 P3 第六节写"**一个 50 人班必须可以一次批量提交考勤，并返回逐行成功、失败和跳过原因**"——后端 `batch-draft` 端点确实实现了（`teaching/router.py:609`），但**没有对应的页面**。也就是说：**这个能力教务人员用不到**。

---

## 八、发现七：本地优先 → OSS 的迁移就绪度评估

既然 OSS 是"后续再接"，那本次比对该变更的**核心问题就不是"OSS 做了没"，而是"抽象立得对不对、OSS 能不能接得进来"**。逐项验证结论如下。

### 已经做对的部分（比设计更好，应保留）

| # | 事实 | 为何重要 |
| --- | --- | --- |
| 1 | `StorageBackend(ABC)` 定义了 `put_stream / open_stream / stat / exists / delete / health_check`（`attachments/storage.py:34-57`） | 接口面完整，覆盖服务端全部存储操作 |
| 2 | **业务代码零处直接引用 `LocalStorageBackend`**——实测全仓库仅出现在 `storage.py` 自身（类定义 + 工厂返回）。所有模块统一走 `get_storage()` | **抽象没有泄漏**。换后端只需改 `get_storage()` 一个函数 |
| 3 | `StorageStat` 已预留 `etag` 和 `version_id` 字段 | 这两个是 OSS 才有、本地为 `None` 的字段，说明抽象在设计时就考虑了 OSS |
| 4 | `create_download_reference(object_key)` 是**非抽象**的默认实现（本地返回 key 本身），OSS 可覆盖为预签名 URL | 现成的下载扩展点，不需要改调用方 |
| 5 | **`FileReplica` 用 `is_primary` + 部分唯一索引**（`models.py:402-407`）：`Index(unique=True, sqlite_where=text("is_primary = 1 AND deleted_at IS NULL"))` | **这是本次评估最亮的设计**。它天然支持「本地为主副本 → 复制到 OSS → 校验 → 提升 OSS 为主副本 → 本地降级为副副本」的完整迁移路径，且保证任一时刻只有唯一主副本。设计文档只规划了单一 `FileObject`，实现者做了更好的规范化 |
| 6 | `FileReplica` 具备 `replica_status`（含 `COPYING`）、`sha256`、`provider_etag`、`provider_version_id`、`verified_at`、`last_checked_at`、`failure_code`、`failure_message_sanitized` | 逐副本校验、失败留痕、观察期检查全部就位——正好对应 roadmap 里 Sprint 9 写的"复制校验、主副本提升与观察期" |
| 7 | `QUARANTINED` 状态已预留（`attachments/router.py` 有引用） | 设计 P9 五要求"架构保留 QUARANTINED 状态"，已完成 |
| 8 | `cleanup-staged` / `cleanup-orphans` 两个 CLI 已实现（`cli/files.py:58,75`） | 设计 P9 五要求"pending 孤儿对象由 Cron 清理命令处理"，已完成 |
| 9 | 对象键校验拒绝 `..`、绝对路径、`\`、`:`、`\x00`；`put_stream` 用 tmp + `fsync` + `os.replace` 原子落盘并计算 SHA-256；`_path()` 追加 `relative_to(root)` 二次校验 | 路径穿越做了纵深防御，落盘原子性正确——**这是本地实现最容易做错的地方，这里做对了** |
| 10 | 路径语义已是 provider-neutral（`PurePosixPath`，`object_key` 无盘符） | 迁移时不需要做 key 格式转换 |
| 11 | 附件用 `StudentDocument` / `ExamDomainAttachment` / `FinanceAttachment` 等**明确外键**绑定，未使用无约束的 GenericForeignKey | 设计 P9 二明确要求，已完成 |

### OSS 接进来时真正要补的（关键风险）

**唯一但重大的缺口：上传协议层是空白。**

现状是**浏览器 → FormData → FastAPI `UploadFile` → `LocalStorageBackend`**。而设计 P9 第四节和第七节明确要求：

```
前端请求 prepare-upload → 后端校验 → 返回短时 V4 预签名 URL
→ 浏览器直传 OSS（不经过 FastAPI）→ complete-upload → HeadObject 校验
```

实测：`prepare-upload` / `complete-upload` / `presign` / `upload_id` 在 `attachments/router.py` 中**零命中**。ABC 里也**没有 `create_upload_reference()`**（只有 `create_download_reference()`），更没有分片上传（`upload_id` + part）的概念。

**这意味着 OSS 接入不是"写一个 `AliyunOssStorage` 类"就完事。** 真实工作量集中在：

1. 在 `StorageBackend` 上新增 **`create_upload_reference()`**（本地实现返回 None / 走服务端中转，OSS 实现返回预签名 PUT URL）；
2. 新增两个 API：`POST /api/files/prepare-upload`、`POST /api/files/complete-upload`（后者需幂等 + `HeadObject` 校验存在/大小/Content-Type）；
3. **改造前端上传路径**——从"提交 FormData 给 FastAPI"改为"先取签名、再直接 PUT 到 OSS"。设计明确要求"OSS 大文件由浏览器直传，不经过 FastAPI"，录屏尤其如此；
4. 若要支持大录屏，需引入**分片上传**：后端控制 `upload_id` 与 `object_key`，前端只上传授权的 part，完成请求幂等，并提供清理未完成分片的 CLI。

> **结论**：持久层（模型 + 抽象）已经为 OSS 准备好，且质量高于设计。**上传协议层需要一次独立的小型设计**，不要按"换个实现类"来估工。建议在 P9 正式启动前单独写一份 ADR-0003《上传协议：服务端中转 vs 浏览器直传》。

### 其他次要差异

| 项 | 设计 | 实现 | 影响 |
| --- | --- | --- | --- |
| 测试替身 | 要求 `LocalFakeStorage`（测试用假实现）+ `AliyunOssStorage`（生产） | 无 Fake，测试直接 `monkeypatch` 真实 `LocalStorageBackend` 打 tmp 目录 | 低。但**测试永远不会覆盖"OSS 客户端抛异常"的路径**，接入时需补 |
| `bucket` 列 | 要求 `FileObject` 保存 `bucket` | 无 `bucket` 列（有 `metadata_json` 可放） | 低。接入时加列或走 metadata |
| 状态命名 | `PENDING / ACTIVE / QUARANTINED / ARCHIVED / DELETED` | `STAGED`（对应 PENDING）、`ACTIVE`、`QUARANTINED`；副本侧另有 `VERIFIED` / `MISSING` | 低。语义齐备，命名不同需留档 |

---

## 九、修订后的结论

### 评级调整

| 维度 | 前序报告 | 本报告修订后 | 调整理由 |
| --- | --- | --- | --- |
| 领域建模 | A- | **B+** | 语义覆盖约 65–70%；架构性缺失由 4 处收窄为 **2 处**（培训权益台账、代收代付对账），另 `TrainingOrder` 订单层被抹平 |
| 安全基线 | A- | A- | 不变 |
| 数据层与运维 | B+ | B+ | 不变 |
| **存储抽象与 OSS 迁移就绪度** | 未评估 | **A-** | `StorageBackend` 零泄漏、`FileReplica` 的 `is_primary` 部分唯一索引比设计更好；扣分仅在**上传协议层空白** |
| 后端架构分层 | C | C | 不变 |
| 权限与数据范围 | D | D | 不变 |
| 前端交付 | F | F | 不变 |
| **工程交付纪律** | D+ | **F** | 5 个 Sprint 的页面与测试验收要求被系统性跳过 |

### 一句话

> 后端把"模型建对了"，前端和测试没跟上；而设计的验收机制没有拦住这个过程。**现在最该做的不是继续建 P6/P7，而是回头把 P2–P5 的验收把住。**

补充一句关于本次澄清的变更：**"本地优先、后续接 OSS"这个决定是对的，而且执行得比设计更好**——`FileReplica` 的多副本 + 主副本模型天生支持平滑迁移。唯一要留意的是：**别把 OSS 接入估成"换个实现类"**，真正的活在浏览器直传协议和分片上传上。

### 建议的优先级顺序（在上一版基础上修订）

**第 0 步（先做，1 天）**
1. 恢复原始 V3.0 为权威基线；仓库改写版改名并在文件头声明偏离项。
2. 补两条 ADR：**ADR-0001 放弃 Docker 改原生部署**、**ADR-0002 本地存储优先 / OSS 后续迁移**（后者直接引用本报告第八节作为就绪度评估）。
3. 修正 `docs/implementation/roadmap.md` 的 P9 行：从"OSS 后端未实现"改为"存储抽象已就绪，待接入 OSS 客户端 + 上传协议"，避免被误读为漏做。
4. 把设计里 49 条必测用例录成 `docs/implementation/acceptance-checklist.md`。
5. 在 P9 正式启动前，先写 **ADR-0003《上传协议：服务端中转 vs 浏览器直传》**，把第八节列出的 4 项工作量（`create_upload_reference`、prepare/complete-upload、前端直传改造、分片上传）确认成设计。

**第 1 步（工程纪律，3–5 天）**
6. 提交 Sprint 5（21 个文件）并打 tag；清理仓库内 `.db` 与构建产物；建立提交前钩子。

**第 2 步（架构性缺口，必须先于新功能）**
7. **补 `TrainingEntitlement`**（缺口 #1）——它阻塞滚班收费逻辑与 2 条必测用例。
8. **补 `ExamRemittanceRefund` + 三类对账查询**（缺口 #2）。

**第 3 步（权限，2 周）**
11. 实现 `UserDataScope` 的 SQL 层过滤——这是解锁 4 条必测用例的前提。

**第 4 步（测试补齐，与第 3 步并行）**
12. 按 49 条清单补齐，**优先补 4 类并发测试 + 滚班幂等**。

**第 5 步（前端，4–6 周）**
13. 按第七节页面表补齐 P2–P4 的 14 项页面，先上类型生成 + 数据层 + lint/test 地基。

**第 6 步**
14. 之后才进入 P6（退役士兵）。

---

*比对依据：原始设计 V3.0 全文逐节核对；源码 grep 验证（模型存在性、字段存在性、端点存在性、测试断言）；`pytest` 实测 21 passed；`vue-tsc --noEmit` 通过。凡标注 "❌ 缺失" 者均有 grep 零命中或字段缺失证据；凡标注 "⚠️ 未见" 者表示脚本级未见覆盖，可能存在被测函数内部覆盖，需人工复核。*
