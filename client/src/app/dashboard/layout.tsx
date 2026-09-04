import type { ReactNode } from "react";
import Sidebar from "@/components/dashboard/sidebar";

export default function DashboardLayout({ children }: { children: ReactNode }) {
  return <div className="flex min-h-[calc(100vh-4rem)] flex-col bg-(--primary-bg-color) lg:flex-row"><Sidebar /><main className="min-w-0 flex-1">{children}</main></div>;
}
