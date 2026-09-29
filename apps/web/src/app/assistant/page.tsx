"use client";

import { useState } from "react";
import { AlertTriangle, Send } from "lucide-react";
import { Button } from "@/components/button";
import { ComplianceNotice } from "@/components/compliance-notice";
import { ErrorState } from "@/components/error-state";
import { FormField, Input, Textarea } from "@/components/form-field";
import { PageHeader } from "@/components/page-header";
import { apiClient } from "@/lib/api/client";
import { getApiErrorMessage } from "@/lib/api/error-message";
import type { ApiResponse, ChatResponse } from "@/lib/api/types";
import { COMPLIANCE_MESSAGES } from "@/lib/compliance/constants";

export default function AssistantPage() {
  const [message, setMessage] = useState("解释这只基金为什么最大回撤比较高");
  const [fundCode, setFundCode] = useState("000001");
  const [answer, setAnswer] = useState<ApiResponse<ChatResponse> | null>(null);
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
      setThreadId(response.data.thread_id ?? null);
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
          <FormField
            id="assistant-fund-code"
            label="基金代码上下文"
            description="用于读取单只基金的指标与净值；留空时按一般投教问题处理。"
            className="mb-3"
          >
            <Input value={fundCode} inputMode="numeric" maxLength={6} onChange={(event) => setFundCode(event.target.value)} />
          </FormField>
          {threadId ? <div className="mb-3 text-xs text-[var(--text-muted)]">Thread: {threadId}</div> : null}
          <FormField id="assistant-message" label="问题">
            <Textarea className="min-h-32 resize-y bg-white p-3" value={message} onChange={(event) => setMessage(event.target.value)} />
          </FormField>
          <Button className="mt-3" onClick={submit} disabled={loading || !message.trim()}>
            <Send className="h-4 w-4" /> {loading ? "分析中" : "发送"}
          </Button>
          {error ? (
            <div className="mt-4">
              <ErrorState title="AI 回答失败" description={error} onRetry={() => void submit()} />
            </div>
          ) : <div className="mt-4 rounded-md bg-[var(--surface-muted)] p-4 text-sm leading-6">
            {answer ? (
              <div className="grid gap-3">
                {answer.data.unable_to_answer ? (
                  <div className="flex items-center gap-2 text-[var(--danger)]"><AlertTriangle className="h-4 w-4" /> 无法回答</div>
                ) : null}
                <p className="font-medium">{answer.data.conclusion}</p>
                <pre className="whitespace-pre-wrap rounded-md bg-[var(--surface)] p-3 text-xs text-[var(--text-muted)]">{streamText}</pre>
                <div>
                  <div className="text-xs text-[var(--text-muted)]">数据依据</div>
                  <ul className="mt-1 list-inside list-disc">
                    {answer.data.evidence.map((item) => <li key={item}>{item}</li>)}
                  </ul>
                </div>
                <div>
                  <div className="text-xs text-[var(--text-muted)]">引用</div>
                  <div className="mt-1 flex flex-wrap gap-2">
                    {answer.data.references.length ? answer.data.references.map((item) => (
                      <span key={item} className="rounded-md border border-[var(--border)] bg-[var(--surface)] px-2 py-1 text-xs">{item}</span>
                    )) : <span className="text-xs text-[var(--text-muted)]">无可引用数据</span>}
                  </div>
                </div>
                <p>风险提示：{answer.data.risk}</p>
                <p className="text-xs text-[var(--text-muted)]">数据来源：{answer.meta.source}</p>
                <p className="text-xs text-[var(--text-muted)]">数据日期：{answer.data.data_date}</p>
                <p className="text-xs text-[var(--text-muted)]">{answer.data.disclaimer}</p>
              </div>
            ) : "暂无回答"}
          </div>}
        </section>
        <ComplianceNotice>{COMPLIANCE_MESSAGES.aiAnswerRequirements}</ComplianceNotice>
      </div>
    </>
  );
}
