/**
 * Wire shapes exchanged with the Python evidence service.
 *
 * These are deliberately snake_case: they mirror the Pydantic models in
 * ../service/models/*.py one-for-one. Those models are declared
 * `extra="forbid"`, so request bodies must carry these keys and no others.
 * Every field is present in a response (Pydantic emits nulls rather than
 * omitting keys), which is why absent values are typed `| null` rather than
 * optional.
 */

export type ServiceCredentials = {
    username: string;
    password: string;
};

export type ServiceDeviceTarget = {
    host: string;
    http_port: number;
    use_https: boolean;
    credentials: ServiceCredentials | null;
    vendor_hint: string | null;
    timeout_seconds: number;
    verify_tls: boolean;
};

export type ServiceErrorPayload = {
    code: string;
    message: string;
    detail: string | null;
    remediation: string | null;
};

export type ServiceDetection = {
    vendor: string;
    family: string;
    confidence: string;
    method: string;
    signals: string[];
    candidates: string[];
    detected_at: string;
};

export type ServiceDeviceIdentity = {
    vendor: string;
    family: string;
    confidence: string;
    kind: string;
    model_name: string | null;
    serial_number: string | null;
    firmware_version: string | null;
    firmware_released: string | null;
    hardware_version: string | null;
    mac_address: string | null;
    device_name: string | null;
};

export type ServiceNetworkInfo = {
    host: string;
    http_port: number;
    https_port: number | null;
    rtsp_port: number | null;
    sdk_port: number | null;
    mac_address: string | null;
    ipv4_address: string | null;
    subnet_mask: string | null;
    gateway: string | null;
    dhcp_enabled: boolean | null;
};

export type ServiceChannelInfo = {
    channel_id: string;
    name: string | null;
    enabled: boolean | null;
    is_analog: boolean | null;
    codec: string | null;
    resolution: string | null;
    track_id: string | null;
};

export type ServiceStorageInfo = {
    storage_id: string;
    name: string | null;
    kind: string | null;
    status: string | null;
    capacity_bytes: number | null;
    free_bytes: number | null;
    device_property: string | null;
};

export type ServiceClockInfo = {
    device_time: string | null;
    device_time_raw: string | null;
    timezone: string | null;
    ntp_enabled: boolean | null;
    ntp_servers: string[];
    probed_at: string | null;
    drift_seconds: number | null;
};

export type ServiceRawArtifact = {
    endpoint: string;
    method: string;
    status_code: number | null;
    content_type: string | null;
    body: string;
    sha256: string;
    retrieved_at: string;
};

export type ServiceProbeEvidence = {
    method: string;
    started_at: string;
    finished_at: string;
    duration_ms: number;
    endpoints_attempted: string[];
    endpoints_succeeded: string[];
    warnings: string[];
    artifacts: ServiceRawArtifact[];
};

export type ServiceStandardizedDevice = {
    identity: ServiceDeviceIdentity;
    network: ServiceNetworkInfo;
    channels: ServiceChannelInfo[];
    storage: ServiceStorageInfo[];
    clock: ServiceClockInfo;
    capabilities: string[];
    evidence: ServiceProbeEvidence;
    raw: Record<string, unknown>;
};

export type ServiceTimeSpan = {
    start: string;
    end: string;
};

export type ServiceRecording = {
    recording_id: string;
    channel_id: string;
    /** Vendor track identifier; distinct from channel_id since the adapter fix. */
    track_id: string | null;
    span: ServiceTimeSpan;
    codec: string | null;
    size_bytes: number | null;
    playback_uri: string | null;
    file_path: string | null;
    event_type: string | null;
    record_trigger: string | null;
    overwrite_count: number | null;
    source_method: string;
    raw: Record<string, unknown>;
};

export type ServiceRecordingIndex = {
    recordings: ServiceRecording[];
    searched_span: ServiceTimeSpan | null;
    channels_searched: string[];
    truncated: boolean;
    warnings: string[];
};

export type ServiceAcquisition = {
    recording_id: string;
    channel_id: string;
    span: ServiceTimeSpan;
    stored_path: string;
    size_bytes: number;
    md5: string;
    sha256: string;
    container: string | null;
    acquired_at: string;
    duration_ms: number;
    source_uri: string | null;
    warnings: string[];
};

export type ServiceVendorEntry = {
    vendor: string;
    family: string;
    capabilities: string[];
    default_http_port: number;
    sdk_port: number | null;
    provenance: string;
};

export type ServiceRecordingSearchRequest = {
    target: ServiceDeviceTarget;
    channel_ids: string[];
    start: string;
    end: string;
    max_results: number;
};

export type ServiceAcquisitionRequest = {
    target: ServiceDeviceTarget;
    recording_id: string;
    channel_id: string;
    start: string;
    end: string;
    playback_uri: string | null;
    file_path: string | null;
};

export type ServiceAnalysisRequest = {
    device: ServiceStandardizedDevice;
    index: ServiceRecordingIndex | null;
    narrate: boolean;
};

/** The union of every envelope the service returns, read defensively. */
export type ServiceEnvelope = {
    success?: boolean;
    message?: string;
    data?: unknown;
    device?: ServiceStandardizedDevice | null;
    detection?: ServiceDetection | null;
    index?: ServiceRecordingIndex | null;
    acquisition?: ServiceAcquisition | null;
    error?: ServiceErrorPayload | null;
};

export type ServiceArtifactCheck = {
    recording_id: string;
    stored_path: string;
    expected_sha256: string;
};

export type ServiceVerifyRequest = {
    artifacts: ServiceArtifactCheck[];
};

export type ServiceVerifyResult = {
    recording_id: string;
    verified: boolean;
    path: string;
    expected_sha256?: string;
    actual_sha256?: string;
    size_bytes?: number;
    reason: string | null;
};

export type ServiceVerifyData = {
    results: ServiceVerifyResult[];
    verified: number;
    failed: number;
};
