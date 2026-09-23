# 本地附件运维

Windows 建议 `LOCAL_STORAGE_ROOT=D:/boyan-data/attachments`、`LOCAL_TEMP_ROOT=D:/boyan-data/temp`；Linux 建议 `/var/lib/boyan/attachments` 和 `/var/lib/boyan/temp`。这些目录不应位于项目、用户主目录或磁盘根目录，并应由运行服务账号独占写入。

初始化后执行 `python -m app.cli.seed_attachments` 创建资料分类与基础完整度要求。检查命令：`python -m app.cli.files verify --dry-run`，可加 `--sha256`。`cleanup-staged` 与 `cleanup-orphans` 默认 dry-run；只有显式 `--execute` 才会删除。`export-manifest` 输出不含绝对路径的脱敏清单。

SQLite 备份不包括附件目录。数据库与附件需使用同一备份批次清单；恢复后执行 `files verify`。临时目录不进入长期备份。
