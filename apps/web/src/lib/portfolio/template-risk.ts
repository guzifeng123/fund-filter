import type { PortfolioTemplate } from "@/lib/api/types";
import type { RiskProfile } from "@/lib/compliance/constants";

export function isPortfolioTemplateSuitable(template: PortfolioTemplate | undefined, profile: RiskProfile) {
  return template?.suitable_profiles.includes(profile) ?? false;
}

export function portfolioTemplateRiskMessage(
  template: PortfolioTemplate | undefined,
  profile: RiskProfile,
  usesDefault: boolean
) {
  const profileSource = usesDefault ? `临时风险画像 ${profile}` : `最新有效风险画像 ${profile}`;
  if (!template) return `${profileSource}：请选择一个组合模板。`;
  if (isPortfolioTemplateSuitable(template, profile)) {
    return `${profileSource} 与“${template.name}”模板匹配，可以继续创建并查看历史分析。`;
  }
  return `${profileSource} 与“${template.name}”模板不匹配；该模板仅适用于 ${template.suitable_profiles.join(" / ")}。可以浏览参数，但不能据此创建组合。`;
}
