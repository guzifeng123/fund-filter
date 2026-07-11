import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it, vi } from "vitest";
import { ErrorState } from "@/components/error-state";

describe("state components", () => {
  it("renders a reusable error state with retry action", () => {
    const html = renderToStaticMarkup(
      <ErrorState title="基金列表加载失败" description="无法获取筛选结果。" onRetry={vi.fn()} />
    );

    expect(html).toContain("基金列表加载失败");
    expect(html).toContain("无法获取筛选结果");
    expect(html).toContain("重试");
  });

  it("renders default error copy without retry", () => {
    const html = renderToStaticMarkup(<ErrorState />);

    expect(html).toContain("数据加载失败");
    expect(html).not.toContain("<button");
  });
});
