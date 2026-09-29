import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { LEARNING_MODULES } from "@/app/learn/learning-content";
import LearnPage from "@/app/learn/page";
import { COMPLIANCE_DISCLAIMER } from "@/lib/compliance/constants";

const expectedTopics = [
  "收益与复利",
  "最大回撤与波动",
  "夏普与风险调整",
  "费率与长期成本",
  "定投、再平衡与回测局限"
];

describe("LearnPage", () => {
  it("contains five complete learning modules instead of repeated placeholder cards", () => {
    const html = renderToStaticMarkup(<LearnPage />);

    expect(LEARNING_MODULES).toHaveLength(5);
    expect(html.match(/<article/g)).toHaveLength(5);
    for (const topic of expectedTopics) {
      expect(html).toContain(topic);
    }
    expect(html).not.toContain("本节内容进入 RAG 检索后，可被 AI 助手引用并标注来源");
  });

  it("keeps definitions, examples, misconceptions, app links and data guidance complete", () => {
    for (const learningModule of LEARNING_MODULES) {
      expect(learningModule.definition.length).toBeGreaterThan(40);
      expect(learningModule.formula.length).toBeGreaterThan(8);
      expect(learningModule.example.length).toBeGreaterThan(30);
      expect(learningModule.misconceptions.length).toBeGreaterThanOrEqual(3);
      expect(learningModule.links.length).toBeGreaterThanOrEqual(2);
      expect(learningModule.dataNote.length).toBeGreaterThan(30);
    }

    const html = renderToStaticMarkup(<LearnPage />);
    expect(html.match(/aria-label="[^"]*数据与合规提示"/g)).toHaveLength(5);
    expect(html).toContain("小例子 / 公式");
    expect(html).toContain("常见误区");
    expect(html).toContain("在本应用查看");
    expect(html).toContain('href="/funds"');
    expect(html).toContain('href="/compare"');
    expect(html).toContain('href="/portfolio"');
    expect(html).toContain('href="/backtest"');
  });

  it("shows the centralized disclaimer and avoids prohibited trading or return promises", () => {
    const html = renderToStaticMarkup(<LearnPage />);

    expect(html).toContain(COMPLIANCE_DISCLAIMER);
    expect(html).toContain("不构成投资建议");
    expect(html).not.toMatch(/必须买入|立即卖出|保证赚钱|未来会获得收益/);
  });
});
