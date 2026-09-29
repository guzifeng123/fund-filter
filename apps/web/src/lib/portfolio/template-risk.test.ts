import { describe, expect, it } from "vitest";
import { isPortfolioTemplateSuitable, portfolioTemplateRiskMessage } from "@/lib/portfolio/template-risk";

const growth = {
  id: "growth" as const,
  name: "进取型",
  stock_ratio: 80,
  bond_ratio: 20,
  suitable_profiles: ["C4", "C5"] as const
};

describe("portfolio template risk matching", () => {
  it("allows only explicitly suitable profiles", () => {
    expect(isPortfolioTemplateSuitable(growth, "C4")).toBe(true);
    expect(isPortfolioTemplateSuitable(growth, "C3")).toBe(false);
  });

  it("explains mismatch and default profile source", () => {
    expect(portfolioTemplateRiskMessage(growth, "C3", true)).toContain("临时风险画像 C3");
    expect(portfolioTemplateRiskMessage(growth, "C3", true)).toContain("不能据此创建组合");
  });
});
