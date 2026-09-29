import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { isDataStale, StaleDataNotice } from "@/components/stale-data-notice";

describe("StaleDataNotice", () => {
  const now = new Date("2026-07-09T12:00:00Z");

  beforeEach(() => {
    vi.useFakeTimers();
    vi.setSystemTime(now);
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("detects stale data after the configured threshold", () => {
    expect(isDataStale("2026-07-01T11:59:59Z", 7, now)).toBe(true);
    expect(isDataStale("2026-07-03T12:00:00Z", 7, now)).toBe(false);
  });

  it("does not mark missing or invalid dates as stale", () => {
    expect(isDataStale(null, 7, now)).toBe(false);
    expect(isDataStale("not-a-date", 7, now)).toBe(false);
  });

  it("renders stale data guidance when data is outdated", () => {
    const html = renderToStaticMarkup(
      <StaleDataNotice updatedAt="2026-06-30T10:00:00Z" staleAfterDays={7} />
    );

    expect(html).toContain("已超过 7 天");
    expect(html).toContain("请先同步或确认数据源状态");
  });

  it("renders nothing for fresh data", () => {
    const html = renderToStaticMarkup(
      <StaleDataNotice updatedAt="2026-07-09T10:00:00Z" staleAfterDays={7} />
    );

    expect(html).toBe("");
  });

  it("renders an explicit unknown state for a loaded response without data time", () => {
    const html = renderToStaticMarkup(<StaleDataNotice updatedAt={null} />);

    expect(html).toContain("数据更新时间未知");
    expect(html).toContain("最近同步记录");
  });

  it("renders nothing before a response is available", () => {
    expect(renderToStaticMarkup(<StaleDataNotice updatedAt={undefined} />)).toBe("");
  });
});
