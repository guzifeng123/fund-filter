# API 接口说明

本项目 API 合同以两份文件为准：

- 手写摘要：[packages/contracts/api-contract.md](../packages/contracts/api-contract.md)
- 机器可校验 OpenAPI：[packages/contracts/openapi.json](../packages/contracts/openapi.json)

导出命令：

```powershell
python scripts/export_openapi.py
```

也可以通过 npm workspace 根脚本执行：

```powershell
npm.cmd run export:openapi
```

## 维护规则

- 新增或修改后端路由后，必须运行 `python scripts/export_openapi.py`。
- 手写摘要只记录前端和开发者最常看的字段、示例和合规约束。
- OpenAPI JSON 来自 FastAPI app 的实际路由，是检查路径、参数、请求体和响应模型是否漂移的基准。
- sample 数据源、mock LLM 或降级返回仍需在接口摘要中标注当前能力边界。
- `check-all.ps1 -CheckOpenApiDrift` 的 Markdown 摘要必须覆盖 operation、响应码、必填参数、schema 字段定义、required 和校验约束变化；新增必填字段/参数、删除字段/operation/响应码、类型变化及 min/max/enum 等约束收紧要进入 breaking hints。

## OpenAPI 变更审批

`check-all.ps1 -CheckOpenApiDrift` 在导出合同与 Git `HEAD` 一致时直接通过；存在 drift 时，必须同时提交并审阅 [packages/contracts/openapi-change-approval.json](../packages/contracts/openapi-change-approval.json)。审批清单绑定以下不可混用的标识：

- `baseline.contract_blob`：`HEAD:packages/contracts/openapi.json` 的 Git blob ID，不是文件 SHA-256。
- `approved_export_sha256`：本次导出后 `openapi.json` 的 SHA-256。
- `approved_diff_sha256`：原始 Git diff 产物的 SHA-256。
- `approved_summary_sha256`：字段级 Markdown 变更摘要的 SHA-256。

审批还必须提供审阅人、`yyyy-MM-dd` 日期、理由、非空 `change_list`，并显式设置 `breaking_hints_reviewed=true`。基线变化、导出/差异/摘要任一内容变化、未确认 breaking hints 或缺失审阅信息都会使发布门禁失败；更新哈希前必须重新审阅对应产物，不能只机械刷新清单。

## 基金筛选请求边界

- `GET /api/funds/search` 用于一般搜索浏览；调用方未显式传 `risk_level` 时可能返回超出用户风险画像的基金，前端必须展示风险不匹配提示。
- 基金筛选页统一调用 `POST /api/funds/filter`。可选 `keyword` 与有效 `risk_profile`、基金类型、成立年限、规模、收益分位、回撤、夏普、费用和排序在同一次服务端查询中执行；输入关键词不得退回 `GET /search` 或当前页数组过滤。

## 数据状态快速降级

`GET /api/data/status` 使用独立数据库 Session，并受 `DATA_STATUS_TIMEOUT_SECONDS` 控制，默认上限为 `2.5` 秒。
数据库不可用或检查超时时仍返回 `200` envelope，其中 `db_connected=false`、`freshness_status=empty`；该返回只表示当前无法确认数据库状态，不表示已有数据被删除。

数据状态和基金接口的 `meta.source` 从数据库基金记录聚合：单一来源返回原值，多来源返回 `mixed(source_a,source_b)`；数据库不可用时返回 `unavailable`，不得固定声称为 `sample_local`。`data.source` 与数据状态接口的 `meta.source` 使用同一口径。

所有 envelope 的 `meta.data_updated_at` 只表示可从持久化业务数据推导出的更新时间；无法推导时返回 `null`。禁止用 API 响应时间填充该字段，以免前端把“刚响应”误解为“数据刚更新”。前端必须以“时间未知/暂无日期”等文案降级展示。

基金搜索、筛选、比较、详情和净值接口在 repository 层先解析一次基金数据 generation，并用同一上下文生成 payload、`meta.source` 和 `meta.data_updated_at`。`Fund` / `FundDetail` 中的 `snapshot_generation_id` 表示该次读取使用的基金快照 generation。

## 数据同步原子边界

`POST /api/data/sync?task=all|profiles|navs|metrics|risk_levels` 的五个 task 值都执行完整快照原子晋升。后四个值仅为兼容既有调用方和任务名称，不再对 active generation 做局部原地修改。

成功结果的 `result` 至少包含：

- `requested_task`：调用方请求的 task。
- `effective_scope=full_snapshot`：实际执行完整 `fetch_snapshot`。
- `generation_boundary=atomic_promotion`。
- `snapshot_generation_id` / `previous_snapshot_generation_id`。
- `fund_count` / `nav_count` / `metric_count`。

候选 generation 在同一数据库事务中写入，经过行数与父子 generation 一致性校验后才更新单例 active 指针。任何 adapter、质量校验、写库、计数或晋升后异常都会回滚候选，旧 generation 继续对基金、净值、回测和数据状态读取可见。

## 组合不可用持仓边界

组合读取合同必须保留用户已经保存、但不再属于 active 基金快照的持仓：

- 组合列表与详情都必须返回非负整数 `unavailable_position_count`。
- 详情中的每条 `positions[]` 都必须返回布尔值 `available`；基金仍属于 active generation 时为 `true`，否则为 `false`。
- 详情中的每条 `positions[]` 都必须返回结构化 `availability_reason`：`available` 或 `removed_from_active_snapshot`。
- 不可用持仓不是自动删除信号。`DELETE /api/portfolios/{id}/positions/{fund_code}` 仍可删除它；新增或更新持仓只接受当前 active 基金。
- 只要存在不可用持仓，`POST /api/portfolios/{id}/positions/normalize` 与 `POST /api/portfolios/{id}/rebalance-preview` 都返回 `409`，错误码固定为 `PORTFOLIO_HAS_UNAVAILABLE_POSITIONS`，不得沿用最后一版基金分类计算比例。
- 上述 `409` 的 `error.detail` 必须是结构化对象：`{ "availability_reason": "removed_from_active_snapshot", "unavailable_fund_codes": ["000001"] }`。客户端不得解析英文异常字符串判断业务状态。

`available`、`availability_reason` 与 `unavailable_position_count` 是基于 active generation 派生的 API 字段，不是 `portfolio_positions` 数据库列。

## 回测收益口径

`POST /api/backtests` 与 `GET /api/backtests/{id}` 的结果同时返回 `money_weighted_return` 与 `time_weighted_return`。`annualized_return` 继续等同主口径 `money_weighted_return`，即按每笔历史现金流日期和期末市值计算的 XIRR；`time_weighted_return` 会剔除中途投入影响，用于观察资产本身在历史区间的年化表现。`return_calculation_method=xirr|unavailable` 描述主收益口径是否可用。结果中的 `snapshot_generation_id` 会持久化到 `backtest_runs.result_snapshot`，`GET /api/backtests/{id}` 按该 generation 返回来源和更新时间 meta，而不是按查询时最新 active generation 重标。前端必须同屏说明 XIRR 与 TWR 差异，且不得把任一历史收益字段表达为未来收益预测。

## LLM Provider 可观测性

`GET /api/settings/runtime` 的 `data.llm.observability` 是公开安全的最近窗口摘要，包含：

- `status`：`disabled`、`unavailable`、`insufficient_data`、`ok` 或 `alert`。
- `request_count` / `request_rate_per_minute` / `retry_count`。
- `success_rate` / `error_rate` / `retry_rate` / `timeout_rate`。
- `alerts`：仅可能包含 `error_rate`、`timeout_rate`。
- 当前窗口、最小样本数、两个告警阈值和最近事件时间。
- `dispatcher`：后台写入队列的安全聚合健康摘要，包含 `status=disabled|not_started|ok|degraded`、`worker_count`、`pending_count`、`capacity`、`dropped_count`。

provider 事件为请求级聚合，一次调用只写一行。只允许保存净化后的 provider/model、结果、尝试/重试次数、总延迟、超时标记、白名单错误类别和调用完成时间；不得保存用户问题、RAG 依据、模型回答、异常原文、URL、API key、token 或 credential。主路径只做固定容量队列的非阻塞入队，连接获取、锁等待与 commit 在单一 daemon worker 中执行；队列满、写失败、worker 意外退出或关闭超时只记安全汇总日志，不含 provider/model 明细。worker 异常退出后只能在同一 dispatcher 的同一有界队列上受控重启，关闭超时后只能丢弃尚未开始处理的队列遗留事件并计数，不能回到聊天请求线程写库，也不能创建无界线程或队列。worker 必须原样保存事件发生时间，不能用实际落库时间替代。

`LLM_PROVIDER` 的重试策略支持 `Retry-After` 的秒数和 HTTP-date 两种格式，并在上限内加入轻量随机抖动；`429` 与 `503` 的限流/服务不可用响应可复用该头部，其余错误仍按默认指数退避处理。`LLM_BASE_URL` 必须是无凭据、无 query/fragment 的 HTTP(S) 服务根地址，不允许直接配置 `/chat/completions` 端点；真实 provider 响应受 `LLM_MAX_RESPONSE_BYTES` 和 `LLM_MAX_OUTPUT_CHARS` 双上限约束。跨源 provider 重定向会被阻断，避免 `Authorization` 被发送到非预期 origin。

`LLM_OBSERVABILITY_RETENTION_DAYS` 控制 provider 事件保留天数，默认 30 天。`python scripts/cleanup_llm_provider_events.py --json-report-path output/checks/llm-provider-events-cleanup.json` 默认只做 dry-run 并输出聚合报告；确认后加 `--apply` 才删除旧事件。清理报告不得包含 provider/model 明细、prompt、响应或异常原文。

摘要只统计当前净化后的 provider/model，且 `request_count` 排除 `attempt_count=0/config_missing`。`policy_rejected` 表示 provider transport 已成功，只是本地合规层回退，不进入基础设施 `error_rate`；`retry_count` 是重试总次数，`retry_rate` 是发生过重试的请求占比。告警只在有效 provider 请求达到 `minimum_requests` 后评估。

## 生产 CORS 启动合同

- `APP_ENVIRONMENT=staging|production` 时，`CORS_ORIGINS` 与 `WEB_ORIGIN` 必须显式设置。
- `WEB_ORIGIN` 必须与白名单中的一项标准化后完全一致，包括非默认端口。
- Origin 只允许 HTTP(S) 协议、主机和可选端口；通配符、路径、查询、fragment 或内嵌凭据会让 API 启动直接失败。
- 开发/测试可使用默认本地来源；E2E 启动器会把动态 Web 端口同步注入 CORS。
