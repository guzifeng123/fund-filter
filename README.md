# 基金分析 Web 应用

一个本地优先的基金分析 Web 应用，用于风险测评、基金筛选、组合管理、回测和投教型 AI 助手。当前版本仍使用 sample 数据，尚未接入真实公开数据源、盈米 MCP、真实回测引擎或真实 LLM/RAG。

## 技术栈

- 前端：Next.js App Router、React、项目自定义组件、ECharts
- 后端：FastAPI、Pydantic、SQLAlchemy、Alembic
- 数据库：PostgreSQL + pgvector
- 工作区：npm workspaces

## 环境变量

复制 `.env.example` 到本地 `.env` 后按需修改：

```powershell
Copy-Item .env.example .env
```

关键变量：

- `DATABASE_URL`：后端数据库连接，默认指向本地 Docker Postgres。
- `DATABASE_CONNECT_TIMEOUT_SECONDS`：单次数据库连接超时秒数，默认 `2`。
- `DATA_STATUS_TIMEOUT_SECONDS`：`/api/data/status` 请求级查询上限，默认 `2.5` 秒；超时后返回 `db_connected=false`，慢连接在独立 Session 中结束，不阻塞响应。
- `CORS_ORIGINS`：允许访问 API 的前端来源，使用英文逗号分隔；示例默认覆盖本地 `3000` 和备用 `3001` 端口。
- `NEXT_PUBLIC_API_BASE`：前端请求 API 的基础地址，默认 `http://localhost:8000/api`。
- `LLM_PROVIDER`、`LLM_MODEL`、`LLM_API_KEY`、`LLM_BASE_URL`：v0.7 AI Gateway 预留。
- `FUND_DATA_SOURCE`、`FUND_DATA_STALE_DAYS`：v0.6 数据源与数据新鲜度预留。

## 安装依赖

Windows PowerShell 下请使用 `npm.cmd`：

```powershell
npm.cmd install
python -m pip install -e .\apps\api[dev]
```

检查本地开发前置条件：

```powershell
.\scripts\check-env.ps1
```

有 Docker 和正在运行的 API 时，可以串联初始化/验收步骤：

```powershell
.\scripts\check-env.ps1 -StartPostgres -RunMigrations -SeedSampleData
.\scripts\check-env.ps1 -RunSmoke
```

## 数据库初始化

启动 PostgreSQL：

```powershell
docker compose up -d postgres
```

执行迁移：

```powershell
.\scripts\db-migrate.ps1
.\scripts\db-migrate.ps1 -DatabaseUrl "postgresql+psycopg://fund_user:fund_pass@localhost:5432/fund_app"
.\scripts\db-migrate.ps1 -Command current -DryRun
```

等价手动命令：

```powershell
Set-Location .\apps\api
python -m alembic -c alembic.ini upgrade head
Set-Location ..\..
```

写入 sample 数据。该命令应当幂等，连续运行两次不应重复插入基金、净值或指标：

```powershell
python -m app.jobs.seed_sample_data
python -m app.jobs.seed_sample_data
```

## 本地启动

启动 API：

```powershell
npm.cmd run dev:api
```

另开一个 PowerShell 启动 Web：

```powershell
npm.cmd run dev:web
```

默认地址：

- Web: `http://localhost:3000`
- API health: `http://localhost:8000/health`
- Data status: `http://localhost:8000/api/data/status`

## Smoke Test

API 启动后可用 PowerShell 验证：

```powershell
.\scripts\smoke-api.ps1
```

如果 API 不在默认 `http://localhost:8000`，可以传入地址：

```powershell
.\scripts\smoke-api.ps1 -ApiBase "http://localhost:8000"
```

发布或 CI 留档时，可以要求数据新鲜、空库时自动 seed，并输出 JSON 报告：

```powershell
.\scripts\smoke-api.ps1 -SeedIfEmpty -RequireFresh -JsonReportPath ".\output\smoke\api-smoke.json"
```

脚本当前会验证 `/health`、`/api/data/status` 和 `/api/funds/filter` 的基础 envelope。`-RequireFresh` 会要求数据状态为 `fresh`，`-JsonReportPath` 会记录 schema 版本、运行环境、OpenAPI 文件信息、每一步耗时、成功/失败状态和数据摘要。也可以手动执行同等请求：

```powershell
Invoke-RestMethod http://localhost:8000/health
Invoke-RestMethod http://localhost:8000/api/data/status
$body = @{
  risk_profile = 'C3'
  fund_types = @('mixed','bond')
  min_years = 3
  size_range = @(0, 500)
  return_rank_percentile = 50
  max_drawdown_lte_category_avg = $true
  sharpe_gte = 0.8
  fee_lte = 1.5
} | ConvertTo-Json
Invoke-RestMethod -Method Post http://localhost:8000/api/funds/filter -ContentType 'application/json' -Body $body
```

## 质量检查

```powershell
python -m pytest apps/api/app/tests
python -m ruff check apps/api/app
.\scripts\check-compliance-text.ps1
npm.cmd run lint:web
npm.cmd run test:web
npm.cmd run build:web
```

清理本地生成产物：

```powershell
.\scripts\clean-generated.ps1 -WhatIf
.\scripts\clean-generated.ps1
.\scripts\clean-generated.ps1 -WhatIf -SearchRoots apps,packages
.\scripts\clean-generated.ps1 -WhatIf -JsonReportPath ".\output\checks\cleanup-report.json"
```

清理脚本默认跳过 `node_modules`、`.git`、`.venv`、`output` 等大型或需保留目录，并且只允许删除工作区内部路径。

备份与恢复本地数据库：

```powershell
.\scripts\backup-db.ps1
.\scripts\backup-db.ps1 -RetentionCount 10
.\scripts\backup-db.ps1 -Compress -RetentionCount 10
.\scripts\backup-db.ps1 -Compress -RetentionCount 10 -JsonReportPath ".\output\checks\backup-report.json"
.\scripts\restore-db.ps1 -BackupPath ".\backups\fund_app-YYYYMMDD-HHMMSS.sql" -ConfirmRestore RESTORE
.\scripts\restore-db.ps1 -BackupPath ".\backups\fund_app-YYYYMMDD-HHMMSS.sql.gz" -ConfirmRestore RESTORE
```

备份脚本会生成同名 `.sha256` 校验文件；恢复脚本会在校验文件存在时先验证完整性。

发布前也可以用一个脚本串联主要质量门禁：

```powershell
.\scripts\check-all.ps1
.\scripts\check-all.ps1 -CheckOpenApiDrift
.\scripts\check-all.ps1 -CheckOpenApiDrift -OpenApiDiffPath ".\output\checks\openapi.diff"
```

## 常见失败排查

- 环境自检：先运行 `.\scripts\check-env.ps1`，查看 Python、npm.cmd、Docker、依赖和端口提示。
- Docker 未启动：`docker compose up -d postgres` 报错时，先确认 Docker Desktop 已运行。
- 5432 端口占用：检查本机是否已有 PostgreSQL 占用端口；必要时修改 `docker-compose.yml` 的端口映射和 `.env` 的 `DATABASE_URL`。
- 数据库迁移失败：先运行 `.\scripts\db-migrate.ps1 -Command current` 查看当前版本，再运行 `.\scripts\db-migrate.ps1 -Command upgrade -Revision head`。
- seed 导入失败：确认 `DATABASE_URL` 指向已迁移数据库，并查看 `job_runs` 或终端错误详情。
- 前端读取不到 API：确认 API 运行在 `http://localhost:8000`，且 `.env` 中 `NEXT_PUBLIC_API_BASE` 为 `http://localhost:8000/api`。
- API smoke 失败：先访问 `http://localhost:8000/health`，再运行 `.\scripts\smoke-api.ps1 -ApiBase "http://localhost:8000"`。

## Docker Compose

完整服务编排已包含 `postgres`、`api`、`web`：

```powershell
docker compose up --build
```

当前推荐先单独验证 `postgres`、迁移和 seed，再启动 API/Web。

有 Docker 的环境可以运行完整编排验收：

```powershell
.\scripts\verify-docker-compose.ps1
.\scripts\verify-docker-compose.ps1 -DownAfter
```

## 合规边界

本应用仅用于基金数据整理、风险匹配、历史回测和投教解释，不提供收益预测、短线买卖点、自动下单或强交易指令。涉及基金、组合、回测和 AI 输出时必须展示数据来源、数据日期和免责声明。详细规则见 [docs/合规边界.md](docs/合规边界.md)。

## 项目文档

- [docs/web应用技术设计方案.md](docs/web应用技术设计方案.md)：产品、架构、页面、业务规则和里程碑。
- [docs/API接口说明.md](docs/API接口说明.md)：API contract 与 OpenAPI 导出流程。
- [docs/数据源接入方案.md](docs/数据源接入方案.md)：sample、公开数据源和盈米 MCP 接入策略。
- [docs/数据字典.md](docs/数据字典.md)：当前核心表和字段说明。
- [docs/备份与数据清理.md](docs/备份与数据清理.md)：本地数据库备份、恢复和生成产物清理。
- [docs/待完成与版本任务规划.md](docs/待完成与版本任务规划.md)：版本任务、验收门槛和优化备忘。

## 发布检查

发布或阶段验收前按 [docs/发布检查清单.md](docs/发布检查清单.md) 执行。
