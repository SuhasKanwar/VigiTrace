import { LoaderCircle, RotateCcw, TriangleAlert } from "lucide-react";
import type { LucideIcon } from "lucide-react";
import type { ReactNode } from "react";
import StatusScreen from "@/components/ui/status-screen";
import { EMPTY_VALUE } from "@/lib/devices/format";

export const BUTTON = {
    primary: "inline-flex items-center gap-2 bg-(--primary-color) px-5 py-3 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color) disabled:cursor-not-allowed disabled:opacity-60",
    secondary: "inline-flex items-center gap-2 border border-(--border-color) px-5 py-3 text-sm font-semibold transition-colors hover:bg-(--surface-muted-color) disabled:cursor-not-allowed disabled:opacity-60",
    danger: "inline-flex items-center gap-2 border border-(--danger-color) px-5 py-3 text-sm font-semibold text-(--danger-color) transition-colors hover:bg-(--surface-muted-color) disabled:cursor-not-allowed disabled:opacity-60",
    ghost: "inline-flex items-center gap-2 px-3 py-2 text-sm font-semibold text-(--secondary-text-color) transition-colors hover:bg-(--surface-muted-color) hover:text-(--primary-text-color) disabled:cursor-not-allowed disabled:opacity-60",
} as const;

export const EYEBROW = "font-mono text-xs font-semibold uppercase tracking-[.18em] text-(--primary-color)";
export const EYEBROW_MUTED = "font-mono text-[10px] font-semibold uppercase tracking-[.16em] text-(--muted-text-color)";
export const TABLE_HEAD = "border-b border-(--border-color) px-4 py-3 text-left font-mono text-[10px] font-semibold uppercase tracking-[.16em] text-(--muted-text-color)";
export const TABLE_CELL = "border-b border-(--border-color) px-4 py-3 align-top";

export function PageShell({ children }: { children: ReactNode }) {
    return <div className="mx-auto w-full max-w-6xl px-5 py-10 lg:px-8 lg:py-12">{children}</div>;
}

export function PageHeader({ eyebrow, title, description, actions }: { eyebrow: string; title: string; description?: string; actions?: ReactNode }) {
    return (
        <header className="flex flex-col gap-6 border-b border-(--border-color) pb-8 lg:flex-row lg:items-end lg:justify-between">
            <div className="min-w-0">
                <p className={EYEBROW}>{eyebrow}</p>
                <h1 className="mt-3 text-4xl font-bold tracking-[-.04em]">{title}</h1>
                {description ? <p className="mt-4 max-w-2xl leading-7 text-(--secondary-text-color)">{description}</p> : null}
            </div>
            {actions ? <div className="flex flex-wrap gap-3">{actions}</div> : null}
        </header>
    );
}

export function Panel({ eyebrow, title, description, action, children }: { eyebrow?: string; title: string; description?: string; action?: ReactNode; children: ReactNode }) {
    return (
        <section className="border border-(--border-color) bg-(--surface-color)">
            <div className="flex flex-col gap-4 border-b border-(--border-color) p-6 sm:flex-row sm:items-start sm:justify-between">
                <div className="min-w-0">
                    {eyebrow ? <p className={EYEBROW_MUTED}>{eyebrow}</p> : null}
                    <h2 className="mt-2 text-lg font-semibold tracking-[-.02em]">{title}</h2>
                    {description ? <p className="mt-2 max-w-2xl text-sm leading-6 text-(--secondary-text-color)">{description}</p> : null}
                </div>
                {action ? <div className="flex shrink-0 flex-wrap gap-2">{action}</div> : null}
            </div>
            {children}
        </section>
    );
}

export function FieldGrid({ children }: { children: ReactNode }) {
    return <dl className="grid gap-px bg-(--border-color) sm:grid-cols-2 lg:grid-cols-3">{children}</dl>;
}

export function Field({ label, value, mono = false, tone = "default", hint }: { label: string; value: ReactNode; mono?: boolean; tone?: "default" | "danger" | "success"; hint?: string }) {
    const toneClass = tone === "danger" ? "text-(--danger-color)" : tone === "success" ? "text-(--success-color)" : "text-(--primary-text-color)";
    return (
        <div className="bg-(--surface-color) px-6 py-5">
            <dt className={EYEBROW_MUTED}>{label}</dt>
            <dd className={`mt-2 break-words text-sm font-semibold ${mono ? "font-mono" : ""} ${toneClass}`}>{value === null || value === undefined || value === "" ? EMPTY_VALUE : value}</dd>
            {hint ? <p className="mt-2 text-xs leading-5 text-(--secondary-text-color)">{hint}</p> : null}
        </div>
    );
}

export function TableScroll({ children }: { children: ReactNode }) {
    return <div className="overflow-x-auto">{children}</div>;
}

export function ActionButton({ children, Icon, onClick, pending = false, disabled = false, variant = "secondary", type = "button", title }: { children: ReactNode; Icon?: LucideIcon; onClick?: () => void; pending?: boolean; disabled?: boolean; variant?: keyof typeof BUTTON; type?: "button" | "submit"; title?: string }) {
    return (
        <button className={BUTTON[variant]} disabled={disabled || pending} onClick={onClick} title={title} type={type}>
            {pending ? <LoaderCircle aria-hidden="true" className="size-4 animate-spin" /> : Icon ? <Icon aria-hidden="true" className="size-4" /> : null}
            {children}
        </button>
    );
}

export function LoadingPanel({ label }: { label: string }) {
    return (
        <div aria-busy="true" aria-label={label} className="animate-loading-pulse border border-(--border-color) bg-(--surface-color) p-8" role="status">
            <div className="h-3 w-32 bg-(--surface-strong-color)" />
            <div className="mt-6 h-8 w-2/3 bg-(--surface-strong-color)" />
            <div className="mt-8 space-y-3">
                <div className="h-4 w-full bg-(--surface-muted-color)" />
                <div className="h-4 w-5/6 bg-(--surface-muted-color)" />
                <div className="h-4 w-4/6 bg-(--surface-muted-color)" />
            </div>
        </div>
    );
}

export function ErrorPanel({ message, onRetry, title = "This view could not be loaded" }: { message: string; onRetry?: () => void; title?: string }) {
    return (
        <StatusScreen
            action={onRetry ? <ActionButton Icon={RotateCcw} onClick={onRetry} variant="primary">Retry</ActionButton> : undefined}
            description={message}
            embedded
            eyebrow="Request failed"
            icon={<TriangleAlert aria-hidden="true" className="size-5" />}
            title={title}
        >
            <p className="border-l-2 border-(--border-color) pl-4 text-sm leading-6 text-(--secondary-text-color)">No device record was changed. Confirm the VigiTrace API is reachable, then retry.</p>
        </StatusScreen>
    );
}
