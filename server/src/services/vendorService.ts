import axios from "axios";
import { microserviceApi } from "../lib/api.js";
import {
    MICROSERVICE_ACQUIRE_TIMEOUT_MS,
    MICROSERVICE_ANALYSIS_TIMEOUT_MS,
    MICROSERVICE_DISK_ANALYSIS_TIMEOUT_MS,
    MICROSERVICE_TIMEOUT_MS,
} from "../lib/config.js";
import { DeviceState, DiskImageState } from "../generated/prisma/enums.js";
import type {
    ServiceAcquisitionRequest,
    ServiceAnalysisRequest,
    ServiceDeviceTarget,
    ServiceDiskAnalyseRequest,
    ServiceEnvelope,
    ServiceErrorPayload,
    ServiceRecordingSearchRequest,
    ServiceVerifyRequest,
} from "../types/vendor.js";

/** Error codes this server adds on top of the service's own ErrorCode enum. */
export const SERVICE_UNAVAILABLE = "SERVICE_UNAVAILABLE";
export const SERVICE_TIMEOUT = "SERVICE_TIMEOUT";

export type VendorCall =
    | { ok: true; message: string; body: ServiceEnvelope }
    | {
          ok: false;
          message: string;
          status: number;
          code: string;
          detail: string | null;
          remediation: string | null;
          body: ServiceEnvelope | null;
      };

/**
 * A failure at the recorder is not a failure of this server, so device-level
 * problems map onto gateway-flavoured statuses rather than 500.
 */
const STATUS_BY_CODE: Record<string, number> = {
    UNREACHABLE: 502,
    TIMEOUT: 504,
    AUTH_FAILED: 400,
    AUTH_LOCKOUT_RISK: 400,
    UNSUPPORTED_VENDOR: 422,
    CAPABILITY_UNAVAILABLE: 422,
    // The caller named an image that cannot be read. Nothing upstream failed,
    // so reporting a gateway error would send an operator looking for a broken
    // service when the path is simply wrong.
    IMAGE_UNREADABLE: 422,
    PROTOCOL_ERROR: 502,
    NOT_CONFIGURED: 502,
    INTERNAL: 502,
    [SERVICE_UNAVAILABLE]: 503,
    [SERVICE_TIMEOUT]: 504,
};

/**
 * Which terminal state a device lands in when a probe fails. The four failure
 * states stay distinguishable so an investigator can tell a wrong password
 * from a wrong vendor from an unplugged cable.
 */
const STATE_BY_CODE: Record<string, DeviceState> = {
    UNREACHABLE: DeviceState.UNREACHABLE,
    TIMEOUT: DeviceState.UNREACHABLE,
    AUTH_FAILED: DeviceState.AUTH_FAILED,
    AUTH_LOCKOUT_RISK: DeviceState.AUTH_FAILED,
    UNSUPPORTED_VENDOR: DeviceState.UNSUPPORTED,
    CAPABILITY_UNAVAILABLE: DeviceState.UNSUPPORTED,
    PROTOCOL_ERROR: DeviceState.FAILED,
    NOT_CONFIGURED: DeviceState.FAILED,
    INTERNAL: DeviceState.FAILED,
    [SERVICE_UNAVAILABLE]: DeviceState.FAILED,
    [SERVICE_TIMEOUT]: DeviceState.UNREACHABLE,
};

export function statusForServiceError(code: string): number {
    return STATUS_BY_CODE[code] ?? 502;
}

export function stateForServiceError(code: string): DeviceState {
    return STATE_BY_CODE[code] ?? DeviceState.FAILED;
}

/**
 * Which terminal state an on-disk analysis run lands in when it fails. Disk
 * analysis reads a local file rather than reaching across a network, so it
 * has no notion of "unreachable" or "wrong password": only a recognized but
 * unsupported volume format is distinguishable from every other failure.
 */
export function diskStateForServiceError(code: string): DiskImageState {
    return code === "UNSUPPORTED_VENDOR" || code === "CAPABILITY_UNAVAILABLE"
        ? DiskImageState.UNSUPPORTED
        : DiskImageState.FAILED;
}

function failure(
    message: string,
    code: string,
    detail: string | null,
    remediation: string | null,
    body: ServiceEnvelope | null
): VendorCall {
    return {
        ok: false,
        message,
        status: statusForServiceError(code),
        code,
        detail,
        remediation,
        body,
    };
}

function fromServiceError(envelope: ServiceEnvelope, fallbackMessage: string): VendorCall {
    const error: ServiceErrorPayload | null | undefined = envelope.error;
    const code = error?.code ?? "INTERNAL";
    const message = envelope.message || error?.message || fallbackMessage;
    return failure(message, code, error?.detail ?? null, error?.remediation ?? null, envelope);
}

function fromThrown(error: unknown, action: string): VendorCall {
    if (axios.isAxiosError(error)) {
        if (!error.response) {
            const networkCode = error.code ?? "";
            if (networkCode === "ECONNABORTED" || networkCode === "ETIMEDOUT") {
                return failure(
                    `The analysis service did not respond in time while trying to ${action}. It may still be probing the recorder.`,
                    SERVICE_TIMEOUT,
                    error.message,
                    "Retry with a longer timeout, or check the service logs.",
                    null
                );
            }
            return failure(
                `The analysis service is unavailable, so it was not possible to ${action}.`,
                SERVICE_UNAVAILABLE,
                error.message,
                "Start the VigiTrace analysis service and try again.",
                null
            );
        }

        const status = error.response.status;
        const data = error.response.data as ServiceEnvelope | { detail?: unknown } | undefined;

        if (status === 422 && data && "detail" in data) {
            return failure(
                `The analysis service rejected the request to ${action} because it was malformed.`,
                "PROTOCOL_ERROR",
                JSON.stringify(data.detail),
                null,
                null
            );
        }
        if (data && typeof data === "object" && "message" in data) {
            return fromServiceError(
                data as ServiceEnvelope,
                `The analysis service failed to ${action}.`
            );
        }
        return failure(
            `The analysis service returned an unexpected ${status} response while trying to ${action}.`,
            "INTERNAL",
            error.message,
            null,
            null
        );
    }

    return failure(
        `An unexpected error occurred while trying to ${action}.`,
        "INTERNAL",
        error instanceof Error ? error.message : String(error),
        null,
        null
    );
}

type PostOptions = {
    timeout?: number;
    /**
     * Some endpoints use `success: false` to report a negative *finding* rather
     * than a failed call. Integrity verification is one: a tampered artifact is
     * a result the server must persist, not an error to swallow. For those, the
     * envelope is handed back intact and the caller decides what it means.
     */
    successFalseIsResult?: boolean;
};

async function post(
    path: string,
    payload: unknown,
    action: string,
    options: PostOptions = {}
): Promise<VendorCall> {
    const timeout = options.timeout ?? MICROSERVICE_TIMEOUT_MS;
    try {
        const response = await microserviceApi.post<ServiceEnvelope>(path, payload, { timeout });
        const envelope = response.data ?? {};
        if (envelope.success === false && !options.successFalseIsResult) {
            return fromServiceError(envelope, `The analysis service could not ${action}.`);
        }
        return { ok: true, message: envelope.message ?? "The analysis service responded.", body: envelope };
    } catch (error) {
        return fromThrown(error, action);
    }
}

/** Read the vendor adapter registry. */
export async function listVendors(): Promise<VendorCall> {
    try {
        const response = await microserviceApi.get<ServiceEnvelope>("/api/devices/vendors", {
            timeout: MICROSERVICE_TIMEOUT_MS,
        });
        const envelope = response.data ?? {};
        if (envelope.success === false) {
            return fromServiceError(envelope, "The analysis service could not list vendor adapters.");
        }
        return {
            ok: true,
            message: envelope.message ?? "Vendor adapters listed.",
            body: envelope,
        };
    } catch (error) {
        return fromThrown(error, "list the supported vendor adapters");
    }
}

/** Fingerprint a recorder without authenticating. */
export async function detectDevice(target: ServiceDeviceTarget): Promise<VendorCall> {
    return post("/api/devices/detect", target, "detect this recorder's vendor");
}

/** Produce the full standardized device object for a recorder. */
export async function identifyDevice(target: ServiceDeviceTarget): Promise<VendorCall> {
    return post("/api/devices/identify", target, "identify this recorder");
}

/** Re-read channel and storage state for a recorder that is already identified. */
export async function enumerateDevice(target: ServiceDeviceTarget): Promise<VendorCall> {
    return post("/api/devices/enumerate", target, "enumerate this recorder's channels and storage");
}

/** Search the recorder's own recording index. */
export async function searchRecordings(request: ServiceRecordingSearchRequest): Promise<VendorCall> {
    return post("/api/recordings/search", request, "search this recorder's recording index");
}

/** Export one segment, hashing it on the way to disk. */
export async function acquireRecording(request: ServiceAcquisitionRequest): Promise<VendorCall> {
    return post("/api/recordings/acquire", request, "acquire this recording", {
        timeout: MICROSERVICE_ACQUIRE_TIMEOUT_MS,
    });
}

/**
 * Produce reviewable findings for an already-identified device.
 *
 * Given a longer budget than the default because the service may additionally
 * wait on an optional LLM narration. Cutting that off would return a 504 and
 * discard findings the service had already computed, which is the opposite of
 * what a degraded enhancement should cost.
 */
export async function analyzeDevice(request: ServiceAnalysisRequest): Promise<VendorCall> {
    return post("/api/analysis/summary", request, "analyse this device", {
        timeout: MICROSERVICE_ANALYSIS_TIMEOUT_MS,
    });
}

/**
 * Re-hash acquired artifacts against the digests recorded at acquisition time.
 *
 * A failed check comes back as HTTP 200 with `success: false`, so the envelope
 * is kept intact: "two artifacts were tampered with" is an answer, not an error.
 */
export async function verifyArtifacts(request: ServiceVerifyRequest): Promise<VendorCall> {
    return post("/api/integrity/verify", request, "verify the stored evidence", {
        successFalseIsResult: true,
    });
}

/**
 * Say which filesystem an on-disk image carries, without running a full
 * analysis.
 *
 * `success: false` here is ambiguous by design in the service's own response:
 * it means either a real failure (the path could not be opened at all, and
 * carries an `error`) or a negative finding (the image is readable but holds
 * no supported recorder filesystem, and carries `data` instead). Only the
 * former is a call failure the generic `post()` helper should reject; the
 * latter is a normal result the caller must still see, so this bypasses that
 * helper and decides for itself.
 */
export async function identifyDiskImage(path: string): Promise<VendorCall> {
    try {
        const response = await microserviceApi.post<ServiceEnvelope>(
            "/api/disk/identify",
            { path },
            { timeout: MICROSERVICE_TIMEOUT_MS }
        );
        const envelope = response.data ?? {};
        if (envelope.success === false && envelope.error) {
            return fromServiceError(envelope, "The analysis service could not identify this image.");
        }
        return {
            ok: true,
            message: envelope.message ?? "The analysis service identified this image.",
            body: envelope,
        };
    } catch (error) {
        return fromThrown(error, "identify the filesystem on this disk image");
    }
}

/**
 * Parse an on-disk volume in place, sweep for unreferenced footage, and
 * optionally carve what is found.
 *
 * Given a much larger budget than the default: this can whole-image-hash and
 * carve a multi-gigabyte volume, and cutting that off would discard evidence
 * the service had already produced.
 */
export async function analyseDiskImage(request: ServiceDiskAnalyseRequest): Promise<VendorCall> {
    return post("/api/disk/analyse", request, "analyse this disk image", {
        timeout: MICROSERVICE_DISK_ANALYSIS_TIMEOUT_MS,
    });
}
