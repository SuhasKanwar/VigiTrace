import crypto from "node:crypto";
import {
    DeviceFamily,
    DeviceKind,
    DeviceVendor,
    IdentificationConfidence,
} from "../generated/prisma/enums.js";
import type { Device } from "../generated/prisma/client.js";
import { decryptSecret } from "./crypto.js";
import type {
    ServiceDeviceTarget,
    ServiceRawArtifact,
    ServiceRecording,
    ServiceRecordingIndex,
} from "../types/vendor.js";

const IPV4 = /^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$/;
const HOSTNAME = /^(?=.{1,253}$)[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?(\.[A-Za-z0-9]([A-Za-z0-9-]{0,61}[A-Za-z0-9])?)*$/;
const IPV6 = /^[0-9A-Fa-f:]+$/;

/** True for an IPv4 address, an IPv6 address or a DNS hostname. */
export function isValidHost(value: string): boolean {
    const host = value.trim();
    if (!host || host.length > 253) {
        return false;
    }
    const ipv4 = IPV4.exec(host);
    if (ipv4) {
        return ipv4.slice(1).every((octet) => Number(octet) >= 0 && Number(octet) <= 255);
    }
    if (host.includes(":")) {
        return IPV6.test(host);
    }
    return HOSTNAME.test(host);
}

/** Parse a TCP port, returning null when it is not a usable port number. */
export function parsePort(value: unknown): number | null {
    if (value === undefined || value === null || value === "") {
        return null;
    }
    const port = typeof value === "number" ? value : Number(String(value).trim());
    if (!Number.isInteger(port) || port < 1 || port > 65535) {
        return null;
    }
    return port;
}

function toEnum<T extends Record<string, string>>(
    enumeration: T,
    value: unknown,
    fallback: T[keyof T]
): T[keyof T] {
    if (typeof value !== "string") {
        return fallback;
    }
    const key = value.trim().toUpperCase();
    return (Object.values(enumeration) as string[]).includes(key) ? (key as T[keyof T]) : fallback;
}

export function toVendorEnum(value: unknown): DeviceVendor {
    return toEnum(DeviceVendor, value, DeviceVendor.UNKNOWN);
}

export function toFamilyEnum(value: unknown): DeviceFamily {
    return toEnum(DeviceFamily, value, DeviceFamily.UNKNOWN);
}

export function toConfidenceEnum(value: unknown): IdentificationConfidence {
    return toEnum(IdentificationConfidence, value, IdentificationConfidence.UNKNOWN);
}

export function toKindEnum(value: unknown): DeviceKind {
    return toEnum(DeviceKind, value, DeviceKind.UNKNOWN);
}

/** True when the string names one of the supported vendors. */
export function isKnownVendor(value: string): boolean {
    return (Object.values(DeviceVendor) as string[]).includes(value.trim().toUpperCase());
}

export type TargetOptions = {
    timeoutSeconds?: number;
    verifyTls?: boolean;
    requireCredentials?: boolean;
};

export class MissingCredentialsError extends Error {
    constructor() {
        super("This device has no stored credentials, so it cannot be authenticated against.");
        this.name = "MissingCredentialsError";
    }
}

/**
 * Build the snake_case DeviceTarget the Python service expects. The stored
 * password is decrypted here and nowhere else, and is never returned to the
 * client.
 */
export function buildDeviceTarget(device: Device, options: TargetOptions = {}): ServiceDeviceTarget {
    let credentials: ServiceDeviceTarget["credentials"] = null;
    if (device.username && device.password) {
        credentials = { username: device.username, password: decryptSecret(device.password) };
    }
    if (!credentials && options.requireCredentials) {
        throw new MissingCredentialsError();
    }

    return {
        host: device.host,
        http_port: device.httpPort,
        use_https: device.useHttps,
        credentials,
        vendor_hint: device.vendorHint ?? null,
        timeout_seconds: options.timeoutSeconds ?? 8.0,
        verify_tls: options.verifyTls ?? false,
    };
}

/**
 * Reproduce the service's `ProbeEvidence.combined_sha256`: the SHA-256 of every
 * artifact digest, concatenated in endpoint order. Recomputing it here means the
 * stored digest can be checked against the evidence the service returned.
 */
export function combinedEvidenceDigest(artifacts: ServiceRawArtifact[]): string {
    const digest = crypto.createHash("sha256");
    // Python's sorted() orders by code point. localeCompare does not (it sorts
    // "/ISAPI" after "/cgi-bin"), which would silently produce a digest that
    // never matches the service's own and defeat the point of storing it.
    const ordered = [...artifacts].sort((a, b) =>
        a.endpoint < b.endpoint ? -1 : a.endpoint > b.endpoint ? 1 : 0
    );
    for (const artifact of ordered) {
        digest.update(artifact.sha256, "ascii");
    }
    return digest.digest("hex");
}

/** A device as the client may see it: everything except the stored secret. */
export function sanitizeDevice(device: Device): Record<string, unknown> {
    const { password, ...rest } = device;
    return { ...rest, hasCredentials: Boolean(device.username && password) };
}

type PersistedRecording = {
    recordingId: string;
    channelId: string;
    trackId: string | null;
    startTime: Date;
    endTime: Date;
    codec: string | null;
    sizeBytes: bigint | null;
    playbackUri: string | null;
    filePath: string | null;
    eventType: string | null;
    recordTrigger: string | null;
    overwriteCount: number | null;
    raw: unknown;
};

function isServiceRecording(value: unknown): value is ServiceRecording {
    if (value === null || typeof value !== "object") {
        return false;
    }
    const candidate = value as Record<string, unknown>;
    return (
        typeof candidate["recording_id"] === "string" &&
        typeof candidate["channel_id"] === "string" &&
        typeof candidate["source_method"] === "string" &&
        typeof candidate["span"] === "object"
    );
}

/**
 * Rebuild the service's RecordingIndex from persisted rows so analysis runs
 * against the same evidence that was stored, not a fresh probe. The verbatim
 * payload is preferred; a row that predates it is reconstructed field by field.
 */
export function buildRecordingIndexPayload(rows: PersistedRecording[]): ServiceRecordingIndex {
    const recordings: ServiceRecording[] = rows.map((row) => {
        if (isServiceRecording(row.raw)) {
            return row.raw;
        }
        return {
            recording_id: row.recordingId,
            channel_id: row.channelId,
            track_id: row.trackId,
            span: { start: row.startTime.toISOString(), end: row.endTime.toISOString() },
            codec: row.codec,
            size_bytes: row.sizeBytes === null ? null : Number(row.sizeBytes),
            playback_uri: row.playbackUri,
            file_path: row.filePath,
            event_type: row.eventType,
            record_trigger: row.recordTrigger,
            overwrite_count: row.overwriteCount,
            source_method: "UNAUTHENTICATED_FINGERPRINT",
            raw: {},
        };
    });

    const starts = rows.map((row) => row.startTime.getTime());
    const ends = rows.map((row) => row.endTime.getTime());

    return {
        recordings,
        searched_span:
            rows.length > 0
                ? {
                      start: new Date(Math.min(...starts)).toISOString(),
                      end: new Date(Math.max(...ends)).toISOString(),
                  }
                : null,
        channels_searched: [...new Set(rows.map((row) => row.channelId))].sort(),
        truncated: false,
        warnings: [],
    };
}
