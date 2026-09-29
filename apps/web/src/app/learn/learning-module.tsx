import Link from "next/link";
import { ArrowUpRight, BookOpen, Calculator, CircleAlert, Database } from "lucide-react";
import type { LearningGlossaryItem, LearningModuleContent } from "@/app/learn/learning-content";

export function LearningModule({ module, index }: { module: LearningModuleContent; index: number }) {
  const titleId = `${module.id}-title`;

  return (
    <article
      id={module.id}
      aria-labelledby={titleId}
      className="scroll-mt-24 rounded-md border border-[var(--border)] bg-[var(--surface)] p-4 sm:p-5"
    >
      <header className="border-b border-[var(--border)] pb-4">
        <div className="text-xs text-[var(--text-muted)]">学习模块 {index}</div>
        <h2 id={titleId} className="mt-1 text-xl font-semibold">{module.title}</h2>
        <p className="mt-2 text-sm leading-6 text-[var(--text-muted)]">{module.summary}</p>
      </header>

      <div className="mt-4 grid gap-5">
        <section aria-labelledby={`${module.id}-definition`}>
          <h3 id={`${module.id}-definition`} className="flex items-center gap-2 text-sm font-semibold">
            <BookOpen aria-hidden="true" className="h-4 w-4 text-[var(--accent)]" /> 定义
          </h3>
          <p className="mt-2 text-sm leading-7 text-[var(--text-muted)]">{module.definition}</p>
        </section>

        <section aria-labelledby={`${module.id}-example`}>
          <h3 id={`${module.id}-example`} className="flex items-center gap-2 text-sm font-semibold">
            <Calculator aria-hidden="true" className="h-4 w-4 text-[var(--accent)]" /> 小例子 / 公式
          </h3>
          <div className="mt-2 rounded-md bg-[var(--surface-muted)] p-3">
            <code className="block overflow-x-auto whitespace-nowrap text-xs font-semibold text-[var(--text)]">{module.formula}</code>
            <p className="mt-2 text-sm leading-7 text-[var(--text-muted)]">{module.example}</p>
          </div>
        </section>

        <section aria-labelledby={`${module.id}-misconceptions`}>
          <h3 id={`${module.id}-misconceptions`} className="flex items-center gap-2 text-sm font-semibold">
            <CircleAlert aria-hidden="true" className="h-4 w-4 text-[var(--r3)]" /> 常见误区
          </h3>
          <ul className="mt-2 grid gap-2 text-sm leading-6 text-[var(--text-muted)]">
            {module.misconceptions.map((misconception) => (
              <li key={misconception} className="flex gap-2">
                <span aria-hidden="true" className="mt-2 h-1.5 w-1.5 shrink-0 rounded-full bg-[var(--r3)]" />
                <span>{misconception}</span>
              </li>
            ))}
          </ul>
        </section>

        <nav aria-label={`${module.title}在本应用查看入口`}>
          <h3 className="text-sm font-semibold">在本应用查看</h3>
          <div className="mt-2 grid gap-2 sm:grid-cols-2">
            {module.links.map((link) => (
              <Link
                key={`${module.id}-${link.href}`}
                href={link.href}
                className="focus-ring group rounded-md border border-[var(--border)] bg-[var(--background)] p-3 hover:border-[var(--accent)]"
              >
                <span className="flex items-center justify-between gap-2 text-sm font-medium">
                  {link.label}
                  <ArrowUpRight aria-hidden="true" className="h-4 w-4 shrink-0 text-[var(--text-muted)] group-hover:text-[var(--accent)]" />
                </span>
                <span className="mt-1 block text-xs leading-5 text-[var(--text-muted)]">{link.description}</span>
              </Link>
            ))}
          </div>
        </nav>

        <aside className="flex gap-2 border-l-2 border-[var(--accent)] pl-3 text-xs leading-6 text-[var(--text-muted)]" aria-label={`${module.title}数据与合规提示`}>
          <Database aria-hidden="true" className="mt-1 h-4 w-4 shrink-0 text-[var(--accent)]" />
          <div>
            <div className="font-semibold text-[var(--text)]">数据与合规提示</div>
            <p>{module.dataNote}</p>
          </div>
        </aside>
      </div>
    </article>
  );
}

export function LearningGlossary({
  modules,
  items
}: {
  modules: LearningModuleContent[];
  items: LearningGlossaryItem[];
}) {
  return (
    <aside className="grid h-fit gap-5 rounded-md border border-[var(--border)] bg-[var(--surface)] p-4 xl:sticky xl:top-5">
      <nav aria-labelledby="learning-directory-title">
        <h2 id="learning-directory-title" className="text-sm font-semibold">学习目录</h2>
        <ol className="mt-3 grid gap-1">
          {modules.map((module, index) => (
            <li key={module.id}>
              <a
                href={`#${module.id}`}
                className="focus-ring flex min-h-9 items-center gap-2 rounded-md px-2 text-sm text-[var(--text-muted)] hover:bg-[var(--surface-muted)] hover:text-[var(--text)]"
              >
                <span className="text-xs tabular-nums">{String(index + 1).padStart(2, "0")}</span>
                {module.title}
              </a>
            </li>
          ))}
        </ol>
      </nav>

      <section aria-labelledby="learning-glossary-title" className="border-t border-[var(--border)] pt-4">
        <h2 id="learning-glossary-title" className="text-sm font-semibold">快速术语表</h2>
        <dl className="mt-3 grid gap-3">
          {items.map((item) => (
            <div key={item.term}>
              <dt className="text-xs font-semibold text-[var(--text)]">{item.term}</dt>
              <dd className="mt-1 text-xs leading-5 text-[var(--text-muted)]">{item.definition}</dd>
            </div>
          ))}
        </dl>
      </section>
    </aside>
  );
}
