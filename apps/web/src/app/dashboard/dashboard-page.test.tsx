import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DashboardContent } from "@/app/dashboard/page";
import type { DashboardData } from "@/lib/api/types";

const dashboard: DashboardData = {
  risk_profile: "C4",
  risk_status: "valid",
  risk_notice: "风险测评仍在有效期内",
  health: "unavailable",
  portfolio_health_status: "unavailable",
  watchlist_updated_at: null,
  watchlist_status: "not_configured",
  alerts: [],
  alerts_status: "not_configured",
  data_status: {
    db_connected: true,
    source: "public_http_json",
    fund_count: 12,
    nav_count: 240,
    latest_data_updated_at: "2026-07-13T08:15:00Z",
    freshness_status: "failed",
    stale_after_days: 7,
    last_job: {
      name: "sync_fund_navs",
      status: "failed",
      finished_at: "2026-07-13T08:16:00Z",
      error_detail: "上游连接超时"
    }
  },
  recent_job: {
    id: 7,
    name: "sync_fund_navs",
    status: "failed",
    started_at: "2026-07-13T08:14:00Z",
    finished_at: "2026-07-13T08:16:00Z",
    error_detail: "上游连接超时",
    details: { error: "上游连接超时" }
  }
};

describe("DashboardContent", () => {
  it("renders persisted status and explicit unavailable feature states", () => {
    const html = renderToStaticMarkup(<DashboardContent dashboard={dashboard} />);

    expect(html).toContain("public_http_json");
    expect(html).toContain("2026-07-13");
    expect(html).toContain("上游连接超时");
    expect(html).toContain("风险测评仍在有效期内");
    expect(html).toContain("组合健康计算尚未接入");
    expect(html).toContain("自选基金数据表尚未接入");
    expect(html).toContain("业务提醒未配置");
    expect(html).not.toContain("20:30");
    expect(html).not.toContain("补偿同步");
    expect(html).not.toContain("当前组合未触发再平衡阈值");
  });

  it("uses the dashboard response as the page's single status source", () => {
    const source = readFileSync(path.join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("queryFn: apiClient.dashboard");
    expect(source).not.toContain("apiClient.dataStatus");
    expect(source).not.toContain("apiClient.recentDataJobs");
    expect(source.match(/useQuery\(/g)).toHaveLength(1);
  });
});
