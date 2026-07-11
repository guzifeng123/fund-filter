import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { FundTable } from "@/features/funds/fund-table";
import type { Fund } from "@/lib/api/types";

const baseFund: Fund = {
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
  source: "sample_local",
  data_updated_at: "2026-07-09T10:00:00Z"
};

function makeFund(code: string, overrides: Partial<Fund> = {}): Fund {
  return {
    ...baseFund,
    code,
    name: `${baseFund.name}${code}`,
    ...overrides
  };
}

describe("FundTable", () => {
  it("disables adding more funds when the compare pool already has five funds", () => {
    const html = renderToStaticMarkup(
      <FundTable
        funds={[makeFund("000006")]}
        selectedCode="000006"
        compareCodes={["000001", "000002", "000003", "000004", "000005"]}
        riskProfile="C3"
        onSelect={vi.fn()}
        onCompare={vi.fn()}
        onRemoveCompare={vi.fn()}
      />
    );

    expect(html).toContain("disabled");
    expect(html).toContain("比较池已满，最多 5 只基金");
    expect(html).toContain("比较");
  });

  it("marks funds above the user risk profile", () => {
    const html = renderToStaticMarkup(
      <FundTable
        funds={[makeFund("000007", { risk_level: "R4" })]}
        compareCodes={[]}
        riskProfile="C3"
        onSelect={vi.fn()}
        onCompare={vi.fn()}
        onRemoveCompare={vi.fn()}
      />
    );

    expect(html).toContain("超出 C3");
    expect(html).toContain("R4");
  });

  it("renders centralized metric explanations in table headers", () => {
    const html = renderToStaticMarkup(
      <FundTable
        funds={[makeFund("000008")]}
        compareCodes={[]}
        riskProfile="C3"
        onSelect={vi.fn()}
        onCompare={vi.fn()}
        onRemoveCompare={vi.fn()}
      />
    );

    expect(html).toContain("近三年按年折算的历史收益率");
    expect(html).toContain("管理费与托管费合计");
  });
});
