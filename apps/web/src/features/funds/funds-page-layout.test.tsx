import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const fundsPageSourcePath = join(__dirname, "funds-page.tsx");
const searchToolbarSourcePath = join(__dirname, "fund-search-toolbar.tsx");

describe("FundsPage responsive layout guard", () => {
  it("keeps the sort controls wrap-friendly on narrow screens", () => {
    const source = readFileSync(searchToolbarSourcePath, "utf8");

    expect(source).toContain("min-h-10 flex-wrap");
    expect(source).toContain("xl:grid-cols-[minmax(12rem,1fr)_auto]");
    expect(source).not.toContain("md:grid-cols-[minmax(0,1fr)_auto]");
    expect(source).not.toContain("flex h-10 items-center gap-1 rounded-md border");
  });

  it("keeps the compare entry disabled until two funds are selected", () => {
    const source = readFileSync(fundsPageSourcePath, "utf8");

    expect(source).toContain("compareCodes.length >= 2");
    expect(source).toContain("至少选择 2 只基金后才能比较");
    expect(source).toContain("请再选择 1 只基金后进入比较");
  });

  it("uses risk-filtered recommendations after assessment and safe browse mode before assessment", () => {
    const source = readFileSync(fundsPageSourcePath, "utf8");

    expect(source).toContain("createFundFilterPayload(appliedFilter, effectiveRisk.profile, activeSort, normalizedKeyword)");
    expect(source).toContain("apiClient.filterFunds(isDataBrowseMode ? browseFilter : activeFilter)");
    expect(source).toContain("const browseFilter = useMemo(");
    expect(source).toContain('fund_types: ["mixed", "bond", "stock", "money"]');
    expect(source).toContain("return_rank_percentile: 100");
    expect(source).toContain("sharpe_gte: -100");
    expect(source).toContain("isDataBrowseMode");
    expect(source).toContain("全部已应用四步条件内继续收窄");
  });

  it("keeps narrow middle-column toolbar rows at their natural height", () => {
    const source = readFileSync(fundsPageSourcePath, "utf8");

    expect(source).toContain('<section className="grid content-start gap-3">');
    expect(source).toContain("xl:grid-cols-[300px_minmax(0,1fr)]");
    expect(source).toContain("2xl:grid-cols-[300px_minmax(0,1fr)_420px]");
    expect(source).toContain('<aside className="xl:col-span-2 2xl:col-span-1">');
  });
});
