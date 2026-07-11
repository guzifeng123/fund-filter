async (page) => {
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
  const detail = {
    ...funds[0],
    navs: [
      { trade_date: "2025-12-31", nav: 1.12, accumulated_nav: 1.22 },
      { trade_date: "2026-07-09", nav: 1.23, accumulated_nav: 1.45 }
    ],
    ai_summary: "样例摘要，仅用于移动端布局检查。",
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
  const meta = {
    source: "mock",
    data_updated_at: "2026-07-09T10:00:00Z",
    disclaimer: "mock"
  };

  await page.setViewportSize({ width: 390, height: 844 });
  await page.route("**/api/funds/filter", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data: funds, meta })
  }));
  await page.route("**/api/funds/compare", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data: funds, meta })
  }));
  await page.route("**/api/funds/000001?**", (route) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data: detail, meta })
  }));

  const measure = async (url) => {
    await page.goto(url);
    await page.waitForLoadState("networkidle");
    return page.evaluate(() => ({
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
        }))
    }));
  };

  return {
    funds: await measure("http://localhost:3000/funds"),
    compare: await measure("http://localhost:3000/compare?codes=000001,000002")
  };
}
