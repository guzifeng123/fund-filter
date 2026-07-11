"use client";

import { useQuery } from "@tanstack/react-query";
import { ChartCard } from "@/components/chart-card";
import { ComplianceNotice } from "@/components/compliance-notice";
import { DataFreshnessBadge } from "@/components/data-freshness-badge";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetricTile } from "@/components/metric-tile";
import { RiskLevelBadge } from "@/components/risk-level-badge";
import { StaleDataNotice } from "@/components/stale-data-notice";
import { apiClient } from "@/lib/api/client";
import type { FundDetail } from "@/lib/api/types";
import { COMPLIANCE_MESSAGES, type RiskProfile } from "@/lib/compliance/constants";
import { resolveEffectiveRiskProfile } from "@/lib/risk/effective-profile";

export function FundNavSummary({ navs }: { navs: FundDetail["navs"] }) {
  const latestNav = navs.at(-1);

  return (
    <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
      <h3 className="text-sm font-semibold">净值摘要</h3>
      {latestNav ? (
        <div className="mt-3 grid grid-cols-3 gap-2 text-sm">
          <div>
            <div className="text-xs text-[var(--text-muted)]">日期</div>
            <div className="mt-1 font-medium">{latestNav.trade_date}</div>
          </div>
          <div>
            <div className="text-xs text-[var(--text-muted)]">单位净值</div>
            <div className="mt-1 font-medium">{latestNav.nav.toFixed(4)}</div>
          </div>
          <div>
            <div className="text-xs text-[var(--text-muted)]">累计净值</div>
            <div className="mt-1 font-medium">{latestNav.accumulated_nav.toFixed(4)}</div>
          </div>
        </div>
      ) : (
        <p className="mt-3 text-xs leading-5 text-[var(--text-muted)]">暂无可展示的净值点。</p>
      )}
    </section>
  );
}

export function FundDetailPanel({ code, riskProfile }: { code?: string; riskProfile?: RiskProfile }) {
  const riskQuery = useQuery({
    queryKey: ["risk-latest"],
    queryFn: apiClient.latestRiskAssessment,
    enabled: !riskProfile
  });
  const effectiveRisk = riskProfile
    ? { profile: riskProfile, usesDefault: false }
    : resolveEffectiveRiskProfile(riskQuery.data?.data);
  const query = useQuery({
    queryKey: ["fund", code, effectiveRisk.profile],
    queryFn: () => apiClient.fundDetail(code ?? "", effectiveRisk.profile),
    enabled: Boolean(code)
  });

  if (!code) {
    return <LoadingBlock label="选择一只基金查看详情" />;
  }

  if (query.isLoading) {
    return <LoadingBlock />;
  }

  if (query.isError || !query.data) {
    return (
      <div className="grid gap-3">
        <ErrorState
          title="基金详情加载失败"
          description="无法读取基金指标和净值数据，请检查基金代码或 API 服务后重试。"
          onRetry={() => void query.refetch()}
        />
        <ComplianceNotice>{COMPLIANCE_MESSAGES.fundDetailUnavailable}</ComplianceNotice>
      </div>
    );
  }

  const fund = query.data.data;

  return (
    <div className="grid gap-3">
      <StaleDataNotice updatedAt={query.data.meta.data_updated_at ?? fund.data_updated_at} />
      <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
        <div className="flex items-start justify-between gap-3">
          <div>
            <h2 className="text-base font-semibold">{fund.name}</h2>
            <p className="mt-1 text-xs text-[var(--text-muted)]">{fund.code} · {fund.fund_type}</p>
          </div>
          <RiskLevelBadge level={fund.risk_level} />
        </div>
        <p className="mt-3 text-sm leading-6 text-[var(--text-muted)]">{fund.ai_summary}</p>
        {fund.risk_match ? (
          <div className="mt-3 rounded-md border border-[var(--border)] bg-[var(--background)] p-3 text-sm">
            <div className="font-medium">
              {fund.risk_match.matched ? "风险匹配" : "风险不匹配"} · {fund.risk_match.user_risk_profile}
            </div>
            <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">{fund.risk_match.message}</p>
          </div>
        ) : null}
        <div className="mt-3">
          <DataFreshnessBadge source={fund.source} updatedAt={fund.data_updated_at} />
        </div>
      </div>
      <FundNavSummary navs={fund.navs} />
      <div className="grid grid-cols-2 gap-2">
        <MetricTile label="3年年化" value={`${fund.annualized_return_3y.toFixed(2)}%`} />
        <MetricTile label="最大回撤" value={`${fund.max_drawdown.toFixed(2)}%`} />
        <MetricTile label="夏普比率" value={fund.sharpe_ratio.toFixed(2)} />
        <MetricTile label="同类排名" value={`前 ${fund.category_rank_percentile.toFixed(0)}%`} />
        <MetricTile label="费用合计" value={`${(fund.fee_summary?.total_fee ?? fund.management_fee).toFixed(2)}%`} />
      </div>
      <div className="grid gap-3 md:grid-cols-2">
        <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
          <h3 className="text-sm font-semibold">费用结构</h3>
          <div className="mt-3 grid gap-2 text-sm text-[var(--text-muted)]">
            <div>管理费：{(fund.fee_summary?.management_fee ?? fund.management_fee).toFixed(2)}%</div>
            <div>托管费：{(fund.fee_summary?.custody_fee ?? fund.custody_fee).toFixed(2)}%</div>
            <div>合计：{(fund.fee_summary?.total_fee ?? fund.management_fee + fund.custody_fee).toFixed(2)}%</div>
          </div>
          <p className="mt-3 text-xs leading-5 text-[var(--text-muted)]">{fund.fee_summary?.explanation}</p>
        </section>
        <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
          <h3 className="text-sm font-semibold">基金经理</h3>
          <div className="mt-3 grid gap-2 text-sm text-[var(--text-muted)]">
            <div>{fund.manager_profile?.name ?? fund.manager_name}</div>
            <div>管理年限：{fund.manager_profile?.years ?? fund.manager_years} 年</div>
            <div>成立日期：{fund.manager_profile?.inception_date ?? fund.inception_date}</div>
          </div>
          <p className="mt-3 text-xs leading-5 text-[var(--text-muted)]">{fund.manager_profile?.explanation}</p>
        </section>
      </div>
      <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
        <h3 className="text-sm font-semibold">指标解释</h3>
        <div className="mt-3 grid gap-2">
          {fund.metric_explanations.map((metric) => (
            <div key={metric.key} className="rounded-md border border-[var(--border)] bg-[var(--background)] p-3">
              <div className="flex items-center justify-between gap-3 text-sm">
                <span className="font-medium">{metric.label}</span>
                <span>{metric.value}</span>
              </div>
              <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">{metric.explanation}</p>
            </div>
          ))}
        </div>
      </section>
      <ChartCard
        title="历史净值"
        source={fund.source}
        option={{
          tooltip: { trigger: "axis" },
          grid: { left: 36, right: 12, top: 20, bottom: 28 },
          xAxis: { type: "category", data: fund.navs.map((point) => point.trade_date) },
          yAxis: { type: "value", scale: true },
          series: [{ type: "line", smooth: true, data: fund.navs.map((point) => point.accumulated_nav), color: "#0f766e" }]
        }}
      />
      <ComplianceNotice />
    </div>
  );
}
