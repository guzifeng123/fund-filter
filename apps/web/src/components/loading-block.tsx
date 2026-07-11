export function LoadingBlock({ label = "加载中" }: { label?: string }) {
  return (
    <div className="grid min-h-32 place-items-center rounded-md border border-dashed border-[var(--border)] bg-[var(--surface)] text-sm text-[var(--text-muted)]">
      {label}
    </div>
  );
}
