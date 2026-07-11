async (page) => {
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
    metric_explanations: [
      { key: "return", label: "收益", value: "8.12%", explanation: "历史收益不代表未来。" }
    ],
    risk_match: {
      user_risk_profile: "C3",
      fund_risk_level: "R3",
      matched: true,
      message: "该基金风险等级未超过当前承受能力。"
    }
  };
  const templates = [
    { id: "conservative", name: "稳健型", stock_ratio: 30, bond_ratio: 70, suitable_profiles: ["C2", "C3"] },
    { id: "balanced", name: "平衡型", stock_ratio: 50, bond_ratio: 50, suitable_profiles: ["C3", "C4"] },
    { id: "growth", name: "成长型", stock_ratio: 70, bond_ratio: 30, suitable_profiles: ["C4", "C5"] }
  ];
  const portfolioSummary = {
    id: "portfolio-main",
    name: "我的稳健组合",
    template_key: "balanced",
    stock_ratio: 50,
    bond_ratio: 50,
    position_count: 2
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
        normalized_weight_percent: 60
      },
      {
        fund_code: "000002",
        fund_name: "安心债券基金",
        fund_type: "bond",
        risk_level: "R2",
        weight_percent: 40,
        normalized_weight_percent: 40
      }
    ],
    total_weight_percent: 100,
    weight_warning: null
  };
  const rebalancePreview = {
    portfolio_id: "portfolio-main",
    drift_percent: 10,
    message: "当前偏离超过 5%，可考虑用于恢复比例的再平衡预览，非交易指令。",
    current_stock_ratio: 60,
    current_bond_ratio: 40,
    target_stock_ratio: 50,
    target_bond_ratio: 50,
    triggered: true
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

  const fulfill = (route, data) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data, meta })
  });
  await page.route("**/api/risk-assessments/questions", (route) => fulfill(route, [
    { id: "q1", title: "可承受多大波动？", options: [{ score: 3, label: "中等波动" }] },
    { id: "q2", title: "投资期限？", options: [{ score: 3, label: "三年以上" }] },
    { id: "q3", title: "亏损反应？", options: [{ score: 3, label: "继续观察" }] },
    { id: "q4", title: "收入稳定性？", options: [{ score: 3, label: "较稳定" }] },
    { id: "q5", title: "投资经验？", options: [{ score: 3, label: "有经验" }] },
    { id: "q6", title: "流动性需求？", options: [{ score: 3, label: "中等" }] }
  ]));
  await page.route("**/api/risk-assessments/latest", (route) => fulfill(route, null));
  await page.route("**/api/risk-assessments", (route) => fulfill(route, {
    risk_profile: "C3",
    score: 18,
    effective_from: "2026-07-10",
    effective_to: "2027-07-10",
    expires_soon: false,
    is_expired: false,
    explanation: "中等风险承受能力"
  }));
  await page.route("**/api/funds/filter", (route) => fulfill(route, funds));
  await page.route("**/api/funds/compare", (route) => fulfill(route, funds));
  await page.route("**/api/funds/search**", (route) => fulfill(route, funds));
  await page.route("**/api/funds/000001?**", (route) => fulfill(route, fundDetail));
  await page.route("**/api/portfolios/templates", (route) => fulfill(route, templates));
  await page.route("**/api/portfolios/portfolio-main/rebalance-preview", (route) => fulfill(route, rebalancePreview));
  await page.route("**/api/portfolios/portfolio-main", (route) => fulfill(route, portfolioDetail));
  await page.route("**/api/portfolios", (route) => {
    if (route.request().method() === "POST") {
      return fulfill(route, portfolioDetail);
    }
    return fulfill(route, [portfolioSummary]);
  });
  await page.route("**/api/backtests", (route) => fulfill(route, backtestResult));
  await page.route("**/api/ai/chat", (route) => fulfill(route, chatResponse));
  await page.route("**/api/ai/chat/stream", (route) => route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: [
      `data: ${JSON.stringify({ chunk: chatResponse.conclusion })}`,
      "",
      `data: ${JSON.stringify({ chunk: chatResponse.risk })}`,
      "",
      `data: ${JSON.stringify({ done: true, response: chatResponse })}`,
      "",
      ""
    ].join("\n")
  }));

  const expectText = async (text) => {
    await page.locator(`text=${text}`).first().waitFor({ timeout: 10000 });
  };
  const canvasSummary = async () => page.evaluate(() =>
    Array.from(document.querySelectorAll("canvas")).map((canvas) => ({
      width: canvas.width,
      height: canvas.height,
      clientWidth: canvas.clientWidth,
      clientHeight: canvas.clientHeight
    }))
  );
  const waitForChartCanvas = async () => {
    await page.waitForFunction(() => document.querySelectorAll("canvas").length > 0, { timeout: 10000 });
  };

  const checks = {};

  await page.setViewportSize({ width: 1280, height: 900 });
  await page.goto("http://localhost:3000/risk-assessment");
  await page.waitForSelector("text=可承受多大波动？");
  await page.evaluate(() => {
    for (const button of Array.from(document.querySelectorAll("button"))) {
      if (button.textContent?.includes("3 分")) {
        button.click();
      }
    }
  });
  await expectText("6/6");
  await page.locator("button", { hasText: "保存测评结果" }).click();
  await expectText("C3");
  checks.riskAssessment = { ok: true };

  await page.goto("http://localhost:3000/funds");
  await expectText("稳健配置基金");
  await page.locator("button", { hasText: "比较" }).first().click();
  await page.locator("button", { hasText: "比较" }).first().click();
  await expectText("已选比较 2/5");
  checks.funds = { ok: true };

  await page.goto("http://localhost:3000/compare?codes=000001,000002");
  await expectText("比较雷达");
  await waitForChartCanvas();
  const compareCanvases = await canvasSummary();
  checks.compare = { ok: compareCanvases.some((item) => item.width > 0 && item.height > 0), canvases: compareCanvases };

  await page.goto("http://localhost:3000/portfolio");
  await page.locator("button", { hasText: "创建" }).click();
  await expectText("再平衡预览");
  await waitForChartCanvas();
  const portfolioCanvases = await canvasSummary();
  checks.portfolio = { ok: portfolioCanvases.some((item) => item.width > 0 && item.height > 0), canvases: portfolioCanvases };

  await page.goto("http://localhost:3000/backtest");
  await page.locator("button", { hasText: "运行回测" }).click();
  await expectText("组合与基准收益曲线");
  await waitForChartCanvas();
  const backtestCanvases = await canvasSummary();
  await page.locator("button", { hasText: "解释本次回测" }).click();
  await expectText("这是基于样例数据的投教式解释。");
  checks.backtest = { ok: backtestCanvases.some((item) => item.width > 0 && item.height > 0), canvases: backtestCanvases };

  await page.goto("http://localhost:3000/assistant");
  await page.locator("button", { hasText: "发送" }).click();
  await expectText("本内容仅用于投教和个人研究");
  checks.assistant = { ok: true };

  const failed = Object.entries(checks).filter(([, value]) => !value.ok).map(([key]) => key);
  return { ok: failed.length === 0, failed, checks };
}
