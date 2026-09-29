"use client";

import { useQuery } from "@tanstack/react-query";
import { AlertTriangle, Bot, CheckCircle2, Database } from "lucide-react";
import Link from "next/link";
import { ComplianceNotice } from "@/components/compliance-notice";
import { DataStatusNotice } from "@/components/data-status-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetricTile } from "@/components/metric-tile";
import { PageHeader } from "@/components/page-header";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { DashboardData } from "@/lib/api/types";

const freshnessLabels = {
  empty: "暂无数据",
  fresh: "正常",
  stale: "已过期",
  failed: "同步失败"
} as const;

const jobStatusLabels = {
  running: "运行中",
  success: "成功",
  failed: "失败"
} as const;

export function DashboardContent({ dashboard }: { dashboard: DashboardData }) {
  const dataStatus = dashboard.data_status;
  const recentJob = dashboard.recent_job;
  const latestDataDate = dataStatus.latest_data_updated_at?.slice(0, 10) ?? "暂无数据";
  const freshnessHint =
    dataStatus.freshness_status === "stale"
      ? `超过 ${dataStatus.stale_after_days} 天`
      : recentJob?.error_detail
        ?? dataStatus.last_job?.error_detail
        ?? (recentJob ? `${recentJob.name} · ${jobStatusLabels[recentJob.status]}` : `来源：${dataStatus.source}`);
  const portfolioHealthAvailable = dashboard.portfolio_health_status === "available";
  const watchlistAvailable = dashboard.watchlist_status === "available";
  const watchlistValue = watchlistAvailable
    ? dashboard.watchlist_updated_at?.slice(0, 10) ?? "暂无更新"
    : "未配置";
  const watchlistHint = watchlistAvailable
    ? dashboard.watchlist_updated_at ?? "尚无更新时间"
    : "自选基金数据表尚未接入";
  const riskNeedsAttention = dashboard.risk_status !== "valid";

  return (
    <div className="grid gap-4">
      <DataStatusNotice status={dataStatus} />
      <div className="grid gap-3 md:grid-cols-4">
        <MetricTile label="风险测评" value={dashboard.risk_profile} hint={dashboard.risk_notice} />
        <MetricTile
          label="组合健康"
          value={portfolioHealthAvailable ? dashboard.health : "暂不可用"}
          hint={portfolioHealthAvailable ? "基于当前组合计算" : "组合健康计算尚未接入"}
        />
        <MetricTile label="自选更新时间" value={watchlistValue} hint={watchlistHint} />
        <MetricTile label="AI 助手" value="可用" hint="解释指标与回测" />
      </div>
      <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <Database className="h-4 w-4 text-[var(--accent)]" />数据状态
        </div>
        <div className="grid gap-3 md:grid-cols-4">
          <MetricTile
            label="数据状态"
            value={freshnessLabels[dataStatus.freshness_status]}
            hint={freshnessHint}
          />
          <MetricTile
            label="数据库"
            value={dataStatus.db_connected ? "已连接" : "未连接"}
            hint={`来源：${dataStatus.source}`}
          />
          <MetricTile label="基金数量" value={String(dataStatus.fund_count)} hint={`${dataStatus.nav_count} 个净值点`} />
          <MetricTile
            label="数据日期"
            value={latestDataDate}
            hint={recentJob ? `${recentJob.name} · ${jobStatusLabels[recentJob.status]}` : "无任务记录"}
          />
        </div>
      </section>
      <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
        <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
          <AlertTriangle className="h-4 w-4 text-[var(--r3)]" />风险与业务提醒
        </div>
        <div className="mb-3 flex items-center gap-2 text-sm text-[var(--text-muted)]">
          {riskNeedsAttention ? (
            <AlertTriangle className="h-4 w-4 text-[var(--r3)]" />
          ) : (
            <CheckCircle2 className="h-4 w-4 text-[var(--accent)]" />
          )}
          {dashboard.risk_notice}
        </div>
        {dashboard.alerts_status === "available" ? (
          dashboard.alerts.length > 0 ? (
            <div className="grid gap-2">
              {dashboard.alerts.map((alert) => (
                <div key={alert} className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                  <AlertTriangle className="h-4 w-4 text-[var(--r3)]" />
                  {alert}
                </div>
              ))}
            </div>
          ) : (
            <EmptyState title="暂无业务提醒" description="当前提醒数据源没有待处理事项。" />
          )
        ) : (
          <EmptyState
            title="业务提醒未配置"
            description="自选基金与提醒数据表尚未接入；当前仅展示真实风险测评状态。"
          />
        )}
      </section>
      <Link href="/assistant" className="focus-ring inline-flex h-10 w-fit items-center gap-2 rounded-md bg-[var(--accent)] px-4 text-sm font-medium text-white">
        <Bot className="h-4 w-4" /> 打开 AI 助手
      </Link>
      <ComplianceNotice />
    </div>
  );
}

export default function DashboardPage() {
  const query = useQuery({ queryKey: ["dashboard"], queryFn: apiClient.dashboard });

  return (
    <>
      <PageHeader title="个人首页" description="先看风险、数据新鲜度和组合状态，再进入筛选或回测。" />
      {query.isLoading ? <LoadingBlock /> : query.isError ? (
        <ErrorState
          title="首页数据加载失败"
          description={getApiErrorMessage(query.error, "无法读取风险画像和数据状态，请检查 API 服务后重试。")}
          onRetry={() => void query.refetch()}
        />
      ) : query.data ? <DashboardContent dashboard={query.data.data} /> : null}
    </>
  );
}
