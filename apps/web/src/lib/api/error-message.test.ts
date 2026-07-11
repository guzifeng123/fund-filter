import { describe, expect, it } from "vitest";
import { ApiClientError } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { ApiErrorPayload } from "@/lib/api/types";

function apiError(code: string, message: string) {
  const payload: ApiErrorPayload = {
    error: { code, message, detail: null },
    meta: {
      source: "test",
      data_updated_at: "2026-07-10T00:00:00Z",
      disclaimer: "test"
    }
  };
  return new ApiClientError(400, payload);
}

describe("getApiErrorMessage", () => {
  it("adds recovery guidance for a known API error code", () => {
    expect(getApiErrorMessage(apiError("INVALID_DATE_RANGE", "日期范围无效"), "fallback"))
      .toBe("日期范围无效 开始日期不能晚于结束日期。");
  });

  it("preserves the server message for an unknown API error code", () => {
    expect(getApiErrorMessage(apiError("CUSTOM_ERROR", "自定义错误"), "fallback"))
      .toBe("自定义错误");
  });

  it("maps fetch failures to connection guidance", () => {
    expect(getApiErrorMessage(new TypeError("Failed to fetch"), "fallback"))
      .toContain("CORS");
  });

  it("uses the fallback for non-error values", () => {
    expect(getApiErrorMessage(null, "请稍后重试"))
      .toBe("请稍后重试");
  });
});
