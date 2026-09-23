# 当前状态（2026-09-22）

开始时 `D:\workstation\boyan教务` 为空目录，不是 Git 仓库；没有 README、AGENTS.md、现有依赖或历史代码。提供的唯一项目资料是 `codex-prompts-fastapi-sqlite-training-system.md`，已复制到 `docs/requirements/`。本机有 Python 3.12.12、Node.js 22.18.0、npm 10.9.3、uv 0.11.2。

因此本次从零建立 Sprint 0 基线。需求文档包含项目总提示词和 Prompt 1–11；其中写给 Codex 的步骤是项目资料，具体实施范围以用户当前请求和本路线图为准。用户已明确要求不使用 Docker，项目采用直接运行的方式。

当前代码包含 FastAPI/SQLite/Alembic 基础模型、Session 认证、CSRF、权限入口、Vue 登录壳、检查命令。业务主线（学员、课程报名、班级、考试、财务、补贴、附件、报表）尚未实施。
