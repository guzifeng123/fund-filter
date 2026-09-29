import type { Route } from "next";

export type LearningModuleContent = {
  id: string;
  title: string;
  summary: string;
  definition: string;
  formula: string;
  example: string;
  misconceptions: string[];
  links: Array<{ href: Route; label: string; description: string }>;
  dataNote: string;
};

export type LearningGlossaryItem = {
  term: string;
  definition: string;
};

export const LEARNING_MODULES: LearningModuleContent[] = [
  {
    id: "returns-and-compounding",
    title: "收益与复利",
    summary: "先分清区间收益、年化折算和复利路径，再比较历史表现。",
    definition: "区间收益率衡量期末价值相对期初价值的变化；年化收益是把一段历史结果折算为年度口径，便于同区间比较，并不代表下一年会重复。复利表示每一期涨跌都作用于上一期变化后的余额。",
    formula: "区间收益率 = 期末价值 ÷ 期初价值 - 1",
    example: "100 元先上涨 10% 变成 110 元，再下跌 10% 只剩 99 元，整个区间收益率是 -1%。相同幅度的上涨和下跌不能直接抵消。",
    misconceptions: [
      "把历史年化 8% 理解成以后每年都会固定获得 8%。",
      "把不同起止日期、不同分红处理口径的收益直接横向比较。",
      "只看收益率，不同时查看回撤、波动、费率和数据更新时间。"
    ],
    links: [
      { href: "/funds", label: "基金筛选", description: "查看统一口径的 3 年历史年化与更新时间" },
      { href: "/compare", label: "基金比较", description: "在同一表格中比较 5 年历史年化、回撤和费用" }
    ],
    dataNote: "示例是简化演算，不使用实时基金数据。比较收益时应先确认统计区间、净值口径和更新时间，不得把历史折算结果外推为未来收益。"
  },
  {
    id: "drawdown-and-volatility",
    title: "最大回撤与波动",
    summary: "回撤描述最深的历史下跌路径，波动率描述收益变化幅度。",
    definition: "最大回撤是统计区间内从某个历史高点到随后低点的最大跌幅；波动率是历史收益变化幅度的年化统计值。两者观察的是不同风险侧面，应结合区间、频率和基金类型理解。",
    formula: "最大回撤 = min（当前价值 ÷ 截至当时的历史峰值 - 1）",
    example: "净值从 100 上涨到 120，随后回落到 90：相对起点是 -10%，但从峰值 120 到低点 90 的回撤是 -25%。最大回撤关注的是投资过程中曾承受的最深下跌。",
    misconceptions: [
      "把最大回撤等同于期末亏损，忽略中途从峰值下跌的路径。",
      "认为历史波动率较低就代表不存在信用、流动性或数据缺失风险。",
      "用不同观察区间或不同数据频率计算出的回撤、波动率直接排名。"
    ],
    links: [
      { href: "/funds", label: "基金详情", description: "查看历史净值、最大回撤与风险等级" },
      { href: "/backtest", label: "回测学习", description: "结合收益曲线查看历史回撤和波动率" }
    ],
    dataNote: "回撤和波动率都依赖历史净值完整性与所选区间。净值缺失或区间过短时，不应补出看似精确的风险指标。"
  },
  {
    id: "sharpe-and-risk-adjustment",
    title: "夏普与风险调整",
    summary: "夏普比率把历史超额收益与波动放在同一个口径中观察。",
    definition: "夏普比率用于衡量单位历史波动对应的历史超额收益。它需要明确无风险利率、收益区间和波动率口径，适合辅助比较，不应脱离最大回撤、费用与基金类型单独使用。",
    formula: "夏普比率 =（历史年化收益率 - 无风险利率）÷ 历史年化波动率",
    example: "假设同一区间无风险利率为 2%：A 的历史年化收益 8%、波动率 10%，简化夏普为 0.6；B 的收益 10%、波动率 20%，简化夏普为 0.4。B 的原始收益更高，但承担的历史波动也更多。",
    misconceptions: [
      "认为夏普比率较高就等于收益有保证或未来一定更好。",
      "忽略无风险利率、统计区间和年化方式不同造成的口径差异。",
      "跨基金类型机械比较夏普，而不看回撤、费用和风险等级。"
    ],
    links: [
      { href: "/funds", label: "基金筛选", description: "设置夏普下限并同时检查回撤与费率" },
      { href: "/compare", label: "基金比较", description: "在统一表格中查看夏普、收益和风险差异" }
    ],
    dataNote: "本例只演示公式，未计入真实数据的小数精度、无风险利率变化和缺失值处理。夏普反映历史统计关系，不构成收益预测。"
  },
  {
    id: "fees-and-long-term-costs",
    title: "费率与长期成本",
    summary: "先确认费用包含什么，再评估长期持有中的成本差异。",
    definition: "本应用的“费用”指标是管理费与托管费合计，不包含可能发生的申购费、赎回费等交易费用。费率会持续影响持有结果，但不能替代对策略、风险和跟踪误差的判断。",
    formula: "简化年度成本 ≈ 期初金额 × 年费率",
    example: "以 10 万元做静态教学估算：费率 1.5% 对应首年约 1,500 元，费率 0.8% 对应约 800 元，相差约 700 元。真实费用通常从基金资产中计提，金额也会随净值变化。",
    misconceptions: [
      "认为页面费率已经包含申购、赎回等所有可能费用。",
      "只要费率较低就一定有更好的历史或未来表现。",
      "忽略持有期限、净值变化和费率持续计提带来的复合影响。"
    ],
    links: [
      { href: "/funds", label: "基金详情", description: "查看管理费、托管费及费用口径说明" },
      { href: "/compare", label: "基金比较", description: "比较多只基金的管理费与托管费合计" }
    ],
    dataNote: "示例是静态估算，不等同于真实扣费结果。使用页面费用数据时，应同时确认基金公告、更新时间和未纳入本指标的其他费用。"
  },
  {
    id: "dca-rebalancing-and-backtests",
    title: "定投、再平衡与回测局限",
    summary: "策略规则可以用历史数据学习，但历史回测不是未来情景的承诺。",
    definition: "定投是在预设时间投入固定金额；再平衡是当资产比例偏离目标时，用于恢复目标结构的规则。本应用以历史净值模拟这些规则，并在资产类别偏离目标超过 5 个百分点时生成再平衡预览。",
    formula: "偏离百分点 = | 当前资产比例 - 目标资产比例 |",
    example: "目标股债比例为 50/50，当前变成 60/40，则股票部分偏离 10 个百分点，超过 5 个百分点阈值；应用只展示“可考虑用于恢复目标比例”的预览。若每月定投 1,000 元，净值 1.0 和 0.8 时分别买到 1,000 和 1,250 份，但份额增加并不保证最终获利。",
    misconceptions: [
      "把一段历史回测曲线当作未来收益预测或买卖时点。",
      "认为定投可以消除亏损，或再平衡一定能提高收益。",
      "反复调整参数直到历史结果最好，却忽略过拟合、费用和缺失数据。"
    ],
    links: [
      { href: "/backtest", label: "回测学习", description: "设置历史区间、金额和频率并查看局限提示" },
      { href: "/portfolio", label: "组合管理", description: "查看目标比例、当前偏离和再平衡预览" }
    ],
    dataNote: "回测只解释所选历史区间，结果受起止日期、净值质量、费用假设和参数影响；不得据此生成未来收益、短期买卖点或自动交易指令。"
  }
];

export const LEARNING_GLOSSARY: LearningGlossaryItem[] = [
  { term: "历史年化收益", definition: "把特定历史区间的复合变化折算为年度口径，不是未来年度收益。" },
  { term: "最大回撤", definition: "统计区间内从历史峰值到随后低点的最大跌幅。" },
  { term: "波动率", definition: "历史收益变化幅度的年化统计值。" },
  { term: "夏普比率", definition: "单位历史波动对应的历史超额收益。" },
  { term: "费率", definition: "本应用指管理费与托管费合计，不含申购、赎回等可能费用。" },
  { term: "定投", definition: "按预设时间投入固定金额的规则，不保证获利。" },
  { term: "再平衡", definition: "资产比例偏离目标后，用于恢复目标结构的规则。" },
  { term: "回测", definition: "用历史数据模拟规则表现的学习工具，不预测未来。" }
];
