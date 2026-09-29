# 基金分析 Web 应用

一个本地优先的基金分析 Web 应用，用于风险测评、基金筛选、组合管理、回测和投教型 AI 助手。当前版本已完成本地功能闭环：数据库持久化、sample/CSV/静态 JSON 数据源 adapter、真实净值回测、AI Gateway、SSE 与 RAG 基础表已落地；真实公开数据字段映射、盈米 MCP、真实 LLM provider 和账号体系仍待接入。

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
- `APP_ENVIRONMENT`：运行环境，支持 `development`、`test`、`staging`、`production`；后两者启用部署配置 fail-fast 校验。
- `CORS_ORIGINS`：允许访问 API 的显式 HTTP(S) 前端来源，使用英文逗号分隔；不允许通配符、路径、查询参数或内嵌凭据。
- `WEB_ORIGIN`：实际 Web Origin（协议、域名和可选端口）；`staging`/`production` 必须显式设置，且必须与 `CORS_ORIGINS` 中一项完全匹配。
- `NEXT_PUBLIC_API_BASE`：前端请求 API 的基础地址，默认 `http://localhost:8000/api`。
- `LLM_PROVIDER`、`LLM_MODEL`、`LLM_API_KEY`、`LLM_BASE_URL`：AI Gateway 配置；默认可使用 mock provider。`LLM_BASE_URL` 必须是无凭据、无 query/fragment 的 HTTP(S) 服务根地址，不能直接填 `/chat/completions` 端点。
- `LLM_TIMEOUT_SECONDS`、`LLM_MAX_RETRIES`、`LLM_MAX_RESPONSE_BYTES`、`LLM_MAX_OUTPUT_CHARS`：真实 provider 的超时、重试次数、响应 body 字节上限和输出字符上限。
- `LLM_AUDIT_ENABLED`：是否写入脱敏后的 provider 请求级可观测事件，默认开启；事件不保存 prompt、响应正文、异常原文、API key 或 endpoint。
- `LLM_OBSERVABILITY_WINDOW_MINUTES`、`LLM_OBSERVABILITY_MINIMUM_REQUESTS`、`LLM_ERROR_RATE_ALERT_THRESHOLD`、`LLM_TIMEOUT_RATE_ALERT_THRESHOLD`：最近窗口、触发告警所需最小请求数，以及错误率/超时率阈值。两个比率阈值取值 `0..1`。
- `LLM_OBSERVABILITY_QUEUE_CAPACITY`、`LLM_OBSERVABILITY_SHUTDOWN_TIMEOUT_SECONDS`：provider 事件后台队列容量和 API 正常关闭时 drain/close 的最长等待秒数；默认分别为 `256`、`2`。
- `LLM_OBSERVABILITY_RETENTION_DAYS`：provider 可观测事件保留天数，默认 `30`。可用 `python scripts/cleanup_llm_provider_events.py --json-report-path output/checks/llm-provider-events-cleanup.json` 预览，确认后加 `--apply` 执行删除。
- `LLM_ALERT_WEBHOOK_URL`、`LLM_ALERT_COOLDOWN_MINUTES`、`LLM_ALERT_TIMEOUT_SECONDS`：可选的 LLM 阈值外部告警 webhook、同一 provider/model/告警类型的重复通知冷却分钟数和投递超时秒数。webhook URL 只接受无凭据、无 query/fragment 的 HTTP(S) URL；投递 payload 只包含净化后的 provider/model、窗口聚合指标、阈值、`triggered/recovered` 动作和时间戳，不包含事件明细、prompt、响应正文、异常原文、endpoint 或 API key。
- `FUND_DATA_SOURCE`、`FUND_DATA_STALE_DAYS`：数据源 adapter 与数据新鲜度配置。
- `FUND_NAV_VALUE_MIN` / `FUND_NAV_VALUE_MAX`、`FUND_ACCUMULATED_NAV_VALUE_MIN` / `FUND_ACCUMULATED_NAV_VALUE_MAX`：单位净值与累计净值的正数异常告警区间；默认只告警。`FUND_NAV_REJECT_ANOMALIES=true` 时，任一越界值会让整次净值同步失败并回滚。
- `FUND_SNAPSHOT_MIN_FUND_COUNT`、`FUND_SNAPSHOT_MIN_NAV_COVERAGE_RATIO`、`FUND_SNAPSHOT_MAX_LATEST_NAV_AGE_DAYS`、`FUND_SNAPSHOT_MAX_FUND_COUNT_DROP_RATIO`、`FUND_SNAPSHOT_QUALITY_OVERRIDES`：完整快照晋升前的业务完整性阈值，可按真实 provider source 覆盖；失败时旧 active generation 继续可见。
- `PUBLIC_FUND_DATA_BASE_URL`、`PUBLIC_FUND_DATA_PROFILE`、`PUBLIC_FUND_DATA_TIMEOUT_SECONDS`、`PUBLIC_FUND_DATA_CACHE_DIR`、`PUBLIC_FUND_DATA_MIN_INTERVAL_SECONDS`、`PUBLIC_FUND_DATA_BATCH_SIZE`、`PUBLIC_FUND_DATA_MAX_PAGES`、`PUBLIC_FUND_DATA_PROXY_URLS`：公开 JSON 数据源地址、字段 profile、超时、条件缓存、限速、分页上限和可选的运维代理池。代理池只接受你明确配置的 HTTP(S) 代理，按请求轮换；系统不会自动发现公共代理或用轮换规避上游限流。默认 `generic_aliases_v1` 保持旧别名兼容；标准镜像可选 `normalized_v1`，东方财富审计镜像使用 `eastmoney_snapshot_v1`。分页 `next` 必须保持同源，默认最多读取 100 页。

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

### Linux/macOS 用法（make）

Windows 继续使用上面的 `scripts/*.ps1` 入口；Linux/macOS 上仓库根提供等价的 `Makefile`，统一通过仓库根 `.venv` 调用，无需手动激活虚拟环境：

```bash
make install        # npm install + 把 apps/api[dev] 装进 .venv
make migrate        # alembic upgrade head（在 apps/api 下执行）
make seed           # 幂等写入 sample 基金数据
make test           # 后端 pytest 套件
make lint           # ruff check（锁定 0.14.9）
make mypy           # mypy --strict
make connectivity   # AKShare 上游连通性烟雾测试
make sync-eastmoney # 把 EastMoney 审计快照拉进本地 SQLite
make smoke          # 对本地 :8000 API 跑 /health 与 /api/data/status
make dev-api        # 启动 FastAPI 开发服务器
```

如需自定义 Python 解释器路径，可覆盖 `PYTHON` 变量，例如 `make test PYTHON=/path/to/bin/python`。

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
.\scripts\db-migrate.ps1 -Command current -DryRun -JsonReportPath ".\output\checks\migration-report.json"
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

生产或预发布环境必须同时声明实际 Web Origin，配置错误会让 API 在启动时直接失败，避免部署后只在浏览器中表现为泛化网络错误。例如：

```powershell
$env:APP_ENVIRONMENT = "production"
$env:WEB_ORIGIN = "https://fund.example.com:8443"
$env:CORS_ORIGINS = "https://fund.example.com:8443"
npm.cmd run dev:api
```

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

脚本当前会验证 `/health`、`/api/data/status` 和 `/api/funds/filter` 的基础 envelope。`-RequireFresh` 会要求数据状态为 `fresh`，`-JsonReportPath` 会记录 schema 版本、运行环境、OpenAPI 文件信息、每一步耗时、成功/失败状态和数据摘要。空库触发 `-SeedIfEmpty` 时，生产 seed 入口会把 sample 的 `data_updated_at` 设为本次运行时间，因此固定教学 fixture 不会因自然时间流逝导致新建 smoke 环境立即 stale；这不降低非 sample 数据的 freshness 要求。也可以手动执行同等请求：

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

生成已验收的东方财富静态快照镜像（只生成标准 `public_http_json` 文件，不直接写数据库）：

```powershell
python scripts/build_eastmoney_mirror.py --fund-code 000001 --output-dir output/eastmoney-mirror
```

通过静态 HTTP 服务暴露生成目录后，读取该镜像时设置：

```powershell
$env:FUND_DATA_SOURCE = "public_http_json"
$env:PUBLIC_FUND_DATA_BASE_URL = "http://127.0.0.1:9000/"
$env:PUBLIC_FUND_DATA_PROFILE = "eastmoney_snapshot_v1"
```

如需为自动同步配置 IP 轮换，请只填入你自己管理、已获授权的 HTTP(S) 代理：

```powershell
$env:PUBLIC_FUND_DATA_PROXY_URLS = "http://proxy-a.example:8080,http://proxy-b.example:8080"
```

每次上游请求按列表轮询代理；同步任务本身还会在计划时间上随机错峰 `0-120` 秒。系统不会自动寻找公共代理或伪造“最新数据”：如果上游仍返回旧快照，页面会继续显示真实的过期状态。

基金 API 会保留 `source=eastmoney_snapshot`、`provider_profile=eastmoney_snapshot_v1` 和 `upstream_provider=eastmoney`，而不是把上游统一折叠成 `public_http_json`。

真实数据源的净值日期必须是完整 ISO `YYYY-MM-DD`；`sample_local` 的 `YYYY` 年度点继续保留，供遗留样本回测使用。迁移 `0007_add_nav_trade_date_precision` 只增加并回填 `day/year/unknown` 精度标记，不改写现有 `trade_date`，因此升级与回滚不会把用户库中的年份字符串猜测为某个交易日。

迁移 `0008_add_snapshot_generation` 为基金资料、净值和指标增加 generation，并用单例 active 指针完成原子晋升。`sync_all` 以及手动 `profiles/navs/metrics/risk_levels` 兼容入口都会执行完整 `fetch_snapshot`；后四者的返回中会标记 `effective_scope=full_snapshot`。候选写入、行数/父子一致性校验和 active 切换位于同一事务，失败时旧 generation 保持可见。

迁移 `0009_add_llm_provider_events` 增加 LLM provider 请求级可观测事件。一次 provider 请求只记录一行安全元数据：净化后的 provider/model、成功或回退结果、尝试/重试次数、总延迟、是否经历超时和白名单错误类别。主路径只向固定容量队列执行非阻塞入队，单个 daemon worker 才获取数据库连接并提交；队列满、写库失败或关闭超时只记安全汇总日志。worker 意外退出时在同一 dispatcher 和同一容量队列上受控重启；API 正常关闭时按配置上限 drain/close，并在超时后丢弃尚未开始处理的队列遗留事件，因此锁等待、慢 commit 或异常恢复不会增加聊天返回时延。

`GET /api/settings/runtime` 只聚合当前净化后的 provider/model。`request_count` 排除未发起网络请求的 `config_missing`；本地 `policy_rejected` 表示 transport 成功，不计 provider 基础设施错误。`retry_count` 是窗口内重试总次数，`retry_rate` 是发生过至少一次重试的请求占比。HTTP 400/401/403、无效 base URL、本地无效响应、响应 body 超限和输出长度超限不重试；timeout/network、408、429、5xx/504 可重试。429/503 的 `Retry-After` 支持秒数和 HTTP-date，两者都会受 2 秒上限约束并叠加轻量随机抖动。跨源 provider 重定向会被阻断，避免 `Authorization` 发送到非预期 origin。

当配置 `LLM_ALERT_WEBHOOK_URL` 后，runtime observability 聚合会按当前窗口告警状态投递最小化 JSON 通知。同一 provider/model/告警类型在冷却期内只重复通知一次；告警消失后发送 `recovered` 通知。投递失败只记录安全日志，不会把失败状态写入冷却窗口，下一次聚合仍可重试。

异常阈值可以按上游口径调整。零、负数、`NaN` 和无穷值始终作为无效合同拒绝；正数越界默认写入同步任务 `quality_warnings` 并保存在净值 `raw_data`，仅在显式开启拒绝模式时回滚整次净值同步：

```powershell
$env:FUND_NAV_VALUE_MIN = "0.01"
$env:FUND_NAV_VALUE_MAX = "100"
$env:FUND_ACCUMULATED_NAV_VALUE_MIN = "0.01"
$env:FUND_ACCUMULATED_NAV_VALUE_MAX = "1000"
$env:FUND_NAV_REJECT_ANOMALIES = "false"
```

逐字段口径、来源 URL、限频与失败回退边界见 `docs/数据源接入方案.md` 的 `eastmoney_snapshot_v1` 小节。

调度器默认启用，每 5 分钟自动拉取一次完整基金数据；也可选择 interval 或五段 cron，并配置错峰与运行锁超时：

```powershell
FUND_SYNC_SCHEDULER_ENABLED=true
FUND_SYNC_SCHEDULE_MODE=interval
FUND_SYNC_INTERVAL_MINUTES=5
FUND_SYNC_JITTER_SECONDS=120
FUND_SYNC_MISFIRE_GRACE_SECONDS=900
FUND_SYNC_LOCK_TIMEOUT_MINUTES=120
```

运行状态可通过 `GET /api/data/scheduler/status` 或设置页查看。同名任务并发会返回 `409 DATA_SYNC_ALREADY_RUNNING`，不会启动第二个写库任务。

## 质量检查

```powershell
python -m pytest apps/api/app/tests
python -m ruff check apps/api/app
python -m mypy apps/api/app --strict
.\scripts\check-compliance-text.ps1
npm.cmd run lint:web
npm.cmd --workspace apps/web exec tsc -- --noEmit
npm.cmd run test:web
npm.cmd run build:web
npm.cmd run e2e:web
npm.cmd run e2e:web:real
```

`e2e:web` 运行 mocked API 主路径；`e2e:web:real` 会创建隔离的 SQLite 数据库、执行 Alembic 迁移与 sample seed，并启动真实 FastAPI + Next.js 联调项目。Windows 启动器在未传端口时会为 Web/API 自动选择不同的空闲端口；显式传入的端口若已占用会立即失败，真实 API 模式也会拒绝相同的 Web/API 端口。可按需固定端口，例如 `scripts/run-web-e2e.ps1 -WebPort 3101` 或 `scripts/run-real-api-e2e.ps1 -WebPort 3101 -ApiPort 8101`。

启动器会等待端口就绪、使用隐藏窗口，并在结束时清理完整进程树。每次运行的服务 stdout/stderr 会分别保留在 `output/playwright/service-logs/`，包含实际端口、日志路径、状态和失败原因的启动汇总保存在 `output/playwright/*-e2e-launcher-*.json`。真实 API E2E 成功后还会校验 `output/playwright/real-api-visual-check.json`，并把报告路径与合同状态写入启动汇总。无需启动服务即可检查端口与报告合同：

```powershell
.\scripts\check-playwright-launcher-contract.ps1
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
.\scripts\collect-artifacts.ps1
.\scripts\collect-artifacts.ps1 -RequireArtifacts "output/checks/openapi.diff","output/smoke/*.json","output/playwright/*.png"
.\scripts\collect-artifacts.ps1 -Profile local-release
```

OpenAPI drift Markdown 摘要会同时列出 operation、响应码、必填参数、schema 字段、字段定义和 required 变化；`scripts/check-openapi-diff-summary.ps1` 使用固定 before/after fixture 校验摘要合同及审批拒绝路径。存在 drift 时，门禁要求 `packages/contracts/openapi-change-approval.json` 同时绑定 Git 基线 blob、导出合同/diff/摘要三份 SHA-256，并提供审阅人、日期、理由、非空变更清单和 `breaking_hints_reviewed=true`；合同与 `HEAD` 一致时无需审批清单。任何绑定内容变化都必须重新审阅，不能只刷新哈希。

`release-notes-snippet.md` 当前是完整发布说明模板，包含发布元数据、变更摘要、验证证据、数据/API、合规、部署回滚、已知限制和审批清单；无法由 manifest 推导的事实保留显式 `TODO`。`scripts/check-release-notes-template.ps1` 会生成 fixture 包并验证必需章节。

发布前最小检查顺序：

1. `.\scripts\check-all.ps1 -CheckOpenApiDrift -OpenApiDiffPath ".\output\checks\openapi.diff"`
2. `.\scripts\smoke-api.ps1 -SeedIfEmpty -RequireFresh -JsonReportPath ".\output\smoke\api-smoke.json"`
3. `.\scripts\verify-docker-compose.ps1`
4. `.\scripts\collect-artifacts.ps1 -Profile local-release -FailOnAlerts`

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
- [docs/合规边界.md](docs/合规边界.md)：禁止输出、推荐表达、回测和 AI 合规边界。
- [docs/待完成与版本任务规划.md](docs/待完成与版本任务规划.md)：当前状态、已完成历史合并、剩余待办和发布验收入口。
### AKShare 数据源连通性检查

项目提供独立的 AKShare 烟雾测试，不直接把不稳定的第三方请求放进事务快照。安装 API 依赖后运行：

```powershell
python scripts/verify_akshare.py --fund 000001 --stock 600036
```

脚本兼容 AKShare 新旧基金净值函数名，会校验基金日净值、历史净值和 A 股日线，并将结果写入 `output/akshare-smoke.json`。成功后再将经过审计的 JSON 快照接入现有 `public_http_json` adapter。

### SQLite 本地业务库

开发环境默认使用 `output/dev/fund.db`，Alembic 会将全部业务表迁移到 SQLite。使用下面的命令迁移到最新版本，并从 EastMoney 拉取基金 `000001` 的真实资料、指标和历史净值后原子写入 SQLite：

```powershell
pwsh.exe -ExecutionPolicy Bypass -File scripts/db-migrate.ps1 -DatabaseUrl "sqlite:///./output/dev/fund.db"
python scripts/sync_sqlite_data.py --fund-code 000001
```

不传 `--fund-code` 时会从 AKShare 的开放式基金排名中发现基金并默认写入 10 只满足 3/5 年历史指标要求的基金；也可重复传入多个 `--fund-code` 精确同步。同步失败时不会晋升不完整快照，数据库保留上一代可用数据。

使用上游快照运行本地 API 时请设置 `FUND_SYNC_SCHEDULER_ENABLED=false`，避免调度器用 sample 数据覆盖手动拉取的上游快照；生产环境可保持启用。
