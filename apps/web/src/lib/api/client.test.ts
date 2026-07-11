import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, apiClient } from "@/lib/api/client";

describe("apiClient errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves a structured API error envelope", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: "FUND_NOT_FOUND", message: "未找到指定基金", detail: null },
      meta: { source: "test", data_updated_at: "", disclaimer: "" }
    }), { status: 404, headers: { "Content-Type": "application/json" } })));

    await expect(apiClient.fundDetail("missing")).rejects.toMatchObject({
      name: "ApiClientError",
      status: 404,
      code: "FUND_NOT_FOUND",
      message: "未找到指定基金"
    });
  });

  it("normalizes a non-JSON gateway failure", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response("Bad gateway", { status: 502 })));

    const error = await apiClient.dataStatus().catch((reason: unknown) => reason);

    expect(error).toBeInstanceOf(ApiClientError);
    expect(error).toMatchObject({
      status: 502,
      code: "HTTP_502",
      message: "API 服务暂时不可用"
    });
  });
});
