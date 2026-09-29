"use client";

import { Plus, X } from "lucide-react";
import type { Fund } from "@/lib/api/types";
import { Button } from "@/components/button";
import { MetricLabel } from "@/components/metric-label";
import { RiskLevelBadge } from "@/components/risk-level-badge";
import type { RiskProfile } from "@/lib/compliance/constants";
import { RISK_PROFILE_LIMITS } from "@/lib/compliance/constants";

export function FundTable({
  funds,
  selectedCode,
  compareCodes,
  riskProfile,
  onSelect,
  onCompare,
  onRemoveCompare
}: {
  funds: Fund[];
  selectedCode?: string;
  compareCodes: string[];
  riskProfile: RiskProfile;
  onSelect: (code: string) => void;
  onCompare: (code: string) => void;
  onRemoveCompare: (code: string) => void;
}) {
  const allowedRiskLevels: readonly string[] = RISK_PROFILE_LIMITS[riskProfile];
  const isCompareFull = compareCodes.length >= 5;

  return (
    <div className="grid gap-2">
      {isCompareFull ? (
        <div className="rounded-md border border-[var(--r4)] bg-[var(--surface)] px-3 py-2 text-xs text-[var(--r4)]">
          比较池已满，最多 5 只基金。请先移除一只基金后再添加。
        </div>
      ) : null}
      <div className="overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--surface)]">
        <table className="w-full min-w-[860px] border-collapse text-sm">
          <thead className="bg-[var(--surface-muted)] text-left text-xs text-[var(--text-muted)]">
            <tr>
              <th className="px-3 py-2">基金</th>
              <th className="px-3 py-2">风险</th>
              <th className="px-3 py-2 text-right"><MetricLabel metricKey="annualized_return_3y" align="right" /></th>
              <th className="px-3 py-2 text-right"><MetricLabel metricKey="max_drawdown" align="right" /></th>
              <th className="px-3 py-2 text-right"><MetricLabel metricKey="sharpe_ratio" align="right" /></th>
              <th className="px-3 py-2 text-right"><MetricLabel metricKey="fee" align="right" /></th>
              <th className="px-3 py-2"><MetricLabel metricKey="data_updated_at" /></th>
              <th className="px-3 py-2"></th>
            </tr>
          </thead>
          <tbody>
            {funds.map((fund) => {
              const isInCompare = compareCodes.includes(fund.code);
              const isRiskMatched = allowedRiskLevels.includes(fund.risk_level);
              return (
                <tr
                  key={fund.code}
                  className={`border-t border-[var(--border)] ${selectedCode === fund.code ? "bg-[var(--accent-weak)]" : ""}`}
                >
                  <td className="px-3 py-3">
                    <Button
                      variant="unstyled"
                      size="none"
                      aria-pressed={selectedCode === fund.code}
                      className="text-left"
                      onClick={() => onSelect(fund.code)}
                    >
                      <div className="font-medium">{fund.name}</div>
                      <div className="text-xs text-[var(--text-muted)]">{fund.code} · {fund.manager_name}</div>
                    </Button>
                  </td>
                  <td className="px-3 py-3">
                    <div className="flex flex-col items-start gap-1">
                      <RiskLevelBadge level={fund.risk_level} />
                      {!isRiskMatched ? <span className="text-xs text-[var(--r4)]">超出 {riskProfile}</span> : null}
                    </div>
                  </td>
                  <td className="px-3 py-3 text-right">{fund.annualized_return_3y.toFixed(2)}%</td>
                  <td className="px-3 py-3 text-right">{fund.max_drawdown.toFixed(2)}%</td>
                  <td className="px-3 py-3 text-right">{fund.sharpe_ratio.toFixed(2)}</td>
                  <td className="px-3 py-3 text-right">{(fund.management_fee + fund.custody_fee).toFixed(2)}%</td>
                  <td className="px-3 py-3 text-xs text-[var(--text-muted)]">{fund.data_updated_at.slice(0, 10)}</td>
                  <td className="px-3 py-3 text-right">
                    {isInCompare ? (
                      <Button
                        variant="secondary"
                        size="sm"
                        className="gap-1"
                        onClick={() => onRemoveCompare(fund.code)}
                      >
                        <X className="h-3.5 w-3.5" /> 移除
                      </Button>
                    ) : (
                      <Button
                        variant="secondary"
                        size="sm"
                        className="gap-1"
                        onClick={() => onCompare(fund.code)}
                        disabled={isCompareFull}
                      >
                        <Plus className="h-3.5 w-3.5" /> 比较
                      </Button>
                    )}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
