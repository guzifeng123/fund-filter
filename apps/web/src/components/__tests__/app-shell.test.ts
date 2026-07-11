import { describe, expect, it } from "vitest";
import { isNavItemActive } from "@/components/app-shell";

describe("AppShell navigation", () => {
  it("marks exact and nested routes as active", () => {
    expect(isNavItemActive("/funds", "/funds")).toBe(true);
    expect(isNavItemActive("/funds/000001", "/funds")).toBe(true);
  });

  it("does not mark sibling routes as active", () => {
    expect(isNavItemActive("/funds-extra", "/funds")).toBe(false);
    expect(isNavItemActive("/compare", "/funds")).toBe(false);
  });
});
