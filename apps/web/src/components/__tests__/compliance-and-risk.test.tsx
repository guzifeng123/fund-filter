import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { ComplianceNotice } from "@/components/compliance-notice";
import { RiskLevelBadge } from "@/components/risk-level-badge";
import { COMPLIANCE_DISCLAIMER, RISK_PROFILE_LIMITS } from "@/lib/compliance/constants";

describe("compliance and risk presentation", () => {
  it("renders the centralized compliance disclaimer by default", () => {
    const html = renderToStaticMarkup(<ComplianceNotice />);

    expect(html).toContain(COMPLIANCE_DISCLAIMER);
    expect(html).toContain("不构成投资建议");
  });

  it("renders risk level labels consistently", () => {
    const html = renderToStaticMarkup(<RiskLevelBadge level="R4" />);

    expect(html).toContain("R4");
    expect(html).toContain("中高风险");
  });

  it("keeps C3 users capped at R3 funds", () => {
    expect(RISK_PROFILE_LIMITS.C3).toEqual(["R1", "R2", "R3"]);
    expect(RISK_PROFILE_LIMITS.C3).not.toContain("R4");
  });
});
