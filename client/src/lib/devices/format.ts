import { CLOCK_DRIFT_LIMIT_SECONDS, type Device } from "./types";

export const EMPTY_VALUE = "—";

const BYTE_UNITS = ["B", "KB", "MB", "GB", "TB", "PB"];

/** Base-1024 sizes, the convention recorder firmware reports capacity in. */
export function formatBytes(bytes: number | null | undefined): string {
    if (bytes === null || bytes === undefined || !Number.isFinite(bytes) || bytes < 0) return EMPTY_VALUE;
    if (bytes === 0) return "0 B";

    let value = bytes;
    let unit = 0;

    while (value >= 1024 && unit < BYTE_UNITS.length - 1) {
        value /= 1024;
        unit += 1;
    }

    return `${value.toFixed(unit === 0 ? 0 : value >= 100 ? 0 : 1)} ${BYTE_UNITS[unit]}`;
}

/** UTC, not locale time: an evidence timestamp must read the same to every reviewer. */
export function formatTimestamp(value: string | null | undefined): string {
    if (!value) return EMPTY_VALUE;
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;
    return `${parsed.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

export function formatRelative(value: string | null | undefined): string {
    if (!value) return "never probed";
    const parsed = new Date(value);
    if (Number.isNaN(parsed.getTime())) return value;

    const seconds = Math.round((Date.now() - parsed.getTime()) / 1000);
    if (seconds < 0) return "in the future";
    if (seconds < 60) return "moments ago";
    if (seconds < 3600) return `${Math.floor(seconds / 60)} min ago`;
    if (seconds < 86400) return `${Math.floor(seconds / 3600)} h ago`;
    return `${Math.floor(seconds / 86400)} d ago`;
}

export function formatDuration(milliseconds: number | null | undefined): string {
    if (milliseconds === null || milliseconds === undefined || !Number.isFinite(milliseconds)) return EMPTY_VALUE;
    if (milliseconds < 1000) return `${Math.round(milliseconds)} ms`;
    return `${(milliseconds / 1000).toFixed(2)} s`;
}

export function formatDrift(seconds: number | null | undefined): string {
    if (seconds === null || seconds === undefined || !Number.isFinite(seconds)) return EMPTY_VALUE;
    const rounded = Math.abs(seconds) >= 10 ? seconds.toFixed(1) : seconds.toFixed(2);
    return `${seconds > 0 ? "+" : ""}${rounded} s`;
}

export function isDriftOutOfTolerance(seconds: number | null | undefined): boolean {
    return typeof seconds === "number" && Number.isFinite(seconds) && Math.abs(seconds) > CLOCK_DRIFT_LIMIT_SECONDS;
}

export function formatBoolean(value: boolean | null | undefined): string {
    if (value === null || value === undefined) return EMPTY_VALUE;
    return value ? "Yes" : "No";
}

export function formatValue(value: string | number | null | undefined): string {
    if (value === null || value === undefined) return EMPTY_VALUE;
    const text = String(value).trim();
    return text || EMPTY_VALUE;
}

export function formatEndpoint(device: Pick<Device, "network">): string {
    const { host, httpPort, useHttps } = device.network;
    const scheme = useHttps ? "https" : "http";
    return httpPort === null ? `${scheme}://${host}` : `${scheme}://${host}:${httpPort}`;
}

/** `datetime-local` inputs speak local wall-clock time with no zone; the API speaks ISO. */
export function toLocalInputValue(date: Date): string {
    const offset = date.getTimezoneOffset() * 60000;
    return new Date(date.getTime() - offset).toISOString().slice(0, 16);
}

export function fromLocalInputValue(value: string): string | null {
    if (!value) return null;
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed.toISOString();
}
