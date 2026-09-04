import type { ConfidenceLevel, DeviceState, FindingSeverity } from "@/lib/devices/types";

type Tone = "success" | "progress" | "danger" | "neutral" | "info";

const TONE_CLASS: Record<Tone, string> = {
    success: "border-(--success-color) bg-(--surface-color) text-(--success-color)",
    progress: "border-(--warning-color) bg-(--surface-color) text-(--warning-color)",
    danger: "border-(--danger-color) bg-(--surface-color) text-(--danger-color)",
    info: "border-(--primary-color) bg-(--surface-color) text-(--primary-color)",
    neutral: "border-(--border-color) bg-(--surface-muted-color) text-(--secondary-text-color)",
};

const BADGE_BASE = "inline-flex items-center gap-2 border px-2.5 py-1 font-mono text-[10px] font-semibold uppercase tracking-[.16em] whitespace-nowrap";

export const STATE_TONE: Record<DeviceState, Tone> = {
    REGISTERED: "neutral",
    IDENTIFYING: "progress",
    IDENTIFIED: "success",
    ENUMERATING: "progress",
    ENUMERATED: "success",
    INDEXING: "progress",
    INDEXED: "success",
    ACQUIRING: "progress",
    ACQUIRED: "success",
    VERIFYING: "progress",
    VERIFIED: "success",
    UNREACHABLE: "danger",
    AUTH_FAILED: "danger",
    UNSUPPORTED: "danger",
    FAILED: "danger",
};

export const STATE_NOTE: Record<DeviceState, string> = {
    REGISTERED: "Recorded in the workspace; nothing has been probed yet.",
    IDENTIFYING: "Fingerprinting the recorder.",
    IDENTIFIED: "Vendor and model established.",
    ENUMERATING: "Reading channels and storage.",
    ENUMERATED: "Channels and storage recorded.",
    INDEXING: "Reading the recorder's recording index.",
    INDEXED: "Recording index captured.",
    ACQUIRING: "Controlled export in progress.",
    ACQUIRED: "Export written and hashed.",
    VERIFYING: "Re-hashing acquired media.",
    VERIFIED: "Hashes matched the acquisition record.",
    UNREACHABLE: "No response from the host at the recorded endpoint.",
    AUTH_FAILED: "The recorder rejected the stored credentials.",
    UNSUPPORTED: "No adapter covers this recorder's protocol.",
    FAILED: "The last operation did not complete.",
};

export function StateBadge({ state }: { state: DeviceState }) {
    const tone = STATE_TONE[state];
    return <span className={`${BADGE_BASE} ${TONE_CLASS[tone]}`} title={STATE_NOTE[state]}><span aria-hidden="true" className={`size-1.5 rounded-full bg-current ${tone === "progress" ? "animate-loading-pulse" : ""}`} />{state.replace(/_/g, " ")}</span>;
}

export const CONFIDENCE_NOTE: Record<ConfidenceLevel, string> = {
    CONFIRMED: "Returned by the recorder's authenticated vendor API.",
    PROBABLE: "Fingerprint-derived attribution, not vendor-confirmed. Do not report as fact.",
    UNKNOWN: "No attribution has been established for this recorder.",
};

export function ConfidenceBadge({ confidence }: { confidence: ConfidenceLevel }) {
    const tone: Tone = confidence === "CONFIRMED" ? "success" : confidence === "PROBABLE" ? "progress" : "neutral";
    const provisional = confidence !== "CONFIRMED";
    return <span className={`${BADGE_BASE} ${TONE_CLASS[tone]} ${provisional ? "border-dashed" : ""}`} title={CONFIDENCE_NOTE[confidence]}><span aria-hidden="true" className="size-1.5 rounded-full bg-current" />{confidence}<span className="sr-only"> — {CONFIDENCE_NOTE[confidence]}</span></span>;
}

/** The visible counterpart to the badge: an unconfirmed attribution must never read as a fact. */
export function ConfidenceNote({ confidence }: { confidence: ConfidenceLevel }) {
    if (confidence === "CONFIRMED") return null;
    return <p className={`border-l-2 px-4 py-3 text-sm leading-6 ${confidence === "PROBABLE" ? "border-(--warning-color) bg-(--surface-muted-color) text-(--warning-color)" : "border-(--muted-text-color) bg-(--surface-muted-color) text-(--secondary-text-color)"}`}>{confidence === "PROBABLE" ? "Attribution is fingerprint-derived — inferred from digest realm shape, banner, and open-port profile — and has not been confirmed by an authenticated vendor API. Record it as probable, not established." : "No vendor attribution has been established. Run Identify with valid credentials before relying on any device fact below."}</p>;
}

export function VendorBadge({ vendor, family }: { vendor: string | null; family?: string | null }) {
    const known = vendor && vendor !== "UNKNOWN";
    return <span className={`${BADGE_BASE} ${known ? TONE_CLASS.neutral : "border-dashed border-(--muted-text-color) bg-(--surface-color) text-(--muted-text-color)"}`} title={known && family && family !== vendor ? `${vendor} recorders run the ${family} protocol family.` : undefined}>{known ? vendor : "UNIDENTIFIED"}{known && family && family !== vendor ? <span className="text-(--muted-text-color)">/ {family}</span> : null}</span>;
}

export function SeverityBadge({ severity }: { severity: FindingSeverity }) {
    const tone: Tone = severity === "CRITICAL" ? "danger" : severity === "WARNING" ? "progress" : "info";
    return <span className={`${BADGE_BASE} ${TONE_CLASS[tone]}`}><span aria-hidden="true" className="size-1.5 rounded-full bg-current" />{severity}</span>;
}

export function CapabilityChip({ capability, available = true }: { capability: string; available?: boolean }) {
    return <span className={`${BADGE_BASE} ${available ? TONE_CLASS.neutral : "border-dashed border-(--border-color) bg-(--surface-color) text-(--muted-text-color)"}`}>{capability.replace(/_/g, " ")}</span>;
}
