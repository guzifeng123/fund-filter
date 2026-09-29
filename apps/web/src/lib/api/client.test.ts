import { afterEach, describe, expect, it, vi } from "vitest";
import { ApiClientError, apiClient } from "@/lib/api/client";

describe("apiClient errors", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves a structured API error envelope", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(JSON.stringify({
      error: { code: "FUND_NOT_FOUND", message: "未找到指定基金", detail: null },
      meta: { source: "test", data_updated_at: null, disclaimer: "" }
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

describe("apiClient AI stream", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("preserves the final SSE provenance meta with the structured response", async () => {
    const chatResponse = {
      thread_id: "thread-1",
      conclusion: "历史指标解释",
      evidence: ["最大回撤 -8%"],
      references: ["funds:000001"],
      risk: "历史数据有局限",
      data_date: "2026-07-13",
      disclaimer: "仅供分析学习",
      unable_to_answer: false
    };
    const meta = {
      source: "eastmoney_snapshot",
      data_updated_at: "2026-07-13T08:00:00Z",
      disclaimer: "统一免责声明",
      pagination: null
    };
    const sse = [
      `data: ${JSON.stringify({ chunk: "历史指标解释" })}`,
      `data: ${JSON.stringify({ done: true, response: chatResponse, meta })}`,
      ""
    ].join("\n\n");
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(new Response(sse, {
      status: 200,
      headers: { "Content-Type": "text/event-stream" }
    })));
    const chunks: string[] = [];

    const result = await apiClient.streamAssistantWithContext("解释", {}, (chunk) => chunks.push(chunk));

    expect(chunks).toEqual(["历史指标解释"]);
    expect(result).toEqual({ data: chatResponse, meta });
  });
});

describe("apiClient fund search", () => {
  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("sends a trimmed q through GET search without adding a risk cap", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: [],
      meta: { source: "test", data_updated_at: "2026-07-13T00:00:00Z", disclaimer: "test" }
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);

    await apiClient.searchFunds("  R4 成长  ", {
      page: 1,
      page_size: 100,
      fund_type: ["stock", "mixed"],
      sort_by: "annualized_return_3y",
      sort_order: "desc"
    });

    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    const parsedUrl = new URL(requestUrl);
    expect(parsedUrl.pathname).toBe("/api/funds/search");
    expect(parsedUrl.searchParams.get("q")).toBe("R4 成长");
    expect(parsedUrl.searchParams.getAll("fund_type")).toEqual(["stock", "mixed"]);
    expect(parsedUrl.searchParams.has("risk_level")).toBe(false);
    expect(requestInit.method).toBeUndefined();
  });

  it("posts keyword together with risk, all filter criteria, and sorting", async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify({
      data: [],
      meta: { source: "test", data_updated_at: "2026-07-13T00:00:00Z", disclaimer: "test" }
    }), { status: 200, headers: { "Content-Type": "application/json" } }));
    vi.stubGlobal("fetch", fetchMock);
    const payload = {
      keyword: "000001 稳健",
      risk_profile: "C4" as const,
      fund_types: ["mixed", "bond"] as const,
      min_years: 5,
      size_range: [20, 80] as [number, number],
      return_rank_percentile: 25,
      max_drawdown_lte_category_avg: false,
      sharpe_gte: 1.5,
      fee_lte: 1.2,
      sort_by: "fee" as const,
      sort_order: "asc" as const
    };

    await apiClient.filterFunds({ ...payload, fund_types: [...payload.fund_types] });

    const [requestUrl, requestInit] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(new URL(requestUrl).pathname).toBe("/api/funds/filter");
    expect(requestInit.method).toBe("POST");
    expect(JSON.parse(String(requestInit.body))).toEqual({ ...payload, fund_types: [...payload.fund_types] });
  });
});
