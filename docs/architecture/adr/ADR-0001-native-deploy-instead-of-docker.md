# ADR-0001：放弃 Docker Compose，改为单机原生部署

- **状态**：已采纳（Accepted）
- **决策人**：项目负责人（用户）
- **留档日期**：2026-09-23
- **影响范围**：部署架构、运维方式、CI、文档（Prompt 1 第九节、Prompt 11 第二/三节）
- **基线偏离**：本决策**偏离**《职业培训教务系统 Codex 提示词 V3.0》原文。原文锁定「目标部署：单台阿里云 ECS + Docker Compose」，并在 Prompt 1 第九节要求「开发 Docker Compose 可以包含 api 和 nginx」，Prompt 11 第二节要求「容器非 root」「只读根文件系统」。

---

## 一、背景

原始设计 V3.0 锁定「单台阿里云 ECS + Docker Compose」作为第一期部署方式，并要求容器以非 root 运行、根文件系统只读。

在项目实际推进中，项目负责人明确要求**不使用 Docker**，改为在 ECS 上以 Nginx + systemd + Uvicorn 的原生方式部署。

## 二、决策

**第一期采用 ECS 原生部署，不引入 Docker、Docker Compose 或任何容器运行时。**

具体形态：

| 层 | 实现 |
| --- | --- |
| 反向代理与静态资源 | Nginx（`infra/nginx/boyan.conf`） |
| 应用进程 | Uvicorn，**固定单 worker**，由 systemd 托管（`infra/systemd/` 下 3 个 unit） |
| 数据库 | SQLite，位于 ECS 本地数据盘（如 `/data/app.db`） |
| 定时任务 | 宿主机 cron 或 systemd timer 调用 CLI 命令 |
| 前端 | Vite 构建为静态产物，由 Nginx 直接托管 |

## 三、理由

1. **部署链路更短**：单机、单进程、单数据库的规模下，容器带来的隔离收益小于其运维成本（镜像构建、镜像仓库、卷权限、日志采集适配）。
2. **SQLite 与容器天然不匹配**：SQLite 要求数据库文件位于本地数据盘且只允许单实例写入；容器化会额外引入数据卷挂载、文件权限（容器非 root + 只读根文件系统）与 WAL 文件落盘的复杂度，收益为负。
3. **故障排查直接**：`systemctl status` + journald + 直接操作 SQLite 文件，无需进入容器上下文。
4. **与设计锁定的技术栈无冲突**：V3.0 禁止引入 PostgreSQL、Redis、Celery、Kubernetes 等重组件，其目的是「不为千人规模建设重型基础设施」。放弃 Docker 与这一原则**方向一致**，属于同一取舍的延伸。

## 四、影响与后果

### 已执行的落地情况（实测）

- 仓库内**无任何容器产物**：无 `Dockerfile`、无 `docker-compose*.yml`、无 `.dockerignore`。
- `infra/` 仅包含 `nginx/boyan.conf` 与 3 个 systemd unit，与原生部署一致。
- `docs/deployment/ecs-native.md` 已按原生部署撰写。
- `docs/architecture/current-state.md` 记录了「用户已明确要求不使用 Docker」。

**执行是干净的，不存在"半迁移"或残留。**

### 由此新增的运维要求

1. 必须通过 systemd 保证单实例（`Restart=always` + 单 unit），**不得启动第二个 Uvicorn worker**。
2. SQLite PRAGMA（WAL / `foreign_keys` / `busy_timeout=5000` / `synchronous=NORMAL`）必须由应用在连接时注入，不再依赖容器初始化脚本。
3. 备份、孤儿附件清理、过期 session 清理通过宿主机 cron / systemd timer 调用 CLI。
4. 优雅关闭由 systemd 的 `TimeoutStopSec` 与应用信号处理共同保证，需完成当前短事务。

### 被放弃的设计要求（明确记录，避免后续被误判为漏做）

| 原文要求 | 现状 | 处置 |
| --- | --- | --- |
| Prompt 1 第九节「Docker 与检查」 | 不适用 | 本 ADR 替代 |
| Prompt 11 第二节「容器非 root」 | 不适用 | 改为「systemd unit 指定非 root 运行用户」 |
| Prompt 11 第二节「只读根文件系统」 | 不适用 | 改为「应用数据目录权限最小化，仅 `/data` 可写」 |
| 镜像构建与镜像仓库相关要求 | 不适用 | 无替代物 |

## 五、后续

- 若未来出现「多实例」「多 ECS」「需要高可用」等需求，**重新评审**是否引入容器；届时本 ADR 需被新的 ADR 取代，而不是静默修改。
- 与 PostgreSQL 迁移阈值相关的判断（见 Prompt 11 第九节）不受本决策影响。

---

*关联文档：`docs/architecture/baseline.md`（权威基线）、`docs/deployment/ecs-native.md`（部署细节）、`ADR-0002`（附件存储本地优先）*
