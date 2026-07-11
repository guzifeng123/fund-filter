import type { RiskLevel } from "@/lib/compliance/constants";

const riskText: Record<RiskLevel, string> = {
  R1: "低风险",
  R2: "中低风险",
  R3: "中风险",
  R4: "中高风险",
  R5: "高风险"
};

export function RiskLevelBadge({ level }: { level: RiskLevel }) {
  return (
    <span
      className="inline-flex h-6 min-w-16 items-center justify-center rounded-md px-2 text-xs font-medium text-white"
      style={{ background: `var(--${level.toLowerCase()})` }}
    >
      {level} {riskText[level]}
    </span>
  );
}
