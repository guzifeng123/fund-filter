import AxeBuilder from "@axe-core/playwright";
import { expect, test, type Page, type Route } from "@playwright/test";

const meta = {
  source: "mock",
  data_updated_at: "2026-07-14T10:00:00Z",
  disclaimer: "仅用于自动化无障碍测试。"
};

const dataStatus = {
  db_connected: true,
  source: "mock",
  fund_count: 2,
  nav_count: 4,
  latest_data_updated_at: "2026-07-14T10:00:00Z",
  freshness_status: "fresh",
  stale_after_days: 7,
  last_job: null
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
    data_updated_at: "2026-07-14T10:00:00Z",
    snapshot_generation_id: "accessibility-snapshot"
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
    data_updated_at: "2026-07-14T10:00:00Z",
    snapshot_generation_id: "accessibility-snapshot"
  }
];

const portfolioSummary = {
  id: "portfolio-accessibility",
  name: "无障碍测试组合",
  template_key: "balanced",
  stock_ratio: 50,
  bond_ratio: 50,
  position_count: 2,
  unavailable_position_count: 0
};

function fulfill(route: Route, data: unknown) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data, meta })
  });
}

async function mockAccessibilityApi(
  page: Page,
  { unavailablePortfolio = false }: { unavailablePortfolio?: boolean } = {}
) {
  const activePortfolioSummary = unavailablePortfolio
    ? { ...portfolioSummary, unavailable_position_count: 1 }
    : portfolioSummary;
  await page.route("**/api/**", (route) => {
    const pathname = new URL(route.request().url()).pathname;
    if (pathname === "/api/dashboard") {
      return fulfill(route, {
        risk_profile: "C3",
        risk_status: "valid",
        risk_notice: "风险测评在有效期内。",
        health: "暂不可用",
        portfolio_health_status: "unavailable",
        watchlist_updated_at: null,
        watchlist_status: "not_configured",
        alerts: [],
        alerts_status: "not_configured",
        data_status: dataStatus,
        recent_job: null
      });
    }
    if (pathname === "/api/risk-assessments/questions") {
      return fulfill(
        route,
        Array.from({ length: 6 }, (_, index) => ({
          id: `q${index + 1}`,
          title: `风险问题 ${index + 1}`,
          options: [
            { score: 1, label: "较低" },
            { score: 3, label: "中等" },
            { score: 5, label: "较高" }
          ]
        }))
      );
    }
    if (pathname === "/api/risk-assessments/latest") {
      return fulfill(route, null);
    }
    if (pathname === "/api/risk-assessments") {
      return fulfill(route, {
        risk_profile: "C3",
        score: 18,
        effective_from: "2026-07-14",
        effective_to: "2027-07-14",
        expires_soon: false,
        is_expired: false,
        explanation: "中等风险承受能力"
      });
    }
    if (pathname === "/api/funds/filter" || pathname === "/api/funds/search") {
      return fulfill(route, funds);
    }
    if (pathname === "/api/funds/compare") {
      return fulfill(route, funds);
    }
    if (pathname === "/api/funds/000001") {
      return fulfill(route, {
        ...funds[0],
        navs: [
          { trade_date: "2026-07-11", nav: 1.1, accumulated_nav: 1.2 },
          { trade_date: "2026-07-14", nav: 1.2, accumulated_nav: 1.3 }
        ],
        ai_summary: "历史数据解释。",
        fee_summary: {
          management_fee: 1.2,
          custody_fee: 0.2,
          total_fee: 1.4,
          explanation: "费用仅用于历史说明。"
        },
        manager_profile: {
          name: "王一",
          years: 6,
          inception_date: "2018-01-01",
          explanation: "经理年限说明。"
        },
        metric_explanations: [],
        risk_match: {
          user_risk_profile: "C3",
          fund_risk_level: "R3",
          matched: true,
          message: "风险等级未超过当前承受能力。"
        }
      });
    }
    if (pathname === "/api/portfolios/templates") {
      return fulfill(route, [
        { id: "conservative", name: "保守型", stock_ratio: 20, bond_ratio: 80, suitable_profiles: ["C1", "C2"] },
        { id: "balanced", name: "稳健型", stock_ratio: 50, bond_ratio: 50, suitable_profiles: ["C2", "C3"] },
        { id: "growth", name: "进取型", stock_ratio: 80, bond_ratio: 20, suitable_profiles: ["C4", "C5"] }
      ]);
    }
    if (pathname === "/api/portfolios") {
      return fulfill(route, [activePortfolioSummary]);
    }
    if (pathname === "/api/portfolios/portfolio-accessibility") {
      return fulfill(route, {
        ...activePortfolioSummary,
        positions: [
          { fund_code: "000001", fund_name: "稳健配置基金", fund_type: "mixed", risk_level: "R3", weight_percent: 50, normalized_weight_percent: 50, available: !unavailablePortfolio },
          { fund_code: "000002", fund_name: "安心债券基金", fund_type: "bond", risk_level: "R2", weight_percent: 50, normalized_weight_percent: 50, available: true }
        ],
        total_weight_percent: 100,
        weight_warning: null
      });
    }
    if (pathname === "/api/portfolios/portfolio-accessibility/rebalance-preview") {
      return fulfill(route, {
        portfolio_id: "portfolio-accessibility",
        drift_percent: 0,
        message: "当前偏离未超过阈值，非交易指令。",
        current_stock_ratio: 50,
        current_bond_ratio: 50,
        target_stock_ratio: 50,
        target_bond_ratio: 50,
        triggered: false
      });
    }
    if (pathname === "/api/data/status") {
      return fulfill(route, dataStatus);
    }
    if (pathname === "/api/data/jobs/recent") {
      return fulfill(route, []);
    }
    if (pathname === "/api/data/scheduler/status") {
      return fulfill(route, {
        enabled: false,
        running: false,
        schedule_mode: "interval",
        schedule_expression: "every 24 hour(s)",
        timezone: "Asia/Shanghai",
        jitter_seconds: 300,
        misfire_grace_seconds: 900,
        next_run_at: null,
        running_tasks: []
      });
    }
    if (pathname === "/api/settings/runtime") {
      return fulfill(route, {
        data_source: {
          configured_source: "sample_local",
          configured_profile: null,
          actual_source: "mock",
          configured: true
        },
        llm: { provider: "mock", model: "local", configured: false, mock_mode: true },
        yingmi_mcp: { configured: false, implemented: false },
        risk_assessment: { validity_months: 12 },
        cleanup: {
          method: "manual_script",
          dry_run_supported: true,
          automatic_cleanup_supported: false
        }
      });
    }
    return route.fulfill({ status: 404, body: "unmocked accessibility endpoint" });
  });
}

const auditedRoutes = [
  "/dashboard",
  "/risk-assessment",
  "/funds",
  "/compare?codes=000001,000002",
  "/portfolio",
  "/backtest",
  "/assistant",
  "/learn",
  "/settings"
];

async function expectNoWcagViolations(
  page: Page,
  route: string,
  readyText?: string | RegExp
) {
  await page.goto(route);
  await expect(page.locator("h1")).toBeVisible();
  if (readyText) await expect(page.getByText(readyText)).toBeVisible();
  await expect(page.getByText(/Application error|Unhandled Runtime Error/)).toHaveCount(0);
  const results = await new AxeBuilder({ page })
    .withTags(["wcag2a", "wcag2aa", "wcag21a", "wcag21aa"])
    .analyze();
  const violationSummary = results.violations.map(({ id, impact, nodes }) => ({
    id,
    impact,
    nodes: nodes.map(({ target, failureSummary }) => ({ target, failureSummary }))
  }));
  expect(violationSummary, `${route}: automated WCAG A/AA violations`).toEqual([]);
}

test.beforeEach(async ({ page }) => {
  await mockAccessibilityApi(page);
});

for (const route of auditedRoutes) {
  test(`${route} has no automated WCAG A/AA violations`, async ({ page }) => {
    await expectNoWcagViolations(page, route);
  });
}

for (const route of ["/funds", "/assistant"]) {
  test(`${route} has no automated WCAG A/AA violations on mobile`, async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await expectNoWcagViolations(page, route);
  });
}

test("/portfolio unavailable-position state has no automated WCAG A/AA violations", async ({ page }) => {
  await page.unroute("**/api/**");
  await mockAccessibilityApi(page, { unavailablePortfolio: true });
  await expectNoWcagViolations(page, "/portfolio", "组合含当前不可用持仓");
});
