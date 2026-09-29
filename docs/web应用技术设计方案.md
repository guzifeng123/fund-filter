# 基金分析 Web 应用技术设计方案

文档版本：v1.3
日期：2026-07-14
应用定位：个人自用的基金分析与闲钱管理 Web 应用  
目标用户：基金投资新手、希望用规则化方式管理闲钱的个人用户  
默认工作目录：`C:\Users\39187\Desktop\基金`

## 0. 当前实现状态

截至 2026-07-17，核心页面、可编辑四步筛选、设置运行状态、完整投教内容、后端分层、数据库地基、风险测评、组合、回测、AI Gateway、真实 LLM provider 边界、聚合观测与事件保留清理、RAG、数据源 adapter、基金数据原子快照、质量脚本与本地运维均已基本落地。Playwright 已同时覆盖 mocked 主路径和真实 API 的基金/组合/回测/AI 四个合规表面，并输出机器视觉合同。仍处于后续阶段的内容包括：盈米 MCP、账号与多用户隔离、不可变历史 generation、生产级外部监控/告警投递和 LLM 事件清理自动调度/分区归档。

当前状态、历史完成记录和剩余待办统一维护在 [待完成与版本任务规划.md](待完成与版本任务规划.md)。本文档保留为产品与技术设计基准，不再承载逐条任务追踪。

## 1. 背景与目标

本应用基于两份输入材料整理而成：

- `个股分析软件功能需求.pdf`：提供投研工作台、GUI + LUI 双交互、行情/指标/资金/资讯/事件分析等扩展方向。
- `基金分析软件设计.pdf`：提供基金新手场景、合规约束、数据源策略、筛选比较、组合管理、回测学习等核心设计。

v1 明确以基金分析为主，不在首版实现个股投研主流程。个股相关能力只作为后续扩展点保留，例如行情模块、事件模块、资金流模块和语言交互入口。

### 1.1 产品目标

构建一个安静、专业、适合反复扫描的基金分析工作台，帮助用户完成以下闭环：

1. 通过风险测评理解自己的风险承受能力。
2. 基于合规历史净值和风险等级筛选基金。
3. 对最多 5 只基金做收益、风险、费用和基金经理维度对比。
4. 通过预设组合模板管理闲钱配置。
5. 用历史回测理解定投、再平衡等被动策略。
6. 通过 AI 分析助手解释指标、总结基金、诊断组合和辅助学习。

### 1.2 非目标

v1 不实现以下能力：

- 不提供基金实时估值。
- 不预测未来净值、未来收益率或短期买卖点。
- 不接入真实交易和自动下单。
- 不做 SaaS 多租户、计费、企业权限和复杂审计。
- 不以个股短线交易为主线。

### 1.3 合规原则

应用必须始终遵守以下边界：

- 所有分析页面显示数据来源、数据更新时间和免责声明。
- 基金风险等级必须与用户风险测评结果匹配。
- 超出风险承受能力的基金允许浏览，但必须触发明显风险提示，不进入推荐结果。
- 回测页面必须展示“历史表现不预示未来收益”。
- AI 助手输出必须说明“仅供分析学习，不构成投资建议”。

## 2. 技术栈

### 2.1 前端

| 分类 | 选型 | 用途 |
| --- | --- | --- |
| Web 框架 | Next.js 16 App Router | 页面路由、服务端渲染、静态资源和前端构建 |
| UI 框架 | React 19 | 组件化 UI |
| 类型系统 | TypeScript strict | 前端类型安全 |
| 样式 | Tailwind CSS v4 | 设计 token、响应式布局和组件样式 |
| 组件基础 | 项目自定义语义组件 | `Button`、`Input`、`Select`、`Textarea`、`FormField` 等统一样式、状态和 ARIA 关联 |
| 图标 | lucide-react | 按钮、导航、状态和工具图标 |
| 服务端状态 | TanStack Query | API 请求、缓存、重试和加载状态 |
| 表格 | TanStack Table | 基金列表、比较表和回测明细 |
| 图表 | Apache ECharts | 净值曲线、雷达图、热力图、环形图和回测曲线 |

### 2.2 后端

| 分类 | 选型 | 用途 |
| --- | --- | --- |
| API 框架 | FastAPI | REST API、OpenAPI、SSE 流式接口 |
| 数据校验 | Pydantic v2 | 请求、响应和配置校验 |
| ORM | SQLAlchemy 2 | 数据模型和查询 |
| 迁移 | Alembic | 数据库 schema 迁移 |
| 定时任务 | APScheduler | 个人部署下的数据同步任务 |
| 类型检查 | mypy | Python 类型检查 |
| 代码质量 | Ruff | Python lint 与 format |

### 2.3 数据与 AI

| 分类 | 选型 | 用途 |
| --- | --- | --- |
| 主数据库 | PostgreSQL 17 | 业务数据、基金数据、组合和回测记录 |
| 向量检索 | pgvector | 投教内容、指标解释和 AI RAG 检索 |
| JSON 存储 | PostgreSQL JSONB | 保存原始 API 响应和第三方数据快照 |
| AI 接口 | LLM Gateway | 统一封装 OpenAI-compatible provider |
| Embedding | Provider configurable | 文档切片和投教检索 |

### 2.4 部署

个人自用采用 Docker Compose，包含：

- `web`：Next.js 前端服务。
- `api`：FastAPI 后端服务。
- `postgres`：PostgreSQL + pgvector 数据库。

本地开发环境使用 Windows PowerShell。所有 npm 命令统一使用 `npm.cmd`，例如：

```powershell
npm.cmd run dev
npm.cmd run build
npm.cmd run test
```

## 3. 系统架构

### 3.1 总体架构

```mermaid
flowchart LR
  Browser["浏览器"] --> Web["Next.js Web"]
  Web --> API["FastAPI API"]
  API --> DB["PostgreSQL + pgvector"]
  API --> Jobs["APScheduler 数据任务"]
  Jobs --> DataSource["盈米 MCP / 公开数据源"]
  API --> LLM["LLM Gateway"]
  LLM --> DB
```

### 3.2 目录结构

```text
fund-web/
  apps/
    web/
      src/
        app/
        components/
        features/
        lib/
        styles/
    api/
      app/
        core/
        routers/
        services/
        repositories/
        schemas/
        models/
        jobs/
        tests/
      alembic/
  packages/
    contracts/
  docs/
    web应用技术设计方案.md
    api接口说明.md
    数据字典.md
```

### 3.3 前端分层

```text
src/app
  路由、布局和页面装配，只负责组合组件

src/features
  按业务域组织页面片段、hooks 和状态
  例如 funds、portfolio、backtest、assistant

src/components
  通用 UI 组件和领域组件

src/lib/api
  API client、OpenAPI 生成类型和请求封装

src/styles
  Tailwind token、主题变量和图表色板
```

页面不得直接调用 `fetch`。所有请求必须通过 `src/lib/api` 的 typed client。

### 3.4 后端分层

```text
routers
  路由层，只做鉴权、参数接收和响应封装

services
  业务逻辑层，例如基金筛选、组合诊断、回测、AI 编排

repositories
  数据访问层，封装 SQLAlchemy 查询

schemas
  Pydantic 请求和响应模型

models
  SQLAlchemy 数据模型

jobs
  数据同步、指标计算和补偿任务
```

路由层不得直接写 SQL，服务层不得直接拼 HTTP 响应。

## 4. 核心页面

### 4.1 `/dashboard`

个人首页，展示：

- 用户风险等级和有效期。
- 组合健康状态。
- 自选基金最新净值更新时间。
- 近期风险提示。
- AI 助手入口。

### 4.2 `/funds`

基金筛选主页面。桌面端采用三栏布局：

- 左侧：筛选条件和四步筛选器。
- 中间：基金列表。
- 右侧：选中基金详情摘要。

移动端改为：

- 顶部搜索。
- 筛选抽屉。
- 列表页。
- 独立详情页。

### 4.3 `/funds/[code]`

基金详情页，展示：

- 基金基础信息。
- 历史净值曲线。
- 收益、最大回撤、夏普比率、排名分位。
- 风险等级和风险匹配结果。
- 费用结构。
- 基金经理信息。
- AI “1 秒诊断”摘要。

### 4.4 `/compare`

基金比较页：

- 最多比较 5 只基金。
- 表格对比收益、风险、费用、经理经验。
- 雷达图展示收益、风险控制、费用友好度、经理稳定性。
- 支持从 `/funds` 列表加入比较。

### 4.5 `/portfolio`

组合管理页：

- 保守型、稳健型、进取型模板。
- 自定义组合持仓。
- 股债比例环形图。
- 组合收益曲线。
- 偏离阈值提示。
- 再平衡预览。

### 4.6 `/backtest`

回测学习页：

- 每月定投模板。
- 股债再平衡模板。
- 自定义起止时间、金额和频率。
- 组合与基准收益曲线。
- 年化收益、最大回撤、波动率等指标。
- 强制展示免责声明。

### 4.7 `/assistant`

AI 分析助手页的产品目标：

- 自然语言筛选基金。
- 解释指标含义。
- 总结基金优劣势。
- 诊断组合风险。
- 解读回测结果。
- 回答投教问题。

当前已有专门数据读取路径的是 `context.fund_code` 基金解释、`context.backtest_id` 回测解释和 RAG 投教问答。自然语言筛选基金与基于 `portfolio_id` 的组合诊断仍是后续目标；页面入口或任意 `context` 字段本身不代表能力已经落地。

所有回答都必须附：

- 使用的数据日期。
- 数据来源（JSON `/api/ai/chat` 由外层 API envelope 的 `meta.source` 提供，不属于 `ChatResponse` 字段）。
- 合规免责声明。
- 无法回答或数据不足时的明确说明。

`/api/ai/chat/stream` 的最终 SSE 事件同时携带 `response: ChatResponse` 与外层 `meta`，其中包含实际基金数据来源、可推导的数据更新时间和统一免责声明；中间 chunk 只承载展示文本。

### 4.8 `/learn`

投教学习页：

- 基金基础概念。
- 风险等级解释。
- 定投和再平衡说明。
- 指标解释。
- 常见误区。

### 4.9 `/settings`

设置页：

- 盈米 MCP 配置。
- LLM provider 配置。
- 数据源声明。
- 风险测评有效期。
- 本地数据清理。

## 5. 组件设计库

### 5.1 组件策略

项目直接维护轻量的语义组件层。业务页面必须优先使用项目自定义组件暴露统一样式、默认行为和 ARIA 关联；新增复杂交互组件时再评估成熟无障碍库，不能在文档中把未安装的组件库写成当前依赖。

示例：

- 允许：`<RiskLevelBadge level="R3" />`
- 不建议：业务页面手写 `<Badge className="...">R3</Badge>`

### 5.2 通用组件

| 组件 | 用途 |
| --- | --- |
| `AppShell` | 顶部栏、侧边栏、主内容区和 AI 助手停靠入口 |
| `PageHeader` | 页面标题、说明、操作区 |
| `DataFreshnessBadge` | 数据来源和更新时间 |
| `ComplianceNotice` | 免责声明和风险提示 |
| `EmptyState` | 空结果、未配置数据源、无回测结果 |
| `ErrorState` | API 失败、数据源失败、AI 失败 |
| `LoadingBlock` | 页面和图表加载态 |
| `MetricExplainTooltip` | 指标解释 |
| `Button` | 统一按钮变体、尺寸、默认 `type=button` 和焦点状态 |
| `Input` / `Select` / `Textarea` | 统一表单控件样式、禁用态和 ARIA 属性 |
| `FormField` | 统一 label、description、error 与控件 ID 关联 |

### 5.3 领域组件

| 组件 | 用途 |
| --- | --- |
| `FundSearchCombobox` | 按名称、代码搜索基金 |
| `FilterStepper` | 四步筛选框架 |
| `FundTable` | 基金列表 |
| `FundDetailPanel` | 列表右侧详情摘要 |
| `RiskLevelBadge` | R1-R5 风险等级 |
| `NetValueChart` | 净值曲线 |
| `RiskHeatmap` | 风险热力图 |
| `FundCompareRadar` | 基金雷达图 |
| `AllocationDonut` | 组合股债比例 |
| `BacktestResultPanel` | 回测结果展示 |
| `AssistantDock` | 页面右下或右侧 AI 助手入口 |

### 5.4 视觉规范

整体视觉方向为“安静、专业、可扫描”。避免营销页风格和大面积装饰。

关键规则：

- 卡片圆角不超过 `8px`。
- 页面区块采用全宽布局或无框布局，不做层层嵌套卡片。
- 表格、指标和图表保持紧凑，优先可读性。
- 按钮使用 lucide 图标和简短文案。
- 风险色统一使用 R1-R5 token。

风险色建议：

| 等级 | 语义 | 颜色 |
| --- | --- | --- |
| R1 | 低风险 | `#2E7D32` |
| R2 | 中低风险 | `#6A8F2A` |
| R3 | 中风险 | `#B58B00` |
| R4 | 中高风险 | `#C65D21` |
| R5 | 高风险 | `#B3261E` |

图表必须具备：

- loading 状态。
- empty 状态。
- error 状态。
- stale data 状态。
- 数据来源标注。

## 6. 核心业务规则

### 6.1 风险测评

用户首次使用必须完成风险测评：

- 当前题库：6 道；提交时必须覆盖当前全部题目 ID，且同一 `question_id` 只能出现一次。请求 schema 预留 5-8 道扩展范围。
- 输出结果：C1-C5。
- 有效期：从 `assessed_at` 起固定 365 天；API 根据存储的测评时间派生 `effective_from`、`effective_to` 和 `is_expired`，数据库不保存起止日期列。
- 到期前 30 天（含）返回 `expires_soon=true` 并提醒重新测评。设置页显示的“12 个月”是 `365 / 30` 四舍五入后的展示值，不是按自然月计算。

匹配规则：

| 用户等级 | 可匹配基金 |
| --- | --- |
| C1 | R1 |
| C2 | R1-R2 |
| C3 | R1-R3 |
| C4 | R1-R4 |
| C5 | R1-R5 |

### 6.2 基金筛选

筛选采用四步框架：

1. 基础条件：成立年限、规模、基金类型、风险等级。
2. 核心指标：近 3 年和近 5 年收益、最大回撤、夏普比率。
3. 费用结构：申购费、管理费、托管费。
4. 基金经理：从业年限、管理同类基金年限、历史稳定性。

默认条件：

- 成立年限不少于 3 年；按基金 `inception_date` 到请求处理日的完整年数计算，不使用基金经理任职年限。查询实现先计算包含边界的成立日 cutoff，遇到 2 月 29 日回退到目标非闰年的 2 月 28 日。
- 基金规模建议 10-100 亿。
- 收益排名默认取同类前 30%。
- 最大回撤幅度不劣于同类平均。内部最大回撤使用负数百分比，因此同类型基金均值为 `-10%` 时，`-8%` 应保留，查询条件为基金值 `>=` 同类均值。请求字段 `max_drawdown_lte_category_avg` 中的 `lte` 描述回撤幅度，不是负数存储值的数值比较方向；字段为 `false` 时不应用此条件。
- 夏普比率默认不低于 1.2。
- 管理费默认不高于 1.5%。

### 6.3 基金比较

比较规则：

- 最多比较 5 只基金。
- 超过 5 只时前端禁止继续添加。
- 比较维度固定为收益、风险、费用、基金经理、风险匹配。
- 风险超配基金必须在比较表中高亮。

### 6.4 组合管理

默认模板：

| 模板 | 股票/偏股基金 | 债券/货币基金 | 适用用户 |
| --- | --- | --- | --- |
| 保守型 | 20% | 80% | C1-C2 |
| 稳健型 | 50% | 50% | C2-C3 |
| 进取型 | 80% | 20% | C4-C5 |

再平衡规则：

- 任一资产类别偏离目标比例超过 `5%` 时，生成再平衡预览。
- 预览只展示“需要调回目标比例”的信息，不给出强制交易指令。
- 所有建议使用“可考虑”“用于恢复比例”这类非指令性表达。
- 已持有基金从 active snapshot 移除时保留用户持仓，并返回 `available=false`、`availability_reason=removed_from_active_snapshot` 与 `unavailable_position_count`；用户仍可删除该持仓。
- 存在不可用持仓时禁止归一化和再平衡预览，统一返回 `409 PORTFOLIO_HAS_UNAVAILABLE_POSITIONS`，`error.detail` 包含 `availability_reason` 与 `unavailable_fund_codes`，不得使用旧基金分类推导当前股债比例。

### 6.5 回测

允许的策略：

- 每周定投。
- 每月定投。
- 固定比例再平衡。
- 模板组合回测。

禁止的策略：

- 未来收益预测。
- 短期买卖点推荐。
- 基于实时估值的套利策略。
- 自动交易策略。

回测结果默认主口径保持资金加权收益率 XIRR：`annualized_return` 与 `money_weighted_return` 均按每笔投入现金流日期和期末市值计算。结果同时返回 `time_weighted_return`，用于剔除中途投入影响后观察资产本身历史表现；前端结果区需同屏展示“资金加权”和“时间加权”，并说明二者差异，不得把任一收益口径包装成未来收益预测。

## 7. API 设计

### 7.1 API 约定

统一前缀：`/api`

响应结构：

```json
{
  "data": {},
  "meta": {
    "source": "eastmoney_snapshot",
    "data_updated_at": "2026-07-13T20:30:00+08:00",
    "disclaimer": "本工具基于历史数据，仅供分析学习，不构成投资建议。"
  }
}
```

错误结构：

```json
{
  "error": {
    "code": "FUND_NOT_FOUND",
    "message": "未找到指定基金",
    "detail": {}
  }
}
```

### 7.2 基金接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/funds/search?q=` | 搜索基金 |
| GET | `/api/funds/{code}` | 基金详情 |
| GET | `/api/funds/{code}/nav?start=&end=` | 历史净值 |
| POST | `/api/funds/filter` | 条件筛选 |
| POST | `/api/funds/compare` | 基金比较 |

`POST /api/funds/filter` 请求示例：

```json
{
  "risk_profile": "C3",
  "fund_types": ["mixed", "bond"],
  "min_years": 3,
  "size_range": [10, 100],
  "return_rank_percentile": 30,
  "max_drawdown_lte_category_avg": true,
  "sharpe_gte": 1.2,
  "fee_lte": 1.5
}
```

筛选合同补充：`min_years` 对应基金成立年限；`max_drawdown_lte_category_avg=true` 按数据库内相同 `fund_type` 且已有指标的基金计算最大回撤平均值，并保留回撤幅度不劣于该均值的基金。最大回撤采用负数口径，因此实现比较方向为 `>=`；传 `false` 时不做同类回撤过滤。

### 7.3 风险测评接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/risk-assessments` | 提交风险测评 |
| GET | `/api/risk-assessments/latest` | 获取最新测评 |

### 7.4 组合接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/portfolios` | 获取组合列表 |
| POST | `/api/portfolios` | 创建组合 |
| GET | `/api/portfolios/{id}` | 组合详情 |
| PATCH | `/api/portfolios/{id}` | 更新组合名称 |
| DELETE | `/api/portfolios/{id}` | 删除组合 |
| PUT | `/api/portfolios/{id}/positions` | 新增或更新当前 active 基金持仓 |
| DELETE | `/api/portfolios/{id}/positions/{fund_code}` | 删除持仓，包括不可用持仓 |
| POST | `/api/portfolios/{id}/positions/normalize` | 原子归一化持仓权重 |
| POST | `/api/portfolios/{id}/rebalance-preview` | 再平衡预览 |

列表/详情的 `unavailable_position_count`，以及详情 `positions[].available` / `positions[].availability_reason` 为必填派生字段。归一化和再平衡在存在不可用持仓时返回 `409 PORTFOLIO_HAS_UNAVAILABLE_POSITIONS`，并在 `error.detail.unavailable_fund_codes` 返回不可用基金代码列表。

### 7.5 回测接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/backtests` | 创建回测 |
| GET | `/api/backtests/{id}` | 获取回测结果 |

基金搜索、筛选、比较、详情和净值接口在 repository 层解析一次 active generation，并用同一 generation 上下文返回 payload、`meta.source` 与 `meta.data_updated_at`。回测创建时同样先解析一次 generation 加载 NAV，结果中的 `snapshot_generation_id` 持久化在 `backtest_runs.result_snapshot`；历史回测详情按该 generation 返回来源和更新时间。

### 7.6 AI 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| POST | `/api/ai/chat` | AI 对话，返回结构化 JSON |
| POST | `/api/ai/chat/stream` | AI 对话，SSE 分块并在最终事件返回完整结构化响应 |
| GET | `/api/ai/threads` | 对话列表 |
| GET | `/api/ai/threads/{id}` | 对话详情 |

`POST /api/ai/chat` 请求示例：

```json
{
  "thread_id": "optional-thread-id",
  "message": "帮我解释这只基金为什么最大回撤比较高",
  "context": {
    "fund_code": "000001",
    "page": "fund_detail"
  }
}
```

`POST /api/ai/chat` 的运行时响应固定包含以下字段：

| 字段 | 含义 |
| --- | --- |
| `thread_id` | 持久化后的线程 ID；`ChatResponse` schema 允许为 `null`，但保存成功后会写入实际 ID。 |
| `conclusion` | 结论摘要。 |
| `evidence` | 数据依据列表。 |
| `references` | 基金、指标、回测或 RAG 文档引用列表；无法引用时为空数组。 |
| `risk` | 风险与局限说明。 |
| `data_date` | 本次回答采用的数据日期。 |
| `disclaimer` | AI 专用免责声明。 |
| `unable_to_answer` | 因数据缺失或合规 guardrail 无法回答时为 `true`。 |

`context` 当前有专门读取逻辑的键为单只基金的 `fund_code` 和已持久化回测的 `backtest_id`；其他键可随请求传入，但不能据此宣称已实现相应业务诊断。

## 8. 数据模型

本节按 `apps/api/app/db/models.py` 与 Alembic 当前 head `0009_add_llm_provider_events` 记录已落库结构；字段级说明以《数据字典》为准。未来概念与已实现表分开列示，不能把页面占位字段或设计名称当作数据库合同。

### 8.1 核心表

| 表名 | 用途 |
| --- | --- |
| `funds` | 基金基础信息 |
| `fund_navs` | 基金历史净值 |
| `fund_metrics` | 收益、回撤、夏普、分位等指标 |
| `fund_data_snapshots` | 完整基金数据 generation 的来源、状态和计数 |
| `fund_data_snapshot_state` | 单例 active generation 指针 |
| `risk_assessments` | 用户风险测评结果 |
| `portfolios` | 组合基础信息 |
| `portfolio_positions` | 组合持仓 |
| `backtest_runs` | 回测配置和结果 |
| `job_runs` | 数据任务运行记录与同名运行锁 |
| `ai_threads` | AI 对话线程 |
| `ai_messages` | AI 对话消息 |
| `documents` | 投教或说明文档 |
| `document_chunks` | 文档切片和向量 |
| `llm_provider_events` | 真实 provider 请求的最小化可观测事件 |

### 8.2 关键字段

| 表 | 当前实际字段 |
| --- | --- |
| `funds` | `code`, `name`, `fund_type`, `risk_level`, `manager_name`, `inception_date`, `fund_size_billion`, `management_fee`, `custody_fee`, `source`, `data_updated_at`, `ai_summary`, `raw_data`, `snapshot_generation_id`, `created_at`, `updated_at` |
| `fund_navs` | `id`, `fund_code`, `trade_date`, `trade_date_precision`, `nav`, `accumulated_nav`, `raw_data`, `snapshot_generation_id` |
| `fund_metrics` | `fund_code`, `annualized_return_3y`, `annualized_return_5y`, `max_drawdown`, `sharpe_ratio`, `category_rank_percentile`, `manager_years`, `raw_data`, `snapshot_generation_id`, `updated_at` |
| `fund_data_snapshots` | `generation_id`, `source`, `status`, `fund_count`, `nav_count`, `metric_count`, `created_at`, `promoted_at` |
| `fund_data_snapshot_state` | `id=1`, `active_generation_id`, `updated_at` |
| `risk_assessments` | `id`, `user_id`, `risk_profile`, `answers`, `assessed_at` |
| `portfolios` | `id`, `user_id`, `name`, `template_key`, `stock_ratio`, `bond_ratio`, `config`, `created_at`, `updated_at` |
| `portfolio_positions` | `id`, `portfolio_id`, `fund_code`, `weight_percent`, `metadata`（ORM 属性名 `metadata_`） |
| `backtest_runs` | `id`, `user_id`, `strategy_type`, `request_payload`, `result_snapshot`, `annualized_return`, `max_drawdown`, `volatility`, `created_at` |
| `job_runs` | `id`, `name`, `status`, `started_at`, `finished_at`, `details` |
| `ai_threads` | `id`, `user_id`, `title`, `created_at`, `updated_at` |
| `ai_messages` | `id`, `thread_id`, `role`, `content`, `payload`, `created_at` |
| `documents` | `id`, `title`, `source_uri`, `document_type`, `content_hash`, `metadata`（ORM 属性名 `metadata_`）, `created_at`, `updated_at` |
| `document_chunks` | `id`, `document_id`, `chunk_index`, `content`, `embedding`, `metadata`（ORM 属性名 `metadata_`）, `created_at` |
| `llm_provider_events` | `id`, `provider_name`, `model_name`, `outcome`, `attempt_count`, `retry_count`, `latency_ms`, `timed_out`, `error_category`, `created_at` |

风险测评响应中的 `effective_from`、`effective_to`、`expires_soon`、`is_expired` 和 `explanation` 均由 repository/schema 根据 `assessed_at` 派生，不是 `risk_assessments` 的数据库列。类似地，基金净值没有 `daily_return`、`source`、`fetched_at` 列；基金指标也没有通用 `period`、`annualized_return`、`volatility`、`pe_pb_percentile` 或 `calculated_at` 列。回测的 `snapshot_generation_id` 是 `result_snapshot` 内的响应/审计字段，不是 `backtest_runs` 的独立列。

### 8.3 尚未落库的未来概念

| 概念 | 当前边界 |
| --- | --- |
| `portfolio_snapshots` | 仅代表未来的组合每日快照设计；当前没有 ORM model、Alembic 表或读写 API。组合回测结果存于 `backtest_runs.result_snapshot`，不能等同于组合每日快照。 |
| `watchlists` / watchlist | 仅代表未来的自选基金能力；当前没有持久化表。Dashboard 的 `watchlist_updated_at=null`、`watchlist_status=not_configured` 是能力状态占位，不是 watchlist 数据。 |
| `alerts` / alert | 仅代表未来的业务提醒能力；当前没有持久化表。Dashboard 固定返回空 `alerts` 与 `alerts_status=not_configured`；发布产物中的 artifact alerts 是质量报告，和业务提醒无关。 |

## 9. AI 分析助手设计

### 9.1 能力范围

v1 设计范围：

- 自然语言筛选基金。
- 基金指标解释。
- 基金优劣势摘要。
- 组合风险诊断。
- 回测结果解释。
- 投教问答。

截至当前版本，基金指标/历史摘要、已持久化回测解释和 RAG 投教问答已有专门读取路径；自然语言筛选与组合诊断尚无对应 service/repository 实现，仍属于设计目标。

v1 不支持：

- 自动下单。
- 未来收益预测。
- 明确买入、卖出、加仓、减仓指令。
- 绕过风险等级匹配。

### 9.2 LLM Gateway

后端只通过 `LLM Gateway` 调用模型，不允许业务服务直接调用 provider SDK。

接口职责：

- 注入系统提示词。
- 注入合规边界。
- 执行 RAG 检索。
- 在 `ai_messages` 中持久化产品对话消息。
- 在 `llm_provider_events` 中记录不含 prompt/响应正文的 provider 可观测元数据。
- 屏蔽敏感配置。
- 统一错误处理。

当前实现中，`LLM_PROVIDER=mock` 时继续走确定性本地回答；非 mock 时走 OpenAI-compatible `/chat/completions`，并带超时、有限重试、base URL 安全校验、跨源重定向阻断、响应 body/输出长度硬上限、基础敏感信息脱敏和输出后置合规检查。模型文本若包含强交易指令、收益保证、择时信号或确定性未来预测，会被丢弃并回退确定性合规回答。

真实 provider 每次调用最多生成一条 `llm_provider_events` 请求级事件，记录净化后的 provider/model、结果、尝试/重试次数、总延迟、超时和白名单错误类别，不保存用户问题、RAG 依据、模型回答、异常原文、URL 或凭据。请求线程只向固定容量队列非阻塞入队，单 worker 独立事务落库；worker 异常退出后仅在同一 dispatcher 的同一有界队列上受控重启，关闭超时后丢弃尚未开始处理的队列遗留事件并计入安全汇总，不回退到聊天请求线程同步写库。`GET /api/settings/runtime` 按当前 provider/model 返回最近窗口请求率、成功率、错误率、重试率、超时率、阈值状态和后台写入队列健康摘要。`LLM_OBSERVABILITY_RETENTION_DAYS` 控制事件保留天数，`scripts/cleanup_llm_provider_events.py` 默认 dry-run 并可输出 JSON 清理报告，显式 `--apply` 后才删除旧事件。生产化后续是外部告警投递、去重冷却、自动调度、分区/归档和规模化索引，而不是再次实现数据库事件表。

### 9.3 RAG 数据来源

进入向量库的内容：

- 投教文章。
- 指标解释。
- 风险等级说明。
- 应用内合规声明。
- 用户已导入的基金说明材料。

不进入向量库的内容：

- API key。
- 用户密码。
- 未脱敏的敏感配置。

### 9.4 AI 输出模板

AI 对基金、回测或投教问题的结构化输出与 `ChatResponse` 保持一致：

```text
conclusion          结论摘要
evidence[]          数据依据
references[]        可核验引用
risk                风险与局限
data_date           数据日期
disclaimer          AI 免责声明
unable_to_answer    是否无法回答
```

展示层可以把这些字段排版为自然语言栏目，但不得删除 `references`、`data_date`、`disclaimer` 或 `unable_to_answer`，也不得另造一个当前 schema 不存在的“适合进一步查看的指标”必填字段。

## 10. 数据刷新与任务设计

### 10.1 任务列表

| 任务 | 频率 | 说明 |
| --- | --- | --- |
| `sync_all` | 每日或交易日收盘后 | 单次读取完整来源快照，在一个事务中写入并原子晋升 generation |
| `sync_fund_navs` / `sync_fund_profiles` / `calculate_metrics` / `sync_risk_levels` | 手动兼容入口 | 保留任务名，但实际 `effective_scope=full_snapshot`，不原地拼接 active generation |
| `refresh_embeddings` | 文档变化时 | 更新投教向量 |
| `cleanup_job_runs` | 每周一次 | 清理过旧任务记录 |

### 10.2 任务原则

- 任务必须幂等。
- 每次运行写入 `job_runs`。
- 数据源失败不覆盖已有数据。
- 完整候选必须通过基金/NAV/metric 计数及父子 generation 一致性校验，最后一步才切换单例 active 指针。
- 基金读取把 active 指针嵌入数据 SQL，避免晋升发生在两条读取语句之间时返回被移除的残留行。
- 前端必须可见数据过期状态。
- 数据同步失败时展示降级提示。

## 11. 代码规范

### 11.1 TypeScript 规范

- 开启 `strict`。
- 禁止业务代码使用 `any`。
- API 类型从 OpenAPI 生成，不手写重复类型。
- React 组件使用 PascalCase。
- hooks 使用 `useXxx`。
- 文件名使用 kebab-case。
- 页面组件只做装配，不写复杂业务逻辑。

推荐命名：

```text
fund-search-combobox.tsx
risk-level-badge.tsx
use-fund-filter.ts
funds-api.ts
```

### 11.2 Python 规范

- API 边界必须使用 Pydantic schema。
- SQLAlchemy model 不直接作为 API response。
- service 层不得返回 ORM 对象。
- repository 层只负责数据读写。
- 所有复杂计算必须有单元测试。
- 使用 Ruff format/lint。
- 使用 mypy 做类型检查。

### 11.3 CSS 与设计 token

- 业务颜色写入 theme token。
- 风险颜色集中维护。
- 图表色板集中维护。
- 不在页面内散落任意颜色值。
- 固定格式 UI 组件必须有稳定尺寸，避免 hover、加载或文本变化造成布局抖动。

### 11.4 合规文案

免责声明、风险提示、数据来源声明必须集中维护：

```text
src/lib/compliance/constants.ts
apps/api/app/core/compliance.py
```

业务页面只能引用，不得手写重复文案。

## 12. 测试计划

### 12.1 后端单元测试

必须覆盖：

- 收益率计算。
- 最大回撤计算。
- 夏普比率计算。
- 风险等级匹配。
- 再平衡偏离阈值。
- 定投回测。
- 数据同步幂等性。

### 12.2 API 测试

必须覆盖：

- 基金搜索。
- 基金详情。
- 基金筛选。
- 基金比较。
- 风险测评提交。
- 组合创建。
- 再平衡预览。
- 回测创建和查询。
- AI chat SSE 返回。
- 数据源失败降级。

### 12.3 前端测试

必须覆盖：

- 筛选流程。
- 最多 5 只基金比较。
- 风险测评。
- 组合模板套用。
- 回测结果展示。
- AI 诊断入口。
- 图表 loading、empty、error、stale 状态。

### 12.4 E2E 测试

Playwright 主路径：

1. 打开应用。
2. 完成风险测评。
3. 进入基金筛选页。
4. 筛选符合风险等级的基金。
5. 加入 2-5 只基金到比较页。
6. 创建一个稳健型组合。
7. 运行一次定投回测。
8. 打开 AI 助手解释回测结果。

当前已提供 CI 友好的 `@playwright/test` 入口：

```powershell
npm.cmd --workspace apps/web run e2e
```

`apps/web/e2e/main-flow.spec.ts` 使用 mocked API 覆盖主路径；`accessibility.spec.ts` 对 9 个桌面路由、基金/AI 移动端和组合不可用持仓分支执行 axe WCAG A/AA 自动审计；`real-api.spec.ts` 连接自动迁移与 seed 的真实 FastAPI，覆盖基金、组合、回测和 AI 的来源、更新时间、免责声明与关键图表。Windows 启动器默认选择空闲 Web/API 端口，保留服务 stdout/stderr 和 JSON 启动汇总；失败时 trace、截图、视频和 HTML report 输出到 `output/playwright`，成功时额外校验 `real-api-visual-check.json`。自动 axe 不替代键盘、缩放、高对比度和屏幕阅读器人工验收；真实 API 当前只覆盖 Desktop Chrome。

### 12.5 视觉验收

桌面端和移动端都要检查：

- 文本不溢出。
- 图表非空。
- 风险颜色一致。
- 数据更新时间可见。
- 空状态和错误状态可理解。
- AI 助手不遮挡主要操作。

## 13. 开发里程碑

### 阶段 1：项目骨架与数据基础

目标周期：1-2 周

交付：

- Monorepo 初始化。
- Docker Compose。
- Next.js 基础布局。
- FastAPI 基础服务。
- PostgreSQL schema。
- 基金搜索和详情 API。
- 数据来源与更新时间展示。

### 阶段 2：筛选与比较

目标周期：2-3 周

交付：

- 四步筛选框架。
- 基金列表。
- 基金详情右侧面板。
- 最多 5 只基金比较。
- 雷达图和比较表。
- 指标解释 tooltip。

### 阶段 3：组合与风险

目标周期：3-4 周

交付：

- 风险测评。
- 组合模板。
- 组合持仓管理。
- 股债比例图。
- 再平衡预览。
- 风险匹配弹窗。

### 阶段 4：回测与 AI

目标周期：4-5 周

交付：

- 定投回测。
- 再平衡回测。
- 回测结果图表。
- LLM Gateway。
- AI chat SSE。
- 投教 RAG 检索。
- 基金和组合诊断。

## 14. 验收标准

v1 完成时必须满足：

- 用户可以完成风险测评并得到 C1-C5 结果。
- 用户可以按名称或代码搜索基金。
- 用户可以按四步框架筛选基金。
- 用户最多可以比较 5 只基金。
- 用户可以创建组合并查看比例偏离。
- 用户可以运行一次定投回测。
- AI 助手可以解释基金指标、组合风险和回测结果。
- 所有结果页面都显示数据来源、更新时间和免责声明。
- 超出风险等级的基金有明显提示。
- 前端和后端测试可以通过。
- Docker Compose 可以在个人电脑上启动完整服务。

## 15. 参考文档

官方技术文档：

- [Next.js Documentation](https://nextjs.org/docs)
- [React Documentation](https://react.dev)
- [Tailwind CSS Documentation](https://tailwindcss.com/docs)
- [WAI-ARIA Authoring Practices](https://www.w3.org/WAI/ARIA/apg/)
- [axe-core Documentation](https://github.com/dequelabs/axe-core)
- [FastAPI Documentation](https://fastapi.tiangolo.com)
- [SQLAlchemy Documentation](https://docs.sqlalchemy.org)
- [Alembic Documentation](https://alembic.sqlalchemy.org)
- [PostgreSQL Documentation](https://www.postgresql.org/docs/)
- [pgvector](https://github.com/pgvector/pgvector)
- [TanStack Query Documentation](https://tanstack.com/query/latest)
- [TanStack Table Documentation](https://tanstack.com/table/latest)
- [Apache ECharts Documentation](https://echarts.apache.org/handbook/en/get-started/)
- [Playwright Documentation](https://playwright.dev/docs/intro)

输入材料：

- `C:\Users\39187\Desktop\有空看\个股分析软件功能需求.pdf`
- `C:\Users\39187\Desktop\有空看\基金分析软件设计.pdf`
