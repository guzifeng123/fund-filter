import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { DataStatusNotice } from "@/components/data-status-notice";
import type { DataStatus } from "@/lib/api/types";

const baseStatus: DataStatus = {
  db_connected: true,
  fund_count: 2,
  nav_count: 4,
  latest_data_updated_at: "2026-07-01T10:00:00Z",
  freshness_status: "fresh",
  stale_after_days: 7,
  last_job: null
};

describe("DataStatusNotice", () => {
  it("does not render for fresh data", () => {
    expect(renderToStaticMarkup(<DataStatusNotice status={baseStatus} />)).toBe("");
  });

  it("renders stale guidance with the configured threshold", () => {
    const html = renderToStaticMarkup(
      <DataStatusNotice status={{ ...baseStatus, freshness_status: "stale" }} />
    );
    expect(html).toContain("数据已超过新鲜度阈值");
    expect(html).toContain("超过 7 天");
  });

  it("renders the latest synchronization error", () => {
    const html = renderToStaticMarkup(
      <DataStatusNotice
        status={{
          ...baseStatus,
          freshness_status: "failed",
          last_job: {
            name: "sync_all",
            status: "failed",
            finished_at: "2026-07-10T10:00:00Z",
            error_detail: "上游连接超时"
          }
        }}
      />
    );
    expect(html).toContain("最近一次数据同步失败");
    expect(html).toContain("上游连接超时");
  });
});
