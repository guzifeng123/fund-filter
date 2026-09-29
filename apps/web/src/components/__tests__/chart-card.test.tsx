import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ChartCard } from "@/components/chart-card";

describe("ChartCard business states", () => {
  it("renders loading without mounting a zero-value chart", () => {
    const html = renderToStaticMarkup(<ChartCard title="组合比例" status="loading" />);

    expect(html).toContain("组合比例加载中");
    expect(html).not.toContain("echarts");
  });

  it("renders an explicit empty state instead of a 0/0 chart", () => {
    const html = renderToStaticMarkup(
      <ChartCard
        title="组合比例"
        status="empty"
        emptyTitle="尚无持仓"
        emptyDescription="添加持仓后再查看股债比例。"
      />
    );

    expect(html).toContain("尚无持仓");
    expect(html).toContain("添加持仓后再查看股债比例");
  });

  it("renders retryable errors", () => {
    const html = renderToStaticMarkup(
      <ChartCard title="历史净值" status="error" onRetry={() => undefined} />
    );

    expect(html).toContain("历史净值加载失败");
    expect(html).toContain("重试");
  });

  it("renders stale guidance together with a ready chart contract", () => {
    const html = renderToStaticMarkup(
      <ChartCard
        title="历史净值"
        status="stale"
        staleMessage="数据日期已过期"
        option={{ series: [] }}
      />
    );

    expect(html).toContain("数据日期已过期");
  });
});
