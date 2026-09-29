import { NextResponse } from "next/server";

// Local-only fallback used when the web app is run without the API service
// (for example, mocked Playwright flows). Production deployments point
// NEXT_PUBLIC_API_BASE at the FastAPI service, so this route is not used.
export function GET() {
  return NextResponse.json({
    data: {
      db_connected: false,
      source: "web-fallback",
      fund_count: 0,
      nav_count: 0,
      latest_data_updated_at: null,
      freshness_status: "unknown",
      stale_after_days: 7,
      last_job: null
    },
    meta: {
      source: "web-fallback",
      data_updated_at: null,
      disclaimer: "仅用于本地页面降级显示。"
    }
  });
}
