import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { PageHeader } from "@/components/page-header";

describe("PageHeader", () => {
  it("allows header actions to wrap on narrow screens", () => {
    const html = renderToStaticMarkup(
      <PageHeader
        title="基金筛选"
        actions={(
          <>
            <span>已选比较 5/5</span>
            <a href="/compare">进入比较</a>
          </>
        )}
      />
    );

    expect(html).toContain("flex-wrap");
  });
});
