import { Database } from "lucide-react";

export function DataFreshnessBadge({ source, updatedAt }: { source: string; updatedAt: string }) {
  return (
    <span className="inline-flex h-7 items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 text-xs text-[var(--text-muted)]">
      <Database className="h-3.5 w-3.5" />
      {source} · {new Date(updatedAt).toLocaleString("zh-CN", { hour12: false })}
    </span>
  );
}
