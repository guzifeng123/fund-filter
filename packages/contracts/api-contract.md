# API Contract

The API uses a uniform success envelope:

```json
{
  "data": {},
  "meta": {
    "source": "sample_local",
    "data_updated_at": "2026-07-08T20:30:00+08:00",
    "disclaimer": "本工具基于历史数据，仅供分析学习，不构成投资建议。历史表现不预示未来收益。"
  }
}
```

Errors use a uniform envelope:

```json
{
  "error": {
    "code": "VALIDATION_ERROR",
    "message": "请求参数不符合接口要求",
    "detail": []
  },
  "meta": {
    "source": "sample_local",
    "data_updated_at": null,
    "disclaimer": "本工具基于历史数据，仅供分析学习，不构成投资建议。历史表现不预示未来收益。"
  }
}
```

Frontend pages must call `apps/web/src/lib/api/client.ts` instead of using `fetch` directly.

## Common Meta

- `source`: data-backed fund/status routes aggregate actual persisted sources; a single source is returned directly, multiple sources use `mixed(source_a,source_b)`, and unavailable status uses `unavailable`.
- `data_updated_at`: latest available data timestamp when the route can derive it from persisted data; otherwise `null`. Response time must never be presented as data time.
- `disclaimer`: compliance disclaimer.
- `pagination`: optional `{ "page": 1, "page_size": 20, "total": 4 }` on paginated routes.

## Dashboard

`GET /api/dashboard`

The dashboard returns persisted risk assessment, data freshness, and the most recent `job_runs` row in one response. It does not synthesize watchlist, alert, or portfolio-health results while those capabilities have no backing data model.

Key fields:

- `risk_status`: `not_assessed`, `valid`, `expires_soon`, or `expired`.
- `portfolio_health_status`: currently `unavailable`; legacy `health` remains `unavailable` for compatibility.
- `watchlist_status`: currently `not_configured`; `watchlist_updated_at` is `null` rather than a fabricated timestamp.
- `alerts_status`: currently `not_configured`; `alerts` is empty rather than containing synthetic sync or rebalance messages.
- `data_status`: the same persisted counts, source, freshness, and last-job view used by the data-status repository.
- `recent_job`: the latest full job summary, or `null` when no task has run.

The response `meta.source` and `meta.data_updated_at` are copied from `data_status`, so the dashboard never labels real data with a fixed source or response-time placeholder.

## Runtime Settings

`GET /api/settings/runtime`

Returns a read-only, public-safe configuration summary:

- `data_source`: configured adapter name/profile, persisted actual source summary, and readiness boolean. `configured_profile` is only populated for `public_http_json` and contains no endpoint or credential data.
- `llm`: safe provider/model names, whether the provider is usable, whether it is the local mock path, and a public-safe `observability` summary.
- `yingmi_mcp`: endpoint-configured boolean and implementation boolean. The endpoint itself is never returned.
- `risk_assessment.validity_months`: current risk-assessment validity period.
- `cleanup`: manual-script method, dry-run support, and automatic-cleanup support.

The response schema deliberately has no database URL, CORS allowlist, API key, token, credential, filesystem path, or LLM/MCP service endpoint field. Configuration remains server-side and the Web page is read-only.

`llm.observability` reports `disabled`, `unavailable`, `insufficient_data`, `ok`, or `alert`; the configured recent window and minimum sample size; request count/rate and total retry count; success, infrastructure-error, retried-request, and timeout rates; threshold values; active `error_rate` / `timeout_rate` alerts; and the latest event timestamp. Metrics only include the current sanitized provider/model and requests with at least one network attempt. `config_missing` is excluded; `policy_rejected` counts as transport success. Provider/model labels that resemble keys, tokens, JWTs, URLs, bare hostnames/host:port values, or credentials are returned as `unknown`. No prompt, response, raw exception, URL, endpoint, or credential is exposed.

## Health

`GET /health`

Returns a plain health object:

```json
{ "status": "ok" }
```

## Data Status

`GET /api/data/status`

Success data:

```json
{
  "db_connected": true,
  "source": "sample_local",
  "fund_count": 4,
  "nav_count": 24,
  "latest_data_updated_at": "2026-07-08T20:30:00",
  "freshness_status": "fresh",
  "stale_after_days": 7,
  "last_job": {
    "name": "seed_sample_data",
    "status": "success",
    "finished_at": "2026-07-08T20:31:00",
    "error_detail": null
  }
}
```

`freshness_status` is one of:

- `empty`: funds or NAV rows are empty.
- `fresh`: data exists and is within `stale_after_days`.
- `stale`: latest fund data is older than `stale_after_days`.
- `failed`: the latest job run failed.

When the database is unavailable, this route returns `200` with `db_connected=false` and `freshness_status=empty`.
The database check is isolated in its own session and has a request-level timeout controlled by
`DATA_STATUS_TIMEOUT_SECONDS` (default `2.5`). A timed-out connection check may finish in the
background, but it does not delay the response or reuse the request's session.

### Recent Data Jobs

`GET /api/data/jobs/recent?limit=10`

Success data:

```json
[
  {
    "id": 1,
    "name": "seed_sample_data",
    "status": "success",
    "started_at": "2026-07-08T20:30:00",
    "finished_at": "2026-07-08T20:31:00",
    "error_detail": null,
    "details": { "fund_count": 4 }
  }
]
```

`status` is one of `running`, `success`, `failed`.

### Manual Sync

`POST /api/data/sync?task=all`

Supported task values:

- `all`
- `profiles`
- `navs`
- `metrics`
- `risk_levels`

All task values now share the same atomic snapshot boundary. `profiles`, `navs`, `metrics`, and `risk_levels` are compatibility aliases: each performs one complete `fetch_snapshot`, checks snapshot-level quality thresholds, writes profile/NAV/metric rows under one staging generation, validates counts and parent/child generation consistency, and promotes only in the final transaction step. A successful result includes `requested_task`, `effective_scope=full_snapshot`, `generation_boundary=atomic_promotion`, `snapshot_generation_id`, `previous_snapshot_generation_id`, the three row counts, and `snapshot_quality_thresholds`. Any failure leaves the previous active generation visible.

Each task writes to `job_runs`. Scheduler configuration is environment based and disabled by default:

```powershell
FUND_SYNC_SCHEDULER_ENABLED=false
FUND_SYNC_SCHEDULE_MODE=interval
FUND_SYNC_INTERVAL_HOURS=24
FUND_SYNC_CRON=15 2 * * *
FUND_SYNC_JITTER_SECONDS=300
FUND_SYNC_MISFIRE_GRACE_SECONDS=900
FUND_SYNC_LOCK_TIMEOUT_MINUTES=120
```

- `GET /api/data/scheduler/status` returns configured mode/expression, timezone, jitter, misfire grace, next run time, process state, and database-visible running tasks.
- `FUND_SYNC_SCHEDULE_MODE=cron` uses a standard five-field expression in `FUND_SYNC_CRON`; `interval` uses `FUND_SYNC_INTERVAL_HOURS`.
- A partial unique index allows only one `job_runs.status=running` row per task name. Overlap returns `409 DATA_SYNC_ALREADY_RUNNING`; locks older than the configured timeout are failed before a new run starts.
- Alembic `0008_add_snapshot_generation` stores the singleton active pointer. Fund search/filter/compare/detail/NAV routes resolve one generation context per repository read and use that same context for payload, `meta.source`, and `meta.data_updated_at`. Backtest calculation resolves one generation before loading NAVs and persists that generation in the result snapshot.
- Snapshot promotion guardrails are configured by `FUND_SNAPSHOT_MIN_FUND_COUNT`, `FUND_SNAPSHOT_MIN_NAV_COVERAGE_RATIO`, `FUND_SNAPSHOT_MAX_LATEST_NAV_AGE_DAYS`, `FUND_SNAPSHOT_MAX_FUND_COUNT_DROP_RATIO`, and optional JSON `FUND_SNAPSHOT_QUALITY_OVERRIDES` keyed by adapter source or persisted fund source. Threshold failures reject the sync before candidate rows are written and record the reason in the failed `job_runs.details.error`.

## Funds

### Search

`GET /api/funds/search`

Query parameters:

- `q`: optional code/name keyword.
- `page`: default `1`, minimum `1`.
- `page_size`: default `20`, range `1..100`.
- `fund_type`: repeatable, one of `stock`, `mixed`, `bond`, `money`.
- `risk_level`: repeatable, one of `R1`..`R5`.
- `sort_by`: `code`, `annualized_return_3y`, `annualized_return_5y`, `max_drawdown`, `sharpe_ratio`, `fee`, `size`.
- `sort_order`: `asc` or `desc`.

Success data: `Fund[]`, with `meta.pagination`.

Each fund exposes provenance independently from the envelope: `source` is the stable persisted source (for example `public_http_json` or `eastmoney_snapshot`), `provider_profile` identifies the normalization contract, `upstream_provider` identifies a known final upstream such as `eastmoney`, and `snapshot_generation_id` identifies the active fund-data generation used by the read. Generic/normalized mirrors may return `upstream_provider=null`.

This endpoint is a general browsing/search contract. Unless callers explicitly pass `risk_level`, results may include funds above a user's effective risk profile and the UI must label that mismatch. The fund-filter page must use `POST /api/funds/filter` when keyword browsing is combined with its applied four-step criteria.

### Filter

`POST /api/funds/filter`

Request:

```json
{
  "keyword": "稳健",
  "risk_profile": "C3",
  "fund_types": ["mixed", "bond"],
  "min_years": 3,
  "size_range": [0, 500],
  "return_rank_percentile": 50,
  "max_drawdown_lte_category_avg": true,
  "sharpe_gte": 0.8,
  "fee_lte": 1.5,
  "sort_by": "annualized_return_3y",
  "sort_order": "desc"
}
```

Success data: `Fund[]`. Funds above the user's risk profile are excluded.

Filter semantics:

- `keyword` is optional. After surrounding whitespace is removed, a non-empty value is matched case-insensitively against fund code or name in the same database query as every criterion below. Omitting it or sending only whitespace applies no keyword restriction.
- `risk_profile` is always applied to the database query. Supplying `keyword` does not switch to the unrestricted search contract and does not permit funds above the effective risk profile.
- `min_years` means completed years since `funds.inception_date`, evaluated against the API processing date. The repository converts it to an inclusive inception cutoff (`inception_date <= cutoff`); when subtracting years from February 29 into a non-leap year, the cutoff is February 28. It does not use fund-manager tenure.
- `max_drawdown_lte_category_avg=false` does not apply a category-drawdown filter.
- When `max_drawdown_lte_category_avg=true`, the category average is calculated across persisted funds with metrics and the same `fund_type`. Maximum drawdown is stored as a signed negative percentage, so “loss magnitude no worse than the category average” is implemented as `fund.max_drawdown >= category_average`. The legacy field name uses `lte` for drawdown magnitude, not for the signed stored number.

### Detail

`GET /api/funds/{code}?risk_profile=C3`

Query parameters:

- `risk_profile`: optional, one of `C1`..`C5`, default `C3`.

Success data: `FundDetail`, including:

- `navs`: historical NAV points.
- `ai_summary`: sample AI summary placeholder.
- `fee_summary`: management fee, custody fee, total fee, and explanation.
- `manager_profile`: manager name, years, inception date, and explanation.
- `metric_explanations`: centralized metric explanation entries.
- `risk_match`: risk-profile match result and non-directive message.

Errors:

- `404 FUND_NOT_FOUND`

### NAV

`GET /api/funds/{code}/nav?start=2023&end=2025`

`start` and `end` are optional string bounds compared against `trade_date`. Current sample data uses year strings; future real data can use ISO dates.

Success data: `NavPoint[]`.

Errors:

- `400 INVALID_DATE_RANGE`
- `404 FUND_NOT_FOUND`

### Compare

`POST /api/funds/compare`

Request:

```json
{ "codes": ["000001", "000002"] }
```

Request contract: `codes` must contain 2-5 entries. Success data preserves requested code order for existing funds.

## Risk

### Questions

`GET /api/risk-assessments/questions`

Success data: 6 questions, each with 5 scored options.

### Latest

`GET /api/risk-assessments/latest`

Success data is `RiskAssessmentResult | null`:

```json
{
  "risk_profile": "C3",
  "score": 18,
  "effective_from": "2026-07-08",
  "effective_to": "2027-07-08",
  "expires_soon": false,
  "is_expired": false,
  "explanation": "稳健型，可接受适度波动，适合均衡配置。"
}
```

### Submit

`POST /api/risk-assessments`

Request:

```json
{
  "answers": [
    { "question_id": "horizon", "score": 3 },
    { "question_id": "drawdown_tolerance", "score": 3 },
    { "question_id": "income_stability", "score": 3 },
    { "question_id": "investment_experience", "score": 3 },
    { "question_id": "liquidity_need", "score": 3 },
    { "question_id": "goal_priority", "score": 3 }
  ]
}
```

The result is persisted to `risk_assessments`. Validity is 12 months.

## Portfolios

- `GET /api/portfolios/templates`
- `GET /api/portfolios`
- `POST /api/portfolios`
- `GET /api/portfolios/{portfolio_id}`
- `PATCH /api/portfolios/{portfolio_id}`
- `DELETE /api/portfolios/{portfolio_id}`
- `PUT /api/portfolios/{portfolio_id}/positions`
- `DELETE /api/portfolios/{portfolio_id}/positions/{fund_code}`
- `POST /api/portfolios/{portfolio_id}/positions/normalize`
- `POST /api/portfolios/{portfolio_id}/rebalance-preview`

Create request:

```json
{
  "name": "我的稳健组合",
  "template_key": "balanced"
}
```

Position request:

```json
{
  "fund_code": "000001",
  "weight_percent": 50
}
```

Portfolio detail includes:

- `unavailable_position_count`: required non-negative count of positions whose fund is no longer in the active snapshot generation.
- `positions[].available`: required boolean derived from the active snapshot generation; it is not a database column.
- `positions[].availability_reason`: required structured reason. It is `available` for active funds and `removed_from_active_snapshot` when a saved holding points to a fund outside the current active generation.
- `positions[].weight_percent`: saved user-entered weight.
- `positions[].normalized_weight_percent`: read-only preview normalized to 100% when total weight is greater than 0.
- `total_weight_percent`: sum of saved position weights.
- `weight_warning`: non-directive warning when total weight is not close to 100%.

An existing position is retained when its fund leaves the active snapshot and can still be removed with `DELETE /positions/{fund_code}`. Creating or updating a position only accepts a fund from the active snapshot.

`POST /positions/normalize` atomically persists the currently previewed normalized proportions. It requires at least one positive position, keeps relative weights unchanged, and makes the saved total exactly 100% by assigning any rounding remainder to the last deterministic position. This is a configuration convenience, not a trade or rebalance instruction. If any position is unavailable, the endpoint returns `409 PORTFOLIO_HAS_UNAVAILABLE_POSITIONS` without changing weights. The error `detail` is structured as `{ "availability_reason": "removed_from_active_snapshot", "unavailable_fund_codes": ["000001"] }`.

Rebalance preview uses saved `portfolio_positions` and target stock/bond ratios. It only sets `triggered=true` when drift is greater than 5%, and messages must remain non-directive. If any position is unavailable, the endpoint returns `409 PORTFOLIO_HAS_UNAVAILABLE_POSITIONS` with the same structured detail instead of using the fund's last known classification.

## Backtests

- `POST /api/backtests`
- `GET /api/backtests/{backtest_id}`

Create request:

```json
{
  "strategy_type": "template_portfolio",
  "amount": 1000,
  "start": "2021",
  "end": "2026",
  "fund_codes": ["000001", "000002"],
  "rebalance_threshold": 5,
  "template_key": "balanced"
}
```

Supported `strategy_type` values:

- `monthly_dca`
- `weekly_dca`
- `rebalance`
- `template_portfolio`

Validation contract:

- `amount` must be a finite number greater than 0.
- `start` and `end` must both be four-digit years or both be ISO dates (`YYYY-MM-DD`), with `start <= end`.
- `fund_codes` must contain 1-5 distinct six-digit fund codes; whitespace is normalized before validation.
- `GET /api/backtests/{backtest_id}` returns `404 BACKTEST_NOT_FOUND` instead of a fabricated zero-valued result when the run does not exist.

`template_portfolio` uses the selected portfolio template's stock/bond ratio and classifies selected funds by type: `stock`/`mixed` as stock-like, `bond`/`money` as bond-like. Results are calculated from one resolved `fund_navs` generation, persisted to `backtest_runs.result_snapshot`, and include annualized return, money-weighted return, time-weighted return, return calculation method, `snapshot_generation_id`, max drawdown, annualized volatility, Sharpe ratio, total invested, final value, warning text, and portfolio/benchmark curve points. With ISO daily NAV dates, `monthly_dca`/template contributions occur on the first common trading date of each month and `weekly_dca` on the first common ISO-week date; portfolio and benchmark use identical cash-flow dates, while `rebalance` invests once. `annualized_return` and `money_weighted_return` use XIRR over the simulated cash-flow dates plus the final portfolio value; `time_weighted_return` removes external contribution effects before annualizing the historical asset path; `return_calculation_method` is `xirr`, or `unavailable` when data is insufficient. Legacy yearly sample dates continue to use every available point and return an explicit approximation warning.

## AI

- `POST /api/ai/chat`
- `POST /api/ai/chat/stream`
- `GET /api/ai/threads`
- `GET /api/ai/threads/{thread_id}`

Chat request:

```json
{
  "message": "解释这只基金的最大回撤",
  "context": {
    "page": "assistant",
    "fund_code": "000001"
  }
}
```

Backtest explanation can pass a persisted backtest id:

```json
{
  "message": "解释这次回测结果",
  "context": {
    "page": "backtest",
    "backtest_id": "bt_xxx"
  }
}
```

Chat response always includes:

- `conclusion`
- `evidence`
- `references`
- `risk`
- `data_date`
- `disclaimer`
- `unable_to_answer`

Business code calls `LLMGateway`; the default provider is `mock`, configured by `LLM_PROVIDER`, `LLM_MODEL`, `LLM_API_KEY`, and `LLM_BASE_URL`. Guardrails reject predictions, short-term trading points, and directive buy/sell language.

Non-mock provider requests enqueue one best-effort `llm_provider_events` row with sanitized provider/model labels, final outcome, attempts/retries, total latency, timeout flag, and a bounded error category. The request path uses a fixed-capacity non-blocking queue; one daemon worker owns connection acquisition and commits, and application shutdown performs a bounded drain/close. Queue overflow, lock waits, or persistence failures do not change or delay provider results and deterministic fallback availability. The table never stores prompts, retrieved evidence, responses, raw exception messages, API keys, credentials, or service URLs.

Retries are limited to transient timeout/network failures, HTTP 408/429, and 5xx responses (including 504 as timeout). HTTP 400/401/403, invalid local response parsing, and policy callback failures do not retry. Numeric `Retry-After` values on 429 are honored with a two-second cap; unsupported HTTP-date values use the bounded backoff.

When `context.backtest_id` is provided, the mock gateway reads `backtest_runs`, cites the run id, summarizes historical annualized return, max drawdown, volatility, total invested, final value and curve point count, and explicitly states that historical performance does not imply future returns.

`/api/ai/chat/stream` returns `text/event-stream` chunks and a final event. The final event carries the same provenance meta as the JSON chat route while keeping the structured `ChatResponse` under `response`:

```text
data: {"chunk":"..."}

data: {"done":true,"response":{...},"meta":{"source":"sample_local","data_updated_at":"2026-07-08T20:30:00","disclaimer":"...","pagination":null}}
```

AI threads and messages are persisted in `ai_threads` and `ai_messages`.

RAG document ingestion, chunking, deterministic embeddings, references, and retrieval are implemented. PostgreSQL uses pgvector cosine nearest-neighbor candidate retrieval; SQLite keeps an in-process cosine fallback for tests and local degradation. Production-scale index tuning and retrieval observability remain follow-up work.
