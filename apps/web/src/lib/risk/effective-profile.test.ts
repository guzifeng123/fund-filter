import { describe, expect, it } from "vitest";
import { resolveEffectiveRiskProfile } from "@/lib/risk/effective-profile";
import type { RiskAssessmentResult } from "@/lib/api/types";

const validAssessment: RiskAssessmentResult = {
  risk_profile: "C4",
  score: 30,
  effective_from: "2026-07-10",
  effective_to: "2027-07-10",
  expires_soon: false,
  is_expired: false,
  explanation: "较高风险承受能力"
};

describe("resolveEffectiveRiskProfile", () => {
  it("uses the latest assessment when it is still valid", () => {
    expect(resolveEffectiveRiskProfile(validAssessment)).toEqual({ profile: "C4", usesDefault: false });
  });

  it("falls back to C3 when no assessment exists", () => {
    expect(resolveEffectiveRiskProfile(null)).toEqual({ profile: "C3", usesDefault: true });
  });

  it("falls back to C3 when the latest assessment expired", () => {
    expect(resolveEffectiveRiskProfile({ ...validAssessment, is_expired: true })).toEqual({
      profile: "C3",
      usesDefault: true
    });
  });
});
