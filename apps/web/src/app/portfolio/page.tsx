"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, Save, Trash2 } from "lucide-react";
import { ChartCard } from "@/components/chart-card";
import { ComplianceNotice } from "@/components/compliance-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetricTile } from "@/components/metric-tile";
import { PageHeader } from "@/components/page-header";
import { RiskLevelBadge } from "@/components/risk-level-badge";
import { StaleDataNotice } from "@/components/stale-data-notice";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { PortfolioTemplate } from "@/lib/api/types";
import { COMPLIANCE_MESSAGES } from "@/lib/compliance/constants";

export default function PortfolioPage() {
  const queryClient = useQueryClient();
  const templatesQuery = useQuery({ queryKey: ["portfolio-templates"], queryFn: apiClient.portfolioTemplates });
  const portfoliosQuery = useQuery({ queryKey: ["portfolios"], queryFn: apiClient.portfolios });
  const fundsQuery = useQuery({ queryKey: ["portfolio-fund-candidates"], queryFn: () => apiClient.searchFunds("", { page_size: 20 }) });
  const portfolios = useMemo(() => portfoliosQuery.data?.data ?? [], [portfoliosQuery.data?.data]);
  const templates = useMemo(() => templatesQuery.data?.data ?? [], [templatesQuery.data?.data]);
  const [selectedPortfolioId, setSelectedPortfolioId] = useState<string>("");
  const [selectedTemplate, setSelectedTemplate] = useState<PortfolioTemplate["id"]>("balanced");
  const [portfolioName, setPortfolioName] = useState("我的稳健组合");
  const [selectedFundCode, setSelectedFundCode] = useState("");
  const [weightPercent, setWeightPercent] = useState(50);
  const activePortfolioId = selectedPortfolioId || portfolios[0]?.id || "";

  const detailQuery = useQuery({
    queryKey: ["portfolio-detail", activePortfolioId],
    queryFn: () => apiClient.portfolioDetail(activePortfolioId),
    enabled: Boolean(activePortfolioId)
  });
  const previewQuery = useQuery({
    queryKey: ["portfolio-rebalance-preview", activePortfolioId, detailQuery.data?.data.positions],
    queryFn: () => apiClient.rebalancePreview(activePortfolioId),
    enabled: Boolean(activePortfolioId)
  });

  const selectedPortfolio = detailQuery.data?.data;
  const preview = previewQuery.data?.data;
  const fundCandidates = useMemo(() => fundsQuery.data?.data ?? [], [fundsQuery.data?.data]);
  const activeFundCode = selectedFundCode || fundCandidates[0]?.code || "";

  const createMutation = useMutation({
    mutationFn: () => apiClient.createPortfolio({ name: portfolioName, template_key: selectedTemplate }),
    onSuccess: (response) => {
      setSelectedPortfolioId(response.data.id);
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
    }
  });
  const renameMutation = useMutation({
    mutationFn: () => apiClient.updatePortfolio(activePortfolioId, { name: portfolioName }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portfolios"] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio-detail", activePortfolioId] });
    }
  });
  const positionMutation = useMutation({
    mutationFn: () => apiClient.savePortfolioPosition(activePortfolioId, { fund_code: activeFundCode, weight_percent: weightPercent }),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portfolio-detail", activePortfolioId] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio-rebalance-preview", activePortfolioId] });
    }
  });
  const removePositionMutation = useMutation({
    mutationFn: (fundCode: string) => apiClient.removePortfolioPosition(activePortfolioId, fundCode),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portfolio-detail", activePortfolioId] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio-rebalance-preview", activePortfolioId] });
    }
  });

  const template = useMemo(() => templates.find((item) => item.id === selectedTemplate), [selectedTemplate, templates]);
  const mutationError = createMutation.error ?? renameMutation.error ?? positionMutation.error ?? removePositionMutation.error;

  return (
    <>
      <PageHeader title="组合管理" description="使用模板创建组合，维护持仓比例，并查看超过 5% 偏离时的再平衡预览。" />
      {templatesQuery.isLoading || portfoliosQuery.isLoading || fundsQuery.isLoading ? <LoadingBlock /> : templatesQuery.isError || portfoliosQuery.isError || fundsQuery.isError ? (
        <ErrorState
          title="组合管理数据加载失败"
          description="无法读取模板、组合或基金候选数据，当前不会提交修改。"
          onRetry={() => {
            void templatesQuery.refetch();
            void portfoliosQuery.refetch();
            void fundsQuery.refetch();
          }}
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)_420px]">
          <aside className="grid h-fit gap-3">
            <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-sm font-semibold">创建组合</h2>
              <label className="mt-3 grid gap-1 text-xs text-[var(--text-muted)]">
                名称
                <input
                  className="h-9 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-sm text-[var(--text)] outline-none"
                  value={portfolioName}
                  onChange={(event) => setPortfolioName(event.target.value)}
                />
              </label>
              <label className="mt-3 grid gap-1 text-xs text-[var(--text-muted)]">
                模板
                <select
                  className="h-9 rounded-md border border-[var(--border)] bg-[var(--background)] px-2 text-sm text-[var(--text)] outline-none"
                  value={selectedTemplate}
                  onChange={(event) => setSelectedTemplate(event.target.value as PortfolioTemplate["id"])}
                >
                  {templates.map((item) => (
                    <option key={item.id} value={item.id}>{item.name}</option>
                  ))}
                </select>
              </label>
              <div className="mt-3 grid grid-cols-2 gap-2 text-xs text-[var(--text-muted)]">
                <span>目标股类</span><strong className="text-right text-[var(--text)]">{template?.stock_ratio ?? 0}%</strong>
                <span>目标债类</span><strong className="text-right text-[var(--text)]">{template?.bond_ratio ?? 0}%</strong>
              </div>
              <div className="mt-3 rounded-md border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-xs text-[var(--text-muted)]">
                <div className="font-medium text-[var(--text)]">适用风险画像</div>
                <div className="mt-2 flex flex-wrap gap-1">
                  {(template?.suitable_profiles ?? []).map((profile) => (
                    <span key={profile} className="rounded-md border border-[var(--border)] bg-[var(--background)] px-2 py-1">
                      {profile}
                    </span>
                  ))}
                </div>
              </div>
              <button
                className="focus-ring mt-4 inline-flex h-9 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white"
                disabled={!portfolioName.trim() || createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                <Plus className="h-4 w-4" /> 创建
              </button>
            </section>
            <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-sm font-semibold">我的组合</h2>
              <div className="mt-3 grid gap-2">
                {portfolios.map((portfolio) => (
                  <button
                    key={portfolio.id}
                    className={`focus-ring rounded-md border px-3 py-2 text-left text-sm ${activePortfolioId === portfolio.id ? "border-[var(--accent)] bg-[var(--accent-weak)]" : "border-[var(--border)] bg-[var(--background)]"}`}
                    onClick={() => {
                      setSelectedPortfolioId(portfolio.id);
                      setPortfolioName(portfolio.name);
                    }}
                  >
                    <span className="font-medium">{portfolio.name}</span>
                    <span className="mt-1 block text-xs text-[var(--text-muted)]">{portfolio.stock_ratio}/{portfolio.bond_ratio} · {portfolio.position_count} 只</span>
                  </button>
                ))}
              </div>
            </section>
          </aside>
          <section className="grid gap-3">
            <StaleDataNotice updatedAt={detailQuery.data?.meta.data_updated_at ?? portfoliosQuery.data?.meta.data_updated_at} />
            {mutationError ? (
              <ErrorState
                title="组合修改失败"
                description={getApiErrorMessage(mutationError, "本次更改尚未保存，现有组合数据未被覆盖。")}
              />
            ) : null}
            {detailQuery.isError ? (
              <ErrorState
                title="组合详情加载失败"
                description="无法读取当前组合持仓。"
                onRetry={() => void detailQuery.refetch()}
              />
            ) : detailQuery.isLoading ? <LoadingBlock /> : selectedPortfolio ? (
              <>
                <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                    <input
                      className="h-10 rounded-md border border-[var(--border)] bg-[var(--background)] px-3 text-sm outline-none"
                      value={portfolioName}
                      onChange={(event) => setPortfolioName(event.target.value)}
                    />
                    <button
                      className="focus-ring inline-flex h-10 items-center gap-2 rounded-md border border-[var(--border)] px-3 text-sm"
                      disabled={!portfolioName.trim() || renameMutation.isPending}
                      onClick={() => renameMutation.mutate()}
                    >
                      <Save className="h-4 w-4" /> 保存名称
                    </button>
                  </div>
                </div>
                <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_120px_auto]">
                  <select
                    className="h-10 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm outline-none"
                    value={activeFundCode}
                    onChange={(event) => setSelectedFundCode(event.target.value)}
                  >
                    {fundCandidates.map((fund) => (
                      <option key={fund.code} value={fund.code}>{fund.code} · {fund.name}</option>
                    ))}
                  </select>
                  <input
                    type="number"
                    min={0}
                    max={100}
                    className="h-10 rounded-md border border-[var(--border)] bg-[var(--surface)] px-3 text-sm outline-none"
                    value={weightPercent}
                    onChange={(event) => setWeightPercent(Number(event.target.value))}
                  />
                  <button
                    className="focus-ring inline-flex h-10 items-center gap-2 rounded-md bg-[var(--accent)] px-3 text-sm font-medium text-white"
                    disabled={!activeFundCode || positionMutation.isPending}
                    onClick={() => positionMutation.mutate()}
                  >
                    <Plus className="h-4 w-4" /> 保存持仓
                  </button>
                </div>
                {selectedPortfolio.weight_warning ? (
                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-sm leading-6 text-[var(--text-muted)]">
                    <div className="font-medium text-[var(--text)]">持仓权重提示</div>
                    <p>{selectedPortfolio.weight_warning}</p>
                  </div>
                ) : null}
                {selectedPortfolio.positions.length ? (
                  <div className="overflow-x-auto rounded-md border border-[var(--border)] bg-[var(--surface)]">
                    <table className="w-full min-w-[620px] text-sm">
                      <thead className="bg-[var(--surface-muted)] text-left text-xs text-[var(--text-muted)]">
                        <tr><th className="p-3">基金</th><th className="p-3">风险</th><th className="p-3 text-right">比例</th><th className="p-3 text-right">归一化</th><th className="p-3"></th></tr>
                      </thead>
                      <tbody>
                        {selectedPortfolio.positions.map((position) => (
                          <tr key={position.fund_code} className="border-t border-[var(--border)]">
                            <td className="p-3"><div className="font-medium">{position.fund_name}</div><div className="text-xs text-[var(--text-muted)]">{position.fund_code} · {position.fund_type}</div></td>
                            <td className="p-3"><RiskLevelBadge level={position.risk_level} /></td>
                            <td className="p-3 text-right">{position.weight_percent.toFixed(2)}%</td>
                            <td className="p-3 text-right">{position.normalized_weight_percent?.toFixed(2) ?? "-"}%</td>
                            <td className="p-3 text-right">
                              <button className="focus-ring rounded-md border border-[var(--border)] p-2" onClick={() => removePositionMutation.mutate(position.fund_code)}>
                                <Trash2 className="h-4 w-4" />
                              </button>
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                ) : (
                  <EmptyState title="暂无持仓" description="选择基金并设置比例后，可以查看真实偏离和再平衡预览。" />
                )}
              </>
            ) : (
              <EmptyState title="还没有组合" description="先选择模板创建一个组合。" />
            )}
          </section>
          <aside className="grid h-fit gap-3">
            {previewQuery.isError ? (
              <ErrorState
                title="再平衡预览加载失败"
                description="持仓仍可编辑，但当前偏离比例不可用。"
                onRetry={() => void previewQuery.refetch()}
              />
            ) : null}
            <div className="grid grid-cols-2 gap-2">
              <MetricTile label="持仓合计" value={`${selectedPortfolio?.total_weight_percent ?? 0}%`} />
              <MetricTile label="目标股类" value={`${selectedPortfolio?.stock_ratio ?? 0}%`} />
              <MetricTile label="目标债类" value={`${selectedPortfolio?.bond_ratio ?? 0}%`} />
              <MetricTile label="当前股类" value={`${preview?.current_stock_ratio ?? 0}%`} />
              <MetricTile label="当前债类" value={`${preview?.current_bond_ratio ?? 0}%`} />
            </div>
            <ChartCard
              title="股债比例"
              option={{
                tooltip: { trigger: "item" },
                series: [{
                  type: "pie",
                  radius: ["48%", "72%"],
                  data: [
                    { name: "股票/偏股", value: preview?.current_stock_ratio ?? 0 },
                    { name: "债券/货币", value: preview?.current_bond_ratio ?? 0 }
                  ],
                  color: ["#0f766e", "#b58b00"]
                }]
              }}
            />
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-sm font-semibold">再平衡预览</h2>
              <div className="mt-2 text-2xl font-semibold">{(preview?.drift_percent ?? 0).toFixed(2)}%</div>
              <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">{preview?.message ?? "暂无预览"}</p>
            </div>
            <ComplianceNotice>{COMPLIANCE_MESSAGES.portfolioRebalancePreview}</ComplianceNotice>
          </aside>
        </div>
      )}
    </>
  );
}
