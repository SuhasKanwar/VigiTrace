"use client";

import { createPortal } from "react-dom";
import { CheckCircle2, CircleAlert, Info, X } from "lucide-react";
import { useMemo, useSyncExternalStore } from "react";
import type { ReactNode } from "react";
import { dismissToast, getToasts, pushToast, subscribe, type ToastInput, type ToastItem } from "@/lib/toast";

type ToastContextValue = {
    pushToast: (toast: ToastInput) => string;
    dismissToast: (id: string) => void;
};

export function ToastProvider({ children }: { children: ReactNode }) {
    const toasts = useSyncExternalStore(subscribe, getToasts, getToasts);
    const mounted = useSyncExternalStore(() => () => undefined, () => true, () => false);

    return (
        <>
            {children}
            {mounted ? createPortal(<ToastViewport toasts={toasts} />, document.body) : null}
        </>
    );
}

export function useToast(): ToastContextValue {
    return useMemo(() => ({
        pushToast,
        dismissToast,
    }), []);
}

/**
 * Anchored to the bottom rather than the top: the dashboard's sticky header
 * carries the device actions, and a stacked toast sat directly over them.
 * Because the card itself is pointer-events-auto, a click on "Verify integrity"
 * or "Enumerate" landed on the toast instead and did nothing at all - no
 * request, no error, no feedback. Column-reverse keeps the newest toast nearest
 * the bottom edge as the stack grows upward.
 */
function ToastViewport({ toasts }: { toasts: ToastItem[] }) {
    return (
        <div aria-label="Notifications" className="pointer-events-none fixed bottom-4 right-4 z-100 flex w-[calc(100vw-2rem)] max-w-sm flex-col-reverse gap-3 sm:bottom-6 sm:right-6">
            {toasts.map((toast) => (
                <ToastCard key={toast.id} toast={toast} />
            ))}
        </div>
    );
}

function ToastCard({ toast }: { toast: ToastItem }) {
    const tone =
        toast.variant === "success"
            ? "border-(--success-color) bg-(--surface-muted-color) text-(--primary-text-color)"
            : toast.variant === "error"
                ? "border-(--danger-color) bg-(--surface-muted-color) text-(--primary-text-color)"
                : "border-(--border-color) bg-(--surface-color) text-(--primary-text-color)";
    const Icon = toast.variant === "success" ? CheckCircle2 : toast.variant === "error" ? CircleAlert : Info;
    const iconTone = toast.variant === "success" ? "text-(--success-color)" : toast.variant === "error" ? "text-(--danger-color)" : "text-(--primary-color)";

    return (
        <div className={`pointer-events-auto animate-toast-enter border border-l-4 p-4 shadow-[0_12px_30px_var(--shadow-color)] ${tone}`}>
            <div className="flex items-start gap-3">
                <Icon aria-hidden="true" className={`mt-0.5 size-5 shrink-0 ${iconTone}`} />
                <div className="min-w-0 flex-1">
                    <p className="font-mono text-[10px] uppercase tracking-[0.22em] text-(--secondary-text-color)">
                        {toast.variant}
                    </p>
                    <p className="mt-1 font-(family-name:--font-display) text-sm leading-6">
                        {toast.message}
                    </p>
                </div>
                <button aria-label="Dismiss toast" className="rounded-full p-1 text-(--secondary-text-color) transition-colors hover:text-(--primary-text-color)" onClick={() => dismissToast(toast.id)} type="button">
                    <X aria-hidden="true" className="h-4 w-4" />
                </button>
            </div>
        </div>
    );
}
