import { Info } from "lucide-react";
import { Button } from "@/components/button";
import { ANALYSIS_METRIC_COPY, type AnalysisMetricKey } from "@/lib/funds/metric-copy";

export function MetricLabel({
  metricKey,
  align = "left"
}: {
  metricKey: AnalysisMetricKey;
  align?: "left" | "right";
}) {
  const metric = ANALYSIS_METRIC_COPY[metricKey];

  return (
    <span className={`group relative inline-flex items-center gap-1 ${align === "right" ? "justify-end" : ""}`}>
      {metric.label}
      <Button
        variant="unstyled"
        size="none"
        className="inline-flex h-5 w-5 items-center justify-center rounded-md text-[var(--text-muted)]"
        aria-label={`${metric.label}说明：${metric.explanation}`}
      >
        <Info aria-hidden="true" className="h-3.5 w-3.5" />
      </Button>
      <span className="pointer-events-none absolute top-6 z-10 hidden w-56 rounded-md border border-[var(--border)] bg-[var(--surface)] p-2 text-left text-xs leading-5 text-[var(--text)] shadow-sm group-focus-within:block group-hover:block">
        {metric.explanation}
      </span>
    </span>
  );
}
