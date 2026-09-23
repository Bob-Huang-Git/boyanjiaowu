# 阿里云 ECS 原生部署

本文适用于 Ubuntu 24.04 LTS。部署使用 Nginx、systemd、Uvicorn 和 SQLite；应用只运行一个实例和一个 Uvicorn worker。数据库必须位于 ECS 本地可靠磁盘，不能位于代码目录、OSS、NFS、NAS 或其他网络文件系统。

## 目录与账户

创建专用运行账户和目录：

```bash
sudo useradd --system --home /opt/boyan --shell /usr/sbin/nologin boyan
sudo install -d -o boyan -g boyan -m 0750 /opt/boyan/releases /var/lib/boyan/backups /var/lib/boyan/runtime /var/log/boyan
sudo install -d -o root -g root -m 0755 /opt/boyan
sudo install -d -o root -g root -m 0750 /etc/boyan
```

发布代码放在 `/opt/boyan/releases/<版本>`，`/opt/boyan/current` 指向正在运行的版本。Python 虚拟环境是 `/opt/boyan/venv`，前端入口 `/opt/boyan/frontend-dist` 也指向当前版本的 `frontend/dist`。SQLite 主库固定为 `/var/lib/boyan/app.db`，备份位于 `/var/lib/boyan/backups`。代码发布不会覆盖数据目录。

`/etc/boyan/boyan.env` 仅在服务器保存真实密钥：

```dotenv
APP_ENV=production
APP_SECRET_KEY=replace-with-a-unique-secret-at-least-32-characters
DATABASE_URL=sqlite:////var/lib/boyan/app.db
SESSION_COOKIE_NAME=boyan_session
SESSION_SECURE=true
SESSION_SAMESITE=lax
CSRF_SECRET=replace-with-a-different-unique-secret-at-least-32-characters
PII_ENCRYPTION_KEY=provided-by-kms-or-secure-secret-store
PII_BLIND_INDEX_KEY=provided-by-kms-or-secure-secret-store
LOG_LEVEL=INFO
BACKUP_LOCAL_DIR=/var/lib/boyan/backups
```

设置 `sudo chown root:root /etc/boyan/boyan.env` 和 `sudo chmod 600 /etc/boyan/boyan.env`。密钥不进入 Git、日志、Vite 环境变量或 systemd unit。当前附件使用受控本地目录；OSS 适配器尚未开发，当前不配置任何 OSS 变量。

## 首次安装

安装 Python 3.12、Node.js 22.12+、Nginx 和 Git。将已审核的代码检出到一个 release 目录后，建立运行环境：

```bash
sudo -u boyan python3.12 -m venv /opt/boyan/venv
sudo -u boyan /opt/boyan/venv/bin/python -m pip install --upgrade pip
sudo -u boyan /opt/boyan/venv/bin/pip install '/opt/boyan/releases/<版本>/backend[dev]'
sudo ln -sfn /opt/boyan/releases/<版本> /opt/boyan/current
sudo ln -sfn /opt/boyan/current/frontend/dist /opt/boyan/frontend-dist
sudo -u boyan env $(sudo grep -v '^#' /etc/boyan/boyan.env | xargs) /opt/boyan/venv/bin/alembic -c /opt/boyan/current/backend/alembic.ini upgrade head
```

最后一条命令须在 `WorkingDirectory=/opt/boyan/current/backend` 下执行；更稳妥的方式是先 `sudo -u boyan -H bash`，`cd /opt/boyan/current/backend`，载入受控环境后执行 Alembic。任何迁移失败都停止发布，保留旧代码与数据库，不删除 SQLite 文件。

将 [boyan.service](../../infra/systemd/boyan.service)、[boyan-backup.service](../../infra/systemd/boyan-backup.service) 和 [boyan-backup.timer](../../infra/systemd/boyan-backup.timer) 分别安装到 `/etc/systemd/system/`，然后执行：

```bash
sudo systemctl daemon-reload
sudo systemctl enable boyan
sudo systemctl enable --now boyan-backup.timer
sudo systemctl restart boyan
sudo systemctl status boyan
```

服务使用 `boyan` 账户、监听 `127.0.0.1:8000`、禁用 reload，并显式限制为单 worker。Nginx 是唯一公网入口。

## Nginx 与 HTTPS

将 [boyan.conf](../../infra/nginx/boyan.conf) 安装为 `/etc/nginx/sites-available/boyan`，替换域名和证书路径，再创建链接并检查：

```bash
sudo ln -sfn /etc/nginx/sites-available/boyan /etc/nginx/sites-enabled/boyan
sudo nginx -t
sudo systemctl reload nginx
```

启用 HTTPS 后，保留一个 80 端口 server 将请求 `return 301 https://$host$request_uri;`，并在 443 端口 server 中启用证书。生产环境设置 `SESSION_SECURE=true` 后必须经 HTTPS 访问。Nginx 配置提供 Vue History 回退、`/api/` 反代、转发地址头、上传体积限制、静态缓存和对隐藏文件、数据库与备份路径的拒绝规则；它不映射 `/var/lib/boyan`。

## 发布

每次发布使用新的 `/opt/boyan/releases/<commit-or-tag>` 目录。发布操作必须在维护窗口执行，并保存 `/var/log/boyan/deploy.log`。

1. 获取指定、已审核的 Git commit 或 tag 到新的 release 目录，记录当前 `readlink -f /opt/boyan/current` 与目标 commit。
2. 在停止服务前执行 `/opt/boyan/current/scripts/backup_db.py --database /var/lib/boyan/app.db --output-dir /var/lib/boyan/backups`；确认命令成功、`integrity_check=ok` 和 JSON 清单 SHA-256 已生成。
3. 在新 release 的 `backend` 中，用 `/opt/boyan/venv/bin/pip install '<release>/backend[dev]'` 安装锁定范围内依赖；运行 Ruff、pytest 和 Alembic 空库升级测试。
4. 在新 release 的 `frontend` 中运行 `npm ci` 与 `npm run build`。
5. 将 `DATABASE_URL` 指向生产库并从新 release 的 `backend` 执行 `alembic upgrade head`。失败时立即停止，保留旧软链接和部署前备份，按恢复流程处理。
6. 原子更新 `current` 与 `frontend-dist` 软链接，执行 `sudo systemctl restart boyan`。
7. 执行 `/opt/boyan/current/scripts/healthcheck.sh`，检查 `systemctl status boyan`、Nginx 状态和管理员登录，记录结果。

迁移前后都不允许删除数据库文件。迁移应在 SQLite batch mode 中维护，并针对空库、上一版本库、外键和关键唯一约束进行测试。

## 回滚

先确定迁移是否与旧代码兼容。若兼容，将 `current` 和 `frontend-dist` 软链接切回上一 release，重启 `boyan`，再执行健康检查。若不兼容，停止应用，使用部署前备份进行人工恢复，切回旧 release 后启动服务。不要假定所有迁移都可自动降级；涉及数据删除或表重建时，以已验证备份恢复为准。记录回滚原因、目标版本、备份清单和健康检查结果。

## 定时任务与边界

`boyan-backup.timer` 每日 02:15 触发一致性备份。清理临时对象、异常上传检查等任务应使用独立 systemd timer 或 Cron，以同样的专用账户运行。不得使用 Redis、Celery、RabbitMQ、Kafka、Kubernetes 或额外数据库。OSS 备份上传将在 OSS 适配器阶段实现；在此之前，本地有效备份不会因远端上传失败被删除。

备份、恢复演练与完整性检查见[SQLite 备份与恢复](../operations/sqlite-backup-recovery.md)。
