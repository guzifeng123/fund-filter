import { AlertTriangle, RefreshCw } from "lucide-react";
import { Button } from "@/components/button";

export function ErrorState({
  title = "数据加载失败",
  description = "请稍后重试，或检查 API 服务和网络连接。",
  onRetry
}: {
  title?: string;
  description?: string;
  onRetry?: () => void;
}) {
  return (
    <div className="rounded-md border border-[var(--danger)] bg-[var(--surface)] p-4 text-sm">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-[var(--danger)]" />
        <div>
          <div className="font-semibold">{title}</div>
          <div className="mt-1 text-xs leading-5 text-[var(--text-muted)]">{description}</div>
          {onRetry ? (
            <Button
              variant="secondary"
              size="sm"
              className="mt-3 gap-1"
              onClick={onRetry}
            >
              <RefreshCw className="h-3.5 w-3.5" /> 重试
            </Button>
          ) : null}
        </div>
      </div>
    </div>
  );
}
