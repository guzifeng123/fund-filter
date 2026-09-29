import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { createDefaultFundFilterCriteria } from "@/features/funds/fund-filter-model";
import { FundFilterPanel } from "@/features/funds/fund-filter-panel";

describe("FundFilterPanel", () => {
  it("renders all editable steps and keeps the effective risk profile read-only", () => {
    const criteria = createDefaultFundFilterCriteria();
    const html = renderToStaticMarkup(
      <FundFilterPanel
        riskProfile="C3"
        usesDefaultRiskProfile={false}
        value={criteria}
        appliedValue={criteria}
        onChange={vi.fn()}
        onApply={vi.fn()}
        onReset={vi.fn()}
      />
    );

    expect(html).toContain("风险画像基线");
    expect(html).toContain("来自最新有效测评，不可在此修改");
    expect(html).toContain("基金类型");
    expect(html).toContain("规模下限");
    expect(html).toContain("收益排名前");
    expect(html).toContain("最大回撤不高于同类平均");
    expect(html).toContain("夏普比率下限");
    expect(html).toContain("费率合计上限");
    expect(html).toContain("成立年限下限");
    expect(html).toContain("应用筛选");
    expect(html).not.toContain("name=\"risk_profile\"");
  });
});
