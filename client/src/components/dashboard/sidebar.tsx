"use client";

import { Activity, FileCheck2, FolderOpen, LayoutDashboard, Settings2, Upload } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

type SidebarLink = { label: string; href: string; Icon: LucideIcon };

export const SIDEBAR_LINKS: SidebarLink[] = [
    { label: "Overview", href: "/dashboard", Icon: LayoutDashboard },
    { label: "Cases", href: "/dashboard/cases", Icon: FolderOpen },
    { label: "Acquisition", href: "/dashboard/acquisition", Icon: Upload },
    { label: "Analysis", href: "/dashboard/analysis", Icon: Activity },
    { label: "Reports", href: "/dashboard/reports", Icon: FileCheck2 },
    { label: "Settings", href: "/dashboard/settings", Icon: Settings2 },
];

export default function Sidebar() {
    const pathname = usePathname();

    return (
        <aside className="border-b border-(--border-color) bg-(--surface-color) lg:sticky lg:top-16 lg:h-[calc(100vh-4rem)] lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r">
            <div className="flex h-full flex-col px-4 py-5">
                <p className="px-3 font-mono text-[10px] font-semibold uppercase tracking-[.18em] text-(--muted-text-color)">Workspace</p>
                <nav aria-label="Dashboard navigation" className="mt-3 grid grid-cols-2 gap-1 sm:grid-cols-3 lg:block lg:space-y-1">
                    {SIDEBAR_LINKS.map(({ label, href, Icon }) => {
                        const active = pathname === href;
                        return <Link aria-current={active ? "page" : undefined} className={`flex items-center gap-3 px-3 py-2.5 text-sm font-semibold transition-colors ${active ? "bg-(--surface-strong-color) text-(--primary-text-color)" : "text-(--secondary-text-color) hover:bg-(--surface-muted-color) hover:text-(--primary-text-color)"}`} href={href} key={href}><Icon aria-hidden="true" className={`size-4 ${active ? "text-(--primary-color)" : "text-(--muted-text-color)"}`} />{label}</Link>;
                    })}
                </nav>
                <div className="mt-auto hidden border-t border-(--border-color) px-3 pt-5 lg:block"><p className="font-mono text-[10px] uppercase tracking-[.16em] text-(--muted-text-color)">Evidence mode</p><p className="mt-2 flex items-center gap-2 text-sm font-semibold"><span className="size-2 rounded-full bg-(--success-color)" />Integrity ready</p></div>
            </div>
        </aside>
    );
}
