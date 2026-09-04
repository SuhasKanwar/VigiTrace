import type { ReactNode } from "react";
import { ShieldCheck } from "lucide-react";

type StatusScreenProps = {
    eyebrow: string;
    title: string;
    description: string;
    children?: ReactNode;
    action?: ReactNode;
    icon?: ReactNode;
};

export default function StatusScreen({
    eyebrow,
    title,
    description,
    children,
    action,
    icon,
} : StatusScreenProps) {
    return (
        <main className="flex min-h-screen flex-1 items-center justify-center px-5 py-10">
            <section className="animate-screen-enter w-full max-w-xl rounded-3xl border border-(--border-color) bg-(--surface-color)/90 p-8 shadow-[0_24px_70px_var(--shadow-color)] backdrop-blur sm:p-10">
                <div className="flex items-center gap-3 text-sm font-semibold tracking-tight">
                    <span className="grid size-10 place-items-center rounded-xl bg-(--primary-color) text-white shadow-[0_8px_24px_var(--glow-color)]">{icon ?? <ShieldCheck aria-hidden="true" className="size-5" />}</span>
                    <span>VigiTrace</span>
                </div>
                <div className="mt-12">
                    <p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">{eyebrow}</p>
                    <h1 className="mt-3 text-3xl font-semibold tracking-tight sm:text-4xl">{title}</h1>
                    <p className="mt-4 max-w-md text-base leading-7 text-(--secondary-text-color)">{description}</p>
                </div>
                {children ? <div className="mt-6">{children}</div> : null}
                {action ? <div className="mt-8 flex flex-wrap gap-3">{action}</div> : null}
            </section>
        </main>
    );
}
