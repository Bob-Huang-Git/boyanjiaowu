# 职业培训教务系统

当前交付已覆盖 Sprint 0–5：工程与原生部署基线、学员与课程报名、本地附件中心、班级教学、分科考试与证书，以及收费、代收代缴、退费和教师结算。项目采用 Windows 原生开发与阿里云 ECS Linux 原生部署，不使用 Docker。

Sprint 6 的退役身份、政府项目资格、餐宿事实、补贴权益与学校垫资后端已经完成；细粒度数据范围、六项业务页面和人工验收仍在施工。后续 Sprint 6–11 按 [分批施工计划](docs/implementation/sprint-6-11-execution-plan.md) 推进。

## Windows 本地开发

环境要求：Python 3.12、Node.js 22.12+ 和 npm。PowerShell 的执行策略若阻止激活虚拟环境，可在当前终端执行 `Set-ExecutionPolicy -Scope Process Bypass`。

后端命令在 `backend` 目录执行：

```powershell
cd D:\workstation\boyan教务\backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
Copy-Item .env.example .env
alembic upgrade head
python -m app.cli.sync_sprint4_permissions
python -m app.cli.sync_sprint5_permissions
python -m app.cli.sync_sprint6_permissions
python -m app.cli.bootstrap
python -m app.cli.seed_demo
python -m app.cli.seed_attachments
python -m app.cli.seed_exam
python -m app.cli.seed_finance
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

`.env` 中的 `DATABASE_URL=sqlite:///./data/app.db` 是本地默认值；不得填写真实生产密钥。创建管理员会交互读取至少 6 位的密码，密码不会出现在命令历史中。后端地址为 `http://127.0.0.1:8000`，开发文档为 `http://127.0.0.1:8000/api/docs`，就绪检查为 `http://127.0.0.1:8000/api/health/ready`。

`seed_demo` 只用于开发环境，幂等创建“人工智能训练师”和“全媒体运营”演示课程及其已发布版本；不导入真实学员数据。

`seed_attachments` 幂等创建学员资料分类、允许格式和基础完整度要求。附件默认保存到 `.env` 指定的 `LOCAL_STORAGE_ROOT`，临时文件保存到 `LOCAL_TEMP_ROOT`；两者不应设为项目目录。当前仅支持 `STORAGE_BACKEND=local`，设置为 `oss` 会明确停止启动，因为 OSS 后端和迁移尚未实现。

Sprint 3 增加课次、教师安排、考勤提交确认锁定与修订、滚班、外部 HTTPS 录屏链接和教师分钟汇总。时长全部以整数分钟存储；考勤证明继续引用 Sprint 2 的本地附件对象。

Sprint 4 增加考试批次与科目配置、按课程报名的分科考试、任意次数补考、定点整数成绩、官方确认与修订、两阶段 Excel 成绩导入、考试费用认定及证书代发状态机。考试费用仅保存应收依据和政策快照，不包含 `paid`、真实收款、退款或财务流水。成绩导入模板可从考试工作台下载，也可请求 `GET /api/imports/exam-results/template`。

Sprint 5 增加培训费和考试费应收、线下收款及分配、考试机构应代缴和实际代缴、按锁定考勤分钟计算的退费快照、退款审批与付款、教师课次结算和付款。金额全部使用整数分，时长全部使用整数分钟。`SCHOOL_REVENUE` 与 `AGENCY_COLLECTION` 分开汇总；已确认资金记录通过追加调整或冲正保留历史。

另开 PowerShell 启动前端：

```powershell
cd D:\workstation\boyan教务\frontend
npm install
npm run dev
```

浏览器访问 `http://localhost:5173`。Vite 会将 `/api` 转发到本地 FastAPI。正式构建运行 `npm run build`，产物是 `frontend/dist`。

## 检查

```powershell
cd D:\workstation\boyan教务\backend
.\.venv\Scripts\Activate.ps1
ruff check .
ruff format --check .
pytest
python -m app.cli.exam verify
python -m app.cli.files verify --dry-run
python -m app.cli.files cleanup-staged --dry-run
python -m app.cli.files cleanup-orphans --dry-run

cd ..\frontend
npm run typecheck
npm run build
```

空数据库迁移已由后端测试覆盖；也可手动将 `DATABASE_URL` 指向一个新的本地 SQLite 文件后运行 `alembic upgrade head`。

## 常见问题

- `python` 找不到或版本不是 3.12：安装 Python 3.12，并确认 `python --version` 后重新创建 `backend\.venv`。
- PowerShell 拒绝运行 `Activate.ps1`：在当前终端执行 `Set-ExecutionPolicy -Scope Process Bypass`，然后重新激活。
- `alembic upgrade head` 提示数据库路径问题：确认在 `backend` 目录执行，并检查 `.env` 的 `DATABASE_URL` 是否为本机可写的 SQLite 路径。
- 地址已被占用：停止占用 8000 或 5173 端口的进程，或为 Uvicorn/Vite 指定其他端口。
- `database is locked`：确认只有一个本地后端实例在写入，结束长期事务后重试；生产环境固定一个应用实例和一个 Uvicorn worker。

## 原生部署

生产部署、systemd、Nginx、SQLite 备份恢复与回滚步骤位于[阿里云 ECS 原生部署文档](docs/deployment/ecs-native.md)。生产数据库位于 ECS 本地数据目录，不在代码仓库、OSS、NFS 或其他网络文件系统中运行。
