import type { RiskLevel, RiskProfile } from "@/lib/compliance/constants";

export type ApiMeta = {
  source: string;
  data_updated_at: string | null;
  disclaimer: string;
  pagination?: { page: number; page_size: number; total: number } | null;
};

export type ApiResponse<T> = {
  data: T;
  meta: ApiMeta;
};

export type ApiErrorPayload = {
  error: {
    code: string;
    message: string;
    detail: unknown | null;
  };
  meta: ApiMeta;
};

export type DataStatus = {
  db_connected: boolean;
  source: string;
  fund_count: number;
  nav_count: number;
  latest_data_updated_at: string | null;
  freshness_status: "empty" | "fresh" | "stale" | "failed";
  stale_after_days: number;
  last_job: {
    name: string;
    status: "running" | "success" | "failed";
    finished_at: string | null;
    error_detail: string | null;
  } | null;
};

export type JobRunSummary = {
  id: number;
  name: string;
  status: "running" | "success" | "failed";
  started_at: string;
  finished_at: string | null;
  error_detail: string | null;
  details: Record<string, unknown>;
};

export type DashboardFeatureStatus = "available" | "unavailable" | "not_configured";

export type DashboardData = {
  risk_profile: string;
  risk_status: "not_assessed" | "valid" | "expires_soon" | "expired";
  risk_notice: string;
  health: string;
  portfolio_health_status: DashboardFeatureStatus;
  watchlist_updated_at: string | null;
  watchlist_status: DashboardFeatureStatus;
  alerts: string[];
  alerts_status: DashboardFeatureStatus;
  data_status: DataStatus;
  recent_job: JobRunSummary | null;
};

export type RuntimeSettingsData = {
  data_source: {
    configured_source: string;
    configured_profile: string | null;
    actual_source: string;
    configured: boolean;
  };
  llm: {
    provider: string | null;
    model: string | null;
    configured: boolean;
    mock_mode: boolean;
    observability: {
      enabled: boolean;
      status: "disabled" | "unavailable" | "insufficient_data" | "ok" | "alert";
      window_minutes: number;
      minimum_requests: number;
      request_count: number;
      retry_count: number;
      request_rate_per_minute: number;
      success_rate: number;
      error_rate: number;
      retry_rate: number;
      timeout_rate: number;
      error_rate_alert_threshold: number;
      timeout_rate_alert_threshold: number;
      alerts: Array<"error_rate" | "timeout_rate">;
      last_event_at: string | null;
      dispatcher: {
        status: "disabled" | "not_started" | "ok" | "degraded";
        worker_count: number;
        pending_count: number;
        capacity: number;
        dropped_count: number;
      };
    };
  };
  yingmi_mcp: {
    configured: boolean;
    implemented: boolean;
  };
  risk_assessment: {
    validity_months: number;
  };
  cleanup: {
    method: "manual_script";
    dry_run_supported: boolean;
    automatic_cleanup_supported: boolean;
  };
};

export type SchedulerStatus = {
  enabled: boolean;
  running: boolean;
  schedule_mode: "interval" | "cron";
  schedule_expression: string;
  timezone: string;
  jitter_seconds: number;
  misfire_grace_seconds: number;
  next_run_at: string | null;
  running_tasks: JobRunSummary[];
};

export type DataSyncResult = {
  task: "all" | "profiles" | "navs" | "metrics" | "risk_levels";
  result: Record<string, unknown>;
};

export type RiskQuestion = {
  id: string;
  title: string;
  options: Array<{ score: number; label: string }>;
};

export type RiskAnswer = {
  question_id: string;
  score: number;
};

export type RiskAssessmentResult = {
  risk_profile: RiskProfile;
  score: number;
  effective_from: string;
  effective_to: string;
  expires_soon: boolean;
  is_expired: boolean;
  explanation: string;
};

export type Fund = {
  code: string;
  name: string;
  fund_type: "stock" | "mixed" | "bond" | "money";
  risk_level: RiskLevel;
  manager_name: string;
  inception_date: string;
  fund_size_billion: number;
  management_fee: number;
  custody_fee: number;
  annualized_return_3y: number;
  annualized_return_5y: number;
  max_drawdown: number;
  sharpe_ratio: number;
  category_rank_percentile: number;
  manager_years: number;
  source: string;
  data_updated_at: string;
};

export type FundDetail = Fund & {
  navs: Array<{ trade_date: string; nav: number; accumulated_nav: number }>;
  ai_summary: string;
  fee_summary: {
    management_fee: number;
    custody_fee: number;
    total_fee: number;
    explanation: string;
  } | null;
  manager_profile: {
    name: string;
    years: number;
    inception_date: string;
    explanation: string;
  } | null;
  metric_explanations: Array<{
    key: string;
    label: string;
    value: string;
    explanation: string;
  }>;
  risk_match: {
    user_risk_profile: RiskProfile;
    fund_risk_level: RiskLevel;
    matched: boolean;
    message: string;
  } | null;
};

export type FundFilterRequest = {
  keyword?: string;
  risk_profile: RiskProfile;
  fund_types: Fund["fund_type"][];
  min_years: number;
  size_range: [number, number];
  return_rank_percentile: number;
  max_drawdown_lte_category_avg: boolean;
  sharpe_gte: number;
  fee_lte: number;
  sort_by?:
    | "code"
    | "annualized_return_3y"
    | "annualized_return_5y"
    | "max_drawdown"
    | "sharpe_ratio"
    | "fee"
    | "size";
  sort_order?: "asc" | "desc";
};

export type FundSearchParams = {
  q?: string;
  page?: number;
  page_size?: number;
  fund_type?: Fund["fund_type"][];
  risk_level?: RiskLevel[];
  sort_by?: NonNullable<FundFilterRequest["sort_by"]>;
  sort_order?: NonNullable<FundFilterRequest["sort_order"]>;
};

export type PortfolioTemplate = {
  id: "conservative" | "balanced" | "growth";
  name: string;
  stock_ratio: number;
  bond_ratio: number;
  suitable_profiles: ReadonlyArray<RiskProfile>;
};

export type PortfolioSummary = {
  id: string;
  name: string;
  template_key: PortfolioTemplate["id"];
  stock_ratio: number;
  bond_ratio: number;
  position_count: number;
  unavailable_position_count: number;
};

export type PortfolioDetail = PortfolioSummary & {
  positions: Array<{
    fund_code: string;
    fund_name: string;
    fund_type: Fund["fund_type"];
    risk_level: RiskLevel;
    weight_percent: number;
    normalized_weight_percent: number | null;
    available: boolean;
    availability_reason: "available" | "removed_from_active_snapshot";
  }>;
  total_weight_percent: number;
  weight_warning: string | null;
};

export type RebalancePreview = {
  portfolio_id: string | null;
  drift_percent: number;
  message: string;
  current_stock_ratio: number;
  current_bond_ratio: number;
  target_stock_ratio: number;
  target_bond_ratio: number;
  triggered: boolean;
};

export type BacktestResult = {
  id: string;
  strategy_type: "monthly_dca" | "weekly_dca" | "rebalance" | "template_portfolio";
  annualized_return: number;
  max_drawdown: number;
  volatility: number;
  sharpe_ratio: number;
  total_invested: number;
  final_value: number;
  money_weighted_return: number;
  time_weighted_return: number;
  return_calculation_method: "xirr" | "unavailable";
  snapshot_generation_id: string | null;
  data_warning: string | null;
  points: Array<{ date: string; portfolio: number; benchmark: number }>;
};

export type BacktestRequest = {
  strategy_type: BacktestResult["strategy_type"];
  amount: number;
  start: string;
  end: string;
  fund_codes: string[];
  rebalance_threshold?: number;
  template_key?: PortfolioTemplate["id"];
};

export type ChatResponse = {
  thread_id: string | null;
  conclusion: string;
  evidence: string[];
  references: string[];
  risk: string;
  data_date: string;
  disclaimer: string;
  unable_to_answer: boolean;
};
