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

const freshnessLabels = {
  empty: "暂无数据",
  fresh: "正常",
  stale: "已过期",
  failed: "同步失败"
} as const;

export default function DashboardPage() {
  const query = useQuery({ queryKey: ["dashboard"], queryFn: apiClient.dashboard });
  const dataStatusQuery = useQuery({ queryKey: ["data-status"], queryFn: apiClient.dataStatus });
  const recentJobsQuery = useQuery({ queryKey: ["data-jobs-recent"], queryFn: () => apiClient.recentDataJobs(1) });
  const dataStatus = dataStatusQuery.data?.data;
  const recentJob = recentJobsQuery.data?.data[0];
  const latestDataDate = dataStatus?.latest_data_updated_at?.slice(0, 10) ?? "暂无数据";
  const freshnessStatus = dataStatus?.freshness_status ?? "empty";
  const freshnessHint =
    freshnessStatus === "stale"
      ? `超过 ${dataStatus?.stale_after_days ?? 0} 天`
      : recentJob?.error_detail ?? dataStatus?.last_job?.status ?? "本地数据源";

  return (
    <>
      <PageHeader title="个人首页" description="先看风险、数据新鲜度和组合状态，再进入筛选或回测。" />
      {query.isLoading ? <LoadingBlock /> : query.isError ? (
        <ErrorState
          title="首页数据加载失败"
          description="无法读取风险画像和组合状态，请检查 API 服务后重试。"
          onRetry={() => void query.refetch()}
        />
      ) : (
        <div className="grid gap-4">
          <DataStatusNotice status={dataStatus} />
          <div className="grid gap-3 md:grid-cols-4">
            <MetricTile label="风险测评" value={query.data?.data.risk_profile ?? "C3"} hint="有效期 12 个月" />
            <MetricTile label="组合健康" value={query.data?.data.health ?? "稳健"} hint="偏离阈值 5%" />
            <MetricTile label="自选更新时间" value="20:30" hint={query.data?.data.watchlist_updated_at ?? ""} />
            <MetricTile label="AI 助手" value="可用" hint="解释指标与回测" />
          </div>
          <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold">
              <Database className="h-4 w-4 text-[var(--accent)]" />数据状态
            </div>
            {dataStatusQuery.isError ? (
              <ErrorState
                title="数据状态检查失败"
                description="业务数据仍可能可用，但当前无法确认数据库连接和数据新鲜度。"
                onRetry={() => void dataStatusQuery.refetch()}
              />
            ) : <div className="grid gap-3 md:grid-cols-4">
              <MetricTile
                label="数据状态"
                value={freshnessLabels[freshnessStatus]}
                hint={freshnessHint}
              />
              <MetricTile
                label="数据库"
                value={dataStatusQuery.isError ? "异常" : dataStatus?.db_connected ? "已连接" : "未连接"}
                hint={dataStatusQuery.isLoading ? "检查中" : "本地数据源"}
              />
              <MetricTile label="基金数量" value={String(dataStatus?.fund_count ?? 0)} hint="funds" />
              <MetricTile label="数据日期" value={latestDataDate} hint={dataStatus?.last_job?.status ?? "无任务记录"} />
            </div>}
          </section>
          <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
            <div className="mb-3 flex items-center gap-2 text-sm font-semibold"><AlertTriangle className="h-4 w-4 text-[var(--r3)]" />近期风险提示</div>
            {(query.data?.data.alerts ?? []).length ? <div className="grid gap-2">
              {query.data?.data.alerts.map((alert) => (
                <div key={alert} className="flex items-center gap-2 text-sm text-[var(--text-muted)]">
                  <CheckCircle2 className="h-4 w-4 text-[var(--accent)]" />
                  {alert}
                </div>
              ))}
            </div> : <EmptyState title="暂无风险提示" description="当前没有需要关注的组合偏离或风险画像提醒。" />}
          </div>
          <Link href="/assistant" className="focus-ring inline-flex h-10 w-fit items-center gap-2 rounded-md bg-[var(--accent)] px-4 text-sm font-medium text-white">
            <Bot className="h-4 w-4" /> 打开 AI 助手
          </Link>
          <ComplianceNotice />
        </div>
      )}
    </>
  );
}
