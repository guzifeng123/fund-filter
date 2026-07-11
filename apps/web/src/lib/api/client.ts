import type {
  ApiErrorPayload,
  ApiResponse,
  BacktestRequest,
  BacktestResult,
  ChatResponse,
  DataStatus,
  DataSyncResult,
  Fund,
  FundDetail,
  FundFilterRequest,
  FundSearchParams,
  JobRunSummary,
  PortfolioDetail,
  PortfolioSummary,
  PortfolioTemplate,
  RebalancePreview,
  RiskAnswer,
  RiskAssessmentResult,
  RiskQuestion
} from "@/lib/api/types";

const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://localhost:8000/api";

export class ApiClientError extends Error {
  code: string;
  detail: unknown | null;
  status: number;

  constructor(status: number, payload: ApiErrorPayload) {
    super(payload.error.message);
    this.name = "ApiClientError";
    this.status = status;
    this.code = payload.error.code;
    this.detail = payload.error.detail;
  }
}

function buildQuery(params: FundSearchParams): string {
  const searchParams = new URLSearchParams();
  if (params.q) {
    searchParams.set("q", params.q);
  }
  for (const key of ["page", "page_size", "sort_by", "sort_order"] as const) {
    const value = params[key];
    if (value !== undefined) {
      searchParams.set(key, String(value));
    }
  }
  for (const fundType of params.fund_type ?? []) {
    searchParams.append("fund_type", fundType);
  }
  for (const riskLevel of params.risk_level ?? []) {
    searchParams.append("risk_level", riskLevel);
  }
  const query = searchParams.toString();
  return query ? `?${query}` : "";
}

async function parseApiError(response: Response): Promise<ApiClientError> {
  try {
    const payload = (await response.json()) as ApiErrorPayload;
    if (payload?.error?.code && payload.error.message) {
      return new ApiClientError(response.status, payload);
    }
  } catch {
    // Proxies and gateways may return HTML or an empty body.
  }

  return new ApiClientError(response.status, {
    error: {
      code: `HTTP_${response.status}`,
      message: response.status >= 500 ? "API 服务暂时不可用" : "API 请求未成功",
      detail: null
    },
    meta: {
      source: "api",
      data_updated_at: "",
      disclaimer: ""
    }
  });
}

async function request<T>(path: string, init?: RequestInit): Promise<ApiResponse<T>> {
  const response = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...init?.headers
    }
  });

  if (!response.ok) {
    throw await parseApiError(response);
  }

  return response.json() as Promise<ApiResponse<T>>;
}

export const apiClient = {
  dashboard: () =>
    request<{
      risk_profile: string;
      health: string;
      watchlist_updated_at: string;
      alerts: string[];
    }>("/dashboard"),
  dataStatus: () => request<DataStatus>("/data/status"),
  recentDataJobs: (limit = 10) => request<JobRunSummary[]>(`/data/jobs/recent?limit=${limit}`),
  syncData: (task: DataSyncResult["task"] = "all") =>
    request<DataSyncResult>(`/data/sync?task=${task}`, { method: "POST" }),
  riskQuestions: () => request<RiskQuestion[]>("/risk-assessments/questions"),
  latestRiskAssessment: () => request<RiskAssessmentResult | null>("/risk-assessments/latest"),
  submitRiskAssessment: (answers: RiskAnswer[]) =>
    request<RiskAssessmentResult>("/risk-assessments", {
      method: "POST",
      body: JSON.stringify({ answers })
    }),
  searchFunds: (query: string, params: Omit<FundSearchParams, "q"> = {}) =>
    request<Fund[]>(`/funds/search${buildQuery({ ...params, q: query })}`),
  filterFunds: (payload: FundFilterRequest) =>
    request<Fund[]>("/funds/filter", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  fundDetail: (code: string, riskProfile = "C3") =>
    request<FundDetail>(`/funds/${code}?risk_profile=${riskProfile}`),
  compareFunds: (codes: string[]) =>
    request<Fund[]>("/funds/compare", {
      method: "POST",
      body: JSON.stringify({ codes })
    }),
  portfolioTemplates: () => request<PortfolioTemplate[]>("/portfolios/templates"),
  portfolios: () => request<PortfolioSummary[]>("/portfolios"),
  createPortfolio: (payload: { name: string; template_key: PortfolioTemplate["id"] }) =>
    request<PortfolioDetail>("/portfolios", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  updatePortfolio: (portfolioId: string, payload: { name: string }) =>
    request<PortfolioDetail>(`/portfolios/${portfolioId}`, {
      method: "PATCH",
      body: JSON.stringify(payload)
    }),
  portfolioDetail: (portfolioId: string) => request<PortfolioDetail>(`/portfolios/${portfolioId}`),
  savePortfolioPosition: (portfolioId: string, payload: { fund_code: string; weight_percent: number }) =>
    request<PortfolioDetail>(`/portfolios/${portfolioId}/positions`, {
      method: "PUT",
      body: JSON.stringify(payload)
    }),
  removePortfolioPosition: (portfolioId: string, fundCode: string) =>
    request<PortfolioDetail>(`/portfolios/${portfolioId}/positions/${fundCode}`, { method: "DELETE" }),
  rebalancePreview: (portfolioId: string) =>
    request<RebalancePreview>(`/portfolios/${portfolioId}/rebalance-preview`, { method: "POST" }),
  runBacktest: (payload: BacktestRequest) =>
    request<BacktestResult>("/backtests", {
      method: "POST",
      body: JSON.stringify(payload)
    }),
  askAssistant: (message: string) =>
    request<ChatResponse>("/ai/chat", {
      method: "POST",
      body: JSON.stringify({ message, context: { page: "assistant" } })
    }),
  askAssistantWithContext: (message: string, context: Record<string, unknown>) =>
    request<ChatResponse>("/ai/chat", {
      method: "POST",
      body: JSON.stringify({ message, context })
    }),
  streamAssistantWithContext: async (
    message: string,
    context: Record<string, unknown>,
    onChunk: (chunk: string) => void,
    threadId?: string | null
  ) => {
    const response = await fetch(`${API_BASE}/ai/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ message, context, thread_id: threadId })
    });
    if (!response.ok) {
      throw await parseApiError(response);
    }
    const reader = response.body?.getReader();
    const decoder = new TextDecoder();
    let buffer = "";
    let finalResponse: ChatResponse | null = null;
    while (reader) {
      const { value, done } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const events = buffer.split("\n\n");
      buffer = events.pop() ?? "";
      for (const event of events) {
        const line = event.split("\n").find((item) => item.startsWith("data: "));
        if (!line) continue;
        const payload = JSON.parse(line.slice(6)) as { chunk?: string; done?: boolean; response?: ChatResponse };
        if (payload.chunk) onChunk(payload.chunk);
        if (payload.done && payload.response) finalResponse = payload.response;
      }
    }
    if (!finalResponse) {
      throw new Error("AI 流式响应未返回完整结果");
    }
    return finalResponse;
  }
};
