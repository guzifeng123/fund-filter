"use client";

import { useMemo, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, ShieldCheck } from "lucide-react";
import { Button } from "@/components/button";
import { ComplianceNotice } from "@/components/compliance-notice";
import { EmptyState } from "@/components/empty-state";
import { ErrorState } from "@/components/error-state";
import { LoadingBlock } from "@/components/loading-block";
import { MetricTile } from "@/components/metric-tile";
import { PageHeader } from "@/components/page-header";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { RiskAnswer } from "@/lib/api/types";
import { COMPLIANCE_MESSAGES } from "@/lib/compliance/constants";

export default function RiskAssessmentPage() {
  const queryClient = useQueryClient();
  const questionsQuery = useQuery({ queryKey: ["risk-questions"], queryFn: apiClient.riskQuestions });
  const latestQuery = useQuery({ queryKey: ["risk-latest"], queryFn: apiClient.latestRiskAssessment });
  const [answers, setAnswers] = useState<Record<string, number>>({});

  const questions = useMemo(() => questionsQuery.data?.data ?? [], [questionsQuery.data?.data]);
  const completedCount = Object.keys(answers).length;
  const canSubmit = questions.length > 0 && completedCount === questions.length;
  const answerPayload: RiskAnswer[] = useMemo(
    () => questions.map((question) => ({ question_id: question.id, score: answers[question.id] ?? 0 })),
    [answers, questions]
  );

  const mutation = useMutation({
    mutationFn: () => apiClient.submitRiskAssessment(answerPayload),
    onSuccess: () => {
      void queryClient.invalidateQueries({ queryKey: ["risk-latest"] });
      void queryClient.invalidateQueries({ queryKey: ["dashboard"] });
    }
  });

  const result = mutation.data?.data ?? latestQuery.data?.data;

  return (
    <>
      <PageHeader
        title="风险测评"
        description="完成 6 道题生成 C1-C5 风险画像，有效期 12 个月，到期前会在首页提示。"
        actions={<span className="text-xs text-[var(--text-muted)]">{completedCount}/{questions.length || 6}</span>}
      />
      {questionsQuery.isLoading ? <LoadingBlock /> : questionsQuery.isError ? (
        <ErrorState
          title="风险测评题目加载失败"
          description={getApiErrorMessage(questionsQuery.error, "无法读取题库，当前不会生成或覆盖风险画像。")}
          onRetry={() => void questionsQuery.refetch()}
        />
      ) : !questions.length ? (
        <EmptyState title="暂无风险测评题目" description="题库为空，请检查 API 数据初始化状态。" />
      ) : (
        <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
          <section className="grid gap-3">
            {questions.map((question, index) => (
              <div key={question.id} className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
                <div className="text-xs text-[var(--text-muted)]">Q{index + 1}</div>
                <h2 className="mt-1 text-base font-semibold">{question.title}</h2>
                <div className="mt-3 grid gap-2 sm:grid-cols-5">
                  {question.options.map((option) => {
                    const selected = answers[question.id] === option.score;
                    return (
                      <Button
                        key={option.score}
                        variant="unstyled"
                        size="none"
                        aria-pressed={selected}
                        className={`min-h-16 rounded-md border px-3 py-2 text-left text-sm ${selected ? "border-[var(--accent)] bg-[var(--accent-weak)]" : "border-[var(--border)] bg-[var(--background)] hover:bg-[var(--surface-muted)]"}`}
                        onClick={() => setAnswers((current) => ({ ...current, [question.id]: option.score }))}
                      >
                        <span className="block text-xs text-[var(--text-muted)]">{option.score} 分</span>
                        {option.label}
                      </Button>
                    );
                  })}
                </div>
              </div>
            ))}
            <Button
              className="w-fit"
              disabled={!canSubmit || mutation.isPending}
              onClick={() => mutation.mutate()}
            >
              <ShieldCheck className="h-4 w-4" />
              保存测评结果
            </Button>
            {mutation.isError ? (
              <ErrorState
                title="测评结果保存失败"
                description={getApiErrorMessage(mutation.error, "本次答案尚未保存，请稍后重试。")}
                onRetry={() => mutation.mutate()}
              />
            ) : null}
          </section>
          <aside className="grid h-fit gap-3">
            {latestQuery.isError && !mutation.data ? (
              <ErrorState
                title="历史测评加载失败"
                description={getApiErrorMessage(latestQuery.error, "仍可完成新测评，但当前无法读取最近一次风险画像。")}
                onRetry={() => void latestQuery.refetch()}
              />
            ) : result ? (
              <>
                <MetricTile label="风险画像" value={result.risk_profile} hint={result.explanation} />
                <MetricTile label="总分" value={String(result.score)} hint={`${result.effective_from} 至 ${result.effective_to}`} />
                <div className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
                  <div className="flex items-center gap-2 text-sm font-semibold">
                    <CheckCircle2 className="h-4 w-4 text-[var(--accent)]" />
                    {result.is_expired ? "已过期" : result.expires_soon ? "即将过期" : "有效"}
                  </div>
                  <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">
                    风险画像用于筛选和比较时识别风险等级是否匹配，不代表任何收益承诺或交易指令。
                  </p>
                </div>
              </>
            ) : (
              <ComplianceNotice>{COMPLIANCE_MESSAGES.riskAssessmentDefault}</ComplianceNotice>
            )}
            <ComplianceNotice />
          </aside>
        </div>
      )}
    </>
  );
}
