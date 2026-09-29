import { renderToStaticMarkup } from "react-dom/server";
import { describe, expect, it } from "vitest";
import { Button } from "@/components/button";
import { FormField, Input, Select, Textarea } from "@/components/form-field";

describe("project form controls", () => {
  it("uses a non-submitting native button by default and remains keyboard focusable", () => {
    const html = renderToStaticMarkup(<Button>保存</Button>);

    expect(html).toContain('type="button"');
    expect(html).toContain("focus-ring");
    expect(html).not.toContain("tabindex=\"-1\"");
  });

  it("associates labels, help, and errors with an input", () => {
    const html = renderToStaticMarkup(
      <FormField
        id="fund-code"
        label="基金代码"
        description="请输入六位代码"
        error="代码格式不正确"
        required
      >
        <Input defaultValue="1" />
      </FormField>
    );

    expect(html).toContain('for="fund-code"');
    expect(html).toContain('id="fund-code"');
    expect(html).toContain('aria-describedby="fund-code-description fund-code-error"');
    expect(html).toContain('aria-invalid="true"');
    expect(html).toContain('role="alert"');
  });

  it("associates a native select with the same field contract", () => {
    const html = renderToStaticMarkup(
      <FormField id="strategy" label="策略">
        <Select defaultValue="monthly">
          <option value="monthly">每月定投</option>
        </Select>
      </FormField>
    );

    expect(html).toContain('for="strategy"');
    expect(html).toContain('<select id="strategy"');
    expect(html).not.toContain("tabindex=\"-1\"");
  });

  it("associates a textarea with its label and description", () => {
    const html = renderToStaticMarkup(
      <FormField id="assistant-message" label="问题" description="请输入要分析的问题">
        <Textarea defaultValue="解释最大回撤" />
      </FormField>
    );

    expect(html).toContain('for="assistant-message"');
    expect(html).toContain('<textarea id="assistant-message"');
    expect(html).toContain('aria-describedby="assistant-message-description"');
  });
});
