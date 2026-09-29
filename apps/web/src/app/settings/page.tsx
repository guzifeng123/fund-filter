"use client";

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { RefreshCw } from "lucide-react";
import { Button } from "@/components/button";
import { ComplianceNotice } from "@/components/compliance-notice";
import { DataStatusNotice } from "@/components/data-status-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetricTile } from "@/components/metric-tile";
import { PageHeader } from "@/components/page-header";
import { SettingsObservabilityCard } from "@/components/settings-observability-card";
import { SettingsStatusCard, type SettingsStatusLabel } from "@/components/settings-status-card";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { DataSyncResult, RuntimeSettingsData } from "@/lib/api/types";

const syncTasks: Array<{ value: DataSyncResult["task"]; label: string }> = [
  { value: "all", label: "一键拉取全部数据" },
  { value: "profiles", label: "基金资料" },
  { value: "navs", label: "净值" },
  { value: "metrics", label: "指标" },
  { value: "risk_levels", label: "风险等级" }
];

export function RuntimeSettingsCards({ runtime }: { runtime: RuntimeSettingsData }) {
  const llmStatus: SettingsStatusLabel = runtime.llm.configured ? "已配置" : "未配置";
  const yingmiStatus: SettingsStatusLabel = runtime.yingmi_mcp.implemented
    ? runtime.yingmi_mcp.configured ? "已配置" : "未配置"
    : "未实现";
  const llmProvider = runtime.llm.provider ?? "未设置";
  const llmModel = runtime.llm.model ?? "未设置";

  return (
    <div className="grid gap-3 md:grid-cols-2">
      <SettingsStatusCard
        title="盈米 MCP 配置"
        status={yingmiStatus}
        description={`端点状态：${runtime.yingmi_mcp.configured ? "已配置" : "未配置"}；当前版本尚未实现 YingmiMcpFundDataSource。`}
        action="如需接入，应先在后端实现独立 adapter、认证与限额处理；本页面不会读取或展示端点和凭据。"
      />
      <SettingsStatusCard
        title="LLM provider 配置"
        status={llmStatus}
        description={`Provider：${llmProvider}；模型：${llmModel}${runtime.llm.mock_mode ? "；当前使用本地 mock 降级" : ""}。`}
        action={runtime.llm.configured
          ? "通过服务器环境变量维护配置；本页面只读且不会返回 API key 或服务端点。"
          : "在服务器环境变量中补齐 provider、model、API key 与兼容服务地址后重启 API。"}
      />
      <SettingsStatusCard
        title="风险测评有效期"
        status="手动维护"
        description={`当前有效期为 ${runtime.risk_assessment.validity_months} 个月，由后端风险测评规则统一计算。`}
        action="页面暂不支持修改；调整规则需修改后端配置与测试后重新部署。"
      />
      <SettingsStatusCard
        title="本地数据清理"
        status="手动维护"
        description={`清理方式：PowerShell 手动脚本；预检：${runtime.cleanup.dry_run_supported ? "支持" : "不支持"}；自动清理：${runtime.cleanup.automatic_cleanup_supported ? "支持" : "不支持"}。`}
        action="先运行 .\\scripts\\clean-generated.ps1 -WhatIf 检查范围，确认后再手动执行清理。"
      />
      <SettingsObservabilityCard observability={runtime.llm.observability} />
    </div>
  );
}

export default function SettingsPage() {
  const queryClient = useQueryClient();
  const statusQuery = useQuery({ queryKey: ["data-status"], queryFn: apiClient.dataStatus });
  const jobsQuery = useQuery({ queryKey: ["data-jobs-recent", 5], queryFn: () => apiClient.recentDataJobs(5) });
  const schedulerQuery = useQuery({ queryKey: ["data-scheduler-status"], queryFn: apiClient.schedulerStatus });
  const runtimeQuery = useQuery({ queryKey: ["settings-runtime"], queryFn: apiClient.runtimeSettings });
  const syncMutation = useMutation({
    mutationFn: (task: DataSyncResult["task"]) => apiClient.syncData(task),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["data-status"] });
      void queryClient.invalidateQueries({ queryKey: ["data-jobs-recent"] });
      void queryClient.invalidateQueries({ queryKey: ["data-scheduler-status"] });
      void queryClient.invalidateQueries({ queryKey: ["settings-runtime"] });
      void queryClient.invalidateQueries({ queryKey: ["funds"] });
    }
  });
  const status = statusQuery.data?.data;
  const jobs = jobsQuery.data?.data ?? [];
  const scheduler = schedulerQuery.data?.data;
  const runtime = runtimeQuery.data?.data;

  return (
    <>
      <PageHeader title="设置" description="配置数据源、LLM provider、风险测评有效期和本地数据清理。" />
      <div className="mb-4 grid gap-3">
        <DataStatusNotice status={status} />
        {statusQuery.isError ? (
          <ErrorState
            title="数据状态加载失败"
            description={getApiErrorMessage(statusQuery.error, "无法确认数据库连接和数据新鲜度，请检查 API 服务。")}
            onRetry={() => void statusQuery.refetch()}
          />
        ) : null}
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_420px]">
        <section className="grid gap-3">
          <div className="grid gap-3 md:grid-cols-3">
            <MetricTile
              label="实际数据源"
              value={runtime?.data_source.actual_source ?? status?.source ?? "加载中"}
              hint={`配置：${runtime?.data_source.configured_source ?? "加载中"}${runtime && !runtime.data_source.configured ? "（未就绪）" : ""}`}
            />
            <MetricTile label="数据状态" value={status?.freshness_status ?? "empty"} hint={`stale ${status?.stale_after_days ?? 7} 天`} />
            <MetricTile label="基金数量" value={String(status?.fund_count ?? 0)} hint={status?.latest_data_updated_at?.slice(0, 10) ?? "暂无日期"} />
          </div>
          <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
            <h2 className="text-sm font-semibold">手动同步</h2>
            <div className="mt-3 flex flex-wrap gap-2">
              {syncTasks.map((task) => (
                <Button
                  key={task.value}
                  variant={task.value === "all" ? "primary" : "secondary"}
                  size="compact"
                  disabled={syncMutation.isPending}
                  onClick={() => syncMutation.mutate(task.value)}
                >
                  <RefreshCw className={`h-4 w-4 ${syncMutation.isPending && syncMutation.variables === task.value ? "animate-spin" : ""}`} />
                  {syncMutation.isPending && syncMutation.variables === task.value ? "拉取中..." : task.label}
                </Button>
              ))}
            </div>
            {syncMutation.data ? (
              <p className="mt-3 text-sm text-[var(--text-muted)]">数据拉取完成，基金列表与数据状态已刷新。</p>
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
          <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
            <h2 className="text-sm font-semibold">同步调度器</h2>
            {schedulerQuery.isLoading ? <LoadingBlock /> : schedulerQuery.isError ? (
              <div className="mt-3">
                <ErrorState
                  title="调度器状态加载失败"
                  description={getApiErrorMessage(schedulerQuery.error, "无法读取调度配置和运行中任务。")}
                  onRetry={() => void schedulerQuery.refetch()}
                />
              </div>
            ) : scheduler ? (
              <div className="mt-3 grid gap-2 text-sm text-[var(--text-muted)] md:grid-cols-2">
                <div>启用状态：<strong className="text-[var(--text)]">{scheduler.enabled ? "已启用" : "已停用"}</strong></div>
                <div>进程状态：<strong className="text-[var(--text)]">{scheduler.running ? "运行中" : "未运行"}</strong></div>
                <div>计划：<strong className="text-[var(--text)]">{scheduler.schedule_mode} · {scheduler.schedule_expression}</strong></div>
                <div>时区：<strong className="text-[var(--text)]">{scheduler.timezone}</strong></div>
                <div>错峰：<strong className="text-[var(--text)]">0-{scheduler.jitter_seconds} 秒</strong></div>
                <div>下次运行：<strong className="text-[var(--text)]">{scheduler.next_run_at ?? "暂无"}</strong></div>
                <div className="md:col-span-2">运行中任务：<strong className="text-[var(--text)]">{scheduler.running_tasks.length ? scheduler.running_tasks.map((job) => job.name).join("、") : "无"}</strong></div>
              </div>
            ) : null}
          </div>
          {runtimeQuery.isLoading ? <LoadingBlock /> : runtimeQuery.isError ? (
            <ErrorState
              title="运行配置状态加载失败"
              description={getApiErrorMessage(runtimeQuery.error, "无法读取只读配置状态；敏感配置不会由该接口返回。")}
              onRetry={() => void runtimeQuery.refetch()}
            />
          ) : runtime ? <RuntimeSettingsCards runtime={runtime} /> : null}
        </section>
        <aside className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
          <h2 className="text-sm font-semibold">最近同步任务</h2>
          {jobsQuery.isLoading ? <LoadingBlock /> : jobsQuery.isError ? (
            <div className="mt-3">
              <ErrorState
                title="同步任务记录加载失败"
                description={getApiErrorMessage(jobsQuery.error, "无法读取最近运行记录。")}
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
