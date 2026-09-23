# SQLite 备份与恢复

## 备份

运行中的 SQLite 数据库不得使用 `cp`、`copy` 或直接复制 `app.db`。使用[备份脚本](../../scripts/backup_db.py)调用 Python `sqlite3.backup()` API：

```bash
sudo -u boyan /opt/boyan/venv/bin/python /opt/boyan/current/scripts/backup_db.py \
  --database /var/lib/boyan/app.db \
  --output-dir /var/lib/boyan/backups
```

脚本生成一致性快照、执行 `PRAGMA integrity_check`、计算 SHA-256，并写入同名 JSON 清单。失败返回非零退出码；临时文件会被清理；既有有效备份不会被删除。应在每天定时、迁移前、正式报表提交前和关键导入前执行。可按本地保留策略清理超过期限的备份，长期备份通过 OSS 私有 Bucket 生命周期规则管理。

验证某个备份：

```bash
sqlite3 /var/lib/boyan/backups/app-<timestamp>.sqlite3 'PRAGMA integrity_check;'
sha256sum /var/lib/boyan/backups/app-<timestamp>.sqlite3
cat /var/lib/boyan/backups/app-<timestamp>.json
```

当前脚本只生成本地一致性备份。待 OSS 存储适配器在后续附件阶段完成后，上传程序应使用 `backups/sqlite/YYYY/MM/DD/` 前缀并在远端确认成功后才记录上传结果；远端失败不得删除本地副本。

## 恢复演练

恢复会原子替换正式 SQLite 文件，必须在维护窗口操作：

1. 执行 `sudo systemctl stop boyan`，确认服务已停止。
2. 先对当前故障数据库执行一次备份命令，保留现场。
3. 选择备份文件和 JSON 清单，使用 `sha256sum` 核对 SHA-256。
4. 执行恢复：

```bash
sudo -u boyan /opt/boyan/venv/bin/python /opt/boyan/current/scripts/restore_db.py \
  /var/lib/boyan/backups/app-<timestamp>.sqlite3 \
  --database /var/lib/boyan/app.db \
  --confirm-application-stopped
```

5. 脚本会先还原到同目录临时文件，执行 `PRAGMA integrity_check`，再通过原子替换写入正式路径。
6. 检查所有者和权限：`sudo chown boyan:boyan /var/lib/boyan/app.db && sudo chmod 640 /var/lib/boyan/app.db`。
7. 执行 `sudo systemctl start boyan`，然后检查 `sudo systemctl status boyan`、`/api/health/ready` 和管理员登录。

恢复前不运行 Alembic 降级。若恢复到旧 schema，先切回与该备份匹配的代码 release；之后由人工评估是否执行向前迁移。每次恢复记录备份文件、哈希、恢复原因、操作者和健康检查结果。

