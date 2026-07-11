async (page) => {
  await page.unroute("**/*").catch(() => {});

  const meta = {
    source: "mock",
    data_updated_at: "2026-07-09T10:00:00Z",
    disclaimer: "mock"
  };
  const fund = {
    code: "000001",
    name: "Stable Allocation Fund",
    fund_type: "mixed",
    risk_level: "R3",
    manager_name: "Manager One",
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
  };
  const detailRequests = [];
  const fulfill = (route, data) => route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data, meta })
  });

  await page.route("**/api/risk-assessments/latest", (route) => fulfill(route, {
    risk_profile: "C4",
    score: 26,
    effective_from: "2026-07-10",
    effective_to: "2027-07-10",
    expires_soon: false,
    is_expired: false,
    explanation: "Higher risk capacity"
  }));
  await page.route("**/api/funds/filter", (route) => fulfill(route, [fund]));
  await page.route("**/api/funds/000001?**", (route) => {
    detailRequests.push(route.request().url());
    return fulfill(route, {
      ...fund,
      navs: [{ trade_date: "2026-07-09", nav: 1.23, accumulated_nav: 1.45 }],
      ai_summary: "Mock detail summary.",
      fee_summary: {
        management_fee: 1.2,
        custody_fee: 0.2,
        total_fee: 1.4,
        explanation: "Mock fee summary."
      },
      manager_profile: {
        name: "Manager One",
        years: 6,
        inception_date: "2018-01-01",
        explanation: "Mock manager profile."
      },
      metric_explanations: [
        { key: "return", label: "Return", value: "8.12%", explanation: "Mock metric explanation." }
      ],
      risk_match: {
        user_risk_profile: "C4",
        fund_risk_level: "R3",
        matched: true,
        message: "Mock risk match."
      }
    });
  });

  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto("http://localhost:3001/funds");
  await page.waitForFunction(() => document.body.innerText.includes("Stable Allocation Fund"), { timeout: 10000 });
  await page.waitForFunction(() => document.body.innerText.includes("C4"), { timeout: 10000 });

  return {
    ok: detailRequests.some((url) => url.includes("risk_profile=C4")),
    detailRequests
  };
}
