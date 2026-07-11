import { describe, expect, it } from "vitest";
import { formatProvenanceDate } from "@/components/data-provenance-footer";

describe("formatProvenanceDate", () => {
  it("formats a valid API timestamp", () => {
    expect(formatProvenanceDate("2026-07-10T10:30:00+08:00")).toContain("2026");
  });

  it("distinguishes missing and invalid timestamps", () => {
    expect(formatProvenanceDate(null)).toBe("暂无数据");
    expect(formatProvenanceDate("not-a-date")).toBe("日期不可用");
  });
});
