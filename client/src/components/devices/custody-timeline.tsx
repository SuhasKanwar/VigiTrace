import { FileClock } from "lucide-react";
import { EYEBROW_MUTED } from "@/components/devices/ui";
import { formatRelative, formatTimestamp } from "@/lib/devices/format";
import type { CustodyEvent } from "@/lib/devices/types";

export function sortCustody(events: CustodyEvent[]): CustodyEvent[] {
    return [...events].sort((a, b) => (b.recordedAt ?? "").localeCompare(a.recordedAt ?? ""));
}

export default function CustodyTimeline({ events, emptyMessage = "No custody events have been recorded for this device yet." }: { events: CustodyEvent[]; emptyMessage?: string }) {
    if (events.length === 0) {
        return <p className="flex items-center gap-3 p-6 text-sm text-(--secondary-text-color)"><FileClock aria-hidden="true" className="size-4 text-(--muted-text-color)" />{emptyMessage}</p>;
    }

    return (
        <ol className="p-6">
            {sortCustody(events).map((event, index, all) => (
                <li className="relative flex gap-5 pb-6 last:pb-0" key={event.id}>
                    <span aria-hidden="true" className="relative flex flex-col items-center"><span className="mt-1.5 size-2.5 shrink-0 rounded-full bg-(--primary-color)" />{index < all.length - 1 ? <span className="mt-1 w-px flex-1 bg-(--border-color)" /> : null}</span>
                    <div className="min-w-0 flex-1 border-b border-(--border-color) pb-6 last:border-b-0 last:pb-0">
                        <div className="flex flex-wrap items-baseline justify-between gap-x-4 gap-y-1">
                            <p className="font-mono text-xs font-semibold uppercase tracking-[.16em] text-(--primary-text-color)">{event.action.replace(/_/g, " ")}</p>
                            <p className={EYEBROW_MUTED} title={formatTimestamp(event.recordedAt)}>{formatRelative(event.recordedAt)}</p>
                        </div>
                        <p className="mt-2 font-mono text-[11px] text-(--muted-text-color)">{formatTimestamp(event.recordedAt)}</p>
                        {event.detail ? <p className="mt-2 text-sm leading-6 text-(--secondary-text-color)">{event.detail}</p> : null}
                        <div className="mt-3 flex flex-wrap gap-x-6 gap-y-1 text-xs text-(--secondary-text-color)">
                            {event.actor ? <span>Actor · <span className="font-semibold text-(--primary-text-color)">{event.actor}</span></span> : null}
                            {event.hash ? <span className="font-mono break-all text-(--muted-text-color)" title={event.hash}>SHA-256 · {event.hash.slice(0, 24)}…</span> : null}
                        </div>
                    </div>
                </li>
            ))}
        </ol>
    );
}
