import { expect, test, type Page, type Route, type TestInfo } from "@playwright/test";

const disclaimer = "本工具基于历史数据，仅供分析学习，不构成投资建议。历史表现不预示未来收益。";
const freshMeta = {
  source: "state-fixture",
  data_updated_at: "2026-07-13T08:00:00Z",
  disclaimer
};
const fund = {
  code: "000001",
  name: "状态测试基金",
  fund_type: "mixed",
  risk_level: "R3",
  manager_name: "测试经理",
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
  source: "state-fixture",
  data_updated_at: "2020-01-01T08:00:00Z"
};
const fundDetail = {
  ...fund,
  navs: [{ trade_date: "2020-01-01", nav: 1.1, accumulated_nav: 1.1 }],
  ai_summary: "用于 stale 状态浏览器断言。",
  fee_summary: null,
  manager_profile: null,
  metric_explanations: [],
  risk_match: {
    user_risk_profile: "C3",
    fund_risk_level: "R3",
    matched: true,
    message: "风险匹配。"
  }
};

function fulfill(route: Route, data: unknown, meta = freshMeta) {
  return route.fulfill({
    status: 200,
    contentType: "application/json",
    body: JSON.stringify({ data, meta })
  });
}

async function mockFundPageBase(page: Page) {
  await page.route("**/api/risk-assessments/latest", (route) => fulfill(route, null));
  await page.route("**/api/data/status", (route) =>
    fulfill(route, {
      db_connected: true,
      fund_count: 1,
      nav_count: 1,
      latest_data_updated_at: freshMeta.data_updated_at,
      freshness_status: "fresh",
      stale_after_days: 7,
      last_job: null
    })
  );
}

async function archiveScreenshot(page: Page, testInfo: TestInfo, name: string) {
  await page.screenshot({ path: testInfo.outputPath(`${name}.png`), fullPage: true });
}

test("empty fund result renders an actionable empty state", async ({ page }, testInfo) => {
  await mockFundPageBase(page);
  await page.route("**/api/funds/filter", (route) => fulfill(route, []));

  await page.goto("/funds");

  await expect(page.getByText("没有符合条件的基金")).toBeVisible();
  await expect(page.getByText("可以放宽夏普、费用、规模或基金类型条件后重新应用筛选。")).toBeVisible();
  await archiveScreenshot(page, testInfo, "empty-funds");
});

test("stale fund data renders freshness warnings with usable old data", async ({ page }, testInfo) => {
  await mockFundPageBase(page);
  const staleMeta = { ...freshMeta, data_updated_at: "2020-01-01T08:00:00Z" };
  await page.route("**/api/funds/filter", (route) => fulfill(route, [fund], staleMeta));
  await page.route("**/api/funds/000001?**", (route) => fulfill(route, fundDetail, staleMeta));

  await page.goto("/funds");

  await expect(page.getByText("状态测试基金").first()).toBeVisible();
  await expect(page.getByText(/数据更新时间为 .*已超过 7 天/).first()).toBeVisible();
  await expect(page.getByText(disclaimer).first()).toBeVisible();
  await archiveScreenshot(page, testInfo, "stale-funds");
});

test("failed sync status exposes the upstream error and recent job", async ({ page }, testInfo) => {
  const failedJob = {
    id: 9,
    name: "sync_fund_profiles",
    status: "failed",
    started_at: "2026-07-13T07:00:00Z",
    finished_at: "2026-07-13T07:00:02Z",
    error_detail: "上游接口超时",
    details: { error: "上游接口超时" }
  };
  const runningJob = {
    ...failedJob,
    id: 10,
    name: "sync_fund_navs",
    status: "running",
    finished_at: null,
    error_detail: null,
    details: {}
  };
  await page.route("**/api/data/status", (route) =>
    fulfill(route, {
      db_connected: true,
      fund_count: 4,
      nav_count: 24,
      latest_data_updated_at: freshMeta.data_updated_at,
      freshness_status: "failed",
      stale_after_days: 7,
      last_job: failedJob
    })
  );
  await page.route("**/api/data/jobs/recent?**", (route) => fulfill(route, [failedJob]));
  await page.route("**/api/data/scheduler/status", (route) =>
    fulfill(route, {
      enabled: true,
      running: true,
      schedule_mode: "cron",
      schedule_expression: "15 2 * * *",
      timezone: "Asia/Shanghai",
      jitter_seconds: 300,
      misfire_grace_seconds: 900,
      next_run_at: "2026-07-14T02:15:00+08:00",
      running_tasks: [runningJob]
    })
  );

  await page.goto("/settings");

  await expect(page.getByText("最近一次数据同步失败")).toBeVisible();
  await expect(page.getByText("上游接口超时")).toHaveCount(2);
  await expect(page.getByText("sync_fund_profiles")).toBeVisible();
  await expect(page.getByText("sync_fund_navs")).toBeVisible();
  await expect(page.getByText("cron · 15 2 * * *")).toBeVisible();
  await archiveScreenshot(page, testInfo, "failed-sync");
});

test("API 500 renders retry guidance instead of a blank fund list", async ({ page }, testInfo) => {
  await mockFundPageBase(page);
  await page.route("**/api/funds/filter", (route) =>
    route.fulfill({
      status: 500,
      contentType: "application/json",
      body: JSON.stringify({
        error: { code: "internal_error", message: "状态场景故障", detail: null },
        meta: freshMeta
      })
    })
  );

  await page.goto("/funds");

  await expect(page.getByText("基金筛选失败")).toBeVisible();
  await expect(page.getByRole("button", { name: "重试" })).toBeVisible();
  await expect(page.getByText("状态场景故障")).toBeVisible();
  await archiveScreenshot(page, testInfo, "api-500-funds");
});
