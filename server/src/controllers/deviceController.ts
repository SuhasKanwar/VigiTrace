import type { Request, Response } from "express";
import prisma from "../lib/prisma.js";
import { Prisma } from "../generated/prisma/client.js";
import type { Device } from "../generated/prisma/client.js";
import { DeviceState } from "../generated/prisma/enums.js";
import type { ApiResponse } from "../types/response.js";
import type {
    ServiceAcquisition,
    ServiceDetection,
    ServiceRecordingIndex,
    ServiceStandardizedDevice,
    ServiceVerifyData,
    ServiceVerifyResult,
} from "../types/vendor.js";
import { cacheService } from "../services/cacheService.js";
import {
    acquireRecording,
    analyzeDevice,
    detectDevice,
    enumerateDevice,
    identifyDevice,
    listVendors,
    searchRecordings,
    stateForServiceError,
    verifyArtifacts,
    type VendorCall,
} from "../services/vendorService.js";
import {
    DeviceStateTransitionError,
    recordCustodyEvent,
    transitionDevice,
} from "../services/deviceStateService.js";
import { encryptSecret } from "../utils/crypto.js";
import { toCamelCaseDeep } from "../utils/caseConvert.js";
import { toBigIntOrNull, toSerializable } from "../utils/serialize.js";
import {
    buildDeviceTarget,
    buildRecordingIndexPayload,
    combinedEvidenceDigest,
    isKnownVendor,
    isValidHost,
    MissingCredentialsError,
    parsePort,
    sanitizeDevice,
    toConfidenceEnum,
    toFamilyEnum,
    toKindEnum,
    toVendorEnum,
} from "../utils/device.js";
import { VENDOR_REGISTRY_CACHE_TTL_SECONDS } from "../lib/config.js";

const VENDOR_REGISTRY_CACHE_KEY = "vendors:registry";
const CUSTODY_TAIL_SIZE = 25;

type VendorFailure = Extract<VendorCall, { ok: false }>;

function vendorFailureResponse(res: Response<ApiResponse>, call: VendorFailure) {
    return res.status(call.status).json({
        success: false,
        message: call.message,
        error: {
            code: call.code,
            detail: call.detail,
            remediation: call.remediation,
        },
    });
}

/** Express 5 types a route parameter as string | string[]; a device id is a single value. */
function deviceIdFrom(req: Request): string {
    const value = req.params["id"];
    return typeof value === "string" ? value : "";
}

function unauthorized(res: Response<ApiResponse>) {
    return res.status(401).json({
        success: false,
        message: "Authentication is required to work with devices.",
    });
}

function notFound(res: Response<ApiResponse>) {
    return res.status(404).json({
        success: false,
        message: "That device does not exist, or it does not belong to you.",
    });
}

/** Every device read is scoped to the caller: one user never sees another's recorders. */
async function findOwnedDevice(userId: string, deviceId: string): Promise<Device | null> {
    return prisma.device.findFirst({ where: { id: deviceId, userId } });
}

function transitionFailureResponse(res: Response<ApiResponse>, error: unknown) {
    if (error instanceof DeviceStateTransitionError) {
        return res.status(409).json({
            success: false,
            message: error.message,
            error: { from: error.from, to: error.to },
        });
    }
    return null;
}

/** Move a device into a terminal failure state without masking the original error. */
async function markFailed(
    deviceId: string,
    userId: string,
    code: string,
    detail: string
): Promise<void> {
    try {
        await transitionDevice(deviceId, userId, stateForServiceError(code), detail, "PROBE_FAILED");
    } catch (error) {
        console.error("Could not record the failure state for device", deviceId, error);
    }
}

/**
 * Load a device as ONE complete resource: its channels, storage, latest probe
 * and custody tail live inside the device object rather than beside it, so a
 * consumer models a single thing instead of reassembling five.
 */

/** Parse a service timestamp, tolerating null and unparsable values. */
function toDate(value: string | null | undefined): Date | null {
    if (!value) {
        return null;
    }
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? null : parsed;
}

async function loadDeviceResource(userId: string, deviceId: string) {
    const device = await prisma.device.findFirst({
        where: { id: deviceId, userId },
        include: {
            channels: { orderBy: { channelId: "asc" } },
            storage: { orderBy: { storageId: "asc" } },
            probes: { orderBy: { createdAt: "desc" }, take: 1 },
            custodyEvents: { orderBy: { createdAt: "desc" }, take: CUSTODY_TAIL_SIZE },
            _count: {
                select: { recordings: true, acquisitions: true, probes: true, custodyEvents: true },
            },
        },
    });

    if (!device) {
        return null;
    }

    const { channels, storage, probes, custodyEvents, _count, ...rest } = device;
    return {
        ...sanitizeDevice(rest),
        channels,
        storage,
        // Clock state is grouped rather than left flat: the reading is only
        // meaningful as a set (a device time without the probe time it was
        // compared against says nothing), and consumers render it as one block.
        clock: {
            deviceTime: device.clockDeviceTime,
            deviceTimeRaw: device.clockDeviceTimeRaw,
            timezone: device.timezone,
            ntpEnabled: device.ntpEnabled,
            ntpServers: device.ntpServers,
            probedAt: device.clockProbedAt,
            driftSeconds: device.driftSeconds,
        },
        latestProbe: probes[0] ?? null,
        custody: [...custodyEvents].reverse(),
        channelCount: channels.length,
        counts: _count,
    };
}

type PersistOptions = {
    /**
     * Identification decides what the device IS; enumeration only re-reads what
     * it currently HOLDS. Enumeration therefore refreshes channels, storage and
     * the clock but leaves vendor, model and serial number alone, so a routine
     * storage refresh can never quietly re-attribute a recorder.
     */
    refreshIdentity: boolean;
    startedAt: Date;
    finishedAt: Date;
    evidenceDigest: string;
};

/** Persist a StandardizedDevice: channels and storage upserted, probe appended. */
async function persistStandardizedDevice(
    deviceId: string,
    standardized: ServiceStandardizedDevice,
    options: PersistOptions
): Promise<void> {
    const evidence = standardized.evidence;

    await prisma.$transaction(async (tx) => {
        const identityFields = options.refreshIdentity
            ? {
                  vendor: toVendorEnum(standardized.identity?.vendor),
                  family: toFamilyEnum(standardized.identity?.family),
                  confidence: toConfidenceEnum(standardized.identity?.confidence),
                  kind: toKindEnum(standardized.identity?.kind),
                  modelName: standardized.identity?.model_name ?? null,
                  serialNumber: standardized.identity?.serial_number ?? null,
                  firmwareVersion: standardized.identity?.firmware_version ?? null,
                  hardwareVersion: standardized.identity?.hardware_version ?? null,
                  macAddress:
                      standardized.identity?.mac_address ?? standardized.network?.mac_address ?? null,
              }
            : {};

        await tx.device.update({
            where: { id: deviceId },
            data: {
                ...identityFields,
                driftSeconds: standardized.clock?.drift_seconds ?? null,
                timezone: standardized.clock?.timezone ?? null,
                clockDeviceTime: toDate(standardized.clock?.device_time),
                clockDeviceTimeRaw: standardized.clock?.device_time_raw ?? null,
                clockProbedAt: toDate(standardized.clock?.probed_at),
                ntpEnabled: standardized.clock?.ntp_enabled ?? null,
                ntpServers: standardized.clock?.ntp_servers ?? [],
                lastProbedAt: options.finishedAt,
            },
        });

        for (const channel of standardized.channels ?? []) {
            const values = {
                name: channel.name ?? null,
                enabled: channel.enabled ?? null,
                isAnalog: channel.is_analog ?? null,
                codec: channel.codec ?? null,
                resolution: channel.resolution ?? null,
                trackId: channel.track_id ?? null,
            };
            await tx.deviceChannel.upsert({
                where: { deviceId_channelId: { deviceId, channelId: channel.channel_id } },
                create: { deviceId, channelId: channel.channel_id, ...values },
                update: values,
            });
        }

        for (const disk of standardized.storage ?? []) {
            const values = {
                name: disk.name ?? null,
                kind: disk.kind ?? null,
                status: disk.status ?? null,
                capacityBytes: toBigIntOrNull(disk.capacity_bytes),
                freeBytes: toBigIntOrNull(disk.free_bytes),
                storageProperty: disk.device_property ?? null,
            };
            await tx.deviceStorage.upsert({
                where: { deviceId_storageId: { deviceId, storageId: disk.storage_id } },
                create: { deviceId, storageId: disk.storage_id, ...values },
                update: values,
            });
        }

        await tx.deviceProbe.create({
            data: {
                deviceId,
                method: evidence?.method ?? "UNAUTHENTICATED_FINGERPRINT",
                success: true,
                startedAt: evidence?.started_at ? new Date(evidence.started_at) : options.startedAt,
                finishedAt: evidence?.finished_at
                    ? new Date(evidence.finished_at)
                    : options.finishedAt,
                durationMs:
                    evidence?.duration_ms ??
                    options.finishedAt.getTime() - options.startedAt.getTime(),
                evidenceDigest: options.evidenceDigest,
                endpointsAttempted: evidence?.endpoints_attempted ?? [],
                endpointsSucceeded: evidence?.endpoints_succeeded ?? [],
                warnings: evidence?.warnings ?? [],
                // The verbatim standardized device, kept so analysis can be
                // re-run against the evidence that was actually collected.
                raw: standardized as unknown as Prisma.InputJsonValue,
            },
        });
    });
}

/** Record a probe that never produced a device, so the failure is auditable. */
async function recordFailedProbe(
    deviceId: string,
    startedAt: Date,
    finishedAt: Date,
    code: string,
    message: string
): Promise<void> {
    await prisma.deviceProbe.create({
        data: {
            deviceId,
            method: "UNAUTHENTICATED_FINGERPRINT",
            success: false,
            startedAt,
            finishedAt,
            durationMs: finishedAt.getTime() - startedAt.getTime(),
            endpointsAttempted: [],
            endpointsSucceeded: [],
            warnings: [],
            errorCode: code,
            errorMessage: message,
        },
    });
}

export async function getVendorsHandler(req: Request, res: Response<ApiResponse>) {
    try {
        if (!req.userId) {
            return unauthorized(res);
        }

        const cached = cacheService.get<unknown>(VENDOR_REGISTRY_CACHE_KEY);
        if (cached) {
            return res.status(200).json({
                success: true,
                message: "Supported vendor adapters retrieved successfully.",
                data: cached,
            });
        }

        const call = await listVendors();
        if (!call.ok) {
            return vendorFailureResponse(res, call);
        }

        const payload = toCamelCaseDeep(call.body.data ?? { vendors: [] });
        cacheService.set(VENDOR_REGISTRY_CACHE_KEY, payload, VENDOR_REGISTRY_CACHE_TTL_SECONDS);

        return res.status(200).json({
            success: true,
            message: "Supported vendor adapters retrieved successfully.",
            data: payload,
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while listing the supported vendor adapters.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function createDeviceHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }

        const name = typeof req.body?.name === "string" ? req.body.name.trim() : "";
        const host = typeof req.body?.host === "string" ? req.body.host.trim() : "";
        const username = typeof req.body?.username === "string" ? req.body.username.trim() : "";
        const password = req.body?.password;
        const vendorHintRaw = typeof req.body?.vendorHint === "string" ? req.body.vendorHint.trim() : "";

        if (!name) {
            return res.status(400).json({
                success: false,
                message: "A name is required so this recorder can be identified in the case file.",
            });
        }
        if (!host || !isValidHost(host)) {
            return res.status(400).json({
                success: false,
                message: "A valid host is required: an IP address or a resolvable hostname.",
            });
        }

        const httpPort = req.body?.httpPort === undefined ? 80 : parsePort(req.body.httpPort);
        if (httpPort === null) {
            return res.status(400).json({
                success: false,
                message: "The HTTP port must be a whole number between 1 and 65535.",
            });
        }

        if (req.body?.useHttps !== undefined && typeof req.body.useHttps !== "boolean") {
            return res.status(400).json({
                success: false,
                message: "The useHttps flag must be true or false.",
            });
        }
        const useHttps = req.body?.useHttps === true;

        if (password !== undefined && password !== null && typeof password !== "string") {
            return res.status(400).json({
                success: false,
                message: "The recorder password must be a string.",
            });
        }
        if (username && !password) {
            return res.status(400).json({
                success: false,
                message: "A password is required whenever a username is supplied.",
            });
        }
        if (vendorHintRaw && !isKnownVendor(vendorHintRaw)) {
            return res.status(400).json({
                success: false,
                message: "The vendor hint must be one of HIKVISION, DAHUA, CPPLUS, GODREJ or UNKNOWN.",
            });
        }

        const duplicate = await prisma.device.findFirst({
            where: { userId, host, httpPort },
        });
        if (duplicate) {
            return res.status(409).json({
                success: false,
                message: `You have already registered a device at ${host}:${httpPort}.`,
            });
        }

        const device = await prisma.device.create({
            data: {
                userId,
                name,
                host,
                httpPort,
                useHttps,
                username: username || null,
                password: typeof password === "string" && password ? encryptSecret(password) : null,
                vendorHint: vendorHintRaw ? toVendorEnum(vendorHintRaw) : null,
            },
        });

        await recordCustodyEvent(
            device.id,
            userId,
            "DEVICE_REGISTERED",
            `Registered ${name} at ${host}:${httpPort}.`
        );

        return res.status(201).json({
            success: true,
            message: "Device registered successfully.",
            data: { device: toSerializable(sanitizeDevice(device)) },
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while registering the device.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function listDevicesHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }

        const devices = await prisma.device.findMany({
            where: { userId },
            orderBy: { createdAt: "desc" },
            include: {
                _count: {
                    select: {
                        channels: true,
                        storage: true,
                        recordings: true,
                        acquisitions: true,
                        probes: true,
                        custodyEvents: true,
                    },
                },
            },
        });

        const payload = devices.map(({ _count, ...device }) => ({
            ...sanitizeDevice(device),
            counts: _count,
        }));

        return res.status(200).json({
            success: true,
            message: `Retrieved ${payload.length} device(s).`,
            data: toSerializable({ devices: payload }),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while listing your devices.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function getDeviceHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await loadDeviceResource(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        return res.status(200).json({
            success: true,
            message: "Device retrieved successfully.",
            // The device is returned as one complete resource rather than as
            // sibling collections, so a consumer models a single object.
            data: toSerializable({ device }),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while retrieving the device.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function updateDeviceHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const existing = await findOwnedDevice(userId, deviceId);
        if (!existing) {
            return notFound(res);
        }

        const data: Prisma.DeviceUpdateInput = {};
        const changed: string[] = [];

        if (req.body?.name !== undefined) {
            const name = typeof req.body.name === "string" ? req.body.name.trim() : "";
            if (!name) {
                return res.status(400).json({
                    success: false,
                    message: "The device name cannot be empty.",
                });
            }
            data.name = name;
            changed.push("name");
        }

        if (req.body?.host !== undefined) {
            const host = typeof req.body.host === "string" ? req.body.host.trim() : "";
            if (!isValidHost(host)) {
                return res.status(400).json({
                    success: false,
                    message: "A valid host is required: an IP address or a resolvable hostname.",
                });
            }
            data.host = host;
            changed.push("host");
        }

        if (req.body?.httpPort !== undefined) {
            const httpPort = parsePort(req.body.httpPort);
            if (httpPort === null) {
                return res.status(400).json({
                    success: false,
                    message: "The HTTP port must be a whole number between 1 and 65535.",
                });
            }
            data.httpPort = httpPort;
            changed.push("httpPort");
        }

        if (req.body?.useHttps !== undefined) {
            if (typeof req.body.useHttps !== "boolean") {
                return res.status(400).json({
                    success: false,
                    message: "The useHttps flag must be true or false.",
                });
            }
            data.useHttps = req.body.useHttps;
            changed.push("useHttps");
        }

        if (req.body?.username !== undefined) {
            if (req.body.username !== null && typeof req.body.username !== "string") {
                return res.status(400).json({
                    success: false,
                    message: "The recorder username must be a string, or null to clear it.",
                });
            }
            const username = typeof req.body.username === "string" ? req.body.username.trim() : "";
            data.username = username || null;
            changed.push("username");
        }

        if (req.body?.password !== undefined) {
            if (req.body.password !== null && typeof req.body.password !== "string") {
                return res.status(400).json({
                    success: false,
                    message: "The recorder password must be a string, or null to clear it.",
                });
            }
            data.password = typeof req.body.password === "string" && req.body.password
                ? encryptSecret(req.body.password)
                : null;
            changed.push("password");
        }

        if (req.body?.vendorHint !== undefined) {
            if (req.body.vendorHint === null) {
                data.vendorHint = null;
            } else {
                const hint = typeof req.body.vendorHint === "string" ? req.body.vendorHint.trim() : "";
                if (!hint || !isKnownVendor(hint)) {
                    return res.status(400).json({
                        success: false,
                        message: "The vendor hint must be one of HIKVISION, DAHUA, CPPLUS, GODREJ or UNKNOWN.",
                    });
                }
                data.vendorHint = toVendorEnum(hint);
            }
            changed.push("vendorHint");
        }

        if (changed.length === 0) {
            return res.status(400).json({
                success: false,
                message: "No updatable fields were supplied.",
            });
        }

        const targetHost = typeof data.host === "string" ? data.host : existing.host;
        const targetPort = typeof data.httpPort === "number" ? data.httpPort : existing.httpPort;
        if (targetHost !== existing.host || targetPort !== existing.httpPort) {
            const clash = await prisma.device.findFirst({
                where: { userId, host: targetHost, httpPort: targetPort, NOT: { id: deviceId } },
            });
            if (clash) {
                return res.status(409).json({
                    success: false,
                    message: `You have already registered a device at ${targetHost}:${targetPort}.`,
                });
            }
        }

        const device = await prisma.device.update({ where: { id: deviceId }, data });

        await recordCustodyEvent(
            deviceId,
            userId,
            "DEVICE_UPDATED",
            `Updated ${changed.join(", ")}.`
        );

        return res.status(200).json({
            success: true,
            message: "Device updated successfully.",
            data: { device: toSerializable(sanitizeDevice(device)) },
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while updating the device.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function deleteDeviceHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        await prisma.device.delete({ where: { id: deviceId } });

        return res.status(200).json({
            success: true,
            message: `Device ${device.name} and all of its evidence records were deleted.`,
            data: { id: deviceId },
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while deleting the device.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function detectDeviceHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        const startedAt = new Date();
        const call = await detectDevice(buildDeviceTarget(device));
        const finishedAt = new Date();
        const durationMs = finishedAt.getTime() - startedAt.getTime();

        if (!call.ok) {
            const detection = (call.body?.detection ?? null) as ServiceDetection | null;
            await prisma.deviceProbe.create({
                data: {
                    deviceId,
                    method: detection?.method ?? "UNAUTHENTICATED_FINGERPRINT",
                    success: false,
                    startedAt,
                    finishedAt,
                    durationMs,
                    endpointsAttempted: [],
                    endpointsSucceeded: [],
                    warnings: [],
                    errorCode: call.code,
                    errorMessage: call.detail ?? call.message,
                    raw: (detection ?? Prisma.DbNull) as Prisma.InputJsonValue,
                },
            });
            // Detection is an unauthenticated read, so a failed one is recorded
            // but does not move the device: a momentary outage of the analysis
            // service must not knock an already-IDENTIFIED recorder into FAILED.
            // Identify, search and acquire are what drive the state machine.
            await recordCustodyEvent(
                deviceId,
                userId,
                "DETECTION_FAILED",
                `${call.message} (${call.code})`
            );
            return vendorFailureResponse(res, call);
        }

        const detection = (call.body.detection ?? null) as ServiceDetection | null;

        await prisma.$transaction(async (tx) => {
            await tx.deviceProbe.create({
                data: {
                    deviceId,
                    method: detection?.method ?? "UNAUTHENTICATED_FINGERPRINT",
                    success: true,
                    startedAt,
                    finishedAt,
                    durationMs,
                    endpointsAttempted: [],
                    endpointsSucceeded: [],
                    warnings: detection?.signals ?? [],
                    raw: (detection ?? Prisma.DbNull) as Prisma.InputJsonValue,
                },
            });
            if (detection) {
                await tx.device.update({
                    where: { id: deviceId },
                    data: {
                        vendor: toVendorEnum(detection.vendor),
                        family: toFamilyEnum(detection.family),
                        confidence: toConfidenceEnum(detection.confidence),
                        lastProbedAt: finishedAt,
                    },
                });
            }
        });

        await recordCustodyEvent(
            deviceId,
            userId,
            "DEVICE_DETECTED",
            detection
                ? `Detected ${detection.vendor} (${detection.family}) at ${detection.confidence} confidence.`
                : "Detection completed without a vendor determination."
        );

        return res.status(200).json({
            success: true,
            message: call.message,
            data: toCamelCaseDeep({ detection }),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while detecting the recorder's vendor.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function identifyDeviceHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        let target;
        try {
            target = buildDeviceTarget(device, { requireCredentials: true });
        } catch (error) {
            if (error instanceof MissingCredentialsError) {
                return res.status(400).json({
                    success: false,
                    message: "Add the recorder's username and password before identifying it.",
                });
            }
            throw error;
        }

        try {
            await transitionDevice(deviceId, userId, DeviceState.IDENTIFYING, "Identification started.");
        } catch (error) {
            const conflict = transitionFailureResponse(res, error);
            if (conflict) {
                return conflict;
            }
            throw error;
        }

        const startedAt = new Date();
        const call = await identifyDevice(target);
        const finishedAt = new Date();

        if (!call.ok) {
            await recordFailedProbe(
                deviceId,
                startedAt,
                finishedAt,
                call.code,
                call.detail ?? call.message
            );
            await markFailed(deviceId, userId, call.code, `Identification failed: ${call.message}`);
            return vendorFailureResponse(res, call);
        }

        const standardized = call.body.device as ServiceStandardizedDevice | undefined;
        if (!standardized) {
            await markFailed(deviceId, userId, "PROTOCOL_ERROR", "Identification returned no device.");
            return res.status(502).json({
                success: false,
                message: "The analysis service reported success but returned no device object.",
            });
        }

        const evidence = standardized.evidence;
        const evidenceDigest = combinedEvidenceDigest(evidence?.artifacts ?? []);

        await persistStandardizedDevice(deviceId, standardized, {
            refreshIdentity: true,
            startedAt,
            finishedAt,
            evidenceDigest,
        });

        const updated = await transitionDevice(
            deviceId,
            userId,
            DeviceState.IDENTIFIED,
            `Identified ${standardized.identity?.vendor} ${standardized.identity?.model_name ?? ""}`.trim(),
            "DEVICE_IDENTIFIED"
        );

        const identifiedResource = await loadDeviceResource(userId, deviceId);

        return res.status(200).json({
            success: true,
            message: call.message,
            data: toSerializable({
                // The complete resource, matching getDeviceHandler and enumerate:
                // the client renders this response directly, so a bare device
                // would blank the channel and storage tables it just populated.
                device: identifiedResource ?? sanitizeDevice(updated),
                evidenceDigest,
                identification: toCamelCaseDeep({
                    identity: standardized.identity,
                    network: standardized.network,
                    clock: standardized.clock,
                    capabilities: standardized.capabilities,
                    channels: standardized.channels,
                    storage: standardized.storage,
                    warnings: evidence?.warnings ?? [],
                }),
                detection: toCamelCaseDeep(call.body.detection ?? null),
            }),
        });
    } catch (error) {
        const conflict = transitionFailureResponse(res, error);
        if (conflict) {
            return conflict;
        }
        return res.status(500).json({
            success: false,
            message: "An error occurred while identifying the recorder.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function enumerateDeviceHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        // Enumeration refreshes what a known recorder holds. On a device that has
        // never been identified there is no known channel or disk layout to
        // refresh, so this is a meaningless request rather than a failed one.
        if (device.state === DeviceState.REGISTERED) {
            return res.status(409).json({
                success: false,
                message:
                    "Identify this device before enumerating it; its channels and storage are unknown until identification has run.",
                error: { from: device.state, to: DeviceState.ENUMERATING },
            });
        }

        let target;
        try {
            target = buildDeviceTarget(device, { requireCredentials: true });
        } catch (error) {
            if (error instanceof MissingCredentialsError) {
                return res.status(400).json({
                    success: false,
                    message: "Add the recorder's username and password before enumerating it.",
                });
            }
            throw error;
        }

        try {
            await transitionDevice(
                deviceId,
                userId,
                DeviceState.ENUMERATING,
                "Channel and storage enumeration started."
            );
        } catch (error) {
            const conflict = transitionFailureResponse(res, error);
            if (conflict) {
                return conflict;
            }
            throw error;
        }

        const startedAt = new Date();
        const call = await enumerateDevice(target);
        const finishedAt = new Date();

        if (!call.ok) {
            await recordFailedProbe(
                deviceId,
                startedAt,
                finishedAt,
                call.code,
                call.detail ?? call.message
            );
            await markFailed(deviceId, userId, call.code, `Enumeration failed: ${call.message}`);
            return vendorFailureResponse(res, call);
        }

        const standardized = call.body.device as ServiceStandardizedDevice | undefined;
        if (!standardized) {
            await markFailed(deviceId, userId, "PROTOCOL_ERROR", "Enumeration returned no device.");
            return res.status(502).json({
                success: false,
                message: "The analysis service reported success but returned no device object.",
            });
        }

        const evidenceDigest = combinedEvidenceDigest(standardized.evidence?.artifacts ?? []);
        await persistStandardizedDevice(deviceId, standardized, {
            refreshIdentity: false,
            startedAt,
            finishedAt,
            evidenceDigest,
        });

        const channelCount = (standardized.channels ?? []).length;
        const diskCount = (standardized.storage ?? []).length;

        await transitionDevice(
            deviceId,
            userId,
            DeviceState.ENUMERATED,
            `Enumerated ${channelCount} channel(s) and ${diskCount} storage device(s).`,
            "DEVICE_ENUMERATED"
        );

        const resource = await loadDeviceResource(userId, deviceId);
        return res.status(200).json({
            success: true,
            message: `Refreshed ${channelCount} channel(s) and ${diskCount} storage device(s) for this recorder.`,
            data: toSerializable({ device: resource, evidenceDigest }),
        });
    } catch (error) {
        const conflict = transitionFailureResponse(res, error);
        if (conflict) {
            return conflict;
        }
        return res.status(500).json({
            success: false,
            message: "An error occurred while enumerating the recorder's channels and storage.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function searchRecordingsHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        const start = new Date(req.body?.start);
        const end = new Date(req.body?.end);
        if (Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
            return res.status(400).json({
                success: false,
                message: "A start and end time are required, both as ISO-8601 timestamps.",
            });
        }
        if (end <= start) {
            return res.status(400).json({
                success: false,
                message: "The end time must be later than the start time.",
            });
        }

        const channelIdsRaw = req.body?.channelIds;
        if (channelIdsRaw !== undefined && !Array.isArray(channelIdsRaw)) {
            return res.status(400).json({
                success: false,
                message: "The channelIds field must be an array of channel identifiers.",
            });
        }
        const channelIds: string[] = Array.isArray(channelIdsRaw)
            ? channelIdsRaw.map((value: unknown) => String(value).trim()).filter(Boolean)
            : [];

        const maxResults = req.body?.maxResults === undefined ? 200 : Number(req.body.maxResults);
        if (!Number.isInteger(maxResults) || maxResults < 1 || maxResults > 5000) {
            return res.status(400).json({
                success: false,
                message: "The maxResults field must be a whole number between 1 and 5000.",
            });
        }

        let target;
        try {
            target = buildDeviceTarget(device, { requireCredentials: true });
        } catch (error) {
            if (error instanceof MissingCredentialsError) {
                return res.status(400).json({
                    success: false,
                    message: "Add the recorder's username and password before searching its index.",
                });
            }
            throw error;
        }

        try {
            await transitionDevice(deviceId, userId, DeviceState.INDEXING, "Recording index search started.");
        } catch (error) {
            const conflict = transitionFailureResponse(res, error);
            if (conflict) {
                return conflict;
            }
            throw error;
        }

        const call = await searchRecordings({
            target,
            channel_ids: channelIds,
            start: start.toISOString(),
            end: end.toISOString(),
            max_results: maxResults,
        });

        if (!call.ok) {
            await markFailed(deviceId, userId, call.code, `Recording search failed: ${call.message}`);
            return vendorFailureResponse(res, call);
        }

        const index = (call.body.index ?? null) as ServiceRecordingIndex | null;
        const recordings = index?.recordings ?? [];

        await prisma.$transaction(async (tx) => {
            for (const recording of recordings) {
                const values = {
                    channelId: recording.channel_id,
                    trackId: recording.track_id ?? null,
                    startTime: new Date(recording.span.start),
                    endTime: new Date(recording.span.end),
                    codec: recording.codec ?? null,
                    sizeBytes: toBigIntOrNull(recording.size_bytes),
                    playbackUri: recording.playback_uri ?? null,
                    filePath: recording.file_path ?? null,
                    eventType: recording.event_type ?? null,
                    recordTrigger: recording.record_trigger ?? null,
                    overwriteCount: recording.overwrite_count ?? null,
                    raw: recording as unknown as Prisma.InputJsonValue,
                };
                await tx.recording.upsert({
                    where: {
                        deviceId_recordingId: { deviceId, recordingId: recording.recording_id },
                    },
                    create: { deviceId, recordingId: recording.recording_id, ...values },
                    update: values,
                });
            }
        });

        await transitionDevice(
            deviceId,
            userId,
            DeviceState.INDEXED,
            `Indexed ${recordings.length} segment(s) between ${start.toISOString()} and ${end.toISOString()}.`,
            "RECORDINGS_INDEXED"
        );

        const persisted = await prisma.recording.count({ where: { deviceId } });

        return res.status(200).json({
            success: true,
            message: `${call.message} ${recordings.length} segment(s) were stored against this device.`,
            data: toSerializable({
                index: toCamelCaseDeep(index),
                persistedCount: recordings.length,
                totalStored: persisted,
            }),
        });
    } catch (error) {
        const conflict = transitionFailureResponse(res, error);
        if (conflict) {
            return conflict;
        }
        return res.status(500).json({
            success: false,
            message: "An error occurred while searching the recorder's index.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function listRecordingsHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        const channelId = typeof req.query["channelId"] === "string" ? req.query["channelId"] : undefined;
        const limitRaw = Number(req.query["limit"] ?? 200);
        const limit = Number.isInteger(limitRaw) && limitRaw > 0 && limitRaw <= 1000 ? limitRaw : 200;
        const offsetRaw = Number(req.query["offset"] ?? 0);
        const offset = Number.isInteger(offsetRaw) && offsetRaw >= 0 ? offsetRaw : 0;

        const where: Prisma.RecordingWhereInput = { deviceId };
        if (channelId) {
            where.channelId = channelId;
        }

        const [recordings, total] = await Promise.all([
            prisma.recording.findMany({
                where,
                orderBy: { startTime: "asc" },
                take: limit,
                skip: offset,
            }),
            prisma.recording.count({ where }),
        ]);

        return res.status(200).json({
            success: true,
            message: `Retrieved ${recordings.length} of ${total} indexed recording(s).`,
            data: toSerializable({ recordings, total, limit, offset }),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while listing the indexed recordings.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function createAcquisitionHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        const recordingId = typeof req.body?.recordingId === "string" ? req.body.recordingId.trim() : "";
        if (!recordingId) {
            return res.status(400).json({
                success: false,
                message: "A recordingId is required to acquire a segment.",
            });
        }

        const stored = await prisma.recording.findFirst({ where: { deviceId, recordingId } });

        const channelId =
            typeof req.body?.channelId === "string" && req.body.channelId.trim()
                ? req.body.channelId.trim()
                : stored?.channelId;
        const start = req.body?.start ? new Date(req.body.start) : stored?.startTime;
        const end = req.body?.end ? new Date(req.body.end) : stored?.endTime;

        if (!channelId || !start || !end || Number.isNaN(start.getTime()) || Number.isNaN(end.getTime())) {
            return res.status(400).json({
                success: false,
                message:
                    "That recording is not in this device's index, so a channelId, start and end must be supplied explicitly.",
            });
        }
        if (end <= start) {
            return res.status(400).json({
                success: false,
                message: "The end time must be later than the start time.",
            });
        }

        const playbackUri =
            typeof req.body?.playbackUri === "string" && req.body.playbackUri.trim()
                ? req.body.playbackUri.trim()
                : stored?.playbackUri ?? null;
        const filePath =
            typeof req.body?.filePath === "string" && req.body.filePath.trim()
                ? req.body.filePath.trim()
                : stored?.filePath ?? null;

        let target;
        try {
            target = buildDeviceTarget(device, { requireCredentials: true });
        } catch (error) {
            if (error instanceof MissingCredentialsError) {
                return res.status(400).json({
                    success: false,
                    message: "Add the recorder's username and password before acquiring evidence from it.",
                });
            }
            throw error;
        }

        try {
            await transitionDevice(
                deviceId,
                userId,
                DeviceState.ACQUIRING,
                `Acquisition of ${recordingId} on channel ${channelId} started.`
            );
        } catch (error) {
            const conflict = transitionFailureResponse(res, error);
            if (conflict) {
                return conflict;
            }
            throw error;
        }

        const call = await acquireRecording({
            target,
            recording_id: recordingId,
            channel_id: channelId,
            start: start.toISOString(),
            end: end.toISOString(),
            playback_uri: playbackUri,
            file_path: filePath,
        });

        if (!call.ok) {
            await markFailed(deviceId, userId, call.code, `Acquisition failed: ${call.message}`);
            return vendorFailureResponse(res, call);
        }

        const result = call.body.acquisition as ServiceAcquisition | undefined;
        if (!result) {
            await markFailed(deviceId, userId, "PROTOCOL_ERROR", "Acquisition returned no result.");
            return res.status(502).json({
                success: false,
                message: "The analysis service reported success but returned no acquisition result.",
            });
        }

        const acquisition = await prisma.acquisition.create({
            data: {
                deviceId,
                recordingId: result.recording_id,
                channelId: result.channel_id,
                storedPath: result.stored_path,
                sizeBytes: toBigIntOrNull(result.size_bytes) ?? BigInt(0),
                md5: result.md5,
                sha256: result.sha256,
                container: result.container ?? null,
                acquiredAt: new Date(result.acquired_at),
                durationMs: result.duration_ms,
                sourceUri: result.source_uri ?? null,
                verified: Boolean(result.md5 && result.sha256),
            },
        });

        await transitionDevice(
            deviceId,
            userId,
            DeviceState.ACQUIRED,
            `Acquired ${result.size_bytes} bytes for ${result.recording_id} (sha256 ${result.sha256}).`,
            "RECORDING_ACQUIRED"
        );

        return res.status(201).json({
            success: true,
            message: call.message,
            data: toSerializable({
                acquisition,
                warnings: result.warnings ?? [],
            }),
        });
    } catch (error) {
        const conflict = transitionFailureResponse(res, error);
        if (conflict) {
            return conflict;
        }
        return res.status(500).json({
            success: false,
            message: "An error occurred while acquiring the recording.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function listAcquisitionsHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        const acquisitions = await prisma.acquisition.findMany({
            where: { deviceId },
            orderBy: { acquiredAt: "desc" },
        });

        return res.status(200).json({
            success: true,
            message: `Retrieved ${acquisitions.length} acquisition(s).`,
            data: toSerializable({ acquisitions }),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while listing the acquisitions.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function verifyDeviceHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        const acquisitions = await prisma.acquisition.findMany({
            where: { deviceId },
            orderBy: { acquiredAt: "asc" },
        });

        // Verifying nothing would report a pass, which is worse than refusing:
        // a device that has never been acquired from has nothing to attest to.
        if (acquisitions.length === 0) {
            return res.status(409).json({
                success: false,
                message:
                    "There is nothing to verify: no evidence has been acquired from this device yet. Acquire a recording first.",
            });
        }

        try {
            await transitionDevice(
                deviceId,
                userId,
                DeviceState.VERIFYING,
                `Integrity verification of ${acquisitions.length} artifact(s) started.`
            );
        } catch (error) {
            const conflict = transitionFailureResponse(res, error);
            if (conflict) {
                return conflict;
            }
            throw error;
        }

        const call = await verifyArtifacts({
            artifacts: acquisitions.map((acquisition) => ({
                recording_id: acquisition.recordingId,
                stored_path: acquisition.storedPath,
                expected_sha256: acquisition.sha256,
            })),
        });

        if (!call.ok) {
            await markFailed(deviceId, userId, call.code, `Verification failed: ${call.message}`);
            return vendorFailureResponse(res, call);
        }

        const data = (call.body.data ?? { results: [], verified: 0, failed: 0 }) as ServiceVerifyData;
        const results = data.results ?? [];

        // Results are matched on stored path, not recording id: the same
        // recording can be acquired more than once, and each export is its own
        // artifact with its own digest.
        const byPath = new Map<string, ServiceVerifyResult>();
        for (const result of results) {
            byPath.set(result.path, result);
        }

        await prisma.$transaction(async (tx) => {
            for (const acquisition of acquisitions) {
                const result = byPath.get(acquisition.storedPath);
                await tx.acquisition.update({
                    where: { id: acquisition.id },
                    data: { verified: result?.verified === true },
                });
            }
        });

        const failed = results.filter((result) => !result.verified).length;
        const verified = results.length - failed;

        if (failed > 0) {
            await transitionDevice(
                deviceId,
                userId,
                DeviceState.FAILED,
                `${failed} of ${results.length} artifact(s) failed integrity verification: ${results
                    .filter((result) => !result.verified)
                    .map((result) => `${result.recording_id} (${result.reason ?? "digest mismatch"})`)
                    .join("; ")}`,
                "INTEGRITY_CHECK_FAILED"
            );

            const resource = await loadDeviceResource(userId, deviceId);
            // A tampered artifact is an answer, not a server error: HTTP 200
            // carrying success:false, so the finding reaches the investigator
            // as a finding rather than as a failed request.
            return res.status(200).json({
                success: false,
                message: `${failed} of ${results.length} acquired artifact(s) failed integrity verification. This device has been marked FAILED and its evidence must not be relied on.`,
                data: toSerializable({
                    device: resource,
                    verification: toCamelCaseDeep({ results, verified, failed }),
                }),
            });
        }

        await transitionDevice(
            deviceId,
            userId,
            DeviceState.VERIFIED,
            `All ${verified} acquired artifact(s) matched their recorded SHA-256 digests.`,
            "EVIDENCE_VERIFIED"
        );

        const resource = await loadDeviceResource(userId, deviceId);
        return res.status(200).json({
            success: true,
            message: `All ${verified} acquired artifact(s) still match the digests recorded at acquisition time.`,
            data: toSerializable({
                device: resource,
                verification: toCamelCaseDeep({ results, verified, failed }),
            }),
        });
    } catch (error) {
        const conflict = transitionFailureResponse(res, error);
        if (conflict) {
            return conflict;
        }
        return res.status(500).json({
            success: false,
            message: "An error occurred while verifying this device's acquired evidence.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function getCustodyHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        const events = await prisma.custodyEvent.findMany({
            where: { deviceId },
            orderBy: { createdAt: "asc" },
        });

        return res.status(200).json({
            success: true,
            message: `Retrieved ${events.length} chain-of-custody entr${events.length === 1 ? "y" : "ies"}.`,
            data: toSerializable({ events, currentState: device.state }),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while retrieving the chain of custody.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}

export async function analyzeDeviceHandler(req: Request, res: Response<ApiResponse>) {
    try {
        const userId = req.userId;
        if (!userId) {
            return unauthorized(res);
        }
        const deviceId = deviceIdFrom(req);

        const device = await findOwnedDevice(userId, deviceId);
        if (!device) {
            return notFound(res);
        }

        if (req.body?.narrate !== undefined && typeof req.body.narrate !== "boolean") {
            return res.status(400).json({
                success: false,
                message: "The narrate flag must be true or false.",
            });
        }
        const narrate = req.body?.narrate !== false;
        const includeIndex = req.body?.includeIndex !== false;

        const probes = await prisma.deviceProbe.findMany({
            where: { deviceId, success: true },
            orderBy: { createdAt: "desc" },
            take: 20,
        });

        const standardized = probes
            .map((probe) => probe.raw as unknown)
            .find(
                (raw): raw is ServiceStandardizedDevice =>
                    raw !== null &&
                    typeof raw === "object" &&
                    "identity" in (raw as Record<string, unknown>) &&
                    "evidence" in (raw as Record<string, unknown>)
            );

        if (!standardized) {
            return res.status(409).json({
                success: false,
                message: "Identify this device before requesting analysis; there is no stored evidence to analyse.",
            });
        }

        const rows = includeIndex
            ? await prisma.recording.findMany({
                  where: { deviceId },
                  orderBy: { startTime: "asc" },
              })
            : [];

        const call = await analyzeDevice({
            device: standardized,
            index: rows.length > 0 ? buildRecordingIndexPayload(rows) : null,
            narrate,
        });

        if (!call.ok) {
            return vendorFailureResponse(res, call);
        }

        await recordCustodyEvent(
            deviceId,
            userId,
            "ANALYSIS_REQUESTED",
            `Analysis run over ${rows.length} indexed segment(s).`
        );

        return res.status(200).json({
            success: true,
            message: call.message,
            data: toSerializable(toCamelCaseDeep(call.body.data ?? {})),
        });
    } catch (error) {
        return res.status(500).json({
            success: false,
            message: "An error occurred while analysing the device.",
            error: error instanceof Error ? error.message : String(error),
        });
    }
}
