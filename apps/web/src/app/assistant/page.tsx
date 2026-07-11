"use client";

import { useState } from "react";
import { AlertTriangle, Send } from "lucide-react";
import { ComplianceNotice } from "@/components/compliance-notice";
import { ErrorState } from "@/components/error-state";
import { PageHeader } from "@/components/page-header";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { ChatResponse } from "@/lib/api/types";
import { COMPLIANCE_MESSAGES } from "@/lib/compliance/constants";

export default function AssistantPage() {
  const [message, setMessage] = useState("解释这只基金为什么最大回撤比较高");
  const [fundCode, setFundCode] = useState("000001");
  const [answer, setAnswer] = useState<ChatResponse | null>(null);
  const [threadId, setThreadId] = useState<string | null>(null);
  const [streamText, setStreamText] = useState("暂无回答");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submit() {
    setLoading(true);
    setError(null);
    setAnswer(null);
    setStreamText("");
    try {
      const response = await apiClient.streamAssistantWithContext(
        message,
        { page: "assistant", fund_code: fundCode },
        (chunk) => setStreamText((current) => `${current}${current ? "\n" : ""}${chunk}`),
        threadId
      );
      setAnswer(response);
      setThreadId(response.thread_id ?? null);
    } catch (submitError) {
      setError(getApiErrorMessage(submitError, "AI 服务暂时无法响应，请稍后重试。"));
    } finally {
      setLoading(false);
    }
  }

  return (
    <>
      <PageHeader title="AI 分析助手" description="解释指标、总结基金、诊断组合和解读回测结果。" />
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_360px]">
        <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
          <label className="mb-3 grid gap-1 text-xs text-[var(--text-muted)]">
            基金代码上下文
            <input className="h-9 rounded-md border border-[var(--border)] bg-white px-3 text-sm text-[var(--text)] outline-none focus:border-[var(--accent)]" value={fundCode} onChange={(event) => setFundCode(event.target.value)} />
          </label>
          {threadId ? <div className="mb-3 text-xs text-[var(--text-muted)]">Thread: {threadId}</div> : null}
          <textarea className="min-h-32 w-full resize-y rounded-md border border-[var(--border)] bg-white p-3 text-sm outline-none focus:border-[var(--accent)]" value={message} onChange={(event) => setMessage(event.target.value)} />
          <button className="focus-ring mt-3 inline-flex h-10 items-center gap-2 rounded-md bg-[var(--accent)] px-4 text-sm font-medium text-white disabled:cursor-not-allowed disabled:opacity-50" onClick={submit} disabled={loading || !message.trim()}>
            <Send className="h-4 w-4" /> {loading ? "分析中" : "发送"}
          </button>
          {error ? (
            <div className="mt-4">
              <ErrorState title="AI 回答失败" description={error} onRetry={() => void submit()} />
            </div>
          ) : <div className="mt-4 rounded-md bg-[var(--surface-muted)] p-4 text-sm leading-6">
            {answer ? (
              <div className="grid gap-3">
                {answer.unable_to_answer ? (
                  <div className="flex items-center gap-2 text-[var(--danger)]"><AlertTriangle className="h-4 w-4" /> 无法回答</div>
                ) : null}
                <p className="font-medium">{answer.conclusion}</p>
                <pre className="whitespace-pre-wrap rounded-md bg-[var(--surface)] p-3 text-xs text-[var(--text-muted)]">{streamText}</pre>
                <div>
                  <div className="text-xs text-[var(--text-muted)]">数据依据</div>
                  <ul className="mt-1 list-inside list-disc">
                    {answer.evidence.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
                <div>
                  <div className="text-xs text-[var(--text-muted)]">引用</div>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {answer.references.length ? answer.references.map((item) => (
                      <span key={item} className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs">{item}</span>
                    )) : <span className="text-xs text-[var(--text-muted)]">无可引用数据</span>}
                  </div>
                </div>
                <p>风险提示：{answer.risk}</p>
                <p className="text-xs text-[var(--text-muted)]">数据日期：{answer.data_date}</p>
                <p className="text-xs text-[var(--text-muted)]">{answer.disclaimer}</p>
              </div>
            ) : "暂无回答"}
          </div>}
        </section>
        <ComplianceNotice>{COMPLIANCE_MESSAGES.aiAnswerRequirements}</ComplianceNotice>
      </div>
    </>
  );
}
