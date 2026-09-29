"use client";

import { useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { X } from "lucide-react";
import Link from "next/link";
import { Button } from "@/components/button";
import { ComplianceNotice } from "@/components/compliance-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { PageHeader } from "@/components/page-header";
import { StaleDataNotice } from "@/components/stale-data-notice";
import { FundDetailPanel } from "@/features/funds/fund-detail-panel";
import {
  createDefaultFundFilterCriteria,
  createFundFilterPayload,
  type FundFilterCriteria,
  type FundSort,
  normalizeFundKeyword
} from "@/features/funds/fund-filter-model";
import { FundFilterPanel } from "@/features/funds/fund-filter-panel";
import { FundSearchToolbar } from "@/features/funds/fund-search-toolbar";
import { FundTable } from "@/features/funds/fund-table";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import { riskProfileComplianceMessage } from "@/lib/compliance/constants";
import { resolveEffectiveRiskProfile } from "@/lib/risk/effective-profile";

const sortOptions: Array<FundSort & { label: string }> = [
  { label: "收益", sort_by: "annualized_return_3y", sort_order: "desc" },
  { label: "回撤", sort_by: "max_drawdown", sort_order: "desc" },
  { label: "夏普", sort_by: "sharpe_ratio", sort_order: "desc" },
  { label: "费用", sort_by: "fee", sort_order: "asc" },
  { label: "规模", sort_by: "size", sort_order: "desc" }
];

export function FundsPage() {
  const [queryText, setQueryText] = useState("");
  const [selectedCode, setSelectedCode] = useState<string>();
  const [compareCodes, setCompareCodes] = useState<string[]>([]);
  const [sortIndex, setSortIndex] = useState(0);
  const [compareMessage, setCompareMessage] = useState("");
  const [draftFilter, setDraftFilter] = useState<FundFilterCriteria>(createDefaultFundFilterCriteria);
  const [appliedFilter, setAppliedFilter] = useState<FundFilterCriteria>(createDefaultFundFilterCriteria);
  const riskQuery = useQuery({ queryKey: ["risk-latest"], queryFn: apiClient.latestRiskAssessment });
  const effectiveRisk = resolveEffectiveRiskProfile(riskQuery.data?.data);
  const activeSort = sortOptions[sortIndex] ?? sortOptions[0];
  const normalizedKeyword = normalizeFundKeyword(queryText);
  const isSearchMode = Boolean(normalizedKeyword);
  const isDataBrowseMode = effectiveRisk.usesDefault;
  const activeFilter = useMemo(
    () => createFundFilterPayload(appliedFilter, effectiveRisk.profile, activeSort, normalizedKeyword),
    [activeSort, appliedFilter, effectiveRisk.profile, normalizedKeyword]
  );
  const browseFilter = useMemo(
    () => createFundFilterPayload(
      {
        fund_types: ["mixed", "bond", "stock", "money"],
        min_years: 0,
        size_range: [0, 100000],
        return_rank_percentile: 100,
        max_drawdown_lte_category_avg: false,
        sharpe_gte: -100,
        fee_lte: 100
      },
      "C5",
      activeSort,
      normalizedKeyword
    ),
    [activeSort, normalizedKeyword]
  );
  const compareStatusMessage = compareCodes.length >= 5
    ? "比较池已满，最多 5 只基金。"
    : compareCodes.length === 1
      ? "请再选择 1 只基金后进入比较。"
      : compareMessage;
  const fundsQuery = useQuery({
    queryKey: ["funds", isDataBrowseMode ? "browse" : "filter", activeFilter],
    // Before a risk assessment exists, browse the complete synced universe so
    // the user can see what is actually in SQLite. Once an assessment exists,
    // the editable four-step criteria and risk profile are enforced together.
    queryFn: () => apiClient.filterFunds(isDataBrowseMode ? browseFilter : activeFilter),
    enabled: !riskQuery.isLoading
  });
  const funds = useMemo(() => fundsQuery.data?.data ?? [], [fundsQuery.data?.data]);
  const detailCode = selectedCode && funds.some((fund) => fund.code === selectedCode)
    ? selectedCode
    : funds[0]?.code;

  function applyFilter() {
    setAppliedFilter(draftFilter);
  }

  function resetFilter() {
    setDraftFilter(createDefaultFundFilterCriteria());
    setAppliedFilter(createDefaultFundFilterCriteria());
  }

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

  const compareHref = { pathname: "/compare", query: { codes: compareCodes.join(",") } };

  return (
    <>
      <PageHeader
        title="基金筛选"
        description="编辑四步条件生成风险匹配推荐；输入名称或代码时切换为服务端关键词浏览。"
        actions={(
          <>
            <span className="text-xs text-[var(--text-muted)]">已选比较 {compareCodes.length}/5</span>
            {compareCodes.length >= 2 ? (
              <Link
                href={compareHref}
                className="focus-ring inline-flex h-9 items-center rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white"
              >
                进入比较
              </Link>
            ) : (
              <Button
                variant="secondary"
                size="compact"
                disabled
                className="text-[var(--text-muted)] opacity-70"
                title="至少选择 2 只基金后才能比较"
              >
                进入比较
              </Button>
            )}
          </>
        )}
      />
      <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)] 2xl:grid-cols-[300px_minmax(0,1fr)_420px]">
        <div className="grid h-fit gap-3">
          <FundFilterPanel
            riskProfile={effectiveRisk.profile}
            usesDefaultRiskProfile={effectiveRisk.usesDefault}
            value={draftFilter}
            appliedValue={appliedFilter}
            onChange={setDraftFilter}
            onApply={applyFilter}
            onReset={resetFilter}
          />
          <ComplianceNotice>{riskProfileComplianceMessage(effectiveRisk.profile, effectiveRisk.usesDefault)}</ComplianceNotice>
        </div>
        <section className="grid content-start gap-3">
          <StaleDataNotice updatedAt={fundsQuery.data?.meta.data_updated_at} />
          <FundSearchToolbar
            keyword={queryText}
            onKeywordChange={setQueryText}
            sortOptions={sortOptions}
            activeSortIndex={sortIndex}
            onSortChange={setSortIndex}
          />
          <div className={`rounded-md border p-3 text-xs leading-5 ${isSearchMode ? "border-[var(--r3)] bg-[var(--surface)] text-[var(--text-muted)]" : "border-[var(--border)] bg-[var(--surface-muted)] text-[var(--text-muted)]"}`} role="status">
            {isSearchMode ? (
              <>
                <strong className="text-[var(--text)]">关键词浏览：</strong>
                服务端按名称或代码在当前 {effectiveRisk.profile} 风险画像与全部已应用四步条件内继续收窄。该结果来自用户主动搜索，不视为个性化推荐；清空关键词可恢复完整风险匹配筛选。
              </>
            ) : (
              <>
                <strong className="text-[var(--text)]">{isDataBrowseMode ? "基金数据浏览：" : "筛选推荐："}</strong>
                {isDataBrowseMode
                  ? "尚未完成有效风险测评，当前展示已同步的基金基础数据；完成风险测评后将自动启用风险匹配筛选。"
                  : `服务端严格使用 ${effectiveRisk.profile} 风险画像与已应用的四步条件，不返回风险超配基金。`}
              </>
            )}
          </div>
          {compareCodes.length ? (
            <div className="flex flex-wrap items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] p-2 text-xs">
              {compareCodes.map((code) => (
                <Button
                  key={code}
                  variant="unstyled"
                  size="none"
                  className="inline-flex h-7 items-center gap-1 rounded-md bg-[var(--surface-muted)] px-2"
                  onClick={() => removeCompare(code)}
                >
                  {code}<X className="h-3 w-3" />
                </Button>
              ))}
              {compareStatusMessage ? <span className="text-[var(--r4)]">{compareStatusMessage}</span> : null}
            </div>
          ) : null}
          {riskQuery.isLoading || fundsQuery.isLoading ? <LoadingBlock /> : fundsQuery.isError ? (
            <ErrorState
              title={isSearchMode ? "基金搜索失败" : "基金筛选失败"}
              description={getApiErrorMessage(
                fundsQuery.error,
                isDataBrowseMode
                  ? "无法获取已同步的基金数据，请确认 API 服务可用后重试。"
                  : isSearchMode
                  ? "无法获取关键词搜索结果，请确认 API 服务可用后重试。"
                  : "无法获取筛选推荐结果，请确认 API 服务可用后重试。"
              )}
              onRetry={() => void fundsQuery.refetch()}
            />
          ) : funds.length ? (
            <FundTable
              funds={funds}
              selectedCode={selectedCode}
              compareCodes={compareCodes}
              riskProfile={effectiveRisk.profile}
              onSelect={setSelectedCode}
              onCompare={addCompare}
              onRemoveCompare={removeCompare}
            />
          ) : (
            <EmptyState
              title={isSearchMode ? "没有匹配关键词的基金" : "没有符合条件的基金"}
              description={isSearchMode
                ? "请尝试其他名称或代码，或调整基金类型后再搜索。"
                : "可以放宽夏普、费用、规模或基金类型条件后重新应用筛选。"}
            />
          )}
        </section>
        <aside className="xl:col-span-2 2xl:col-span-1">
          <FundDetailPanel code={detailCode} riskProfile={effectiveRisk.profile} />
        </aside>
      </div>
    </>
  );
}
