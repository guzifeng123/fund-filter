"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { ArrowUpDown, Filter, Search, X } from "lucide-react";
import Link from "next/link";
import { ComplianceNotice } from "@/components/compliance-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageHeader } from "@/components/page-header";
import { StaleDataNotice } from "@/components/stale-data-notice";
import { FundDetailPanel } from "@/features/funds/fund-detail-panel";
import { FundTable } from "@/features/funds/fund-table";
import { apiClient } from "@/lib/api/client";
import type { FundFilterRequest } from "@/lib/api/types";
import { riskProfileComplianceMessage } from "@/lib/compliance/constants";
import { resolveEffectiveRiskProfile } from "@/lib/risk/effective-profile";

const baseFilter: FundFilterRequest = {
  risk_profile: "C3",
  fund_types: ["mixed", "bond"],
  min_years: 3,
  size_range: [10, 100],
  return_rank_percentile: 30,
  max_drawdown_lte_category_avg: true,
  sharpe_gte: 1.2,
  fee_lte: 1.5,
  sort_by: "annualized_return_3y",
  sort_order: "desc"
};

const sortOptions = [
  { label: "收益", sort_by: "annualized_return_3y", sort_order: "desc" },
  { label: "回撤", sort_by: "max_drawdown", sort_order: "desc" },
  { label: "夏普", sort_by: "sharpe_ratio", sort_order: "desc" },
  { label: "费用", sort_by: "fee", sort_order: "asc" },
  { label: "规模", sort_by: "size", sort_order: "desc" }
] satisfies Array<Pick<FundFilterRequest, "sort_by" | "sort_order"> & { label: string }>;

export function FundsPage() {
  const [queryText, setQueryText] = useState("");
  const [selectedCode, setSelectedCode] = useState<string>();
  const [compareCodes, setCompareCodes] = useState<string[]>([]);
  const [sortIndex, setSortIndex] = useState(0);
  const [compareMessage, setCompareMessage] = useState("");
  const riskQuery = useQuery({ queryKey: ["risk-latest"], queryFn: apiClient.latestRiskAssessment });
  const effectiveRisk = resolveEffectiveRiskProfile(riskQuery.data?.data);
  const activeSort = sortOptions[sortIndex];
  const activeFilter: FundFilterRequest = {
    ...baseFilter,
    risk_profile: effectiveRisk.profile,
    sort_by: activeSort.sort_by,
    sort_order: activeSort.sort_order
  };
  const compareStatusMessage = compareCodes.length >= 5 ? "比较池已满，最多 5 只基金。" : compareMessage;
  const fundsQuery = useQuery({
    queryKey: ["funds", activeFilter],
    queryFn: () => apiClient.filterFunds(activeFilter)
  });

  const funds = useMemo(() => {
    const rows = fundsQuery.data?.data ?? [];
    if (!queryText.trim()) return rows;
    return rows.filter((fund) => `${fund.code}${fund.name}`.includes(queryText.trim()));
  }, [fundsQuery.data?.data, queryText]);

  function addCompare(code: string) {
    setCompareCodes((current) => {
      if (current.includes(code)) {
        setCompareMessage("该基金已在比较池中。");
        return current;
      }
      if (current.length >= 5) {
        setCompareMessage("比较池最多 5 只基金。");
        return current;
      }
      setCompareMessage("");
      return [...current, code];
    });
  }

  function removeCompare(code: string) {
    setCompareMessage("");
    setCompareCodes((current) => current.filter((item) => item !== code));
  }

  const compareHref = compareCodes.length ? { pathname: "/compare", query: { codes: compareCodes.join(",") } } : "/compare";

  return (
    <>
      <PageHeader
        title="基金筛选"
        description="四步筛选框架已按默认规则执行：成立年限、规模、收益分位、回撤、夏普比率和费用。"
        actions={(
          <>
            <span className="text-xs text-[var(--text-muted)]">已选比较 {compareCodes.length}/5</span>
            <Link
              href={compareHref}
              className={`focus-ring inline-flex h-9 items-center rounded-md px-3 text-sm font-medium ${compareCodes.length >= 2 ? "bg-[var(--accent)] text-white" : "border border-[var(--border)] text-[var(--text-muted)]"}`}
            >
              进入比较
            </Link>
          </>
        )}
      />
      <div className="grid gap-4 xl:grid-cols-[280px_minmax(0,1fr)_420px]">
        <aside className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
          <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><Filter className="h-4 w-4" />四步筛选器</div>
          {[
            ["基础条件", `类型 ${activeFilter.fund_types.join(" / ")} · 规模 ${activeFilter.size_range[0]}-${activeFilter.size_range[1]} 亿`],
            ["核心指标", `收益分位 ≤ ${activeFilter.return_rank_percentile}% · 夏普 ≥ ${activeFilter.sharpe_gte}`],
            ["费用结构", `费用合计 ≤ ${activeFilter.fee_lte}%`],
            ["基金经理", `管理年限 ≥ ${activeFilter.min_years} 年`]
          ].map(([step, description], index) => (
            <div key={step} className="border-t border-[var(--border)] py-3">
              <div className="text-xs text-[var(--text-muted)]">Step {index + 1}</div>
              <div className="mt-1 text-sm font-medium">{step}</div>
              <div className="mt-1 text-xs leading-5 text-[var(--text-muted)]">{description}</div>
            </div>
          ))}
          <ComplianceNotice>{riskProfileComplianceMessage(effectiveRisk.profile, effectiveRisk.usesDefault)}</ComplianceNotice>
        </aside>
        <section className="grid gap-3">
          <StaleDataNotice updatedAt={fundsQuery.data?.meta.data_updated_at} />
          <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto]">
            <label className="flex h-10 items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3">
              <Search className="h-4 w-4 text-[var(--text-muted)]" />
              <input
                className="w-full bg-transparent text-sm outline-none"
                value={queryText}
                onChange={(event) => setQueryText(event.target.value)}
                placeholder="按名称或代码搜索"
              />
            </label>
            <div className="flex min-h-10 flex-wrap items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1">
              <ArrowUpDown className="h-4 w-4 text-[var(--text-muted)]" />
              {sortOptions.map((option, index) => (
                <button
                  key={option.label}
                  className={`focus-ring h-7 rounded-md px-2 text-xs ${sortIndex === index ? "bg-[var(--accent)] text-white" : "text-[var(--text-muted)] hover:bg-[var(--surface-muted)]"}`}
                  onClick={() => setSortIndex(index)}
                >
                  {option.label}
                </button>
              ))}
            </div>
          </div>
          {compareCodes.length ? (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] p-2 text-xs">
              {compareCodes.map((code) => (
                <button
                  key={code}
                  className="focus-ring inline-flex h-7 items-center gap-1 rounded-md bg-[var(--surface-muted)] px-2"
                  onClick={() => removeCompare(code)}
                >
                  {code}<X className="h-3 w-3" />
                </button>
              ))}
              {compareStatusMessage ? <span className="text-[var(--r4)]">{compareStatusMessage}</span> : null}
            </div>
          ) : null}
          {fundsQuery.isLoading ? <LoadingBlock /> : fundsQuery.isError ? (
            <ErrorState
              title="基金列表加载失败"
              description="无法获取筛选结果，请确认 API 服务可用后重试。"
              onRetry={() => void fundsQuery.refetch()}
            />
          ) : funds.length ? (
            <FundTable
              funds={funds}
              selectedCode={selectedCode}
              compareCodes={compareCodes}
              riskProfile={activeFilter.risk_profile}
              onSelect={setSelectedCode}
              onCompare={addCompare}
              onRemoveCompare={removeCompare}
            />
          ) : (
            <EmptyState title="没有符合条件的基金" description="可以放宽夏普、费用或基金类型筛选条件。" />
          )}
        </section>
        <aside>
          <FundDetailPanel code={selectedCode ?? funds[0]?.code} riskProfile={effectiveRisk.profile} />
        </aside>
      </div>
    </>
  );
}
