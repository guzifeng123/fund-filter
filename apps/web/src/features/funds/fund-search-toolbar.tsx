"use client";

import { ArrowUpDown, Search } from "lucide-react";
import { Button } from "@/components/button";
import { Input } from "@/components/form-field";

export function FundSearchToolbar({
  keyword,
  onKeywordChange,
  sortOptions,
  activeSortIndex,
  onSortChange
}: {
  keyword: string;
  onKeywordChange: (keyword: string) => void;
  sortOptions: ReadonlyArray<{ label: string }>;
  activeSortIndex: number;
  onSortChange: (index: number) => void;
}) {
  return (
    <div className="grid gap-2 xl:grid-cols-[minmax(12rem,1fr)_auto]">
      <label className="flex h-10 items-center gap-2 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 focus-within:border-[var(--accent)]">
        <span className="sr-only">按基金名称或代码搜索</span>
        <Search className="h-4 w-4 text-[var(--text-muted)]" />
        <Input
          variant="unstyled"
          className="w-full bg-transparent text-sm outline-none"
          value={keyword}
          onChange={(event) => onKeywordChange(event.currentTarget.value)}
          placeholder="按名称或代码服务端搜索"
        />
      </label>
      <div className="flex min-h-10 flex-wrap items-center gap-1 rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1" aria-label="基金排序">
        <ArrowUpDown className="h-4 w-4 text-[var(--text-muted)]" />
        {sortOptions.map((option, index) => (
          <Button
            key={option.label}
            variant="unstyled"
            size="none"
            aria-pressed={activeSortIndex === index}
            className={`h-7 rounded-md px-2 text-xs ${activeSortIndex === index ? "bg-[var(--accent)] text-white" : "text-[var(--text-muted)] hover:bg-[var(--surface-muted)]"}`}
            onClick={() => onSortChange(index)}
          >
            {option.label}
          </Button>
        ))}
      </div>
    </div>
  );
}
