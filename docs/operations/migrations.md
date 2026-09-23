# 数据库迁移

发布前必须先用一致性备份脚本备份 SQLite，再在 `backend` 目录运行 `alembic upgrade head`。Sprint 1 revision 为 `83208c080abe`，只新增业务表和索引，不删除 Sprint 0 的用户、角色、会话或审计数据。

SQLite 继续使用 Alembic batch migration。Sprint 4 从 Sprint 3 revision `0699df8f1196` 依次升级到 `c8ddc70c572c`、`66f961811c0b`、`4ffc2789065a` 和当前 head `8605eb546b45`。本地门禁已验证空库升级、head 降级至 Sprint 3、以及 Sprint 3 再升级到 head。

生产发布仍需先备份。迁移失败时停止发布、保留代码和数据库，按[SQLite 备份恢复](sqlite-backup-recovery.md)恢复。Alembic downgrade 只用于已验证且没有新增正式 Sprint 4 数据的受控回滚；一旦产生考试、费用认定或证书数据，应恢复发布前备份并由人工处理业务数据，不能把 downgrade 当作数据备份。
