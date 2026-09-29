"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Plus, RefreshCw, Save, Trash2 } from "lucide-react";
import { Button } from "@/components/button";
import { ChartCard } from "@/components/chart-card";
import { ComplianceNotice } from "@/components/compliance-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { FormField, Input, Select } from "@/components/form-field";
import { LoadingBlock } from "@/components/loading-block";
import { MetricTile } from "@/components/metric-tile";
import { PageHeader } from "@/components/page-header";
import { RiskLevelBadge } from "@/components/risk-level-badge";
import { StaleDataNotice } from "@/components/stale-data-notice";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { PortfolioTemplate } from "@/lib/api/types";
import { COMPLIANCE_MESSAGES } from "@/lib/compliance/constants";
import { isPortfolioTemplateSuitable, portfolioTemplateRiskMessage } from "@/lib/portfolio/template-risk";
import { resolveEffectiveRiskProfile } from "@/lib/risk/effective-profile";

export default function PortfolioPage() {
  const queryClient = useQueryClient();
  const templatesQuery = useQuery({ queryKey: ["portfolio-templates"], queryFn: apiClient.portfolioTemplates });
  const portfoliosQuery = useQuery({ queryKey: ["portfolios"], queryFn: apiClient.portfolios });
  const fundsQuery = useQuery({ queryKey: ["portfolio-fund-candidates"], queryFn: () => apiClient.searchFunds("", { page_size: 20 }) });
  const riskQuery = useQuery({ queryKey: ["risk-latest"], queryFn: apiClient.latestRiskAssessment });
  const effectiveRisk = resolveEffectiveRiskProfile(riskQuery.data?.data);
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
  const selectedPortfolio = detailQuery.data?.data;
  const hasUnavailablePositions = (selectedPortfolio?.unavailable_position_count ?? 0) > 0;
  const previewQuery = useQuery({
    queryKey: ["portfolio-rebalance-preview", activePortfolioId, detailQuery.data?.data.positions],
    queryFn: () => apiClient.rebalancePreview(activePortfolioId),
    enabled: Boolean(activePortfolioId && selectedPortfolio) && !hasUnavailablePositions
  });

  const preview = previewQuery.data?.data;
  const canShowPreview = !hasUnavailablePositions && previewQuery.isSuccess && Boolean(preview);
  const previewMessage = hasUnavailablePositions
    ? "存在不可用持仓，当前不会生成再平衡结论。"
    : previewQuery.isError
      ? "再平衡预览加载失败，当前不展示历史结果。"
      : previewQuery.isLoading
        ? "正在加载再平衡预览。"
        : preview?.message ?? "暂无可用预览。";
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
  const normalizePositionsMutation = useMutation({
    mutationFn: () => apiClient.normalizePortfolioPositions(activePortfolioId),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["portfolio-detail", activePortfolioId] });
      void queryClient.invalidateQueries({ queryKey: ["portfolio-rebalance-preview", activePortfolioId] });
    }
  });

  const template = useMemo(() => templates.find((item) => item.id === selectedTemplate), [selectedTemplate, templates]);
  const templateSuitable = isPortfolioTemplateSuitable(template, effectiveRisk.profile);
  const mutationError = createMutation.error
    ?? renameMutation.error
    ?? positionMutation.error
    ?? removePositionMutation.error
    ?? normalizePositionsMutation.error;

  return (
    <>
      <PageHeader title="组合管理" description="使用模板创建组合，维护持仓比例，并查看超过 5% 偏离时的再平衡预览。" />
      {templatesQuery.isLoading || portfoliosQuery.isLoading || fundsQuery.isLoading || riskQuery.isLoading ? <LoadingBlock /> : templatesQuery.isError || portfoliosQuery.isError || fundsQuery.isError || riskQuery.isError ? (
        <ErrorState
          title="组合管理数据加载失败"
          description={getApiErrorMessage(
            templatesQuery.error ?? portfoliosQuery.error ?? fundsQuery.error ?? riskQuery.error,
            "无法读取模板、组合、基金候选或风险画像，当前不会提交修改。"
          )}
          onRetry={() => {
            void templatesQuery.refetch();
            void portfoliosQuery.refetch();
            void fundsQuery.refetch();
            void riskQuery.refetch();
          }}
        />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[300px_minmax(0,1fr)_420px]">
          <aside className="grid h-fit gap-3">
            <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-sm font-semibold">创建组合</h2>
              <FormField id="new-portfolio-name" label="名称" className="mt-3">
                <Input
                  controlSize="compact"
                  value={portfolioName}
                  onChange={(event) => setPortfolioName(event.target.value)}
                />
              </FormField>
              <FormField id="new-portfolio-template" label="模板" className="mt-3">
                <Select
                  controlSize="compact"
                  value={selectedTemplate}
                  onChange={(event) => setSelectedTemplate(event.target.value as PortfolioTemplate["id"])}
                >
                  {templates.map((item) => (
                    <option key={item.id} value={item.id}>
                      {item.name}{isPortfolioTemplateSuitable(item, effectiveRisk.profile) ? "" : `（不匹配 ${effectiveRisk.profile}）`}
                    </option>
                  ))}
                </Select>
              </FormField>
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
              <div className="mt-3">
                <ComplianceNotice>
                  {portfolioTemplateRiskMessage(template, effectiveRisk.profile, effectiveRisk.usesDefault)}
                </ComplianceNotice>
              </div>
              <Button
                size="compact"
                className="mt-4"
                disabled={!portfolioName.trim() || !templateSuitable || createMutation.isPending}
                onClick={() => createMutation.mutate()}
              >
                <Plus className="h-4 w-4" /> 创建
              </Button>
            </section>
            <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-sm font-semibold">我的组合</h2>
              <div className="mt-3 grid gap-2">
                {portfolios.map((portfolio) => (
                  <Button
                    key={portfolio.id}
                    variant="unstyled"
                    size="none"
                    aria-pressed={activePortfolioId === portfolio.id}
                    className={`rounded-md border px-3 py-2 text-left text-sm ${activePortfolioId === portfolio.id ? "border-[var(--accent)] bg-[var(--accent-weak)]" : "border-[var(--border)] bg-[var(--background)]"}`}
                    onClick={() => {
                      setSelectedPortfolioId(portfolio.id);
                      setPortfolioName(portfolio.name);
                    }}
                  >
                    <span className="font-medium">{portfolio.name}</span>
                    <span className="mt-1 block text-xs text-[var(--text-muted)]">
                      {portfolio.stock_ratio}/{portfolio.bond_ratio} · {portfolio.position_count} 只
                      {portfolio.unavailable_position_count ? ` · ${portfolio.unavailable_position_count} 只不可用` : ""}
                    </span>
                  </Button>
                ))}
              </div>
            </section>
          </aside>
          <section className="grid gap-3">
            <StaleDataNotice updatedAt={fundsQuery.data?.meta.data_updated_at ?? detailQuery.data?.meta.data_updated_at ?? portfoliosQuery.data?.meta.data_updated_at} />
            {mutationError ? (
              <ErrorState
                title="组合修改失败"
                description={getApiErrorMessage(mutationError, "本次更改尚未保存，现有组合数据未被覆盖。")}
              />
            ) : null}
            {detailQuery.isError ? (
              <ErrorState
                title="组合详情加载失败"
                description={getApiErrorMessage(detailQuery.error, "无法读取当前组合持仓。")}
                onRetry={() => void detailQuery.refetch()}
              />
            ) : detailQuery.isLoading ? <LoadingBlock /> : selectedPortfolio ? (
              <>
                <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
                  <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto]">
                    <Input
                      aria-label="组合名称"
                      value={portfolioName}
                      onChange={(event) => setPortfolioName(event.target.value)}
                    />
                    <Button
                      variant="secondary"
                      disabled={!portfolioName.trim() || renameMutation.isPending}
                      onClick={() => renameMutation.mutate()}
                    >
                      <Save className="h-4 w-4" /> 保存名称
                    </Button>
                  </div>
                </div>
                <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_120px_auto]">
                  <Select
                    aria-label="持仓基金"
                    className="bg-[var(--surface)]"
                    value={activeFundCode}
                    onChange={(event) => setSelectedFundCode(event.target.value)}
                  >
                    {fundCandidates.map((fund) => (
                      <option key={fund.code} value={fund.code}>{fund.code} · {fund.name}</option>
                    ))}
                  </Select>
                  <Input
                    aria-label="持仓比例（百分比）"
                    type="number"
                    min={0}
                    max={100}
                    className="bg-[var(--surface)]"
                    value={weightPercent}
                    onChange={(event) => setWeightPercent(Number(event.target.value))}
                  />
                  <Button
                    disabled={!activeFundCode || positionMutation.isPending}
                    onClick={() => positionMutation.mutate()}
                  >
                    <Plus className="h-4 w-4" /> 保存持仓
                  </Button>
                </div>
                {hasUnavailablePositions ? (
                  <div className="rounded-md border border-[var(--r4)] bg-[var(--surface)] p-3 text-sm leading-6 text-[var(--text-muted)]" role="status">
                    <div className="font-medium text-[var(--text)]">组合含当前不可用持仓</div>
                    <p>
                      {selectedPortfolio.unavailable_position_count} 只基金已移出当前数据快照。持仓记录仍保留并可删除；移除或重新同步前，不会计算归一化和再平衡预览。
                    </p>
                  </div>
                ) : null}
                {selectedPortfolio.weight_warning ? (
                  <div className="rounded-md border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-sm leading-6 text-[var(--text-muted)]">
                    <div className="font-medium text-[var(--text)]">持仓权重提示</div>
                    <p>{selectedPortfolio.weight_warning}</p>
                    <Button
                      variant="secondary"
                      size="none"
                      className="mt-3 h-9 px-3 text-xs"
                      disabled={hasUnavailablePositions || normalizePositionsMutation.isPending || selectedPortfolio.total_weight_percent <= 0}
                      onClick={() => normalizePositionsMutation.mutate()}
                    >
                      <RefreshCw className="h-3.5 w-3.5" /> 一键按归一化比例填充
                    </Button>
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
                            <td className="p-3">
                              <div className="flex flex-wrap items-center gap-2">
                                <span className="font-medium">{position.fund_name}</span>
                                {!position.available ? (
                                  <span className="rounded-md border border-[var(--r4)] px-2 py-0.5 text-xs text-[var(--r4)]">
                                    {position.availability_reason === "removed_from_active_snapshot" ? "已移出快照" : "当前不可用"}
                                  </span>
                                ) : null}
                              </div>
                              <div className="text-xs text-[var(--text-muted)]">{position.fund_code} · {position.fund_type}</div>
                            </td>
                            <td className="p-3"><RiskLevelBadge level={position.risk_level} /></td>
                            <td className="p-3 text-right">{position.weight_percent.toFixed(2)}%</td>
                            <td className="p-3 text-right">
                              {position.normalized_weight_percent == null
                                ? "-"
                                : `${position.normalized_weight_percent.toFixed(2)}%`}
                            </td>
                            <td className="p-3 text-right">
                              <Button
                                variant="secondary"
                                size="icon"
                                aria-label={`移除 ${position.fund_name}`}
                                title={`移除 ${position.fund_name}`}
                                onClick={() => removePositionMutation.mutate(position.fund_code)}
                              >
                                <Trash2 className="h-4 w-4" />
                              </Button>
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
            <div className="grid grid-cols-2 gap-2">
              <MetricTile label="持仓合计" value={`${selectedPortfolio?.total_weight_percent ?? 0}%`} />
              <MetricTile label="目标股类" value={`${selectedPortfolio?.stock_ratio ?? 0}%`} />
              <MetricTile label="目标债类" value={`${selectedPortfolio?.bond_ratio ?? 0}%`} />
              <MetricTile label="当前股类" value={canShowPreview ? `${preview?.current_stock_ratio}%` : "--"} />
              <MetricTile label="当前债类" value={canShowPreview ? `${preview?.current_bond_ratio}%` : "--"} />
            </div>
            {hasUnavailablePositions ? (
              <ChartCard
                title="股债比例"
                source={fundsQuery.data?.meta.source}
                status="error"
                errorTitle="含不可用持仓"
                errorDescription="当前基金分类已不在 active 快照内，移除不可用持仓或重新同步后再计算股债比例。"
              />
            ) : previewQuery.isLoading ? (
              <ChartCard title="股债比例" source={fundsQuery.data?.meta.source} status="loading" />
            ) : previewQuery.isError ? (
              <ChartCard
                title="股债比例"
                source={fundsQuery.data?.meta.source}
                status="error"
                errorDescription={getApiErrorMessage(previewQuery.error, "持仓仍可编辑，但当前偏离比例不可用。")}
                onRetry={() => void previewQuery.refetch()}
              />
            ) : !selectedPortfolio?.positions.length || !preview ? (
              <ChartCard
                title="股债比例"
                source={fundsQuery.data?.meta.source}
                status="empty"
                emptyTitle="尚无持仓比例"
                emptyDescription="添加至少一只持仓后再查看股债比例，空组合不会绘制 0/0 饼图。"
              />
            ) : (
              <ChartCard
                title="股债比例"
                source={fundsQuery.data?.meta.source}
                option={{
                  tooltip: { trigger: "item" },
                  series: [{
                    type: "pie",
                    radius: ["48%", "72%"],
                    data: [
                      { name: "股票/偏股", value: preview.current_stock_ratio },
                      { name: "债券/货币", value: preview.current_bond_ratio }
                    ],
                    color: ["#0f766e", "#b58b00"]
                  }]
                }}
              />
            )}
            <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
              <h2 className="text-sm font-semibold">再平衡预览</h2>
              <div className="mt-2 text-2xl font-semibold">
                {canShowPreview ? `${preview?.drift_percent.toFixed(2)}%` : "--"}
              </div>
              <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">{previewMessage}</p>
            </div>
            <ComplianceNotice>{COMPLIANCE_MESSAGES.portfolioRebalancePreview}</ComplianceNotice>
          </aside>
        </div>
      )}
    </>
  );
}
