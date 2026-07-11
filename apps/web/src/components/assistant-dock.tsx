import Link from "next/link";
import { Bot } from "lucide-react";

export function AssistantDock() {
  return (
    <Link
      href="/assistant"
      className="focus-ring fixed bottom-5 right-5 z-30 hidden h-11 items-center gap-2 rounded-md bg-[var(--accent)] px-4 text-sm font-medium text-white shadow-lg lg:inline-flex"
    >
      <Bot className="h-4 w-4" />
      AI 助手
    </Link>
  );
}
