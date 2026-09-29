import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sourcePath = join(__dirname, "page.tsx");

describe("ComparePage responsive layout guard", () => {
  it("keeps the comparison table scrollable with a narrower mobile baseline", () => {
    const source = readFileSync(sourcePath, "utf8");

    expect(source).toContain("min-w-[760px]");
    expect(source).toContain("md:min-w-[900px]");
  });

  it("does not call the compare API for fewer than two funds", () => {
    const source = readFileSync(sourcePath, "utf8");

    expect(source).toContain("enabled: codes.length >= 2");
    expect(source).toContain("至少选择 2 只基金");
  });
});
