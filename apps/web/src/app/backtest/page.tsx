"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery } from "@tanstack/react-query";
import { Bot, Play } from "lucide-react";
import { ChartCard } from "@/components/chart-card";
import { ComplianceNotice } from "@/components/compliance-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetricTile } from "@/components/metric-tile";
import { PageHeader } from "@/components/page-header";
import { StaleDataNotice } from "@/components/stale-data-notice";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { BacktestRequest, BacktestResult, PortfolioTemplate } from "@/lib/api/types";

const strategyLabels: Record<BacktestResult["strategy_type"], string> = {
  monthly_dca: "每月定投",
  weekly_dca: "每周定投",
  rebalance: "固定比例再平衡",
  template_portfolio: "组合模板回测"
};

export default function BacktestPage() {
  const fundsQuery = useQuery({ queryKey: ["backtest-funds"], queryFn: () => apiClient.searchFunds("", { page_size: 20 }) });
  const templatesQuery = useQuery({ queryKey: ["backtest-portfolio-templates"], queryFn: apiClient.portfolioTemplates });
  const funds = useMemo(() => fundsQuery.data?.data ?? [], [fundsQuery.data?.data]);
  const templates = useMemo(() => templatesQuery.data?.data ?? [], [templatesQuery.data?.data]);
  const [strategyType, setStrategyType] = useState<BacktestResult["strategy_type"]>("monthly_dca");
  const [templateKey, setTemplateKey] = useState<PortfolioTemplate["id"]>("balanced");
  const [amount, setAmount] = useState(1000);
  const [start, setStart] = useState("2021");
  const [end, setEnd] = useState("2026");
  const [rebalanceThreshold, setRebalanceThreshold] = useState(5);
  const [selectedCodes, setSelectedCodes] = useState<string[]>(["000001", "000002"]);

  const mutation = useMutation({
    mutationFn: (payload: BacktestRequest) => apiClient.runBacktest(payload)
  });
  const explainMutation = useMutation({
    mutationFn: (backtestId: string) =>
      apiClient.askAssistantWithContext("解释这次回测结果", { page: "backtest", backtest_id: backtestId })
  });
  const result = mutation.data?.data;

  function toggleFund(code: string) {
    setSelectedCodes((current) => {
      if (current.includes(code)) {
        return current.filter((item) => item !== code);
      }
      return current.length >= 5 ? current : [...current, code];
    });
  }

  return (
    <>
      <PageHeader title="回测学习" description="用历史净值理解定投和再平衡，不预测未来收益或买卖点。" />
      {fundsQuery.isError || templatesQuery.isError ? (
        <ErrorState
          title="回测参数加载失败"
          description="无法读取基金或组合模板，回测不会提交。"
          onRetry={() => {
            void fundsQuery.refetch();
            void templatesQuery.refetch();
          }}
        />
      ) : <div className="grid gap-4 xl:grid-cols-[340px_minmax(0,1fr)]">
        <aside className="grid h-fit gap-3 rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
          <h2 className="text-sm font-semibold">策略参数</h2>
          <label className="grid gap-1 text-xs text-[var(--text-muted)]">
            策略
            <select className="h-9 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-sm text-[var(--text)] outline-none" value={strategyType} onChange={(event) => setStrategyType(event.target.value as BacktestResult["strategy_type"])}>
              {Object.entries(strategyLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
            </select>
          </label>
          {strategyType === "template_portfolio" ? (
            <label className="grid gap-1 text-xs text-[var(--text-muted)]">
              组合模板
              <select className="h-9 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-sm text-[var(--text)] outline-none" value={templateKey} onChange={(event) => setTemplateKey(event.target.value as PortfolioTemplate["id"])}>
                {templates.map((template) => <option key={template.id} value={template.id}>{template.name} · {template.stock_ratio}/{template.bond_ratio}</option>)}
              </select>
            </label>
          ) : null}
          <label className="grid gap-1 text-xs text-[var(--text-muted)]">
            每期金额
            <input className="h-9 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-sm text-[var(--text)] outline-none" type="number" value={amount} min={1} onChange={(event) => setAmount(Number(event.target.value))} />
          </label>
          <div className="grid gap-2 sm:grid-cols-2">
            <label className="grid gap-1 text-xs text-[var(--text-muted)]">
              开始
              <input className="h-9 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-sm text-[var(--text)] outline-none" value={start} onChange={(event) => setStart(event.target.value)} />
            </label>
            <label className="grid gap-1 text-xs text-[var(--text-muted)]">
              结束
              <input className="h-9 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-sm text-[var(--text)] outline-none" value={end} onChange={(event) => setEnd(event.target.value)} />
            </label>
          </div>
          <label className="grid gap-1 text-xs text-[var(--text-muted)]">
            再平衡阈值
            <input className="h-9 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-sm text-[var(--text)] outline-none" type="number" value={rebalanceThreshold} min={0} max={100} onChange={(event) => setRebalanceThreshold(Number(event.target.value))} />
          </label>
          <div className="grid gap-2">
            <div className="text-xs text-[var(--text-muted)]">标的基金 {selectedCodes.length}/5</div>
            {fundsQuery.isLoading ? <LoadingBlock /> : funds.length ? funds.map((fund) => (
              <button key={fund.code} className={`focus-ring rounded-md border px-3 py-2 text-left text-sm ${selectedCodes.includes(fund.code) ? "border-[var(--accent)] bg-[var(--accent-weak)]" : "border-[var(--border)] bg-[var(--background)]"}`} onClick={() => toggleFund(fund.code)}>
                <span className="font-medium">{fund.name}</span>
                <span className="mt-1 block text-xs text-[var(--text-muted)]">{fund.code} · {fund.fund_type}</span>
              </button>
            )) : <EmptyState title="暂无可回测基金" description="请先同步基金资料和净值数据。" />}
          </div>
          <button
            className="focus-ring inline-flex h-10 items-center gap-2 rounded-md bg-[var(--accent)] px-4 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50"
            disabled={!selectedCodes.length || mutation.isPending}
            onClick={() => mutation.mutate({ strategy_type: strategyType, amount, start, end, fund_codes: selectedCodes, rebalance_threshold: rebalanceThreshold, template_key: templateKey })}
          >
            <Play className="h-4 w-4" /> 运行回测
          </button>
        </aside>
        <section className="grid gap-4">
          <StaleDataNotice updatedAt={mutation.data?.meta.data_updated_at ?? fundsQuery.data?.meta.data_updated_at} />
          {mutation.isError ? (
            <ErrorState
              title="回测运行失败"
              description={getApiErrorMessage(mutation.error, "未生成或保存结果，请检查日期、基金净值和策略参数后重试。")}
            />
          ) : null}
          {!result ? (
            <EmptyState title="尚未运行回测" description="选择策略参数和基金后运行，结果将基于数据库净值计算。" />
          ) : (
            <>
              <div className="grid gap-3 md:grid-cols-3 xl:grid-cols-6">
                <MetricTile label="年化收益" value={`${result.annualized_return.toFixed(2)}%`} />
                <MetricTile label="最大回撤" value={`${result.max_drawdown.toFixed(2)}%`} />
                <MetricTile label="波动率" value={`${result.volatility.toFixed(2)}%`} />
                <MetricTile label="夏普" value={result.sharpe_ratio.toFixed(2)} />
                <MetricTile label="投入" value={result.total_invested.toFixed(0)} />
                <MetricTile label="期末市值" value={result.final_value.toFixed(0)} />
              </div>
              {result.data_warning ? (
                <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3 text-sm text-[var(--text-muted)]">{result.data_warning}</div>
              ) : null}
              <ChartCard
                title="组合与基准收益曲线"
                option={{
                  tooltip: { trigger: "axis" },
                  legend: { data: ["组合", "基准"] },
                  grid: { left: 40, right: 16, top: 36, bottom: 30 },
                  xAxis: { type: "category", data: result.points.map((point) => point.date) },
                  yAxis: { type: "value" },
                  series: [
                    { name: "组合", type: "line", data: result.points.map((point) => point.portfolio), color: "#0f766e" },
                    { name: "基准", type: "line", data: result.points.map((point) => point.benchmark), color: "#b58b00" }
                  ]
                }}
              />
              <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
                <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                  <div>
                    <h2 className="text-sm font-semibold">AI 回测解释</h2>
                    <p className="mt-1 text-xs text-[var(--text-muted)]">基于本次回测 ID 和历史结果生成投教式解释。</p>
                  </div>
                  <button
                    className="focus-ring inline-flex h-9 items-center gap-2 rounded-md border border-[var(--border)] px-3 text-sm disabled:cursor-not-allowed disabled:opacity-50"
                    disabled={explainMutation.isPending}
                    onClick={() => explainMutation.mutate(result.id)}
                  >
                    <Bot className="h-4 w-4" /> 解释本次回测
                  </button>
                </div>
                {explainMutation.data ? (
                  <div className="mt-4 grid gap-3 text-sm leading-6">
                    <p className="font-medium">{explainMutation.data.data.conclusion}</p>
                    <ul className="grid gap-1 text-[var(--text-muted)]">
                      {explainMutation.data.data.evidence.map((item) => <li key={item}>{item}</li>)}
                    </ul>
                    <p className="text-[var(--r4)]">{explainMutation.data.data.risk}</p>
                  </div>
                ) : null}
                {explainMutation.isError ? (
                  <div className="mt-4">
                    <ErrorState
                      title="回测解释失败"
                      description={getApiErrorMessage(explainMutation.error, "回测结果仍然可用，AI 解释暂时无法生成。")}
                      onRetry={() => explainMutation.mutate(result.id)}
                    />
                  </div>
                ) : null}
              </div>
            </>
          )}
          <ComplianceNotice />
        </section>
      </div>}
    </>
  );
}
