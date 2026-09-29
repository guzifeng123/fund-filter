export const ANALYSIS_METRIC_COPY = {
  annualized_return_3y: {
    label: "3年年化",
    explanation: "近三年按年折算的历史收益率，仅反映过往表现。"
  },
  annualized_return_5y: {
    label: "5年年化",
    explanation: "近五年按实际区间折算的历史年化收益率；覆盖不足时不应展示看似精确的结果。"
  },
  max_drawdown: {
    label: "最大回撤",
    explanation: "统计区间内从高点到低点的最大跌幅，数值越低代表历史波动冲击越大。"
  },
  sharpe_ratio: {
    label: "夏普",
    explanation: "衡量单位波动对应的历史超额收益，需结合回撤、费用和基金类型一起查看。"
  },
  category_rank_percentile: {
    label: "同类排名",
    explanation: "基金在同类样本中的历史排名分位，数值越小越靠前；需确认排名区间和同类口径。"
  },
  fee: {
    label: "费用",
    explanation: "管理费与托管费合计，未包含申购、赎回等可能发生的交易费用。"
  },
  data_updated_at: {
    label: "数据",
    explanation: "当前行基金数据的最近更新时间，过期数据需谨慎使用。"
  },
  manager_years: {
    label: "经理年限",
    explanation: "当前基金经理的管理或从业年限，用于观察经验，不代表未来业绩。"
  },
  backtest_annualized_return: {
    label: "资金加权",
    explanation: "按每笔投入现金流计算的 XIRR 年化收益率，仅用于理解历史策略表现。"
  },
  money_weighted_return: {
    label: "XIRR",
    explanation: "资金加权年化收益率，考虑每次定投或投入发生的具体日期。"
  },
  time_weighted_return: {
    label: "时间加权",
    explanation: "剔除中途投入影响后的年化收益率，用于观察资产本身的历史表现。"
  },
  volatility: {
    label: "波动率",
    explanation: "历史收益变化幅度的年化统计值，数值越高表示历史波动越大。"
  },
  total_invested: {
    label: "投入",
    explanation: "回测区间内按策略规则累计投入的历史模拟金额，不包含真实交易。"
  },
  final_value: {
    label: "期末市值",
    explanation: "历史回测区间结束时的模拟组合价值，不代表未来可获得金额。"
  }
} as const;

export type AnalysisMetricKey = keyof typeof ANALYSIS_METRIC_COPY;
