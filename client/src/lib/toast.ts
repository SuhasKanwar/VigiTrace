export type ToastVariant = "success" | "error" | "info";

export type ToastInput = {
    message: string;
    variant?: ToastVariant;
    duration?: number;
};

export type ToastItem = Required<Pick<ToastInput, "message">> & {
    id: string;
    variant: ToastVariant;
    duration: number;
};

type ToastListener = (toasts: ToastItem[]) => void;

const DEFAULT_DURATION = 4200;
let toasts: ToastItem[] = [];
const listeners = new Set<ToastListener>();

function emit() {
    for (const listener of listeners) {
        listener(toasts);
    }
}

function removeToast(id: string) {
    toasts = toasts.filter((toast) => toast.id !== id);
    emit();
}

export function subscribe(listener: ToastListener) {
    listeners.add(listener);
    listener(toasts);

    return () => {
        listeners.delete(listener);
    };
}

export function getToasts() {
    return toasts;
}

export function pushToast(input: ToastInput) {
    const id = crypto.randomUUID();
    const toast: ToastItem = {
        id,
        message: input.message,
        variant: input.variant ?? "info",
        duration: input.duration ?? DEFAULT_DURATION,
    };

    toasts = [...toasts, toast];
    emit();

    globalThis.setTimeout(() => {
        removeToast(id);
    }, toast.duration);

    return id;
}

export function dismissToast(id: string) {
    removeToast(id);
}