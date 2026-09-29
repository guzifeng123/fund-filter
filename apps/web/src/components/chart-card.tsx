"use client";

import dynamic from "next/dynamic";
import type { EChartsOption } from "echarts";
import { ClockAlert } from "lucide-react";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { DEFAULT_DATA_SOURCE } from "@/lib/compliance/constants";

const ReactECharts = dynamic(() => import("echarts-for-react"), {
  ssr: false,
  loading: () => <LoadingBlock label="图表加载中" />
});

type ChartCardBaseProps = {
  title: string;
  source?: string;
};

type ChartCardReadyProps = ChartCardBaseProps & {
  status?: "ready" | "stale";
  option: EChartsOption;
  staleMessage?: string;
};

type ChartCardLoadingProps = ChartCardBaseProps & {
  status: "loading";
  option?: never;
};

type ChartCardEmptyProps = ChartCardBaseProps & {
  status: "empty";
  option?: never;
  emptyTitle?: string;
  emptyDescription?: string;
};

type ChartCardErrorProps = ChartCardBaseProps & {
  status: "error";
  option?: never;
  errorTitle?: string;
  errorDescription?: string;
  onRetry?: () => void;
};

export type ChartCardProps =
  | ChartCardReadyProps
  | ChartCardLoadingProps
  | ChartCardEmptyProps
  | ChartCardErrorProps;

export function ChartCard(props: ChartCardProps) {
  const { title, source = DEFAULT_DATA_SOURCE } = props;

  return (
    <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3" aria-label={title}>
      <div className="mb-2 flex items-center justify-between">
        <h2 className="text-sm font-semibold">{title}</h2>
        <span className="text-xs text-[var(--text-muted)]">{source}</span>
      </div>
      {props.status === "loading" ? (
        <LoadingBlock label={`${title}加载中`} />
      ) : props.status === "empty" ? (
        <EmptyState
          title={props.emptyTitle ?? "暂无可绘制数据"}
          description={props.emptyDescription ?? "完成数据同步或配置后再查看图表。"}
        />
      ) : props.status === "error" ? (
        <ErrorState
          title={props.errorTitle ?? `${title}加载失败`}
          description={props.errorDescription ?? "图表数据不可用，请检查数据状态后重试。"}
          onRetry={props.onRetry}
        />
      ) : (
        <>
          {props.status === "stale" ? (
            <div className="mb-3 flex gap-2 rounded-md border border-[var(--r4)] p-3 text-xs leading-5 text-[var(--text-muted)]" role="status">
              <ClockAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--r4)]" />
              {props.staleMessage ?? "图表使用的数据已超过新鲜度阈值，请先确认最近同步状态。"}
            </div>
          ) : null}
          <ReactECharts option={props.option} style={{ height: 280, width: "100%" }} notMerge />
        </>
      )}
    </section>
  );
}
