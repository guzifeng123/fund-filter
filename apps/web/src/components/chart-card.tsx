"use client";

import dynamic from "next/dynamic";
import type { EChartsOption } from "echarts";
import { LoadingBlock } from "@/components/loading-block";
import { DEFAULT_DATA_SOURCE } from "@/lib/compliance/constants";

const ReactECharts = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => <LoadingBlock label="图表加载中" />
});

export function ChartCard({
  title,
  option,
  source = DEFAULT_DATA_SOURCE
}: {
  title: string;
  option: EChartsOption;
  source?: string;
}) {
  return (
    <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-[var(--text-muted)]">{source}</span>
      </div>
      <ReactECharts option={option} style={{ height: 280, width: "100%" }} notMerge />
    </div>
  );
}
