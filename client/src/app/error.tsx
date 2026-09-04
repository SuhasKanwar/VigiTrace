"use client";

import { AlertTriangle, RotateCcw } from "lucide-react";
import StatusScreen from "@/components/ui/status-screen";

export default function ErrorPage({ reset }: { error: Error; reset: () => void }) {
    return (
        <StatusScreen
            action={<button className="inline-flex items-center gap-2 rounded-xl bg-(--primary-color) px-4 py-2.5 text-sm font-semibold text-(--surface-color) transition-colors hover:bg-(--secondary-color)" onClick={reset} type="button"><RotateCcw aria-hidden="true" className="size-4" />Try again</button>}
            description="VigiTrace could not load this view. Your evidence data has not been changed."
            eyebrow="Unexpected error"
            icon={<AlertTriangle aria-hidden="true" className="size-5" />}
            title="Something interrupted the workflow"
        />
    );
}
