"use client";

import { useEffect, useRef } from "react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import {
  BarChart3,
  Bot,
  BriefcaseBusiness,
  FlaskConical,
  GraduationCap,
  LayoutDashboard,
  ListFilter,
  Settings,
  ShieldCheck,
  SlidersHorizontal
} from "lucide-react";
import { AssistantDock } from "@/components/assistant-dock";
import { DataProvenanceFooter } from "@/components/data-provenance-footer";

const navItems = [
  { href: "/dashboard", label: "首页", icon: LayoutDashboard },
  { href: "/risk-assessment", label: "风险测评", icon: ShieldCheck },
  { href: "/funds", label: "基金筛选", icon: ListFilter },
  { href: "/compare", label: "比较", icon: BarChart3 },
  { href: "/portfolio", label: "组合", icon: BriefcaseBusiness },
  { href: "/backtest", label: "回测", icon: FlaskConical },
  { href: "/assistant", label: "助手", icon: Bot },
  { href: "/learn", label: "学习", icon: GraduationCap },
  { href: "/settings", label: "设置", icon: Settings }
] as const;

const mobileNavScrollKey = "fund-workbench:mobile-nav-scroll-left";

export function isNavItemActive(pathname: string, href: string) {
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children }: { children: React.ReactNode }) {
  const pathname = usePathname();
  const mobileNavRef = useRef<HTMLElement>(null);
  const activeMobileLinkRef = useRef<HTMLAnchorElement>(null);

  useEffect(() => {
    const nav = mobileNavRef.current;
    if (!nav) return;

    const savedScrollLeft = Number(window.sessionStorage.getItem(mobileNavScrollKey));
    if (Number.isFinite(savedScrollLeft) && savedScrollLeft > 0) {
      nav.scrollLeft = savedScrollLeft;
    }

    window.requestAnimationFrame(() => {
      activeMobileLinkRef.current?.scrollIntoView({ block: "nearest", inline: "nearest" });
    });
  }, [pathname]);

  function rememberMobileNavScroll() {
    const nav = mobileNavRef.current;
    if (!nav) return;
    window.sessionStorage.setItem(mobileNavScrollKey, String(nav.scrollLeft));
  }

  return (
    <div className="min-h-screen">
      <aside className="fixed inset-y-0 left-0 hidden w-64 border-r border-[var(--border)] bg-[var(--surface)] lg:block">
        <div className="flex h-16 items-center gap-2 border-b border-[var(--border)] px-5">
          <SlidersHorizontal className="h-5 w-5 text-[var(--accent)]" />
          <div>
            <div className="text-sm font-semibold">基金分析工作台</div>
            <div className="text-xs text-[var(--text-muted)]">Personal v1</div>
          </div>
        </div>
        <nav className="grid gap-1 p-3">
          {navItems.map((item) => {
            const isActive = isNavItemActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={`focus-ring flex h-10 items-center gap-3 rounded-md px-3 text-sm transition hover:bg-[var(--surface-muted)] hover:text-[var(--text)] ${isActive ? "bg-[var(--surface-muted)] text-[var(--text)]" : "text-[var(--text-muted)]"}`}
              >
                <item.icon className="h-4 w-4" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </aside>
      <div className="sticky top-0 z-20 border-b border-[var(--border)] bg-[var(--surface)] lg:hidden">
        <header className="flex h-12 items-center justify-between px-4">
          <span className="text-sm font-semibold">基金分析工作台</span>
          <Link href="/assistant" className="focus-ring rounded-md p-2" aria-label="打开 AI 助手">
            <Bot className="h-4 w-4" />
          </Link>
        </header>
        <nav
          ref={mobileNavRef}
          className="flex h-12 gap-1 overflow-x-auto px-2 pb-2"
          aria-label="移动端主导航"
          onScroll={rememberMobileNavScroll}
        >
          {navItems.map((item) => {
            const isActive = isNavItemActive(pathname, item.href);
            return (
              <Link
                key={item.href}
                ref={isActive ? activeMobileLinkRef : undefined}
                href={item.href}
                aria-current={isActive ? "page" : undefined}
                className={`focus-ring flex min-w-20 shrink-0 items-center justify-center gap-1.5 rounded-md px-2 text-xs hover:bg-[var(--surface-muted)] hover:text-[var(--text)] ${isActive ? "bg-[var(--surface-muted)] text-[var(--text)]" : "text-[var(--text-muted)]"}`}
              >
                <item.icon className="h-3.5 w-3.5 shrink-0" />
                {item.label}
              </Link>
            );
          })}
        </nav>
      </div>
      <main className="lg:pl-64">
        <div className="mx-auto w-full max-w-[1500px] px-4 py-5 lg:px-6">{children}</div>
        <DataProvenanceFooter />
      </main>
      <AssistantDock />
    </div>
  );
}
