import { MetricTile } from "@/components/metric-tile";

const statusLabels: Record<
  "disabled" | "unavailable" | "insufficient_data" | "ok" | "alert",
  { label: string; className: string }
> = {
  disabled: { label: "已关闭", className: "border-[var(--border)] text-[var(--text-muted)]" },
  unavailable: { label: "不可用", className: "border-[var(--border)] text-[var(--text-muted)]" },
  insufficient_data: { label: "样本不足", className: "border-[var(--r3)] text-[var(--r3)]" },
  ok: { label: "正常", className: "border-[var(--accent)] text-[var(--accent)]" },
  alert: { label: "告警", className: "border-[var(--danger)] text-[var(--danger)]" }
};

const dispatcherStatusLabels: Record<"disabled" | "not_started" | "ok" | "degraded", string> = {
  disabled: "已关闭",
  not_started: "未启动",
  ok: "正常",
  degraded: "降级"
};

function formatRate(value: number) {
  return `${(value * 100).toFixed(1)}%`;
}

function formatLastEvent(lastEventAt: string | null) {
  if (!lastEventAt) {
    return "暂无";
  }
  return lastEventAt.slice(0, 19).replace("T", " ");
}

export function SettingsObservabilityCard({
  observability
}: {
  observability?: {
    enabled: boolean;
    status: "disabled" | "unavailable" | "insufficient_data" | "ok" | "alert";
    window_minutes: number;
    minimum_requests: number;
    request_count: number;
    retry_count: number;
    request_rate_per_minute: number;
    success_rate: number;
    error_rate: number;
    retry_rate: number;
    timeout_rate: number;
    error_rate_alert_threshold: number;
    timeout_rate_alert_threshold: number;
    alerts: Array<"error_rate" | "timeout_rate">;
    last_event_at: string | null;
    dispatcher: {
      status: "disabled" | "not_started" | "ok" | "degraded";
      worker_count: number;
      pending_count: number;
      capacity: number;
      dropped_count: number;
    };
  };
}) {
  // Older API snapshots may not include the optional LLM aggregation block.
  // Keep the settings page usable while the runtime endpoint is upgraded.
  if (!observability) return null;
  const status = statusLabels[observability.status];
  const alerts = observability.alerts.length ? observability.alerts.join("、") : "无";
  const summary =
    observability.status === "disabled"
      ? "当前未启用 LLM 审计。"
      : observability.status === "unavailable"
        ? "最近窗口摘要暂不可用。"
        : "只显示最近窗口的安全聚合指标，不包含事件明细、原始标签、prompt、响应或 URL。";

  return (
    <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">LLM 可观测性摘要</h2>
        <span className={`rounded-md border px-2 py-1 text-xs font-medium ${status.className}`}>{status.label}</span>
      </div>
      <p className="mt-3 text-sm leading-6 text-[var(--text-muted)]">{summary}</p>
      <div className="mt-4 grid gap-3 md:grid-cols-3">
        <MetricTile label="观察窗口" value={`${observability.window_minutes} 分钟`} hint={`最小请求数 ${observability.minimum_requests}`} />
        <MetricTile label="请求数" value={String(observability.request_count)} hint={`每分钟 ${observability.request_rate_per_minute.toFixed(2)} 次`} />
        <MetricTile label="最近事件" value={formatLastEvent(observability.last_event_at)} hint={`重试 ${observability.retry_count} 次`} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-2">
        <MetricTile label="成功率" value={formatRate(observability.success_rate)} hint={`告警阈值 ${formatRate(observability.error_rate_alert_threshold)} / ${formatRate(observability.timeout_rate_alert_threshold)}`} />
        <MetricTile label="错误率 / 超时率" value={`${formatRate(observability.error_rate)} / ${formatRate(observability.timeout_rate)}`} hint={`重试率 ${formatRate(observability.retry_rate)}`} />
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-4">
        <MetricTile label="后台写入" value={dispatcherStatusLabels[observability.dispatcher.status]} hint={`worker ${observability.dispatcher.worker_count}`} />
        <MetricTile label="待写事件" value={String(observability.dispatcher.pending_count)} hint={`容量 ${observability.dispatcher.capacity}`} />
        <MetricTile label="丢弃事件" value={String(observability.dispatcher.dropped_count)} hint="队列满或关闭后累计" />
        <MetricTile label="事件明细" value="不展示" hint="仅保留安全聚合" />
      </div>
      <p className="mt-3 text-xs leading-5 text-[var(--text-muted)]">
        告警：{alerts}；启用状态：{observability.enabled ? "已启用" : "未启用"}。
      </p>
    </section>
  );
}
