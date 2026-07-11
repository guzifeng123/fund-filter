import { FundDetailPanel } from "@/features/funds/fund-detail-panel";
import { PageHeader } from "@/components/page-header";

export default async function FundDetailRoute({ params }: { params: Promise<{ code: string }> }) {
  const { code } = await params;
  return (
    <>
      <PageHeader title="基金详情" description="基础信息、历史净值、风险匹配、费用结构和 AI 诊断摘要。" />
      <FundDetailPanel code={code} />
    </>
  );
}
