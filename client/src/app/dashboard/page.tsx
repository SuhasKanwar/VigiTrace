import { Activity, FileCheck2, FolderOpen } from "lucide-react";
import { redirect } from "next/navigation";
import Logo from "@/components/ui/logo";
import SignOutButton from "@/components/auth/sign-out-button";
import { getAuthSession } from "@/lib/session";

export default async function DashboardPage() {
    const session = await getAuthSession();
    if (!session) redirect("/auth/signin");

    return (
        <main className="min-h-screen bg-(--primary-bg-color)">
            <header className="border-b border-(--border-color) bg-(--surface-color)"><div className="mx-auto flex max-w-7xl items-center justify-between px-5 py-4 lg:px-8"><Logo /><SignOutButton /></div></header>
            <div className="mx-auto max-w-7xl px-5 py-14 lg:px-8">
                <p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">Evidence workspace</p>
                <div className="mt-4 flex flex-col justify-between gap-5 sm:flex-row sm:items-end"><div><h1 className="text-4xl font-bold tracking-[-.045em] sm:text-5xl">Welcome, {session.user.name?.split(" ")[0] ?? "Investigator"}.</h1><p className="mt-4 text-(--secondary-text-color)">Your forensic workspace is ready for the next case.</p></div><button className="inline-flex items-center justify-center gap-2 bg-(--primary-color) px-5 py-3 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color)" type="button"><FolderOpen aria-hidden="true" className="size-4" />Create case</button></div>
                <section className="mt-12 grid gap-5 md:grid-cols-3">{[{ label: "Open cases", value: "0", detail: "No active acquisitions", Icon: FolderOpen }, { label: "Evidence verified", value: "0", detail: "Integrity checks will appear here", Icon: FileCheck2 }, { label: "Review events", value: "0", detail: "Analytics results will appear here", Icon: Activity }].map(({ label, value, detail, Icon }) => <article className="border border-(--border-color) bg-(--surface-color) p-6" key={label}><div className="flex items-start justify-between"><p className="text-sm font-semibold text-(--secondary-text-color)">{label}</p><Icon aria-hidden="true" className="size-5 text-(--primary-color)" /></div><p className="mt-8 text-4xl font-bold tracking-tight">{value}</p><p className="mt-2 text-sm text-(--muted-text-color)">{detail}</p></article>)}</section>
                <section className="mt-8 border border-dashed border-(--border-color) bg-(--surface-color) px-6 py-16 text-center"><FolderOpen aria-hidden="true" className="mx-auto size-8 text-(--primary-color)" /><h2 className="mt-5 text-xl font-bold">No evidence cases yet</h2><p className="mx-auto mt-2 max-w-md text-sm leading-6 text-(--secondary-text-color)">Create a case to begin tracking acquisition, recovery, analysis, and chain of custody.</p></section>
            </div>
        </main>
    );
}
