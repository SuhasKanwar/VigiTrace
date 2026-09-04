"use client";

import { Activity, FileCheck2, FolderOpen, HardDrive, LayoutDashboard, Settings2, Upload } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";

/**
 * `available: false` marks a destination the platform does not implement yet.
 *
 * These render as inert, visibly-pending items rather than links. Previously
 * they were real `<Link>`s to routes that do not exist, so Next.js prefetched
 * each one on every dashboard render and the app fired a 404 per item — and a
 * user clicking one landed on the not-found page. An evidence tool should not
 * advertise capabilities it does not have.
 */
type SidebarLink = { label: string; href: string; Icon: LucideIcon; available: boolean };

export const SIDEBAR_LINKS: SidebarLink[] = [
    { label: "Overview", href: "/dashboard", Icon: LayoutDashboard, available: true },
    { label: "Devices", href: "/dashboard/devices", Icon: HardDrive, available: true },
    { label: "Cases", href: "/dashboard/cases", Icon: FolderOpen, available: false },
    { label: "Acquisition", href: "/dashboard/acquisition", Icon: Upload, available: false },
    { label: "Analysis", href: "/dashboard/analysis", Icon: Activity, available: false },
    { label: "Reports", href: "/dashboard/reports", Icon: FileCheck2, available: false },
    { label: "Settings", href: "/dashboard/settings", Icon: Settings2, available: false },
];

export const AVAILABLE_SIDEBAR_LINKS = SIDEBAR_LINKS.filter((link) => link.available);

const BASE_ITEM = "flex items-center gap-3 px-3 py-2.5 text-sm font-semibold transition-colors";

export default function Sidebar() {
    const pathname = usePathname();

    return (
        <aside className="border-b border-(--border-color) bg-(--surface-color) lg:sticky lg:top-16 lg:h-[calc(100vh-4rem)] lg:w-64 lg:shrink-0 lg:border-b-0 lg:border-r">
            <div className="flex h-full flex-col px-4 py-5">
                <p className="px-3 font-mono text-[10px] font-semibold uppercase tracking-[.18em] text-(--muted-text-color)">Workspace</p>
                <nav aria-label="Dashboard navigation" className="mt-3 grid grid-cols-2 gap-1 sm:grid-cols-3 lg:block lg:space-y-1">
                    {SIDEBAR_LINKS.map(({ label, href, Icon, available }) => {
                        const active = pathname === href || (href !== "/dashboard" && pathname.startsWith(`${href}/`));

                        if (!available) {
                            return (
                                <span
                                    aria-disabled="true"
                                    className={`${BASE_ITEM} cursor-not-allowed text-(--muted-text-color)`}
                                    key={href}
                                    title={`${label} is not implemented yet.`}
                                >
                                    <Icon aria-hidden="true" className="size-4 text-(--muted-text-color)" />
                                    {label}
                                    <span className="ml-auto font-mono text-[9px] uppercase tracking-[.16em] text-(--muted-text-color)">Soon</span>
                                </span>
                            );
                        }

                        return (
                            <Link
                                aria-current={active ? "page" : undefined}
                                className={`${BASE_ITEM} ${active ? "bg-(--surface-strong-color) text-(--primary-text-color)" : "text-(--secondary-text-color) hover:bg-(--surface-muted-color) hover:text-(--primary-text-color)"}`}
                                href={href}
                                key={href}
                            >
                                <Icon aria-hidden="true" className={`size-4 ${active ? "text-(--primary-color)" : "text-(--muted-text-color)"}`} />
                                {label}
                            </Link>
                        );
                    })}
                </nav>
                <div className="mt-auto hidden border-t border-(--border-color) px-3 pt-5 lg:block"><p className="font-mono text-[10px] uppercase tracking-[.16em] text-(--muted-text-color)">Evidence mode</p><p className="mt-2 flex items-center gap-2 text-sm font-semibold"><span className="size-2 rounded-full bg-(--success-color)" />Integrity ready</p></div>
            </div>
        </aside>
    );
}
