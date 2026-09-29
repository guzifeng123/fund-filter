export type SettingsStatusLabel = "已配置" | "未配置" | "手动维护" | "未实现";

const statusClasses: Record<SettingsStatusLabel, string> = {
  已配置: "border-[var(--accent)] text-[var(--accent)]",
  未配置: "border-[var(--r3)] text-[var(--r4)]",
  手动维护: "border-[var(--border)] text-[var(--text-muted)]",
  未实现: "border-[var(--border)] text-[var(--text-muted)]"
};

export function SettingsStatusCard({
  title,
  status,
  description,
  action
}: {
  title: string;
  status: SettingsStatusLabel;
  description: string;
  action: string;
}) {
  return (
    <section className="rounded-md border border-[var(--border)] bg-[var(--surface)] p-4">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <h2 className="text-base font-semibold">{title}</h2>
        <span className={`rounded-md border px-2 py-1 text-xs font-medium ${statusClasses[status]}`}>
          {status}
        </span>
      </div>
      <p className="mt-3 text-sm leading-6 text-[var(--text-muted)]">{description}</p>
      <p className="mt-2 text-xs leading-5 text-[var(--text-muted)]">操作：{action}</p>
    </section>
  );
}
