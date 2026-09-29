import { readFileSync } from "node:fs";
import path from "node:path";
import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { RuntimeSettingsCards } from "@/app/settings/page";
import type { RuntimeSettingsData } from "@/lib/api/types";

const runtime: RuntimeSettingsData = {
  data_source: {
    configured_source: "public_http_json",
    configured_profile: "generic_aliases_v1",
    actual_source: "sample_local",
    configured: true
  },
  llm: {
    provider: "openai-compatible",
    model: "gpt-safe-model",
    configured: true,
    mock_mode: false,
    observability: {
      enabled: true,
      status: "alert",
      window_minutes: 60,
      minimum_requests: 10,
      request_count: 18,
      retry_count: 4,
      request_rate_per_minute: 0.3,
      success_rate: 0.72,
      error_rate: 0.22,
      retry_rate: 0.16,
      timeout_rate: 0.11,
      error_rate_alert_threshold: 0.2,
      timeout_rate_alert_threshold: 0.1,
      alerts: ["error_rate", "timeout_rate"],
      last_event_at: "2026-07-14T08:30:00+00:00",
      dispatcher: {
        status: "degraded",
        worker_count: 1,
        pending_count: 2,
        capacity: 256,
        dropped_count: 3
      }
    }
  },
  yingmi_mcp: {
    configured: true,
    implemented: false
  },
  risk_assessment: {
    validity_months: 12
  },
  cleanup: {
    method: "manual_script",
    dry_run_supported: true,
    automatic_cleanup_supported: false
  }
};

describe("RuntimeSettingsCards", () => {
  it("renders concrete safe runtime states and actionable maintenance guidance", () => {
    const html = renderToStaticMarkup(<RuntimeSettingsCards runtime={runtime} />);

    expect(html).toContain("盈米 MCP 配置");
    expect(html).toContain("未实现");
    expect(html).toContain("端点状态：已配置");
    expect(html).toContain("Provider：openai-compatible");
    expect(html).toContain("模型：gpt-safe-model");
    expect(html).toContain("当前有效期为 12 个月");
    expect(html).toContain("手动维护");
    expect(html).toContain("自动清理：不支持");
    expect(html).toContain("clean-generated.ps1 -WhatIf");
    expect(html).toContain("不会返回 API key 或服务端点");
    expect(html).toContain("LLM 可观测性摘要");
    expect(html).toContain("只显示最近窗口的安全聚合指标");
    expect(html).toContain("18");
    expect(html).toContain("0.30");
    expect(html).toContain("72.0%");
    expect(html).toContain("告警：error_rate、timeout_rate");
    expect(html).toContain("后台写入");
    expect(html).toContain("降级");
    expect(html).toContain("容量 256");
    expect(html).toContain("丢弃事件");
    expect(html).toContain("事件明细");
    expect(html).toContain("不展示");
  });

  it("labels an incomplete external LLM configuration as not configured", () => {
    const html = renderToStaticMarkup(
      <RuntimeSettingsCards runtime={{ ...runtime, llm: { ...runtime.llm, configured: false } }} />
    );

    expect(html).toContain("未配置");
    expect(html).toContain("补齐 provider、model、API key 与兼容服务地址");
  });

  it("loads the read-only runtime endpoint instead of rendering repeated placeholders", () => {
    const source = readFileSync(path.join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain("apiClient.runtimeSettings");
    expect(source).toContain("<RuntimeSettingsCards runtime={runtime} />");
    expect(source).not.toContain("个人部署默认本地保存配置，敏感字段不进入向量库。");
  });

  it("exposes a one-click full data pull with pending and success feedback", () => {
    const source = readFileSync(path.join(__dirname, "page.tsx"), "utf8");

    expect(source).toContain('{ value: "all", label: "一键拉取全部数据" }');
    expect(source).toContain('apiClient.syncData(task)');
    expect(source).toContain('task.value === "all" ? "primary" : "secondary"');
    expect(source).toContain('"拉取中..."');
    expect(source).toContain("数据拉取完成，基金列表与数据状态已刷新。");
  });
});
