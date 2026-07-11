import { ApiClientError } from "@/lib/api/client";

const API_ERROR_GUIDANCE: Record<string, string> = {
  VALIDATION_ERROR: "请检查必填项、数值范围和日期格式后重试。",
  INVALID_RISK_ANSWERS: "请确认每一道风险测评题都已作答。",
  INVALID_DATE_RANGE: "开始日期不能晚于结束日期。",
  INVALID_PORTFOLIO_TEMPLATE: "请选择当前列表中的有效组合模板。",
  FUND_NOT_FOUND: "请刷新基金数据或改选仍然可用的基金。",
  PORTFOLIO_NOT_FOUND: "该组合可能已被删除，请刷新组合列表。",
  AI_THREAD_NOT_FOUND: "原对话已不可用，请开始一个新对话。",
  UNKNOWN_DATA_SOURCE: "请在环境配置中选择已支持的数据源。",
  INTERNAL_SERVER_ERROR: "服务端暂时无法完成请求，请稍后重试并查看服务日志。"
};

export function getApiErrorMessage(error: unknown, fallback: string): string {
  if (error instanceof ApiClientError) {
    const guidance = API_ERROR_GUIDANCE[error.code];
    return guidance ? `${error.message} ${guidance}` : error.message;
  }
  if (error instanceof TypeError) {
    return "无法连接 API 服务，请检查服务地址、网络和 CORS 配置。";
  }
  if (error instanceof Error && error.message) {
    return error.message;
  }
  return fallback;
}
