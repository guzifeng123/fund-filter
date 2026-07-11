import type { Metadata } from "next";
import "@/styles/globals.css";
import { AppShell } from "@/components/app-shell";
import { QueryProvider } from "@/components/query-provider";

export const metadata: Metadata = {
  title: "基金分析工作台",
  description: "个人自用的基金分析与闲钱管理 Web 应用"
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="zh-CN">
      <body>
        <QueryProvider>
          <AppShell>{children}</AppShell>
        </QueryProvider>
      </body>
    </html>
  );
}
