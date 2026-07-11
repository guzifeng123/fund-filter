"use client";

import { useQuery } from "@tanstack/react-query";
import { Clock3, Database } from "lucide-react";
import { apiClient } from "@/lib/api/client";
import { DEFAULT_DATA_SOURCE } from "@/lib/compliance/constants";

export function formatProvenanceDate(value: string | null | undefined): string {
  if (!value) return "暂无数据";
  const parsed = new Date(value);
  if (Number.isNaN(parsed.getTime())) return "日期不可用";
  return parsed.toLocaleString("zh-CN", { hour12: false });
}

export function DataProvenanceFooter() {
  const query = useQuery({
    queryKey: ["data-status"],
    queryFn: apiClient.dataStatus,
    staleTime: 60_000
  });
  const response = query.data;
  const source = response?.meta.source ?? DEFAULT_DATA_SOURCE;
  const updatedAt = response?.data.latest_data_updated_at;

  return (
    <footer className="border-t border-[var(--border)] text-xs text-[var(--text-muted)]">
      <div className="mx-auto flex w-full max-w-[1500px] flex-col gap-2 px-4 py-4 sm:flex-row sm:items-center sm:gap-5 lg:px-6">
        <span className="inline-flex items-center gap-1.5">
          <Database className="h-3.5 w-3.5" /> 数据来源：{source}
        </span>
        <span className="inline-flex items-center gap-1.5">
          <Clock3 className="h-3.5 w-3.5" /> 数据更新时间：{query.isError ? "状态不可用" : formatProvenanceDate(updatedAt)}
        </span>
      </div>
    </footer>
  );
}
