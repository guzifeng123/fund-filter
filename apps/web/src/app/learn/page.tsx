import { ComplianceNotice } from "@/components/compliance-notice";
import { PageHeader } from "@/components/page-header";

const lessons = ["基金基础概念", "风险等级解释", "定投和再平衡", "最大回撤、夏普比率和波动率", "常见误区"];

export default function LearnPage() {
  return (
    <>
      <PageHeader title="投教学习" description="把指标和策略解释清楚，再进入筛选和回测。" />
      <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
        {lessons.map((lesson) => (
          <article key={lesson} className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
            <h2 className="text-base font-semibold">{lesson}</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">本节内容进入 RAG 检索后，可被 AI 助手引用并标注来源。</p>
          </article>
        ))}
      </div>
      <div className="mt-4"><ComplianceNotice /></div>
    </>
  );
}
