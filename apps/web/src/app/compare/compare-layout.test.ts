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
});
