# 职业培训教务系统 Codex 提示词

> ## ⚠️ 本文是**派生工作副本**，不是原始设计
>
> - **权威基线**：`docs/architecture/baseline.md`
> - **原始设计**：《职业培训教务系统 Codex 提示词 V3.0》（项目负责人持有）。**本仓库尚未落盘**，原因与要求见 baseline.md 第四节。
> - **本文已含的偏离**（均为项目负责人决策，**不是实现漏做**）：
>   1. **部署**：原文「单台阿里云 ECS + **Docker Compose**」→ 本文已改写为「ECS 原生部署（Nginx + systemd + Uvicorn 单 worker）」。见 [ADR-0001](../architecture/adr/ADR-0001-native-deploy-instead-of-docker.md)。
>   2. **附件存储**：原文「第一期即接入阿里云 OSS」→ 已调整为「**本地优先、OSS 后续接入**」。见 [ADR-0002](../architecture/adr/ADR-0002-local-storage-first-oss-later.md)。
> - **业务口径澄清**（非偏离）：一个课程报名只允许一条证书记录；本系统不需要成绩有效期，也不需要区分必考／选考。见 baseline.md 第二节。
> - **维护规则**：本文可修订，但每次修订必须登记到 `baseline.md` 第二节；**严禁静默改写**。
> - **评审提示**：直接拿本文做验收，会**自动放过全部部署与存储相关偏离**（本文已不含 「docker」任何字样）。评审请以 `baseline.md` + `docs/implementation/acceptance-checklist.md` 为准。

版本：V3.0 FastAPI + SQLite 轻量实施版
适用规模：单机构、学员少于 1000 人、低并发写入
目标部署：单台阿里云 ECS 原生部署（Nginx + systemd + Uvicorn）
附件存储：阿里云 OSS 私有 Bucket

---

## 0. 使用方法

本文件包含一份“项目总提示词”和 11 份“分阶段执行提示词”。

推荐用法：

1. 第一次把“项目总提示词”交给 Codex，让它检查仓库并输出架构与实施计划，不要让它一次性生成所有业务代码。
2. 确认 Codex 的检查结果后，从 Prompt 1 开始依次执行。
3. 每次只执行一份 Prompt。
4. 每个阶段测试、构建和人工验收通过后，再进入下一阶段。
5. 若仓库已有代码，以仓库实际情况为准，但不得擅自更换本文件锁定的核心技术栈。

---

## 1. 项目总提示词

```text
你是一名资深职业培训教务系统产品专家、FastAPI工程师、SQLAlchemy数据建模专家、Vue 3工程师和阿里云部署工程师。

请基于当前仓库，规划并逐步实现一个职业培训教务系统。当前规模小于1000名学员，单机构、低并发，因此必须坚持轻量设计，不得过度架构。

一、业务背景

机构从事职业教育培训，目前课程包括：
- 人工智能训练师；
- 全媒体运营；
- 后续会持续增加课程。

同一个自然人只能有一个学员主档，但可以报名多门课程。同一个课程报名可以经历首学班、滚班、复学或转班。

机构业务包括：
1. 收取培训费；
2. 代收、代缴首次考试报名费；
3. 协助学员报名考试；
4. 考试按科目管理，目前常见为两科；
5. 学员可能一次通过两科，也可能一科通过、一科失败；
6. 补考按每次、每科管理，补考费用由学员承担，学校代收和代缴；
7. 已通过科目不得被后续失败结果覆盖；
8. 未全部通过的学员可滚入下一个班继续学习；
9. 全部必考科目通过后，学校协助申领、保管和代发证书；
10. 退费按照合同规则和已经履约的课时进行扣减；
11. 一个班可以有多名老师，不同课次可以由不同老师授课，同一课次也可以有主讲、助教或联合授课；
12. 系统需要统计老师实际授课分钟、可结算分钟、课时费和付款情况；
13. 每个课次可以保存上课录屏地址或OSS对象；
14. 学员附件包括身份证、退役证、合同、证书、照片、扫描件和其他材料。

退役士兵业务：
1. 退役身份属于学员级相对稳定信息；
2. 政府项目资格属于“学员某次课程报名”；
3. 学校先垫付教师课时费；
4. 学员满足政策条件后，人社或退役军人管理部门向学校支付补贴；
5. 学校培训期间可能向学员支付餐补和住宿补贴；
6. 餐补根据每日出勤事实计算，同一天多个课次不能重复产生按日餐补；
7. 住宿补贴必须有独立住宿事实，不能只根据考勤推断；
8. 上海不同区、不同部门、不同年度的政策和报表模板可能不同；
9. 系统必须保留申报、退回、修订、核定、政府应收、分次到账和核销全过程；
10. 学校成本、学员补贴权益、政府申报金额、政府核定金额和实际到账金额不能混为一个字段。

二、产品主线

系统采用一个数据底座、三个对象工作空间：

1. 学员360：查看自然人的全部课程、班级经历、考勤、考试、证书、收费、退款、补贴和材料；
2. 课程报名工作空间：查看某学员某门课程的一条完整业务链；
3. 班级360：管理某次开班的学员、课次、老师、考勤、录屏、考试、补贴和报表。

从班级学员名单点击学员后，进入同一个学员360页面，默认选中当前课程报名和当前班级经历。不要开发另一套重复的“班级学员详情页”。

路由需要保留：
- classId；
- enrollmentId；
- 来源视图；
- 筛选条件；
- 排序；
- 页码；
- 当前页签。

任意返回地址只能使用站内命名路由或白名单路径，禁止开放跳转。

三、固定技术栈

必须使用：
- Python 3.12；
- FastAPI；
- SQLAlchemy 2.x同步Session；
- Pydantic v2；
- SQLite；
- Alembic，使用SQLite batch migration；
- Vue 3；
- TypeScript；
- Vite；
- Element Plus；
- Pinia；
- pytest；
- Ruff；
- openpyxl；
- docxtpl和python-docx；
- 阿里云官方Python OSS SDK，并封装为独立适配器。

第一期禁止引入：
- PostgreSQL；
- MySQL；
- Redis；
- Celery；
- RabbitMQ；
- Kafka；
- 微服务；
- Kubernetes；
- Elasticsearch；
- 第二套ORM；
- 第二套数据库迁移工具。

不要因为“以后可能扩容”提前增加这些组件。代码应保持未来可迁移到PostgreSQL，但第一期只实现SQLite。

四、SQLite生产约束

启动时必须确保：

PRAGMA journal_mode = WAL;
PRAGMA foreign_keys = ON;
PRAGMA busy_timeout = 5000;
PRAGMA synchronous = NORMAL;

其他要求：
1. 第一阶段只运行一个Uvicorn Worker；
2. SQLite文件保存在ECS本地数据云盘挂载目录，例如/data/app.db；
3. 禁止把数据库放在OSS、NAS、NFS或网络共享目录；
4. 写事务保持短小；
5. 生成Excel、调用OSS、压缩材料包等慢操作不得占用数据库写事务；
6. 所有外键和关键唯一约束必须真实建立；
7. 所有列表和关联字段建立必要索引；
8. CI必须使用SQLite并验证WAL、外键、迁移和并发行为；
9. 不允许通过删除数据库文件解决migration问题。

五、金额、课时和日期规范

1. 所有人民币金额在数据库中保存为整数“分”，字段后缀统一为_amount_cent或_price_cent；
2. 禁止使用float保存或计算金额；
3. API可以接收和展示元，但进入领域服务前必须明确转换为分；
4. 课次时长、出勤时长和教师结算时长统一保存为整数分钟；
5. 课时换算只在展示或规则计算时进行，并保存换算规则版本；
6. 业务时区为Asia/Shanghai；
7. 数据库存储UTC时间，API和页面按上海时区展示；
8. 政策归属日期、上课日期和住宿夜日期使用明确的date字段，不从UTC时间临时猜测。

六、建议的模块化单体结构

backend/
├── pyproject.toml
├── alembic.ini
├── alembic/
├── app/
│   ├── main.py
│   ├── core/              # 配置、数据库、安全、日志、错误码
│   ├── modules/
│   │   ├── iam/           # 用户、角色、权限、会话、数据范围
│   │   ├── organization/  # 机构、校区、部门
│   │   ├── students/      # 学员、证件、退役身份
│   │   ├── catalog/       # 课程目录、版本、科目和规则
│   │   ├── enrollment/    # 课程报名和班级经历
│   │   ├── teaching/      # 班级、课次、教师、考勤和录屏
│   │   ├── examination/   # 考试、补考、成绩和证书
│   │   ├── finance/       # 收款、代收代付、退费和教师结算
│   │   ├── subsidy/       # 退役士兵补贴和政府申报
│   │   ├── documents/     # OSS对象和附件绑定
│   │   ├── reporting/     # 报表数据集、适配器和快照
│   │   ├── workflow/      # 待办、异常、审批和任务记录
│   │   └── audit/         # 操作审计和业务事件
│   └── cli/               # 备份、清理和运维命令
├── tests/
├── frontend/
├── infra/
└── docs/

每个业务模块可以包含：
- models.py；
- schemas.py；
- service.py；
- repository.py；
- router.py；
- permissions.py；
- tests/。

不要为了形式主义再建立脱离SQLAlchemy模型的第二套实体和复杂Repository层。Service负责业务事务，Repository仅封装重复查询。

七、核心领域关系

必须保持：

Student
→ CourseEnrollment
→ ClassMembership
→ ClassSession / Attendance

CourseEnrollment还关联：
- ExamCase；
- TrainingOrder；
- Refund；
- Certificate；
- FundingCase。

关键说明：
1. Student代表自然人唯一主档；
2. CourseCatalog代表稳定课程目录；
3. CourseOfferingVersion代表可报名的课程版本；
4. 同一学员可以报名多个不同课程；
5. 同一课程未来允许重新报名，但不能把滚班误建为新报名；
6. ClassMembership表示报名进入班级的一段经历；
7. 滚班是在一个事务内结束旧班级经历并新建下一段经历；
8. ClassSession表示实际课次；
9. SessionTeacherAssignment表示一个课次中的一名老师；
10. Attendance表示一名班级成员在一个课次中的考勤。

八、历史数据规则

以下数据确认后禁止直接覆盖或删除：
- 已确认考勤；
- 官方考试结果；
- 收款和收款分配；
- 已审批退款；
- 考试机构代缴；
- 已确认教师课时；
- 已审批教师结算；
- 补贴权益和政府申报；
- 正式报表快照。

更正方式必须是：
- 撤销；
- 冲正；
- 调整记录；
- 新revision。

草稿和未被引用的数据可以删除；主数据使用停用状态。不要给所有表机械增加通用软删除。

九、轻量权限设计

系统只做单机构，但保留organization_id作为未来扩展边界，默认只有一个机构。

权限分为：
1. 操作权限；
2. 校区、班级、项目或本人课次的数据范围；
3. 字段权限；
4. 附件权限；
5. 导出权限。

建议角色：
- 系统管理员；
- 招生/学员管理员；
- 教务；
- 班主任；
- 教师；
- 考务；
- 财务；
- 退役士兵项目专员；
- 报表专员；
- 审批人；
- 审计只读。

列表查询必须在SQL层应用数据范围，禁止查出所有数据后只在前端隐藏。

十、认证方式

这是内部管理系统，前后端同域部署。使用服务端Session：
1. 登录成功生成高强度随机session token；
2. 数据库只保存token哈希、用户、有效期、撤销状态、IP和User-Agent摘要；
3. 浏览器Cookie使用HttpOnly、Secure、SameSite=Lax；
4. 状态修改请求需要CSRF保护；
5. 退出登录立即撤销session；
6. 密码使用Argon2；
7. 不把长期JWT存入localStorage；
8. Nginx对登录接口限流；
9. 敏感字段明文查看、附件下载和批量导出需要独立权限与审计。

十一、学员敏感信息

身份证、退役证号和手机号：
1. 标准化后使用带密钥HMAC-SHA-256生成查重索引；
2. 明文使用cryptography库AES-GCM加密；
3. 密钥来自环境变量或阿里云KMS，不写入仓库；
4. 保存key_version，支持未来轮换；
5. 列表默认脱敏；
6. 明文查看使用独立API，要求填写理由并记录审计；
7. 日志、错误、测试数据和OSS Object Key不得包含真实明文。

十二、轻量任务策略

一期不使用Celery和Redis。

1. 预计10秒内完成的报表和导入可以同步执行；
2. OSS大文件由浏览器直传，不经过FastAPI；
3. 数据库备份、孤儿附件清理和过期session清理由Linux Cron调用CLI命令；
4. FastAPI BackgroundTasks不得承载收费、退款、代缴、结算、补贴、申报等关键业务状态；
5. 如果未来某任务确实超过同步上限，先建立数据库JobRecord和单进程轻量worker，再单独评审；当前阶段不要实现Celery。

十三、OSS设计

第一期使用一个私有Bucket，通过前缀隔离：
- documents/；
- recordings/；
- reports/；
- backups/；
- pending/。

Object Key只使用organizationId、业务对象ID、文件类型和UUID，不包含姓名、身份证号、手机号或原始文件名。

上传流程：
1. 前端请求prepare-upload；
2. 后端校验操作权限、对象数据范围、文件类型、大小和业务归属；
3. 后端生成pending前缀下的短时V4预签名URL；
4. 浏览器直传OSS；
5. 前端调用complete-upload；
6. 后端HeadObject校验存在、大小、Content-Type和OSS校验信息；
7. 校验通过后创建FileObject和明确的业务绑定；
8. 下载时重新鉴权并生成短时URL；
9. 数据库不保存永久公网URL和预签名URL；
10. 录屏可以保存OSS对象，也可以保存经过协议和域名校验的外部HTTPS地址。

第一期只允许业务需要的扩展名和大小。不要执行用户上传的代码、宏、公式或任意模板表达式。

十四、报表策略

一期不要开发复杂低代码报表平台。

采用：
业务事实
→ 版本化政策计算
→ 标准报表数据集
→ 版本化Python模板适配器
→ Excel/Word文件

要求：
1. openpyxl填充真实Excel模板；
2. docxtpl生成Word；
3. 每个区、部门、年度模板有版本；
4. 复杂模板使用明确的Python适配器类；
5. 适配器只负责渲染，不能包含资格和金额计算；
6. 禁止从数据库执行任意Python、SQL、eval或不受控Jinja表达式；
7. 正式提交保存标准数据JSON快照、规则版本、模板版本、文件SHA-256、源记录ID和操作者；
8. 退回后创建新revision，旧文件和旧快照不可覆盖；
9. 使用真实模板建立黄金文件测试。

十五、SQLite备份

禁止在运行时直接复制.db文件。

实现CLI备份命令：
1. 使用Python sqlite3 backup API或VACUUM INTO创建一致性备份；
2. 对备份文件计算SHA-256；
3. 可配置上传到OSS backups前缀；
4. 保存备份清单、文件大小、哈希、创建时间和程序版本；
5. 支持本地恢复验证命令；
6. 每日备份，关键导入、正式报表提交和版本升级前额外备份；
7. 提供30天保留建议，但不要在代码中未经配置自动永久删除。

十六、工程执行方式

开始前必须：
1. 阅读AGENTS.md、README和已有文档；
2. 执行git status，说明脏文件并保留用户已有改动；
3. 检查当前仓库、分支、Python/Node版本、已有依赖、测试和构建方式；
4. 输出docs/architecture/current-state.md；
5. 输出docs/architecture/target-architecture.md；
6. 输出docs/implementation/roadmap.md；
7. 列出真实政策、合同和报表模板的待确认项；
8. 不编造上海各区补贴金额、退费口径和政府字段；
9. 不一次性实现全部模块；
10. 不覆盖与当前阶段无关的代码。

每个阶段交付必须说明：
- 完成内容；
- 数据库migration；
- API；
- 页面；
- 权限；
- 测试与构建结果；
- 遗留风险；
- 下一阶段建议。

现在只完成仓库检查、目标架构和实施路线，不实现完整业务。输出发现的冲突、风险和Prompt 1的精确变更清单。
```

---

## Prompt 1：工程基线与SQLite骨架

```text
根据已确认的目标架构，完成Sprint 0：FastAPI + SQLite工程基线。

本阶段只建立可运行、可测试、可迁移的工程骨架，不实现大量业务CRUD。

要求：

一、仓库安全
1. 阅读AGENTS.md、README和架构文档。
2. 执行git status并保留用户已有改动。
3. 不修改与Sprint 0无关的文件。

二、后端工程
1. Python 3.12、FastAPI、SQLAlchemy 2.x同步Session、Pydantic v2、Alembic、pytest、Ruff。
2. 使用pyproject.toml统一依赖与工具配置。
3. 建立core和业务模块目录，但只创建必要骨架，不生成空表。
4. 配置统一Settings，从环境变量读取SECRET、数据库路径、OSS配置和加密密钥。
5. 提供/dev、/test、/production三套配置，不提交真实Secret。

三、SQLite
1. 默认数据库路径为可配置的/data/app.db。
2. 连接时启用WAL、foreign_keys、busy_timeout=5000和synchronous=NORMAL。
3. SQLAlchemy连接池配置适合单实例SQLite，不盲目使用大连接池。
4. 生产启动文档明确只运行一个Uvicorn Worker。
5. Alembic启用render_as_batch或等效SQLite批量迁移能力。
6. 建立初始migration并验证空库升级。

四、基础模型
只实现：
- Organization；
- User；
- Role；
- Permission；
- UserRole；
- UserDataScope；
- UserSession；
- AuditLog；
- BusinessEvent；
- AppSetting。

Organization第一期初始化为一个默认机构，但所有核心基础模型保留organization_id。

五、认证
1. 实现登录、退出、当前用户和会话撤销API。
2. 使用随机session token，数据库只保存哈希。
3. Cookie使用HttpOnly、SameSite=Lax，生产Secure=true。
4. 使用Argon2密码哈希。
5. 实现CSRF保护并写测试。
6. 登录接口支持Nginx限流配置示例。

六、权限
1. 建立操作权限和数据范围的基础接口。
2. 所有需要登录的API默认拒绝匿名访问。
3. 提供系统管理员和普通只读用户的权限测试。
4. 深链接和API不能仅依赖前端菜单控制。

七、通用规范
1. 公有API使用不可猜测UUID，数据库内部可使用整数主键或UUID，但全项目保持一致。
2. 建立统一审计字段、乐观version字段、错误码和correlation_id。
3. 金额以整数分、时长以整数分钟的规范写入docs/architecture/data-conventions.md。
4. 核心业务未来不使用通用软删除。
5. 不使用FastAPI BackgroundTasks处理关键业务。

八、前端骨架
1. Vue 3 + TypeScript + Vite + Element Plus + Pinia。
2. 实现登录页、基础布局、动态菜单、403、404和统一错误提示。
3. 前后端同域路径规划：/为前端，/api为FastAPI。
4. Cookie认证，不在localStorage保存长期token。

九、原生部署与检查
1. Windows 开发使用 Python 虚拟环境和 Vite；生产由 Nginx 和 systemd 管理 FastAPI。
2. SQLite目录使用 ECS 本地明确的数据目录，不在代码仓库或网络文件系统。
3. 健康检查区分liveness和readiness。
4. 不引入PostgreSQL、Redis、Celery或其他服务。

十、测试与验收
必须运行并报告：
- ruff check；
- ruff format --check；
- pytest；
- alembic upgrade head空库测试；
- 前端typecheck；
- 前端build。

测试至少覆盖：
- SQLite PRAGMA真实生效；
- 外键约束生效；
- 登录、退出和会话撤销；
- CSRF拒绝；
- 权限拒绝；
- migration可从空库执行；
-日志中不出现密码、Cookie和session token。

最终输出完成清单、文件变化、migration、测试结果和Prompt 2实施建议。
```

---

## Prompt 2：学员、课程版本、报名与双主线

```text
实现第一个完整业务纵向切片：学员唯一主档、课程版本、课程报名、班级骨架，以及学员/班级双主线导航。

一、学员
1. Student代表自然人唯一主档。
2. StudentIdentityDocument支持身份证、护照和其他证件。
3. 证件号标准化后生成HMAC-SHA-256查重索引；明文使用AES-GCM加密并保存key_version。
4. 手机号同样加密，列表默认脱敏。
5. 身份证缺失时，只生成疑似重复提示，禁止按姓名或手机号自动合并。
6. 建立学员合并预留模型或服务接口，但本阶段不实现复杂自动合并。
7. 明文查看使用独立API，校验权限、填写理由并记录AuditLog。

二、课程版本
实现：
- CourseCatalog；
- CourseOfferingVersion；
- CurriculumVersion；
- ExamSchemeVersion；
- CourseSubjectVersion；
- FeePolicyVersion；
- RefundPolicyVersion。

初始化人工智能训练师和全媒体运营作为演示数据，但课程名称、科目和规则不得写死在业务代码中。

已发布版本不能直接修改，只能停用或新建版本。

三、课程报名
实现CourseEnrollment：
- 一个学员可以报名多门课程；
- 同一课程未来可以重新报名；
- 滚班不新建CourseEnrollment；
- 报名绑定课程版本、考试方案版本、收费规则版本和退款规则版本；
- lifecycle、learning、exam、financial、certificate、funding状态分别保存，不使用万能status。

四、班级骨架
实现ClassCycle和ClassMembership基本关系，但本阶段不做完整排课。

ClassMembership包含：
- entered_at；
- exited_at；
- membership_status；
- exit_reason；
- previous_membership_id；
- financial_treatment。

同一报名默认不能有两个时间重叠的ACTIVE班级经历。用事务、查询校验和数据库约束能够实现的部分共同保证，并编写并发/重复请求测试。

五、页面
1. 学员列表；
2. 学员360基础页面；
3. 课程报名工作空间；
4. 班级列表；
5. 班级360基础页面；
6. 从班级名单进入学员360并默认选中当前报名；
7. 返回班级时恢复筛选、排序、页码和页签。

学员360、课程报名工作空间和班级360不得复制同一业务表单。

六、权限
- 教师默认不能看身份证明文和财务信息；
- 班主任只看授权班级；
- 学员管理员可查看脱敏信息；
- 明文查看单独授权；
- 所有列表在SQL层应用organization和数据范围。

七、测试
至少覆盖：
- 同一证件并发创建只产生一个学员；
- 一人报名两门课程；
- 同一课程重新报名与滚班的区别；
- 已发布课程版本不可修改；
- 学员敏感字段加密和脱敏；
- 无权用户无法看明文；
- 从班级进入学员再返回时上下文不丢失；
- migration升级和回滚边界说明。

运行后端测试、Ruff、前端typecheck和build，并报告结果。
```

---

## Prompt 3：班级、课次、多教师、考勤与录屏

```text
实现教学执行闭环：班级→课次→多教师→考勤→录屏→教师课时统计。

一、课次
实现ClassSession：
- 计划开始/结束；
- 实际开始/结束；
- service_date；
- 计划分钟；
- 实际分钟；
- 教学内容；
- 状态；
- 取消、改期、补课和来源课次；
- 乐观version。

禁止使用浮点课时。

二、多教师
实现SessionTeacherAssignment：
- teacher_id；
- 角色：主讲、助教、联合授课；
- 实际开始/结束；
- actual_minutes；
- settleable_minutes；
- rate_amount_cent；
- rate_unit；
- 金额快照；
- 确认状态、确认人、确认时间；
- 调整原因和版本。

同一课次多名老师的工作分钟总和允许大于班级课次分钟。班级完成分钟和教师工作分钟必须分别统计。

三、考勤
实现AttendanceRecord、AttendanceRevision和AttendanceFinalization。

考勤支持：
- 到课；
- 迟到；
- 早退；
- 请假；
- 缺勤；
- 实际出勤分钟；
- 备注和证据附件。

状态：DRAFT→SUBMITTED→CONFIRMED→LOCKED。

已经被退款计算、补贴或报表引用的考勤不得覆盖，只能新增Revision或Adjustment。

唯一约束：同一class_session和class_membership只有一条当前AttendanceRecord。

四、滚班
实现原子滚班服务：
1. 锁定当前CourseEnrollment；
2. 检查目标班课程版本一致；
3. 结束旧ClassMembership并记录ROLLOVER退出原因；
4. 新建下一段ClassMembership并关联previous_membership_id；
5. 保存financial_treatment；
6. 记录审计和业务事件；
7. 重复幂等请求不能创建第二条班级经历。

五、录屏
实现SessionRecording：
- OSS对象；或
- 外部HTTPS地址。

保存平台、访问口令密文、时长、有效期、审核状态和备注。
外部地址只允许https和配置的域名白名单，防止javascript/file等危险scheme。

六、页面
- 班级360教学计划；
- 课次日历；
- 批量考勤表；
- 教师与课时；
- 录屏列表；
- 教师移动端今日课次和点名主路径。

一个50人班必须可以一次批量提交考勤，并返回逐行成功、失败和跳过原因。

七、测试
至少覆盖：
- 一班多老师；
- 同课次多老师；
- 未确认教师分钟不进入结算统计；
- 考勤唯一性；
- 批量考勤部分失败；
- 已锁定考勤不能覆盖；
- 考勤更正保留原值；
- 重复滚班幂等；
- 两次并发滚班只有一条有效链；
- 外部录屏危险URL被拒绝；
- 教师只能访问本人相关课次。

运行全部测试和构建并报告。
```

---

## Prompt 4：分科考试、补考费与证书

```text
实现考试、补考、滚班连续性和证书代发闭环。

一、模型
实现：
- ExamCase；
- ExamBatch；
- ExamRegistration；
- ExamRegistrationSubject；
- ExamSubjectResult；
- ExamResultRevision；
- ExamFeeObligation；
- Certificate；
- CertificateDelivery。

二、考试方案
ExamCase在创建时绑定并快照ExamSchemeVersion：
- 必考/选考科目；
- 合格线；
- 成绩有效期；
- 总体通过规则。

课程以后修改科目或合格线，不能改变历史ExamCase结论。

三、分科与多次补考
1. 首考可以同时报名两科；
2. 补考只能选择未通过、缺考或已失效的科目；
3. 每次每科有独立attempt_no；
4. 已通过且仍有效的科目不能重复产生补考费；
5. 单科补考失败后可以继续下一次补考；
6. 滚班不重置ExamCase和attempt编号；
7. 总体通过由所有必考科目的有效官方PASS计算，禁止手工设置overall_passed。

四、成绩
成绩支持：
- 待发布；
- 通过；
- 未通过；
- 缺考；
- 取消；
- 官方结果；
- 临时结果。

成绩纠错创建ExamResultRevision，保留原结果、理由、证据、操作者和时间。

五、考试费用义务
首考和补考统一使用ExamFeeObligation：
- 关联具体ExamRegistrationSubject；
- fee_type区分首次考试和补考；
- amount_cent；
- 状态；
- 幂等键。

同一科目报名和费用类型只能有一个有效费用义务。重复点击和重复请求不得重复收费。

本阶段只建立费用义务，与Prompt 5的统一收款和代缴流水衔接。

六、证书
只有全部必考科目通过才可以进入证书流程。

状态：
NOT_ELIGIBLE→ELIGIBLE→APPLIED→RECEIVED_BY_SCHOOL→NOTIFIED→DELIVERED→ACKNOWLEDGED。

保存：
- 证书编号；
- 发证机构；
- 课程和等级；
- 收证批次；
- 保管位置；
- 通知记录；
- 本人领取或代领；
- 签收附件；
- 补发关系。

同一资格只有一张有效证书，遗失补发不能形成两张并行有效证书。

七、页面和测试
学员360和班级360均可以查看考试摘要，并下钻全部历史。

测试至少覆盖：
- 两科首考均通过；
- 一过一挂；
- 只为未通过科目产生补考费；
- 第一次补考失败、第二次通过；
- 已通过科目先过期导致总体仍未通过；
- 缺考；
- 滚班后继续补考；
- 重复请求不生成重复费用；
- 成绩更正保留历史；
- 未全部通过不能申请证书；
- 补发证书的唯一有效性。

运行全部测试和构建并报告。
```

---

## Prompt 5：收费、代收代付、退费与教师结算

```text
实现轻量但可核对的资金闭环。不建设会计总账，不引入第三方支付平台，不使用浮点金额。

一、学员收费
实现：
- TrainingOrder；
- Charge；
- Payment；
- PaymentAllocation；
- CreditAdjustment；
- RefundRequest；
- RefundLine；
- RefundPayment。

费用性质至少包括：
- TRAINING_REVENUE；
- EXAM_PASS_THROUGH；
- MATERIAL；
- SUPPLEMENT；
- OTHER。

一笔Payment可以分配到多个Charge。一条Charge也可以分多次支付。

所有金额使用整数分。已确认Payment和Allocation禁止直接修改或删除，只能撤销或冲正。

二、考试代收代付
实现：
- ExamRemittanceBatch；
- ExamRemittanceLine；
- ExamRemittanceRefund。

一次向考试机构的汇款可以包含多个学员和多个科目。一条ExamFeeObligation可以被部分或完整代缴。

系统需要能回答：
- 已收未缴；
- 已缴未考；
- 考试机构已退但尚未退学员；
- 已完成对账。

三、退费
退款按照费用项逐行计算，不能只保存一个总金额。

可退上限：
实际已收分配金额
- 历史已退款
- 已审批未支付退款占用
- 已履约不可退金额。

RefundLine保存：
- charge_id；
- 原始实收；
- 已履约分钟；
- 计费分钟；
- 计费规则版本；
- 已代缴考试费明细；
- 机构是否退回；
- 扣减金额；
- 人工调整；
- 可退金额；
- 计算输入JSON快照。

退费口径必须可配置为实际出勤分钟、退学前机构已提供分钟或其他明确策略，但不要编造机构最终口径。

审批时锁定可退额度；支付失败释放或保持待处理必须有明确规则。两个并发退款请求不能超过可退余额。

四、培训权益与滚班
实现轻量TrainingEntitlement或等效记录：
- 购买/赠送分钟；
- 已消耗分钟；
- 免费滚班分钟；
- 补差分钟；
- 退费扣减依据。

ClassMembership的financial_treatment决定新班学习是否重复消耗或产生补差Charge。

五、教师结算
实现：
- TeacherSettlement；
- TeacherSettlementLine；
- TeacherPayment；
- TeacherPaymentAllocation。

只有已完成课次且已确认的SessionTeacherAssignment可进入结算。

同一SessionTeacherAssignment确认版本不能进入两个未作废的结算单。结算审批后冻结分钟和单价快照；后续修正生成下一期正负差额行，不能改历史结算。

六、权限与审计
- 财务数据只对授权角色可见；
- 退费审批和付款分离；
- 人工调整必须有原因；
- 所有收款、分配、退款、代缴和结算写AuditLog；
- 导出防Excel公式注入。

七、测试
至少覆盖：
- 部分付款；
- 一笔付款分配多个费用项；
- 分配金额不能超过付款；
- 两个并发退款只有一笔成功占用余额；
- 已代缴考试费按规则不可退；
- 考试机构退回后可退学员；
- 补考费重复点击不重复生成；
- 免费滚班不重复收费；
- 补差滚班只生成补差Charge；
- 同一教师课次不能重复结算；
- 历史结算只生成差额调整；
- 所有总金额等于明细行合计。

运行全部测试和构建并报告。
```

---

## Prompt 6：退役士兵身份、餐宿补贴与学校垫资

```text
实现退役士兵业务的资格、事实、权益和支付链路。本阶段先不生成政府正式报表。

一、身份层
实现：
- VeteranIdentity；
- VeteranIdentityEvidence；
- VeteranIdentityVerification；
- VeteranAttributeHistory。

稳定身份与时间性属性分离。退役证号加密保存并提供HMAC查重索引。

二、项目和资格
实现：
- FundingProgram；
- FundingProgramVersion；
- FundingSource；
- ProgramFundingSource；
- FundingCase；
- FundingCaseComponent；
- EligibilityAssessment；
- EligibilityEvidence。

FundingCase属于CourseEnrollment，不属于ClassCycle。

班级可以关联政府项目，但最终资格必须逐个落实到学员课程报名。

三、学校成本
实现轻量ProjectCost和ProjectCostAllocation，用于记录学校实际垫付：
- 教师课时费；
- 场地；
- 住宿；
- 其他项目成本。

学校实际成本不得直接等同于政府补贴权益或政府应收。

四、每日出勤事实
实现AttendanceDayFact：
- 学员；
- 日期；
- 来源课次列表；
- 当日计划分钟；
- 当日出勤分钟；
- 迟到、早退、请假和缺勤；
- 半天/全天判定；
- 事实版本和确认状态。

同一天多个课次只能形成一条当前有效每日事实。考勤更正后生成事实新版本或调整，不覆盖已经申报的旧事实。

五、住宿事实
实现LodgingStay和LodgingNightFact：
- 入住、退房；
- 每个住宿夜；
- 地点；
- 是否学校统一安排；
- 凭证；
- 审核状态；
- 与培训日期的关联。

住宿补贴不能仅凭AttendanceDayFact产生。

六、政策规则
实现版本化AllowancePolicy：
- 区；
- 部门；
- 政府项目；
- 费用类型；
- 有效期；
- 政策文件编号和附件；
- 规则选择基准；
- 单价、上限、阈值和舍入规则；
- 发布状态和版本。

规则只允许预定义策略和有类型参数。禁止数据库任意Python、SQL、eval或不受控Jinja。

每个发布规则必须有测试样例，发布后不能修改，只能创建新版本。

七、权益与支付
实现：
- SubsidyEntitlement；
- EntitlementAdjustment；
- AllowancePayable；
- AllowancePayment。

分别记录：
- 政策计算权益；
- 学校应向学员支付金额；
- 学校实际支付金额；
- 支付失败、补发、退回和冲正。

八、页面
- 学员360退役士兵页签；
- 课程报名政府项目资格；
- 班级每日出勤事实；
- 住宿事实；
- 餐补和住宿权益；
- 学校垫资与实际支付摘要。

九、测试
至少覆盖：
- 非退役学员不能建立FundingCase；
- 一个学员多门课程分别审核资格；
- 滚班不自动重置培训补贴资格；
- 同日两个课次只产生一条按日餐补权益；
- 缺勤不产生权益；
- 半天规则；
- 跨年度使用不同政策版本；
- 没有住宿事实不能产生住宿补贴；
- 权益、应付和实际支付金额互不混淆；
- 调整和冲正保留历史。

运行全部测试和构建并报告。
```

---

## Prompt 7：政府申报、核定、应收与到账

```text
实现退役士兵政府申报资金闭环：权益占用→申报→退回修订→核定→应收→到账→核销。

一、模型
实现：
- ClaimBatch；
- ClaimSubmissionRevision；
- ClaimLine；
- ClaimLineSource；
- ClaimDecision；
- ClaimDecisionLine；
- ClaimAdjustment；
- GovernmentReceivable；
- GovernmentReceivableLine；
- GovernmentReceipt；
- GovernmentReceiptAllocation。

二、逻辑批次和提交版本
ClaimBatch代表一次逻辑申报。
每次正式提交创建新的ClaimSubmissionRevision。

v1被退回后：
- v1数据、文件和哈希保持不变；
- v2引用v1；
- 系统展示差异；
- 不允许覆盖v1。

三、权益占用和双部门防重
每个ClaimLineSource明确引用SubsidyEntitlement及本次申报金额。

必须保证：
所有部门已占用申报金额合计 <= 权益可申报余额。

若政策允许两个部门合法分摊，必须有明确ProgramFundingSource分配规则；不能通过忽略警告实现。

SQLite缺少复杂跨行约束时，使用短事务、对FundingCase或Entitlement行进行写入串行化、唯一索引、版本号和服务层再次校验共同保证，并写并发测试。

四、核定
支持批次内：
- 全部通过；
- 部分通过；
- 部分驳回；
- 待处理；
- 退回补材料。

每个DecisionLine保存申报、核定、驳回、待处理金额及原因。

满足：申报金额 = 核定金额 + 驳回金额 + 待处理金额。

只有核定金额形成GovernmentReceivableLine。

五、到账和核销
一笔GovernmentReceipt可以核销多个应收；一个应收可以分多次到账。

约束：
- 到账分配总额不得超过到账金额；
- 应收累计核销不得超过应收余额；
- 银行流水号或业务幂等键防止重复导入；
- 撤销核销和到账冲正引用原记录；
- 不把整个批次简单设置为PAID。

应收状态：OPEN、PARTIALLY_SETTLED、SETTLED、DISPUTED、WRITTEN_OFF、REVERSED。

六、页面
- 申报批次；
- 权益占用明细；
- 提交revision和差异；
- 核定明细；
- 政府应收；
- 到账流水；
- 到账分配和核销；
- 学员与班级两个视角的申报状态。

七、测试
至少覆盖：
- 双部门不同费用合法申报；
- 同一权益重复申报被拦截；
- 合法分摊不超过权益余额；
- v1退回后创建v2；
- v1不可覆盖；
- 五天只核定四天；
- 只按核定金额形成应收；
- 800元应收分500和300两次到账；
- 重复银行流水不重复入账；
- 一个到账核销多个应收；
- 一个应收分多次核销；
- 撤销和冲正保留历史。

运行全部测试和构建并报告。
```

---

## Prompt 8：政府Excel/Word报表中心

```text
实现轻量政府报表中心。先支持一个真实区的人社和退役军人管理部门两套模板。真实模板未提供时使用明确标记的测试模板，禁止伪造正式字段。

一、原则
不开发复杂低代码报表平台。

采用：
业务事实→规则计算→标准数据集→Python适配器→Excel/Word。

二、模型
实现：
- ReportTemplate；
- ReportTemplateVersion；
- ReportAdapterRegistration；
- ReportValidationRule；
- ReportRun；
- ReportValidationIssue；
- ReportSubmissionSnapshot；
- ReportOutputFile。

三、标准数据集
定义只读、版本化的报表字段字典，例如：
- student.name；
- student.id_card_no；
- veteran.retirement_card_no；
- course.name；
- class.code；
- attendance.attended_minutes；
- attendance.day_count；
- exam.overall_passed；
- allowance.meal_amount_cent；
- allowance.lodging_amount_cent；
- claim.approved_amount_cent。

报表数据集不得执行任意数据库表达式。敏感字段只在有权限的正式生成路径解密，日志不得记录明文。

四、模板适配器
1. Excel使用openpyxl修改现有模板；
2. Word使用docxtpl和python-docx；
3. 每个复杂模板使用明确的版本化Python适配器类；
4. 适配器只负责位置、样式、分页、图片和文件渲染；
5. 资格、金额和政策判断必须在报表生成前完成；
6. XlsxWriter只可用于新建内部分析表，不用于修改政府原模板；
7. 不使用pandas直接覆盖正式模板。

五、校验和纠错
生成前执行：
- 必填；
- 格式；
- 范围；
- 跨字段；
- 材料完整性；
- 金额平衡；
- 重复申报；
- 权益占用；
- 核定与应收一致性。

ValidationIssue保存学员、班级、规则、源对象、源字段、错误级别和修复状态。

前端点击错误后直接打开唯一源数据表单；保存后重算并自动复验，再返回原错误位置。不得允许用户只改导出的Excel而不修源数据。

六、正式快照
正式提交保存：
- 标准数据集JSON；
- schema版本；
- 源记录ID和version；
- 规则版本和计算说明；
- 原始模板哈希；
- 适配器版本；
- 程序构建版本；
- 输出文件SHA-256；
- 附件清单和OSS versionId；
- 生成、复核和提交人员；
- 外部受理号；
- previous_revision_id。

七、黄金文件测试
至少检查：
- Sheet名称和顺序；
- 合并单元格；
- 字体、边框和填充；
- 列宽、行高；
- 打印区域、页边距和分页；
- 隐藏行列；
- 图片；
- 公式；
- 未映射区域；
- Word页眉页脚、表格跨页、中文字体和图片位置。

可使用LibreOffice Headless生成PDF预览，但不得声称与Microsoft Office绝对一致。

八、同步执行边界
少于1000学员时先同步生成。生成过程不能持有数据库写事务：
1. 短事务读取并冻结标准数据快照；
2. 事务结束；
3. 生成文件；
4. 上传OSS；
5. 短事务保存输出元数据。

如果实际生成超过10到20秒，只记录为风险，不在本阶段引入Celery。

九、测试
至少覆盖：
- 缺失字段定位；
- 修复源数据后自动复验；
- 模板版本切换；
- 同一数据重复预览；
- 正式快照不随源数据变化；
- 退回后创建新revision；
- 旧文件不可覆盖；
- 黄金模板样式检查；
- 无权用户不能生成、查看或下载正式报表；
- 日志不出现身份证和退役证号。

运行全部测试和构建并报告。
```

---

## Prompt 9：阿里云OSS私有附件

```text
实现阿里云OSS私有附件模块，保持单Bucket和前缀隔离的轻量方案。

一、存储抽象
定义ObjectStorage Protocol或ABC，业务层不得直接依赖SDK。

提供：
- LocalFakeStorage：测试使用；
- AliyunOssStorage：生产使用。

使用阿里云官方Python OSS SDK当前稳定版本和V4签名。凭证从默认凭证链、ECS RAM Role或环境变量读取，禁止硬编码。

二、模型
实现：
- FileObject；
- StudentDocumentBinding；
- EnrollmentDocumentBinding；
- SessionDocumentBinding；
- CertificateDocumentBinding；
- ClaimDocumentBinding；
- ReportDocumentBinding。

重要业务附件使用明确外键关联，不使用一个无约束GenericForeignKey承载全部附件。

FileObject保存：
- bucket；
- object_key；
- version_id；
- size；
- content_type；
- etag；
- OSS校验信息；
- 可选SHA-256；
- sensitivity；
- status；
- uploader；
- created_at。

三、Object Key
示例：
documents/{organizationId}/students/{studentId}/{documentType}/{uuid}.{ext}
recordings/{organizationId}/classes/{classId}/sessions/{sessionId}/{uuid}.{ext}
reports/{organizationId}/{year}/{department}/{submissionId}/{uuid}.{ext}

禁止姓名、证件号、手机号和原始文件名进入Object Key。

四、上传
实现：
- POST /api/files/prepare-upload；
- POST /api/files/complete-upload；
- POST /api/files/{id}/download-url；
- DELETE或archive业务接口。

prepare-upload校验：
- 登录；
- 操作权限；
- 数据范围；
- 业务对象存在；
- 扩展名白名单；
- 文件大小；
- Content-Type；
- 文件密级；
- 不可猜测object_key。

complete-upload必须幂等，使用HeadObject校验存在、大小、Content-Type和校验信息。分片ETag不得当作完整文件MD5。

五、状态
PENDING→ACTIVE / QUARANTINED / ARCHIVED / DELETED。

第一期至少完成：
- 扩展名、Content-Type和文件魔数一致性检查；
- 文件大小限制；
- Office/PDF模板只允许授权管理员上传；
- 失败文件不能进入ACTIVE；
- pending孤儿对象由Cron清理命令处理。

不要在本阶段新增ClamAV容器；将病毒扫描作为上线增强项记录，但架构保留QUARANTINED状态。

六、下载
1. 每次下载重新检查组织、对象归属、角色、数据范围、附件权限和文件状态；
2. 短时URL默认60到300秒；
3. 数据库和日志不保存签名URL；
4. 日志不记录完整query string；
5. 身份证和退役证下载记录理由和审计；
6. 批量材料包下载需要独立权限。

七、录屏
大录屏浏览器直传OSS，不能经过FastAPI进程。

支持分片上传时：
- 后端控制upload_id和object_key；
- 前端只上传授权part；
- 完成请求幂等；
- 提供清理未完成分片的CLI命令。

八、测试
使用LocalFakeStorage或mock，不访问真实生产Bucket。

至少覆盖：
- 无权上传；
- 跨班级下载；
- 伪造fileId；
- 大小或MIME不符；
- 重复complete；
- 过期签名；
- pending文件不能下载；
- object_key无PII；
- 签名URL不进入日志；
- 录屏不经过API服务器。

输出RAM最小权限示例、Bucket CORS、版本控制、加密、生命周期和日志配置清单，但不要创建真实云资源。
```

---

## Prompt 10：工作台、异常队列与批量操作

```text
实现真正降低教务工作量的角色工作台、异常队列、审批和批量操作框架。

一、模型
实现：
- WorkItem；
- ExceptionItem；
- ApprovalTask；
- BatchOperation；
- BatchOperationItem。

不实现通用流程引擎，只覆盖当前明确的待办、异常和审批。

二、角色工作台
按角色显示：
- 招生：疑似重复学员、报名材料缺失；
- 教务：未排课、考勤缺失、课时冲突、滚班待处理；
- 教师：今日课次、录屏待补、本人课时待确认；
- 考务：成绩待录、待补考、成绩异常、证书待发；
- 财务：待收、待代缴、待退、教师结算差异；
- 退役士兵专员：身份待核验、餐宿异常、重复申报风险；
- 报表专员：校验失败、退回待修订、待核定、待核销；
- 审批人：退费、课时、补贴和报表审批。

每条任务包含类型、对象、严重程度、来源规则、责任人、截止时间、状态、推荐动作和是否支持批量处理。

三、批量操作
至少支持统一框架：
- 批量分班；
- 批量考勤；
- 批量导入成绩；
- 批量生成补考费用；
- 批量确认教师课时；
- 批量生成证书发放单；
- 批量计算餐宿补贴；
- 批量生成报表或材料包。

统一交互：
选择→执行前校验→影响预览→二次确认→执行→成功/失败/跳过明细→下载错误清单→审计。

低于1000学员时批量操作同步分块执行。每批必须有明确大小上限，不能一次长事务修改全部记录。

四、权限降级
页面区分：
- 完全不可见；
- 可知道状态但无权看内容；
- 可看脱敏值；
- 临时查看明文。

无权限金额不能显示为0；无权限手机号不能显示为未填写；无附件权限不能错误显示为材料缺失。

五、表格能力
- 保存视图；
- 列配置；
- 固定关键列；
- 清除筛选；
- URL保存筛选、排序、页码和页签；
- 返回后恢复上下文。

六、移动端
375px宽度下支持：
- 教师查看今日课次；
- 班级名单；
- 点名；
- 提交考勤；
- 上传录屏地址；
- 确认本人课时。

不要把桌面宽表格简单缩小到手机。

七、测试和可用性验收
至少覆盖：
- 不同角色工作台内容不同；
- 异常解除后任务自动关闭；
- 批量操作部分失败不回滚成功项，但每项状态可追踪；
- 危险操作具有预览、确认和审计；
- 返回列表保留上下文；
- 教师看不到费用摘要；
- 普通学员不显示空退役士兵页签；
- 错误不只依赖颜色；
- 375px教师主路径无横向大表格。

运行全部测试和构建并报告。
```

---

## Prompt 11：单ECS部署、备份恢复与最终验收

```text
完成FastAPI + SQLite轻量系统的阿里云单ECS生产准备。不要实际购买、创建或修改云资源。

一、部署拓扑
浏览器→Nginx→Vue静态页面和FastAPI→SQLite本地云盘、阿里云OSS。

第一期只包含：
- nginx；
- api。

可选的CLI任务由宿主机 Cron 或 systemd timer 使用 Python 虚拟环境执行。

禁止引入PostgreSQL、Redis、Celery、Kubernetes和微服务。

二、FastAPI运行
1. 一个Uvicorn Worker；
2. 容器非root；
3. 只读根文件系统，只有/data和必要临时目录可写；
4. /data挂载独立持久云盘目录；
5. liveness和readiness；
6. 优雅关闭并完成当前短事务；
7. 不在容器启动时自动执行未审核migration。

三、SQLite运维
1. 启动检查WAL、foreign_keys、busy_timeout和synchronous；
2. 数据库文件和WAL文件权限最小化；
3. 数据库不在镜像和Git仓库内；
4. migration前自动创建一致性备份；
5. 提供数据库完整性检查命令；
6. 提供锁等待和database is locked监控日志；
7. 文档说明多Worker和多ECS暂不支持。

四、备份
实现并验证：
- sqlite3 backup API或VACUUM INTO；
- 备份SHA-256；
- 上传OSS backups前缀；
- 每日Cron示例；
- 关键操作前备份；
- 30天保留配置建议；
- 从备份恢复到新目录；
- 恢复后运行migration版本、完整性和核心业务勾稽检查。

禁止运行时直接cp正在使用的数据库文件作为唯一备份方式。

五、Nginx和网络
1. HTTPS；
2. HTTP跳转HTTPS；
3. 登录限流；
4. 请求体大小限制；
5. 静态资源缓存；
6. 敏感页面no-store；
7. 不记录Cookie、Authorization、签名URLquery和请求正文；
8. 安全响应头；
9. /api/docs生产关闭或仅管理员/内网访问。

六、OSS和RAM
1. 私有Bucket；
2. ECS RAM Role或安全环境变量；
3. 最小权限到Bucket和前缀；
4. V4短时签名；
5. CORS只允许正式域名；
6. 版本控制、服务端加密、生命周期和访问日志配置清单；
7. 不在代码、环境示例或 systemd 配置文件写真实 AK/SK。

七、日志和审计
1. JSON结构化日志；
2. correlation_id；
3. 运行日志和业务AuditLog分开；
4. 脱敏密码、Cookie、token、签名URL、身份证、手机号和退役证号；
5. systemd/journald 日志接入 SLS 的配置说明；
6. 审计导出和定期归档建议。

八、安全测试
至少检查：
- 默认密码；
- CSRF；
- 越权和IDOR；
- 跨班级/跨项目访问；
- 文件类型欺骗；
- 路径穿越；
- 危险外链；
- Excel公式注入；
- 签名URL泄漏；
- 重复提交；
- 并发退款；
- SQLite锁冲突；
- Secret和依赖漏洞。

九、容量和迁移阈值
文档列出迁移PostgreSQL的触发条件：
- 持续出现database is locked；
- 多个并发写入角色明显增加；
- 需要多Uvicorn Worker或多ECS；
- 增加后台并发Worker；
- 多校区、多机构；
- 需要高可用和时间点恢复；
- 数据库数GB且复杂查询明显变慢。

不按学员数量机械迁移。

十、最终回归验收
完成端到端业务故事：
1. 创建一个学员；
2. 分别报名人工智能训练师和全媒体运营；
3. 其中一门课程进入班级；
4. 创建多个课次和多个老师；
5. 完成考勤和录屏；
6. 两科考试一过一挂；
7. 只收未通过科目的补考费并记录代缴；
8. 滚入下一班；
9. 补考通过；
10. 进入证书代发；
11. 完成部分退费案例；
12. 建立退役士兵项目资格；
13. 计算餐补和住宿补贴；
14. 分别向两个部门申报；
15. 处理部分核定和分次到账；
16. 生成政府Excel/Word；
17. 退回后创建revision；
18. 完成数据库备份和恢复验证。

运行所有后端测试、Ruff、前端测试、typecheck、build、Alembic空库升级测试和恢复验证。

最终输出：
- 上线清单；
- 回滚步骤；
- 备份恢复结果；
- 安全检查结果；
- 未执行的真实云端检查；
- 已知容量边界；
- PostgreSQL迁移触发指标；
- 人工验收清单。
```

---

## 附录：Codex 执行纪律补充

如果Codex出现以下倾向，应明确拒绝：

- “为了生产化”擅自加入PostgreSQL、Redis或Celery；
- 一次性生成几十张空表和空CRUD页面；
- 把所有业务状态塞入一个status；
- 把课程、科目和政策写死在Python枚举或前端；
- 使用float保存金额或课时；
- 直接复制正在运行的SQLite文件做备份；
- 在FastAPI BackgroundTasks中处理退款、申报等关键流程；
- 保存永久OSS URL；
- 将身份证号放进Object Key；
- 用一个JSON字段替代考勤、考试、收费或申报领域表；
- 让数据库执行任意Python、SQL或eval规则；
- 用前端按钮禁用代替数据库唯一约束和幂等；
- 覆盖已确认考勤、官方成绩、资金和正式报表历史；
- 声称SQLite绝对不会出现写锁；
- 声称LibreOffice预览与Microsoft Office完全一致。

整个项目的原则是：

> 技术架构保持轻量，业务事实保持严谨；现在不为千人规模建设重型基础设施，但也不以轻量为理由牺牲收费、退款、考试、补贴和政府申报的可追溯性。
