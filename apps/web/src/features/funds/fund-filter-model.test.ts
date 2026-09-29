import { describe, expect, it } from "vitest";
import {
  areFundFilterCriteriaEqual,
  createDefaultFundFilterCriteria,
  createFundFilterPayload,
  normalizeFundKeyword,
  validateFundFilterCriteria
} from "@/features/funds/fund-filter-model";
import type { FundFilterCriteria } from "@/features/funds/fund-filter-model";

describe("fund filter model", () => {
  it("builds the complete recommendation payload from editable criteria and the read-only risk profile", () => {
    const criteria: FundFilterCriteria = {
      ...createDefaultFundFilterCriteria(),
      fund_types: ["stock", "mixed"],
      min_years: 5,
      size_range: [20, 80] as [number, number],
      return_rank_percentile: 25,
      max_drawdown_lte_category_avg: false,
      sharpe_gte: 1.5,
      fee_lte: 1.2
    };

    expect(createFundFilterPayload(
      criteria,
      "C2",
      { sort_by: "fee", sort_order: "asc" },
      "  000001 稳健  "
    )).toEqual({
      keyword: "000001 稳健",
      risk_profile: "C2",
      fund_types: ["stock", "mixed"],
      min_years: 5,
      size_range: [20, 80],
      return_rank_percentile: 25,
      max_drawdown_lte_category_avg: false,
      sharpe_gte: 1.5,
      fee_lte: 1.2,
      sort_by: "fee",
      sort_order: "asc"
    });
  });

  it("returns a fresh default value for reset", () => {
    const first = createDefaultFundFilterCriteria();
    first.fund_types.push("stock");
    first.size_range[0] = 999;

    const reset = createDefaultFundFilterCriteria();
    expect(reset.fund_types).toEqual(["mixed", "bond"]);
    expect(reset.size_range).toEqual([10, 100]);
    expect(areFundFilterCriteriaEqual(reset, createDefaultFundFilterCriteria())).toBe(true);
  });

  it("omits an empty keyword while preserving the complete server filter payload", () => {
    const payload = createFundFilterPayload(createDefaultFundFilterCriteria(), "C4", {
      sort_by: "annualized_return_3y",
      sort_order: "desc"
    });

    expect(payload.risk_profile).toBe("C4");
    expect(payload.fund_types).toEqual(["mixed", "bond"]);
    expect(payload).toMatchObject({ min_years: 3, sharpe_gte: 1.2, fee_lte: 1.5 });
    expect(payload).not.toHaveProperty("keyword");
    expect(normalizeFundKeyword("  000001 稳健  ")).toBe("000001 稳健");
  });

  it("rejects invalid draft criteria before apply", () => {
    expect(validateFundFilterCriteria({
      ...createDefaultFundFilterCriteria(),
      fund_types: []
    })).toBe("至少选择一种基金类型。");
    expect(validateFundFilterCriteria({
      ...createDefaultFundFilterCriteria(),
      size_range: [100, 10]
    })).toBe("规模下限不能高于规模上限。");
  });
});
