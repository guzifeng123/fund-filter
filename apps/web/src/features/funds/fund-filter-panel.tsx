"use client";

import { Check, RotateCcw } from "lucide-react";
import { Button } from "@/components/button";
import { Input } from "@/components/form-field";
import type { Fund } from "@/lib/api/types";
import { RISK_PROFILE_LIMITS, type RiskProfile } from "@/lib/compliance/constants";
import {
  areFundFilterCriteriaEqual,
  createDefaultFundFilterCriteria,
  type FundFilterCriteria,
  validateFundFilterCriteria
} from "@/features/funds/fund-filter-model";

const fundTypeOptions: Array<{ value: Fund["fund_type"]; label: string }> = [
  { value: "stock", label: "股票型" },
  { value: "mixed", label: "混合型" },
  { value: "bond", label: "债券型" },
  { value: "money", label: "货币型" }
];

function FilterStep({
  index,
  title,
  description,
  children
}: {
  index: number;
  title: string;
  description: string;
  children: React.ReactNode;
}) {
  return (
    <fieldset className="border-t border-[var(--border)] py-4 first:border-t-0 first:pt-0">
      <legend className="sr-only">第 {index} 步：{title}</legend>
      <div className="mb-3">
        <div className="text-xs text-[var(--text-muted)]">Step {index}</div>
        <div className="mt-1 text-sm font-semibold">{title}</div>
        <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">{description}</p>
      </div>
      <div className="grid gap-3">{children}</div>
    </fieldset>
  );
}

function NumberFilterField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  suffix
}: {
  label: string;
  value: number;
  onChange: (value: number) => void;
  min?: number;
  max?: number;
  step?: number;
  suffix?: string;
}) {
  return (
    <label className="grid min-w-0 gap-1 text-xs text-[var(--text-muted)]">
      {label}
      <span className="flex h-9 min-w-0 items-center rounded-md border border-[var(--border)] bg-[var(--background)] px-2 focus-within:border-[var(--accent)]">
        <Input
          variant="unstyled"
          className="w-0 min-w-0 flex-1 bg-transparent text-sm text-[var(--text)] outline-none"
          type="number"
          value={value}
          min={min}
          max={max}
          step={step}
          onChange={(event) => onChange(Number(event.currentTarget.value))}
        />
        {suffix ? <span className="ml-1 shrink-0">{suffix}</span> : null}
      </span>
    </label>
  );
}

export function FundFilterPanel({
  riskProfile,
  usesDefaultRiskProfile,
  value,
  appliedValue,
  onChange,
  onApply,
  onReset
}: {
  riskProfile: RiskProfile;
  usesDefaultRiskProfile: boolean;
  value: FundFilterCriteria;
  appliedValue: FundFilterCriteria;
  onChange: (value: FundFilterCriteria) => void;
  onApply: () => void;
  onReset: () => void;
}) {
  const validationMessage = validateFundFilterCriteria(value);
  const isDirty = !areFundFilterCriteriaEqual(value, appliedValue);
  const defaults = createDefaultFundFilterCriteria();
  const isDefault = areFundFilterCriteriaEqual(value, defaults)
    && areFundFilterCriteriaEqual(appliedValue, defaults);

  function updateFundType(fundType: Fund["fund_type"]) {
    const fundTypes = value.fund_types.includes(fundType)
      ? value.fund_types.filter((item) => item !== fundType)
      : [...value.fund_types, fundType];
    onChange({ ...value, fund_types: fundTypes });
  }

  function updateSize(index: 0 | 1, nextValue: number) {
    const sizeRange: [number, number] = [...value.size_range];
    sizeRange[index] = nextValue;
    onChange({ ...value, size_range: sizeRange });
  }

  return (
    <aside className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-3" aria-label="四步基金筛选器">
      <div className="mb-3 flex items-start justify-between gap-3">
        <div>
          <h2 className="text-sm font-semibold">四步筛选器</h2>
          <p className="mt-1 text-xs leading-5 text-[var(--text-muted)]">修改条件后点击“应用筛选”更新推荐结果。</p>
        </div>
        {isDirty ? <span className="shrink-0 rounded-md bg-[var(--accent-weak)] px-2 py-1 text-xs text-[var(--accent)]">待应用</span> : null}
      </div>

      <FilterStep index={1} title="基础条件" description="风险画像只读，推荐结果不会超过当前承受等级。">
        <div className="rounded-md border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-xs">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[var(--text-muted)]">风险画像基线</span>
            <strong>{riskProfile}</strong>
          </div>
          <p className="mt-1 leading-5 text-[var(--text-muted)]">
            可匹配 {RISK_PROFILE_LIMITS[riskProfile].join("-")}；{usesDefaultRiskProfile ? "尚无有效测评，临时使用 C3。" : "来自最新有效测评，不可在此修改。"}
          </p>
        </div>
        <div>
          <div className="mb-2 text-xs text-[var(--text-muted)]">基金类型</div>
          <div className="grid grid-cols-2 gap-2">
            {fundTypeOptions.map((option) => {
              const selected = value.fund_types.includes(option.value);
              return (
                <Button
                  key={option.value}
                  variant="unstyled"
                  size="none"
                  aria-pressed={selected}
                  className={`inline-flex min-h-9 items-center justify-center gap-1.5 rounded-md border px-2 text-xs ${selected ? "border-[var(--accent)] bg-[var(--accent-weak)] text-[var(--text)]" : "border-[var(--border)] bg-[var(--background)] text-[var(--text-muted)]"}`}
                  onClick={() => updateFundType(option.value)}
                >
                  {selected ? <Check className="h-3.5 w-3.5" /> : null}
                  {option.label}
                </Button>
              );
            })}
          </div>
        </div>
        <div className="grid grid-cols-2 gap-2">
          <NumberFilterField label="规模下限" value={value.size_range[0]} min={0} step={1} suffix="亿" onChange={(nextValue) => updateSize(0, nextValue)} />
          <NumberFilterField label="规模上限" value={value.size_range[1]} min={0} step={1} suffix="亿" onChange={(nextValue) => updateSize(1, nextValue)} />
        </div>
      </FilterStep>

      <FilterStep index={2} title="核心指标" description="用历史收益分位、回撤与风险调整后收益缩小范围。">
        <NumberFilterField
          label="收益排名前"
          value={value.return_rank_percentile}
          min={0}
          max={100}
          step={1}
          suffix="%"
          onChange={(returnRankPercentile) => onChange({ ...value, return_rank_percentile: returnRankPercentile })}
        />
        <NumberFilterField
          label="夏普比率下限"
          value={value.sharpe_gte}
          step={0.1}
          onChange={(sharpeGte) => onChange({ ...value, sharpe_gte: sharpeGte })}
        />
        <label className="flex items-start gap-2 rounded-md border border-[var(--border)] bg-[var(--background)] p-2 text-xs leading-5 text-[var(--text-muted)]">
          <Input
            variant="unstyled"
            className="mt-1 accent-[var(--accent)]"
            type="checkbox"
            checked={value.max_drawdown_lte_category_avg}
            onChange={(event) => onChange({ ...value, max_drawdown_lte_category_avg: event.currentTarget.checked })}
          />
          最大回撤不高于同类平均
        </label>
      </FilterStep>

      <FilterStep index={3} title="费用结构" description="管理费与托管费合计不超过设定上限。">
        <NumberFilterField
          label="费率合计上限"
          value={value.fee_lte}
          min={0}
          step={0.1}
          suffix="%"
          onChange={(feeLte) => onChange({ ...value, fee_lte: feeLte })}
        />
      </FilterStep>

      <FilterStep index={4} title="成立年限" description="优先保留具备足够历史区间的基金。">
        <NumberFilterField
          label="成立年限下限"
          value={value.min_years}
          min={0}
          step={1}
          suffix="年"
          onChange={(minimumYears) => onChange({ ...value, min_years: minimumYears })}
        />
      </FilterStep>

      {validationMessage ? <p className="mb-3 text-xs leading-5 text-[var(--danger)]" role="alert">{validationMessage}</p> : null}
      <div className="grid grid-cols-2 gap-2">
        <Button
          variant="unstyled"
          size="none"
          className="inline-flex h-9 items-center justify-center gap-1.5 rounded-md border border-[var(--border)] text-xs text-[var(--text-muted)]"
          disabled={isDefault}
          onClick={onReset}
        >
          <RotateCcw className="h-3.5 w-3.5" /> 重置默认
        </Button>
        <Button
          variant="unstyled"
          size="none"
          className="inline-flex h-9 items-center justify-center rounded-md bg-[var(--accent)] px-3 text-xs font-medium text-white"
          disabled={!isDirty || Boolean(validationMessage)}
          onClick={onApply}
        >
          应用筛选
        </Button>
      </div>
    </aside>
  );
}
