import type { ReactNode } from "react";
import Logo from "@/components/ui/logo";

type StatusScreenProps = {
    eyebrow: string;
    title: string;
    description: string;
    children?: ReactNode;
    action?: ReactNode;
    icon?: ReactNode;
    /** Renders the card on its own, for use inside a page that already owns `<main>` and its heading. */
    embedded?: boolean;
};

export default function StatusScreen({
    eyebrow,
    title,
    description,
    children,
    action,
    icon,
    embedded = false,
} : StatusScreenProps) {
    const Heading = embedded ? "h2" : "h1";
    const card = (
        <section className={`animate-screen-enter w-full border border-(--border-color) border-l-4 border-l-(--primary-color) bg-(--surface-color) p-8 sm:p-10 ${embedded ? "" : "max-w-xl"}`}>
            {embedded ? null : <Logo />}
            <div className={embedded ? "" : "mt-12"}>
                {icon ? <span className="mb-7 grid size-10 place-items-center bg-(--surface-strong-color) text-(--primary-color)">{icon}</span> : null}
                <p className="font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)">{eyebrow}</p>
                <Heading className={`mt-3 font-semibold tracking-tight ${embedded ? "text-2xl sm:text-3xl" : "text-3xl sm:text-4xl"}`}>{title}</Heading>
                <p className="mt-4 max-w-md text-base leading-7 text-(--secondary-text-color)">{description}</p>
            </div>
            {children ? <div className="mt-6">{children}</div> : null}
            {action ? <div className="mt-8 flex flex-wrap gap-3">{action}</div> : null}
        </section>
    );

    if (embedded) return card;

    return <main className="flex min-h-screen flex-1 items-center justify-center px-5 py-10">{card}</main>;
}
