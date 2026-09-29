import { expect, test, type Page, type Route } from "@playwright/test";

const meta = {
  source: "mock",
  data_updated_at: "2026-07-09T10:00:00Z",
  disclaimer: "mock"
};

const funds = [
  {
    code: "000001",
    name: "稳健配置基金",
    fund_type: "mixed",
    risk_level: "R3",
    manager_name: "王一",
    inception_date: "2018-01-01",
    fund_size_billion: 30,
    management_fee: 1.2,
    custody_fee: 0.2,
    annualized_return_3y: 8.12,
    annualized_return_5y: 6.55,
    max_drawdown: -12.34,
    sharpe_ratio: 1.36,
    category_rank_percentile: 22,
    manager_years: 6,
    source: "mock",
    data_updated_at: "2026-07-09T10:00:00Z"
  },
  {
    code: "000002",
    name: "安心债券基金",
    fund_type: "bond",
    risk_level: "R2",
    manager_name: "李二",
    inception_date: "2017-01-01",
    fund_size_billion: 45,
    management_fee: 0.8,
    custody_fee: 0.1,
    annualized_return_3y: 4.12,
    annualized_return_5y: 4.55,
    max_drawdown: -5.34,
    sharpe_ratio: 1.16,
    category_rank_percentile: 32,
    manager_years: 8,
    source: "mock",
    data_updated_at: "2026-07-09T10:00:00Z"
  }
];

const fundDetail = {
  ...funds[0],
  navs: [
    { trade_date: "2025-12-31", nav: 1.12, accumulated_nav: 1.22 },
    { trade_date: "2026-07-09", nav: 1.23, accumulated_nav: 1.45 }
  ],
  ai_summary: "样例摘要，仅用于 E2E 检查。",
  fee_summary: {
    management_fee: 1.2,
    custody_fee: 0.2,
    total_fee: 1.4,
    explanation: "费用合计为管理费和托管费。"
  },
  manager_profile: {
    name: "王一",
    years: 6,
    inception_date: "2018-01-01",
    explanation: "管理年限为样例数据。"
  },
  metric_explanations: [{ key: "return", label: "收益", value: "8.12%", explanation: "历史收益不代表未来。" }],
  risk_match: {
    user_risk_profile: "C3",
    fund_risk_level: "R3",
    matched: true,
    message: "该基金风险等级未超过当前承受能力。"
  }
};

const templates = [
  { id: "conservative", name: "保守型", stock_ratio: 20, bond_ratio: 80, suitable_profiles: ["C1", "C2"] },
  { id: "balanced", name: "稳健型", stock_ratio: 50, bond_ratio: 50, suitable_profiles: ["C2", "C3"] },
  { id: "growth", name: "进取型", stock_ratio: 80, bond_ratio: 20, suitable_profiles: ["C4", "C5"] }
];

const portfolioSummary = {
  id: "portfolio-main",
  name: "我的稳健组合",
  template_key: "balanced",
  stock_ratio: 50,
  bond_ratio: 50,
  position_count: 2,
  unavailable_position_count: 0
};

const portfolioDetail = {
  ...portfolioSummary,
  positions: [
    {
      fund_code: "000001",
      fund_name: "稳健配置基金",
      fund_type: "mixed",
      risk_level: "R3",
      weight_percent: 60,
      normalized_weight_percent: 75,
      available: true
    },
    {
      fund_code: "000002",
      fund_name: "安心债券基金",
      fund_type: "bond",
      risk_level: "R2",
      weight_percent: 20,
      normalized_weight_percent: 25,
      available: true
    }
  ],
  total_weight_percent: 80,
  weight_warning: "当前持仓权重合计为 80.00%，可参考归一化比例检查配置。"
};

const normalizedPortfolioDetail = {
  ...portfolioDetail,
  positions: portfolioDetail.positions.map((position) => ({
    ...position,
    weight_percent: position.normalized_weight_percent
  })),
  total_weight_percent: 100,
  weight_warning: null
};

const unavailablePortfolioSummary = {
  ...portfolioSummary,
  unavailable_position_count: 1
};

const unavailablePortfolioDetail = {
  ...portfolioDetail,
  ...unavailablePortfolioSummary,
  positions: portfolioDetail.positions.map((position, index) => ({
    ...position,
    available: index !== 0
  }))
};

const backtestResult = {
  id: "bt-main",
  strategy_type: "monthly_dca",
  annualized_return: 6.2,
  max_drawdown: -8.5,
  volatility: 12.1,
  sharpe_ratio: 1.08,
  total_invested: 60000,
  final_value: 68800,
  data_warning: null,
  points: [
    { date: "2024", portfolio: 100, benchmark: 100 },
    { date: "2025", portfolio: 108, benchmark: 105 },
    { date: "2026", portfolio: 115, benchmark: 109 }
  ]
};

const chatResponse = {
  thread_id: "thread-main",
  conclusion: "这是基于样例数据的投教式解释。",
  evidence: ["基金代码：000001", "最大回撤：-12.34%"],
  references: ["funds:000001", "document_chunks:1:投教:local://education"],
  risk: "历史表现不预示未来收益，不构成交易指令。",
  data_date: "2026-07-09",
  disclaimer: "本内容仅用于投教和个人研究，不构成投资建议。",
  unable_to_answer: false
};

function fulfill(route: Route, data: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data, meta })
  });
}

async function mockApi(page: Page) {
  let portfolioIsNormalized = false;
  await page.route("**/api/risk-assessments/questions", (route) =>
    fulfill(route, [
      { id: "q1", title: "可承受多大波动？", options: [{ score: 3, label: "中等波动" }] },
      { id: "q2", title: "投资期限？", options: [{ score: 3, label: "三年以上" }] },
      { id: "q3", title: "亏损反应？", options: [{ score: 3, label: "继续观察" }] },
      { id: "q4", title: "收入稳定性？", options: [{ score: 3, label: "较稳定" }] },
      { id: "q5", title: "投资经验？", options: [{ score: 3, label: "有经验" }] },
      { id: "q6", title: "流动性需求？", options: [{ score: 3, label: "中等" }] }
    ])
  );
  await page.route("**/api/risk-assessments/latest", (route) => fulfill(route, null));
  await page.route("**/api/risk-assessments", (route) =>
    fulfill(route, {
      risk_profile: "C3",
      score: 18,
      effective_from: "2026-07-10",
      effective_to: "2027-07-10",
      expires_soon: false,
      is_expired: false,
      explanation: "中等风险承受能力"
    })
  );
  await page.route("**/api/funds/filter", (route) => fulfill(route, funds));
  await page.route("**/api/funds/compare", (route) => fulfill(route, funds));
  await page.route("**/api/funds/search**", (route) => fulfill(route, funds));
  await page.route("**/api/funds/000001?**", (route) => fulfill(route, fundDetail));
  await page.route("**/api/portfolios/templates", (route) => fulfill(route, templates));
  await page.route("**/api/portfolios/portfolio-main/rebalance-preview", (route) =>
    fulfill(route, {
      portfolio_id: "portfolio-main",
      drift_percent: 10,
      message: "当前偏离超过 5%，可考虑用于恢复比例的再平衡预览，非交易指令。",
      current_stock_ratio: 60,
      current_bond_ratio: 40,
      target_stock_ratio: 50,
      target_bond_ratio: 50,
      triggered: true
    })
  );
  await page.route("**/api/portfolios/portfolio-main/positions/normalize", (route) =>
    {
      portfolioIsNormalized = true;
      return fulfill(route, normalizedPortfolioDetail);
    }
  );
  await page.route("**/api/portfolios/portfolio-main", (route) =>
    fulfill(route, portfolioIsNormalized ? normalizedPortfolioDetail : portfolioDetail)
  );
  await page.route("**/api/portfolios", (route) =>
    route.request().method() === "POST" ? fulfill(route, portfolioDetail) : fulfill(route, [portfolioSummary])
  );
  await page.route("**/api/backtests", (route) => fulfill(route, backtestResult));
  await page.route("**/api/ai/chat", (route) => fulfill(route, chatResponse));
  await page.route("**/api/ai/chat/stream", (route) =>
    route.fulfill({
      status: 200,
      contentType: "text/event-stream",
      body: [
        `data: ${JSON.stringify({ chunk: chatResponse.conclusion })}`,
        "",
        `data: ${JSON.stringify({ chunk: chatResponse.risk })}`,
        "",
        `data: ${JSON.stringify({ done: true, response: chatResponse, meta })}`,
        "",
        ""
      ].join("\n")
    })
  );
}

async function expectChartCanvas(page: Page) {
  await expect
    .poll(async () =>
      page.evaluate(() =>
        Array.from(document.querySelectorAll("canvas")).some((canvas) => canvas.width > 0 && canvas.height > 0)
      )
    )
    .toBe(true);
}

test.beforeEach(async ({ page }) => {
  await mockApi(page);
});

test("editable four-step fund form keeps every applied condition in keyword requests", async ({ page }) => {
  const filterRequests: Array<Record<string, unknown>> = [];
  const legacySearchRequests: string[] = [];
  const runtimeErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") runtimeErrors.push(message.text());
  });
  page.on("pageerror", (error) => runtimeErrors.push(error.message));
  page.on("request", (request) => {
    const pathname = new URL(request.url()).pathname;
    if (pathname.endsWith("/api/funds/filter") && request.method() === "POST") {
      filterRequests.push(request.postDataJSON() as Record<string, unknown>);
    }
    if (pathname.endsWith("/api/funds/search")) {
      legacySearchRequests.push(request.url());
    }
  });

  await page.goto("/funds");
  await expect(page).toHaveTitle(/基金/);
  await expect(page.getByRole("heading", { name: "基金筛选" })).toBeVisible();
  await expect(page.getByText(/Application error|Unhandled Runtime Error/)).toHaveCount(0);
  await expect(page.getByText("稳健配置基金").first()).toBeVisible();

  await page.getByRole("button", { name: "股票型" }).click();
  await page.getByLabel(/规模下限/).fill("20");
  await page.getByLabel(/规模上限/).fill("80");
  await page.getByLabel(/收益排名前/).fill("25");
  await page.getByLabel(/夏普比率下限/).fill("1.5");
  await page.getByRole("checkbox", { name: "最大回撤不高于同类平均" }).uncheck();
  await page.getByLabel(/费率合计上限/).fill("1.2");
  await page.getByLabel(/成立年限下限/).fill("5");
  await page.getByRole("button", { name: "应用筛选" }).click();

  await expect.poll(() => filterRequests.some((body) => (
    body.risk_profile === "C3"
    && JSON.stringify(body.fund_types) === JSON.stringify(["mixed", "bond", "stock"])
    && body.min_years === 5
    && JSON.stringify(body.size_range) === JSON.stringify([20, 80])
    && body.return_rank_percentile === 25
    && body.max_drawdown_lte_category_avg === false
    && body.sharpe_gte === 1.5
    && body.fee_lte === 1.2
  ))).toBe(true);

  const keywordInput = page.getByPlaceholder("按名称或代码服务端搜索");
  await keywordInput.evaluate((element) => element.scrollIntoView({ block: "center" }));
  await keywordInput.fill("000001");
  await expect(page.getByText(/该结果来自用户主动搜索，不视为个性化推荐/)).toBeVisible();
  await expect.poll(() => filterRequests.some((body) => (
    body.keyword === "000001"
    && body.risk_profile === "C3"
    && body.min_years === 5
    && JSON.stringify(body.size_range) === JSON.stringify([20, 80])
    && body.return_rank_percentile === 25
    && body.max_drawdown_lte_category_avg === false
    && body.sharpe_gte === 1.5
    && body.fee_lte === 1.2
  ))).toBe(true);

  await page.getByRole("button", { name: "费用", exact: true }).click();
  await expect.poll(() => filterRequests.some((body) => (
    body.keyword === "000001"
    && body.sort_by === "fee"
    && body.sort_order === "asc"
    && body.risk_profile === "C3"
    && body.min_years === 5
  ))).toBe(true);
  expect(legacySearchRequests).toEqual([]);
  expect(runtimeErrors).toEqual([]);
});

test("unavailable portfolio positions block derived actions without hiding deletion", async ({ page }) => {
  let previewRequests = 0;
  let normalizeRequests = 0;
  await page.unroute("**/api/portfolios");
  await page.unroute("**/api/portfolios/portfolio-main");
  await page.unroute("**/api/portfolios/portfolio-main/rebalance-preview");
  await page.unroute("**/api/portfolios/portfolio-main/positions/normalize");
  await page.route("**/api/portfolios", (route) => fulfill(route, [unavailablePortfolioSummary]));
  await page.route("**/api/portfolios/portfolio-main", (route) => fulfill(route, unavailablePortfolioDetail));
  await page.route("**/api/portfolios/portfolio-main/rebalance-preview", (route) => {
    previewRequests += 1;
    return route.fulfill({ status: 409, body: "unexpected preview request" });
  });
  await page.route("**/api/portfolios/portfolio-main/positions/normalize", (route) => {
    normalizeRequests += 1;
    return route.fulfill({ status: 409, body: "unexpected normalize request" });
  });

  await page.goto("/portfolio");

  await expect(page.getByText("组合含当前不可用持仓")).toBeVisible();
  await expect(page.getByText("当前不可用", { exact: true })).toBeVisible();
  await expect(page.getByRole("button", { name: "一键按归一化比例填充" })).toBeDisabled();
  await expect(page.getByRole("button", { name: "移除 稳健配置基金" })).toBeEnabled();
  await expect(page.getByText("当前股类").locator("..")).toContainText("--");
  await expect(page.getByText("当前债类").locator("..")).toContainText("--");
  await expect(page.getByText("含不可用持仓", { exact: true })).toBeVisible();
  await expect(page.getByText("存在不可用持仓，当前不会生成再平衡结论。")).toBeVisible();
  await expect(page.locator("canvas")).toHaveCount(0);
  expect(previewRequests).toBe(0);
  expect(normalizeRequests).toBe(0);
});

test("main product flow works with mocked API responses", async ({ page }) => {
  await page.goto("/risk-assessment");
  await expect(page.getByText("可承受多大波动？")).toBeVisible();
  const optionButtons = await page.getByRole("button", { name: /3 分/ }).all();
  for (const optionButton of optionButtons) {
    await optionButton.click();
  }
  await expect(page.getByText("6/6")).toBeVisible();
  await page.getByRole("button", { name: "保存测评结果" }).click();
  await expect(page.getByText("C3")).toBeVisible();

  await page.goto("/funds");
  await expect(page.getByText("稳健配置基金").first()).toBeVisible();
  await page.getByRole("button", { name: "比较", exact: true }).first().click();
  await page.getByRole("button", { name: "比较", exact: true }).first().click();
  await expect(page.getByText("已选比较 2/5")).toBeVisible();

  await page.goto("/compare?codes=000001,000002");
  await expect(page.getByText("比较雷达")).toBeVisible();
  await expect(page.getByLabel(/5年年化说明/)).toBeVisible();
  await expectChartCanvas(page);

  await page.goto("/portfolio");
  const templateSelect = page.getByLabel("模板");
  await templateSelect.selectOption("growth");
  await expect(page.getByText(/临时风险画像 C3 与“进取型”模板不匹配/)).toBeVisible();
  await expect(page.getByRole("button", { name: "创建" })).toBeDisabled();
  await templateSelect.selectOption("balanced");
  await expect(page.getByText(/临时风险画像 C3 与“稳健型”模板匹配/)).toBeVisible();
  await page.getByRole("button", { name: "创建" }).click();
  await expect(page.getByRole("heading", { name: "再平衡预览" })).toBeVisible();
  const normalizeButton = page.getByRole("button", { name: "一键按归一化比例填充" });
  await expect(normalizeButton).toBeVisible();
  await normalizeButton.click();
  await expect(normalizeButton).toBeHidden();
  await expectChartCanvas(page);

  await page.goto("/backtest");
  await page.getByRole("button", { name: "运行回测" }).click();
  await expect(page.getByText("组合与基准收益曲线")).toBeVisible();
  await expect(page.getByLabel(/波动率说明/)).toBeVisible();
  await expectChartCanvas(page);
  await page.getByRole("button", { name: "解释本次回测" }).click();
  await expect(page.getByText("这是基于样例数据的投教式解释。")).toBeVisible();

  await page.goto("/assistant");
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("数据来源：mock")).toBeVisible();
  await expect(page.getByText("本内容仅用于投教和个人研究")).toBeVisible();
});
