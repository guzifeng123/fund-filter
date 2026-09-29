import { ShieldAlert } from "lucide-react";
import { COMPLIANCE_DISCLAIMER } from "@/lib/compliance/constants";

export function ComplianceNotice({ children }: { children?: React.ReactNode }) {
  const hasContext = children !== undefined && children !== null;

  return (
    <div className="flex gap-2 rounded-md border border-[var(--border)] bg-[var(--surface-muted)] p-3 text-xs leading-5 text-[var(--text-muted)]">
      <ShieldAlert className="mt-0.5 h-4 w-4 shrink-0 text-[var(--accent)]" />
      <div>
        {hasContext ? <div>{children}</div> : null}
        <div className={hasContext ? "mt-1" : undefined}>{COMPLIANCE_DISCLAIMER}</div>
      </div>
    </div>
  );
}
