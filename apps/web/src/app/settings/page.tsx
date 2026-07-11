"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { ComplianceNotice } from "@/components/compliance-notice";
import { DataStatusNotice } from "@/components/data-status-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetricTile } from "@/components/metric-tile";
import { PageHeader } from "@/components/page-header";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { DataSyncResult } from "@/lib/api/types";
import { DEFAULT_DATA_SOURCE } from "@/lib/compliance/constants";

const syncTasks: Array<{ value: DataSyncResult["task"]; label: string }> = [
  { value: "all", label: "全部同步" },
  { value: "profiles", label: "基金资料" },
  { value: "navs", label: "净值" },
  { value: "metrics", label: "指标" },
  { value: "risk_levels", label: "风险等级" }
];

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({ queryKey: ["data-status"], queryFn: apiClient.dataStatus });
  const jobsQuery = useQuery({ queryKey: ["data-jobs-recent", 5], queryFn: () => apiClient.recentDataJobs(5) });
  const syncMutation = useMutation({
    mutationFn: (task: DataSyncResult["task"]) => apiClient.syncData(task),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["data-status"] });
      void queryClient.invalidateQueries({ queryKey: ["data-jobs-recent"] });
      void queryClient.invalidateQueries({ queryKey: ["funds"] });
    }
  });
  const status = statusQuery.data?.data;
  const jobs = jobsQuery.data?.data ?? [];

  return (
    <>
      <PageHeader title="设置" description="配置数据源、LLM provider、风险测评有效期和本地数据清理。" />
      <div className="mb-4 grid gap-3">
        <DataStatusNotice status={status} />
        {statusQuery.isError ? (
          <ErrorState
            title="数据状态加载失败"
            description="无法确认数据库连接和数据新鲜度，请检查 API 服务。"
            onRetry={() => void statusQuery.refetch()}
          />
        ) : null}
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <section className="grid gap-3">
          <div className="grid gap-3 md:grid-cols-3">
            <MetricTile label="数据源" value={DEFAULT_DATA_SOURCE} hint="FUND_DATA_SOURCE" />
            <MetricTile label="数据状态" value={status?.freshness_status ?? "empty"} hint={`stale ${status?.stale_after_days ?? 7} 天`} />
            <MetricTile label="基金数量" value={String(status?.fund_count ?? 0)} hint={status?.latest_data_updated_at?.slice(0, 10) ?? "暂无日期"} />
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
            <h2 className="text-sm font-semibold">手动同步</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {syncTasks.map((task) => (
                <button
                  key={task.value}
                  className="focus-ring inline-flex h-9 items-center gap-2 rounded-md border border-[var(--border)] px-3 text-sm hover:bg-[var(--surface-muted)] disabled:cursor-not-allowed disabled:opacity-50"
                  disabled={syncMutation.isPending}
                  onClick={() => syncMutation.mutate(task.value)}
                >
                  <RefreshCw className="h-4 w-4" />
                  {task.label}
                </button>
              ))}
            </div>
            {syncMutation.data ? (
              <p className="mt-3 text-sm text-[var(--text-muted)]">已完成：{syncMutation.data.data.task}</p>
            ) : null}
            {syncMutation.isError ? (
              <div className="mt-3">
                <ErrorState
                  title="同步任务启动失败"
                  description={getApiErrorMessage(syncMutation.error, "未写入新数据，请检查数据源配置和最近任务错误后重试。")}
                />
              </div>
            ) : null}
          </div>
          <div className="grid gap-3 md:grid-cols-2">
            {["盈米 MCP 配置", "LLM provider 配置", "风险测评有效期", "本地数据清理"].map((item) => (
              <section key={item} className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
                <h2 className="text-base font-semibold">{item}</h2>
                <p className="mt-2 text-sm text-[var(--text-muted)]">个人部署默认本地保存配置，敏感字段不进入向量库。</p>
              </section>
            ))}
          </div>
        </section>
        <aside className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
          <h2 className="text-sm font-semibold">最近同步任务</h2>
          {jobsQuery.isLoading ? <LoadingBlock /> : jobsQuery.isError ? (
            <div className="mt-3">
              <ErrorState
                title="同步任务记录加载失败"
                description="无法读取最近运行记录。"
                onRetry={() => void jobsQuery.refetch()}
              />
            </div>
          ) : jobs.length ? (
            <div className="mt-3 grid gap-2">
              {jobs.map((job) => (
                <div key={job.id} className="rounded-md border border-[var(--border)] bg-[var(--background)] p-3 text-sm">
                  <div className="flex items-center justify-between gap-3">
                    <span className="font-medium">{job.name}</span>
                    <span className="text-xs text-[var(--text-muted)]">{job.status}</span>
                  </div>
                  <div className="mt-1 text-xs text-[var(--text-muted)]">{job.finished_at ?? job.started_at}</div>
                  {job.error_detail ? <div className="mt-1 text-xs text-[var(--danger)]">{job.error_detail}</div> : null}
                </div>
              ))}
            </div>
          ) : <div className="mt-3"><EmptyState title="暂无同步记录" description="运行一次手动同步后，任务结果会显示在这里。" /></div>}
        </aside>
      </div>
      <div className="mt-4"><ComplianceNotice /></div>
    </>
  );
}
