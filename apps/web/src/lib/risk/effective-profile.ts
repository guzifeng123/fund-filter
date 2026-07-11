import type { RiskAssessmentResult } from "@/lib/api/types";
import type { RiskProfile } from "@/lib/compliance/constants";

export const DEFAULT_RISK_PROFILE: RiskProfile = "C3";

export type EffectiveRiskProfile = {
  profile: RiskProfile;
  usesDefault: boolean;
};

export function resolveEffectiveRiskProfile(
  assessment: RiskAssessmentResult | null | undefined
): EffectiveRiskProfile {
  if (!assessment || assessment.is_expired) {
    return { profile: DEFAULT_RISK_PROFILE, usesDefault: true };
  }
  return { profile: assessment.risk_profile, usesDefault: false };
}
