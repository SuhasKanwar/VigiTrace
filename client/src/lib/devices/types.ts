export const DEVICE_STATES = [
    "REGISTERED",
    "IDENTIFYING",
    "IDENTIFIED",
    "ENUMERATING",
    "ENUMERATED",
    "INDEXING",
    "INDEXED",
    "ACQUIRING",
    "ACQUIRED",
    "VERIFYING",
    "VERIFIED",
    "UNREACHABLE",
    "AUTH_FAILED",
    "UNSUPPORTED",
    "FAILED",
] as const;

export type DeviceState = (typeof DEVICE_STATES)[number];

export const CONFIDENCE_LEVELS = ["CONFIRMED", "PROBABLE", "UNKNOWN"] as const;

export type ConfidenceLevel = (typeof CONFIDENCE_LEVELS)[number];

export const VENDOR_HINTS = ["HIKVISION", "DAHUA", "CPPLUS", "GODREJ"] as const;

export type VendorHint = (typeof VENDOR_HINTS)[number];

export const FINDING_SEVERITIES = ["CRITICAL", "WARNING", "INFO"] as const;

export type FindingSeverity = (typeof FINDING_SEVERITIES)[number];

/** Clock offset beyond which every timeline claim needs manual reconciliation. */
export const CLOCK_DRIFT_LIMIT_SECONDS = 300;

/** The capability set adapters declare against; anything absent is a stage the device cannot support. */
export const KNOWN_CAPABILITIES = [
    "IDENTIFY",
    "ENUMERATE_CHANNELS",
    "ENUMERATE_STORAGE",
    "READ_CLOCK",
    "READ_NTP",
    "SEARCH_RECORDINGS",
    "DOWNLOAD_RECORDING",
    "READ_LOGS",
    "READ_USERS",
] as const;

export type VendorAdapter = {
    vendor: string;
    family: string | null;
    capabilities: string[];
    defaultHttpPort: number | null;
    sdkPort: number | null;
    provenance: string | null;
};

export type DeviceIdentity = {
    vendor: string | null;
    family: string | null;
    kind: string | null;
    confidence: ConfidenceLevel;
    model: string | null;
    serialNumber: string | null;
    firmwareVersion: string | null;
    firmwareReleased: string | null;
    hardwareVersion: string | null;
    macAddress: string | null;
    deviceName: string | null;
};

export type DeviceNetwork = {
    host: string;
    httpPort: number | null;
    httpsPort: number | null;
    rtspPort: number | null;
    sdkPort: number | null;
    useHttps: boolean;
    macAddress: string | null;
    ipv4Address: string | null;
    subnetMask: string | null;
    gateway: string | null;
    dhcpEnabled: boolean | null;
};

export type DeviceChannel = {
    channelId: string;
    name: string | null;
    enabled: boolean | null;
    isAnalog: boolean | null;
    codec: string | null;
    resolution: string | null;
    trackId: string | null;
};

export type DeviceStorageVolume = {
    storageId: string;
    name: string | null;
    kind: string | null;
    status: string | null;
    capacityBytes: number | null;
    freeBytes: number | null;
    usedBytes: number | null;
    deviceProperty: string | null;
};

export type DeviceClock = {
    deviceTime: string | null;
    deviceTimeRaw: string | null;
    timezone: string | null;
    ntpEnabled: boolean | null;
    ntpServers: string[];
    probedAt: string | null;
    driftSeconds: number | null;
};

export type DeviceProbe = {
    method: string | null;
    startedAt: string | null;
    finishedAt: string | null;
    durationMs: number | null;
    endpointsAttempted: string[];
    endpointsSucceeded: string[];
    warnings: string[];
    sha256: string | null;
};

export type CustodyEvent = {
    id: string;
    action: string;
    actor: string | null;
    detail: string | null;
    recordedAt: string | null;
    hash: string | null;
};

export type Device = {
    id: string;
    name: string;
    state: DeviceState;
    identity: DeviceIdentity;
    network: DeviceNetwork;
    channels: DeviceChannel[];
    storage: DeviceStorageVolume[];
    clock: DeviceClock;
    capabilities: string[];
    custody: CustodyEvent[];
    latestProbe: DeviceProbe | null;
    channelCount: number;
    lastProbedAt: string | null;
    createdAt: string | null;
    updatedAt: string | null;
};

export type DetectionResult = {
    vendor: string | null;
    family: string | null;
    confidence: ConfidenceLevel;
    method: string | null;
    signals: string[];
    candidates: string[];
    detectedAt: string | null;
};

export type Recording = {
    recordingId: string;
    channelId: string;
    start: string | null;
    end: string | null;
    codec: string | null;
    sizeBytes: number | null;
    playbackUri: string | null;
    filePath: string | null;
    eventType: string | null;
    recordTrigger: string | null;
    overwriteCount: number | null;
};

export type RecordingIndex = {
    recordings: Recording[];
    truncated: boolean;
    warnings: string[];
    channelsSearched: string[];
};

export type AnalysisFinding = {
    severity: FindingSeverity;
    category: string | null;
    title: string;
    detail: string | null;
    observation: string | null;
};

export type AnalysisReport = {
    findings: AnalysisFinding[];
    counts: Record<string, number>;
};

export type CreateDeviceInput = {
    name: string;
    host: string;
    httpPort: number;
    useHttps: boolean;
    username: string;
    password: string;
    vendorHint?: VendorHint;
};

export type RecordingSearchInput = {
    channelIds: string[];
    start: string;
    end: string;
    maxResults: number;
};

export type AcquisitionInput = {
    recordingId: string;
    channelId: string;
    start: string;
    end: string;
    playbackUri?: string;
    filePath?: string;
};

/** A completed controlled export, with the integrity material recorded at acquisition time. */
export type Acquisition = {
    id: string;
    recordingId: string;
    channelId: string | null;
    storedPath: string | null;
    sizeBytes: number | null;
    md5: string | null;
    sha256: string | null;
    container: string | null;
    acquiredAt: string | null;
    durationMs: number | null;
    sourceUri: string | null;
    /** Null until an integrity check has been run against this artifact. */
    verified: boolean | null;
};

export type VerificationOutcome = {
    recordingId: string | null;
    verified: boolean;
    path: string | null;
    expectedSha256: string | null;
    actualSha256: string | null;
    sizeBytes: number | null;
    /** Present only on failure, explaining what went wrong. */
    reason: string | null;
};

export type VerificationResult = {
    verified: number;
    failed: number;
    results: VerificationOutcome[];
};
