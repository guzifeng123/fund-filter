import { AlertTriangle, Database } from "lucide-react";
import type { DataStatus } from "@/lib/api/types";

export function DataStatusNotice({ status }: { status: DataStatus | null | undefined }) {
  if (!status || status.freshness_status === "fresh") {
    return null;
  }

  const content = {
    empty: {
      title: "数据源暂无可用数据",
      description: "请先在设置页运行数据同步，再进行筛选、组合或回测。"
    },
    stale: {
      title: "数据已超过新鲜度阈值",
      description: status.last_job?.status === "success"
        ? `最近一次同步已成功完成${status.last_job.finished_at ? `（${status.last_job.finished_at.replace("T", " ").slice(0, 16)}）` : ""}，但上游最新数据仍停留在 ${status.latest_data_updated_at?.slice(0, 10) ?? "未知日期"}，已超过 ${status.stale_after_days} 天。请检查数据源是否仍提供旧快照。`
        : `最近数据已超过 ${status.stale_after_days} 天，请同步后再用于分析。`
    },
    failed: {
      title: "最近一次数据同步失败",
      description: status.last_job?.error_detail ?? "旧数据仍可读取，请在设置页检查任务详情后重试。"
    }
  }[status.freshness_status];

  const Icon = status.freshness_status === "empty" ? Database : AlertTriangle;
  const borderColor = status.freshness_status === "failed" ? "border-[var(--danger)]" : "border-[var(--r3)]";

  return (
    <div className={`rounded-md border ${borderColor} bg-[var(--surface)] p-4 text-sm`} role="status">
      <div className="flex items-start gap-2">
        <Icon className="mt-0.5 h-4 w-4 shrink-0 text-[var(--r3)]" />
        <div>
          <div className="font-semibold">{content.title}</div>
          <div className="mt-1 text-xs leading-5 text-[var(--text-muted)]">{content.description}</div>
        </div>
      </div>
    </div>
  );
}
