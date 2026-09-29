import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ComplianceNotice } from "@/components/compliance-notice";
import { MetricLabel } from "@/components/metric-label";
import { RiskLevelBadge } from "@/components/risk-level-badge";
import { COMPLIANCE_DISCLAIMER, RISK_PROFILE_LIMITS } from "@/lib/compliance/constants";

describe("compliance and risk presentation", () => {
  it("renders the centralized compliance disclaimer by default", () => {
    const html = renderToStaticMarkup(<ComplianceNotice />);

    expect(html).toContain(COMPLIANCE_DISCLAIMER);
    expect(html).toContain("不构成投资建议");
  });

  it("keeps the centralized disclaimer when a page adds contextual guidance", () => {
    const html = renderToStaticMarkup(<ComplianceNotice>仅生成再平衡预览。</ComplianceNotice>);

    expect(html).toContain("仅生成再平衡预览");
    expect(html).toContain(COMPLIANCE_DISCLAIMER);
  });

  it("renders risk level labels consistently", () => {
    const html = renderToStaticMarkup(<RiskLevelBadge level="R4" />);

    expect(html).toContain("R4");
    expect(html).toContain("中高风险");
  });

  it("exposes metric explanations through a semantic icon button", () => {
    const html = renderToStaticMarkup(<MetricLabel metricKey="max_drawdown" />);

    expect(html).toContain("<button");
    expect(html).toContain('type="button"');
    expect(html).toContain('aria-label="最大回撤说明：');
  });

  it("keeps C3 users capped at R3 funds", () => {
    expect(RISK_PROFILE_LIMITS.C3).toEqual(["R1", "R2", "R3"]);
    expect(RISK_PROFILE_LIMITS.C3).not.toContain("R4");
  });
});
