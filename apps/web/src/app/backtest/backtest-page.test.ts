import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

describe("backtest page compliance", () => {
  it("keeps the historical-performance disclaimer visible through the default notice", () => {
    const source = readFileSync(path.join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("<ComplianceNotice />");
    expect(source).not.toContain("历史表现不预示未来收益");
  });

  it("provides an AI explanation entry that references the persisted backtest id", () => {
    const source = readFileSync(path.join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("askAssistantWithContext");
    expect(source).toContain('backtest_id: backtestId');
    expect(source).toContain("解释本次回测");
  });
});
