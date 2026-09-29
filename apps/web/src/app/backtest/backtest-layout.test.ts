import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sourcePath = join(__dirname, "page.tsx");

describe("BacktestPage responsive layout guard", () => {
  it("keeps date inputs single-column on narrow screens", () => {
    const source = readFileSync(sourcePath, "utf8");

    expect(source).toContain("grid min-w-0 gap-2 sm:grid-cols-2");
    expect(source).toContain("h-9 w-full min-w-0");
    expect(source).not.toContain("grid grid-cols-2 gap-2");
  });
});
