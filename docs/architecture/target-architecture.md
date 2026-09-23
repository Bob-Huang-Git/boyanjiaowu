# 目标架构

## 部署与边界

单机构、少于 1000 学员、低并发写入。开发者在 Windows 上使用 Python 虚拟环境与 Node.js；生产环境为阿里云 ECS Linux。浏览器经同域 Nginx 访问 Vue 静态文件及 `/api` FastAPI。FastAPI 由 systemd 以单 worker 运行，使用 SQLAlchemy 2.x 同步 Session，SQLite 文件位于 ECS 本地持久数据盘。OSS 私有 Bucket 存附件与异地备份。备份、清理由 systemd timer 或 Cron 调用 CLI。第一期不引入 Docker、队列、缓存服务或多数据库。

```text
浏览器 → Nginx → Vue 3
               ↘ FastAPI → SQLite（本地盘）
                          ↘ OSS（私有 Bucket）
```

数据库连接启用 WAL、外键、5 秒 busy timeout、NORMAL 同步；迁移使用 Alembic batch mode。每个请求创建并关闭一个同步 Session。写事务保持短小，遇到 SQLite 写锁返回 `DATABASE_BUSY`，不无限重试。报表生成、OSS 调用和压缩不得占用写事务。金额存整数分，时长存整数分钟。时间戳存 UTC，业务日期明确保存，页面按 Asia/Shanghai 展示。

## 业务对象

主链为 Student → CourseEnrollment → ClassMembership → ClassSession/Attendance。学员主档对应自然人；课程报名对应一次课程业务链；滚班结束旧班经历并新增一段经历。考试按科目、场次和结果记录，已通过科目保持通过。资金事实区分收款、代收代付、退款、教师结算、学员补贴、政府申报、政府核定、应收和到账。

页面采用学员 360、课程报名工作空间、班级 360。班级名单打开同一个学员 360，并通过受控路由参数保留来源、筛选、排序、页码和页签。

## 安全与审计

服务端 Session，仅存随机 token 的哈希；Cookie 为 HttpOnly、SameSite=Lax，生产 Secure。修改请求校验 CSRF。角色决定操作权限，数据范围在 SQL 查询层实施；敏感字段和附件下载另设权限及审计。身份信息按规范化 HMAC 查重，明文 AES-GCM 加密，密钥从环境或 KMS 取得。正式事实使用修订、调整或冲正，不覆盖历史。

## 当前实现与待完成

Sprint 0 已建立基础认证与权限模型；数据范围只有存储结构，尚无业务查询可应用。OSS 配置字段已预留，适配器和密钥处理将在附件阶段实现。当前页面只是登录及工作台壳，不表示业务功能已交付。
