import { mkdirSync, writeFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { expect, test, type Page, type TestInfo } from "@playwright/test";

const disclaimer = "本工具基于历史数据，仅供分析学习，不构成投资建议。历史表现不预示未来收益。";
const aiDisclaimer = "AI 输出仅供分析学习，不构成投资建议；无法替代持牌机构的适当性意见。";
const visualReportPath = resolve(__dirname, "../../../output/playwright/real-api-visual-check.json");

type VisualResult = {
  name: string;
  path: string;
  viewportWidth: number;
  bodyScrollWidth: number;
  documentScrollWidth: number;
  overflowingElements: Array<{
    tag: string;
    className: string;
    clientWidth: number;
    scrollWidth: number;
    text: string;
  }>;
  canvases: Array<{
    width: number;
    height: number;
    clientWidth: number;
    clientHeight: number;
  }>;
};

async function expectProvenance(page: Page) {
  await expect(page.getByText("数据来源：sample_local").first()).toBeVisible();
  await expect(page.getByText(/数据更新时间：(?!暂无数据|状态不可用|日期不可用).+/).first()).toBeVisible();
}

async function measurePage(page: Page, name: string): Promise<VisualResult> {
  return page.evaluate((pageName) => {
    const overflowingElements = Array.from(document.querySelectorAll<HTMLElement>("body *"))
      .filter((element) => {
        const style = getComputedStyle(element);
        return (
          !["INPUT", "SELECT", "TEXTAREA"].includes(element.tagName)
          && !element.classList.contains("sr-only")
          && style.display !== "inline"
          && element.scrollWidth > element.clientWidth + 1
          && style.overflowX !== "auto"
        );
      })
      .slice(0, 10)
      .map((element) => ({
        tag: element.tagName.toLowerCase(),
        className: element.getAttribute("class") ?? "",
        clientWidth: element.clientWidth,
        scrollWidth: element.scrollWidth,
        text: (element.textContent ?? "").trim().slice(0, 40)
      }));
    const canvases = Array.from(document.querySelectorAll("canvas")).map((canvas) => ({
      width: canvas.width,
      height: canvas.height,
      clientWidth: canvas.clientWidth,
      clientHeight: canvas.clientHeight
    }));

    return {
      name: pageName,
      path: window.location.pathname,
      viewportWidth: document.documentElement.clientWidth,
      bodyScrollWidth: document.body.scrollWidth,
      documentScrollWidth: document.documentElement.scrollWidth,
      overflowingElements,
      canvases
    };
  }, name);
}

function writeVisualReport(results: VisualResult[], viewport: { width: number; height: number }) {
  const failures = results
    .filter((result) => (
      result.bodyScrollWidth > result.viewportWidth
      || result.documentScrollWidth > result.viewportWidth
      || result.overflowingElements.length > 0
    ))
    .map((result) => result.name);
  const chartNames = new Set(["portfolio", "backtestResult"]);
  const chartFailures = results
    .filter((result) => chartNames.has(result.name))
    .filter((result) => !result.canvases.some((canvas) => canvas.width > 0 && canvas.height > 0))
    .map((result) => result.name);
  const report = {
    schema_version: 1,
    ok: failures.length === 0 && chartFailures.length === 0,
    viewport,
    failures,
    chartFailures,
    results
  };

  mkdirSync(dirname(visualReportPath), { recursive: true });
  writeFileSync(visualReportPath, `${JSON.stringify(report, null, 2)}\n`, "utf8");
  return report;
}

function shouldWriteVisualReport(testInfo: TestInfo) {
  return testInfo.project.name === "real-api-chromium";
}

test("fund, portfolio, backtest, and AI use the seeded API with compliance context", async ({ page }, testInfo) => {
  test.setTimeout(120_000);
  const consoleErrors: string[] = [];
  page.on("console", (message) => {
    if (message.type() === "error") consoleErrors.push(message.text());
  });
  page.on("pageerror", (error) => consoleErrors.push(error.message));
  const visualResults: VisualResult[] = [];

  await page.goto("/funds");
  await expect(page).toHaveTitle(/基金/);
  await expect(page.getByRole("heading", { name: "基金筛选" })).toBeVisible();
  await expect(page.getByRole("button", { name: /稳健成长混合 A/ })).toBeVisible();
  await expect(page.getByRole("heading", { name: "稳健成长混合 A" })).toBeVisible();
  await expect(page.getByText(/sample_local ·/).first()).toBeVisible();
  await expect(page.getByText(disclaimer).first()).toBeVisible();
  await expectProvenance(page);
  visualResults.push(await measurePage(page, "fund"));

  await page.goto("/portfolio");
  await expect(page.getByRole("heading", { name: "组合管理" })).toBeVisible();
  await page.getByLabel("名称", { exact: true }).fill("真实 API 合规组合");
  await page.getByRole("button", { name: "创建" }).click();
  await expect(page.getByRole("heading", { name: "再平衡预览" })).toBeVisible();
  await page.getByRole("button", { name: "保存持仓" }).click();
  await expect(page.locator("canvas")).toBeVisible();
  await expect(page.getByText(disclaimer).first()).toBeVisible();
  await expectProvenance(page);
  visualResults.push(await measurePage(page, "portfolio"));

  await page.goto("/backtest");
  await expect(page.getByRole("heading", { name: "回测学习" })).toBeVisible();
  await page.getByRole("button", { name: "运行回测" }).click();
  await expect(page.getByText("组合与基准收益曲线")).toBeVisible();
  await expect(page.locator("canvas")).toBeVisible();
  await page.getByRole("button", { name: "解释本次回测" }).click();
  await expect(page.getByText("引用与数据来源")).toBeVisible();
  await expect(page.getByText(/数据日期：\d{4}-\d{2}-\d{2}/)).toBeVisible();
  await expect(page.getByText(aiDisclaimer)).toBeVisible();
  await expect(page.getByText(disclaimer).first()).toBeVisible();
  await expectProvenance(page);
  visualResults.push(await measurePage(page, "backtestResult"));

  await page.goto("/assistant");
  await expect(page.getByRole("heading", { name: "AI 分析助手" })).toBeVisible();
  await page.getByRole("button", { name: "发送" }).click();
  await expect(page.getByText("数据依据")).toBeVisible();
  await expect(page.getByText("funds:000001")).toBeVisible();
  await expect(page.getByText(/数据日期：\d{4}-\d{2}-\d{2}/)).toBeVisible();
  await expect(page.getByText(aiDisclaimer)).toBeVisible();
  await expect(page.getByText(disclaimer).first()).toBeVisible();
  await expectProvenance(page);
  visualResults.push(await measurePage(page, "assistant"));

  await page.goto("/settings");
  await expect(page.getByRole("heading", { name: "设置" })).toBeVisible();
  await expect(page.getByText("启用状态：已停用")).toBeVisible();
  // The runtime contract is configured in minutes (defaults to 5); keep the
  // assertion tied to the rendered interval shape rather than an obsolete
  // 24-hour fixture from the earlier scheduler contract.
  await expect(page.getByText(/interval · every \d+ minute\(s\)/)).toBeVisible();
  await expect(page.getByText("运行中任务：无")).toBeVisible();

  for (const result of visualResults) {
    expect(result.bodyScrollWidth, `${testInfo.project.name}:${result.name} body overflow`).toBeLessThanOrEqual(result.viewportWidth);
    expect(result.documentScrollWidth, `${testInfo.project.name}:${result.name} document overflow`).toBeLessThanOrEqual(result.viewportWidth);
    expect(result.overflowingElements, `${testInfo.project.name}:${result.name} overflowing elements`).toEqual([]);
  }
  for (const result of visualResults.filter((item) => ["portfolio", "backtestResult"].includes(item.name))) {
    expect(
      result.canvases.some((canvas) => canvas.width > 0 && canvas.height > 0),
      `${testInfo.project.name}:${result.name} canvas`,
    ).toBe(true);
  }
  if (shouldWriteVisualReport(testInfo)) {
    const viewport = page.viewportSize() ?? { width: 1280, height: 720 };
    const visualReport = writeVisualReport(visualResults, viewport);
    expect(visualReport.failures).toEqual([]);
    expect(visualReport.chartFailures).toEqual([]);
  }
  expect(consoleErrors).toEqual([]);
});
