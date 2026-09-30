# 全市场基金批处理同步 Runbook（D4）

本 Runbook 面向运维/数据负责人，描述如何从 0 到 1 跑通「全市场开放式基金净值批量回填」，
并在日常以**每日增量**方式维护。配套模块：

- 断点状态机：`app/jobs/batch_state.py`（D0，冻结契约，只读消费）
- 进度聚合与滚动报告：`app/jobs/batch_report.py`
- 每日增量规划：`app/jobs/batch_incremental.py`
- 命令行：`scripts/batch_report.py`、`scripts/batch_incremental_plan.py`

> 本期**不新增 HTTP 端点**：进度一律通过文件报告（`output/batch/report-<job_id>.json`）与控制台摘要获取。

---

## 1. 环境准备

### 1.1 依赖与虚拟环境
- 仓库根目录虚拟环境：`./.venv`（门禁一律用 `apps/api` 下 `../../.venv/bin/python`）。
- 安装可编辑依赖：`make install`。
- 基线：`make test`（539 用例全绿）、`make lint`（ruff 0.14.9）、`make mypy`（`--strict` 0 错）。

### 1.2 存储选择
- **默认 SQLite（零配置，推荐先在它上面灰度）**：
  业务库 `output/dev/fund.db`；批处理断点库独立位于 `output/batch/state.db`。
- **PostgreSQL（全量/长期运行推荐）**：
  ```bash
  make pg-start            # 本地 pgvector，localhost:55432，数据目录在仓库外 ../pgdata
  make pg-migrate         # 对 fund_app 应用 Alembic 迁移
  export DATABASE_URL=postgresql+psycopg://postgres@localhost:55432/fund_app
  ```
- 断点库**永远是独立的 SQLite**（`FUND_BATCH_STATE_DB`），与 Alembic 管理的业务库物理隔离，
  这样即使业务库切到 PG，断点也不受迁移影响。

### 1.3 关键配置（`.env`，纯增量，勿重排既有行）
| 变量 | 默认 | 说明 |
|---|---|---|
| `FUND_BATCH_STATE_DB` | `output/batch/state.db` | 断点 SQLite |
| `FUND_BATCH_REPORT_DIR` | `output/batch` | 滚动报告目录 |
| `FUND_BATCH_SIZE` | `50` | 每批基金数 |
| `FUND_BATCH_WORKERS` | `1` | 并发拉取，硬上限 3 |
| `FUND_BATCH_MIN_INTERVAL_*` | `0.5` | 每域名最小请求间隔（秒） |
| `FUND_BATCH_MAX_RETRIES` | `3` | 瞬态错误最大重试 |
| `FUND_BATCH_CLAIM_TIMEOUT_SECONDS` | `1800` | in_flight 超时回收 |
| `FUND_BATCH_INCLUDE_SHORT_HISTORY` | `false` | 是否纳入不足 3 年的新基金 |
| `FUND_BATCH_UNIVERSE_CACHE_DIR` | `output/universe` | 全市场清单当日缓存 |

---

## 2. 灰度：先跑 500 只（务必先 dry-run）

目标：在不动主库的前提下，验证抓取、核对、质量门、断点与报告全链路。

1. **dry-run（不写主库）**
   ```bash
   cd apps/api
   ../../.venv/bin/python -m app.jobs.<runner> --limit 500 --dry-run
   ```
   （`--dry-run` 与 `--limit` 由 D2 runner 提供；D4 已就绪的是其上的报告与增量。）
2. **观察两份产物**
   - 滚动报告：`output/batch/report-<job_id>.json`（每批原子覆写）。
   - 多源核对报告：`output/reconciliation/`（蛋卷/新浪与东财的逐日偏差）。
3. **控制台实时看进度**
   ```bash
   python scripts/batch_report.py --job-id <job_id> --watch 30
   ```
4. **小批实写确认无误后**，再放大规模。灰度阶段重点确认：
   - `verified` 占比合理；`failed` 多为瞬态（可重试）；
   - `reconciliation_mismatch` 数量在预期内（终态，不重试）；
   - 速率（只/分钟）与限速假设一致。

---

## 3. 全量回填

### 3.1 分片与并发
- 全市场开放式基金约 **2 万只**。通过 `--shards N`（配合 `--shard i`）把待处理集合
  按 `seq % shards` 确定性切分，可在多机/多进程间分摊，互不重叠。
- `FUND_BATCH_WORKERS` **默认 1，硬上限 3**；生产建议保持 1，靠「多进程分片」而非「多线程」提速，
  以严格遵守每域名 0.5s 的礼貌间隔。

### 3.2 预计时长依据（约 14h）
- 假设：约 20 000 只、每只约 2–3 次请求（东财主源 + 蛋卷 + 新浪复权点）、
  每域名最小间隔 0.5s、单 worker、含退避（2/4/8s 封顶）与最多 3 次重试的余量。
- 粗算：20 000 × ~2.5 请求 × 0.5s ≈ 7h 纯请求时间；叠加退避、核对与写盘开销，
  经验值约 **14h**。若用 3 分片并行，可压缩到约 5h 量级，但每域名间隔仍需满足。

### 3.3 启动全量
```bash
# 单机单进程（最简）
python scripts/batch_incremental_plan.py            # 先看计划规模
# 由 D2 runner 消费计划并执行；D4 侧每批结束调用 aggregate_report 落报告。
```

---

## 4. 断点续传 / 重试 / 超时回收

- **断点**：进度落在 `fund_sync_state`。进程被杀后重跑同一计划不会重复已 `done/skipped` 的基金，
  `build_plan` 幂等、不重置 attempts。
- **超时回收**：`in_flight` 超过 `FUND_BATCH_CLAIM_TIMEOUT_SECONDS`（默认 30min）的行会在下一次
  `claim_batch` 时自动转回 `pending` 并 `attempts+1`，无需人工干预。
- **失败重试**：`failed` 为瞬态基础设施错误（429/5xx/超时）。执行 `--retry`（对应
  `BatchState.retry_failed()`）把所有 `failed` 重置为 `pending` 再跑一遍；报告中
  `pending_retry` 即待重试数量，并通过 `failures_sample`（code/attempts/last_error）定位反复失败的代码。

---

## 5. 每日增量模式

全量完成后，日常不再全量重抓。`app/jobs/batch_incremental.py` 产出确定性目标集：

- `done_codes`：已 `done` 基金——**只拉最新点**（复用 B4 增量能力），不重下全历史；
- `retry_codes`：上次 `failed` 的基金——重试；
- `new_codes`：新进入 `pending` 的基金（新上市/新纳入清单，尚未处理）；
- `estimated_requests`：粗略请求预算；结果按 code 确定性排序，重复规划幂等。

```bash
# 打印今日增量计划（JSON）
python scripts/batch_incremental_plan.py
# 仅规划某几只 / 限量
python scripts/batch_incremental_plan.py --codes 000001,000002 --limit 100
# 落盘
python scripts/batch_incremental_plan.py --out output/batch/today-plan.json
```

> 该模块只读断点、不抓网、不写主库；由 D2 runner/脚本合并后真正消费执行。

---

## 6. 短历史口径（`FUND_BATCH_INCLUDE_SHORT_HISTORY`）

- **默认 `false`**：成立但成立不足 3 年的基金走 `new_short_history` / `history_lt_3y`，
  运行时落入 `skipped_special`，**默认排除**。
- **打开后**：这些基金按 `reason=short_history_included` 被纳入并正常回填；
  报告中 `verified` 仍计数，同时单独给出 `short_history_included` 子计数，便于与「满 3 年」主口径区分。
- 切换开关只影响新规划的基金口径，不改变已落库的历史数据解读。

---

## 7. PG vs SQLite 选择建议

| 维度 | SQLite | PostgreSQL |
|---|---|---|
| 起步/灰度 | ✅ 零配置 | 需 `make pg-start` + 迁移 |
| 并发写入 | 单写者，足够（worker=1） | 多进程分片/长期运行更稳 |
| 业务库数据量 | 小/中 | 全市场 2 万只 × 多年净值，推荐 |
| 断点库 | **始终 SQLite**（独立文件） | 断点仍走 SQLite；业务库才切 PG |

建议：灰度用 SQLite，全量/长期把**业务库**切到 PG；断点库保持 SQLite 以解耦迁移。

---

## 8. 合规边界（必须遵守）

- 仅使用**公开可访问**的基金净值/资料数据，不抓取任何需登录或非公开接口。
- **每域名最小间隔 ≥ 0.5s**（东财/蛋卷/新浪独立旋钮），不得调低。
- **不绕过限流**：429/5xx/超时按 2/4/8s 退避、最多 3 次，命中即停手。
- **不使用代理/翻墙**：`PUBLIC_FUND_DATA_PROXY_URLS` 保持为空；不找代理。
- **东财 push2 接口不可达**时，切换到配置的备用镜像/缓存，不得自行突破。
- 不批量并发压测；`FUND_BATCH_WORKERS ≤ 3`。

---

## 9. 结果口径解读

滚动报告 `totals` 字段（D2 runner 按同一 reason 词汇落 checkpoint）：

| 字段 | 含义 |
|---|---|
| `total` | 清单总基金数 |
| `processed` | 已处理 = done + skipped + failed |
| `pending` / `in_flight` | 待处理 / 处理中 |
| `verified` | `done` 且 `fund_written=1`：真正落库的合格基金 |
| `short_history_included` | 被短历史开关纳入并落库的子计数 |
| `skipped_secondary` | `reason=danjuan_not_listed`（蛋卷未列/404/暂不销售，次级份额同桶） |
| `skipped_special` | `reason∈{special_caliber, unknown_type, history_lt_3y}`（货币/场内 ETF/QDII 商品/REITs/不足 3 年，默认排除） |
| `skipped_quality` | `reason=quality_failed`（B2 质量门 error） |
| `failed` | = `failed_retryable`（瞬态，可重试）+ `failed_terminal_reconciliation`（终态） |
| `failed_terminal_reconciliation` | `skipped` 且 `reason=reconciliation_mismatch`：多源核对矛盾，**终态不可重试** |
| `pending_retry` | 当前可被 `--retry` 重置的 `failed` 数量 |
| `other` | 未归类（未知 reason / done 但未写库）；原始 reason 见 `other_reasons`，**不得丢数** |
| `rate_per_minute` / `eta_seconds` | 吞吐（只/分钟）与剩余预计耗时；无 started_at 或零进展时为 `null` |

### reconciliation_mismatch 如何处置
终态、**不自动重试**。处理方式：人工查看 `output/reconciliation/` 对应偏差明细，
确认是源数据本身不一致还是抓取错误；若为源抖动可稍后单独把该 code 移回重试，
若确属口径差异则保留为跳过并记录。

### 覆盖率口径
- 蛋卷（danjuan）覆盖率约 **97%**：剩余约 3% 多为未在蛋卷挂牌/暂不销售的份额，
  归入 `skipped_secondary`，属预期损耗而非故障。
- **债券份额口径**：债券型份额（尤其是机构/定制份额）在不同数据源常缺失或口径不一，
  易落入 `skipped_secondary` 或 `reconciliation_mismatch`；解读覆盖率时应把债券型单独看待，
  不要与股票/混合型混用同一覆盖率预期。

---

## 10. 报告文件位置

- 滚动进度：`output/batch/report-<job_id>.json`（临时文件 + `os.replace` 原子覆写）
- 断点库：`output/batch/state.db`
- 多源核对：`output/reconciliation/`
- 全市场清单缓存：`output/universe/universe_YYYYMMDD.json`

控制台摘要：`python scripts/batch_report.py --job-id <job_id> [--watch 30] [--json]`。
