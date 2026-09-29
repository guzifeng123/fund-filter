import type { FundFilterRequest } from "@/lib/api/types";
import type { RiskProfile } from "@/lib/compliance/constants";

export type FundFilterCriteria = Omit<
  FundFilterRequest,
  "keyword" | "risk_profile" | "sort_by" | "sort_order"
>;

export type FundSort = Required<Pick<FundFilterRequest, "sort_by" | "sort_order">>;

const DEFAULT_FUND_FILTER_CRITERIA: FundFilterCriteria = {
  fund_types: ["mixed", "bond"],
  min_years: 3,
  size_range: [10, 100],
  return_rank_percentile: 30,
  max_drawdown_lte_category_avg: true,
  sharpe_gte: 1.2,
  fee_lte: 1.5
};

export function createDefaultFundFilterCriteria(): FundFilterCriteria {
  return {
    ...DEFAULT_FUND_FILTER_CRITERIA,
    fund_types: [...DEFAULT_FUND_FILTER_CRITERIA.fund_types],
    size_range: [...DEFAULT_FUND_FILTER_CRITERIA.size_range]
  };
}

export function createFundFilterPayload(
  criteria: FundFilterCriteria,
  riskProfile: RiskProfile,
  sort: FundSort,
  keyword = ""
): FundFilterRequest {
  const normalizedKeyword = normalizeFundKeyword(keyword);
  return {
    ...(normalizedKeyword ? { keyword: normalizedKeyword } : {}),
    ...criteria,
    fund_types: [...criteria.fund_types],
    size_range: [...criteria.size_range],
    risk_profile: riskProfile,
    sort_by: sort.sort_by,
    sort_order: sort.sort_order
  };
}

export function normalizeFundKeyword(value: string): string {
  return value.trim();
}

export function validateFundFilterCriteria(criteria: FundFilterCriteria): string | null {
  if (!criteria.fund_types.length) {
    return "至少选择一种基金类型。";
  }
  if (criteria.min_years < 0) {
    return "成立年限不能小于 0 年。";
  }
  const [minimumSize, maximumSize] = criteria.size_range;
  if (minimumSize < 0 || maximumSize < 0) {
    return "基金规模不能小于 0 亿。";
  }
  if (minimumSize > maximumSize) {
    return "规模下限不能高于规模上限。";
  }
  if (criteria.return_rank_percentile < 0 || criteria.return_rank_percentile > 100) {
    return "收益排名分位必须在 0-100 之间。";
  }
  if (criteria.fee_lte < 0) {
    return "费率上限不能小于 0%。";
  }
  return null;
}

export function areFundFilterCriteriaEqual(
  left: FundFilterCriteria,
  right: FundFilterCriteria
): boolean {
  return (
    left.min_years === right.min_years
    && left.size_range[0] === right.size_range[0]
    && left.size_range[1] === right.size_range[1]
    && left.return_rank_percentile === right.return_rank_percentile
    && left.max_drawdown_lte_category_avg === right.max_drawdown_lte_category_avg
    && left.sharpe_gte === right.sharpe_gte
    && left.fee_lte === right.fee_lte
    && left.fund_types.length === right.fund_types.length
    && left.fund_types.every((fundType) => right.fund_types.includes(fundType))
  );
}
