import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const sourcePath = join(__dirname, "funds-page.tsx");

describe("FundsPage responsive layout guard", () => {
  it("keeps the sort controls wrap-friendly on narrow screens", () => {
    const source = readFileSync(sourcePath, "utf8");

    expect(source).toContain("min-h-10 flex-wrap");
    expect(source).not.toContain("flex h-10 items-center gap-1 rounded-md border");
  });
});
