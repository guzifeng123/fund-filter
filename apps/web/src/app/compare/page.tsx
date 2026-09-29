"use client";

import { Suspense, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSearchParams } from "next/navigation";
import { ChartCard } from "@/components/chart-card";
import { ComplianceNotice } from "@/components/compliance-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetricLabel } from "@/components/metric-label";
import { PageHeader } from "@/components/page-header";
import { RiskLevelBadge } from "@/components/risk-level-badge";
import { StaleDataNotice } from "@/components/stale-data-notice";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { Fund } from "@/lib/api/types";
import { riskProfileComplianceMessage, RISK_PROFILE_LIMITS } from "@/lib/compliance/constants";
import { resolveEffectiveRiskProfile } from "@/lib/risk/effective-profile";


function parseCompareCodes(codes: string | null) {
  const rawCodes = codes?.split(",") ?? [];
  return Array.from(new Set(rawCodes.map((code) => code.trim()).filter(Boolean))).slice(0, 5);
}

function bestCode(funds: Fund[], selector: (fund: Fund) => number) {
  if (!funds.length) return "";
  return funds.reduce((best, fund) => (selector(fund) > selector(best) ? fund : best), funds[0]).code;
}

function lowestCode(funds: Fund[], selector: (fund: Fund) => number) {
  if (!funds.length) return "";
  return funds.reduce((best, fund) => (selector(fund) < selector(best) ? fund : best), funds[0]).code;
}

function highlightClass(code: string, targetCode: string) {
  return code === targetCode ? "bg-[var(--accent-weak)] font-semibold" : "";
}

function ComparePageContent() {
  const searchParams = useSearchParams();
  const codes = useMemo(() => parseCompareCodes(searchParams.get("codes")), [searchParams]);
  const riskQuery = useQuery({ queryKey: ["risk-latest"], queryFn: apiClient.latestRiskAssessment });
  const effectiveRisk = resolveEffectiveRiskProfile(riskQuery.data?.data);
  const allowedRiskLevels: readonly string[] = RISK_PROFILE_LIMITS[effectiveRisk.profile];

  const query = useQuery({
    queryKey: ["compare", codes],
    queryFn: () => apiClient.compareFunds(codes),
    enabled: codes.length >= 2 && !riskQuery.isLoading
  });
  const funds = useMemo(() => query.data?.data ?? [], [query.data?.data]);
  const bestReturn = useMemo(() => bestCode(funds, (fund) => fund.annualized_return_5y), [funds]);
  const bestDrawdown = useMemo(() => bestCode(funds, (fund) => fund.max_drawdown), [funds]);
  const bestSharpe = useMemo(() => bestCode(funds, (fund) => fund.sharpe_ratio), [funds]);
  const lowestFee = useMemo(() => lowestCode(funds, (fund) => fund.management_fee + fund.custody_fee), [funds]);
  const bestManagerYears = useMemo(() => bestCode(funds, (fund) => fund.manager_years), [funds]);

  return (
    <>
      <PageHeader title="基金比较" description="最多比较 5 只基金，固定展示收益、风险、费用、经理和风险匹配。" />
      {!codes.length ? (
        <EmptyState title="还没有选择基金" description="请先在基金筛选页加入 2-5 只基金后进入比较。" />
      ) : codes.length < 2 ? (
        <EmptyState title="至少选择 2 只基金" description="单只基金请在详情页查看；比较需要 2-5 只不同基金。" />
      ) : riskQuery.isLoading || query.isLoading ? <LoadingBlock /> : query.isError ? (
        <ErrorState
          title="基金比较加载失败"
          description={getApiErrorMessage(query.error, "无法获取比较池基金数据，请确认所选基金代码和 API 服务状态后重试。")}
          onRetry={() => void query.refetch()}
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
          <StaleDataNotice updatedAt={query.data?.meta.data_updated_at} className="xl:col-span-2" />
          <div className="overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--surface)]">
            <table className="w-full min-w-[760px] text-sm md:min-w-[900px]">
              <thead className="bg-[var(--surface-muted)] text-left text-xs text-[var(--text-muted)]">
                <tr>
                  <th className="p-3">基金</th>
                  <th className="p-3">风险</th>
                  <th className="p-3 text-right"><MetricLabel metricKey="annualized_return_5y" align="right" /></th>
                  <th className="p-3 text-right"><MetricLabel metricKey="max_drawdown" align="right" /></th>
                  <th className="p-3 text-right"><MetricLabel metricKey="sharpe_ratio" align="right" /></th>
                  <th className="p-3 text-right"><MetricLabel metricKey="fee" align="right" /></th>
                  <th className="p-3 text-right"><MetricLabel metricKey="manager_years" align="right" /></th>
                </tr>
              </thead>
              <tbody>
                {funds.map((fund) => {
                  const isRiskMatched = allowedRiskLevels.includes(fund.risk_level);
                  const fee = fund.management_fee + fund.custody_fee;
                  return (
                    <tr key={fund.code} className={`border-t border-[var(--border)] ${!isRiskMatched ? "bg-[var(--surface-muted)]" : ""}`}>
                      <td className="p-3"><div className="font-medium">{fund.name}</div><div className="text-xs text-[var(--text-muted)]">{fund.code}</div></td>
                      <td className="p-3">
                        <div className="flex flex-col items-start gap-1">
                          <RiskLevelBadge level={fund.risk_level} />
                          {!isRiskMatched ? <span className="text-xs text-[var(--r4)]">超出 {effectiveRisk.profile}</span> : null}
                        </div>
                      </td>
                      <td className={`p-3 text-right ${highlightClass(fund.code, bestReturn)}`}>{fund.annualized_return_5y.toFixed(2)}%</td>
                      <td className={`p-3 text-right ${highlightClass(fund.code, bestDrawdown)}`}>{fund.max_drawdown.toFixed(2)}%</td>
                      <td className={`p-3 text-right ${highlightClass(fund.code, bestSharpe)}`}>{fund.sharpe_ratio.toFixed(2)}</td>
                      <td className={`p-3 text-right ${highlightClass(fund.code, lowestFee)}`}>{fee.toFixed(2)}%</td>
                      <td className={`p-3 text-right ${highlightClass(fund.code, bestManagerYears)}`}>{fund.manager_years} 年</td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
          <ChartCard
            title="比较雷达"
            source={query.data?.meta.source}
            option={{
              radar: { indicator: ["收益", "风险控制", "费用友好", "经理稳定", "风险匹配"].map((name) => ({ name, max: 100 })) },
              series: [{
                type: "radar",
                data: funds.map((fund) => ({
                  name: fund.name,
                  value: [
                    fund.annualized_return_5y * 6,
                    Math.max(0, 100 + fund.max_drawdown * 3),
                    Math.max(0, 100 - (fund.management_fee + fund.custody_fee) * 30),
                    Math.min(100, fund.manager_years * 8),
                    allowedRiskLevels.includes(fund.risk_level) ? 90 : 35
                  ]
                }))
              }]
            }}
          />
          <ComplianceNotice>{riskProfileComplianceMessage(effectiveRisk.profile, effectiveRisk.usesDefault)}</ComplianceNotice>
        </div>
      )}
    </>
  );
}

export default function ComparePage() {
  return (
    <Suspense fallback={<LoadingBlock />}>
      <ComparePageContent />
    </Suspense>
  );
}
