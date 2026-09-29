import { LEARNING_GLOSSARY, LEARNING_MODULES } from "@/app/learn/learning-content";
import { LearningGlossary, LearningModule } from "@/app/learn/learning-module";
import { ComplianceNotice } from "@/components/compliance-notice";
import { PageHeader } from "@/components/page-header";

export default function LearnPage() {
  return (
    <>
      <PageHeader
        title="投教学习"
        description="用简化公式和小例子理解历史指标、费用与策略边界，再进入筛选、比较和回测。"
      />
      <div className="mb-4">
        <ComplianceNotice>本页示例仅用于解释指标口径；计算前请确认数据区间、更新时间和费用假设。</ComplianceNotice>
      </div>
      <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_340px]">
        <section className="order-2 grid gap-4 xl:order-1" aria-label="投教学习模块">
          {LEARNING_MODULES.map((module, index) => (
            <LearningModule key={module.id} module={module} index={index + 1} />
          ))}
        </section>
        <div className="order-1 xl:order-2">
          <LearningGlossary modules={LEARNING_MODULES} items={LEARNING_GLOSSARY} />
        </div>
      </div>
    </>
  );
}
