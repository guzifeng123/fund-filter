import { ClockAlert } from "lucide-react";

const MS_PER_DAY = 24 * 60 * 60 * 1000;

export function isDataStale(updatedAt: string | null | undefined, staleAfterDays = 7, now = new Date()) {
  if (!updatedAt) return false;
  const updatedAtDate = new Date(updatedAt ?? "");
  if (Number.isNaN(updatedAtDate.getTime())) return false;
  return now.getTime() - updatedAtDate.getTime() > staleAfterDays * MS_PER_DAY;
}

export function StaleDataNotice({
  updatedAt,
  staleAfterDays = 7,
  className = ""
}: {
  updatedAt: string | null | undefined;
  staleAfterDays?: number;
  className?: string;
}) {
  if (updatedAt === undefined) {
    return null;
  }
  if (updatedAt === null || !updatedAt.trim() || Number.isNaN(new Date(updatedAt).getTime())) {
    return (
      <div className={`flex gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] p-3 text-xs leading-5 text-[var(--text-muted)] ${className}`} role="status">
        <ClockAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--r3)]" />
        <div>数据更新时间未知。请先确认数据源状态和最近同步记录，再将结果用于分析。</div>
      </div>
    );
  }
  if (!isDataStale(updatedAt, staleAfterDays)) {
    return null;
  }
  const updatedAtDate = new Date(updatedAt ?? "");

  return (
    <div className={`flex gap-2 rounded-md border border-[var(--r4)] bg-[var(--surface)] p-3 text-xs leading-5 text-[var(--text-muted)] ${className}`} role="status">
      <ClockAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--r4)]" />
      <div>
        数据更新时间为 {updatedAtDate.toLocaleString("zh-CN", { hour12: false })}，已超过 {staleAfterDays} 天。请先同步或确认数据源状态后再用于分析。
      </div>
    </div>
  );
}
