export function EmptyState({ title, description }: { title: string; description: string }) {
  return (
    <div className="rounded-md border border-dashed border-[var(--border)] bg-[var(--surface)] p-6 text-center">
      <div className="text-sm font-semibold">{title}</div>
      <div className="mt-1 text-sm text-[var(--text-muted)]">{description}</div>
    </div>
  );
}
