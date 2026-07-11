export const FUND_METRIC_COPY = {
  annualized_return_3y: {
    label: "3年年化",
    explanation: "近三年按年折算的历史收益率，仅反映过往表现。"
  },
  max_drawdown: {
    label: "最大回撤",
    explanation: "统计区间内从高点到低点的最大跌幅，数值越低代表历史波动冲击越大。"
  },
  sharpe_ratio: {
    label: "夏普",
    explanation: "衡量单位波动对应的历史超额收益，需结合回撤、费用和基金类型一起查看。"
  },
  fee: {
    label: "费用",
    explanation: "管理费与托管费合计，未包含申购、赎回等可能发生的交易费用。"
  },
  data_updated_at: {
    label: "数据",
    explanation: "当前行基金数据的最近更新时间，过期数据需谨慎使用。"
  }
} as const;

export type FundMetricKey = keyof typeof FUND_METRIC_COPY;
