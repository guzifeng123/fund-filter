export const COMPLIANCE_DISCLAIMER =
  "本工具基于历史数据，仅供分析学习，不构成投资建议。历史表现不预示未来收益。";

export const AI_DISCLAIMER =
  "AI 输出仅供分析学习，不构成投资建议；无法替代持牌机构的适当性意见。";

export const DEFAULT_DATA_SOURCE = "sample_local";

export const COMPLIANCE_MESSAGES = {
  aiAnswerRequirements: "所有 AI 回答必须附数据日期、数据来源、合规免责声明；数据不足时必须明确说明。",
  compareRiskHighlight: "风险超配基金必须高亮；当前示例使用 C3 匹配规则，R4-R5 不进入推荐比较。",
  fundDetailUnavailable: "基金详情暂不可用，请检查数据源配置。",
  fundFilterDefaultRisk: "风险测评默认为 C3，仅展示 R1-R3 匹配基金；超配基金不会进入推荐结果。",
  portfolioRebalancePreview: "当任一资产类别偏离目标比例超过 5% 时，只生成“可考虑用于恢复比例”的再平衡预览。",
  riskAssessmentDefault: "尚未完成风险测评，基金筛选会临时使用 C3 作为默认画像。"
} as const;

export function riskProfileComplianceMessage(profile: RiskProfile, usesDefault: boolean) {
  return usesDefault
    ? COMPLIANCE_MESSAGES.riskAssessmentDefault
    : `当前使用最新有效风险画像 ${profile} 进行基金筛选与风险匹配；超出承受范围的基金不会进入推荐结果。`;
}

export const RISK_PROFILE_LIMITS = {
  C1: ["R1"],
  C2: ["R1", "R2"],
  C3: ["R1", "R2", "R3"],
  C4: ["R1", "R2", "R3", "R4"],
  C5: ["R1", "R2", "R3", "R4", "R5"]
} as const;

export type RiskProfile = keyof typeof RISK_PROFILE_LIMITS;
export type RiskLevel = (typeof RISK_PROFILE_LIMITS)[RiskProfile][number];
