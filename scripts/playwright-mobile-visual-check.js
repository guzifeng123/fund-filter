async (page) => {
  const baseUrl = page.url().split("/").slice(0, 3).join("/");
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
    ai_summary: "样例摘要，仅用于移动端视觉检查。",
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
    { id: "balanced", name: "平衡型", stock_ratio: 50, bond_ratio: 50, suitable_profiles: ["C3", "C4"] }
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
  const dataStatus = {
    db_connected: true,
    fund_count: 2,
    nav_count: 4,
    latest_data_updated_at: "2026-07-09T10:00:00Z",
    freshness_status: "fresh",
    stale_after_days: 7,
    last_job: { name: "sync_all", status: "success", finished_at: "2026-07-09T10:00:00Z", error_detail: null }
  };
  const recentJobs = [
    { id: 1, name: "sync_all", status: "success", started_at: "2026-07-09T09:59:00Z", finished_at: "2026-07-09T10:00:00Z", error_detail: null, details: {} }
  ];
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
    references: ["funds:000001"],
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

  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/dashboard", (route) => fulfill(route, {
    risk_profile: "C3",
    health: "稳健",
    watchlist_updated_at: "2026-07-09T10:00:00Z",
    alerts: ["组合偏离处于观察区间"]
  }));
  await page.route("**/api/data/status", (route) => fulfill(route, dataStatus));
  await page.route("**/api/data/jobs/recent**", (route) => fulfill(route, recentJobs));
  await page.route("**/api/data/sync**", (route) => fulfill(route, { task: "all", result: {} }));
  await page.route("**/api/risk-assessments/questions", (route) => fulfill(route, [
    { id: "q1", title: "可承受多大波动？", options: [{ score: 3, label: "中等波动" }] }
  ]));
  await page.route("**/api/risk-assessments/latest", (route) => fulfill(route, {
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
  await page.route("**/api/portfolios", (route) => fulfill(route, [portfolioSummary]));
  await page.route("**/api/backtests", (route) => fulfill(route, backtestResult));
  await page.route("**/api/ai/chat/stream", (route) => route.fulfill({
    status: 200,
    contentType: "text/event-stream",
    body: [
      `data: ${JSON.stringify({ chunk: chatResponse.conclusion })}`,
      "",
      `data: ${JSON.stringify({ done: true, response: chatResponse })}`,
      "",
      ""
    ].join("\n")
  }));

  const waitForText = async (text) => page.waitForFunction(
    (expected) => document.body.innerText.includes(expected),
    text,
    { timeout: 10000 }
  );
  const measure = async (name, url, expectedText, requiresCanvas = false) => {
    try {
      await page.goto(url);
      await waitForText(expectedText);
      if (requiresCanvas) {
        await page.waitForFunction(() => document.querySelectorAll("canvas").length > 0, { timeout: 10000 });
      }
    } catch (error) {
      throw new Error(`${name} (${url}) failed while waiting for "${expectedText}": ${error.message}`);
    }
    return page.evaluate((pageName) => {
      const overflowingElements = Array.from(document.querySelectorAll("body *"))
        .filter((element) => element.scrollWidth > element.clientWidth + 1 && getComputedStyle(element).overflowX !== "auto")
        .slice(0, 10)
        .map((element) => ({
          tag: element.tagName.toLowerCase(),
          className: element.getAttribute("class") ?? "",
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
          text: (element.textContent ?? "").trim().slice(0, 40)
        }));
      const canvases = Array.from(document.querySelectorAll("canvas")).map((canvas) => ({
        width: canvas.width,
        height: canvas.height,
        clientWidth: canvas.clientWidth,
        clientHeight: canvas.clientHeight
      }));
      return {
        name: pageName,
        path: window.location.pathname,
        viewportWidth: document.documentElement.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
        documentScrollWidth: document.documentElement.scrollWidth,
        overflowingElements,
        canvases
      };
    }, name);
  };

  const results = [
    await measure("dashboard", `${baseUrl}/dashboard`, "个人首页"),
    await measure("riskAssessment", `${baseUrl}/risk-assessment`, "风险测评"),
    await measure("funds", `${baseUrl}/funds`, "稳健配置基金"),
    await measure("compare", `${baseUrl}/compare?codes=000001,000002`, "比较雷达", true),
    await measure("portfolio", `${baseUrl}/portfolio`, "再平衡预览", true),
    await measure("backtestInitial", `${baseUrl}/backtest`, "尚未运行回测"),
    await (async () => {
      await page.locator("button", { hasText: "运行回测" }).click();
      await waitForText("组合与基准收益曲线");
      await page.waitForFunction(() => document.querySelectorAll("canvas").length > 0, { timeout: 10000 });
      return page.evaluate(() => ({
        name: "backtestResult",
        path: window.location.pathname,
        viewportWidth: document.documentElement.clientWidth,
        bodyScrollWidth: document.body.scrollWidth,
        documentScrollWidth: document.documentElement.scrollWidth,
        overflowingElements: Array.from(document.querySelectorAll("body *"))
          .filter((element) => element.scrollWidth > element.clientWidth + 1 && getComputedStyle(element).overflowX !== "auto")
          .slice(0, 10)
          .map((element) => ({
            tag: element.tagName.toLowerCase(),
            className: element.getAttribute("class") ?? "",
            clientWidth: element.clientWidth,
            scrollWidth: element.scrollWidth,
            text: (element.textContent ?? "").trim().slice(0, 40)
          })),
        canvases: Array.from(document.querySelectorAll("canvas")).map((canvas) => ({
          width: canvas.width,
          height: canvas.height,
          clientWidth: canvas.clientWidth,
          clientHeight: canvas.clientHeight
        }))
      }));
    })(),
    await measure("assistant", `${baseUrl}/assistant`, "AI 分析助手"),
    await measure("settings", `${baseUrl}/settings`, "设置")
  ];

  const failures = results
    .filter((result) => result.bodyScrollWidth > result.viewportWidth || result.documentScrollWidth > result.viewportWidth || result.overflowingElements.length > 0)
    .map((result) => result.name);
  const chartFailures = results
    .filter((result) => ["compare", "portfolio", "backtestResult"].includes(result.name))
    .filter((result) => !result.canvases.some((canvas) => canvas.width > 0 && canvas.height > 0))
    .map((result) => result.name);

  return {
    ok: failures.length === 0 && chartFailures.length === 0,
    failures,
    chartFailures,
    results
  };
}
