import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { FundNavSummary } from "@/features/funds/fund-detail-panel";

describe("FundNavSummary", () => {
  it("renders the latest nav point", () => {
    const html = renderToStaticMarkup(
      <FundNavSummary
        navs={[
          { trade_date: "2025-12-31", nav: 1.1234, accumulated_nav: 1.2234 },
          { trade_date: "2026-07-09", nav: 1.2345, accumulated_nav: 1.4567 }
        ]}
      />
    );

    expect(html).toContain("净值摘要");
    expect(html).toContain("2026-07-09");
    expect(html).toContain("1.2345");
    expect(html).toContain("1.4567");
  });

  it("renders an empty nav state", () => {
    const html = renderToStaticMarkup(<FundNavSummary navs={[]} />);

    expect(html).toContain("暂无可展示的净值点");
  });
});
