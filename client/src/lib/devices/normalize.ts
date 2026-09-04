import {
    CONFIDENCE_LEVELS,
    DEVICE_STATES,
    FINDING_SEVERITIES,
    type Acquisition,
    type AnalysisFinding,
    type AnalysisReport,
    type CustodyEvent,
    type Device,
    type DeviceChannel,
    type DeviceClock,
    type DeviceIdentity,
    type DeviceNetwork,
    type DeviceProbe,
    type DeviceStorageVolume,
    type DetectionResult,
    type FindingSeverity,
    type Recording,
    type RecordingIndex,
    type VendorAdapter,
    type VerificationResult,
} from "./types";

/**
 * The server normalizes the probe service's snake_case evidence model into its
 * own payloads, and may carry either shape through for nested objects. Reading
 * both key styles here keeps a naming drift on the wire from blanking a field an
 * investigator is relying on - and keeps a malformed payload from crashing a page.
 */

type Raw = Record<string, unknown>;

export function asRecord(value: unknown): Raw {
    return value !== null && typeof value === "object" && !Array.isArray(value) ? (value as Raw) : {};
}

function asArray(value: unknown): unknown[] {
    return Array.isArray(value) ? value : [];
}

function pick(source: Raw, ...keys: string[]): unknown {
    for (const key of keys) {
        const value = source[key];
        if (value !== undefined && value !== null && value !== "") return value;
    }
    return undefined;
}

function text(value: unknown): string | null {
    if (typeof value === "string") return value.trim() || null;
    if (typeof value === "number" || typeof value === "boolean") return String(value);
    return null;
}

function integer(value: unknown): number | null {
    if (typeof value === "number" && Number.isFinite(value)) return value;
    if (typeof value === "string" && value.trim()) {
        const parsed = Number(value);
        return Number.isFinite(parsed) ? parsed : null;
    }
    return null;
}

function flag(value: unknown): boolean | null {
    if (typeof value === "boolean") return value;
    if (value === "true" || value === "1" || value === 1) return true;
    if (value === "false" || value === "0" || value === 0) return false;
    return null;
}

function stringList(value: unknown): string[] {
    return asArray(value)
        .map((entry) => (typeof entry === "string" ? entry : text(asRecord(entry).name ?? entry)))
        .filter((entry): entry is string => Boolean(entry));
}

function timestamp(value: unknown): string | null {
    const raw = text(value);
    if (!raw) return null;
    const parsed = new Date(raw);
    return Number.isNaN(parsed.getTime()) ? raw : parsed.toISOString();
}

function oneOf<T extends string>(value: unknown, allowed: readonly T[], fallback: T): T {
    const candidate = text(value)?.toUpperCase();
    return allowed.find((entry) => entry === candidate) ?? fallback;
}

function upper(value: unknown): string | null {
    const raw = text(value);
    return raw ? raw.toUpperCase() : null;
}

export function normalizeVendorAdapter(input: unknown): VendorAdapter {
    const raw = asRecord(input);
    return {
        vendor: upper(pick(raw, "vendor", "name")) ?? "UNKNOWN",
        family: upper(pick(raw, "family", "vendor_family", "vendorFamily")),
        capabilities: stringList(pick(raw, "capabilities")),
        defaultHttpPort: integer(pick(raw, "default_http_port", "defaultHttpPort")),
        sdkPort: integer(pick(raw, "sdk_port", "sdkPort")),
        provenance: text(pick(raw, "provenance", "notes", "basis")),
    };
}

function normalizeIdentity(raw: Raw, nested: Raw): DeviceIdentity {
    const read = (...keys: string[]) => pick(nested, ...keys) ?? pick(raw, ...keys);
    return {
        vendor: upper(read("vendor")),
        family: upper(read("family", "vendor_family", "vendorFamily")),
        kind: upper(read("kind", "device_kind", "deviceKind")),
        confidence: oneOf(read("confidence"), CONFIDENCE_LEVELS, "UNKNOWN"),
        model: text(read("model_name", "modelName", "model")),
        serialNumber: text(read("serial_number", "serialNumber", "serial")),
        firmwareVersion: text(read("firmware_version", "firmwareVersion", "firmware")),
        firmwareReleased: text(read("firmware_released", "firmwareReleased")),
        hardwareVersion: text(read("hardware_version", "hardwareVersion")),
        macAddress: text(read("mac_address", "macAddress", "mac")),
        deviceName: text(read("device_name", "deviceName")),
    };
}

function normalizeNetwork(raw: Raw, nested: Raw): DeviceNetwork {
    const read = (...keys: string[]) => pick(nested, ...keys) ?? pick(raw, ...keys);
    return {
        host: text(read("host", "address", "ip")) ?? "unknown",
        httpPort: integer(read("http_port", "httpPort", "port")),
        httpsPort: integer(read("https_port", "httpsPort")),
        rtspPort: integer(read("rtsp_port", "rtspPort")),
        sdkPort: integer(read("sdk_port", "sdkPort")),
        useHttps: flag(read("use_https", "useHttps")) ?? false,
        macAddress: text(read("mac_address", "macAddress")),
        ipv4Address: text(read("ipv4_address", "ipv4Address")),
        subnetMask: text(read("subnet_mask", "subnetMask")),
        gateway: text(read("gateway")),
        dhcpEnabled: flag(read("dhcp_enabled", "dhcpEnabled")),
    };
}

export function normalizeChannel(input: unknown, index: number): DeviceChannel {
    const raw = asRecord(input);
    return {
        channelId: text(pick(raw, "channel_id", "channelId", "id")) ?? String(index + 1),
        name: text(pick(raw, "name", "channel_name", "channelName")),
        enabled: flag(pick(raw, "enabled")),
        isAnalog: flag(pick(raw, "is_analog", "isAnalog")),
        codec: text(pick(raw, "codec")),
        resolution: text(pick(raw, "resolution")),
        trackId: text(pick(raw, "track_id", "trackId")),
    };
}

export function normalizeStorage(input: unknown, index: number): DeviceStorageVolume {
    const raw = asRecord(input);
    const capacityBytes = integer(pick(raw, "capacity_bytes", "capacityBytes", "capacity"));
    const freeBytes = integer(pick(raw, "free_bytes", "freeBytes", "free"));
    const usedBytes = integer(pick(raw, "used_bytes", "usedBytes"));
    return {
        storageId: text(pick(raw, "storage_id", "storageId", "id")) ?? String(index + 1),
        name: text(pick(raw, "name")),
        kind: text(pick(raw, "kind", "type")),
        status: text(pick(raw, "status")),
        capacityBytes,
        freeBytes,
        usedBytes: usedBytes ?? (capacityBytes !== null && freeBytes !== null ? Math.max(capacityBytes - freeBytes, 0) : null),
        // The API persists this as storageProperty; the service calls it
        // device_property. Accept both so a rename on either side cannot blank
        // the column silently.
        deviceProperty: text(pick(raw, "device_property", "deviceProperty", "storageProperty", "storage_property")),
    };
}

function normalizeClock(input: unknown): DeviceClock {
    const raw = asRecord(input);
    return {
        deviceTime: timestamp(pick(raw, "device_time", "deviceTime")),
        deviceTimeRaw: text(pick(raw, "device_time_raw", "deviceTimeRaw")),
        timezone: text(pick(raw, "timezone", "time_zone", "timeZone")),
        ntpEnabled: flag(pick(raw, "ntp_enabled", "ntpEnabled")),
        ntpServers: stringList(pick(raw, "ntp_servers", "ntpServers")),
        probedAt: timestamp(pick(raw, "probed_at", "probedAt")),
        driftSeconds: integer(pick(raw, "drift_seconds", "driftSeconds")),
    };
}

function normalizeProbe(input: unknown): DeviceProbe | null {
    const raw = asRecord(input);
    if (Object.keys(raw).length === 0) return null;
    const evidence = asRecord(pick(raw, "evidence"));
    const read = (...keys: string[]) => pick(raw, ...keys) ?? pick(evidence, ...keys);
    return {
        method: upper(read("method")),
        startedAt: timestamp(read("started_at", "startedAt")),
        finishedAt: timestamp(read("finished_at", "finishedAt", "completed_at", "completedAt")),
        durationMs: integer(read("duration_ms", "durationMs")),
        endpointsAttempted: stringList(read("endpoints_attempted", "endpointsAttempted")),
        endpointsSucceeded: stringList(read("endpoints_succeeded", "endpointsSucceeded")),
        warnings: stringList(read("warnings")),
        sha256: text(read("combined_sha256", "combinedSha256", "sha256")),
    };
}

export function normalizeCustodyEvent(input: unknown, index: number): CustodyEvent {
    const raw = asRecord(input);
    return {
        id: text(pick(raw, "id", "event_id", "eventId")) ?? `custody-${index}`,
        action: text(pick(raw, "action", "event", "event_type", "eventType", "type")) ?? "EVENT",
        actor: text(pick(raw, "actor", "actor_name", "actorName", "user", "operator")),
        detail: text(pick(raw, "detail", "details", "description", "note", "message")),
        recordedAt: timestamp(pick(raw, "recorded_at", "recordedAt", "occurred_at", "occurredAt", "created_at", "createdAt", "at", "timestamp")),
        hash: text(pick(raw, "hash", "sha256", "digest")),
    };
}

export function normalizeDevice(input: unknown): Device {
    const raw = asRecord(input);
    const identitySource = asRecord(pick(raw, "identity"));
    const networkSource = asRecord(pick(raw, "network"));
    const channels = asArray(pick(raw, "channels")).map(normalizeChannel);
    const clockSource = pick(raw, "clock") ?? raw;

    return {
        id: text(pick(raw, "id", "device_id", "deviceId")) ?? "",
        name: text(pick(raw, "name", "label", "device_name", "deviceName")) ?? "Unnamed device",
        state: oneOf(pick(raw, "state", "status"), DEVICE_STATES, "REGISTERED"),
        identity: normalizeIdentity(raw, identitySource),
        network: normalizeNetwork(raw, networkSource),
        channels,
        storage: asArray(pick(raw, "storage", "storage_volumes", "storageVolumes")).map(normalizeStorage),
        clock: normalizeClock(clockSource),
        capabilities: stringList(pick(raw, "capabilities")).map((entry) => entry.toUpperCase()),
        custody: asArray(pick(raw, "custody", "custody_events", "custodyEvents", "events")).map(normalizeCustodyEvent),
        latestProbe: normalizeProbe(pick(raw, "latestProbe", "latest_probe", "probe")),
        channelCount: integer(pick(raw, "channel_count", "channelCount")) ?? channels.length,
        lastProbedAt: timestamp(pick(raw, "last_probed_at", "lastProbedAt", "lastProbed", "probed_at", "probedAt")),
        createdAt: timestamp(pick(raw, "created_at", "createdAt")),
        updatedAt: timestamp(pick(raw, "updated_at", "updatedAt")),
    };
}

export function normalizeDetection(input: unknown): DetectionResult {
    const raw = asRecord(input);
    return {
        vendor: upper(pick(raw, "vendor")),
        family: upper(pick(raw, "family")),
        confidence: oneOf(pick(raw, "confidence"), CONFIDENCE_LEVELS, "UNKNOWN"),
        method: upper(pick(raw, "method")),
        signals: stringList(pick(raw, "signals")),
        candidates: stringList(pick(raw, "candidates")),
        detectedAt: timestamp(pick(raw, "detected_at", "detectedAt")),
    };
}

export function normalizeRecording(input: unknown, index: number): Recording {
    const raw = asRecord(input);
    const span = asRecord(pick(raw, "span"));
    return {
        recordingId: text(pick(raw, "recording_id", "recordingId", "id")) ?? `recording-${index}`,
        channelId: text(pick(raw, "channel_id", "channelId")) ?? "—",
        start: timestamp(pick(span, "start") ?? pick(raw, "start", "start_time", "startTime")),
        end: timestamp(pick(span, "end") ?? pick(raw, "end", "end_time", "endTime")),
        codec: text(pick(raw, "codec")),
        sizeBytes: integer(pick(raw, "size_bytes", "sizeBytes", "size")),
        playbackUri: text(pick(raw, "playback_uri", "playbackUri")),
        filePath: text(pick(raw, "file_path", "filePath")),
        eventType: text(pick(raw, "event_type", "eventType")),
        recordTrigger: text(pick(raw, "record_trigger", "recordTrigger")),
        overwriteCount: integer(pick(raw, "overwrite_count", "overwriteCount")),
    };
}

export function normalizeRecordingIndex(input: unknown): RecordingIndex {
    const raw = asRecord(input);
    return {
        recordings: asArray(pick(raw, "recordings")).map(normalizeRecording),
        truncated: flag(pick(raw, "truncated")) ?? false,
        warnings: stringList(pick(raw, "warnings")),
        channelsSearched: stringList(pick(raw, "channels_searched", "channelsSearched")),
    };
}

export function normalizeFinding(input: unknown): AnalysisFinding {
    const raw = asRecord(input);
    return {
        severity: oneOf<FindingSeverity>(pick(raw, "severity", "level"), FINDING_SEVERITIES, "INFO"),
        category: text(pick(raw, "category")),
        title: text(pick(raw, "title", "summary")) ?? "Untitled finding",
        detail: text(pick(raw, "detail", "details", "description")),
        observation: text(pick(raw, "observation", "evidence")),
    };
}

export function normalizeAnalysis(input: unknown): AnalysisReport {
    const raw = asRecord(input);
    const findings = asArray(pick(raw, "findings")).map(normalizeFinding);
    const rawCounts = asRecord(pick(raw, "counts"));
    const counts: Record<string, number> = {};

    for (const severity of FINDING_SEVERITIES) {
        const reported = integer(pick(rawCounts, severity, severity.toLowerCase()));
        counts[severity] = reported ?? findings.filter((finding) => finding.severity === severity).length;
    }

    return { findings, counts };
}

/** One stored acquisition, as returned by GET /api/devices/:id/acquisitions. */
export function normalizeAcquisition(input: unknown): Acquisition {
    const raw = asRecord(input);
    return {
        id: text(pick(raw, "id")) ?? "",
        recordingId: text(pick(raw, "recording_id", "recordingId")) ?? "",
        channelId: text(pick(raw, "channel_id", "channelId")),
        storedPath: text(pick(raw, "stored_path", "storedPath")),
        sizeBytes: integer(pick(raw, "size_bytes", "sizeBytes")),
        md5: text(pick(raw, "md5")),
        sha256: text(pick(raw, "sha256")),
        container: text(pick(raw, "container")),
        acquiredAt: timestamp(pick(raw, "acquired_at", "acquiredAt")),
        durationMs: integer(pick(raw, "duration_ms", "durationMs")),
        sourceUri: text(pick(raw, "source_uri", "sourceUri")),
        // Deliberately tri-state: false means an integrity check FAILED, while
        // null means none has been run. Collapsing them would let unverified
        // evidence read as verified-negative, or worse, the reverse.
        verified: flag(pick(raw, "verified")),
    };
}

export function normalizeVerification(input: unknown): VerificationResult {
    const raw = asRecord(input);
    return {
        verified: integer(pick(raw, "verified")) ?? 0,
        failed: integer(pick(raw, "failed")) ?? 0,
        results: asArray(pick(raw, "results")).map((entry) => {
            const row = asRecord(entry);
            return {
                recordingId: text(pick(row, "recording_id", "recordingId")),
                verified: flag(pick(row, "verified")) === true,
                path: text(pick(row, "path", "stored_path", "storedPath")),
                expectedSha256: text(pick(row, "expected_sha256", "expectedSha256")),
                actualSha256: text(pick(row, "actual_sha256", "actualSha256")),
                sizeBytes: integer(pick(row, "size_bytes", "sizeBytes")),
                reason: text(pick(row, "reason")),
            };
        }),
    };
}
