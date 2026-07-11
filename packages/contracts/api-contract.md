# API Contract

The API uses a uniform success envelope:

```json
{
  "data": {},
  "meta": {
    "source": "sample_local",
    "data_updated_at": "2026-07-08T20:30:00+08:00",
    "disclaimer": "本工具基于历史数据，仅供分析学习，不构成投资建议。"
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
    "data_updated_at": "2026-07-08T20:30:00+08:00",
    "disclaimer": "本工具基于历史数据，仅供分析学习，不构成投资建议。"
  }
}
```

Frontend pages must call `apps/web/src/lib/api/client.ts` instead of using `fetch` directly.

## Common Meta

- `source`: current data source, currently `sample_local`.
- `data_updated_at`: latest available data timestamp when the route can derive it from the database; otherwise current response time.
- `disclaimer`: compliance disclaimer.
- `pagination`: optional `{ "page": 1, "page_size": 20, "total": 4 }` on paginated routes.

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

Each task writes to `job_runs`. Scheduler configuration is environment based and disabled by default:

```powershell
FUND_SYNC_SCHEDULER_ENABLED=false
FUND_SYNC_INTERVAL_HOURS=24
```

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

### Filter

`POST /api/funds/filter`

Request:

```json
{
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

Success data: up to 5 funds, preserving requested code order for existing funds.

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

- `positions[].weight_percent`: saved user-entered weight.
- `positions[].normalized_weight_percent`: read-only preview normalized to 100% when total weight is greater than 0.
- `total_weight_percent`: sum of saved position weights.
- `weight_warning`: non-directive warning when total weight is not close to 100%.

Rebalance preview uses saved `portfolio_positions` and target stock/bond ratios. It only sets `triggered=true` when drift is greater than 5%, and messages must remain non-directive.

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

`template_portfolio` uses the selected portfolio template's stock/bond ratio and classifies selected funds by type: `stock`/`mixed` as stock-like, `bond`/`money` as bond-like. Results are calculated from `fund_navs`, persisted to `backtest_runs`, and include annualized return, max drawdown, volatility, Sharpe ratio, total invested, final value, warning text, and portfolio/benchmark curve points. Current sample data uses yearly NAV points, so DCA frequency and template rebalancing are approximated by available NAV dates until real monthly/weekly data is connected.

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

When `context.backtest_id` is provided, the mock gateway reads `backtest_runs`, cites the run id, summarizes historical annualized return, max drawdown, volatility, total invested, final value and curve point count, and explicitly states that historical performance does not imply future returns.

`/api/ai/chat/stream` returns `text/event-stream` chunks and a final event:

```text
data: {"chunk":"..."}

data: {"done":true,"response":{...}}
```

AI threads and messages are persisted in `ai_threads` and `ai_messages`.

Document chunks, embeddings, and full RAG remain v0.7 follow-up work.
