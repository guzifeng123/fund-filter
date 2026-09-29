import { NextResponse } from "next/server";

// Keep optional settings UI queries non-fatal when only the web server is
// running. The real API remains the authoritative source in normal use.
export function GET() {
  return NextResponse.json({
    data: {
      app_environment: "development",
      fund_data_source: "sample_local",
      configured_source: "sample_local",
      source_status: "unavailable",
      public_fund_data_base_url_configured: false,
      scheduler: {
        enabled: false,
        running: false,
        schedule_mode: "interval",
        schedule_expression: null,
        timezone: "Asia/Shanghai",
        jitter_seconds: 0,
        misfire_grace_seconds: 0,
        next_run_at: null,
        running_tasks: []
      },
      llm: {
        provider_configured: false,
        observability: null
      }
    },
    meta: {
      source: "web-fallback",
      data_updated_at: null,
      disclaimer: "仅用于本地页面降级显示。"
    }
  });
}
